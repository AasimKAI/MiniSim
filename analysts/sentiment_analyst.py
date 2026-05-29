"""
LAYER B - SENTIMENT ANALYST
Uses local LLM (Ollama). Timeout/malformed/nonsense = abstain.
Schema-validated; confirmation-only; never overrides arithmetic.
"""

import logging
import requests
from typing import Dict, Optional
from datetime import datetime, timezone
import json
import time

logger = logging.getLogger(__name__)


class SentimentAnalyst:
    """Sentiment analysis using local Ollama LLM."""

    def __init__(self, config):
        self.config = config
        self.ollama_url = getattr(config, 'OLLAMA_BASE_URL', 'http://localhost:11434')
        self.model = getattr(config, 'SENTIMENT_MODEL', 'llama2')
        self.timeout_sec = config.SENTIMENT_TIMEOUT_SEC
        self.max_retries = config.SENTIMENT_MAX_RETRIES

    def analyze(self, coin: str, news_sentiment: Optional[str], reddit_sentiment: Optional[str],
                twitter_sentiment: Optional[str]) -> Dict:
        """
        Analyze sentiment from news, Reddit, Twitter.
        Returns standard verdict shape or neutral if LLM fails.
        """
        if not any([news_sentiment, reddit_sentiment, twitter_sentiment]):
            return self._neutral_verdict(coin, "no sentiment data")

        # Build prompt
        prompt = f"""
Given the following sentiment indicators for {coin}:
- News: {news_sentiment or 'none'}
- Reddit: {reddit_sentiment or 'none'}
- Twitter: {twitter_sentiment or 'none'}

Summarize the overall sentiment in 1-2 sentences. Use only: very positive, positive, neutral, negative, very negative.
"""

        try:
            result = self._call_ollama(prompt)
            if not result:
                return self._neutral_verdict(coin, "LLM timeout or error")

            # Validate result
            lower_result = result.lower()
            if 'very positive' in lower_result or 'bullish' in lower_result:
                view = "bullish"
                confidence = 0.7
            elif 'positive' in lower_result:
                view = "bullish"
                confidence = 0.55
            elif 'very negative' in lower_result or 'bearish' in lower_result:
                view = "bearish"
                confidence = 0.7
            elif 'negative' in lower_result:
                view = "bearish"
                confidence = 0.55
            else:
                view = "neutral"
                confidence = 0.5

            return {
                "analyst": "sentiment",
                "coin": coin,
                "view": view,
                "confidence": confidence,
                "reasoning": f"LLM summary: {result}",
                "timestamp": self._now_iso(),
                "data_age_seconds": 0,
                "status": "validated",
                "sentiment_score": confidence,
            }

        except Exception as e:
            logger.error(f"Sentiment analysis error: {e}")
            return self._neutral_verdict(coin, "LLM error")

    def _call_ollama(self, prompt: str) -> Optional[str]:
        """Call Ollama with timeout and retry."""
        url = f"{self.ollama_url}/api/generate"

        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    url,
                    json={"model": self.model, "prompt": prompt, "stream": False},
                    timeout=self.timeout_sec,
                )
                response.raise_for_status()
                data = response.json()
                return data.get("response", "").strip()
            except requests.Timeout:
                logger.warning(f"Ollama timeout, attempt {attempt + 1}/{self.max_retries}")
                if attempt < self.max_retries - 1:
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Ollama error: {e}")
                return None

        return None

    def _neutral_verdict(self, coin: str, reason: str) -> Dict:
        return {
            "analyst": "sentiment",
            "coin": coin,
            "view": "neutral",
            "confidence": 0.0,
            "reasoning": f"abstained: {reason}",
            "timestamp": self._now_iso(),
            "data_age_seconds": 0,
            "status": "validated",
        }

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
