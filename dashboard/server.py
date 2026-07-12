"""
v5 Dashboard server (FastAPI + uvicorn).

Two tailored views from the same data:
  /pi  -> compact kiosk for the Raspberry Pi touchscreen
  /    -> mobile-optimised view for your phone on the same Wi-Fi

Security posture (home-LAN personal tool):
 * READ endpoints (status/decisions, the pages) are open on the LAN unless you
   set MINISIM_DASH_TOKEN, in which case they require it too.
 * STATE-CHANGING endpoints (/api/kill, /api/resume) are protected by THREE
   layers so a malicious website a LAN device visits cannot stop/restart your
   trading:
     1. a per-process CSRF token, embedded in the served page (same-origin only),
     2. an Origin/Referer check (blocks classic cross-site POSTs),
     3. a Host allow-list (blocks DNS-rebinding attacks).
 * The CSRF token is injected into the page automatically, so the phone/Pi UI
   works with no configuration. Set MINISIM_DASH_TOKEN for an extra shared
   secret if you want belt-and-braces.

Run:  python -m dashboard.server
"""
import os, secrets as _secrets, time as _time
from urllib.parse import urlparse
from config import config
from common import read_json, read_jsonl
from operations import kill_switch

_candle_cache: dict = {}   # (symbol, limit) -> (fetched_at, data)

try:
    from fastapi import FastAPI, Request, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse
except ImportError:
    FastAPI = None

HERE = os.path.dirname(os.path.abspath(__file__))
CSRF_TOKEN = _secrets.token_urlsafe(24)        # fresh each process start


def _allowed_hosts():
    hosts = {"localhost", "127.0.0.1", "::1"}
    # the Pi's own hostnames/IPs
    try:
        import socket
        hn = socket.gethostname()
        hosts.add(hn); hosts.add(f"{hn}.local")
        hosts.add(socket.gethostbyname(hn))
        # reliable primary LAN IP (the address your phone actually connects to)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            hosts.add(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        pass
    extra = os.environ.get("MINISIM_DASH_HOSTS", "")
    hosts.update(h.strip() for h in extra.split(",") if h.strip())
    return hosts


ALLOWED_HOSTS = _allowed_hosts()


def _host_only(value):
    if not value:
        return ""
    if "://" not in value:
        value = "//" + value
    return (urlparse(value).hostname or "").lower()


def _require_read(request):
    if config.DASHBOARD_TOKEN:
        sent = request.headers.get("x-auth-token") or request.query_params.get("token")
        if not sent or not _secrets.compare_digest(sent, config.DASHBOARD_TOKEN):
            raise HTTPException(status_code=401, detail="auth required")


def _require_write(request):
    _require_read(request)
    # 1) Host allow-list (anti DNS-rebinding)
    host = _host_only(request.headers.get("host", ""))
    if host and host not in ALLOWED_HOSTS:
        raise HTTPException(status_code=403, detail="host not allowed")
    # 2) Origin / Referer must match host (anti-CSRF)
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin and _host_only(origin) not in ALLOWED_HOSTS and _host_only(origin) != host:
        raise HTTPException(status_code=403, detail="bad origin")
    # 3) CSRF token from the page
    if not _secrets.compare_digest(request.headers.get("x-csrf-token", ""), CSRF_TOKEN):
        raise HTTPException(status_code=403, detail="bad csrf token")


def _page(name):
    with open(os.path.join(HERE, name, "index.html")) as f:
        html = f.read()
    return html.replace("__CSRF__", CSRF_TOKEN)


