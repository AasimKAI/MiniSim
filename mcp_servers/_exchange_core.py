"""Exchange core.

Paper mode: a self-contained simulator with a persistent wallet. All wallet
mutations are guarded by an OS-level file lock so concurrent callers (the exit
loop and the think-cycle) can never corrupt state via interleaved
read-modify-write (fixes the writer race).

Take-profit progress and the trailing-stop peak are stored in a SEPARATE sidecar
file (position_meta.json), keyed by coin, so exit tracking works identically
whether balances come from the paper wallet or a real exchange.

testnet/live route order placement through ccxt; real balances/positions are
implemented in this module's _ccxt_* helpers (see exchange safety task).
"""
import os, time, uuid, json, threading
from contextlib import contextmanager
from config import config
from common import read_json, atomic_write_json

_ex_lock        = threading.Lock()
_spot_ex_cache  = None
_fut_ex_cache   = None
_leverage_done: set = set()   # futures symbols already initialised this process

_WALLET = os.path.join(config.STATE_DIR, "paper_wallet.json")
_META = os.path.join(config.STATE_DIR, "position_meta.json")
_LOCK = os.path.join(config.STATE_DIR, "wallet.lock")


@contextmanager
def _wallet_lock():
    """Cross-process exclusive lock around wallet/meta mutations (Linux/Pi)."""
    os.makedirs(config.STATE_DIR, exist_ok=True)
    f = open(_LOCK, "w")
    try:
        try:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass  # non-POSIX dev box: degrade to no-op (single process anyway)
        yield
    finally:
        try:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        f.close()


def _load():
    return read_json(_WALLET, {"cash_usd": 10000.0, "positions": {}, "shorts": {}, "fills": []})

def _save(w):
    atomic_write_json(_WALLET, w)


# ---------- position metadata (TP progress + trailing peak) ----------
def _load_meta():
    return read_json(_META, {})

def position_meta():
    return _load_meta()

def update_meta(coin, peak_pnl=None, add_target=None):
    with _wallet_lock():
        m = _load_meta()
        cur = m.get(coin, {"peak_pnl": None, "targets_taken": []})
        if peak_pnl is not None:
            cur["peak_pnl"] = (peak_pnl if cur["peak_pnl"] is None
                               else max(cur["peak_pnl"], peak_pnl))
        if add_target is not None and add_target not in cur["targets_taken"]:
            cur["targets_taken"].append(add_target)
        m[coin] = cur
        atomic_write_json(_META, m)
    return m[coin]

def _clear_meta(coin, m=None):
    own = m is None
    m = m if m is not None else _load_meta()
    if coin in m:
        del m[coin]
        if own:
            atomic_write_json(_META, m)
    return m


# ---------- balances / positions ----------
def balance():
    if config.MODE in ("testnet", "live"):
        return _ccxt_balance()
    w = _load()
    equity = w["cash_usd"]
    for coin, p in w["positions"].items():
        equity += p["quantity"] * _mark(coin)
    # Short positions: collateral already deducted from cash; add back collateral + unrealized P&L
    for coin, s in w.get("shorts", {}).items():
        current = _mark(coin)
        short_pnl = (s["entry_price"] - current) * s["quantity"]
        equity += s["collateral"] + short_pnl
    n_open = len(w["positions"]) + len(w.get("shorts", {}))
    return {"cash_usd": round(w["cash_usd"], 2), "equity_usd": round(equity, 2),
            "open_positions": n_open, "mode": config.MODE}


