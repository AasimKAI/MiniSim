"""
LAYER F - DECISION LOG
Append-only log: proposed, approved, executed, exited, vetoed.
Schema Annex 3.4.
"""

import logging
import json
import uuid
from typing import Dict, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class DecisionLog:
    """Append-only decision log."""

    def __init__(self, config, log_file: str = "data/decision_log.jsonl"):
        self.config = config
        self.log_file = log_file
        self.entries = []

    def log_proposed(self, signal: Dict) -> str:
        """Log proposed signal."""
        log_id = str(uuid.uuid4())
        entry = {
            "log_id": log_id,
            "signal_id": signal.get('signal_id', ''),
            "status": "proposed",
            "coin": signal.get('coin', ''),
            "decision": signal.get('decision', ''),
            "view": signal.get('view', ''),
            "confidence": signal.get('confidence', 0),
            "timestamp": signal.get('timestamp', self._now_iso()),
            "reason": f"signal generated: {signal.get('view')} with {signal.get('confidence', 0):.1%} confidence",
        }
        self._append(entry)
        return log_id

    def log_approved(self, signal: Dict, approval_id: str = "") -> str:
        """Log approved signal."""
        log_id = str(uuid.uuid4())
        entry = {
            "log_id": log_id,
            "signal_id": signal.get('signal_id', ''),
            "status": "approved",
            "coin": signal.get('coin', ''),
            "decision": signal.get('decision', ''),
            "view": signal.get('view', ''),
            "confidence": signal.get('confidence', 0),
            "timestamp": self._now_iso(),
            "reason": f"approved for execution (approval_id: {approval_id})",
        }
        self._append(entry)
        return log_id

    def log_executed(self, signal: Dict, order_id: str, filled_price: float) -> str:
        """Log executed trade."""
        log_id = str(uuid.uuid4())
        entry = {
            "log_id": log_id,
            "signal_id": signal.get('signal_id', ''),
            "status": "executed",
            "coin": signal.get('coin', ''),
            "decision": signal.get('decision', ''),
            "view": signal.get('view', ''),
            "confidence": signal.get('confidence', 0),
            "timestamp": self._now_iso(),
            "reason": f"executed order {order_id} at {filled_price:.2f}",
        }
        self._append(entry)
        return log_id

    def log_exited(self, signal: Dict, exit_reason: str, exit_price: float) -> str:
        """Log position exit."""
        log_id = str(uuid.uuid4())
        entry = {
            "log_id": log_id,
            "signal_id": signal.get('signal_id', ''),
            "status": "exited",
            "coin": signal.get('coin', ''),
            "decision": signal.get('decision', ''),
            "view": signal.get('view', ''),
            "timestamp": self._now_iso(),
            "reason": f"exited: {exit_reason} at price {exit_price:.2f}",
        }
        self._append(entry)
        return log_id

    def log_vetoed(self, signal: Dict, veto_reason: str) -> str:
        """Log vetoed signal."""
        log_id = str(uuid.uuid4())
        entry = {
            "log_id": log_id,
            "signal_id": signal.get('signal_id', ''),
            "status": "vetoed",
            "coin": signal.get('coin', ''),
            "decision": signal.get('decision', ''),
            "view": signal.get('view', ''),
            "timestamp": self._now_iso(),
            "reason": veto_reason,
        }
        self._append(entry)
        return log_id

    def _append(self, entry: Dict) -> None:
        """Append entry to log."""
        self.entries.append(entry)
        # Also write to file (atomic)
        try:
            from collector.utils import atomic_write_json
            all_entries = self.get_all()
            atomic_write_json(self.log_file, all_entries)
        except Exception as e:
            logger.error(f"Failed to write decision log: {e}")

    def get_all(self) -> List[Dict]:
        """Get all log entries."""
        return self.entries.copy()

    def get_for_signal(self, signal_id: str) -> List[Dict]:
        """Get log entries for signal."""
        return [e for e in self.entries if e.get('signal_id') == signal_id]

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
