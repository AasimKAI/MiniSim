"""
Telegram-gated session management for the dashboard.

Flow:
  1. Unauthenticated request → redirect to /login
  2. User clicks "Request access" → one-time token sent to TELEGRAM_CHAT_ID
  3. User clicks link in Telegram → session cookie set → redirect to /
  4. Session cookie valid for DASHBOARD_SESSION_HOURS (default 24h)

If Telegram is not configured, dashboard falls back to open access.
"""

import hashlib
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from fastapi import Cookie, Request
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

# In-memory stores (single-process; survived across requests within session)
_pending_tokens: dict[str, float] = {}   # token -> expiry_epoch
_active_sessions: dict[str, float] = {}  # session_id -> expiry_epoch

_TOKEN_TTL_SEC = 300       # 5 minutes for one-time login link
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
        # Purge expired before saving
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
        self.external_url = getattr(config, "DASHBOARD_EXTERNAL_URL", "http://localhost:8080").rstrip("/")

    # ------------------------------------------------------------------
    # Middleware check
    # ------------------------------------------------------------------

    def is_authenticated(self, request: Request) -> bool:
        if not self._auth_required():
            return True
        session_id = request.cookies.get(_SESSION_COOKIE)
        if not session_id:
            return False
        expiry = _active_sessions.get(session_id, 0)
        return time.time() < expiry

    def require_auth(self, request: Request) -> Optional[RedirectResponse]:
        """Return redirect response if not authenticated, else None."""
        if not self.is_authenticated(request):
            return RedirectResponse(url="/login")
        return None

    # ------------------------------------------------------------------
    # Login flow
    # ------------------------------------------------------------------

    def request_access(self) -> dict:
        """
        Generate a one-time login token and send it via Telegram.
        Returns {"ok": bool, "message": str}.
        """
        if not self._auth_required():
            return {"ok": False, "message": "Auth not required (Telegram not configured)."}

        token = secrets.token_hex(24)
        _pending_tokens[token] = time.time() + _TOKEN_TTL_SEC
        link = f"{self.external_url}/login/verify?token={token}"

        if self.telegram_enabled and self.bot_token and self.chat_id:
            sent = self._send_telegram(
                f"🔐 MiniSim Dashboard login requested.\n\n"
                f"Click to authenticate (valid 5 min):\n{link}"
            )
            if sent:
                return {"ok": True, "message": "Login link sent to Telegram."}
            return {"ok": False, "message": "Failed to send Telegram message. Check bot configuration."}

        # Fallback: log token (development mode)
        logger.warning(f"Telegram not configured. Login token: {token}")
        logger.warning(f"Verify URL: {link}")
        return {"ok": True, "message": "Token logged (Telegram not configured). Check server logs."}

    def verify_token(self, token: str) -> Optional[str]:
        """
        Validate a one-time token and return a new session_id, or None if invalid.
        Consumes the token on success.
        """
        expiry = _pending_tokens.get(token)
        if expiry is None:
            return None
        if time.time() > expiry:
            _pending_tokens.pop(token, None)
            return None

        # Consume token
        _pending_tokens.pop(token, None)

        # Create session
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
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _auth_required(self) -> bool:
        return bool(self.telegram_enabled and self.bot_token and self.chat_id)

    def _send_telegram(self, text: str) -> bool:
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            r = requests.post(url, json={"chat_id": self.chat_id, "text": text}, timeout=10)
            return r.status_code == 200
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False
