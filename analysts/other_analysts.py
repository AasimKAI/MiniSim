"""Volume, order-book and on-chain analysts (pure arithmetic)."""
from analysts import indicators as ind
from schemas.validators import validate_analyst_verdict


def volume_analyst(coin, candles):
    vols = [c.get("volume", 0) for c in candles]
    closes = [c["close"] for c in candles]
    if len(vols) < 30:
        return _v("volume", coin, "neutral", 0.0, "insufficient data")
    avg = sum(vols[-30:-1]) / 29
    spike = vols[-1] / avg if avg else 1
    up = closes[-1] > closes[-2]
    if spike > 2.0 and up:
        return _v("volume", coin, "bullish", min(0.8, spike / 3), f"volume spike x{spike:.1f} on up candle")
    if spike > 2.0 and not up:
        return _v("volume", coin, "bearish", min(0.8, spike / 3), f"volume spike x{spike:.1f} on down candle")
    return _v("volume", coin, "neutral", 0.2, f"volume normal (x{spike:.1f})")


def order_book_analyst(coin, ob):
    imb = ob.get("imbalance", 0)
    if imb > 0.2:
        return _v("order_book", coin, "bullish", min(0.7, abs(imb)), f"bid-heavy book ({imb:+.2f})")
    if imb < -0.2:
        return _v("order_book", coin, "bearish", min(0.7, abs(imb)), f"ask-heavy book ({imb:+.2f})")
    return _v("order_book", coin, "neutral", 0.2, f"balanced book ({imb:+.2f})")


def on_chain_analyst(coin, ticker):
    # Placeholder arithmetic proxy until an on-chain MCP feed is added.
    ch = ticker.get("change_24h_pct", 0)
    if ch > 4:
        return _v("on_chain", coin, "bullish", 0.4, "strong 24h momentum proxy")
    if ch < -4:
        return _v("on_chain", coin, "bearish", 0.4, "weak 24h momentum proxy")
    return _v("on_chain", coin, "neutral", 0.2, "flat momentum proxy")


def _v(a, coin, verdict, conf, reason):
    return validate_analyst_verdict({"analyst": a, "coin": coin, "verdict": verdict,
                                     "confidence": round(conf, 3), "reasoning": reason})
