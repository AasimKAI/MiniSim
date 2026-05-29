"""
LAYER E - WATCHDOG
Monitors long-running components. Restarts hangs/crashes.
Checks heartbeat, manages process state.
"""

import logging
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta
import subprocess

logger = logging.getLogger(__name__)


class Watchdog:
    """Monitors and restarts components."""

    def __init__(self, config):
        self.config = config
        self.enabled = config.WATCHDOG_ENABLED
        self.check_interval = config.WATCHDOG_CHECK_INTERVAL_SEC
        self.restart_limit = config.WATCHDOG_RESTART_RETRY_LIMIT
        self.component_health = {}  # component -> {last_check, restart_count, status}

    def register_component(self, component_name: str) -> None:
        """Register component for monitoring."""
        self.component_health[component_name] = {
            "last_check": datetime.now(timezone.utc),
            "restart_count": 0,
            "status": "running",
        }

    def check_component(self, component_name: str, is_alive: bool) -> Optional[str]:
        """
        Check component health.
        Returns: action ("restart", "alert", None)
        """
        if not self.enabled or component_name not in self.component_health:
            return None

        health = self.component_health[component_name]

        if is_alive:
            health["last_check"] = datetime.now(timezone.utc)
            health["status"] = "running"
            health["restart_count"] = 0
            return None

        # Component appears dead
        elapsed = (datetime.now(timezone.utc) - health["last_check"]).total_seconds()

        if elapsed > self.check_interval * 2:
            # Component hung or crashed
            if health["restart_count"] < self.restart_limit:
                health["restart_count"] += 1
                logger.warning(f"Component {component_name} hung, restart attempt {health['restart_count']}")
                return "restart"
            else:
                logger.error(f"Component {component_name} exceeded restart limit")
                return "alert"

        return None

    def report_alive(self, component_name: str) -> None:
        """Component reports it's alive."""
        if component_name in self.component_health:
            self.component_health[component_name]["last_check"] = datetime.now(timezone.utc)
            self.component_health[component_name]["status"] = "running"

    def get_status(self) -> Dict:
        """Get overall watchdog status."""
        return {
            "enabled": self.enabled,
            "components": self.component_health,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