def positions():
    meta = _load_meta()
    if config.MODE in ("testnet", "live"):
        raw = _ccxt_positions()
    else:
        w = _load()
        raw = []
        for coin, p in w["positions"].items():
            raw.append({**p, "coin": coin, "side": "LONG"})

    # Short positions: real futures when credentials are present, otherwise paper wallet.
    # In testnet/live mode _ccxt_positions() already appends futures shorts, so only
    # fall back to the paper wallet when futures are not configured.
    if not (config.MODE in ("testnet", "live") and _futures_available()):
        w = _load()
        for coin, s in w.get("shorts", {}).items():
            raw.append({**s, "coin": coin, "side": "SHORT"})

    out = []
    for p in raw:
        coin = p["coin"]
        price = _mark(coin)
        side = p.get("side", "LONG")
        if side == "SHORT":
            pnl_pct = (p["entry_price"] - price) / p["entry_price"] * 100 if p["entry_price"] else 0
        else:
            pnl_pct = (price - p["entry_price"]) / p["entry_price"] * 100 if p["entry_price"] else 0
        mm = meta.get(coin, {})
        out.append({**p, "current_price": price,
                    "unrealised_pnl_pct": round(pnl_pct, 2),
                    "peak_pnl": mm.get("peak_pnl"),
                    "targets_taken": mm.get("targets_taken", [])})
    return out


def _mark(coin):
    from mcp_servers._marketdata_core import get_ticker
    return get_ticker(coin)["price"]


# ---------- order placement ----------
def place_order(coin, side, quantity, client_order_id=None):
    """Place an order. Idempotent on client_order_id.
    Paper mode fills against the current mark price under the wallet lock."""
    if config.MODE in ("testnet", "live"):
        return _ccxt_order(coin, side, quantity, client_order_id)

    coid = client_order_id or str(uuid.uuid4())
    price = _mark(coin)
    with _wallet_lock():
        w = _load()
        if any(f["client_order_id"] == coid for f in w["fills"]):
            return {"status": "duplicate_ignored", "client_order_id": coid}
        notional = price * quantity
        if side == "BUY":
            if notional > w["cash_usd"]:
                return {"status": "rejected", "reason": "insufficient cash"}
            w["cash_usd"] -= notional
            pos = w["positions"].get(coin)
            if pos:
                tot = pos["quantity"] + quantity
                pos["entry_price"] = (pos["entry_price"] * pos["quantity"] + price * quantity) / tot
                pos["quantity"] = tot
            else:
                w["positions"][coin] = {"quantity": quantity, "entry_price": price,
                                        "opened_at": time.time()}
                # fresh position -> reset exit tracking
                m = _load_meta(); m[coin] = {"peak_pnl": 0.0, "targets_taken": []}
                atomic_write_json(_META, m)
        elif side == "SELL":  # spot: reduce/close an existing long only
            pos = w["positions"].get(coin)
            if not pos:
                return {"status": "rejected", "reason": "no position to sell"}
            sell_qty = min(quantity, pos["quantity"])   # never sell more than held
            w["cash_usd"] += price * sell_qty
            pos["quantity"] -= sell_qty
            quantity = sell_qty
            if pos["quantity"] <= 1e-9:
                del w["positions"][coin]
                _clear_meta(coin)

        elif side == "SHORT":  # synthetic short: reserve collateral from cash
            notional = price * quantity
            if notional > w["cash_usd"]:
                return {"status": "rejected", "reason": "insufficient cash for short collateral"}
            if coin in w.get("shorts", {}):
                return {"status": "rejected", "reason": f"already short {coin}"}
            w["cash_usd"] -= notional
            w.setdefault("shorts", {})[coin] = {
                "quantity": quantity, "entry_price": price,
                "opened_at": time.time(), "collateral": notional,
            }
            m = _load_meta()
            m[coin] = {"peak_pnl": 0.0, "targets_taken": []}
            atomic_write_json(_META, m)

        elif side == "COVER":  # close a synthetic short, return collateral ± P&L
            shorts = w.get("shorts", {})
            short_pos = shorts.get(coin)
            if not short_pos:
                return {"status": "rejected", "reason": f"no short to cover on {coin}"}
            cover_qty = min(quantity, short_pos["quantity"])
            frac = cover_qty / short_pos["quantity"]
            pnl = (short_pos["entry_price"] - price) * cover_qty
            collateral_return = short_pos["collateral"] * frac
            w["cash_usd"] += collateral_return + pnl
            w["realized_short_pnl"] = w.get("realized_short_pnl", 0.0) + pnl
            short_pos["quantity"] -= cover_qty
            short_pos["collateral"] -= collateral_return
            quantity = cover_qty
            if short_pos["quantity"] <= 1e-9:
                del shorts[coin]
                _clear_meta(coin)
        fill = {"client_order_id": coid, "coin": coin, "side": side,
                "quantity": round(quantity, 8), "price": price, "ts": time.time()}
        w["fills"].append(fill)
        _save(w)
    return {"status": "filled", **fill}


