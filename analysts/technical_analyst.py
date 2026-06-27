"""
v5 Technical Analyst — combines the upgraded indicators into a single weighted
verdict (bullish / bearish / neutral) with a confidence 0-1, plus a higher
timeframe confirmation check. Pure arithmetic, no LLM, fully explainable.
"""
from analysts import indicators as ind
from schemas.validators import validate_analyst_verdict
from common import get_logger

log = get_logger("technical")

# weights for each signal contribution
WEIGHTS = {
    "trend_ema": 1.0, "macd": 1.0, "rsi": 0.8, "stoch_rsi": 0.6,
    "adx": 1.0, "supertrend": 1.2, "bollinger": 0.6, "ichimoku": 1.0,
    "obv": 0.6, "vwap": 0.6, "divergence": 1.0, "htf_confirm": 1.2,
}


def _series(candles):
    o = [c["open"] for c in candles]
    h = [c["high"] for c in candles]
    l = [c["low"] for c in candles]
    c = [c["close"] for c in candles]
    v = [c_.get("volume", 0.0) for c_ in candles]
    return o, h, l, c, v


def _score(candles):
    """Return (signed_score, reasons, metrics) for one timeframe."""
    o, h, l, c, v = _series(candles)
    score = 0.0
    reasons = []
    m = {}

    ema20, ema50 = ind.ema(c, 20), ind.ema(c, 50)
    if ema20 and ema50:
        m["ema20"], m["ema50"] = round(ema20, 4), round(ema50, 4)
        if ema20 > ema50:
            score += WEIGHTS["trend_ema"]; reasons.append("EMA20>EMA50 (uptrend)")
        else:
            score -= WEIGHTS["trend_ema"]; reasons.append("EMA20<EMA50 (downtrend)")

    mac = ind.macd(c)
    if mac:
        m["macd_hist"] = round(mac["hist"], 5)
        if mac["hist"] > 0:
            score += WEIGHTS["macd"]; reasons.append("MACD histogram positive")
        else:
            score -= WEIGHTS["macd"]; reasons.append("MACD histogram negative")

    # ADX first — it tells us whether to trust trend or mean-reversion signals.
    adx = ind.dmi_adx(h, l, c)
    trending = False
    di_dir = 0
    if adx:
        m["adx"] = round(adx["adx"], 1)
        di_dir = 1 if adx["plus_di"] > adx["minus_di"] else -1
        if adx["adx"] > 25:
            trending = True
            score += WEIGHTS["adx"] * di_dir
            reasons.append(f"ADX {adx['adx']:.0f} strong {'up' if di_dir>0 else 'down'}-trend")

    # RSI / StochRSI: in a TREND, an extreme reading CONFIRMS the trend rather
    # than signalling a reversal. Only treat extremes as counter-trend
    # reversal signals when the market is ranging (low ADX).
    r = ind.rsi(c)
    if r is not None:
        m["rsi"] = round(r, 2)
        if trending:
            if r < 40 and di_dir < 0:
                score -= WEIGHTS["rsi"]; reasons.append(f"RSI {r:.0f} confirms down-trend")
            elif r > 60 and di_dir > 0:
                score += WEIGHTS["rsi"]; reasons.append(f"RSI {r:.0f} confirms up-trend")
        else:
            if r < 30:
                score += WEIGHTS["rsi"]; reasons.append(f"RSI {r:.0f} oversold (range)")
            elif r > 70:
                score -= WEIGHTS["rsi"]; reasons.append(f"RSI {r:.0f} overbought (range)")

    sr = ind.stoch_rsi(c)
    if sr:
        m["stoch_rsi_k"] = round(sr["k"], 1)
        if not trending:
            if sr["k"] < 20:
                score += WEIGHTS["stoch_rsi"]; reasons.append("StochRSI oversold (range)")
            elif sr["k"] > 80:
                score -= WEIGHTS["stoch_rsi"]; reasons.append("StochRSI overbought (range)")

    st = ind.supertrend(h, l, c)
    if st:
        m["supertrend"] = st["direction"]
        score += WEIGHTS["supertrend"] if st["direction"] == "up" else -WEIGHTS["supertrend"]
        reasons.append(f"Supertrend {st['direction']}")

    bb = ind.bollinger(c)
    if bb:
        m["bb_width"] = round(bb["width"], 4)
        if c[-1] < bb["lower"]:
            score += WEIGHTS["bollinger"]; reasons.append("price below lower Bollinger")
        elif c[-1] > bb["upper"]:
            score -= WEIGHTS["bollinger"]; reasons.append("price above upper Bollinger")

    ich = ind.ichimoku(h, l, c)
    if ich:
        m["ichimoku"] = ich["bias"]
        if ich["bias"] == "bullish":
            score += WEIGHTS["ichimoku"]; reasons.append("Ichimoku bullish")
        elif ich["bias"] == "bearish":
            score -= WEIGHTS["ichimoku"]; reasons.append("Ichimoku bearish")

    ob = ind.obv(c, v)
    if ob:
        m["obv_trend"] = ob["trend"]
        score += WEIGHTS["obv"] if ob["trend"] == "rising" else -WEIGHTS["obv"]

    vw = ind.vwap(h, l, c, v)
    if vw:
        m["vwap"] = round(vw, 4)
        score += WEIGHTS["vwap"] if c[-1] > vw else -WEIGHTS["vwap"]

    div = ind.rsi_divergence(c)
    if div != "none":
        m["divergence"] = div
        score += WEIGHTS["divergence"] if div == "bullish" else -WEIGHTS["divergence"]
        reasons.append(f"{div} RSI divergence")

    return score, reasons, m


def analyze(coin, candles):
    """candles: list of dicts (oldest->newest) with open/high/low/close/volume."""
    if len(candles) < 60:
        return validate_analyst_verdict({
            "analyst": "technical", "coin": coin, "verdict": "neutral",
            "confidence": 0.0, "reasoning": "insufficient candle history", "metrics": {}})

    score, reasons, metrics = _score(candles)

    # higher-timeframe confirmation (e.g. 5x bars)
    htf = ind.resample(candles, 5)
    htf_dir = 0
    metrics["htf_conflict"] = False
    if len(htf) >= 60:
        htf_score, _, _ = _score(htf)
        htf_dir = 1 if htf_score > 0 else -1 if htf_score < 0 else 0
        if (score > 0 and htf_dir > 0) or (score < 0 and htf_dir < 0):
            score += WEIGHTS["htf_confirm"] * (1 if score > 0 else -1)
            reasons.append("higher-timeframe agrees")
        elif htf_dir != 0:
            score *= 0.6  # conflict -> dampen
            reasons.append("higher-timeframe conflicts (dampened)")
            metrics["htf_conflict"] = True

    max_score = sum(WEIGHTS.values())
    confidence = min(1.0, abs(score) / (max_score * 0.55))
    verdict = "bullish" if score > 0.8 else "bearish" if score < -0.8 else "neutral"
    if verdict == "neutral":
        confidence = min(confidence, 0.4)

    return validate_analyst_verdict({
        "analyst": "technical", "coin": coin, "verdict": verdict,
        "confidence": round(confidence, 3),
        "reasoning": "; ".join(reasons[:6]) or "no strong signals",
        "metrics": metrics, "raw_score": round(score, 2),
    })
