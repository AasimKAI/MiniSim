"""Writes status.json that both dashboards read. Single source of truth."""
import time
from config import config
from common import atomic_write_json, read_json
from llm.quantized_client import healthcheck

_START = time.time()
_EQUITY_MIN_INTERVAL_SEC = 300   # don't sample more often than this
_EQUITY_MAX_POINTS = 2000        # ring buffer cap (~7 days at the interval above)


def _record_equity(equity):
    """Append a point to the equity history ring buffer, throttled so the
    30s exit-watch loop doesn't flood it with near-duplicate samples."""
    if equity is None:
        return
    hist = read_json(config.EQUITY_HISTORY_FILE, [])
    now = time.time()
    if hist and now - hist[-1]["ts"] < _EQUITY_MIN_INTERVAL_SEC:
        return
    hist.append({"ts": now, "equity": equity})
    if len(hist) > _EQUITY_MAX_POINTS:
        hist = hist[-_EQUITY_MAX_POINTS:]
    atomic_write_json(config.EQUITY_HISTORY_FILE, hist)


def write_status(mcp, regime="—", last_cycle="—"):
    bal = mcp.balance()
    pos = mcp.positions()
    llm = healthcheck()
    data_source = "unknown"
    if config.TRACKED_COINS:
        try:
            data_source = mcp.ticker(config.TRACKED_COINS[0]).get("source", "unknown")
        except Exception:  # noqa
            pass
    up = int(time.time() - _START)
    _record_equity(bal.get("equity_usd"))
    atomic_write_json(config.STATUS_FILE, {
        "version": config.VERSION, "mode": config.MODE,
        "equity_usd": bal.get("equity_usd"), "cash_usd": bal.get("cash_usd"),
        "open_positions": bal.get("open_positions"), "positions": pos,
        "regime": regime, "last_cycle": last_cycle,
        "mcp_transport": mcp.status().get("transport"),
        "llm_backend": llm.get("backend"), "llm_model_present": llm.get("model_present"),
        "coins_tracked": len(config.TRACKED_COINS),
        "data_source": data_source,
        "uptime": f"{up//3600}h{(up%3600)//60}m",
        "updated": time.time(),
    })
