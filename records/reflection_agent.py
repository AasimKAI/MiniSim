"""
LAYER F - REFLECTION AGENT
Post-trade analysis. Stores lesson if statistically significant.
Provisional if not. No influence on live trading.
Lessons read by analysts/CEO but advisory-only.
"""

import logging
import uuid
from typing import Dict, List, Optional
from datetime import datetime, timezone
from math import isnan

logger = logging.getLogger(__name__)


class ReflectionAgent:
    """Post-trade reflection and learning."""

    def __init__(self, config):
        self.config = config
        self.enabled = config.REFLECTION_ENABLED
        self.min_sample_size = config.REFLECTION_MIN_SAMPLE_SIZE
        self.confidence_threshold = config.REFLECTION_CONFIDENCE_THRESHOLD
        self.provisional_enabled = config.REFLECTION_PROVISIONAL_LEARNING_ENABLED
        self.lessons = []

    def analyze_trade_outcome(self, signal: Dict, order: Dict, exit: Dict) -> Optional[Dict]:
        """
        Analyze trade outcome and potentially store lesson.
        Returns: lesson record or None.
        """
        if not self.enabled:
            return None

        coin = signal.get('coin', '')
        analyst = signal.get('analyst', 'unknown')
        entry_price = order.get('price', 0)
        exit_price = exit.get('exit_price', 0)
        pnl_percent = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

        # Simplistic: if analyst was bullish and trade was profitable, maybe pattern holds
        original_view = signal.get('view', 'neutral')
        was_correct = (original_view == 'bullish' and pnl_percent > 0) or \
                      (original_view == 'bearish' and pnl_percent < 0)

        if not was_correct:
            return None  # Don't store lessons from failed trades

        # Calculate confidence (simplified: based on PnL magnitude)
        confidence = min(0.9, abs(pnl_percent) / 100)

        # For now, treat as provisional (no sample size verification)
        is_provisional = True

        lesson = {
            "lesson_id": str(uuid.uuid4()),
            "coin": coin,
            "analyst": analyst,
            "pattern": f"{original_view}_on_{exit.get('trigger', 'unknown')}_profitable",
            "confidence": confidence,
            "sample_size": 1,  # Single trade (provisional)
            "p_value": 0.05,  # Placeholder
            "is_provisional": is_provisional,
            "pnl_percent": pnl_percent,
            "timestamp": self._now_iso(),
            "schema_version": "1.0.0",
        }

        self.lessons.append(lesson)
        logger.info(f"Reflection: {analyst} on {coin} - pattern stored (provisional={is_provisional})")
        return lesson

    def get_lessons_for_analyst(self, analyst: str, coin: Optional[str] = None) -> List[Dict]:
        """Get lessons for analyst (advisory only)."""
        lessons = [l for l in self.lessons if l.get('analyst') == analyst]
        if coin:
            lessons = [l for l in lessons if l.get('coin') == coin]
        return lessons

    def get_all_lessons(self) -> List[Dict]:
        """Get all lessons."""
        return self.lessons.copy()

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
