"""
RangeScalp — RSI mean-reversion in ranging / low-ADX markets.

Requires ADX < 22 (no real trend). Buys at RSI < 30 + BB lower band touch;
sells at RSI > 70 + BB upper band touch. Both directions.
Tight SL/TP — exits quickly because ranging markets snap back.
"""
from strategies.base import Strategy, Signal, StrategyParams
from analysts import indicators as ind


class RangeScalp(Strategy):
    name        = "RangeScalp"
    label       = "Range Mean Reversion"
    description = ("RSI/Bollinger mean-reversion in ranging markets (ADX < 22). "
                   "Buys oversold extremes, sells overbought extremes. "
                   "Tight SL/TP. Both directions.")
    best_for    = ["ranging"]
    params      = StrategyParams(
        sl_pct=0.015, tp1_pct=0.03, tp1_frac=0.50,
        tp2_pct=0.05, tp2_frac=0.50,
        tp3_pct=0.0,  tp3_frac=0.0,
        trail_pct=0.02, conf_min=0.60, side="BOTH",
        max_hold_candles=80,    # 20 h max — mean reversion should happen quickly
    )

    def signal(self, coin: str, candles: list, regime: str, ticker: dict) -> Signal:
        if len(candles) < 60:
            return Signal("HOLD", 0.0, "insufficient history", self.name)

        c  = [x["close"] for x in candles]
        h  = [x["high"]  for x in candles]
        lo = [x["low"]   for x in candles]

        price = c[-1]
        r     = ind.rsi(c)
        stoch = ind.stoch_rsi(c)
        bb    = ind.bollinger(c)
        adx   = ind.dmi_adx(h, lo, c)
        kelt  = ind.keltner(h, lo, c)

        # Hard gate: must be ranging (low ADX)
        if adx and adx["adx"] > 25:
            return Signal("HOLD", 0.0, f"ADX={adx['adx']:.0f} — trending", self.name)

        if r is None or bb is None:
            return Signal("HOLD", 0.0, "indicators unavailable", self.name)

        # ── Oversold → BUY ────────────────────────────────────────────────────
        if r < 35:
            score   = 0
            reasons = []

            if r < 25:
                score += 3; reasons.append(f"RSI={r:.0f}")
            elif r < 30:
                score += 2; reasons.append(f"RSI={r:.0f}")
            else:
                score += 1; reasons.append(f"RSI={r:.0f}")

            if price < bb["lower"]:
                score += 2; reasons.append("price<BB_lower")
            elif price < bb["mid"]:
                score += 1

            if stoch and stoch["k"] < 20:
                score += 1; reasons.append(f"StochK={stoch['k']:.0f}")
            if stoch and stoch["k"] > stoch["d"]:
                score += 1; reasons.append("StochRSI turning↑")
            if kelt and price < kelt["lower"]:
                score += 1; reasons.append("price<Keltner")

            max_score = 8
            conf = round(min(0.95, score / max_score), 3)
            if conf >= self.params.conf_min:
                return Signal("BUY", conf, ", ".join(reasons), self.name)

        # ── Overbought → SELL ─────────────────────────────────────────────────
        elif r > 65:
            score   = 0
            reasons = []

            if r > 75:
                score += 3; reasons.append(f"RSI={r:.0f}")
            elif r > 70:
                score += 2; reasons.append(f"RSI={r:.0f}")
            else:
                score += 1; reasons.append(f"RSI={r:.0f}")

            if price > bb["upper"]:
                score += 2; reasons.append("price>BB_upper")
            elif price > bb["mid"]:
                score += 1

            if stoch and stoch["k"] > 80:
                score += 1; reasons.append(f"StochK={stoch['k']:.0f}")
            if stoch and stoch["k"] < stoch["d"]:
                score += 1; reasons.append("StochRSI turning↓")
            if kelt and price > kelt["upper"]:
                score += 1; reasons.append("price>Keltner")

            max_score = 8
            conf = round(min(0.95, score / max_score), 3)
            if conf >= self.params.conf_min:
                return Signal("SELL", conf, ", ".join(reasons), self.name)

        return Signal("HOLD", 0.0, f"RSI={r:.0f} mid-range", self.name)


_instance = RangeScalp()
