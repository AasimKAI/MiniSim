"""
Technical indicators for analysis.
RSI, MACD, EMA, Bollinger Bands, ATR - pure arithmetic, no LLM.
"""

import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
    """
    Calculate Relative Strength Index.
    Returns RSI value 0-100, or None if insufficient data.
    """
    if not prices or len(prices) < period + 1:
        return None

    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 0.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[Dict]:
    """
    Calculate MACD (Moving Average Convergence Divergence).
    Returns: {"macd": float, "signal": float, "histogram": float} or None if insufficient data.
    """
    if not prices or len(prices) < slow:
        return None

    ema_fast = calculate_ema(prices, fast)
    ema_slow = calculate_ema(prices, slow)

    if not ema_fast or not ema_slow or len(ema_fast) < signal:
        return None

    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = calculate_ema(macd_line, signal)

    if not signal_line:
        return None

    return {
        "macd": macd_line[-1],
        "signal": signal_line[-1],
        "histogram": macd_line[-1] - signal_line[-1],
    }


def calculate_ema(prices: List[float], period: int) -> Optional[List[float]]:
    """
    Calculate Exponential Moving Average.
    Returns list of EMA values or None if insufficient data.
    """
    if not prices or len(prices) < period:
        return None

    ema_values = []
    multiplier = 2 / (period + 1)

    # Start with SMA for first value
    sma = sum(prices[:period]) / period
    ema_values.append(sma)

    for price in prices[period:]:
        ema = (price - ema_values[-1]) * multiplier + ema_values[-1]
        ema_values.append(ema)

    return ema_values


def calculate_bollinger_bands(prices: List[float], period: int = 20, stddev: int = 2) -> Optional[Dict]:
    """
    Calculate Bollinger Bands.
    Returns: {"upper": float, "middle": float, "lower": float} or None if insufficient data.
    """
    if not prices or len(prices) < period:
        return None

    sma = sum(prices[-period:]) / period
    variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
    std = variance ** 0.5

    return {
        "upper": sma + (std * stddev),
        "middle": sma,
        "lower": sma - (std * stddev),
    }


def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Optional[float]:
    """
    Calculate Average True Range.
    Returns ATR value or None if insufficient data.
    """
    if not highs or not lows or not closes or len(highs) < period:
        return None

    true_ranges = []
    for i in range(len(closes)):
        h = highs[i]
        l = lows[i]
        c = closes[i - 1] if i > 0 else closes[i]
        tr = max(h - l, abs(h - c), abs(l - c))
        true_ranges.append(tr)

    atr = sum(true_ranges[-period:]) / period
    return atr


def calculate_sma(prices: List[float], period: int) -> Optional[float]:
    """
    Calculate Simple Moving Average.
    Returns SMA value or None if insufficient data.
    """
    if not prices or len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def is_price_trend_up(short_ema: Optional[float], long_ema: Optional[float]) -> bool:
    """Check if price is trending up (short EMA above long EMA)."""
    if short_ema is None or long_ema is None:
        return False
    return short_ema > long_ema


def is_price_trend_down(short_ema: Optional[float], long_ema: Optional[float]) -> bool:
    """Check if price is trending down (short EMA below long EMA)."""
    if short_ema is None or long_ema is None:
        return False
    return short_ema < long_ema


def get_signal_confluence(signals: Dict[str, bool]) -> int:
    """
    Count number of bullish signals.
    Returns count of True values.
    """
    return sum(1 for v in signals.values() if v)
