"""Layer D — order execution via the exchange MCP server. Idempotent."""
from config import config
from common import get_logger, append_jsonl, utcnow_iso
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
    if res.get("status") == "unknown":
        # The order MAY have executed (transport died mid-flight and is never
        # retried, to avoid double execution). Record it so the operator can
        # reconcile against the exchange's trade history.
        try:
            append_jsonl(config.RECONCILIATION_LOG, {
                "ts": utcnow_iso(), "client_order_id": coid, "coin": coin,
                "side": side, "quantity": quantity, "trigger": trigger,
                "status": res.get("status"), "reason": res.get("reason", "")})
            log.warning("order outcome UNKNOWN — logged to %s for reconciliation",
                        config.RECONCILIATION_LOG)
        except Exception:
            pass
    return res
