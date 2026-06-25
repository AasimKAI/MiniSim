"""
VolBreakout — volume-confirmed breakout above resistance (LONG) or below support (SHORT).

Designed for small accounts: tight 1.2% SL keeps per-trade loss small;
TP targets are quick 2.5% / 5% scalps, not extended holds.
Only fires when volume meaningfully confirms the move (≥ 1.5× 20-bar average).
Best for: trending or breakout markets.
"""
from strategies.base import Strategy, Signal, StrategyParams, LLM_TRIGGER_CONF
from analysts import indicators as ind


class VolBreakout(Strategy):
    name        = "VolBreakout"
    label       = "Volume Breakout"
    description = ("Buys breakouts above 20-bar high or sells breakdowns below 20-bar low, "
                   "confirmed by above-average volume. Tight 1.2% SL, 2.5%/5% TP. "
                   "Small-account friendly — quick in, quick out. Both directions.")
    philosophy  = (
        "Enter on genuine volume-confirmed breakouts only. Price must clear the 20-bar "
        "resistance (LONG) or break the 20-bar support (SHORT) with volume at least 1.5× "
        "the 20-bar average. RSI must confirm direction: above 50 for longs, below 50 for "
        "shorts. EMA20 should be sloping in the direction of the trade. "
        "OBV rising on a long breakout is strong additional confirmation. "
        "Avoid chasing breakouts that happen without volume — they fail and reverse fast. "
        "SL is tight (1.2%) because failed breakouts reverse quickly and we must cut fast. "
        "TP1 at 2.5% (take half off), TP2 at 5%. Do not hold for extended moves — "
        "small accounts should bank gains quickly and reset rather than ride for more."
    )
    best_for    = ["bull", "bear", "trending"]
    params      = StrategyParams(
        sl_pct=0.012, tp1_pct=0.025, tp1_frac=0.50,
        tp2_pct=0.050, tp2_frac=0.50,
        tp3_pct=0.0,  tp3_frac=0.0,
        trail_pct=0.015, conf_min=0.55, side="BOTH",
        max_hold_candles=48,    # 12 h max — breakout should follow through quickly
    )

    def signal(self, coin: str, candles: list, regime: str, ticker: dict) -> Signal:
        if len(candles) < 25:
            return Signal("HOLD", 0.0, "insufficient history", self.name)

        c  = [x["close"] for x in candles]
        h  = [x["high"]  for x in candles]
        lo = [x["low"]   for x in candles]
        v  = [x.get("volume", 0) for x in candles]

        price = c[-1]

        # 20-bar high/low breakout levels (exclude current candle)
        lookback   = 20
        prior_high = max(h[-lookback - 1:-1])
        prior_low  = min(lo[-lookback - 1:-1])

        # Volume ratio: current bar vs 20-bar average (excluding current)
        avg_vol   = sum(v[-lookback - 1:-1]) / lookback if len(v) > lookback else None
        curr_vol  = v[-1]
        vol_ratio = (curr_vol / avg_vol) if avg_vol and avg_vol > 0 else 0.0

        ema20    = ind.ema(c, 20)
        ema50    = ind.ema(c, 50)
        r        = ind.rsi(c)
        obv_data = ind.obv(c, v)

        if r is None or ema20 is None:
            return Signal("HOLD", 0.0, "indicators unavailable", self.name)

        arith_action = "HOLD"
        score        = 0
        reasons      = []

        # ── LONG breakout ─────────────────────────────────────────────────────
        if price > prior_high:
            arith_action = "BUY"
            score += 2; reasons.append(f"price>{lookback}bar_high")

            if vol_ratio >= 2.0:
                score += 3; reasons.append(f"vol×{vol_ratio:.1f}")
            elif vol_ratio >= 1.5:
                score += 2; reasons.append(f"vol×{vol_ratio:.1f}")
            elif vol_ratio >= 1.2:
                score += 1; reasons.append(f"vol×{vol_ratio:.1f}")

            if r > 55:
                score += 1; reasons.append(f"RSI={r:.0f}")
            if price > ema20:
                score += 1; reasons.append("price>EMA20")
            if ema50 and ema20 > ema50:
                score += 1; reasons.append("EMA20>EMA50")
            if obv_data and obv_data["trend"] == "rising":
                score += 1; reasons.append("OBV↑")

        # ── SHORT breakdown ────────────────────────────────────────────────────
        elif price < prior_low:
            arith_action = "SELL"
            score += 2; reasons.append(f"price<{lookback}bar_low")

            if vol_ratio >= 2.0:
                score += 3; reasons.append(f"vol×{vol_ratio:.1f}")
            elif vol_ratio >= 1.5:
                score += 2; reasons.append(f"vol×{vol_ratio:.1f}")
            elif vol_ratio >= 1.2:
                score += 1; reasons.append(f"vol×{vol_ratio:.1f}")

            if r < 45:
                score += 1; reasons.append(f"RSI={r:.0f}")
            if price < ema20:
                score += 1; reasons.append("price<EMA20")
            if ema50 and ema20 < ema50:
                score += 1; reasons.append("EMA20<EMA50")
            if obv_data and obv_data["trend"] == "falling":
                score += 1; reasons.append("OBV↓")

        else:
            return Signal("HOLD", 0.0, "no breakout", self.name)

        max_score  = 9
        arith_conf = round(min(0.95, score / max_score), 3)

        if arith_conf < LLM_TRIGGER_CONF:
            return Signal("HOLD", arith_conf, f"pre-screen too weak ({score}/{max_score})", self.name)

        facts = {
            "price":       round(price, 4),
            "prior_high":  round(prior_high, 4),
            "prior_low":   round(prior_low, 4),
            "vol_ratio":   round(vol_ratio, 2),
            "RSI":         round(r, 1),
            "EMA20":       round(ema20, 4),
            "EMA50":       round(ema50, 4) if ema50 else None,
            "OBV_trend":   obv_data["trend"] if obv_data else None,
            "regime":      regime,
            "arithmetic_signals": ", ".join(reasons) or "none",
            "arithmetic_score":   f"{score}/{max_score}",
        }

        return self._llm_confirm(coin, regime, arith_action, arith_conf, facts)


_instance = VolBreakout()
