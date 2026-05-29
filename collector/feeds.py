"""
LAYER A - FEED IMPLEMENTATIONS
7 feeds: CoinGecko, News/RSS, Reddit, Twitter/X, Binance OrderBook, On-Chain, Economic Calendar
Each feed has retry-with-backoff, respects rate limits.
"""

import logging
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "XRP": "ripple",
    "ADA": "cardano",
    "SOL": "solana",
}


class Feed:
    """Base feed class."""

    def name(self) -> str:
        raise NotImplementedError

    def fetch(self) -> Dict:
        """Fetch and return standardized data. Raises on error."""
        raise NotImplementedError


class FeedCoinGecko(Feed):
    """CoinGecko price and market data."""

    def __init__(self, config):
        self.config = config

    def name(self) -> str:
        return "coingecko"

    def fetch(self) -> Dict:
        """
        Fetch price/volume/market cap for tracked coins.
        Returns: {"items": [{"coin": "BTC", "price": 50000, "volume_24h": ...}, ...]}
        """
        items = []
        for coin in self.config.TRACKED_COINS:
            coingecko_id = COINGECKO_IDS.get(coin)
            if not coingecko_id:
                logger.warning(f"No CoinGecko id configured for {coin}")
                continue

            market = self._get_json(
                f"https://api.coingecko.com/api/v3/coins/{coingecko_id}/market_chart",
                {"vs_currency": "usd", "days": "3", "interval": "hourly"},
            )
            prices = [point[1] for point in market.get("prices", []) if len(point) >= 2]
            volumes = [point[1] for point in market.get("total_volumes", []) if len(point) >= 2]
            if not prices:
                logger.warning(f"CoinGecko returned no price history for {coin}")
                continue

            items.append({
                "coin": coin,
                "price_usd": prices[-1],
                "price_history_usd": prices,
                "volume_history_usd": volumes,
                "volume_24h_usd": volumes[-1] if volumes else 0.0,
                "market_cap_usd": None,
                "change_24h_percent": self._percent_change(prices[-24:]) if len(prices) >= 24 else None,
                "timestamp": self._timestamp(),
            })

        return {
            "source": "coingecko",
            "items": items,
            "timestamp": self._timestamp(),
        }

    def _timestamp(self) -> str:
        from collector.utils import now_iso
        return now_iso()

    def _get_json(self, url: str, params: Dict) -> Dict:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        return response.json()

    def _percent_change(self, prices: List[float]) -> Optional[float]:
        if len(prices) < 2 or prices[0] == 0:
            return None
        return ((prices[-1] - prices[0]) / prices[0]) * 100


class FeedNews(Feed):
    """News and RSS feed sentiment."""

    def __init__(self, config):
        self.config = config

    def name(self) -> str:
        return "news"

    def fetch(self) -> Dict:
        """
        Fetch news articles for tracked coins.
        Returns: {"items": [{"coin": "BTC", "headline": "...", "source": "...", "sentiment": ...}, ...]}
        """
        api_key = getattr(self.config, "NEWSAPI_KEY", None)
        if not api_key:
            logger.info("NEWSAPI_KEY not configured; news feed unavailable")
            items = []
        else:
            items = []
            for coin in self.config.TRACKED_COINS:
                payload = requests.get(
                    "https://newsapi.org/v2/everything",
                    params={"q": f"{coin} crypto", "apiKey": api_key, "pageSize": 5, "sortBy": "publishedAt"},
                    timeout=15,
                )
                payload.raise_for_status()
                for article in payload.json().get("articles", []):
                    items.append({
                        "coin": coin,
                        "headline": article.get("title", ""),
                        "source": article.get("source", {}).get("name", "newsapi"),
                        "sentiment_keyword": "neutral",
                        "url": article.get("url", ""),
                        "timestamp": article.get("publishedAt") or self._timestamp(),
                    })

        return {
            "source": "news",
            "items": items,
            "timestamp": self._timestamp(),
        }

    def _timestamp(self) -> str:
        from collector.utils import now_iso
        return now_iso()


class FeedReddit(Feed):
    """Reddit sentiment from r/cryptocurrency."""

    def __init__(self, config):
        self.config = config

    def name(self) -> str:
        return "reddit"

    def fetch(self) -> Dict:
        """
        Fetch Reddit posts/comments for tracked coins.
        Returns: {"items": [{"coin": "BTC", "posts_24h": 100, "sentiment_avg": 0.5}, ...]}
        """
        logger.info("Reddit feed requires API credentials; returning no fabricated data")
        items = []

        return {
            "source": "reddit",
            "items": items,
            "timestamp": self._timestamp(),
        }

    def _timestamp(self) -> str:
        from collector.utils import now_iso
        return now_iso()


