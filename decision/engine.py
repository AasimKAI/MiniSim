"""
Layer C — Decision.
 regime_filter -> researchers (bull/bear, LLM) -> CEO (weighs everything).
Arithmetic aggregation is the backbone; the LLM adds a research narrative but
can never override the safety logic. Stand-down is the default.
"""
from config import config
from common import get_logger
from llm.quantized_client import chat_json

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
    """Weighted score in [-1,1] and total confidence."""
    num = 0.0; wsum = 0.0
    for v in verdicts:
        w = ANALYST_WEIGHTS.get(v["analyst"], 0.5)
        num += w * _SIGN[v["verdict"]] * v["confidence"]
        wsum += w
    score = num / wsum if wsum else 0.0
    return score


def research(coin, verdicts, regime):
    """LLM bull/bear summary — narrative only, safe fallback to empty."""
    facts = "; ".join(f"{v['analyst']}={v['verdict']}({v['confidence']:.2f})" for v in verdicts)
    sysmsg = ("You are the CEO of a cautious crypto trading desk. Given the analyst "
              "verdicts and regime, decide the single best action. Be conservative; "
              "prefer STAND_DOWN when signals conflict.")
    user = (f"Coin: {coin}\nRegime: {regime}\nAnalysts: {facts}\n"
            "Reply JSON with keys verdict (bullish|bearish|neutral) and confidence.")
    return chat_json(sysmsg, user)


def decide(coin, verdicts, regime):
    allowed, reason = regime_allows(regime)
    score = blend(verdicts)
    direction = "bullish" if score > 0 else "bearish" if score < 0 else "neutral"
    arith_conf = min(1.0, abs(score))

    ceo = research(coin, verdicts, regime)
    ceo_dir = ceo.get("verdict", "neutral")
    if ceo_dir not in ("bullish", "bearish", "neutral"):
        ceo_dir = "neutral"      # reject anything the LLM invents (XSS/garbage guard)
    ceo_conf = float(ceo.get("confidence", 0.0) or 0.0)
    ceo_conf = max(0.0, min(1.0, ceo_conf))

    # Blend arithmetic (primary) with CEO (secondary), require agreement for action
    agree = (ceo_dir == direction) and direction != "neutral"
    confidence = round(0.7 * arith_conf + 0.3 * (ceo_conf if agree else 0.0), 3)

    action = "STAND_DOWN"
    if allowed and direction == "bullish" and confidence >= config.ROUTINE_SIGNAL_CONFIDENCE_MIN:
        action = "ENTRY_BUY"
    elif allowed and direction == "bearish" and confidence >= config.ROUTINE_SIGNAL_CONFIDENCE_MIN:
        action = "ENTRY_SELL"

    reasoning = (f"regime={regime} ({reason}); blended_score={score:+.2f}; "
                 f"ceo={ceo_dir}({ceo_conf:.2f}); agree={agree}")
    return {"coin": coin, "action": action, "confidence": confidence,
            "direction": direction, "reasoning": reasoning, "regime": regime,
            "ceo_backend": ceo.get("_backend")}
