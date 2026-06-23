"""
BreakdownScalp — fast momentum short on Bollinger breakdown + volume spike.

Targets the initial breakdown candle, not the sustained trend.
Tighter SL and TP targets; RSI should NOT yet be oversold (room to fall).
SHORT only.
"""
from strategies.base import Strategy, Signal, StrategyParams
from analysts import indicators as ind


class BreakdownScalp(Strategy):
    name        = "BreakdownScalp"
    label       = "Bear Breakdown Scalp"
    description = ("Fast short when price breaks Bollinger lower band on high volume. "
                   "Requires MACD momentum negative and RSI not yet oversold. "
                   "Tight SL/TP — exit quickly. SHORT only.")
    best_for    = ["bear", "trending", "ranging"]
    params      = StrategyParams(
        sl_pct=0.015, tp1_pct=0.03, tp1_frac=0.50,
        tp2_pct=0.06, tp2_frac=0.50,
        tp3_pct=0.0,  tp3_frac=0.0,
        trail_pct=0.02, conf_min=0.55, side="SHORT",
        max_hold_candles=96,   # 24 h max
    )

    def signal(self, coin: str, candles: list, regime: str, ticker: dict) -> Signal:
        if len(candles) < 60:
            return Signal("HOLD", 0.0, "insufficient history", self.name)

        c = [x["close"]  for x in candles]
        v = [x["volume"] for x in candles]

        price = c[-1]
        bb    = ind.bollinger(c)
        m     = ind.macd(c)
        r     = ind.rsi(c)

        if not bb:
            return Signal("HOLD", 0.0, "no BB", self.name)

        avg_vol   = sum(v[-20:]) / 20 if len(v) >= 20 else None
        vol_ratio = (v[-1] / avg_vol) if avg_vol and avg_vol > 0 else 1.0

        score   = 0
        reasons = []

        # Price broke below lower band
        if price < bb["lower"]:
            score += 2; reasons.append("price<BB_lower")
        elif price < bb["lower"] * 1.005:
            score += 1; reasons.append("price≈BB_lower")

        # Strong volume (capitulation spike drives the breakdown)
        if vol_ratio >= 2.5:
            score += 3; reasons.append(f"vol×{vol_ratio:.1f}")
        elif vol_ratio >= 1.8:
            score += 2; reasons.append(f"vol×{vol_ratio:.1f}")
        elif vol_ratio >= 1.3:
            score += 1; reasons.append(f"vol×{vol_ratio:.1f}")

        # MACD negative momentum
        if m and m["hist"] < 0:
            score += 1; reasons.append("MACD hist<0")
            if m["macd"] < 0:
                score += 1; reasons.append("MACD<0")

        # RSI in 35-55 range — not yet oversold, still room to fall
        if r and 30 < r < 55:
            score += 1; reasons.append(f"RSI={r:.0f}")

        # BB band-width expanding (volatility increasing = real breakdown)
        if bb["width"] > 0.04:
            score += 1; reasons.append(f"BB_w={bb['width']:.3f}")

        max_score = 9
        conf = round(min(0.95, score / max_score), 3)

        if conf >= self.params.conf_min:
            return Signal("SELL", conf, ", ".join(reasons), self.name)
        return Signal("HOLD", conf, f"no clean breakdown ({score}/{max_score})", self.name)


_instance = BreakdownScalp()
