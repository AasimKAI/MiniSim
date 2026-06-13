"""Layer F — append-only decision log."""
import time, uuid
from config import config
from common import append_jsonl, utcnow_iso
from schemas.validators import validate_signal

def log_decision(coin, action, confidence, reasoning, extra=None):
    rec = {"signal_id": str(uuid.uuid4()), "coin": coin, "action": action,
           "confidence": round(float(confidence), 3), "timestamp": utcnow_iso(),
           "reasoning": reasoning}
    if extra:
        rec.update(extra)
    validate_signal(rec)
    append_jsonl(config.DECISION_LOG, rec)
    return rec
