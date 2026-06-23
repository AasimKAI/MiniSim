"""
MomentumLong — rides established bull market uptrends.

Requires full EMA stack alignment (20 > 50 > 200), Supertrend bullish,
MACD positive, ADX confirming trend strength. Wide TP targets; lets
winners run. LONG only.
"""
from strategies.base import Strategy, Signal, StrategyParams
from analysts import indicators as ind


class MomentumLong(Strategy):
    name        = "MomentumLong"
    label       = "Bull Momentum Long"
    description = ("Buys sustained bull trends with EMA stack (20>50>200), "
                   "Supertrend bullish, MACD > 0, ADX > 20. Wide TP targets "
                   "to capture extended uptrend moves. LONG only.")
    best_for    = ["bull", "trending"]
    params      = StrategyParams(
        sl_pct=0.025, tp1_pct=0.08, tp1_frac=0.33,
        tp2_pct=0.15, tp2_frac=0.33,
        tp3_pct=0.25, tp3_frac=0.34,
        trail_pct=0.05, conf_min=0.60, side="LONG",
        max_hold_candles=384,   # 4 days
    )

    def signal(self, coin: str, candles: list, regime: str, ticker: dict) -> Signal:
        if len(candles) < 210:
            return Signal("HOLD", 0.0, "insufficient history", self.name)

        c  = [x["close"] for x in candles]
        h  = [x["high"]  for x in candles]
        lo = [x["low"]   for x in candles]

        price  = c[-1]
        ema20  = ind.ema(c, 20)
        ema50  = ind.ema(c, 50)
        ema200 = ind.ema(c, 200)
        adx    = ind.dmi_adx(h, lo, c)
        st     = ind.supertrend(h, lo, c)
        m      = ind.macd(c)

        score   = 0
        reasons = []

        if ema20 and ema50 and ema20 > ema50:
            score += 1; reasons.append("EMA20>50")
        if ema50 and ema200 and ema50 > ema200:
            score += 1; reasons.append("EMA50>200")
        if ema200 and price > ema200:
            score += 1; reasons.append("price>EMA200")
        if st and st["direction"] == "up":
            score += 2; reasons.append("ST↑")
        if m and m["macd"] > 0 and m["hist"] > 0:
            score += 1; reasons.append("MACD>0")
        if adx:
            if adx["adx"] > 30:
                score += 2; reasons.append(f"ADX={adx['adx']:.0f}")
            elif adx["adx"] > 20:
                score += 1; reasons.append(f"ADX={adx['adx']:.0f}")
            if adx["plus_di"] > adx["minus_di"]:
                score += 1; reasons.append("+DI>-DI")

        # Higher timeframe confirmation
        htf = ind.resample(candles, 16)
        if len(htf) >= 30:
            htfc  = [x["close"] for x in htf]
            htfh  = [x["high"]  for x in htf]
            htflo = [x["low"]   for x in htf]
            htf_st = ind.supertrend(htfh, htflo, htfc)
            if htf_st and htf_st["direction"] == "up":
                score += 1; reasons.append("HTF_ST↑")

        max_score = 10
        conf = round(score / max_score, 3)

        if conf >= self.params.conf_min:
            return Signal("BUY", conf, ", ".join(reasons), self.name)
        return Signal("HOLD", conf, f"only {score}/{max_score} bull signals", self.name)


_instance = MomentumLong()
