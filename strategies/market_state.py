"""
Market-state detector — classifies each tracked coin as bear / bull / neutral
and produces an aggregate read that the strategy router uses.

Inputs: a dict of {coin: list[candle]} (same format as backtest fetch_candles).
Output: MarketState dict.
"""
from __future__ import annotations
from analysts import indicators as ind


def _direction_for_coin(candles: list) -> dict:
    """Per-coin: bear / bull / neutral + supporting data."""
    if len(candles) < 210:
        return {"direction": "neutral", "score": 0}

    c = [x["close"] for x in candles]
    h = [x["high"]  for x in candles]
    lo = [x["low"]  for x in candles]

    price  = c[-1]
    ema20  = ind.ema(c, 20)
    ema50  = ind.ema(c, 50)
    ema200 = ind.ema(c, 200)
    adx    = ind.dmi_adx(h, lo, c)
    st     = ind.supertrend(h, lo, c)

    # 7-day and 24-hour returns (15 min candles: 96/day, 672/week)
    ret_24h = (price / c[-96]  - 1) * 100 if len(c) >= 96  else 0.0
    ret_7d  = (price / c[-672] - 1) * 100 if len(c) >= 672 else ret_24h * 7

    bull_score = 0
    bear_score = 0

    if ema20 and ema50:
        if ema20 > ema50: bull_score += 1
        else:             bear_score += 1
    if ema50 and ema200:
        if ema50 > ema200: bull_score += 1
        else:              bear_score += 1
    if ema200:
        if price > ema200: bull_score += 1
        else:              bear_score += 1
    if st:
        if st["direction"] == "up":   bull_score += 2
        else:                         bear_score += 2
    if adx:
        if adx["plus_di"] > adx["minus_di"]: bull_score += 1
        else:                                 bear_score += 1
    if ret_7d > 8:  bull_score += 1
    if ret_7d < -8: bear_score += 1

    net = bull_score - bear_score   # range roughly -7 .. +7
    if net >= 3:
        direction = "bull"
    elif net <= -3:
        direction = "bear"
    else:
        direction = "neutral"

    return {
        "direction": direction,
        "net_score": net,
        "ret_24h":   round(ret_24h, 2),
        "ret_7d":    round(ret_7d,  2),
        "price":     price,
        "ema20":     ema20,
        "ema50":     ema50,
        "ema200":    ema200,
        "adx":       round(adx["adx"], 1) if adx else None,
        "plus_di":   round(adx["plus_di"],  1) if adx else None,
        "minus_di":  round(adx["minus_di"], 1) if adx else None,
        "supertrend": st["direction"] if st else None,
    }


def detect(coin_candles: dict) -> dict:
    """
    coin_candles: {coin: [candle, ...]}
    Returns a MarketState dict suitable for the strategy router.
    """
    per_coin = {}
    for coin, candles in coin_candles.items():
        if candles:
            per_coin[coin] = _direction_for_coin(candles)

    bear_coins    = [c for c, d in per_coin.items() if d["direction"] == "bear"]
    bull_coins    = [c for c, d in per_coin.items() if d["direction"] == "bull"]
    neutral_coins = [c for c, d in per_coin.items() if d["direction"] == "neutral"]
    total         = max(len(per_coin), 1)

    avg_7d   = sum(d["ret_7d"]  for d in per_coin.values()) / total
    avg_24h  = sum(d["ret_24h"] for d in per_coin.values()) / total
    btc_data = per_coin.get("BTC", {})

    bear_pct = len(bear_coins) / total
    bull_pct = len(bull_coins) / total

    if bear_pct >= 0.55:
        direction = "bear"
    elif bull_pct >= 0.55:
        direction = "bull"
    else:
        direction = "neutral"

    # Regime from BTC candles (leading indicator)
    btc_candles = coin_candles.get("BTC", [])
    regime = "unknown"
    if btc_candles:
        try:
            from analysts import regime_detector
            regime = regime_detector.detect(btc_candles).get("regime", "unknown")
        except Exception:
            pass

    return {
        "direction":    direction,
        "regime":       regime,
        "bear_coins":   len(bear_coins),
        "bull_coins":   len(bull_coins),
        "neutral_coins": len(neutral_coins),
        "total_coins":  total,
        "bear_pct":     round(bear_pct * 100, 1),
        "bull_pct":     round(bull_pct * 100, 1),
        "avg_7d":       round(avg_7d,  2),
        "avg_24h":      round(avg_24h, 2),
        "btc_7d":       round(btc_data.get("ret_7d",  0.0), 2),
        "btc_24h":      round(btc_data.get("ret_24h", 0.0), 2),
        "btc_direction": btc_data.get("direction", "neutral"),
        "per_coin":     per_coin,
    }
