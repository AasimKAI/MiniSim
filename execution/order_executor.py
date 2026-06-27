"""Layer D — order execution via the exchange MCP server. Idempotent."""
from common import get_logger
log = get_logger("execution")

def execute(mcp, signal_id, coin, side, quantity, trigger="entry"):
    # Binance's newClientOrderId only allows [a-zA-Z0-9-_], max 36 chars — a
    # raw UUID (36 chars) plus any suffix violates the length cap, and the
    # "/" separator violates the character set, so every testnet/live order
    # was being rejected before this was caught. Drop the hyphens from the
    # UUID to make room for a trigger suffix while staying under the cap.
    coid = f"{signal_id.replace('-', '')}-{trigger}"[:36]
    res = mcp.place_order(coin, side, quantity, client_order_id=coid)
    if res.get("status") not in ("filled", "duplicate_ignored"):
        log.warning("order %s %s %s -> %s (%s)", coin, side, quantity,
                    res.get("status"), res.get("reason", ""))
    else:
        log.info("order %s %s %s -> %s", coin, side, quantity, res.get("status"))
    return res
