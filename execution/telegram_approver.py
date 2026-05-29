"""
LAYER D - TELEGRAM APPROVAL BOT
For 'big' trades. Configured chat ID only.
Expiry + nonce; expired/mismatched rejected + logged.
"""

import logging
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta
import hashlib

logger = logging.getLogger(__name__)


class TelegramApprover:
    """Telegram approval for big trades."""

    def __init__(self, config):
        self.config = config
        self.enabled = config.TELEGRAM_ENABLED
        self.approval_timeout_sec = config.TELEGRAM_APPROVAL_TIMEOUT_SEC
        self.chat_id = getattr(config, 'TELEGRAM_CHAT_ID', None)
        self.pending_approvals = {}  # nonce -> (timestamp, signal_id)

    def request_approval(self, signal: Dict) -> Dict:
        """
        Request approval for big trade.
        Returns: {"approval_id": str, "expires_at": ISO8601}
        """
        if not self.enabled or signal.get('decision') == 'stand_down' or not signal.get('is_big_trade', False):
            return {"approval_id": "auto", "expires_at": self._now_iso()}

        signal_id = signal.get('signal_id', '')
        coin = signal.get('coin', '')
        view = signal.get('view', '')

        # Generate nonce
        nonce = hashlib.sha256(f"{signal_id}{self._now_iso()}".encode()).hexdigest()[:16]
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.approval_timeout_sec)

        self.pending_approvals[nonce] = (datetime.now(timezone.utc), signal_id)

        logger.info(f"Telegram approval requested: {coin} {view} (nonce: {nonce})")

        return {
            "approval_id": nonce,
            "expires_at": expires_at.isoformat(),
            "signal_id": signal_id,
            "coin": coin,
            "view": view,
        }

    def check_approval(self, approval_id: str, signal_id: str) -> tuple[bool, str]:
        """
        Check if approval is valid.
        Returns: (approved, reason)
        """
        if not self.enabled:
            return True, "approvals disabled"

        if approval_id == "auto":
            return True, "auto-approved"

        if approval_id not in self.pending_approvals:
            return False, "approval not found"

        req_time, req_signal_id = self.pending_approvals[approval_id]
        now = datetime.now(timezone.utc)

        # Check expiry
        if (now - req_time).total_seconds() > self.approval_timeout_sec:
            del self.pending_approvals[approval_id]
            return False, "approval expired"

        # Check nonce match
        if req_signal_id != signal_id:
            return False, "signal ID mismatch"

        # Mark as used
        del self.pending_approvals[approval_id]
        return True, "approved"

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