# ---------- ccxt clients (cached, one per exchange type per process) ----------

def _futures_available():
    """True if futures credentials are configured for the current mode."""
    from config import secrets
    if config.MODE == "testnet":
        return bool(getattr(secrets, "BINANCE_FUTURES_TESTNET_API_KEY", ""))
    if config.MODE == "live":
        return bool(getattr(secrets, "BINANCE_LIVE_FUTURES_API_KEY", ""))
    return False


def _ccxt_client():
    global _spot_ex_cache
    if _spot_ex_cache is not None:
        return _spot_ex_cache
    with _ex_lock:
        if _spot_ex_cache is not None:
            return _spot_ex_cache
        import ccxt
        from config import secrets
        key = (secrets.BINANCE_TESTNET_API_KEY if config.MODE == "testnet"
               else secrets.BINANCE_LIVE_API_KEY)
        sec = (secrets.BINANCE_TESTNET_API_SECRET if config.MODE == "testnet"
               else secrets.BINANCE_LIVE_API_SECRET)
        if not key:
            raise RuntimeError("no spot exchange credentials configured")
        ex = ccxt.binance({"apiKey": key, "secret": sec, "enableRateLimit": True,
                           "options": {"defaultType": "spot"}})
        if config.MODE == "testnet":
            ex.set_sandbox_mode(True)
        _spot_ex_cache = ex
    return _spot_ex_cache


def _futures_client():
    global _fut_ex_cache
    if _fut_ex_cache is not None:
        return _fut_ex_cache
    with _ex_lock:
        if _fut_ex_cache is not None:
            return _fut_ex_cache
        import ccxt
        from config import secrets
        if config.MODE == "testnet":
            key = secrets.BINANCE_FUTURES_TESTNET_API_KEY
            sec = secrets.BINANCE_FUTURES_TESTNET_API_SECRET
        else:
            key = getattr(secrets, "BINANCE_LIVE_FUTURES_API_KEY", "")
            sec = getattr(secrets, "BINANCE_LIVE_FUTURES_API_SECRET", "")
        if not key:
            raise RuntimeError("no futures exchange credentials configured")
        ex = ccxt.binance({"apiKey": key, "secret": sec, "enableRateLimit": True,
                           "options": {"defaultType": "future"}})
        if config.MODE == "testnet":
            ex.set_sandbox_mode(True)
        _fut_ex_cache = ex
    return _fut_ex_cache


def _init_futures_symbol(fex, symbol):
    """Set leverage and margin type once per symbol per process. Non-fatal on error."""
    if symbol in _leverage_done:
        return
    try:
        fex.set_leverage(config.FUTURES_LEVERAGE, symbol)
    except Exception:
        pass
    try:
        fex.set_margin_mode(config.FUTURES_MARGIN_TYPE.lower(), symbol)
    except Exception:
        pass
    _leverage_done.add(symbol)


# ---------- balance / positions ----------

