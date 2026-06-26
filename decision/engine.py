"""
Layer C — Decision.
 regime_filter -> researchers (bull/bear, LLM) -> CEO (weighs everything).
Arithmetic aggregation is the backbone; the LLM adds a research narrative but
can never override the safety logic. Stand-down is the default.

v5.1 — multi-strategy extension:
  Strategy signals from strategies/router.py are passed into the CEO prompt
  so the LLM knows which strategies are firing for this coin and can choose
  which strategy's params to use for execution.
"""
from config import config
from common import get_logger
from llm.quantized_client import chat_json
from records.performance import build_context

log = get_logger("decision")

# how much each analyst counts toward the blended score
ANALYST_WEIGHTS = {"technical": 1.4, "volume": 0.7, "order_book": 0.7,
                   "on_chain": 0.5, "sentiment": 0.9}
_SIGN = {"bullish": 1, "bearish": -1, "neutral": 0}


def regime_allows(regime):
    if not config.REGIME_FILTER_ENABLED:
        return True, "regime filter disabled"
    if regime == "trending":
        return True, "trending regime"
    if regime == "ranging":
        return (not config.REGIME_FILTER_STRICT), \
               ("ranging allowed" if not config.REGIME_FILTER_STRICT else "ranging blocked (strict)")
    return False, f"{regime} regime blocks new entries"


def blend(verdicts):
    """Weighted score in [-1,1]."""
    num = 0.0; wsum = 0.0
    for v in verdicts:
        w = ANALYST_WEIGHTS.get(v["analyst"], 0.5)
        num += w * _SIGN[v["verdict"]] * v["confidence"]
        wsum += w
    score = num / wsum if wsum else 0.0
    return score


def _strategy_context(strategy_signals: list | None) -> str:
    """Format active strategy signals for the CEO prompt."""
    if not strategy_signals:
        return ""
    active = [s for s in strategy_signals if s["action"] != "HOLD"]
    if not active:
        hold_names = [s["strategy"] for s in strategy_signals]
        return f"\n\nActive strategies all hold: {', '.join(hold_names)}."
    lines = [
        f"  • {s['strategy']}: {s['action']} ({s['confidence']:.0%}) — {s['reason']}"
        for s in active
    ]
    return "\n\nActive strategy signals:\n" + "\n".join(lines)


def _strategy_params_block(strategy_signals: list | None) -> str:
    """Summarise each active strategy's SL/TP so CEO can choose one."""
    if not strategy_signals:
        return ""
    from strategies import REGISTRY
    lines = []
    for s in strategy_signals:
        name = s["strategy"]
        inst = REGISTRY.get(name)
        if inst:
            p = inst.params
            lines.append(
                f"  • {name}: SL={p.sl_pct*100:.1f}%  "
                f"TP={p.tp1_pct*100:.0f}/{p.tp2_pct*100:.0f}/{p.tp3_pct*100:.0f}%  "
                f"trail={p.trail_pct*100:.0f}%  side={p.side}"
            )
    return ("\n\nStrategy parameters (pick one to execute):\n"
            + "\n".join(lines)) if lines else ""


def research(coin, verdicts, regime, strategy_signals=None, macro_context=""):
    """LLM CEO decision — returns JSON with verdict, confidence, and chosen strategy."""
    facts = "; ".join(f"{v['analyst']}={v['verdict']}({v['confidence']:.2f})" for v in verdicts)
    perf  = build_context(coin=coin)
    perf_block    = f"\n\n{perf}" if perf else ""
    strat_ctx     = _strategy_context(strategy_signals)
    strat_params  = _strategy_params_block(strategy_signals) if strategy_signals else ""
    macro_block   = f"\nMacro: {macro_context}" if macro_context else ""

    has_strategies = bool(strategy_signals)
    strategy_instr = (
        "\nIf you decide to trade, also return 'strategy': the name of the active "
        "strategy whose parameters should be used. If no strategy fits, omit it."
        if has_strategies else ""
    )

    sysmsg = (
        "You are the CEO of a cautious crypto trading desk. Given the analyst "
        "verdicts, regime, active strategy signals, and your recent trading "
        "performance, decide the single best action. Rules:\n"
        "1. Be conservative — prefer STAND_DOWN when signals conflict.\n"
        "2. Never trade if regime blocks it.\n"
        "3. If strategy signals fire, prefer strategies whose 'best_for' matches "
        "the current regime and direction.\n"
        "4. A strategy with recent losses should get lower weight.\n"
        "5. Agree with analyst arithmetic unless there is a clear reason not to.\n"
        "6. Use macro context (Fear & Greed, funding bias) as a tie-breaker: "
        "extreme fear favours longs; extreme greed + long_crowded funding favours shorts."
    )

    user = (
        f"Coin: {coin}\n"
        f"Regime: {regime}\n"
        f"Analysts: {facts}"
        f"{macro_block}"
        f"{strat_ctx}"
        f"{strat_params}"
        f"{perf_block}\n"
        f"Reply JSON with keys: verdict (bullish|bearish|neutral), confidence (0-1)."
        f"{strategy_instr}"
    )
    return chat_json(sysmsg, user)


