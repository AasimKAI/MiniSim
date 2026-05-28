"""
LAYER C - BULL & BEAR RESEARCHERS
Uses LLM to build strongest case FOR (Bull) and AGAINST (Bear).
Timeout/malformed/unavailable = abstain/stand-down.
"""

import logging
import requests
from typing import Dict, Optional
from datetime import datetime, timezone
import time

logger = logging.getLogger(__name__)


class Researcher:
    """Base researcher class for Bull/Bear cases."""

    def __init__(self, config, role: str):
        self.config = config
        self.role = role  # "bull" or "bear"
        self.ollama_url = getattr(config, 'OLLAMA_BASE_URL', 'http://localhost:11434')
        self.model = getattr(config, 'CEO_MODEL', 'llama2')
        self.timeout_sec = config.RESEARCHER_TIMEOUT_SEC
        self.max_retries = config.RESEARCHER_MAX_RETRIES

    def build_case(self, coin: str, verdicts: list, regime: str) -> Dict:
        """
        Build strongest case for role (bull or bear).
        Returns: {
            "role": "bull"|"bear",
            "coin": str,
            "case": str,
            "confidence": 0-1,
            "model_name": str,
            "model_version": str,
            "timeout_sec": float,
            "validation_result": str,
            "timestamp": ISO8601,
        }
        """
        if not verdicts:
            return self._abstain_case(coin, "no analyst verdicts")

        # Build prompt context
        verdicts_summary = "\n".join([
            f"- {v.get('analyst', 'unknown')}: {v.get('view')} ({v.get('confidence', 0):.1%})"
            for v in verdicts
        ])

        if self.role == "bull":
            prompt = f"""
You are a bull case analyst for {coin}.
Current regime: {regime}
Analyst verdicts:
{verdicts_summary}

Build the STRONGEST bullish case for {coin}. Be concise (2-3 sentences).
Focus on: momentum, technicals, sentiment, or on-chain signals that support buying.
Only mention actually bullish indicators. Be honest about weaknesses.
"""
        else:
            prompt = f"""
You are a bear case analyst for {coin}.
Current regime: {regime}
Analyst verdicts:
{verdicts_summary}

Build the STRONGEST bearish case for {coin}. Be concise (2-3 sentences).
Focus on: risks, overbought conditions, negative sentiment, or weak technicals.
Only mention actually bearish indicators. Be honest about strengths.
"""

        try:
            case_text = self._call_ollama(prompt)
            if not case_text:
                return self._abstain_case(coin, "LLM timeout")

            # Validate response
            if len(case_text) < 20:
                return self._abstain_case(coin, "LLM response too short")

            # Calculate confidence based on verdict agreement
            relevant_verdicts = [v for v in verdicts if v.get('view') != 'neutral']
            if self.role == "bull":
                matching = sum(1 for v in relevant_verdicts if v.get('view') == 'bullish')
            else:
                matching = sum(1 for v in relevant_verdicts if v.get('view') == 'bearish')

            confidence = min(0.9, matching / max(1, len(relevant_verdicts)))

            return {
                "role": self.role,
                "coin": coin,
                "case": case_text,
                "confidence": confidence,
                "model_name": self.model,
                "model_version": "1.0",
                "timeout_sec": self.timeout_sec,
                "validation_result": "valid",
                "timestamp": self._now_iso(),
            }

        except Exception as e:
            logger.error(f"{self.role} researcher error: {e}")
            return self._abstain_case(coin, f"error: {str(e)[:50]}")

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
                logger.warning(f"Ollama timeout ({self.role}), attempt {attempt + 1}/{self.max_retries}")
                if attempt < self.max_retries - 1:
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Ollama error ({self.role}): {e}")
                return None

        return None

    def _abstain_case(self, coin: str, reason: str) -> Dict:
        return {
            "role": self.role,
            "coin": coin,
            "case": f"Abstained: {reason}",
            "confidence": 0.0,
            "model_name": self.model,
            "model_version": "1.0",
            "timeout_sec": self.timeout_sec,
            "validation_result": "abstained",
            "timestamp": self._now_iso(),
        }

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()


class BullResearcher(Researcher):
    def __init__(self, config):
        super().__init__(config, "bull")


class BearResearcher(Researcher):
    def __init__(self, config):
        super().__init__(config, "bear")
