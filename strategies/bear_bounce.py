"""
OversoldBounce — buys deeply oversold dead-cat bounces in bear markets.

Hard gate: RSI must be < 30 (no LLM cost otherwise). When deeply oversold
conditions are detected arithmetically, the LLM evaluates whether a genuine
bounce is likely — considering divergence, StochRSI turn, and volume. LONG only.
"""
from strategies.base import Strategy, Signal, StrategyParams, LLM_TRIGGER_CONF
from analysts import indicators as ind


class OversoldBounce(Strategy):
    name        = "OversoldBounce"
    label       = "Bear Oversold Bounce"
    description = ("Catches dead-cat bounces in bear markets. Buys when RSI < 28, "
                   "StochRSI extreme, price extended below BB. Tight SL/TP — scalp only. "
                   "LONG only.")
    philosophy  = (
        "In bear markets, extreme oversold readings can produce short-lived bounces of 3–6%. "
        "Buy only when RSI is genuinely deeply oversold (under 28 ideally), StochRSI is showing "
        "early signs of turning up (%K crossing %D), and price is extended below the lower "
        "Bollinger band. RSI bullish divergence (price makes a lower low but RSI does not) is "
        "a strong additional signal. Capitulation volume spikes increase conviction. "
        "This is a SCALP — the bear trend resumes quickly. Exit at TP1 or TP2; do not hold. "
        "Reject the trade if there is no sign of momentum turning (StochRSI still falling)."
    )
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

        c  = [x["close"]  for x in candles]
        lo = [x["low"]    for x in candles]
        v  = [x["volume"] for x in candles]

        price = c[-1]
        r     = ind.rsi(c)
        stoch = ind.stoch_rsi(c)
        bb    = ind.bollinger(c)
        div   = ind.rsi_divergence(c)

        avg_vol   = sum(v[-20:]) / 20 if len(v) >= 20 else None
        vol_ratio = (v[-1] / avg_vol) if avg_vol and avg_vol > 0 else 1.0

        # Hard gate: RSI must be oversold — no LLM cost otherwise
        if r is None or r >= 30:
            return Signal("HOLD", 0.0, f"RSI={r:.0f if r else '?'} not oversold", self.name)

        score   = 0
        reasons = []

        if r < 20:
            score += 3; reasons.append(f"RSI={r:.0f}")
        elif r < 25:
            score += 2; reasons.append(f"RSI={r:.0f}")
        else:
            score += 1; reasons.append(f"RSI={r:.0f}")

        if stoch:
            if stoch["k"] < 10:
                score += 2; reasons.append(f"StochK={stoch['k']:.0f}")
            elif stoch["k"] < 20:
                score += 1; reasons.append(f"StochK={stoch['k']:.0f}")
            if stoch["k"] > stoch["d"]:
                score += 1; reasons.append("StochRSI crossing↑")

        if bb:
            if price < bb["lower"] * 0.97:
                score += 2; reasons.append("price<<BB_lower")
            elif price < bb["lower"]:
                score += 1; reasons.append("price<BB_lower")

        if div == "bullish":
            score += 2; reasons.append("RSI div↑")

        if vol_ratio >= 2.0:
            score += 1; reasons.append(f"vol×{vol_ratio:.1f}")

        max_score = 11
        arith_conf = round(score / max_score, 3)

        if arith_conf < LLM_TRIGGER_CONF:
            return Signal("HOLD", arith_conf, f"pre-screen too weak ({score}/{max_score})", self.name)

        facts = {
            "price":          round(price, 4),
            "RSI":            round(r, 1),
            "StochRSI_K":     round(stoch["k"], 1) if stoch else None,
            "StochRSI_D":     round(stoch["d"], 1) if stoch else None,
            "BB_lower":       round(bb["lower"], 4) if bb else None,
            "BB_mid":         round(bb["mid"], 4) if bb else None,
            "RSI_divergence": div,
            "volume_ratio":   round(vol_ratio, 2),
            "regime":         regime,
            "arithmetic_signals": ", ".join(reasons) or "none",
            "arithmetic_score":   f"{score}/{max_score}",
        }

        return self._llm_confirm(coin, regime, "BUY", arith_conf, facts)


_instance = OversoldBounce()
