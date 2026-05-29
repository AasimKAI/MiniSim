"""
LAYER A - DATA FILTER
Removes duplicates, junk; keeps tracked coins; tags items; validates data.
Output to data/latest_clean_data.json.
"""

import logging
from typing import Dict, List, Optional, Any

from collector.utils import atomic_write_json, now_iso

logger = logging.getLogger(__name__)


class DataFilter:
    """Filters and cleans raw data from collectors."""

    def __init__(self, config, raw_data_file: str = "data/latest_raw_data.json",
                 clean_data_file: str = "data/latest_clean_data.json"):
        self.config = config
        self.raw_data_file = raw_data_file
        self.clean_data_file = clean_data_file

    def filter_and_clean(self, raw_data: Dict) -> Dict:
        """
        Process raw data: remove duplicates, junk; keep tracked coins; validate; tag items.
        Returns cleaned data structure.
        """
        if not raw_data:
            logger.warning("No raw data to filter")
            return self._empty_clean_data()

        cleaned = {
            "timestamp": now_iso(),
            "mode": raw_data.get("mode", self.config.MODE),
            "source_timestamp": raw_data.get("timestamp"),
            "feeds": {},
            "summary": {
                "feeds_processed": 0,
                "items_total": 0,
                "items_valid": 0,
                "items_filtered": 0,
                "issues": []
            }
        }

        for feed_name, feed_data in raw_data.get("feeds", {}).items():
            try:
                cleaned_feed = self._filter_feed(feed_name, feed_data)
                cleaned["feeds"][feed_name] = cleaned_feed
                cleaned["summary"]["feeds_processed"] += 1
                cleaned["summary"]["items_total"] += len(feed_data.get("items", []))
                cleaned["summary"]["items_valid"] += len(cleaned_feed.get("items", []))
                cleaned["summary"]["items_filtered"] += (
                    len(feed_data.get("items", [])) - len(cleaned_feed.get("items", []))
                )
            except Exception as e:
                logger.error(f"Error filtering {feed_name}: {e}")
                cleaned["summary"]["issues"].append(f"{feed_name}: {str(e)}")

        # Write cleaned data atomically
        if not atomic_write_json(self.clean_data_file, cleaned):
            logger.error("Failed to write clean data file")

        logger.info(f"Filter complete: {cleaned['summary']['items_valid']}/{cleaned['summary']['items_total']} items valid")
        return cleaned

    def _filter_feed(self, feed_name: str, feed_data: Dict) -> Dict:
        """Filter items within a single feed."""
        items = feed_data.get("items", [])
        filtered_items = []
        seen_hashes = set()

        for item in items:
            # Skip if not a dict
            if not isinstance(item, dict):
                continue

            # Check if coin is tracked
            coin = item.get("coin")
            if coin and coin not in self.config.TRACKED_COINS:
                continue

            # Skip duplicates (by hash of key fields)
            item_hash = self._hash_item(feed_name, item)
            if item_hash in seen_hashes:
                continue
            seen_hashes.add(item_hash)

            # Validate and tag
            validated_item = self._validate_and_tag(feed_name, item)
            if validated_item:
                filtered_items.append(validated_item)

        return {
            "source": feed_data.get("source"),
            "items": filtered_items,
            "timestamp": feed_data.get("timestamp"),
            "count": len(filtered_items),
        }

    def _hash_item(self, feed_name: str, item: Dict) -> str:
        """Create deterministic hash for duplicate detection."""
        import hashlib
        key_fields = f"{feed_name}:{item.get('coin', '')}:{item.get('timestamp', '')}"
        return hashlib.md5(key_fields.encode()).hexdigest()

    def _validate_and_tag(self, feed_name: str, item: Dict) -> Optional[Dict]:
        """
        Validate item schema and add tags.
        Returns tagged item or None if invalid.
        """
        try:
            # Basic validation
            if not isinstance(item, dict):
                return None

            # Tag with metadata
            item["_feed"] = feed_name
            item["_processed_at"] = now_iso()

            # Ensure timestamp
            if "timestamp" not in item:
                item["timestamp"] = now_iso()

            return item
        except Exception as e:
            logger.debug(f"Failed to validate and tag item from {feed_name}: {e}")
            return None

    def _empty_clean_data(self) -> Dict:
        """Return empty clean data structure."""
        return {
            "timestamp": now_iso(),
            "mode": self.config.MODE,
            "feeds": {},
            "summary": {
                "feeds_processed": 0,
                "items_total": 0,
                "items_valid": 0,
                "items_filtered": 0,
                "issues": ["No raw data"]
            }
        }
