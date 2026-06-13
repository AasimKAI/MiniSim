"""Writes status.json that both dashboards read. Single source of truth."""
import time
from config import config
from common import atomic_write_json
from llm.quantized_client import healthcheck

_START = time.time()

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
