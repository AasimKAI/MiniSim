"""
Telegram-gated session management for the dashboard.

Flow:
  1. Unauthenticated request → redirect to /login
  2. User clicks "Request access" → one-time token sent to TELEGRAM_CHAT_ID
  3. User clicks link in Telegram → session cookie set → redirect to /
  4. Session cookie valid for DASHBOARD_SESSION_HOURS (default 24h)

If Telegram is not configured, dashboard denies access by default.
"""

import json
import logging
import secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import Request
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

_pending_tokens: dict[str, float] = {}   # token -> expiry_epoch
_active_sessions: dict[str, float] = {}  # session_id -> expiry_epoch

_TOKEN_TTL_SEC = 300
_SESSION_COOKIE = "minisim_session"
_SESSIONS_FILE = "state/dashboard_sessions.json"


def _load_sessions():
    global _active_sessions
    try:
        p = Path(_SESSIONS_FILE)
        if p.exists():
            _active_sessions = json.loads(p.read_text())
    except Exception:
        pass


def _save_sessions():
    try:
        Path(_SESSIONS_FILE).parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        live = {k: v for k, v in _active_sessions.items() if v > now}
        Path(_SESSIONS_FILE).write_text(json.dumps(live))
    except Exception:
        pass


_load_sessions()


class DashboardAuth:
    """Manages Telegram-gated sessions."""

    def __init__(self, config):
        self.config = config
        self.telegram_enabled = getattr(config, "TELEGRAM_ENABLED", False)
        self.bot_token = getattr(config, "TELEGRAM_BOT_TOKEN", None)
        self.chat_id = getattr(config, "TELEGRAM_CHAT_ID", None)
        self.session_hours = getattr(config, "DASHBOARD_SESSION_HOURS", 24)
        self.secure_cookie = getattr(config, "DASHBOARD_SECURE_COOKIE", False)
        self.external_url = getattr(config, "DASHBOARD_EXTERNAL_URL", "http://localhost:8080").rstrip("/")

    def is_authenticated(self, request: Request) -> bool:
        if not self._auth_required():
            return False
        session_id = request.cookies.get(_SESSION_COOKIE)
        if not session_id:
            return False
        expiry = _active_sessions.get(session_id, 0)
        return time.time() < expiry

    def require_auth(self, request: Request) -> Optional[RedirectResponse]:
        if not self.is_authenticated(request):
            return RedirectResponse(url="/login")
        return None

    def request_access(self) -> dict:
        if not self._auth_required():
            return {"ok": False, "message": "Dashboard auth is not configured. Set Telegram bot token and chat ID."}

        # Prune expired pending tokens before adding a new one
        global _pending_tokens
        now = time.time()
        _pending_tokens = {k: v for k, v in _pending_tokens.items() if v > now}

        token = secrets.token_hex(24)
        _pending_tokens[token] = now + _TOKEN_TTL_SEC
        link = f"{self.external_url}/login/verify?token={token}"

        if self.telegram_enabled and self.bot_token and self.chat_id:
            sent = self._send_telegram(
                f"MiniSim Dashboard login requested.\n\n"
                f"Click to authenticate (valid 5 min):\n{link}"
            )
            if sent:
                return {"ok": True, "message": "Login link sent to Telegram."}
            return {"ok": False, "message": "Failed to send Telegram message. Check bot configuration."}

        return {"ok": False, "message": "Dashboard auth is not configured. Set Telegram bot token and chat ID."}

    def verify_token(self, token: str) -> Optional[str]:
        expiry = _pending_tokens.get(token)
        if expiry is None:
            return None
        if time.time() > expiry:
            _pending_tokens.pop(token, None)
            return None
        # Consume token (single-use)
        _pending_tokens.pop(token, None)

        session_id = secrets.token_hex(32)
        _active_sessions[session_id] = time.time() + self.session_hours * 3600
        _save_sessions()
        return session_id

    def set_session_cookie(self, response, session_id: str):
        response.set_cookie(
            _SESSION_COOKIE,
            session_id,
            max_age=self.session_hours * 3600,
            httponly=True,
            samesite="lax",
            secure=self.secure_cookie,
        )

    def _auth_required(self) -> bool:
        return bool(self.telegram_enabled and self.bot_token and self.chat_id)

    def _send_telegram(self, text: str) -> bool:
        try:
            import requests
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            r = requests.post(url, json={"chat_id": self.chat_id, "text": text}, timeout=10)
            return r.status_code == 200
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False
