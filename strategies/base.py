"""
Strategy base types — shared dataclasses and ABC.

Signal pipeline per strategy:
  1. Arithmetic hard gates  — fast kill-off, no LLM cost
  2. Arithmetic scoring     — builds a 0-1 pre-screen confidence
  3. _llm_confirm()         — called when pre-screen >= LLM_TRIGGER_CONF
                              LLM receives indicator facts + strategy philosophy
                              and independently decides action + confidence
  4. Fallback               — if LLM unavailable, arithmetic result is used
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

# Arithmetic pre-screen must reach this before we spend an LLM call.
LLM_TRIGGER_CONF = 0.35


@dataclass
class StrategyParams:
    sl_pct:    float = 0.02
    tp1_pct:   float = 0.05;  tp1_frac: float = 0.33
    tp2_pct:   float = 0.10;  tp2_frac: float = 0.33
    tp3_pct:   float = 0.15;  tp3_frac: float = 0.34
    trail_pct: float = 0.03
    conf_min:  float = 0.55
    side:      Literal["LONG", "SHORT", "BOTH"] = "BOTH"
    max_hold_candles: int = 192   # 48 h at 15 min


@dataclass
class Signal:
    action:     Literal["BUY", "SELL", "HOLD"]
    confidence: float
    reason:     str
    strategy:   str


class Strategy(ABC):
    name:        str
    label:       str
    description: str
    philosophy:  str = ""   # Passed verbatim to LLM — strategy-specific guidance
    best_for:    list       # e.g. ["bear", "trending"]
    params:      StrategyParams

    @abstractmethod
    def signal(self, coin: str, candles: list, regime: str, ticker: dict) -> Signal:
        """
        Compute indicators, apply hard gates, build facts dict, then call
        _llm_confirm() when the arithmetic pre-screen passes LLM_TRIGGER_CONF.
        """
        ...

    def _llm_confirm(
        self,
        coin: str,
        regime: str,
        arithmetic_action: str,
        arithmetic_conf: float,
        facts: dict,
    ) -> Signal:
        """
        Ask the LLM to confirm or reject an arithmetic pre-screened signal.

        The LLM receives:
          - The strategy name, philosophy, side constraint, and best-for conditions
          - All computed indicator values as plain key: value facts
          - The coin, current regime, and arithmetic pre-screen result

        Returns a Signal whose action and confidence come from the LLM.
        Falls back to the arithmetic result if the LLM is unavailable.
        """
        from llm.quantized_client import chat_json

        side_desc = {
            "LONG":  "long (buy) trades only — never short",
            "SHORT": "short (sell) trades only — never buy",
            "BOTH":  "either direction depending on the setup",
        }.get(self.params.side, "either direction")

        philosophy_text = self.philosophy or self.description

        facts_lines = "\n".join(
            f"  {k}: {v}" for k, v in facts.items() if v is not None
        )

        sysmsg = (
            f"You are a disciplined crypto strategy analyst executing the "
            f"'{self.label}' strategy.\n\n"
            f"Strategy philosophy: {philosophy_text}\n"
            f"Side constraint: {side_desc}\n"
            f"Works best in: {', '.join(self.best_for)} market conditions\n"
            f"SL: {self.params.sl_pct*100:.1f}%  "
            f"TP: {self.params.tp1_pct*100:.0f}/{self.params.tp2_pct*100:.0f}"
            f"/{self.params.tp3_pct*100:.0f}%\n\n"
            f"Rules:\n"
            f"1. Only confirm signals that clearly match THIS strategy's setup.\n"
            f"2. Return HOLD if the setup is borderline or the regime is unfavourable.\n"
            f"3. Do not override the side constraint — a SHORT-only strategy cannot BUY.\n"
            f"4. Confidence 0.0–1.0 reflects how clean and aligned the setup is."
        )

        user = (
            f"Coin: {coin}\n"
            f"Regime: {regime}\n"
            f"Arithmetic pre-screen: {arithmetic_action} "
            f"(score {arithmetic_conf:.0%})\n\n"
            f"Indicator facts:\n{facts_lines}\n\n"
            f"Should the '{self.name}' strategy trade {coin} right now?\n"
            f"Reply JSON with keys: "
            f"action (BUY|SELL|HOLD), confidence (0.0–1.0), reasoning (one sentence)."
        )

        try:
            result = chat_json(sysmsg, user,
                               schema_keys=("action", "confidence", "reasoning"))
            action = str(result.get("action", "HOLD")).upper().strip()
            if action not in ("BUY", "SELL", "HOLD"):
                action = "HOLD"

            # Enforce side constraint even if LLM ignores it
            if self.params.side == "LONG" and action == "SELL":
                action = "HOLD"
            if self.params.side == "SHORT" and action == "BUY":
                action = "HOLD"

            conf = float(result.get("confidence", 0.0) or 0.0)
            conf = max(0.0, min(1.0, conf))
            reasoning = str(result.get("reasoning", "") or "").strip()
            return Signal(action, conf, reasoning or "LLM confirmed", self.name)

        except Exception:
            # LLM unavailable — fall back to arithmetic result
            if arithmetic_action in ("BUY", "SELL") and arithmetic_conf >= self.params.conf_min:
                return Signal(
                    arithmetic_action, arithmetic_conf,
                    "LLM unavailable — arithmetic fallback", self.name
                )
            return Signal("HOLD", arithmetic_conf, "LLM unavailable", self.name)

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "label":       self.label,
            "description": self.description,
            "best_for":    self.best_for,
            "side":        self.params.side,
            "sl_pct":      self.params.sl_pct,
            "tp1_pct":     self.params.tp1_pct,
            "tp2_pct":     self.params.tp2_pct,
            "tp3_pct":     self.params.tp3_pct,
            "trail_pct":   self.params.trail_pct,
            "conf_min":    self.params.conf_min,
        }
