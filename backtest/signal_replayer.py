"""
Bar-by-bar signal replayer.
Feeds OHLCV bars through the existing analyst + decision stack.

Delta trigger: LLM is called only when analyst verdicts change from the
previous bar, avoiding redundant calls on quiet markets.

LLM cache: identical prompts (same coin + verdicts + regime) reuse cached
Ollama responses so repeated patterns don't hit the model at all.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, Generator, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cached wrappers for LLM-backed components
# ---------------------------------------------------------------------------

class _CachedResearcher:
    """Wraps Researcher and caches _call_ollama via LLMCache."""

    def __init__(self, researcher, llm_cache):
        self._r = researcher
        self._cache = llm_cache

    def build_case(self, coin: str, verdicts: list, regime: str) -> Dict:
        original = self._r._call_ollama

        def cached_call(prompt: str) -> Optional[str]:
            if self._cache is not None:
                cached = self._cache.get(prompt)
                if cached is not None:
                    return cached
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
    """Wraps CEOAgent and caches _call_ollama via LLMCache."""

    def __init__(self, ceo, llm_cache):
        self._ceo = ceo
        self._cache = llm_cache

    def decide(self, coin: str, bull_case: Dict, bear_case: Dict, regime: str, position_size_usd: float) -> Dict:
        original = self._ceo._call_ollama

        def cached_call(prompt: str) -> Optional[str]:
            if self._cache is not None:
                cached = self._cache.get(prompt)
                if cached is not None:
                    return cached
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
    """Stable hash of analyst views + regime. Changes → trigger LLM."""
    parts = sorted(f"{v['analyst']}:{v['view']}" for v in verdicts)
    return hashlib.md5(f"{regime}|{'|'.join(parts)}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# SignalReplayer
# ---------------------------------------------------------------------------

class SignalReplayer:
    """
    Replay OHLCV bars through the full MiniSim pipeline.

    Components are created externally (by BacktestRunner) and passed in so
    the replayer has no import-time coupling to specific analyst classes.
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

        # Rolling windows
        self._prices: List[float] = []
        self._volumes: List[float] = []

        # Delta trigger state
        self._prev_fingerprint: Optional[str] = None
        self._prev_signal: Optional[Dict] = None

    def replay(self, bars: List[List]) -> Generator[Dict, None, None]:
        """
        Yield one event dict per bar (after warm-up).

        Event shape:
            bar_index    int
            timestamp    ISO8601 str
            close        float
            verdicts     dict[analyst -> view]
            regime       str
            decision     str (entry_buy | entry_sell | stand_down)
            signal       dict | None  (full signal record if LLM was called)
            llm_called   bool
        """
        for i, bar in enumerate(bars):
            ts_ms, open_, high, low, close, volume = bar[:6]
            ts_iso = _ms_to_iso(ts_ms)

            # Grow rolling windows
            self._prices.append(close)
            self._volumes.append(volume)

            # Feed regime detector
            self.regime_detector.record_price(self.coin, close)

            # Skip warm-up bars — no decisions, just seeding indicators
            if i < self.warmup_bars:
                continue

            # --- Layer B: analysts ---
            verdicts = []
            tech = self.technical.analyze(self.coin, self._prices)
            verdicts.append(tech)

            vol = self.volume.analyze(self.coin, self._volumes, self._prices)
            verdicts.append(vol)

            regime_info = self.regime_detector.detect_regime(self.coin)
            regime = regime_info.get("regime", "neutral")

            # --- Delta trigger ---
            fingerprint = _verdict_fingerprint(verdicts, regime)
            llm_called = False
            signal = None

            if fingerprint != self._prev_fingerprint:
                # Verdicts changed → run full decision pipeline
                llm_called = True
                self._prev_fingerprint = fingerprint

                # Layer C: regime filter
                allowed, reason = self.regime_filter.should_allow_trade(regime, "bullish")
                if not allowed:
                    decision = "stand_down"
                    self._prev_signal = None
                else:
                    bull_case = self.bull.build_case(self.coin, verdicts, regime)
                    bear_case = self.bear.build_case(self.coin, verdicts, regime)
                    signal = self.ceo.decide(
                        self.coin,
                        bull_case,
                        bear_case,
                        regime,
                        self.config.POSITION_SIZE_USD,
                    )
                    decision = signal.get("decision", "stand_down")
                    self._prev_signal = signal
            else:
                # Verdicts unchanged → reuse previous decision
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
            }


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
