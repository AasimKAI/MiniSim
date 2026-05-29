"""
LAYER B - VOLUME ANALYST
Detects volume breakouts; pairs with price direction.
Pure arithmetic, no LLM.
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class VolumeAnalyst:
    """Analyzes volume patterns."""

    def __init__(self, config):
        self.config = config

    def analyze(self, coin: str, volumes: List[float], prices: List[float]) -> Dict:
        """
        Analyze volume breakouts.
        Returns standard verdict shape.
        """
        if not volumes or len(volumes) < 5:
            return self._neutral_verdict(coin, "insufficient volume data")

        avg_volume = sum(volumes[-10:]) / min(10, len(volumes))
        latest_volume = volumes[-1]
        volume_ratio = latest_volume / avg_volume if avg_volume > 0 else 0

        # Check if volume exceeded threshold
        is_breakout = volume_ratio > self.config.VOLUME_BREAKOUT_THRESHOLD

        if not is_breakout:
            return self._neutral_verdict(coin, "no volume breakout detected")

        # Pair with price direction
        if prices and len(prices) >= 2:
            price_direction = "up" if prices[-1] > prices[-2] else "down"
        else:
            price_direction = "unknown"

        confidence = min(0.9, (volume_ratio - 1.0) / 1.0)

        if price_direction == "up":
            view = "bullish"
        elif price_direction == "down":
            view = "bearish"
        else:
            view = "neutral"

        return {
            "analyst": "volume",
            "coin": coin,
            "view": view,
            "confidence": confidence,
            "reasoning": f"volume breakout {volume_ratio:.2f}x on {price_direction} price",
            "timestamp": self._now_iso(),
            "data_age_seconds": 0,
            "status": "validated",
            "volume_signals": {
                "current_volume": latest_volume,
                "average_volume": avg_volume,
                "ratio": volume_ratio,
                "breakout": is_breakout,
            },
        }

    def _neutral_verdict(self, coin: str, reason: str) -> Dict:
        return {
            "analyst": "volume",
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
