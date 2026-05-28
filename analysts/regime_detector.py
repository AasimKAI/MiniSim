"""
LAYER B - REGIME DETECTOR
Detects: trending, ranging, volatile.
Does NOT predict price; purely classifies market state.
"""

import logging
from typing import Dict, Optional
from datetime import datetime, timezone
from collections import deque

logger = logging.getLogger(__name__)


class RegimeDetector:
    """Classifies market regime as trending/ranging/volatile."""

    def __init__(self, config):
        self.config = config
        self.window_hours = config.REGIME_WINDOW_HOURS
        self.volatility_threshold = config.REGIME_VOLATILITY_THRESHOLD_PERCENT
        # Store price history: deque of (timestamp, price) tuples
        self.price_history = {}  # coin -> deque of prices

    def record_price(self, coin: str, price: float) -> None:
        """Record price for regime calculation."""
        if coin not in self.price_history:
            self.price_history[coin] = deque(maxlen=100)
        self.price_history[coin].append(price)

    def detect_regime(self, coin: str) -> Dict:
        """
        Detect regime for coin.
        Returns: {
            "coin": str,
            "regime": "trending"|"ranging"|"volatile",
            "confidence": 0-1,
            "reasoning": str,
            "timestamp": ISO8601,
        }
        """
        if coin not in self.price_history or len(self.price_history[coin]) < 5:
            return {
                "coin": coin,
                "regime": "neutral",
                "confidence": 0.0,
                "reasoning": "insufficient data",
                "timestamp": self._now_iso(),
            }

        prices = list(self.price_history[coin])

        # Calculate volatility
        avg_price = sum(prices) / len(prices)
        variance = sum((p - avg_price) ** 2 for p in prices) / len(prices)
        std_dev = variance ** 0.5
        volatility_percent = (std_dev / avg_price) * 100 if avg_price != 0 else 0

        # Calculate trend (simple: compare recent avg vs older avg)
        mid = len(prices) // 2
        recent_avg = sum(prices[mid:]) / len(prices[mid:])
        older_avg = sum(prices[:mid]) / len(prices[:mid])
        trend_percent = ((recent_avg - older_avg) / older_avg * 100) if older_avg != 0 else 0

        # Classify regime
        if volatility_percent > self.volatility_threshold * 2:
            regime = "volatile"
            confidence = min(0.9, volatility_percent / (self.volatility_threshold * 3))
        elif abs(trend_percent) > 2.0:
            regime = "trending"
            confidence = min(0.9, abs(trend_percent) / 10.0)
        else:
            regime = "ranging"
            confidence = 0.7

        return {
            "coin": coin,
            "regime": regime,
            "confidence": confidence,
            "reasoning": f"volatility={volatility_percent:.2f}%, trend={trend_percent:.2f}%",
            "timestamp": self._now_iso(),
        }

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
