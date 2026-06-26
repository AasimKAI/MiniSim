"""Macro data feeds: Fear & Greed index + perpetual funding rates.

Both are free public APIs, no key required, cached aggressively:
  Fear & Greed  — alternative.me, updates once daily,  cached 1 h
  Funding rates — Binance fapi (Bybit fallback),        cached 15 min

Funding rate sign convention (matches Binance):
  positive → longs pay shorts (market is long-biased)
  negative → shorts pay longs (market is short-biased)
  expressed as a decimal (0.0001 = 0.01% per 8 h)
"""
import time
import httpx
from config import config

_FNG_URL      = "https://api.alternative.me/fng/?limit=2"
_BINANCE_FUND = "https://fapi.binance.com/fapi/v1/premiumIndex"
_BYBIT_FUND   = "https://api.bybit.com/v5/market/tickers?category=linear"

_FNG_TTL     = 3600   # once-daily feed — 1 h cache is fine
_FUNDING_TTL =  900   # 8 h cycle — 15 min resolution is plenty

_fng_cache:     dict = {}
_funding_cache: dict = {}

_SYMBOLS = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "XRP": "XRPUSDT",
    "ADA": "ADAUSDT", "SOL": "SOLUSDT", "BNB": "BNBUSDT",
    "DOGE": "DOGEUSDT", "AVAX": "AVAXUSDT", "DOT": "DOTUSDT",
    "LINK": "LINKUSDT", "LTC": "LTCUSDT", "NEAR": "NEARUSDT",
    "UNI": "UNIUSDT",  "ARB": "ARBUSDT", "ATOM": "ATOMUSDT",
}

_FIXTURE_FNG     = {"value": 50, "label": "Neutral", "previous": 50, "source": "fixture"}
_FIXTURE_FUNDING = {coin: 0.0 for coin in _SYMBOLS}


def get_fear_greed() -> dict:
    """Return the current Fear & Greed index.
    Keys: value (0-100), label, previous (yesterday), source.
    """
    if config.MODE == "fixture":
        return _FIXTURE_FNG.copy()

    now = time.time()
    if _fng_cache and now - _fng_cache.get("_ts", 0) < _FNG_TTL:
        return {k: v for k, v in _fng_cache.items() if k != "_ts"}

    try:
        r = httpx.get(_FNG_URL, timeout=8.0,
                      headers={"User-Agent": "MiniSim/5 macro-feed"})
        r.raise_for_status()
        data = r.json().get("data", [])
        cur  = data[0] if data else {}
        prev = data[1] if len(data) > 1 else cur
        result = {
            "value":    int(cur.get("value", 50)),
            "label":    cur.get("value_classification", "Neutral"),
            "previous": int(prev.get("value", 50)),
            "source":   "alternative.me",
        }
        _fng_cache.clear()
        _fng_cache.update(result)
        _fng_cache["_ts"] = now
        return result
    except Exception:
        return _FIXTURE_FNG.copy()


def get_funding_rates() -> dict:
    """Return the latest perpetual funding rates for all tracked coins.
    Returns {coin: float}.  Binance first; Bybit as fallback.
    """
    if config.MODE == "fixture":
        return _FIXTURE_FUNDING.copy()

    now = time.time()
    if _funding_cache and now - _funding_cache.get("_ts", 0) < _FUNDING_TTL:
        return {k: v for k, v in _funding_cache.items() if k != "_ts"}

    rates = _fetch_binance_funding() or _fetch_bybit_funding()
    _funding_cache.clear()
    _funding_cache.update(rates)
    _funding_cache["_ts"] = now
    return {k: v for k, v in _funding_cache.items() if k != "_ts"}


def _fetch_binance_funding() -> dict | None:
    try:
        r = httpx.get(_BINANCE_FUND, timeout=8.0,
                      headers={"User-Agent": "MiniSim/5 macro-feed"})
        r.raise_for_status()
        sym_map = {v: k for k, v in _SYMBOLS.items()}
        rates = {
            sym_map[row["symbol"]]: float(row.get("lastFundingRate", 0.0))
            for row in r.json()
            if row.get("symbol") in sym_map
        }
        return rates if rates else None
    except Exception:
        return None


def _fetch_bybit_funding() -> dict:
    try:
        r = httpx.get(_BYBIT_FUND, timeout=8.0,
                      headers={"User-Agent": "MiniSim/5 macro-feed"})
        r.raise_for_status()
        sym_map = {v: k for k, v in _SYMBOLS.items()}
        rates = {}
        for item in r.json().get("result", {}).get("list", []):
            coin = sym_map.get(item.get("symbol", ""))
            if coin and item.get("fundingRate") is not None:
                rates[coin] = float(item["fundingRate"])
        return rates
    except Exception:
        return _FIXTURE_FUNDING.copy()
