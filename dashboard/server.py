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
    app = FastAPI(title="MiniSim v5 Dashboard")

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
        st.setdefault("mode", config.MODE)
        st.setdefault("version", config.VERSION)
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
