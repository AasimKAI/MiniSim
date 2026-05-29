"""
LAYER B - TECHNICAL ANALYST
Pure arithmetic: RSI, MACD, EMA, Bollinger Bands, ATR.
No LLM. Confluence, trend-aware, multi-timeframe capable.
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class TechnicalAnalyst:
    """Arithmetic-only technical analysis."""

    def __init__(self, config):
        self.config = config
        self.price_history = {}  # coin -> list of prices

    def analyze(self, coin: str, prices: List[float]) -> Dict:
        """
        Analyze using technical indicators.
        Returns standard verdict shape.
        """
        if not prices or len(prices) < self.config.RSI_PERIOD:
            return self._neutral_verdict(coin, "insufficient data")

        rsi = self._calculate_rsi(prices, self.config.RSI_PERIOD)
        macd_signal = self._calculate_macd(prices)
        ema_short = self._calculate_ema(prices, self.config.EMA_SHORT)
        ema_long = self._calculate_ema(prices, self.config.EMA_LONG)
        bb = self._calculate_bollinger_bands(prices, self.config.BB_PERIOD, self.config.BB_STDDEV)
        atr = self._calculate_atr(prices, self.config.ATR_PERIOD)

        signals = []
        if rsi and rsi > self.config.RSI_OVERBOUGHT:
            signals.append("overbought")
        if rsi and rsi < self.config.RSI_OVERSOLD:
            signals.append("oversold")
        if ema_short and ema_long and ema_short > ema_long:
            signals.append("ema_bullish")
        if ema_short and ema_long and ema_short < ema_long:
            signals.append("ema_bearish")

        view, confidence = self._classify_signals(signals)

        return {
            "analyst": "technical",
            "coin": coin,
            "view": view,
            "confidence": confidence,
            "reasoning": f"signals: {signals}, rsi={rsi:.1f}, macd={'up' if macd_signal > 0 else 'down'}",
            "timestamp": self._now_iso(),
            "data_age_seconds": 0,
            "status": "validated",
            "technical_signals": {
                "rsi": rsi,
                "macd_signal": macd_signal,
                "ema_short": ema_short,
                "ema_long": ema_long,
                "bollinger_bands": bb,
                "atr": atr,
            },
        }

    def _calculate_rsi(self, prices: List[float], period: int) -> Optional[float]:
        """Calculate RSI."""
        if len(prices) < period + 1:
            return None
        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        seed = deltas[:period]
        up = sum(d for d in seed if d > 0) / period
        down = sum(-d for d in seed if d < 0) / period
        rs = up / down if down != 0 else 0
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _calculate_macd(self, prices: List[float]) -> Optional[float]:
        """Calculate MACD signal."""
        if len(prices) < self.config.MACD_SLOW:
            return None
        ema12 = self._calculate_ema(prices, self.config.MACD_FAST)
        ema26 = self._calculate_ema(prices, self.config.MACD_SLOW)
        if ema12 and ema26:
            return ema12 - ema26
        return None

    def _calculate_ema(self, prices: List[float], period: int) -> Optional[float]:
        """Calculate exponential moving average."""
        if len(prices) < period:
            return None
        sma = sum(prices[:period]) / period
        multiplier = 2 / (period + 1)
        ema = sma
        for price in prices[period:]:
            ema = price * multiplier + ema * (1 - multiplier)
        return ema

    def _calculate_bollinger_bands(self, prices: List[float], period: int, stddev: float) -> Dict:
        """Calculate Bollinger Bands."""
        if len(prices) < period:
            return {"middle": None, "upper": None, "lower": None}
        sma = sum(prices[-period:]) / period
        variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
        std = variance ** 0.5
        return {
            "middle": sma,
            "upper": sma + (std * stddev),
            "lower": sma - (std * stddev),
        }

    def _calculate_atr(self, prices: List[float], period: int) -> Optional[float]:
        """Calculate Average True Range (simplified)."""
        if len(prices) < 2:
            return None
        ranges = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
        return sum(ranges[-period:]) / min(period, len(ranges))

    def _classify_signals(self, signals: List[str]) -> tuple:
        """Classify signals to view and confidence."""
        bullish_count = sum(1 for s in signals if 'bullish' in s.lower() or 'oversold' in s.lower())
        bearish_count = sum(1 for s in signals if 'bearish' in s.lower() or 'overbought' in s.lower())

        if bullish_count > bearish_count:
            view = "bullish"
            confidence = min(0.9, bullish_count / 5)
        elif bearish_count > bullish_count:
            view = "bearish"
            confidence = min(0.9, bearish_count / 5)
        else:
            view = "neutral"
            confidence = 0.5
        return view, confidence

    def _neutral_verdict(self, coin: str, reason: str) -> Dict:
        return {
            "analyst": "technical",
            "coin": coin,
            "view": "neutral",
            "confidence": 0.0,
            "reasoning": reason,
            "timestamp": self._now_iso(),
            "data_age_seconds": 0,
            "status": "validated",
        }

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
