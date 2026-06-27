"""Layer D — risk checks. Can SHRINK or VETO an order. Safety first.
Enforces a HARD exposure ceiling: the post-trade total can never exceed
MAX_EXPOSURE_USD (fixes the cap-overshoot)."""
from config import config

def check(coin, action, price, balance, open_positions):
    """Returns (quantity, decision, reason). quantity 0 => veto."""
    if action not in ("ENTRY_BUY", "ENTRY_SELL"):
        return 0.0, "veto", "not an entry"
    if price <= 0:
        return 0.0, "veto", "bad price"
    exposure = sum(p["quantity"] * p.get("current_price", p["entry_price"])
                   for p in open_positions)
    room = config.MAX_EXPOSURE_USD - exposure
    if room <= 10:
        return 0.0, "veto", f"max exposure ${config.MAX_EXPOSURE_USD} reached (exp ${exposure:.0f})"
    size_usd = min(config.POSITION_SIZE_USD, room)
    if action in ("ENTRY_BUY", "ENTRY_SELL") and size_usd > balance.get("cash_usd", 0):
        size_usd = balance.get("cash_usd", 0) * 0.98
    if size_usd < 10:
        return 0.0, "veto", "insufficient cash / room"
    # hard post-trade guarantee
    if exposure + size_usd > config.MAX_EXPOSURE_USD + 1e-6:
        size_usd = max(0.0, room)
    if size_usd < 10:
        return 0.0, "veto", "would breach exposure cap"
    qty = round(size_usd / price, 6)
    decision = "shrink" if size_usd < config.POSITION_SIZE_USD - 1e-6 else "approve"
    if size_usd > config.BIG_TRADE_THRESHOLD_USD:
        decision = "hold_for_approval"
    return qty, decision, f"size ${size_usd:.0f}, exposure ${exposure:.0f}/{config.MAX_EXPOSURE_USD}"
