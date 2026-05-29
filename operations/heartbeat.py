"""
LAYER E - HEARTBEAT
Regular 'alive' signal. Absence triggers notification.
Monitors component health.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class Heartbeat:
    """Monitors system heartbeat."""

    def __init__(self, config):
        self.config = config
        self.enabled = config.HEARTBEAT_ENABLED
        self.interval_sec = config.HEARTBEAT_INTERVAL_SEC
        self.notification_threshold_sec = config.HEARTBEAT_NOTIFICATION_THRESHOLD_SEC
        self.last_heartbeat = datetime.now(timezone.utc)
        self.heartbeat_count = 0

    def pulse(self) -> None:
        """Record heartbeat."""
        self.last_heartbeat = datetime.now(timezone.utc)
        self.heartbeat_count += 1
        logger.debug(f"Heartbeat #{self.heartbeat_count}")

    def check_health(self) -> tuple[bool, str]:
        """
        Check if heartbeat is healthy.
        Returns: (is_healthy, reason)
        """
        if not self.enabled:
            return True, "heartbeat disabled"

        elapsed = (datetime.now(timezone.utc) - self.last_heartbeat).total_seconds()

        if elapsed > self.notification_threshold_sec:
            return False, f"no heartbeat for {elapsed:.0f}s (threshold: {self.notification_threshold_sec}s)"

        return True, "healthy"

    def get_status(self) -> Dict:
        """Get heartbeat status."""
        is_healthy, reason = self.check_health()
        elapsed = (datetime.now(timezone.utc) - self.last_heartbeat).total_seconds()

        return {
            "enabled": self.enabled,
            "is_healthy": is_healthy,
            "reason": reason,
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "elapsed_sec": elapsed,
            "count": self.heartbeat_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
