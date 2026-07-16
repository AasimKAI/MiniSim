"""Lightweight schema validation at module boundaries. No external deps."""

VERDICTS = {"bullish", "bearish", "neutral"}
ACTIONS = {"ENTRY_BUY", "ENTRY_SELL", "STAND_DOWN", "EXIT", "COVER"}

class SchemaError(ValueError):
    pass

def _require(d, keys):
    for k in keys:
        if k not in d:
            raise SchemaError(f"missing field: {k}")

def validate_analyst_verdict(d):
    _require(d, ["analyst", "coin", "verdict", "confidence"])
    if d["verdict"] not in VERDICTS:
        raise SchemaError(f"bad verdict: {d['verdict']}")
    if not (0.0 <= float(d["confidence"]) <= 1.0):
        raise SchemaError("confidence out of range")
    return d

def validate_signal(d):
    _require(d, ["signal_id", "coin", "action", "confidence", "timestamp"])
    if d["action"] not in ACTIONS:
        raise SchemaError(f"bad action: {d['action']}")
    return d

def validate_order(d):
    _require(d, ["client_order_id", "coin", "side", "quantity", "mode"])
    if d["side"] not in {"BUY", "SELL"}:
        raise SchemaError(f"bad side: {d['side']}")
    return d

def validate_position(d):
    _require(d, ["coin", "quantity", "entry_price", "opened_at"])
    return d
