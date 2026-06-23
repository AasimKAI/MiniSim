"""
BreakdownScalp — fast momentum short on Bollinger breakdown + volume spike.

Arithmetic screens for price breaking the lower Bollinger band on elevated
volume with negative MACD momentum. LLM then evaluates whether this is a
genuine breakdown or a false break. SHORT only.
"""
from strategies.base import Strategy, Signal, StrategyParams, LLM_TRIGGER_CONF
from analysts import indicators as ind


class BreakdownScalp(Strategy):
    name        = "BreakdownScalp"
    label       = "Bear Breakdown Scalp"
    description = ("Fast short when price breaks Bollinger lower band on high volume. "
                   "Requires MACD momentum negative and RSI not yet oversold. "
                   "Tight SL/TP — exit quickly. SHORT only.")
    philosophy  = (
        "Target the initial breakdown candle where price closes below the Bollinger lower band "
        "on a volume spike (1.5× or more above average). MACD histogram must be negative — "
        "momentum is already bearish. RSI should NOT yet be oversold (ideally 30–55) because "
        "we need room for the price to fall further. The wider the Bollinger band, the stronger "
        "the breakout. Exit quickly — this is a scalp, not a trend trade. Reject setups where "
        "price is already extremely extended or volume is only marginally elevated."
    )
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

        if price < bb["lower"]:
            score += 2; reasons.append("price<BB_lower")
        elif price < bb["lower"] * 1.005:
            score += 1; reasons.append("price≈BB_lower")

        if vol_ratio >= 2.5:
            score += 3; reasons.append(f"vol×{vol_ratio:.1f}")
        elif vol_ratio >= 1.8:
            score += 2; reasons.append(f"vol×{vol_ratio:.1f}")
        elif vol_ratio >= 1.3:
            score += 1; reasons.append(f"vol×{vol_ratio:.1f}")

        if m and m["hist"] < 0:
            score += 1; reasons.append("MACD hist<0")
            if m["macd"] < 0:
                score += 1; reasons.append("MACD<0")

        if r and 30 < r < 55:
            score += 1; reasons.append(f"RSI={r:.0f}")

        if bb["width"] > 0.04:
            score += 1; reasons.append(f"BB_w={bb['width']:.3f}")

        max_score = 9
        arith_conf = round(min(0.95, score / max_score), 3)

        if arith_conf < LLM_TRIGGER_CONF:
            return Signal("HOLD", arith_conf, f"pre-screen too weak ({score}/{max_score})", self.name)

        facts = {
            "price":          round(price, 4),
            "BB_lower":       round(bb["lower"], 4),
            "BB_upper":       round(bb["upper"], 4),
            "BB_mid":         round(bb["mid"], 4),
            "BB_width":       round(bb["width"], 4),
            "volume_ratio":   round(vol_ratio, 2),
            "MACD":           round(m["macd"], 6) if m else None,
            "MACD_hist":      round(m["hist"], 6) if m else None,
            "RSI":            round(r, 1) if r else None,
            "regime":         regime,
            "arithmetic_signals": ", ".join(reasons) or "none",
            "arithmetic_score":   f"{score}/{max_score}",
        }

        return self._llm_confirm(coin, regime, "SELL", arith_conf, facts)


_instance = BreakdownScalp()
