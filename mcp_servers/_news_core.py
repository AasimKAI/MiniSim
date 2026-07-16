"""News core. Fetches real headlines from free crypto RSS feeds in live modes;
falls back to deterministic fixtures when offline or in fixture mode."""
import time, hashlib, re
from config import config

_COIN_KEYWORDS = {
    "BTC":  ["bitcoin", "btc"],
    "ETH":  ["ethereum", "eth", "ether"],
    "XRP":  ["xrp", "ripple"],
    "ADA":  ["cardano", "ada"],
    "SOL":  ["solana", "sol"],
    "BNB":  ["bnb", "binance coin", "binance smart chain", "bsc"],
    "DOGE": ["dogecoin", "doge"],
    "AVAX": ["avalanche", "avax"],
    "DOT":  ["polkadot", "dot"],
    "LINK": ["chainlink", "link"],
    "LTC":  ["litecoin", "ltc"],
    "NEAR": ["near protocol", "near"],
    "UNI":  ["uniswap", "uni"],
    "ARB":  ["arbitrum", "arb"],
    "ATOM": ["cosmos", "atom"],
}

_FIXTURES = {
    "BTC":  ["ETF inflows hit record as institutions accumulate",
             "Miners hold supply amid halving aftermath",
             "Regulatory clarity improves sentiment"],
    "ETH":  ["Staking yields steady after upgrade",
             "Layer-2 activity reaches new highs",
             "Gas fees fall on rollup adoption"],
    "XRP":  ["Court ruling adds clarity to token status",
             "Cross-border payment pilots expand"],
    "ADA":  ["Network upgrade improves throughput",
             "Developer activity ticks up"],
    "SOL":  ["Outage fears ease after client diversity push",
             "DEX volume rebounds strongly"],
    "BNB":  ["Binance expands product suite amid regulatory progress",
             "BNB Chain throughput reaches new highs"],
    "DOGE": ["Retail interest in Dogecoin picks up on social media",
             "DOGE payment integrations widen"],
    "AVAX": ["Avalanche subnet activity grows as institutions pilot chains",
             "AVAX staking participation rises"],
    "DOT":  ["Polkadot parachain auctions drive ecosystem growth",
             "DOT cross-chain bridge volume increases"],
    "LINK": ["Chainlink CCIP adoption accelerates across DeFi",
             "LINK oracle integrations reach new milestone"],
    "LTC":  ["Litecoin on-chain activity steady amid market consolidation",
             "LTC halving narrative draws miner interest"],
    "NEAR": ["NEAR Protocol developer activity accelerates",
             "NEAR AI integration draws new partnerships"],
    "UNI":  ["Uniswap v4 launch drives protocol fee revenue higher",
             "UNI governance vote passes new incentive structure"],
    "ARB":  ["Arbitrum TVL reaches new high as DeFi migrates to L2",
             "ARB airdrop recipients remain active on-chain"],
    "ATOM": ["Cosmos IBC transfer volume hits record",
             "ATOM staking yield attracts new validators"],
}

_RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://cryptoslate.com/feed/",
    "https://bitcoinist.com/feed/",
]

# cache: coin -> {"ts": float, "headlines": [...]}
_CACHE: dict = {}
_CACHE_TTL = 300  # 5 minutes


def _fetch_rss_titles(url: str, timeout: int = 8) -> list:
    """Fetch an RSS feed and return all <title> text values (skipping the channel title)."""
    try:
        import httpx
        r = httpx.get(url, timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": "MiniSim/5 news-fetcher"})
        r.raise_for_status()
        # Fast regex extraction — avoids pulling in feedparser as a dependency
        titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", r.text, re.DOTALL)
        if not titles:
            titles = re.findall(r"<title>(.*?)</title>", r.text, re.DOTALL)
        # First title is always the channel name — skip it
        return [t.strip() for t in titles[1:] if t.strip()]
    except Exception:
        return []


def _real_headlines(coin: str, limit: int = 5) -> list:
    """Fetch and filter headlines from RSS feeds for the given coin."""
    keywords = _COIN_KEYWORDS.get(coin, [coin.lower()])
    collected = []
    for feed_url in _RSS_FEEDS:
        titles = _fetch_rss_titles(feed_url)
        for title in titles:
            low = title.lower()
            if any(kw in low for kw in keywords):
                # Decode HTML entities
                title = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), title)
                title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                if title not in collected:
                    collected.append(title)
            if len(collected) >= limit:
                break
        if len(collected) >= limit:
            break
    return collected[:limit]


def get_headlines(coin: str, limit: int = 5) -> list:
    """Return recent news headlines for coin.
    Uses real RSS feeds in paper/testnet/live mode; fixtures in fixture mode or on error."""
    if config.MODE == "fixture":
        base = _FIXTURES.get(coin, [f"{coin} trades sideways"])
        return base[:limit]

    # Check cache
    cached = _CACHE.get(coin)
    if cached and (time.time() - cached["ts"]) < _CACHE_TTL:
        return cached["headlines"][:limit]

    headlines = _real_headlines(coin, limit)
    # No fixture fallback outside fixture mode: the canned headlines are
    # permanently bullish, and scoring them as real news injected a
    # systematic long bias for alts with no RSS coverage (UNI, DOGE, …).
    # An empty list makes the sentiment analyst abstain instead.

    _CACHE[coin] = {"ts": time.time(), "headlines": headlines}
    return headlines
