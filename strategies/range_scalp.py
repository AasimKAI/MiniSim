"""
RangeScalp — RSI mean-reversion in ranging / low-ADX markets.

Hard gate: ADX must be below 25 (no real trend). Arithmetic screens for
RSI/Bollinger extremes. When a plausible extreme is detected, the LLM
evaluates whether the range structure is clean enough to trade both sides.
"""
from strategies.base import Strategy, Signal, StrategyParams, LLM_TRIGGER_CONF
from analysts import indicators as ind


class RangeScalp(Strategy):
    name        = "RangeScalp"
    label       = "Range Mean Reversion"
    description = ("RSI/Bollinger mean-reversion in ranging markets (ADX < 25). "
                   "Buys oversold extremes, sells overbought extremes. "
                   "Tight SL/TP. Both directions.")
    philosophy  = (
        "Trade mean-reversion only in confirmed ranging markets where ADX is below 25 and "
        "price is oscillating between clear Bollinger band boundaries. "
        "BUY when RSI is below 30 AND price is touching or below the lower Bollinger band, "
        "with StochRSI showing early signs of turning up. "
        "SELL when RSI is above 70 AND price is at or above the upper Bollinger band, "
        "with StochRSI turning down. Keltner channel confirmation strengthens the signal. "
        "Reject any trade where ADX is rising (range breaking down) or where one side of "
        "the range has already been broken with expanding volume. "
        "This is a tight scalp — exit at TP1 and TP2, do not hold for extended moves."
    )
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

        arith_action = "HOLD"
        score        = 0
        reasons      = []

        # ── Oversold → BUY ────────────────────────────────────────────────────
        if r < 35:
            arith_action = "BUY"
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

        # ── Overbought → SELL ─────────────────────────────────────────────────
        elif r > 65:
            arith_action = "SELL"
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

        else:
            return Signal("HOLD", 0.0, f"RSI={r:.0f} mid-range", self.name)

        max_score  = 8
        arith_conf = round(min(0.95, score / max_score), 3)

        if arith_conf < LLM_TRIGGER_CONF:
            return Signal("HOLD", arith_conf, f"pre-screen too weak ({score}/{max_score})", self.name)

        facts = {
            "price":          round(price, 4),
            "RSI":            round(r, 1),
            "BB_lower":       round(bb["lower"], 4),
            "BB_upper":       round(bb["upper"], 4),
            "BB_mid":         round(bb["mid"], 4),
            "BB_width":       round(bb["width"], 4),
            "StochRSI_K":     round(stoch["k"], 1) if stoch else None,
            "StochRSI_D":     round(stoch["d"], 1) if stoch else None,
            "ADX":            round(adx["adx"], 1) if adx else None,
            "Keltner_lower":  round(kelt["lower"], 4) if kelt else None,
            "Keltner_upper":  round(kelt["upper"], 4) if kelt else None,
            "regime":         regime,
            "arithmetic_signals": ", ".join(reasons) or "none",
            "arithmetic_score":   f"{score}/{max_score}",
        }

        return self._llm_confirm(coin, regime, arith_action, arith_conf, facts)


_instance = RangeScalp()
