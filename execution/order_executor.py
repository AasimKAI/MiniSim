"""Layer D — order execution via the exchange MCP server. Idempotent."""
from common import get_logger
log = get_logger("execution")

def execute(mcp, signal_id, coin, side, quantity, trigger="entry"):
    coid = f"{signal_id}/{trigger}"
    res = mcp.place_order(coin, side, quantity, client_order_id=coid)
    log.info("order %s %s %s -> %s", coin, side, quantity, res.get("status"))
    return res