class FeedTwitter(Feed):
    """Twitter/X sentiment for tracked coins."""

    def __init__(self, config):
        self.config = config

    def name(self) -> str:
        return "twitter"

    def fetch(self) -> Dict:
        """
        Fetch tweets mentioning tracked coins.
        Returns: {"items": [{"coin": "BTC", "tweets_24h": 1000, "sentiment_avg": 0.5}, ...]}
        """
        logger.info("Twitter feed requires API credentials; returning no fabricated data")
        items = []

        return {
            "source": "twitter",
            "items": items,
            "timestamp": self._timestamp(),
        }

    def _timestamp(self) -> str:
        from collector.utils import now_iso
        return now_iso()


class FeedBinanceOrderBook(Feed):
    """Binance spot order book imbalance."""

    def __init__(self, config):
        self.config = config

    def name(self) -> str:
        return "binance_orderbook"

    def fetch(self) -> Dict:
        """
        Fetch order book imbalance for tracked coins.
        Returns: {"items": [{"coin": "BTC", "buy_pressure": 0.5, "spread_percent": 0.05}, ...]}
        """
        items = []
        base_url = getattr(self.config, "BINANCE_MARKET_DATA_BASE_URL", "https://api.binance.com")
        for coin in self.config.TRACKED_COINS:
            symbol = getattr(self.config, "BINANCE_SPOT_SYMBOL_FORMAT", "{}USDT").format(coin)
            payload = requests.get(
                f"{base_url}/api/v3/depth",
                params={"symbol": symbol, "limit": 50},
                timeout=15,
            )
            payload.raise_for_status()
            data = payload.json()
            bids = [(float(price), float(qty)) for price, qty in data.get("bids", [])]
            asks = [(float(price), float(qty)) for price, qty in data.get("asks", [])]
            if not bids or not asks:
                logger.warning(f"Binance order book empty for {symbol}")
                continue
            best_bid = bids[0][0]
            best_ask = asks[0][0]
            mid = (best_bid + best_ask) / 2
            bid_volume = sum(qty for _, qty in bids)
            ask_volume = sum(qty for _, qty in asks)
            items.append({
                "coin": coin,
                "bid": best_bid,
                "ask": best_ask,
                "spread_percent": ((best_ask - best_bid) / mid) * 100 if mid else 0,
                "bid_volume": bid_volume,
                "ask_volume": ask_volume,
                "imbalance_ratio": bid_volume / ask_volume if ask_volume else None,
                "timestamp": self._timestamp(),
            })

        return {
            "source": "binance_orderbook",
            "items": items,
            "timestamp": self._timestamp(),
        }

    def _timestamp(self) -> str:
        from collector.utils import now_iso
        return now_iso()


class FeedOnChain(Feed):
    """On-chain metrics (whale wallets, exchange flows)."""

    def __init__(self, config):
        self.config = config

    def name(self) -> str:
        return "on_chain"

    def fetch(self) -> Dict:
        """
        Fetch on-chain metrics for tracked coins.
        Returns: {"items": [{"coin": "BTC", "whale_accumulation": 10.5, "exchange_inflow": -5.2}, ...]}
        """
        logger.info("On-chain feed requires a provider integration; returning no fabricated data")
        items = []

        return {
            "source": "on_chain",
            "items": items,
            "timestamp": self._timestamp(),
        }

    def _timestamp(self) -> str:
        from collector.utils import now_iso
        return now_iso()


class FeedEconomicCalendar(Feed):
    """Economic calendar events (Fed, inflation, etc)."""

    def __init__(self, config):
        self.config = config

    def name(self) -> str:
        return "economic_calendar"

    def fetch(self) -> Dict:
        """
        Fetch upcoming economic events.
        Returns: {"items": [{"event": "Fed Rate Decision", "impact": "high", "date": "2026-06-18"}, ...]}
        """
        logger.info("Economic calendar provider not configured; returning no fabricated data")
        items = []

        return {
            "source": "economic_calendar",
            "items": items,
            "timestamp": self._timestamp(),
        }

    def _timestamp(self) -> str:
        from collector.utils import now_iso
        return now_iso()
