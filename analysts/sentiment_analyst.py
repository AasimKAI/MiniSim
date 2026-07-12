"""Sentiment analyst.

Fetches headlines from the news MCP server (lightweight, no model) and runs the
LLM scoring HERE in the main process. This guarantees the quantized model is
loaded in exactly one process (not also inside the news server), saving RAM on
the Pi and keeping all inference under one hard time budget.
"""
from schemas.validators import validate_analyst_verdict
from llm.quantized_client import chat_json
from records.performance import coin_context


def sentiment_analyst(coin, mcp):
    heads = mcp.headlines(coin) or []
    if not heads:
        # Nothing real to score — abstain rather than hallucinate sentiment
        # (also saves an LLM inference per coin with no news coverage).
        return validate_analyst_verdict({
            "analyst": "sentiment", "coin": coin, "verdict": "neutral",
            "confidence": 0.0,
            "reasoning": "no coin-specific headlines — abstaining"})
    perf = coin_context(coin)
    perf_block = f"\n\n{perf}" if perf else ""
    system = ("You are a crypto market sentiment analyst. Read the headlines and "
              "judge near-term sentiment for the coin. Where available, factor in "
              "your recent trading history for this coin — if past trades have been "
              "losing, weight bearish signals more heavily.")
    user = f"Coin: {coin}\nHeadlines:\n- " + "\n- ".join(heads) + perf_block
    res = chat_json(system, user)
    verdict = res.get("verdict", "neutral")
    if verdict not in ("bullish", "bearish", "neutral"):
        verdict = "neutral"
    return validate_analyst_verdict({
        "analyst": "sentiment", "coin": coin, "verdict": verdict,
        "confidence": float(res.get("confidence", 0.0) or 0.0),
        "reasoning": (res.get("reasoning") or "")[:120],
    })
