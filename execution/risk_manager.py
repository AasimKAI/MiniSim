"""
LAYER D - RISK MANAGER
Sizing rules, exposure caps, kill switch.
Can SHRINK/VETO orders.
"""

import logging
from typing import Dict, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class RiskManager:
    """Manages position sizing and exposure."""

    def __init__(self, config):
        self.config = config
        self.position_size_usd = config.POSITION_SIZE_USD
        self.max_exposure_usd = config.MAX_EXPOSURE_USD
        self.leverage = config.LEVERAGE
        self.stop_loss_percent = config.STOP_LOSS_PERCENT

    def check_signal(self, signal: Dict, current_exposure_usd: float, is_kill_switch_active: bool) -> tuple[bool, str, Optional[float]]:
        """
        Check if signal can be executed.
        Returns: (approved, reason, adjusted_position_size_usd)
        """
        if is_kill_switch_active:
            return False, "kill switch active", None

        if signal.get('decision') == 'stand_down':
            return False, "signal is stand down", None

        if signal.get('decision') == 'entry_sell' and not getattr(self.config, 'ALLOW_SHORTS', False):
            return False, "short entries are disabled for this execution venue", None

        # Check exposure
        remaining_capacity = self.max_exposure_usd - current_exposure_usd
        if remaining_capacity <= 0:
            return False, "max exposure reached", None

        # Size position
        position_size = min(self.position_size_usd, remaining_capacity)

        return True, "approved", position_size

    def calculate_exit_plan(self, entry_price: float, coin: str, signal: Dict) -> Dict:
        """
        Calculate full exit plan for position.
        Returns: {
            "entry_price": float,
            "stop_loss": float,
            "profit_targets": [...],
            "trailing_rule": {...},
            "thesis_condition": {...},
            "max_hold_time_sec": float,
        }
        """
        is_short = signal.get('decision') == 'entry_sell'
        stop_loss = (
            entry_price * (1 + self.config.STOP_LOSS_PERCENT / 100)
            if is_short
            else entry_price * (1 - self.config.STOP_LOSS_PERCENT / 100)
        )

        target_direction = -1 if is_short else 1

        profit_targets = [
            {
                "target_price": entry_price * (1 + target_direction * self.config.TAKE_PROFIT_TARGET_1_PERCENT / 100),
                "quantity_percent": 33.33,
            },
            {
                "target_price": entry_price * (1 + target_direction * self.config.TAKE_PROFIT_TARGET_2_PERCENT / 100),
                "quantity_percent": 33.33,
            },
            {
                "target_price": entry_price * (1 + target_direction * self.config.TAKE_PROFIT_TARGET_3_PERCENT / 100),
                "quantity_percent": 33.34,
            },
        ]

        trailing_rule = {
            "enabled": True,
            "percent": self.config.TRAILING_STOP_PERCENT,
        }

        # Thesis condition: monitor key signal
        thesis_condition = {
            "condition_type": "signal_validity",
            "parameters": {
                "original_view": signal.get('view', 'bullish'),
                "monitor_field": "regime",
            },
            "prose_rationale": "close if original thesis breaks (regime change or analyst reversal)",
        }

        max_hold_time_sec = self.config.MAX_HOLD_TIME_HOURS * 3600

        return {
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "profit_targets": profit_targets,
            "trailing_rule": trailing_rule,
            "thesis_condition": thesis_condition,
            "max_hold_time_sec": max_hold_time_sec,
        }
