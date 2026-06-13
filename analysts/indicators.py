"""
v5 indicator library — pure Python (no hard numpy dependency).

v4 had: RSI, MACD, EMA, Bollinger, ATR.
v5 adds: Stochastic RSI, ADX/DMI, Supertrend, VWAP, OBV, Ichimoku,
Keltner channels, and bullish/bearish RSI divergence — plus a
multi-timeframe helper so signals are confirmed on a higher timeframe.

Every function takes lists of floats (candles) and returns plain numbers,
so results serialise straight to JSON for the dashboard.
"""
from math import isnan

# ---------- basics ----------
def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period

def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e

def _ema_series(values, period):
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out

def rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100 - (100 / (1 + rs))

def macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return None
    ef, es = _ema_series(closes, fast), _ema_series(closes, slow)
    n = min(len(ef), len(es))
    macd_line = [ef[-n + i] - es[-n + i] for i in range(n)]
    sig = _ema_series(macd_line, signal)
    if not sig:
        return None
    hist = macd_line[-1] - sig[-1]
    return {"macd": macd_line[-1], "signal": sig[-1], "hist": hist}

def bollinger(closes, period=20, mult=2.0):
    if len(closes) < period:
        return None
    mid = sma(closes, period)
    window = closes[-period:]
    var = sum((c - mid) ** 2 for c in window) / period
    sd = var ** 0.5
    return {"upper": mid + mult * sd, "mid": mid, "lower": mid - mult * sd, "width": (2 * mult * sd) / mid if mid else 0}

def atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    a = sum(trs[:period]) / period
    for t in trs[period:]:
        a = (a * (period - 1) + t) / period
    return a

# ---------- v5 additions ----------
def stoch_rsi(closes, period=14, smooth_k=3, smooth_d=3):
    """Stochastic RSI with proper %K and %D smoothing (0-100)."""
    rsis = []
    for i in range(period + 1, len(closes) + 1):
        r = rsi(closes[:i], period)
        if r is not None:
            rsis.append(r)
    if len(rsis) < period + smooth_k + smooth_d:
        return None
    raw = []
    for j in range(period, len(rsis) + 1):
        win = rsis[j - period:j]
        lo, hi = min(win), max(win)
        raw.append(0.0 if hi == lo else (win[-1] - lo) / (hi - lo) * 100)
    # %K = SMA of raw over smooth_k ; %D = SMA of %K over smooth_d
    k_series = [sum(raw[i - smooth_k:i]) / smooth_k for i in range(smooth_k, len(raw) + 1)]
    if len(k_series) < smooth_d:
        return None
    k = k_series[-1]
    d = sum(k_series[-smooth_d:]) / smooth_d
    return {"k": round(k, 2), "d": round(d, 2)}

def dmi_adx(highs, lows, closes, period=14):
    """ADX + Directional Movement. ADX>25 = strong trend."""
    if len(closes) < period * 2:
        return None
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(closes)):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    def _smooth(x):
        s = sum(x[:period])
        out = [s]
        for v in x[period:]:
            s = s - s / period + v
            out.append(s)
        return out
    str_, spdm, smdm = _smooth(trs), _smooth(plus_dm), _smooth(minus_dm)
    n = min(len(str_), len(spdm), len(smdm))
    dxs = []
    for i in range(n):
        if str_[i] == 0:
            continue
        pdi = 100 * spdm[i] / str_[i]
        mdi = 100 * smdm[i] / str_[i]
        denom = pdi + mdi
        dxs.append(0.0 if denom == 0 else 100 * abs(pdi - mdi) / denom)
    if len(dxs) < period:
        return None
    adx = sum(dxs[-period:]) / period
    pdi = 100 * spdm[-1] / str_[-1] if str_[-1] else 0
    mdi = 100 * smdm[-1] / str_[-1] if str_[-1] else 0
    return {"adx": adx, "plus_di": pdi, "minus_di": mdi}

def supertrend(highs, lows, closes, period=10, mult=3.0):
    """Proper Supertrend with band carry-over and trend flips."""
    n = len(closes)
    if n < period + 2:
        return None
    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i],
                      abs(highs[i] - closes[i - 1]),
                      abs(lows[i] - closes[i - 1])))
    atr_s = [sum(tr[:period]) / period]            # Wilder ATR series
    for i in range(period, n):
        atr_s.append((atr_s[-1] * (period - 1) + tr[i]) / period)
    direction = 1                                  # 1 up, -1 down
    final_upper = final_lower = None
    for k in range(len(atr_s)):
        i = period - 1 + k
        hl2 = (highs[i] + lows[i]) / 2
        a = atr_s[k]
        bu, bl = hl2 + mult * a, hl2 - mult * a
        if final_upper is None:
            final_upper, final_lower = bu, bl
        else:
            final_upper = bu if (bu < final_upper or closes[i - 1] > final_upper) else final_upper
            final_lower = bl if (bl > final_lower or closes[i - 1] < final_lower) else final_lower
        if closes[i] > final_upper:
            direction = 1
        elif closes[i] < final_lower:
            direction = -1
    return {"direction": "up" if direction == 1 else "down",
            "stop": final_lower if direction == 1 else final_upper, "atr": atr_s[-1]}

