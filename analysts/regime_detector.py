"""Market regime detector: trending / ranging / volatile.

Optionally accepts macro context (Fear & Greed + funding rates) to enrich
the output dict. The base regime string is unchanged — macro data is additive.
"""
from analysts import indicators as ind


def detect(candles, fear_greed=None, funding_rates=None, dominance=None):
    """Detect market regime from candles + optional macro context.

    Returns dict with at minimum:
      regime   : "trending" | "ranging" | "volatile"
      adx      : float
      atr_pct  : float

    With macro args also returns:
      fear_greed        : int (0-100)
      fear_greed_label  : str
      avg_funding_pct   : float  (percent per 8h, e.g. 0.0100 = 0.01%)
      funding_bias      : "long_crowded" | "short_crowded" | "neutral"
      btc_dominance     : float  (% of total market cap)
      alt_dominance     : float
      dominance_signal  : "alt_season" | "btc_season" | "neutral"
    """
    h = [c["high"]  for c in candles]
    l = [c["low"]   for c in candles]
    c = [c["close"] for c in candles]

    adx     = ind.dmi_adx(h, l, c)
    atr     = ind.atr(h, l, c)
    price   = c[-1]
    vol_pct = (atr / price * 100) if (atr and price) else 0
    adx_v   = adx["adx"] if adx else 0

    if vol_pct > 3.0:
        regime = "volatile"
    elif adx_v > 25:
        regime = "trending"
    else:
        regime = "ranging"

    result = {"regime": regime, "adx": round(adx_v, 1), "atr_pct": round(vol_pct, 2)}

    # ── Fear & Greed overlay ──────────────────────────────────────────────────
    fng = fear_greed or {}
    fng_val = fng.get("value", 50)
    result["fear_greed"]       = fng_val
    result["fear_greed_label"] = fng.get("label", "Neutral")

    # ── Funding rate overlay ──────────────────────────────────────────────────
    if funding_rates:
        vals = [v for v in funding_rates.values() if v is not None]
        avg  = sum(vals) / len(vals) if vals else 0.0
        result["avg_funding_pct"] = round(avg * 100, 4)
        if avg > 0.0005:        # >0.05%/8h — market overleveraged long
            result["funding_bias"] = "long_crowded"
        elif avg < -0.0003:     # negative — market overleveraged short
            result["funding_bias"] = "short_crowded"
        else:
            result["funding_bias"] = "neutral"
    else:
        result["avg_funding_pct"] = 0.0
        result["funding_bias"]    = "neutral"

    # ── Dominance overlay ─────────────────────────────────────────────────────
    dom = dominance or {}
    btc_dom = dom.get("btc_dominance", 0.0)
    alt_dom = dom.get("alt_dominance", 0.0)
    result["btc_dominance"] = btc_dom
    result["alt_dominance"] = alt_dom
    # BTC dom > 58% = capital hiding in BTC = risk-off for alts
    # BTC dom < 48% = alt season = alts outperforming
    if btc_dom >= 58.0:
        result["dominance_signal"] = "btc_season"
    elif btc_dom <= 48.0 and btc_dom > 0:
        result["dominance_signal"] = "alt_season"
    else:
        result["dominance_signal"] = "neutral"

    return result
