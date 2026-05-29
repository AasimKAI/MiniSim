"""
Prompt-hash LLM response cache backed by SQLite.
Keyed by sha256(prompt) so identical prompts never hit Ollama twice.
Uses a persistent connection with a threading.Lock for Pi-safe concurrent access.
"""

import hashlib
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class LLMCache:
    """Thread-safe SQLite-backed cache for Ollama responses."""

    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
        self._init_db()
        self._hits = 0
        self._misses = 0

    def _init_db(self):
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_cache (
                    prompt_hash TEXT PRIMARY KEY,
                    response     TEXT NOT NULL,
                    created_at   TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def _hash(self, prompt: str) -> str:
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def get(self, prompt: str) -> Optional[str]:
        h = self._hash(prompt)
        with self._lock:
            row = self._conn.execute(
                "SELECT response FROM llm_cache WHERE prompt_hash = ?", (h,)
            ).fetchone()
        if row:
            self._hits += 1
            logger.debug(f"LLM cache HIT (hash={h[:8]})")
            return row[0]
        self._misses += 1
        return None

    def set(self, prompt: str, response: str) -> None:
        h = self._hash(prompt)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO llm_cache (prompt_hash, response, created_at) VALUES (?, ?, ?)",
                (h, response, datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total else 0.0

    @property
    def stats(self) -> dict:
        return {"hits": self._hits, "misses": self._misses, "hit_rate": self.hit_rate}
