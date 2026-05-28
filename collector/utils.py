"""
Utility functions for collectors and data processing.
Atomic writes, retry logic, date handling, common patterns.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def atomic_write_json(file_path: str, data: Dict[str, Any], fsync: bool = True) -> bool:
    """
    Atomically write JSON to file (write temp, fsync, rename).
    Returns True if successful, False otherwise.
    """
    try:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = Path(f"{file_path}.tmp")
        with open(temp_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
            if fsync:
                f.flush()
                os.fsync(f.fileno())

        # Atomic rename
        temp_path.replace(path)
        return True
    except Exception as e:
        logger.error(f"atomic_write_json failed for {file_path}: {e}")
        return False


def read_json_safe(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Read JSON file safely. Returns None if file doesn't exist or is malformed.
    """
    try:
        if not os.path.exists(file_path):
            return None
        with open(file_path) as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"read_json_safe failed for {file_path}: {e}")
        return None


def now_iso() -> str:
    """Return current timestamp in ISO 8601 format (UTC)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def retry_with_backoff(fn, max_retries: int = 3, initial_delay: float = 1.0, backoff: float = 2.0) -> Optional[Any]:
    """
    Retry function with exponential backoff.
    Returns result if successful, None if all retries exhausted.
    """
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Final retry failed: {e}")
                return None
            logger.warning(f"Retry {attempt + 1}/{max_retries} failed: {e}. Waiting {delay}s...")
            time.sleep(delay)
            delay *= backoff
    return None


def rate_limit_sleep(calls_per_minute: int) -> float:
    """Calculate sleep time to maintain calls per minute rate limit."""
    return 60.0 / calls_per_minute


def is_recent_data(timestamp_iso: str, max_age_seconds: int) -> bool:
    """Check if ISO timestamp is within max_age_seconds."""
    try:
        ts = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age = (now - ts).total_seconds()
        return age <= max_age_seconds
    except Exception:
        return False


def safe_get_nested(data: Dict, *keys, default=None) -> Any:
    """Safely get nested dict value without KeyError."""
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return default
    return current if current is not None else default


def merge_dicts_safe(base: Dict, updates: Dict) -> Dict:
    """Safely merge updates into base, overwriting only provided keys."""
    result = base.copy()
    for key, value in updates.items():
        if value is not None:
            result[key] = value
    return result


def ensure_dir(dir_path: str) -> bool:
    """Ensure directory exists. Returns True if successful."""
    try:
        Path(dir_path).mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        logger.error(f"Failed to ensure directory {dir_path}: {e}")
        return False


def sanitize_coin_symbol(symbol: str) -> str:
    """Normalize coin symbol (uppercase, strip whitespace)."""
    return symbol.upper().strip()


def format_percent_change(change: float) -> str:
    """Format percentage change with sign."""
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.2f}%"


def format_price(price: float, decimals: int = 8) -> str:
    """Format price with appropriate decimals."""
    return f"{price:.{decimals}f}".rstrip('0').rstrip('.')


def timestamp_to_seconds_ago(timestamp_iso: str) -> int:
    """Convert ISO timestamp to seconds ago."""
    try:
        ts = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return int((now - ts).total_seconds())
    except Exception:
        return -1


def file_exists(file_path: str) -> bool:
    """Check if file exists."""
    return os.path.exists(file_path) and os.path.isfile(file_path)


def get_file_size_mb(file_path: str) -> float:
    """Get file size in MB."""
    if not file_exists(file_path):
        return 0.0
    return os.path.getsize(file_path) / (1024 * 1024)
