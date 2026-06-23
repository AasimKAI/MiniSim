"""
DipBuy — buys pullbacks in established bull uptrends.

Hard gates: price must be above EMA200 (uptrend confirmed) and RSI must be
pulled back (≤ 52). When conditions look like a genuine dip, the LLM
evaluates the quality of the setup — divergence, StochRSI turn, proximity
to EMA50 support. LONG only.
"""
from strategies.base import Strategy, Signal, StrategyParams, LLM_TRIGGER_CONF
from analysts import indicators as ind


class DipBuy(Strategy):
    name        = "DipBuy"
    label       = "Bull Dip Buy"
    description = ("Buys pullbacks in uptrends: price > EMA200, RSI 28-50, "
                   "near EMA50 support, StochRSI turning up. Moderate TP targets. "
                   "LONG only.")
    philosophy  = (
        "In bull markets, buy meaningful pullbacks where the uptrend structure is intact. "
        "Price must be above EMA200 — if it is not, the uptrend is broken and this strategy "
        "does not apply. RSI should be pulled back to the 28–50 range (not overbought entry). "
        "The ideal setup has price near EMA50 support (within 2–4%), StochRSI starting to "
        "cross up from oversold territory, and MACD histogram improving (less negative). "
        "RSI bullish divergence is a strong additional confirmation. "
        "Moderate TP targets — we are trading the bounce back to the prior highs, not a new "
        "leg up. Reject the trade if price is still falling hard with no signs of support."
    )
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

        if r < 28:
            score += 2; reasons.append(f"RSI={r:.0f}")
        elif r < 38:
            score += 3; reasons.append(f"RSI={r:.0f}")
        elif r < 50:
            score += 1; reasons.append(f"RSI={r:.0f}")

        dist = None
        if ema50:
            dist = abs(price / ema50 - 1)
            if dist < 0.02:
                score += 2; reasons.append("at EMA50")
            elif dist < 0.04:
                score += 1; reasons.append("near EMA50")

        if stoch:
            if stoch["k"] > stoch["d"] and stoch["k"] < 40:
                score += 2; reasons.append("StochRSI crossing↑")
            elif stoch["k"] < 25:
                score += 1; reasons.append(f"StochK={stoch['k']:.0f}")

        if m and m["hist"] > -abs(m["hist"] * 0.8):
            score += 1; reasons.append("MACD hist improving")

        if div == "bullish":
            score += 2; reasons.append("RSI div↑")

        max_score = 12
        arith_conf = round(score / max_score, 3)

        if arith_conf < LLM_TRIGGER_CONF:
            return Signal("HOLD", arith_conf, f"pre-screen too weak ({score}/{max_score})", self.name)

        facts = {
            "price":            round(price, 4),
            "EMA50":            round(ema50, 4) if ema50 else None,
            "EMA200":           round(ema200, 4),
            "dist_EMA50_pct":   round(dist * 100, 2) if dist is not None else None,
            "RSI":              round(r, 1),
            "StochRSI_K":       round(stoch["k"], 1) if stoch else None,
            "StochRSI_D":       round(stoch["d"], 1) if stoch else None,
            "MACD_hist":        round(m["hist"], 6) if m else None,
            "RSI_divergence":   div,
            "regime":           regime,
            "arithmetic_signals": ", ".join(reasons) or "none",
            "arithmetic_score":   f"{score}/{max_score}",
        }

        return self._llm_confirm(coin, regime, "BUY", arith_conf, facts)


_instance = DipBuy()
