"""Macro data feeds: Fear & Greed index, perpetual funding rates, dominance.

All are free public APIs, no key required, cached aggressively:
  Fear & Greed  — alternative.me, updates once daily,  cached 1 h
  Funding rates — Binance fapi (Bybit fallback),        cached 15 min
  Dominance     — CoinGecko /global,                    cached 30 min

Funding rate sign convention (matches Binance):
  positive → longs pay shorts (market is long-biased)
  negative → shorts pay longs (market is short-biased)
  expressed as a decimal (0.0001 = 0.01% per 8 h)

Dominance interpretation:
  btc_dominance rising  → capital rotating into BTC (risk-off for alts)
  btc_dominance falling → altcoin season, capital spreading out
  alt_dominance         = 100 - btc_dom - eth_dom (everything else)
"""
import time
import httpx
from config import config

_FNG_URL      = "https://api.alternative.me/fng/?limit=2"
_BINANCE_FUND = "https://fapi.binance.com/fapi/v1/premiumIndex"
_BYBIT_FUND   = "https://api.bybit.com/v5/market/tickers?category=linear"
_COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"

_FNG_TTL       = 3600   # once-daily feed — 1 h cache is fine
_FUNDING_TTL   =  900   # 8 h cycle — 15 min resolution is plenty
_DOMINANCE_TTL = 1800   # updates every few minutes but 30 min is plenty

_fng_cache:       dict = {}
_funding_cache:   dict = {}
_dominance_cache: dict = {}

_SYMBOLS = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "XRP": "XRPUSDT",
    "ADA": "ADAUSDT", "SOL": "SOLUSDT", "BNB": "BNBUSDT",
    "DOGE": "DOGEUSDT", "AVAX": "AVAXUSDT", "DOT": "DOTUSDT",
    "LINK": "LINKUSDT", "LTC": "LTCUSDT", "NEAR": "NEARUSDT",
    "UNI": "UNIUSDT",  "ARB": "ARBUSDT", "ATOM": "ATOMUSDT",
}

_FIXTURE_FNG       = {"value": 50, "label": "Neutral", "previous": 50, "source": "fixture"}
_FIXTURE_FUNDING   = {coin: 0.0 for coin in _SYMBOLS}
_FIXTURE_DOMINANCE = {
    "btc_dominance": 50.0, "eth_dominance": 15.0, "alt_dominance": 35.0,
    "total_mcap_usd": 0.0, "mcap_change_24h_pct": 0.0, "source": "fixture",
}
_FIXTURE_OI  = {coin: {"oi_usd": 0.0, "oi_change_pct": 0.0} for coin in _SYMBOLS}
_FIXTURE_LS  = {coin: {"long_pct": 0.5, "short_pct": 0.5, "ratio": 1.0} for coin in _SYMBOLS}
_FIXTURE_TRADFI = {
    "sp500": {"price": 0.0, "change_pct": 0.0},
    "vix":   {"price": 20.0, "change_pct": 0.0},
    "dxy":   {"price": 100.0, "change_pct": 0.0},
    "gold":  {"price": 0.0, "change_pct": 0.0},
}


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


_OI_TTL      = 300   # 5 min
_LS_TTL      = 300   # 5 min
_TRADFI_TTL  = 1800  # 30 min — yfinance returns daily bars

_oi_cache:      dict = {}
_ls_cache:      dict = {}
_tradfi_cache:  dict = {}

_BINANCE_OI_HIST = "https://fapi.binance.com/futures/data/openInterestHist"
_BINANCE_LS      = "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"

_TRADFI_TICKERS = {
    "sp500": "^GSPC",
    "vix":   "^VIX",
    "dxy":   "DX-Y.NYB",
    "gold":  "GC=F",
}


def _fetch_oi_one(coin: str, symbol: str) -> tuple:
    try:
        r = httpx.get(_BINANCE_OI_HIST,
                      params={"symbol": symbol, "period": "1h", "limit": 2},
                      timeout=5.0, headers={"User-Agent": "MiniSim/5 macro-feed"})
        r.raise_for_status()
        data = r.json()
        if data:
            curr = float(data[-1]["sumOpenInterestValue"])
            prev = float(data[0]["sumOpenInterestValue"]) if len(data) >= 2 else curr
            chg  = round((curr - prev) / prev * 100, 2) if prev else 0.0
            return coin, {"oi_usd": curr, "oi_change_pct": chg}
    except Exception:
        pass
    return coin, {"oi_usd": 0.0, "oi_change_pct": 0.0}


def get_open_interest() -> dict:
    """Return futures open interest (USD) + 1h change % for all tracked coins.
    {coin: {oi_usd: float, oi_change_pct: float}}
    """
    if config.MODE == "fixture":
        return _FIXTURE_OI.copy()

    now = time.time()
    if _oi_cache and now - _oi_cache.get("_ts", 0) < _OI_TTL:
        return {k: v for k, v in _oi_cache.items() if k != "_ts"}

    from concurrent.futures import ThreadPoolExecutor, as_completed
    result = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(_fetch_oi_one, coin, sym): coin
                for coin, sym in _SYMBOLS.items()}
        for f in as_completed(futs, timeout=15):
            try:
                coin, data = f.result()
                result[coin] = data
            except Exception:
                pass

    _oi_cache.clear()
    _oi_cache.update(result)
    _oi_cache["_ts"] = now
    return result


