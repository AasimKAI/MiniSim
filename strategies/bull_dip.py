"""
DipBuy — buys pullbacks in established bull uptrends.

Requires price above EMA200 (uptrend confirmed), RSI pulled back to 28-50
range, price near EMA50 support, and StochRSI starting to turn up.
Smaller TP targets than MomentumLong — trades the rebound, not the trend.
LONG only.
"""
from strategies.base import Strategy, Signal, StrategyParams
from analysts import indicators as ind


class DipBuy(Strategy):
    name        = "DipBuy"
    label       = "Bull Dip Buy"
    description = ("Buys pullbacks in uptrends: price > EMA200, RSI 28-50, "
                   "near EMA50 support, StochRSI turning up. Moderate TP targets. "
                   "LONG only.")
    best_for    = ["bull", "ranging"]
    params      = StrategyParams(
        sl_pct=0.02, tp1_pct=0.05, tp1_frac=0.40,
        tp2_pct=0.10, tp2_frac=0.40,
        tp3_pct=0.0,  tp3_frac=0.20,
        trail_pct=0.03, conf_min=0.55, side="LONG",
        max_hold_candles=192,
    )

    def signal(self, coin: str, candles: list, regime: str, ticker: dict) -> Signal:
        if len(candles) < 210:
            return Signal("HOLD", 0.0, "insufficient history", self.name)

        c  = [x["close"] for x in candles]
        h  = [x["high"]  for x in candles]
        lo = [x["low"]   for x in candles]

        price  = c[-1]
        ema50  = ind.ema(c, 50)
        ema200 = ind.ema(c, 200)
        r      = ind.rsi(c)
        stoch  = ind.stoch_rsi(c)
        m      = ind.macd(c)
        div    = ind.rsi_divergence(c)

        # Hard gate: must be above EMA200 (uptrend exists)
        if not ema200 or price < ema200:
            return Signal("HOLD", 0.0, "below EMA200 — not an uptrend", self.name)

        # Hard gate: RSI must be pulled back (not overbought entry)
        if r is None or r > 52:
            return Signal("HOLD", 0.0, f"RSI={r:.0f} not a dip", self.name)

        score   = 0
        reasons = []
        reasons.append("price>EMA200"); score += 1

        # RSI zone scoring
        if r < 28:
            score += 2; reasons.append(f"RSI={r:.0f}")
        elif r < 38:
            score += 3; reasons.append(f"RSI={r:.0f}")
        elif r < 50:
            score += 1; reasons.append(f"RSI={r:.0f}")

        # Near EMA50 support
        if ema50:
            dist = abs(price / ema50 - 1)
            if dist < 0.02:
                score += 2; reasons.append("at EMA50")
            elif dist < 0.04:
                score += 1; reasons.append("near EMA50")

        # StochRSI turning — %K crossing %D from below in oversold zone
        if stoch:
            if stoch["k"] > stoch["d"] and stoch["k"] < 40:
                score += 2; reasons.append("StochRSI crossing↑")
            elif stoch["k"] < 25:
                score += 1; reasons.append(f"StochK={stoch['k']:.0f}")

        # MACD histogram turning from negative to less negative
        if m and m["hist"] > -abs(m["hist"] * 0.8):
            score += 1; reasons.append("MACD hist improving")

        # Bullish divergence = strong dip signal
        if div == "bullish":
            score += 2; reasons.append("RSI div↑")

        max_score = 12
        conf = round(score / max_score, 3)

        if conf >= self.params.conf_min:
            return Signal("BUY", conf, ", ".join(reasons), self.name)
        return Signal("HOLD", conf, f"dip not confirmed ({score}/{max_score})", self.name)


_instance = DipBuy()
