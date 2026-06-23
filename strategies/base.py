"""
Strategy base types — shared dataclasses and ABC.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


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
    best_for:    list   # e.g. ["bear", "trending"]
    params:      StrategyParams

    @abstractmethod
    def signal(self, coin: str, candles: list, regime: str, ticker: dict) -> Signal:
        """Return a trading signal for this coin given current candles + regime."""
        ...

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