def _ccxt_balance():
    try:
        ex = _ccxt_client()
        bal = ex.fetch_balance()
        cash = float(bal.get("USDT", {}).get("free", 0.0))
        fills = _load().get("fills", [])
        coins_we_bought = {f["coin"] for f in fills if f["side"] == "BUY"}
        equity = cash
        held = {}
        for coin in coins_we_bought:
            qty = float(bal.get("total", {}).get(coin, 0))
            if coin in config.TRACKED_COINS and qty > 1e-9:
                held[coin] = qty
                try:
                    equity += qty * ex.fetch_ticker(f"{coin}/USDT")["last"]
                except Exception:
                    pass

        n_open = len(held)
        if _futures_available():
            # Futures wallet balance (USDT total already includes unrealized PnL)
            try:
                fex = _futures_client()
                fbal = fex.fetch_balance()
                fut_total = float(fbal.get("USDT", {}).get("total", 0.0))
                equity += fut_total
                n_open += sum(1 for p in fex.fetch_positions()
                              if (p.get("contracts") or 0) > 0)
            except Exception:
                pass
        else:
            # Paper-wallet synthetic shorts (fallback when no futures creds)
            w = _load()
            short_collateral = sum(s["collateral"] for s in w.get("shorts", {}).values())
            for coin, s in w.get("shorts", {}).items():
                equity += s["collateral"] + (s["entry_price"] - _mark(coin)) * s["quantity"]
                n_open += 1
            equity += w.get("realized_short_pnl", 0.0)
            cash = round(cash - short_collateral, 2)

        return {"cash_usd": round(cash, 2), "equity_usd": round(equity, 2),
                "open_positions": n_open, "mode": config.MODE}
    except Exception as e:  # noqa
        return {"cash_usd": 0.0, "equity_usd": 0.0, "open_positions": 0,
                "mode": config.MODE, "error": str(e)}


def _ccxt_positions():
    """Spot LONGs MiniSim opened + real futures SHORTs (when credentials present).
    Pre-loaded testnet tokens are excluded from spot — they were not traded by this
    system and would falsely inflate exposure."""
    out = []

    # ── spot LONGs ──────────────────────────────────────────────────────────
    try:
        ex = _ccxt_client()
        bal = ex.fetch_balance()
        fills = _load().get("fills", [])
        coins_we_bought = {f["coin"] for f in fills if f["side"] == "BUY"}
        for coin in coins_we_bought:
            if coin not in config.TRACKED_COINS:
                continue
            qty = float(bal.get("total", {}).get(coin, 0))
            if qty <= 1e-9:
                continue
            entries = [f for f in fills if f["coin"] == coin and f["side"] == "BUY"]
            out.append({"coin": coin, "side": "LONG",
                        "quantity": qty,
                        "entry_price": float(entries[-1]["price"]),
                        "opened_at": entries[-1]["ts"]})
    except Exception:
        pass

    # ── futures SHORTs ──────────────────────────────────────────────────────
    if _futures_available():
        try:
            fex = _futures_client()
            for pos in fex.fetch_positions():
                contracts = pos.get("contracts") or 0
                if pos.get("side") == "short" and contracts > 0:
                    sym = pos.get("symbol", "")           # e.g. "BTC/USDT:USDT"
                    coin = sym.split("/")[0]
                    out.append({"coin": coin, "side": "SHORT",
                                "quantity": float(contracts),
                                "entry_price": float(pos.get("entryPrice") or 0),
                                "opened_at": time.time()})
        except Exception:
            pass

    return out


# ---------- order placement (ccxt) ----------

