"""News + sentiment core. Pulls headlines (or fixtures) and scores sentiment
with the quantized LLM. Always returns something safe."""
import time, hashlib
from config import config

_FIXTURES = {
    "BTC": ["ETF inflows hit record as institutions accumulate",
            "Miners hold supply amid halving aftermath",
            "Regulatory clarity improves sentiment"],
    "ETH": ["Staking yields steady after upgrade",
            "Layer-2 activity reaches new highs",
            "Gas fees fall on rollup adoption"],
    "XRP": ["Court ruling adds clarity to token status",
            "Cross-border payment pilots expand"],
    "ADA": ["Network upgrade improves throughput",
            "Developer activity ticks up"],
    "SOL": ["Outage fears ease after client diversity push",
            "DEX volume rebounds strongly"],
}


def get_headlines(coin, limit=5):
    base = _FIXTURES.get(coin, [f"{coin} trades sideways"])
    # In a real deployment, paper/live would query CryptoPanic/RSS here.
    return base[:limit]
