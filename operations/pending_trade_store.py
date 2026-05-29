"""
Durable pending approval state for trades waiting on Telegram.
"""

from typing import Dict

from collector.utils import atomic_write_json, read_json_safe


class PendingTradeStore:
    """Persists pending trades so approval state survives process restarts."""

    def __init__(self, config, state_file: str = None):
        self.config = config
        self.state_file = state_file or f"{config.STATE_DIR}/pending_trades.json"

    def load(self) -> Dict:
        data = read_json_safe(self.state_file) or {}
        pending = data.get("pending_trades", {})
        return pending if isinstance(pending, dict) else {}

    def save(self, pending_trades: Dict) -> bool:
        return atomic_write_json(
            self.state_file,
            {"pending_trades": pending_trades},
            fsync=getattr(self.config, "ATOMIC_WRITE_FSYNC", True),
        )
