"""
LAYER C - REGIME FILTER
Determines if current regime is suitable for trading.
Stand-down if unsuitable or no clear agreement.
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class RegimeFilter:
    """Filters trades based on market regime."""

    def __init__(self, config):
        self.config = config
        self.enabled = config.REGIME_FILTER_ENABLED
        self.strict = config.REGIME_FILTER_STRICT

    def should_allow_trade(self, regime: str, verdict_view: str) -> tuple[bool, str]:
        """
        Determine if regime allows trading.
        Returns: (allow, reason)
        """
        if not self.enabled:
            return True, "regime filter disabled"

        if regime == "ranging":
            if self.strict:
                return False, "ranging regime disallowed in strict mode"
            # Allow ranging with mean-reversion strategies (opposite view)
            return True, "ranging regime allows mean-reversion trades"

        if regime == "volatile":
            return False, "volatile regime unsafe, stand down"

        if regime == "trending":
            return True, "trending regime suitable for trend-following trades"

        if regime == "neutral":
            return False, "insufficient regime data"

        return False, f"unknown regime: {regime}"
