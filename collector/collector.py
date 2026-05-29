"""
LAYER A - DATA COLLECTOR
Fetches all 7 feeds every 5 minutes, writes to data/latest_raw_data.json.
Single feed failure never stops others.
Every feed has retry-with-backoff, respects rate limits.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from collector.utils import atomic_write_json, now_iso, retry_with_backoff, ensure_dir
from collector.feeds import (
    FeedCoinGecko, FeedNews, FeedReddit, FeedTwitter,
    FeedBinanceOrderBook, FeedOnChain, FeedEconomicCalendar
)

logger = logging.getLogger(__name__)


class Collector:
    """Orchestrates all data feeds."""

    def __init__(self, config, data_dir: str = "data"):
        self.config = config
        self.data_dir = data_dir
        self.raw_data_file = f"{data_dir}/latest_raw_data.json"

        self.feeds = [
            FeedCoinGecko(config),
            FeedNews(config),
            FeedReddit(config),
            FeedTwitter(config),
            FeedBinanceOrderBook(config),
            FeedOnChain(config),
            FeedEconomicCalendar(config),
        ]

        ensure_dir(data_dir)
        logger.info(f"Collector initialized with {len(self.feeds)} feeds, output: {self.raw_data_file}")

    def collect_all(self) -> Dict:
        """
        Collect from all feeds, return combined result.
        Single feed failure does NOT stop others.
        """
        result = {
            "timestamp": now_iso(),
            "mode": self.config.MODE,
            "feeds": {},
            "summary": {
                "total_feeds": len(self.feeds),
                "successful": 0,
                "failed": 0,
                "errors": {}
            }
        }

        for feed in self.feeds:
            feed_name = feed.name()
            logger.info(f"Collecting from {feed_name}...")

            try:
                data = retry_with_backoff(feed.fetch, max_retries=3, initial_delay=1.0)
                if data is None:
                    result["summary"]["failed"] += 1
                    result["summary"]["errors"][feed_name] = "Retries exhausted"
                    logger.warning(f"Feed {feed_name} failed after retries")
                else:
                    result["feeds"][feed_name] = data
                    result["summary"]["successful"] += 1
                    logger.info(f"Feed {feed_name} collected: {len(data.get('items', []))} items")
            except Exception as e:
                result["summary"]["failed"] += 1
                result["summary"]["errors"][feed_name] = str(e)
                logger.error(f"Exception collecting {feed_name}: {e}")

        # Write raw data atomically
        if not atomic_write_json(self.raw_data_file, result):
            logger.error("Failed to write raw data file (atomic write)")
            return result

        logger.info(f"Collector completed: {result['summary']['successful']}/{result['summary']['total_feeds']} feeds successful")
        return result

    def get_latest_raw_data(self) -> Optional[Dict]:
        """Retrieve latest collected raw data."""
        import json
        try:
            with open(self.raw_data_file) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read raw data: {e}")
            return None
