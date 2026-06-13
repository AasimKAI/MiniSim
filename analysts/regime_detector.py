"""Market regime detector: trending / ranging / volatile (no price prediction)."""
from analysts import indicators as ind

def detect(candles):
    h=[c["high"] for c in candles]; l=[c["low"] for c in candles]; c=[c["close"] for c in candles]
    adx = ind.dmi_adx(h, l, c)
    bb = ind.bollinger(c)
    atr = ind.atr(h, l, c)
    price = c[-1]
    vol_pct = (atr / price * 100) if (atr and price) else 0
    adx_v = adx["adx"] if adx else 0
    if vol_pct > 3.0:
        return {"regime": "volatile", "adx": round(adx_v,1), "atr_pct": round(vol_pct,2)}
    if adx_v > 25:
        return {"regime": "trending", "adx": round(adx_v,1), "atr_pct": round(vol_pct,2)}
    return {"regime": "ranging", "adx": round(adx_v,1), "atr_pct": round(vol_pct,2)}
