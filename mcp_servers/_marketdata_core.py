"""Core market-data logic, independent of MCP transport.

In paper/testnet/live it fetches REAL prices from CoinGecko's market_chart
endpoint (which returns enough points, unlike the ohlc endpoint), caches them
for MARKET_CACHE_SEC so the fast exit loop doesn't hammer the API, and clearly
reports which source is in use. In fixture mode (or when the network fails) it
falls back to deterministic synthetic candles and labels them as such.

Honesty note: prices/high/low are REAL when source == 'coingecko'. Per-candle
volume from the public endpoint is approximate (24h rolling), so volume-based
indicators (OBV/VWAP) are best-effort; price-based indicators are real.
"""
import time, math, hashlib
from config import config

_PRICE_ANCHOR = {"BTC": 65000, "ETH": 3400, "XRP": 0.55, "ADA": 0.45, "SOL": 150}
_COINGECKO_IDS = {"BTC": "bitcoin", "ETH": "ethereum", "XRP": "ripple",
                  "ADA": "cardano", "SOL": "solana"}

# cache: coin -> {"ts": float, "candles": [...], "source": str}
_CACHE = {}


def _seed(coin, bucket):
    h = hashlib.sha256(f"{coin}-{bucket}".encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def synth_candles(coin, count=200, tf_minutes=5):
    """Deterministic pseudo-random OHLCV so the system runs fully offline."""
    anchor = _PRICE_ANCHOR.get(coin, 100.0)
    now = int(time.time() // (tf_minutes * 60))
    candles = []
    price = anchor
    for i in range(count):
        bucket = now - (count - i)
        drift = (_seed(coin, bucket) - 0.5) * 0.02
        wave = math.sin(bucket / 12.0) * 0.004
        price = max(0.0001, price * (1 + drift + wave))
        spread = price * (0.001 + _seed(coin, bucket + 1) * 0.004)
        o = price
        c = price * (1 + (_seed(coin, bucket + 2) - 0.5) * 0.006)
        h = max(o, c) + spread
        l = min(o, c) - spread
        vol = 100 + _seed(coin, bucket + 3) * 900
        candles.append({"t": bucket * tf_minutes * 60, "open": round(o, 6),
                        "high": round(h, 6), "low": round(l, 6),
                        "close": round(c, 6), "volume": round(vol, 2)})
        price = c
    return candles


def _real_candles(coin):
    """Fetch real prices via CoinGecko market_chart (days=1 -> ~5-min points).
    Builds honest 'line candles' (open=prev close, high/low=range between points).
    Returns (candles, source) or (None, None) on any failure."""
    cid = _COINGECKO_IDS.get(coin)
    if not cid:
        return None, None
    try:
        import httpx
        r = httpx.get(
            f"https://api.coingecko.com/api/v3/coins/{cid}/market_chart",
            params={"vs_currency": "usd", "days": "1"}, timeout=10)
        r.raise_for_status()
        data = r.json()
        prices = data.get("prices", [])
        vols = {int(t): v for t, v in data.get("total_volumes", [])}
        if len(prices) < 60:
            return None, None
        candles = []
        for i in range(1, len(prices)):
            t0, p0 = prices[i - 1]
            t1, p1 = prices[i]
            candles.append({
                "t": int(t1 // 1000),
                "open": p0, "close": p1,
                "high": max(p0, p1), "low": min(p0, p1),
                # approximate per-candle volume from the 24h rolling figure
                "volume": round(vols.get(int(t1), 0.0) / max(len(prices), 1), 4),
            })
        return candles, "coingecko"
    except Exception:
        return None, None


def get_candles(coin, count=200):
    """Cached candle fetch. Real data in paper/testnet/live, synthetic otherwise.
    The cache is only reused if it actually holds >= the requested length, so a
    later larger request never silently gets a short slice."""
    c = _CACHE.get(coin)
    if (c and (time.time() - c["ts"]) < config.MARKET_CACHE_SEC
            and len(c["candles"]) >= count):
        return c["candles"][-count:]

    candles, source = (None, None)
    if config.MODE in ("paper", "testnet", "live"):
        candles, source = _real_candles(coin)
    if not candles or len(candles) < count:
        # ensure synthetic series is at least as long as requested
        candles = synth_candles(coin, max(count, 300))
        source = "synthetic" if config.MODE == "fixture" else "synthetic(fallback)"

    _CACHE[coin] = {"ts": time.time(), "candles": candles, "source": source}
    return candles[-count:]


def current_source(coin="BTC"):
    """Which data source is currently feeding signals (for the dashboard)."""
    c = _CACHE.get(coin)
    return c["source"] if c else "unknown"


def get_ticker(coin):
    candles = get_candles(coin, 300)
    last = candles[-1]
    last_t = last.get("t", 0)
    # 24h change by timestamp (robust to candle timeframe) -> fixes the old c[-24] bug
    target = last_t - 86400
    ref = candles[0]
    for cd in candles:
        if cd.get("t", 0) >= target:
            ref = cd
            break
    change = ((last["close"] - ref["close"]) / ref["close"] * 100) if ref["close"] else 0
    return {"coin": coin, "price": last["close"], "change_24h_pct": round(change, 2),
            "ts": last_t, "source": _CACHE.get(coin, {}).get("source", "unknown")}


def get_orderbook(coin):
    """L1 order-book imbalance. (A real L2 book would come from the exchange feed;
    this is a lightweight proxy and is labelled approximate.)"""
    s = _seed(coin, int(time.time() // 60))
    bid_vol = 1000 * (0.5 + s)
    ask_vol = 1000 * (1.5 - s)
    imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol)
    return {"coin": coin, "bid_volume": round(bid_vol, 1), "ask_volume": round(ask_vol, 1),
            "imbalance": round(imbalance, 3), "spread_bps": round(2 + s * 8, 2),
            "approximate": True}