def _fetch_ls_one(coin: str, symbol: str) -> tuple:
    try:
        r = httpx.get(_BINANCE_LS,
                      params={"symbol": symbol, "period": "5m", "limit": 1},
                      timeout=5.0, headers={"User-Agent": "MiniSim/5 macro-feed"})
        r.raise_for_status()
        data = r.json()
        if data:
            row = data[0]
            lp = float(row["longAccount"])
            sp = float(row["shortAccount"])
            return coin, {"long_pct": round(lp, 4), "short_pct": round(sp, 4),
                          "ratio": round(float(row["longShortRatio"]), 3)}
    except Exception:
        pass
    return coin, {"long_pct": 0.5, "short_pct": 0.5, "ratio": 1.0}


def get_long_short_ratio() -> dict:
    """Return futures long/short account ratio for all tracked coins.
    {coin: {long_pct: float, short_pct: float, ratio: float}}
    Contrarian: >70% long is crowded; <30% long is oversold.
    """
    if config.MODE == "fixture":
        return _FIXTURE_LS.copy()

    now = time.time()
    if _ls_cache and now - _ls_cache.get("_ts", 0) < _LS_TTL:
        return {k: v for k, v in _ls_cache.items() if k != "_ts"}

    from concurrent.futures import ThreadPoolExecutor, as_completed
    result = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(_fetch_ls_one, coin, sym): coin
                for coin, sym in _SYMBOLS.items()}
        for f in as_completed(futs, timeout=15):
            try:
                coin, data = f.result()
                result[coin] = data
            except Exception:
                pass

    _ls_cache.clear()
    _ls_cache.update(result)
    _ls_cache["_ts"] = now
    return result


def get_tradfi() -> dict:
    """Return TradFi macro indicators via yfinance: S&P500, VIX, DXY, Gold.
    {sp500|vix|dxy|gold: {price: float, change_pct: float}}
    Key relationships:
      DXY rising  → crypto headwind (inverse correlation)
      VIX >25     → risk-off, avoid new longs
      S&P500 falling sharply → crypto likely follows
    """
    if config.MODE == "fixture":
        return _FIXTURE_TRADFI.copy()

    now = time.time()
    if _tradfi_cache and now - _tradfi_cache.get("_ts", 0) < _TRADFI_TTL:
        return {k: v for k, v in _tradfi_cache.items() if k != "_ts"}

    try:
        import yfinance as yf
    except ImportError:
        return _FIXTURE_TRADFI.copy()

    result = {}
    for name, ticker in _TRADFI_TICKERS.items():
        try:
            d = yf.download(ticker, period="5d", interval="1d",
                            progress=False, auto_adjust=True)
            col = d["Close"].dropna()
            if len(col) >= 2:
                curr = float(col.squeeze().iloc[-1])
                prev = float(col.squeeze().iloc[-2])
                chg  = round((curr - prev) / prev * 100, 2)
                result[name] = {"price": round(curr, 2), "change_pct": chg}
            elif len(col) == 1:
                result[name] = {"price": round(float(col.squeeze().iloc[-1]), 2),
                                "change_pct": 0.0}
        except Exception:
            result[name] = _FIXTURE_TRADFI.get(name, {"price": 0.0, "change_pct": 0.0})

    _tradfi_cache.clear()
    _tradfi_cache.update(result)
    _tradfi_cache["_ts"] = now
    return result


def get_dominance() -> dict:
    """Return BTC, ETH, and altcoin market-cap dominance from CoinGecko /global.

    Keys:
      btc_dominance     : float  — % of total market cap held by BTC
      eth_dominance     : float  — % held by ETH
      alt_dominance     : float  — everything else (100 - btc - eth)
      total_mcap_usd    : float  — total crypto market cap in USD
      mcap_change_24h_pct: float — 24h market cap change %
      source            : str
    """
    if config.MODE == "fixture":
        return _FIXTURE_DOMINANCE.copy()

    now = time.time()
    if _dominance_cache and now - _dominance_cache.get("_ts", 0) < _DOMINANCE_TTL:
        return {k: v for k, v in _dominance_cache.items() if k != "_ts"}

    try:
        r = httpx.get(_COINGECKO_GLOBAL, timeout=8.0,
                      headers={"User-Agent": "MiniSim/5 macro-feed"})
        r.raise_for_status()
        data = r.json().get("data", {})
        pct  = data.get("market_cap_percentage", {})
        btc  = round(float(pct.get("btc", 0.0)), 2)
        eth  = round(float(pct.get("eth", 0.0)), 2)
        alt  = round(max(0.0, 100.0 - btc - eth), 2)
        result = {
            "btc_dominance":      btc,
            "eth_dominance":      eth,
            "alt_dominance":      alt,
            "total_mcap_usd":     float(data.get("total_market_cap", {}).get("usd", 0.0)),
            "mcap_change_24h_pct": round(float(data.get("market_cap_change_percentage_24h_usd", 0.0)), 2),
            "source":             "coingecko",
        }
        _dominance_cache.clear()
        _dominance_cache.update(result)
        _dominance_cache["_ts"] = now
        return result
    except Exception:
        return _FIXTURE_DOMINANCE.copy()
