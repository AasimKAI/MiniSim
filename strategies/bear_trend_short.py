"""
TrendShort — controlled downtrend following.

Arithmetic gates screen for full EMA stack alignment, Supertrend bearish,
MACD negative, and ADX confirming a real trend. When the pre-screen passes,
the LLM evaluates the full indicator picture and decides whether to trade.
SHORT only.
"""
from strategies.base import Strategy, Signal, StrategyParams, LLM_TRIGGER_CONF
from analysts import indicators as ind


class TrendShort(Strategy):
    name        = "TrendShort"
    label       = "Bear Trend Short"
    description = ("Shorts strong, controlled downtrends. Requires EMA stack alignment, "
                   "Supertrend bearish, MACD < 0, ADX > 25. Wide TP targets for sustained moves.")
    philosophy  = (
        "Enter shorts only when a genuine downtrend is confirmed across multiple timeframes. "
        "All three EMAs must be stacked bearishly (20 < 50 < 200), Supertrend must be down on "
        "both the 15m and 4h timeframe, MACD must be negative, and ADX must show trend strength "
        "above 25. Avoid shorting in choppy markets or when any major EMA alignment is missing. "
        "Wide TP targets because real bear trends are sustained — do not exit too early."
    )
    best_for    = ["bear", "trending"]
    params      = StrategyParams(
        sl_pct=0.025, tp1_pct=0.08, tp1_frac=0.33,
        tp2_pct=0.15, tp2_frac=0.33,
        tp3_pct=0.25, tp3_frac=0.34,
        trail_pct=0.05, conf_min=0.60, side="SHORT",
        max_hold_candles=384,   # 4 days — bear trends take time
    )

    def signal(self, coin: str, candles: list, regime: str, ticker: dict) -> Signal:
        if len(candles) < 210:
            return Signal("HOLD", 0.0, "insufficient history", self.name)

        c  = [x["close"]  for x in candles]
        h  = [x["high"]   for x in candles]
        lo = [x["low"]    for x in candles]

        price  = c[-1]
        ema20  = ind.ema(c, 20)
        ema50  = ind.ema(c, 50)
        ema200 = ind.ema(c, 200)
        adx    = ind.dmi_adx(h, lo, c)
        st     = ind.supertrend(h, lo, c)
        m      = ind.macd(c)

        score   = 0
        reasons = []

        if ema20 and ema50 and ema20 < ema50:
            score += 1; reasons.append("EMA20<50")
        if ema50 and ema200 and ema50 < ema200:
            score += 1; reasons.append("EMA50<200")
        if ema200 and price < ema200:
            score += 1; reasons.append("price<EMA200")
        if st and st["direction"] == "down":
            score += 2; reasons.append("ST↓")
        if m and m["macd"] < 0 and m["hist"] < 0:
            score += 1; reasons.append("MACD<0")
        if adx:
            if adx["adx"] > 30:
                score += 2; reasons.append(f"ADX={adx['adx']:.0f}")
            elif adx["adx"] > 25:
                score += 1; reasons.append(f"ADX={adx['adx']:.0f}")
            if adx["minus_di"] > adx["plus_di"]:
                score += 1; reasons.append("-DI>+DI")

        htf_st_dir = None
        htf = ind.resample(candles, 16)
        if len(htf) >= 30:
            htfc  = [x["close"] for x in htf]
            htfh  = [x["high"]  for x in htf]
            htflo = [x["low"]   for x in htf]
            htf_st = ind.supertrend(htfh, htflo, htfc)
            if htf_st:
                htf_st_dir = htf_st["direction"]
                if htf_st_dir == "down":
                    score += 1; reasons.append("HTF_ST↓")

        max_score = 10
        arith_conf = round(score / max_score, 3)

        if arith_conf < LLM_TRIGGER_CONF:
            return Signal("HOLD", arith_conf, f"pre-screen too weak ({score}/{max_score})", self.name)

        facts = {
            "price":         round(price, 4),
            "EMA20":         round(ema20, 4) if ema20 else None,
            "EMA50":         round(ema50, 4) if ema50 else None,
            "EMA200":        round(ema200, 4) if ema200 else None,
            "supertrend_15m": st["direction"] if st else None,
            "supertrend_4h":  htf_st_dir,
            "MACD":          round(m["macd"], 6) if m else None,
            "MACD_hist":     round(m["hist"], 6) if m else None,
            "ADX":           round(adx["adx"], 1) if adx else None,
            "+DI":           round(adx["plus_di"], 1) if adx else None,
            "-DI":           round(adx["minus_di"], 1) if adx else None,
            "regime":        regime,
            "arithmetic_signals": ", ".join(reasons) or "none",
            "arithmetic_score":   f"{score}/{max_score}",
        }

        return self._llm_confirm(coin, regime, "SELL", arith_conf, facts)


_instance = TrendShort()
