"""
OversoldBounce — buys deeply oversold dead-cat bounces in bear markets.

Looks for RSI < 28, StochRSI < 15, BB extension, and ideally RSI bullish
divergence. Short-hold scalp targeting a 3-6 % bounce before the bear
resumes. LONG only, tight SL.
"""
from strategies.base import Strategy, Signal, StrategyParams
from analysts import indicators as ind


class OversoldBounce(Strategy):
    name        = "OversoldBounce"
    label       = "Bear Oversold Bounce"
    description = ("Catches dead-cat bounces in bear markets. Buys when RSI < 28, "
                   "StochRSI extreme, price extended below BB. Tight SL/TP — scalp only. "
                   "LONG only.")
    best_for    = ["bear", "ranging"]
    params      = StrategyParams(
        sl_pct=0.015, tp1_pct=0.03, tp1_frac=0.50,
        tp2_pct=0.06, tp2_frac=0.50,
        tp3_pct=0.0,  tp3_frac=0.0,
        trail_pct=0.02, conf_min=0.55, side="LONG",
        max_hold_candles=64,   # 16 h max — bounce plays are short
    )

    def signal(self, coin: str, candles: list, regime: str, ticker: dict) -> Signal:
        if len(candles) < 80:
            return Signal("HOLD", 0.0, "insufficient history", self.name)

        c = [x["close"] for x in candles]
        h = [x["high"]  for x in candles]
        lo = [x["low"]  for x in candles]
        v = [x["volume"] for x in candles]

        price = c[-1]
        r     = ind.rsi(c)
        stoch = ind.stoch_rsi(c)
        bb    = ind.bollinger(c)
        div   = ind.rsi_divergence(c)

        avg_vol   = sum(v[-20:]) / 20 if len(v) >= 20 else None
        vol_ratio = (v[-1] / avg_vol) if avg_vol and avg_vol > 0 else 1.0

        score   = 0
        reasons = []

        # Deep RSI oversold
        if r is not None:
            if r < 20:
                score += 3; reasons.append(f"RSI={r:.0f}")
            elif r < 25:
                score += 2; reasons.append(f"RSI={r:.0f}")
            elif r < 30:
                score += 1; reasons.append(f"RSI={r:.0f}")
            else:
                return Signal("HOLD", 0.0, f"RSI={r:.0f} not oversold", self.name)

        # StochRSI extreme
        if stoch:
            if stoch["k"] < 10:
                score += 2; reasons.append(f"StochK={stoch['k']:.0f}")
            elif stoch["k"] < 20:
                score += 1; reasons.append(f"StochK={stoch['k']:.0f}")
            # %K crossing above %D = momentum starting to turn
            if stoch["k"] > stoch["d"]:
                score += 1; reasons.append("StochRSI crossing↑")

        # Price well extended below lower BB
        if bb:
            if price < bb["lower"] * 0.97:
                score += 2; reasons.append("price<<BB_lower")
            elif price < bb["lower"]:
                score += 1; reasons.append("price<BB_lower")

        # RSI bullish divergence (price lower low, RSI higher low)
        if div == "bullish":
            score += 2; reasons.append("RSI div↑")

        # Capitulation volume spike
        if vol_ratio >= 2.0:
            score += 1; reasons.append(f"vol×{vol_ratio:.1f}")

        max_score = 11
        conf = round(score / max_score, 3)

        if conf >= self.params.conf_min:
            return Signal("BUY", conf, ", ".join(reasons), self.name)
        return Signal("HOLD", conf, f"not deeply oversold ({score}/{max_score})", self.name)


_instance = OversoldBounce()