def decide(coin, verdicts, regime, strategy_signals=None, macro_context=""):
    """
    Full decision pipeline.

    strategy_signals: optional list of dicts from Strategy.signal():
        [{"action": "BUY"|"SELL"|"HOLD", "confidence": float,
          "reason": str, "strategy": str}, ...]

    Returns:
        {"coin", "action", "confidence", "direction", "reasoning",
         "regime", "strategy", "ceo_backend"}
    """
    allowed, reason = regime_allows(regime)
    score     = blend(verdicts)
    direction = "bullish" if score > 0 else "bearish" if score < 0 else "neutral"
    arith_conf = min(1.0, abs(score))

    ceo = research(coin, verdicts, regime, strategy_signals=strategy_signals,
                   macro_context=macro_context)

    ceo_dir = ceo.get("verdict", "neutral")
    if ceo_dir not in ("bullish", "bearish", "neutral"):
        ceo_dir = "neutral"
    ceo_conf = float(ceo.get("confidence", 0.0) or 0.0)
    ceo_conf = max(0.0, min(1.0, ceo_conf))

    # CEO must agree with arithmetic for a trade to fire
    agree      = (ceo_dir == direction) and direction != "neutral"
    confidence = round(0.7 * arith_conf + 0.3 * (ceo_conf if agree else 0.0), 3)

    # Which strategy did the CEO choose?
    chosen_strategy = ceo.get("strategy")
    from strategies import REGISTRY
    if chosen_strategy not in REGISTRY:
        chosen_strategy = None

    # If no strategy chosen but signals fired, use the highest-confidence one
    if not chosen_strategy and strategy_signals:
        active = [s for s in strategy_signals if s["action"] != "HOLD"]
        if active:
            chosen_strategy = max(active, key=lambda x: x["confidence"])["strategy"]
            if chosen_strategy not in REGISTRY:
                chosen_strategy = None

    action = "STAND_DOWN"
    if allowed and direction == "bullish" and confidence >= config.ROUTINE_SIGNAL_CONFIDENCE_MIN:
        # Check strategy side constraint
        strat_inst = REGISTRY.get(chosen_strategy) if chosen_strategy else None
        if strat_inst and strat_inst.params.side == "SHORT":
            pass  # don't buy with a SHORT-only strategy
        else:
            action = "ENTRY_BUY"
    elif allowed and direction == "bearish" and confidence >= config.ROUTINE_SIGNAL_CONFIDENCE_MIN:
        strat_inst = REGISTRY.get(chosen_strategy) if chosen_strategy else None
        if strat_inst and strat_inst.params.side == "LONG":
            pass  # don't sell with a LONG-only strategy
        else:
            action = "ENTRY_SELL"

    reasoning = (
        f"regime={regime} ({reason}); blended_score={score:+.2f}; "
        f"ceo={ceo_dir}({ceo_conf:.2f}); agree={agree}; "
        f"strategy={chosen_strategy or 'none'}"
    )

    return {
        "coin":        coin,
        "action":      action,
        "confidence":  confidence,
        "direction":   direction,
        "reasoning":   reasoning,
        "regime":      regime,
        "strategy":    chosen_strategy,
        "ceo_backend": ceo.get("_backend"),
    }
