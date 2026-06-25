"""
MicroScalp — ultra-tight mean-reversion scalp inside a Bollinger squeeze.

Designed for small accounts: SL 0.8%, TP1 1.5%, TP2 3% — small gains compound.
Stricter than RangeScalp: requires a Bollinger squeeze (narrow bands) before
entry, confirming volatility has compressed enough for a clean reversal.
ADX must be below 20 (tighter gate than RangeScalp's 25).
Max hold: 6 hours. Both directions.
"""
from strategies.base import Strategy, Signal, StrategyParams, LLM_TRIGGER_CONF
from analysts import indicators as ind

# BB width (as fraction of price) below which we consider the market squeezed.
_SQUEEZE_THRESHOLD = 0.03


class MicroScalp(Strategy):
    name        = "MicroScalp"
    label       = "Micro Range Scalp"
    description = ("Ultra-tight mean-reversion inside a Bollinger squeeze (BB width < 3%). "
                   "SL 0.8%, TP1 1.5%, TP2 3%. ADX < 20 required. "
                   "Small-account friendly — small consistent gains, 6 h max hold.")
    philosophy  = (
        "Only trade when the Bollinger Bands are squeezed (BB width < 3% of price) — "
        "compressed volatility is a prerequisite for a clean mean-reversion move. "
        "BUY when price is at or below the lower band, RSI below 32, and StochRSI "
        "below 20 and crossing up. SELL when price is at or above the upper band, "
        "RSI above 68, and StochRSI above 80 and crossing down. "
        "ADX must be below 20 — any trend strength means this strategy does not apply. "
        "Keltner channel confirmation (price outside Keltner when at BB extreme) strengthens. "
        "SL is very tight (0.8%) because in a genuine squeeze the entry is precise; "
        "if price blows past the band without reversing, exit fast. "
        "TP1 at 1.5% (take 60% off), TP2 at 3%. Max 6-hour hold — "
        "if it has not reverted in 6 hours the range has broken."
    )
    best_for    = ["ranging"]
    params      = StrategyParams(
        sl_pct=0.008, tp1_pct=0.015, tp1_frac=0.60,
        tp2_pct=0.030, tp2_frac=0.40,
        tp3_pct=0.0,  tp3_frac=0.0,
        trail_pct=0.010, conf_min=0.55, side="BOTH",
        max_hold_candles=24,    # 6 h at 15 min candles
    )

    def signal(self, coin: str, candles: list, regime: str, ticker: dict) -> Signal:
        if len(candles) < 60:
            return Signal("HOLD", 0.0, "insufficient history", self.name)

        c  = [x["close"] for x in candles]
        h  = [x["high"]  for x in candles]
        lo = [x["low"]   for x in candles]

        price = c[-1]
        bb    = ind.bollinger(c)
        r     = ind.rsi(c)
        stoch = ind.stoch_rsi(c)
        adx   = ind.dmi_adx(h, lo, c)
        kelt  = ind.keltner(h, lo, c)

        if bb is None or r is None:
            return Signal("HOLD", 0.0, "indicators unavailable", self.name)

        # Hard gate: Bollinger squeeze required
        if bb["width"] > _SQUEEZE_THRESHOLD:
            return Signal("HOLD", 0.0, f"BB width={bb['width']:.3f} — no squeeze", self.name)

        # Hard gate: must not be trending
        if adx and adx["adx"] > 20:
            return Signal("HOLD", 0.0, f"ADX={adx['adx']:.0f} — trending", self.name)

        arith_action = "HOLD"
        score        = 0
        reasons      = []

        # ── Oversold → BUY ────────────────────────────────────────────────────
        if r < 32:
            arith_action = "BUY"
            if r < 22:
                score += 3; reasons.append(f"RSI={r:.0f}")
            elif r < 28:
                score += 2; reasons.append(f"RSI={r:.0f}")
            else:
                score += 1; reasons.append(f"RSI={r:.0f}")

            if price <= bb["lower"]:
                score += 3; reasons.append("price≤BB_lower")
            elif price < bb["mid"]:
                score += 1

            if stoch:
                if stoch["k"] < 15 and stoch["k"] > stoch["d"]:
                    score += 2; reasons.append("StochRSI crossing↑")
                elif stoch["k"] < 20:
                    score += 1; reasons.append(f"StochK={stoch['k']:.0f}")

            if kelt and price < kelt["lower"]:
                score += 1; reasons.append("price<Keltner")

        # ── Overbought → SELL ─────────────────────────────────────────────────
        elif r > 68:
            arith_action = "SELL"
            if r > 78:
                score += 3; reasons.append(f"RSI={r:.0f}")
            elif r > 72:
                score += 2; reasons.append(f"RSI={r:.0f}")
            else:
                score += 1; reasons.append(f"RSI={r:.0f}")

            if price >= bb["upper"]:
                score += 3; reasons.append("price≥BB_upper")
            elif price > bb["mid"]:
                score += 1

            if stoch:
                if stoch["k"] > 85 and stoch["k"] < stoch["d"]:
                    score += 2; reasons.append("StochRSI crossing↓")
                elif stoch["k"] > 80:
                    score += 1; reasons.append(f"StochK={stoch['k']:.0f}")

            if kelt and price > kelt["upper"]:
                score += 1; reasons.append("price>Keltner")

        else:
            return Signal("HOLD", 0.0, f"RSI={r:.0f} mid-range", self.name)

        max_score  = 9
        arith_conf = round(min(0.95, score / max_score), 3)

        if arith_conf < LLM_TRIGGER_CONF:
            return Signal("HOLD", arith_conf, f"pre-screen too weak ({score}/{max_score})", self.name)

        facts = {
            "price":         round(price, 4),
            "RSI":           round(r, 1),
            "BB_lower":      round(bb["lower"], 4),
            "BB_upper":      round(bb["upper"], 4),
            "BB_mid":        round(bb["mid"], 4),
            "BB_width":      round(bb["width"], 4),
            "StochRSI_K":    round(stoch["k"], 1) if stoch else None,
            "StochRSI_D":    round(stoch["d"], 1) if stoch else None,
            "ADX":           round(adx["adx"], 1) if adx else None,
            "Keltner_lower": round(kelt["lower"], 4) if kelt else None,
            "Keltner_upper": round(kelt["upper"], 4) if kelt else None,
            "regime":        regime,
            "arithmetic_signals": ", ".join(reasons) or "none",
            "arithmetic_score":   f"{score}/{max_score}",
        }

        return self._llm_confirm(coin, regime, arith_action, arith_conf, facts)


_instance = MicroScalp()
