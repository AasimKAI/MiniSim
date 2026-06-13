"""Layer D — exit watch. Profit-target ladder, trailing stop, stop loss, max hold.

The position passed in carries persisted exit state:
  peak_pnl       — highest unrealised PnL% seen (for the trailing stop)
  targets_taken  — list of TP levels already sold (so each fires ONCE)

evaluate() returns (should_exit, fraction, reason, meta) where `meta` tells the
caller what to persist: an updated peak_pnl, and either a target_level (a TP
partial) or close=True (a full exit).
"""
import time
from config import config


def evaluate(position, price):
    entry = position["entry_price"]
    pnl = (price - entry) / entry * 100 if entry else 0.0
    age_h = (time.time() - position.get("opened_at", time.time())) / 3600
    prev_peak = position.get("peak_pnl")
    peak = pnl if prev_peak is None else max(prev_peak, pnl)
    taken = set(position.get("targets_taken", []) or [])
    meta = {"peak_pnl": round(peak, 3)}   # always persist the updated peak

    # forced exits first
    if pnl <= -config.STOP_LOSS_PERCENT:
        return True, 1.0, f"stop loss hit ({pnl:.1f}%)", {**meta, "close": True}
    if age_h >= config.MAX_HOLD_TIME_HOURS:
        return True, 1.0, f"max hold {config.MAX_HOLD_TIME_HOURS}h reached ({pnl:.1f}%)", {**meta, "close": True}

    # take-profit ladder — each level fires exactly once
    for lvl, pct, frac in [(1, config.TAKE_PROFIT_TARGET_1_PERCENT, 0.33),
                           (2, config.TAKE_PROFIT_TARGET_2_PERCENT, 0.33),
                           (3, config.TAKE_PROFIT_TARGET_3_PERCENT, 0.34)]:
        if pnl >= pct and lvl not in taken:
            return True, frac, f"take-profit T{lvl} at {pct}% (pnl {pnl:.1f}%)", {**meta, "target_level": lvl}

    # trailing stop once in real profit and pulled back from the peak
    if pnl >= 3 and (peak - pnl) >= config.TRAILING_STOP_PERCENT:
        return True, 1.0, f"trailing stop (peak {peak:.1f}% -> {pnl:.1f}%)", {**meta, "close": True}

    return False, 0.0, f"hold (pnl {pnl:.1f}%, peak {peak:.1f}%)", meta
