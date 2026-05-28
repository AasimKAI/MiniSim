"""
LAYER C - CEO AGENT
Weighs Bull/Bear arguments, decides ENTRIES ONLY.
Unparseable/incomplete/contradictory = stand-down.
Records: prompt version, model name, timeout result, validation result.
"""

import logging
import requests
import uuid
from typing import Dict, Optional
from datetime import datetime, timezone
import time
import json

logger = logging.getLogger(__name__)


class CEOAgent:
    """Makes final entry decisions based on researcher cases."""

    def __init__(self, config):
        self.config = config
        self.ollama_url = getattr(config, 'OLLAMA_BASE_URL', 'http://localhost:11434')
        self.model = getattr(config, 'CEO_MODEL', 'llama2')
        self.timeout_sec = config.CEO_TIMEOUT_SEC
        self.max_retries = config.CEO_MAX_RETRIES
        self.big_trade_threshold = config.BIG_TRADE_THRESHOLD_USD

    def decide(self, coin: str, bull_case: Dict, bear_case: Dict, regime: str,
               position_size_usd: float) -> Dict:
        """
        Make entry decision based on arguments.
        Returns Signal Record (schema Annex 3.2).
        """
        signal_id = str(uuid.uuid4())

        # Validate inputs
        if not bull_case or bull_case.get('validation_result') != 'valid':
            return self._stand_down(signal_id, coin, "bull case invalid", "no_valid_bull", regime)

        if not bear_case or bear_case.get('validation_result') != 'valid':
            return self._stand_down(signal_id, coin, "bear case invalid", "no_valid_bear", regime)

        # Check regime filter
        if regime in ["volatile", "neutral"]:
            return self._stand_down(signal_id, coin, f"unsuitable regime: {regime}", "regime_filter", regime)

        # Check confidence threshold
        bull_confidence = bull_case.get('confidence', 0)
        bear_confidence = bear_case.get('confidence', 0)

        if bull_confidence < self.config.ROUTINE_SIGNAL_CONFIDENCE_MIN and \
           bear_confidence < self.config.ROUTINE_SIGNAL_CONFIDENCE_MIN:
            return self._stand_down(signal_id, coin, "low confidence from both sides", "low_confidence", regime)

        # Call LLM to make decision
        prompt = f"""
You are a crypto trading CEO. Decide: ENTRY_BUY, ENTRY_SELL, or STAND_DOWN.
Coin: {coin}
Regime: {regime}

BULL CASE (confidence: {bull_confidence:.1%}):
{bull_case.get('case', 'no case')}

BEAR CASE (confidence: {bear_confidence:.1%}):
{bear_case.get('case', 'no case')}

Decide: respond with EXACTLY one of: ENTRY_BUY, ENTRY_SELL, STAND_DOWN.
"""

        try:
            decision_text = self._call_ollama(prompt)
            if not decision_text:
                return self._stand_down(signal_id, coin, "CEO LLM timeout", "llm_timeout", regime)

            # Parse decision
            decision_upper = decision_text.upper().strip()
            if "ENTRY_BUY" in decision_upper:
                decision = "entry_buy"
                view = "bullish"
                confidence = bull_confidence
            elif "ENTRY_SELL" in decision_upper:
                decision = "entry_sell"
                view = "bearish"
                confidence = bear_confidence
            else:
                return self._stand_down(signal_id, coin, f"unparseable decision: {decision_text}", "parse_error", regime)

            # Classify trade size
            is_big_trade = position_size_usd > self.big_trade_threshold

            return {
                "signal_id": signal_id,
                "decision": decision,
                "coin": coin,
                "view": view,
                "confidence": confidence,
                "bull_case": bull_case.get('case', ''),
                "bear_case": bear_case.get('case', ''),
                "regime": regime,
                "timestamp": self._now_iso(),
                "ceo_model_name": self.model,
                "ceo_model_version": "1.0",
                "ceo_timeout_sec": self.timeout_sec,
                "ceo_validation_result": "valid",
                "is_big_trade": is_big_trade,
                "schema_version": "1.0.0",
            }

        except Exception as e:
            logger.error(f"CEO decision error: {e}")
            return self._stand_down(signal_id, coin, f"error: {str(e)[:50]}", "exception", regime)

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
                logger.warning(f"CEO LLM timeout, attempt {attempt + 1}/{self.max_retries}")
                if attempt < self.max_retries - 1:
                    time.sleep(1)
            except Exception as e:
                logger.error(f"CEO LLM error: {e}")
                return None

        return None

    def _stand_down(self, signal_id: str, coin: str, reason: str, reason_code: str, regime: str) -> Dict:
        """Create stand-down signal."""
        logger.info(f"CEO standing down {coin}: {reason}")
        return {
            "signal_id": signal_id,
            "decision": "stand_down",
            "coin": coin,
            "view": "neutral",
            "confidence": 0.0,
            "bull_case": "",
            "bear_case": "",
            "regime": regime,
            "timestamp": self._now_iso(),
            "ceo_model_name": self.model,
            "ceo_model_version": "1.0",
            "ceo_timeout_sec": self.timeout_sec,
            "ceo_validation_result": f"stand_down: {reason_code}",
            "is_big_trade": False,
            "schema_version": "1.0.0",
        }

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
