"""
OHLC data fetcher with disk cache.
Downloads bars from any CCXT exchange and caches them as JSONL.
Cache key: {exchange}_{symbol_safe}_{timeframe}.jsonl
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# One OHLCV bar: [timestamp_ms, open, high, low, close, volume]
Bar = List[float]

_TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


class OHLCFetcher:
    """Fetch and cache OHLCV bars from a CCXT exchange."""

    def __init__(self, cache_dir: str, exchange_id: str = "binance"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.exchange_id = exchange_id
        self._exchange = None

    def _get_exchange(self):
        if self._exchange is None:
            try:
                import ccxt
            except ImportError:
                raise ImportError("ccxt is required. Install with: pip install ccxt")
            cls = getattr(ccxt, self.exchange_id)
            self._exchange = cls({"enableRateLimit": True})
        return self._exchange

    def _cache_path(self, symbol: str, timeframe: str) -> Path:
        safe = symbol.replace("/", "_").replace(":", "_")
        return self.cache_dir / f"{self.exchange_id}_{safe}_{timeframe}.jsonl"

    def _load_cache(self, path: Path) -> List[Bar]:
        if not path.exists():
            return []
        bars = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    bars.append(json.loads(line))
        return bars

    def _append_cache(self, path: Path, bars: List[Bar]) -> None:
        with open(path, "a") as f:
            for bar in bars:
                f.write(json.dumps(bar) + "\n")

    def fetch(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str,
        warmup_bars: int = 50,
    ) -> List[Bar]:
        """
        Return OHLCV bars for symbol/timeframe between start_date and end_date,
        plus `warmup_bars` extra bars before start_date.

        Returns bars sorted ascending by timestamp.
        """
        start_ms = self._parse_date_ms(start_date)
        end_ms = self._parse_date_ms(end_date)
        tf_ms = _TIMEFRAME_MS.get(timeframe)
        if tf_ms is None:
            raise ValueError(f"Unknown timeframe: {timeframe}. Valid: {list(_TIMEFRAME_MS)}")

        warmup_start_ms = start_ms - warmup_bars * tf_ms
        cache_path = self._cache_path(symbol, timeframe)

        cached = self._load_cache(cache_path)
        cached_ts = {b[0] for b in cached}

        # Determine what range we still need to download
        need_since = warmup_start_ms
        if cached:
            latest_cached_ts = max(b[0] for b in cached)
            if latest_cached_ts >= end_ms - tf_ms:
                # Cache covers everything — just filter and return
                return self._filter(cached, warmup_start_ms, end_ms)
            need_since = latest_cached_ts + tf_ms

        logger.info(
            f"Fetching {symbol} {timeframe} from {self._ms_to_iso(need_since)} "
            f"to {self._ms_to_iso(end_ms)} via {self.exchange_id}..."
        )

        new_bars = self._download(symbol, timeframe, need_since, end_ms, tf_ms)
        fresh = [b for b in new_bars if b[0] not in cached_ts]
        if fresh:
            self._append_cache(cache_path, fresh)
            cached.extend(fresh)

        result = self._filter(cached, warmup_start_ms, end_ms)
        logger.info(f"Fetched {len(result)} bars ({warmup_bars} warmup + {len(result) - warmup_bars} live)")
        return result

    def _download(
        self, symbol: str, timeframe: str, since_ms: int, end_ms: int, tf_ms: int
    ) -> List[Bar]:
        exchange = self._get_exchange()
        all_bars: List[Bar] = []
        cursor = since_ms
        batch = 500

        while cursor < end_ms:
            try:
                bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=batch)
            except Exception as e:
                logger.error(f"CCXT fetch error: {e}")
                time.sleep(2)
                continue

            if not bars:
                break
            all_bars.extend(b for b in bars if b[0] <= end_ms)
            cursor = bars[-1][0] + tf_ms
            if len(bars) < batch:
                break
            time.sleep(exchange.rateLimit / 1000)

        return all_bars

    @staticmethod
    def _filter(bars: List[Bar], since_ms: int, end_ms: int) -> List[Bar]:
        filtered = sorted(
            (b for b in bars if since_ms <= b[0] <= end_ms),
            key=lambda b: b[0],
        )
        return filtered

    @staticmethod
    def _parse_date_ms(date_str: str) -> int:
        """Parse YYYY-MM-DD to millisecond epoch."""
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)

    @staticmethod
    def _ms_to_iso(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
