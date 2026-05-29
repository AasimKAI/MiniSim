"""
Bar-by-bar signal replayer.
Feeds OHLCV bars through the existing analyst + decision stack.

Delta trigger: LLM is called only when analyst verdicts change from the
previous bar (controlled by BACKTEST_LLM_DELTA_TRIGGER in config).

LLM cache: identical prompts reuse cached Ollama responses.

Ollama failure tracking: if too many LLM calls fail, the run summary
is marked suspect so the user knows results may be unreliable.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, Generator, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cached wrappers for LLM-backed components
# ---------------------------------------------------------------------------

class _CachedResearcher:
    def __init__(self, researcher, llm_cache):
        self._r = researcher
        self._cache = llm_cache

    def build_case(self, coin: str, verdicts: list, regime: str) -> Dict:
        original = self._r._call_ollama

        def cached_call(prompt: str) -> Optional[str]:
            if self._cache is not None:
                hit = self._cache.get(prompt)
                if hit is not None:
                    return hit
            result = original(prompt)
            if result and self._cache is not None:
                self._cache.set(prompt, result)
            return result

        self._r._call_ollama = cached_call
        try:
            return self._r.build_case(coin, verdicts, regime)
        finally:
            self._r._call_ollama = original


class _CachedCEOAgent:
    def __init__(self, ceo, llm_cache):
        self._ceo = ceo
        self._cache = llm_cache

    def decide(self, coin: str, bull_case: Dict, bear_case: Dict, regime: str, position_size_usd: float) -> Dict:
        original = self._ceo._call_ollama

        def cached_call(prompt: str) -> Optional[str]:
            if self._cache is not None:
                hit = self._cache.get(prompt)
                if hit is not None:
                    return hit
            result = original(prompt)
            if result and self._cache is not None:
                self._cache.set(prompt, result)
            return result

        self._ceo._call_ollama = cached_call
        try:
            return self._ceo.decide(coin, bull_case, bear_case, regime, position_size_usd)
        finally:
            self._ceo._call_ollama = original


# ---------------------------------------------------------------------------
# Verdict fingerprint for delta trigger
# ---------------------------------------------------------------------------

def _verdict_fingerprint(verdicts: List[Dict], regime: str) -> str:
    parts = sorted(f"{v['analyst']}:{v['view']}" for v in verdicts)
    return hashlib.md5(f"{regime}|{'|'.join(parts)}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# SignalReplayer
# ---------------------------------------------------------------------------

class SignalReplayer:
    """
    Replay OHLCV bars through the full MiniSim pipeline.

    Components are created externally (by BacktestRunner) and passed in.
    """

    def __init__(
        self,
        coin: str,
        technical_analyst,
        volume_analyst,
        regime_detector,
        regime_filter,
        bull_researcher,
        bear_researcher,
        ceo_agent,
        config,
        llm_cache=None,
        warmup_bars: int = 50,
    ):
        self.coin = coin
        self.technical = technical_analyst
        self.volume = volume_analyst
        self.regime_detector = regime_detector
        self.regime_filter = regime_filter
        self.bull = _CachedResearcher(bull_researcher, llm_cache)
        self.bear = _CachedResearcher(bear_researcher, llm_cache)
        self.ceo = _CachedCEOAgent(ceo_agent, llm_cache)
        self.config = config
        self.warmup_bars = warmup_bars
        self.delta_trigger_enabled = getattr(config, "BACKTEST_LLM_DELTA_TRIGGER", True)

        self._prices: List[float] = []
        self._volumes: List[float] = []
        self._prev_fingerprint: Optional[str] = None
        self._prev_signal: Optional[Dict] = None

        # Failure tracking
        self.llm_attempt_count = 0
        self.llm_failure_count = 0

    def replay(self, bars: List[List]) -> Generator[Dict, None, None]:
        """
        Yield one event dict per bar (after warm-up).

        Event keys: bar_index, timestamp, close, high, low, volume,
                    verdicts, regime, decision, signal, llm_called.
        """
        for i, bar in enumerate(bars):
            ts_ms, open_, high, low, close, volume = bar[:6]
            ts_iso = _ms_to_iso(ts_ms)

            self._prices.append(close)
            self._volumes.append(volume)
            self.regime_detector.record_price(self.coin, close)

            # Warm-up: seed indicators but make no decisions
            if i < self.warmup_bars:
                continue

            # --- Layer B: arithmetic analysts ---
            verdicts = [
                self.technical.analyze(self.coin, self._prices),
                self.volume.analyze(self.coin, self._volumes, self._prices),
            ]

            regime_info = self.regime_detector.detect_regime(self.coin)
            regime = regime_info.get("regime", "neutral")

            # --- Delta trigger ---
            fingerprint = _verdict_fingerprint(verdicts, regime)
            llm_called = False
            signal = None
            llm_failed = False

            verdicts_changed = fingerprint != self._prev_fingerprint
            should_call_llm = verdicts_changed or not self.delta_trigger_enabled

            if should_call_llm:
                llm_called = True
                self._prev_fingerprint = fingerprint
                self.llm_attempt_count += 1

                allowed, reason = self.regime_filter.should_allow_trade(regime, "bullish")
                if not allowed:
                    decision = "stand_down"
                    self._prev_signal = None
                else:
                    bull_case = self.bull.build_case(self.coin, verdicts, regime)
                    bear_case = self.bear.build_case(self.coin, verdicts, regime)

                    # Detect Ollama failure: abstained cases indicate LLM unavailability
                    if (bull_case.get("validation_result") == "abstained" and
                            bear_case.get("validation_result") == "abstained"):
                        self.llm_failure_count += 1
                        llm_failed = True

                    signal = self.ceo.decide(
                        self.coin, bull_case, bear_case, regime,
                        self.config.POSITION_SIZE_USD,
                    )
                    decision = signal.get("decision", "stand_down")
                    self._prev_signal = signal
            else:
                decision = self._prev_signal.get("decision", "stand_down") if self._prev_signal else "stand_down"
                signal = self._prev_signal

            yield {
                "bar_index": i,
                "timestamp": ts_iso,
                "close": close,
                "high": high,
                "low": low,
                "volume": volume,
                "verdicts": {v["analyst"]: v["view"] for v in verdicts},
                "regime": regime,
                "decision": decision,
                "signal": signal,
                "llm_called": llm_called,
                "llm_failed": llm_failed,
            }

    @property
    def llm_failure_rate(self) -> float:
        if self.llm_attempt_count == 0:
            return 0.0
        return self.llm_failure_count / self.llm_attempt_count


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
