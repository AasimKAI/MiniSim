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

_PRICE_ANCHOR = {
    "BTC": 65000, "ETH": 3400, "XRP": 0.55,  "ADA": 0.45,  "SOL": 150,
    "BNB": 600,   "DOGE": 0.15, "AVAX": 35,  "DOT": 7,     "LINK": 14,
    "LTC": 85,    "NEAR": 6,    "UNI": 8,    "ARB": 1.0,   "ATOM": 8,
}
_COINGECKO_IDS = {
    "BTC": "bitcoin",       "ETH": "ethereum",      "XRP": "ripple",
    "ADA": "cardano",       "SOL": "solana",         "BNB": "binancecoin",
    "DOGE": "dogecoin",     "AVAX": "avalanche-2",  "DOT": "polkadot",
    "LINK": "chainlink",    "LTC": "litecoin",       "NEAR": "near",
    "UNI": "uniswap",       "ARB": "arbitrum",       "ATOM": "cosmos",
}
_BINANCE_SYMBOLS = {
    "BTC": "BTCUSDT",  "ETH": "ETHUSDT",  "XRP": "XRPUSDT",
    "ADA": "ADAUSDT",  "SOL": "SOLUSDT",  "BNB": "BNBUSDT",
    "DOGE": "DOGEUSDT","AVAX": "AVAXUSDT","DOT": "DOTUSDT",
    "LINK": "LINKUSDT","LTC": "LTCUSDT",  "NEAR": "NEARUSDT",
    "UNI": "UNIUSDT",  "ARB": "ARBUSDT",  "ATOM": "ATOMUSDT",
}

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


def _real_candles_binance(coin, count=300):
    """Fetch real OHLCV candles from Binance public API (no key needed).
    Timeframe is controlled by config.CANDLE_INTERVAL (default 15m).
    Returns (candles, source) or (None, None) on any failure."""
    symbol = _BINANCE_SYMBOLS.get(coin)
    if not symbol:
        return None, None
    try:
        import httpx
        r = httpx.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": config.CANDLE_INTERVAL, "limit": count},
            timeout=10)
        r.raise_for_status()
        raw = r.json()
        if not raw or len(raw) < 10:
            return None, None
        candles = []
        for k in raw:
            candles.append({
                "t": int(k[0]) // 1000,
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            })
        return candles, "binance"
    except Exception:
        return None, None


def _real_candles_coingecko(coin):
    """Fetch real prices via CoinGecko market_chart. Used as fallback."""
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
                "volume": round(vols.get(int(t1), 0.0) / max(len(prices), 1), 4),
            })
        return candles, "coingecko"
    except Exception:
        return None, None


def _real_candles(coin, count=300):
    """Try Binance first (no rate-limit issues), fall back to CoinGecko."""
    candles, source = _real_candles_binance(coin, count)
    if candles and len(candles) >= 10:
        return candles, source
    return _real_candles_coingecko(coin)


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
        candles, source = _real_candles(coin, max(count, 300))
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


_OB_CACHE: dict = {}   # coin -> (fetched_at, result)

def get_orderbook(coin):
    """Real L2 order-book depth imbalance from Binance (top-20 levels, cached 30s).

    Imbalance = (bid_qty - ask_qty) / (bid_qty + ask_qty) in [-1, +1].
    Positive = bid-heavy (buy pressure). Negative = ask-heavy (sell pressure).
    This is a leading indicator — passive orders anticipate near-term price direction.
    Falls back to neutral on any API error.
    """
    now = time.time()
    cached = _OB_CACHE.get(coin)
    if cached and now - cached[0] < 30:
        return cached[1]

    symbol = _BINANCE_SYMBOLS.get(coin)
    result = {"coin": coin, "bid_volume": 0.0, "ask_volume": 0.0,
              "imbalance": 0.0, "spread_bps": 0.0, "approximate": False}

    if symbol and config.MODE in ("paper", "testnet", "live"):
        try:
            import httpx
            r = httpx.get(
                "https://api.binance.com/api/v3/depth",
                params={"symbol": symbol, "limit": 20},
                timeout=5.0,
            )
            r.raise_for_status()
            data = r.json()
            bid_qty = sum(float(b[1]) for b in data.get("bids", []))
            ask_qty = sum(float(a[1]) for a in data.get("asks", []))
            total   = bid_qty + ask_qty
            imb     = (bid_qty - ask_qty) / total if total else 0.0
            # Spread in bps from best bid/ask
            best_bid = float(data["bids"][0][0]) if data.get("bids") else 0
            best_ask = float(data["asks"][0][0]) if data.get("asks") else 0
            spread_bps = ((best_ask - best_bid) / best_bid * 10000) if best_bid else 0
            result = {"coin": coin,
                      "bid_volume": round(bid_qty, 2), "ask_volume": round(ask_qty, 2),
                      "imbalance": round(imb, 4), "spread_bps": round(spread_bps, 2),
                      "approximate": False}
        except Exception:
            pass   # neutral fallback

    _OB_CACHE[coin] = (now, result)
    return result


_TAKER_CACHE: dict = {}   # coin -> (fetched_at, ratio)

def get_taker_ratio(coin) -> float:
    """Taker buy ratio from last 500 Binance spot aggTrades (cached 60s).

    Binance aggTrades: m=False means BUYER was taker (aggressive buy);
    m=True means SELLER was taker (aggressive sell).
    ratio = buy_qty / total_qty in [0, 1].
    > 0.5 = buy-heavy flow (bullish pressure — leading indicator).
    < 0.5 = sell-heavy flow (bearish pressure).
    Returns 0.5 (neutral) on failure or fixture mode.
    """
    now = time.time()
    cached = _TAKER_CACHE.get(coin)
    if cached and now - cached[0] < 60:
        return cached[1]

    symbol = _BINANCE_SYMBOLS.get(coin)
    ratio = 0.5  # neutral fallback

    if symbol and config.MODE in ("paper", "testnet", "live"):
        try:
            import httpx
            r = httpx.get(
                "https://api.binance.com/api/v3/aggTrades",
                params={"symbol": symbol, "limit": 500},
                timeout=5.0,
            )
            r.raise_for_status()
            trades    = r.json()
            buy_qty   = sum(float(t["q"]) for t in trades if not t["m"])
            total_qty = sum(float(t["q"]) for t in trades)
            if total_qty > 0:
                ratio = round(buy_qty / total_qty, 4)
        except Exception:
            pass

    _TAKER_CACHE[coin] = (now, ratio)
    return ratio
