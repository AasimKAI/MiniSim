"""
Telegram polling listener for approving or rejecting pending trades.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class TelegramApprovalListener:
    """Polls Telegram updates and turns approved nonces into executable actions."""

    def __init__(self, config, session=None):
        self.config = config
        self.enabled = bool(getattr(config, "TELEGRAM_ENABLED", False))
        self.bot_token = getattr(config, "TELEGRAM_BOT_TOKEN", None)
        self.chat_id = str(getattr(config, "TELEGRAM_CHAT_ID", "") or "")
        self.last_update_id = None
        self.session = session

    def poll(self) -> List[Dict]:
        """Return approval actions: [{"action": "approve"|"reject", "approval_id": str}]."""
        if not self.enabled or not self.bot_token or not self.chat_id:
            return []

        try:
            updates = self._get_updates()
        except Exception as e:
            logger.warning("Telegram approval poll failed: %s", e)
            return []
        actions = []
        for update in updates:
            update_id = update.get("update_id")
            if update_id is not None:
                self.last_update_id = update_id

            message = update.get("message") or update.get("edited_message") or {}
            chat = message.get("chat") or {}
            if str(chat.get("id", "")) != self.chat_id:
                logger.warning("Ignoring Telegram command from unauthorized chat")
                continue

            text = (message.get("text") or "").strip()
            action = self._parse_command(text)
            if action:
                actions.append(action)

        return actions

    def notify_pending(self, approval: Dict, signal: Dict, position_size: float) -> None:
        if not self.enabled or not self.bot_token or not self.chat_id:
            return
        text = (
            f"Trade approval required\n"
            f"ID: {approval.get('approval_id')}\n"
            f"Coin: {signal.get('coin')}\n"
            f"Decision: {signal.get('decision')}\n"
            f"Confidence: {signal.get('confidence', 0):.1%}\n"
            f"Size USD: {position_size:.2f}\n"
            f"Approve: /approve {approval.get('approval_id')}\n"
            f"Reject: /reject {approval.get('approval_id')}"
        )
        self._send_message(text)

    def notify_result(self, text: str) -> None:
        if self.enabled and self.bot_token and self.chat_id:
            self._send_message(text)

    def _parse_command(self, text: str) -> Optional[Dict]:
        parts = text.split()
        if len(parts) != 2:
            return None
        command = parts[0].lower()
        if command not in ["/approve", "/reject"]:
            return None
        return {"action": command.lstrip("/"), "approval_id": parts[1]}

    def _get_updates(self) -> List[Dict]:
        params = {"timeout": 0}
        if self.last_update_id is not None:
            params["offset"] = self.last_update_id + 1
        response = self._request("getUpdates", params)
        return response.get("result", []) if response.get("ok") else []

    def _send_message(self, text: str) -> None:
        try:
            self._request("sendMessage", {"chat_id": self.chat_id, "text": text})
        except Exception as e:
            logger.warning("Telegram notification failed: %s", e)

    def _request(self, method: str, params: Dict) -> Dict:
        if self.session is None:
            import requests
            self.session = requests.Session()
        url = f"https://api.telegram.org/bot{self.bot_token}/{method}"
        response = self.session.get(url, params=params, timeout=15)
        response.raise_for_status()
        return response.json()