def _ccxt_order(coin, side, quantity, coid):
    """Route to spot (BUY/SELL) or futures (SHORT/COVER) exchange."""
    if side in ("SHORT", "COVER"):
        if _futures_available():
            return _ccxt_futures_order(coin, side, quantity, coid)
        # No futures creds: fall through to paper-wallet short simulation
        return _paper_short_order(coin, side, quantity, coid)

    # ── spot BUY / SELL ─────────────────────────────────────────────────────
    try:
        ex = _ccxt_client()
        symbol = f"{coin}/USDT"
        if side == "SELL":
            held = float(ex.fetch_balance().get(coin, {}).get("free", 0.0))
            if held <= 0:
                return {"status": "rejected", "reason": "no base balance to sell"}
            quantity = min(quantity, held)
        params = {"newClientOrderId": coid} if coid else {}
        order = ex.create_order(symbol, "market", side.lower(), quantity, params=params)
        px     = order.get("average") or order.get("price")
        filled = order.get("filled") or quantity
        _record_fill(coid or order.get("id"), coin, side, filled, px)
        return {"status": "filled", "exchange_order": order.get("id"),
                "price": px, "quantity": filled}
    except Exception as e:  # noqa
        return {"status": "error", "reason": str(e)}


def _ccxt_futures_order(coin, side, quantity, coid):
    """Place a real USDM futures market order for SHORT entry or COVER exit.
    Assumes ONE-WAY position mode (the Binance futures testnet default)."""
    try:
        fex    = _futures_client()
        symbol = f"{coin}/USDT"
        _init_futures_symbol(fex, symbol)

        if side == "SHORT":
            order_side = "sell"
            params = {}
        else:  # COVER
            order_side = "buy"
            params = {"reduceOnly": True}
        if coid:
            params["newClientOrderId"] = coid

        order  = fex.create_order(symbol, "market", order_side, quantity, params=params)
        px     = order.get("average") or order.get("price")
        filled = order.get("filled") or quantity
        _record_fill(coid or order.get("id"), coin, side, filled, px)
        return {"status": "filled", "exchange_order": order.get("id"),
                "price": px, "quantity": filled}
    except Exception as e:  # noqa
        return {"status": "error", "reason": str(e)}


def _paper_short_order(coin, side, quantity, coid):
    """Synthetic short simulation used when futures credentials are absent."""
    price = _mark(coin)
    coid  = coid or str(uuid.uuid4())
    with _wallet_lock():
        w = _load()
        if any(f["client_order_id"] == coid for f in w["fills"]):
            return {"status": "duplicate_ignored", "client_order_id": coid}
        if side == "SHORT":
            notional = price * quantity
            if notional > w["cash_usd"]:
                return {"status": "rejected", "reason": "insufficient cash for short collateral"}
            if coin in w.get("shorts", {}):
                return {"status": "rejected", "reason": f"already short {coin}"}
            w["cash_usd"] -= notional
            w.setdefault("shorts", {})[coin] = {
                "quantity": quantity, "entry_price": price,
                "opened_at": time.time(), "collateral": notional,
            }
            m = _load_meta()
            m[coin] = {"peak_pnl": 0.0, "targets_taken": []}
            atomic_write_json(_META, m)
        else:  # COVER
            shorts = w.get("shorts", {})
            sp = shorts.get(coin)
            if not sp:
                return {"status": "rejected", "reason": f"no short to cover on {coin}"}
            cover_qty = min(quantity, sp["quantity"])
            frac = cover_qty / sp["quantity"]
            w["cash_usd"] += sp["collateral"] * frac + (sp["entry_price"] - price) * cover_qty
            sp["quantity"]   -= cover_qty
            sp["collateral"] -= sp["collateral"] * frac
            quantity = cover_qty
            if sp["quantity"] <= 1e-9:
                del shorts[coin]
                _clear_meta(coin)
        fill = {"client_order_id": coid, "coin": coin, "side": side,
                "quantity": round(quantity, 8), "price": price, "ts": time.time()}
        w["fills"].append(fill)
        _save(w)
    return {"status": "filled", **fill}


def _record_fill(coid, coin, side, quantity, price):
    """Append a fill hint to the local wallet (used for position reconstruction)."""
    try:
        with _wallet_lock():
            w = _load()
            w.setdefault("fills", []).append(
                {"client_order_id": coid, "coin": coin, "side": side,
                 "quantity": quantity, "price": price or 0.0, "ts": time.time()})
            _save(w)
    except Exception:
        pass
