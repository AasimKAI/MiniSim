"""
LAYER B - ON-CHAIN ANALYST
Analyzes blockchain metrics (transaction volume, whale activity).
Purely arithmetic from on-chain data.
"""

import logging
from typing import Dict, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class OnChainAnalyst:
    """Analyzes on-chain metrics."""

    def __init__(self, config):
        self.config = config

    def analyze(self, coin: str, transaction_volume: float, active_addresses: int,
                whale_activity: float) -> Dict:
        """
        Analyze on-chain metrics.
        Returns standard verdict shape.
        """
        if transaction_volume <= 0 or active_addresses <= 0:
            return self._neutral_verdict(coin, "invalid on-chain data")

        # Simple heuristics
        high_whale_activity = whale_activity > 0.7
        high_address_activity = active_addresses > 100000

        if high_whale_activity and high_address_activity:
            view = "bullish"
            confidence = 0.6
            reasoning = "high whale and address activity"
        elif high_whale_activity and not high_address_activity:
            view = "bearish"
            confidence = 0.5
            reasoning = "whale activity concentrated, few addresses"
        elif high_address_activity:
            view = "bullish"
            confidence = 0.5
            reasoning = "broad address participation"
        else:
            return self._neutral_verdict(coin, "low on-chain activity")

        return {
            "analyst": "on_chain",
            "coin": coin,
            "view": view,
            "confidence": confidence,
            "reasoning": reasoning,
            "timestamp": self._now_iso(),
            "data_age_seconds": 0,
            "status": "validated",
            "on_chain_signals": {
                "transaction_volume": transaction_volume,
                "active_addresses": active_addresses,
                "whale_activity": whale_activity,
            },
        }

    def _neutral_verdict(self, coin: str, reason: str) -> Dict:
        return {
            "analyst": "on_chain",
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
