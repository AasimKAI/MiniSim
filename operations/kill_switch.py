"""
LAYER E - KILL SWITCH
Dashboard + Telegram. Immediate trading halt.
Survives restart. Checked before every order.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict

logger = logging.getLogger(__name__)


class KillSwitch:
    """Kill switch for emergency trading halt."""

    def __init__(self, config):
        self.config = config
        self.kill_switch_path = config.KILL_SWITCH_PATH

    def activate(self, reason: str = "manual") -> bool:
        """Activate kill switch."""
        try:
            os.makedirs(os.path.dirname(self.kill_switch_path), exist_ok=True)
            with open(self.kill_switch_path, 'w') as f:
                f.write(f"activated at {datetime.now(timezone.utc).isoformat()}: {reason}\n")
            logger.error(f"KILL SWITCH ACTIVATED: {reason}")
            return True
        except Exception as e:
            logger.error(f"Failed to activate kill switch: {e}")
            return False

    def deactivate(self) -> bool:
        """Deactivate kill switch."""
        try:
            if os.path.exists(self.kill_switch_path):
                os.remove(self.kill_switch_path)
            logger.info("Kill switch deactivated")
            return True
        except Exception as e:
            logger.error(f"Failed to deactivate kill switch: {e}")
            return False

    def is_active(self) -> bool:
        """Check if kill switch is active."""
        return os.path.exists(self.kill_switch_path)

    def get_reason(self) -> str:
        """Get reason kill switch was activated."""
        if not self.is_active():
            return ""
        try:
            with open(self.kill_switch_path, 'r') as f:
                return f.read().strip()
        except:
            return "unknown reason"

    def get_status(self) -> Dict:
        """Get kill switch status."""
        is_active = self.is_active()
        return {
            "active": is_active,
            "reason": self.get_reason() if is_active else "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
