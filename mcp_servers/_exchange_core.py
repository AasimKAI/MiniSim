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
import os, time, uuid, json
from contextlib import contextmanager
from config import config
from common import read_json, atomic_write_json

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
    return read_json(_WALLET, {"cash_usd": 10000.0, "positions": {}, "fills": []})

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
    return {"cash_usd": round(w["cash_usd"], 2), "equity_usd": round(equity, 2),
            "open_positions": len(w["positions"]), "mode": config.MODE}


def positions():
    meta = _load_meta()
    if config.MODE in ("testnet", "live"):
        raw = _ccxt_positions()
    else:
        w = _load()
        raw = []
        for coin, p in w["positions"].items():
            raw.append({**p, "coin": coin})
    out = []
    for p in raw:
        coin = p["coin"]
        price = _mark(coin)
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
        else:  # SELL — spot: reduce/close an existing long only
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
        fill = {"client_order_id": coid, "coin": coin, "side": side,
                "quantity": round(quantity, 8), "price": price, "ts": time.time()}
        w["fills"].append(fill)
        _save(w)
    return {"status": "filled", **fill}


# ---------- ccxt (testnet/live) ----------
def _ccxt_client():
    import ccxt
    from config import secrets
    key = (secrets.BINANCE_TESTNET_API_KEY if config.MODE == "testnet"
           else secrets.BINANCE_LIVE_API_KEY)
    sec = (secrets.BINANCE_TESTNET_API_SECRET if config.MODE == "testnet"
           else secrets.BINANCE_LIVE_API_SECRET)
    if not key:
        raise RuntimeError("no exchange credentials configured")
    ex = ccxt.binance({"apiKey": key, "secret": sec, "enableRateLimit": True,
                       "options": {"defaultType": "spot"}})
    if config.MODE == "testnet":
        ex.set_sandbox_mode(True)
    return ex


def _ccxt_balance():
    try:
        ex = _ccxt_client()
        bal = ex.fetch_balance()
        cash = float(bal.get("USDT", {}).get("free", 0.0))
        equity = cash
        held = {a: v for a, v in bal.get("total", {}).items()
                if a in config.TRACKED_COINS and v}
        for coin, qty in held.items():
            try:
                equity += qty * ex.fetch_ticker(f"{coin}/USDT")["last"]
            except Exception:
                pass
        return {"cash_usd": round(cash, 2), "equity_usd": round(equity, 2),
                "open_positions": len(held), "mode": config.MODE}
    except Exception as e:  # noqa
        return {"cash_usd": 0.0, "equity_usd": 0.0, "open_positions": 0,
                "mode": config.MODE, "error": str(e)}


def _ccxt_positions():
    """Spot holdings reconstructed from balances. entry_price uses last known
    fill if available, else current price (so PnL is conservative)."""
    try:
        ex = _ccxt_client()
        bal = ex.fetch_balance()
        fills = _load().get("fills", [])  # last known entry hints (best-effort)
        out = []
        for coin, qty in bal.get("total", {}).items():
            if coin not in config.TRACKED_COINS or not qty:
                continue
            entries = [f for f in fills if f["coin"] == coin and f["side"] == "BUY"]
            entry = entries[-1]["price"] if entries else ex.fetch_ticker(f"{coin}/USDT")["last"]
            out.append({"coin": coin, "quantity": float(qty), "entry_price": float(entry),
                        "opened_at": entries[-1]["ts"] if entries else time.time()})
        return out
    except Exception:
        return []


def _ccxt_order(coin, side, quantity, coid):
    """Place a real market order. NOT auto-retried by the client on timeout
    (see place-order idempotency note)."""
    try:
        ex = _ccxt_client()
        symbol = f"{coin}/USDT"
        if side == "SELL":   # spot: never sell more base than held
            held = float(ex.fetch_balance().get(coin, {}).get("free", 0.0))
            if held <= 0:
                return {"status": "rejected", "reason": "no base balance to sell"}
            quantity = min(quantity, held)
        params = {"newClientOrderId": coid} if coid else {}
        order = ex.create_order(symbol, "market", side.lower(), quantity, params=params)
        px = order.get("average") or order.get("price")
        filled = order.get("filled") or quantity
        # record a local fill hint for entry-price reconstruction
        try:
            with _wallet_lock():
                w = _load()
                w.setdefault("fills", []).append(
                    {"client_order_id": coid or order.get("id"), "coin": coin,
                     "side": side, "quantity": filled, "price": px or 0.0, "ts": time.time()})
                _save(w)
        except Exception:
            pass
        return {"status": "filled", "exchange_order": order.get("id"),
                "price": px, "quantity": filled}
    except Exception as e:  # noqa
        return {"status": "error", "reason": str(e)}
