"""
LAYER B - ORDER BOOK ANALYST
Analyzes imbalance and spread. Lowers confidence in thin markets.
Pure arithmetic, no LLM.
"""

import logging
from typing import Dict, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class OrderBookAnalyst:
    """Analyzes order book dynamics."""

    def __init__(self, config):
        self.config = config

    def analyze(self, coin: str, bid_volume: float, ask_volume: float, spread_percent: float) -> Dict:
        """
        Analyze order book.
        Returns standard verdict shape.
        """
        if bid_volume <= 0 or ask_volume <= 0:
            return self._neutral_verdict(coin, "invalid order book data")

        total_volume = bid_volume + ask_volume
        imbalance_ratio = max(bid_volume, ask_volume) / total_volume if total_volume > 0 else 1.0

        # Check imbalance
        is_imbalanced = imbalance_ratio > (self.config.OB_IMBALANCE_THRESHOLD / 2)

        # Check spread
        spread_is_tight = spread_percent < self.config.OB_SPREAD_PERCENT_THRESHOLD
        confidence_reduction = 0.2 if not spread_is_tight else 0.0

        if not is_imbalanced:
            return self._neutral_verdict(coin, "no order book imbalance")

        # Determine view based on imbalance side
        view = "bullish" if bid_volume > ask_volume else "bearish"
        confidence = max(0.1, min(0.7, (imbalance_ratio - 1.0) * 5.0) - confidence_reduction)

        return {
            "analyst": "order_book",
            "coin": coin,
            "view": view,
            "confidence": confidence,
            "reasoning": f"imbalance {imbalance_ratio:.2f}, spread {'tight' if spread_is_tight else 'wide'}",
            "timestamp": self._now_iso(),
            "data_age_seconds": 0,
            "status": "validated",
            "order_book_signals": {
                "bid_volume": bid_volume,
                "ask_volume": ask_volume,
                "imbalance_ratio": imbalance_ratio,
                "spread_percent": spread_percent,
            },
        }

    def _neutral_verdict(self, coin: str, reason: str) -> Dict:
        return {
            "analyst": "order_book",
            "coin": coin,
            "view": "neutral",
            "confidence": 0.0,
            "reasoning": reason,
            "timestamp": self._now_iso(),
            "data_age_seconds": 0,
            "status": "validated",
        }

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
