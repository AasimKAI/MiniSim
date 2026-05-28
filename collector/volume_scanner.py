"""
LAYER A - VOLUME SCANNER
Separate loop every 30-60 seconds, flags candidates (no trades).
Detects breakouts in volume relative to average.
"""

import logging
from typing import Dict, List, Optional

from collector.utils import now_iso

logger = logging.getLogger(__name__)


class VolumeScanner:
    """Scans for abnormal volume spikes in tracked coins."""

    def __init__(self, config):
        self.config = config
        self.volume_history = {}  # coin -> [recent volumes]

    def scan(self, clean_data: Dict) -> Dict:
        """
        Scan clean data for volume breakouts.
        Returns: {"timestamp": ..., "candidates": [{"coin": "BTC", "volume_24h": ..., "avg_volume": ..., "ratio": 2.5}]}
        """
        result = {
            "timestamp": now_iso(),
            "candidates": [],
            "summary": {
                "coins_scanned": 0,
                "breakouts_detected": 0,
            }
        }

        coingecko_feed = clean_data.get("feeds", {}).get("coingecko", {})
        items = coingecko_feed.get("items", [])

        for item in items:
            coin = item.get("coin")
            if not coin:
                continue

            result["summary"]["coins_scanned"] += 1
            volume_24h = item.get("volume_24h_usd", 0)

            # Track volume history
            if coin not in self.volume_history:
                self.volume_history[coin] = []

            self.volume_history[coin].append(volume_24h)
            # Keep only last 100 samples
            if len(self.volume_history[coin]) > 100:
                self.volume_history[coin] = self.volume_history[coin][-100:]

            # Calculate average
            if len(self.volume_history[coin]) < 5:
                continue  # Need minimum history

            avg_volume = sum(self.volume_history[coin][:-1]) / (len(self.volume_history[coin]) - 1)
            if avg_volume == 0:
                continue

            ratio = volume_24h / avg_volume
            threshold = self.config.VOLUME_BREAKOUT_THRESHOLD

            if ratio >= threshold:
                result["candidates"].append({
                    "coin": coin,
                    "volume_24h_usd": volume_24h,
                    "avg_volume_usd": avg_volume,
                    "ratio": ratio,
                    "timestamp": item.get("timestamp"),
                    "flag_reason": f"Volume breakout: {ratio:.2f}x average",
                })
                result["summary"]["breakouts_detected"] += 1
                logger.info(f"Volume breakout detected: {coin} at {ratio:.2f}x average")

        return result
