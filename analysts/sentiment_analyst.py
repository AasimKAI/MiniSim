"""Sentiment analyst.

Fetches headlines from the news MCP server (lightweight, no model) and runs the
LLM scoring HERE in the main process. This guarantees the quantized model is
loaded in exactly one process (not also inside the news server), saving RAM on
the Pi and keeping all inference under one hard time budget.
"""
from schemas.validators import validate_analyst_verdict
from llm.quantized_client import chat_json


def sentiment_analyst(coin, mcp):
    heads = mcp.headlines(coin) or []
    system = ("You are a crypto market sentiment analyst. Read the headlines and "
              "judge near-term sentiment for the coin.")
    user = f"Coin: {coin}\nHeadlines:\n- " + "\n- ".join(heads)
    res = chat_json(system, user)
    verdict = res.get("verdict", "neutral")
    if verdict not in ("bullish", "bearish", "neutral"):
        verdict = "neutral"
    return validate_analyst_verdict({
        "analyst": "sentiment", "coin": coin, "verdict": verdict,
        "confidence": float(res.get("confidence", 0.0) or 0.0),
        "reasoning": (res.get("reasoning") or "")[:120],
    })