def build_app():
    app = FastAPI(title="MiniSim Dashboard")

    @app.get("/", response_class=HTMLResponse)
    def mobile():
        return _page("mobile")

    @app.get("/pi", response_class=HTMLResponse)
    def pi():
        return _page("pi")

    @app.get("/api/status")
    def status(request: Request):
        _require_read(request)
        st = read_json(config.STATUS_FILE, {})
        st["version"]    = config.VERSION   # always reflect live config, not cached file
        st["mode"]       = config.MODE
        st["kill_switch"] = kill_switch.is_active()
        return JSONResponse(st)

    @app.get("/api/decisions")
    def decisions(request: Request, limit: int = 20):
        _require_read(request)
        return JSONResponse(read_jsonl(config.DECISION_LOG, limit=limit)[::-1])

    @app.get("/api/performance")
    def performance(request: Request, limit: int = 50):
        _require_read(request)
        from records.performance import recent_closed_trades, overall_stats
        trades = recent_closed_trades(limit)
        stats = overall_stats(trades)
        stats["recent"] = trades[-20:][::-1]
        return JSONResponse(stats)

    @app.get("/api/equity_history")
    def equity_history(request: Request):
        _require_read(request)
        return JSONResponse(read_json(config.EQUITY_HISTORY_FILE, []))

    @app.get("/api/prices")
    def prices(request: Request):
        _require_read(request)
        from mcp_servers._marketdata_core import get_ticker
        result = {}
        for coin in config.TRACKED_COINS:
            try:
                result[coin] = get_ticker(coin)["price"]
            except Exception:
                result[coin] = None
        return JSONResponse(result)

    @app.get("/api/candles")
    def candles(request: Request, coin: str = "BTC", limit: int = 60):
        _require_read(request)
        import httpx
        symbol = f"{coin.upper()}USDT"
        key = (symbol, limit)
        now = _time.time()
        if key in _candle_cache and now - _candle_cache[key][0] < 60:
            return JSONResponse(_candle_cache[key][1])
        resp = httpx.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": config.CANDLE_INTERVAL, "limit": limit},
            timeout=10.0,
        )
        resp.raise_for_status()
        # kline row: [openTime, open, high, low, close, volume, ...]
        data = {
            "coin": coin.upper(),
            "interval": config.CANDLE_INTERVAL,
            "candles": [
                [float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
                for k in resp.json()
            ],
        }
        _candle_cache[key] = (now, data)
        return JSONResponse(data)

    @app.get("/api/strategy_state")
    def strategy_state(request: Request):
        _require_read(request)
        import os as _os
        data_path = _os.path.join(_os.path.dirname(HERE), "data", "strategy_state.json")
        state = read_json(data_path, {})
        try:
            from strategies import REGISTRY
            catalogue = {name: inst.to_dict() for name, inst in REGISTRY.items()}
        except Exception:
            catalogue = {}
        return JSONResponse({"state": state, "catalogue": catalogue})

    @app.get("/api/macro")
    def macro_data(request: Request):
        _require_read(request)
        from mcp_servers import _macro_core as _macro
        fng     = _macro.get_fear_greed()
        funding = _macro.get_funding_rates()
        dom     = _macro.get_dominance()
        oi      = _macro.get_open_interest()
        ls      = _macro.get_long_short_ratio()
        tf      = _macro.get_tradfi()
        vals    = list(funding.values())
        avg_pct = round(sum(vals) / len(vals) * 100, 4) if vals else 0.0
        bias    = ("long_crowded" if avg_pct > 0.05
                   else "short_crowded" if avg_pct < -0.03
                   else "neutral")
        return JSONResponse({
            "fear_greed":        fng,
            "funding_rates":     funding,
            "avg_funding_pct":   avg_pct,
            "funding_bias":      bias,
            "dominance":         dom,
            "open_interest":     oi,
            "long_short_ratio":  ls,
            "tradfi":            tf,
        })

    @app.get("/macro", response_class=HTMLResponse)
    def macro_page():
        return _page("macro")

    @app.get("/report", response_class=HTMLResponse)
    def report():
        return _page("report")

    @app.get("/api/daily_report")
    def daily_report(request: Request, date: str = ""):
        import datetime as _dt, json as _json, re
        _require_read(request)

        try:
            target = _dt.date.fromisoformat(date) if date else _dt.datetime.utcnow().date()
        except ValueError:
            target = _dt.datetime.utcnow().date()

        date_str = target.isoformat()
        prev_str = (target - _dt.timedelta(days=1)).isoformat()
        next_str = (target + _dt.timedelta(days=1)).isoformat()

        entries, exits, sd_by_coin = [], [], {}
        # near_miss_map: coin -> {best: record, count: int}
        nm_map: dict = {}

        try:
            with open(config.DECISION_LOG) as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        d = _json.loads(raw)
                    except Exception:
                        continue
                    if not d.get("timestamp", "").startswith(date_str):
                        continue
                    action = d.get("action", "")
                    coin   = d.get("coin", "")
                    if action in ("ENTRY_BUY", "ENTRY_SELL"):
                        entries.append(d)
                    elif action == "EXIT":
                        exits.append(d)
                    elif action == "STAND_DOWN":
                        sd_by_coin[coin] = sd_by_coin.get(coin, 0) + 1
                        conf = d.get("confidence", 0)
                        if conf >= 0.45:
                            if coin not in nm_map or conf > nm_map[coin]["best"]["confidence"]:
                                nm_map[coin] = {"best": d, "count": nm_map.get(coin, {}).get("count", 0) + 1}
                            else:
                                nm_map[coin]["count"] += 1
        except FileNotFoundError:
            pass

        # Near misses — one per coin, sorted by confidence, with repeat count
        near_misses = sorted(
            [{**v["best"], "nm_count": v["count"]} for v in nm_map.values()],
            key=lambda d: -d["confidence"],
        )

        # Realized P&L for this day from the tax ledger
        realized_usd = 0.0
        wins_today = losses_today = 0
        try:
            from records.performance import _match_trades
            fills = []
            with open(config.TAX_LEDGER) as fh:
                for raw in fh:
                    raw = raw.strip()
                    if raw:
                        try: fills.append(_json.loads(raw))
                        except: pass
            closed_today = [t for t in _match_trades(fills)
                            if t.get("sell_ts", "").startswith(date_str)]
            for t in closed_today:
                realized_usd += t["qty"] * t["open_price"] * t["pnl_pct"] / 100
                if t["pnl_pct"] > 0: wins_today += 1
                else: losses_today += 1
            realized_usd = round(realized_usd, 2)
        except Exception:
            pass

        # Equity delta
        eq_hist   = read_json(config.EQUITY_HISTORY_FILE, [])
        day_start = _dt.datetime.fromisoformat(date_str + "T00:00:00+00:00").timestamp()
        day_end   = day_start + 86400
        day_pts   = [p for p in eq_hist if day_start <= p["ts"] < day_end]
        eq_start  = day_pts[0]["equity"]  if day_pts else None
        eq_end    = day_pts[-1]["equity"] if day_pts else None
        status    = read_json(config.STATUS_FILE, {})
        if date_str == _dt.datetime.utcnow().date().isoformat():
            eq_end = status.get("equity_usd", eq_end)
        eq_delta = eq_pct = None
        if eq_start and eq_end:
            eq_delta = round(eq_end - eq_start, 2)
            eq_pct   = round(eq_delta / eq_start * 100, 2)

        def _parse_exit(reasoning):
            r = reasoning or ""
            for tp, label in [("T1", "TP1"), ("T2", "TP2"), ("T3", "TP3")]:
                if f"take-profit {tp}" in r or tp in r:
                    m = re.search(r'at ([\d.]+)%', r)
                    return {"label": f"{label} +{m.group(1)}%" if m else label, "outcome": "profit"}
            if "trailing stop" in r.lower():
                return {"label": "Trailing stop", "outcome": "profit"}
            if "stop loss" in r.lower():
                m = re.search(r'\(([-+]?[\d.]+)%\)', r)
                return {"label": f"SL {m.group(1)}%" if m else "Stop loss", "outcome": "loss"}
            if "max hold" in r.lower():
                return {"label": "Timeout", "outcome": "neutral"}
            return {"label": r[:50], "outcome": "neutral"}

        exits_out = [{**e, **_parse_exit(e.get("reasoning", ""))} for e in exits]

        return JSONResponse({
            "date": date_str, "prev_date": prev_str, "next_date": next_str,
            "equity_start": eq_start, "equity_end": eq_end,
            "equity_delta": eq_delta, "equity_delta_pct": eq_pct,
            "realized_usd": realized_usd,
            "wins_today": wins_today, "losses_today": losses_today,
            "regime": status.get("regime", "unknown"),
            "open_positions": status.get("positions", []),
            "entries": entries,
            "exits": exits_out,
            "near_misses": near_misses,
            "stand_down_total": sum(sd_by_coin.values()),
            "stand_down_by_coin": dict(
                sorted(sd_by_coin.items(), key=lambda x: -x[1])[:10]
            ),
        })

    @app.post("/api/kill")
    def kill(request: Request):
        _require_write(request)
        kill_switch.activate("activated via dashboard")
        return {"kill_switch": True}

    @app.post("/api/resume")
    def resume(request: Request):
        _require_write(request)
        kill_switch.deactivate()
        return {"kill_switch": False}

    @app.post("/api/wm/minimize")
    def wm_minimize(request: Request):
        """Minimize the Pi kiosk window via Wayland (Alt+F9 = labwc iconify)."""
        import subprocess
        env = {**os.environ,
               "WAYLAND_DISPLAY": "wayland-0",
               "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
        subprocess.Popen(
            ["wtype", "-M", "alt", "-k", "F9", "-m", "alt"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return {"ok": True}

    return app


def main():
    import uvicorn
    app = build_app()
    print(f"Dashboard: http://{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}  (phone)"
          f"   |   /pi  (Pi screen)")
    print(f"Allowed hosts for control actions: {sorted(ALLOWED_HOSTS)}")
    uvicorn.run(app, host=config.DASHBOARD_HOST, port=config.DASHBOARD_PORT, log_level="warning")


if __name__ == "__main__":
    main()