def vwap(highs, lows, closes, volumes):
    """Volume Weighted Average Price."""
    if not volumes or sum(volumes) == 0:
        return None
    num = sum(((highs[i] + lows[i] + closes[i]) / 3) * volumes[i] for i in range(len(closes)))
    return num / sum(volumes)

def obv(closes, volumes):
    """On-Balance Volume + its short trend."""
    if len(closes) < 2:
        return None
    o = 0.0
    series = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            o += volumes[i]
        elif closes[i] < closes[i - 1]:
            o -= volumes[i]
        series.append(o)
    trend = "rising" if len(series) > 5 and series[-1] > series[-5] else "falling"
    return {"obv": o, "trend": trend}

def ichimoku(highs, lows, closes):
    """Ichimoku cloud — conversion/base lines + cloud bias."""
    def mid(h, l, p):
        if len(h) < p:
            return None
        return (max(h[-p:]) + min(l[-p:])) / 2
    conv = mid(highs, lows, 9)
    base = mid(highs, lows, 26)
    if conv is None or base is None:
        return None
    span_a = (conv + base) / 2
    span_b = mid(highs, lows, 52)
    bias = "bullish" if closes[-1] > (span_b or span_a) and conv > base else \
           "bearish" if closes[-1] < (span_b or span_a) and conv < base else "neutral"
    return {"conversion": conv, "base": base, "span_a": span_a, "span_b": span_b, "bias": bias}

def keltner(highs, lows, closes, period=20, mult=2.0):
    mid = ema(closes, period)
    a = atr(highs, lows, closes, period)
    if mid is None or a is None:
        return None
    return {"upper": mid + mult * a, "mid": mid, "lower": mid - mult * a}

def _pivot_low(vals, w=3):
    """Index of the most recent confirmed swing low (a bar lower than w neighbours)."""
    for i in range(len(vals) - w - 1, w - 1, -1):
        seg = vals[i - w:i + w + 1]
        if vals[i] == min(seg):
            return i
    return None

def _pivot_high(vals, w=3):
    for i in range(len(vals) - w - 1, w - 1, -1):
        seg = vals[i - w:i + w + 1]
        if vals[i] == max(seg):
            return i
    return None

def rsi_divergence(closes, period=14, lookback=40):
    """Confirmed-pivot divergence between price and RSI (reduces false positives).
    Requires TWO swing lows/highs and an opposing RSI slope."""
    if len(closes) < period + lookback + 5:
        return "none"
    rsis = []
    for i in range(period + 1, len(closes) + 1):
        r = rsi(closes[:i], period)
        if r is not None:
            rsis.append(r)
    n = min(len(closes), len(rsis))
    px, rs = closes[-n:], rsis[-n:]

    # bullish: price makes a lower swing-low while RSI makes a higher swing-low
    pl2 = _pivot_low(px)
    if pl2 is not None:
        pl1 = _pivot_low(px[:pl2 - 1]) if pl2 > 6 else None
        if pl1 is not None and px[pl2] < px[pl1] and rs[pl2] > rs[pl1]:
            return "bullish"
    # bearish: price makes a higher swing-high while RSI makes a lower swing-high
    ph2 = _pivot_high(px)
    if ph2 is not None:
        ph1 = _pivot_high(px[:ph2 - 1]) if ph2 > 6 else None
        if ph1 is not None and px[ph2] > px[ph1] and rs[ph2] < rs[ph1]:
            return "bearish"
    return "none"

def resample(candles, factor):
    """Crude higher-timeframe resample: group `factor` candles into one.
    candles = list of dicts with high/low/close/volume/open."""
    out = []
    for i in range(0, len(candles) - factor + 1, factor):
        grp = candles[i:i + factor]
        out.append({
            "open": grp[0]["open"],
            "high": max(c["high"] for c in grp),
            "low": min(c["low"] for c in grp),
            "close": grp[-1]["close"],
            "volume": sum(c["volume"] for c in grp),
        })
    return out
