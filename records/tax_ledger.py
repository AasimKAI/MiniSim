"""Layer F — HMRC-style trade ledger (GBP)."""
from config import config
from common import append_jsonl, utcnow_iso

GBP_PER_USD = 0.78  # static fallback; a real build pulls FX from a feed

def record_trade(coin, side, quantity, price_usd, fee_usd=0.0, strategy=None):
    """strategy: name of the strategy that opened the position (entries only);
    carried through FIFO matching so per-strategy P&L can be computed."""
    gbp = price_usd * quantity * GBP_PER_USD
    append_jsonl(config.TAX_LEDGER, {
        "timestamp": utcnow_iso(), "coin": coin, "side": side,
        "quantity": quantity, "price_usd": price_usd,
        "total_usd": round(price_usd * quantity, 2),
        "total_gbp": round(gbp, 2), "fee_usd": fee_usd,
        "strategy": strategy,
        "fx_rate_gbp_usd": GBP_PER_USD, "fx_source": "static_fallback"})
