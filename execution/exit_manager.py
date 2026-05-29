"""
LAYER D - EXIT MANAGER
Manages exit plan: profit targets, trailing stop, thesis-break.
3 exit triggers, thesis-break closes BEFORE stop-loss.
Continuous exit-watch loop.
"""

import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ExitManager:
    """Manages position exits."""

    def __init__(self, config):
        self.config = config

    def check_exit_conditions(self, position: Dict, current_price: float, regime: str) -> Optional[Dict]:
        """
        Check if any exit condition triggered.
        Returns: exit_order or None.
        """
        entry_price = position.get('entry_price', 0)
        side = position.get('side', 'LONG')
        stop_loss = position.get('stop_loss', 0)
        profit_targets = position.get('take_profit_targets', [])
        trailing_stop = position.get('trailing_stop', entry_price)
        thesis_condition = position.get('thesis_condition', {})
        max_hold_time_sec = position.get('max_hold_time_sec', 0)
        entry_timestamp = position.get('entry_timestamp', '')

        # Parse entry time and check max hold
        if entry_timestamp:
            from datetime import datetime
            try:
                entry_dt = datetime.fromisoformat(entry_timestamp.replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                elapsed = (now - entry_dt).total_seconds()
                if elapsed > max_hold_time_sec:
                    return {
                        "trigger": "max_hold_time",
                        "exit_type": "limit",
                        "exit_price": current_price,
                        "quantity_percent": 100,
                    }
            except:
                pass

        # Check thesis condition FIRST (before stop loss) - intended exit before forced exit
        if self._check_thesis_break(thesis_condition, regime):
            return {
                "trigger": "thesis_break",
                "exit_type": "market",
                "exit_price": current_price,
                "quantity_percent": 100,
            }

        # Check stop loss (after thesis break)
        stop_loss_hit = current_price <= stop_loss if side == 'LONG' else current_price >= stop_loss
        if stop_loss_hit:
            return {
                "trigger": "stop_loss",
                "exit_type": "market",
                "exit_price": current_price,
                "quantity_percent": 100,
            }

        # Check trailing stop
        if position.get('trailing_stop_activated', False):
            if side == 'LONG':
                trailing_stop_price = max(position.get('trailing_stop_level', entry_price), trailing_stop)
            else:
                trailing_stop_price = min(position.get('trailing_stop_level', entry_price), trailing_stop)
            trailing_hit = current_price <= trailing_stop_price if side == 'LONG' else current_price >= trailing_stop_price
            if trailing_hit:
                return {
                    "trigger": "trailing_stop",
                    "exit_type": "market",
                    "exit_price": current_price,
                    "quantity_percent": 100,
                }

        # Check profit targets
        for i, target in enumerate(profit_targets):
            trigger = f"profit_target_{i + 1}"
            if trigger in position.get('closed_exit_triggers', []):
                continue

            if isinstance(target, dict):
                target_price = target.get('target_price')
                quantity_percent = target.get('quantity_percent', 33.33)
            else:
                target_price = target
                quantity_percent = 33.33

            if target_price is None:
                continue

            target_hit = current_price >= target_price if side == 'LONG' else current_price <= target_price
            if target_hit:
                return {
                    "trigger": trigger,
                    "exit_type": "limit",
                    "exit_price": target_price,
                    "quantity_percent": quantity_percent,
                }

        return None

    def _check_thesis_break(self, thesis_condition: Dict, current_regime: str) -> bool:
        """Check if original thesis condition is broken."""
        condition_type = thesis_condition.get('condition_type', '')
        if condition_type == 'signal_validity':
            original_view = thesis_condition.get('parameters', {}).get('original_view', 'bullish')
            # Simple check: if regime became volatile, thesis broken
            if current_regime == 'volatile':
                return True
        return False

    def update_trailing_stop(self, position: Dict, current_price: float) -> Dict:
        """Update trailing stop for position."""
        entry_price = position.get('entry_price', 0)
        side = position.get('side', 'LONG')
        trailing_percent = self.config.TRAILING_STOP_PERCENT

        if side == 'LONG' and current_price > entry_price:
            trailing_level = current_price * (1 - trailing_percent / 100)
            position['trailing_stop_activated'] = True
            position['trailing_stop_level'] = max(position.get('trailing_stop_level', entry_price), trailing_level)
        elif side == 'SHORT' and current_price < entry_price:
            trailing_level = current_price * (1 + trailing_percent / 100)
            position['trailing_stop_activated'] = True
            position['trailing_stop_level'] = min(position.get('trailing_stop_level', entry_price), trailing_level)

        return position
