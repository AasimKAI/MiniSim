"""Layer D — exit watch. Profit-target ladder, trailing stop, stop loss, max hold.

The position passed in carries persisted exit state:
  peak_pnl       — highest unrealised PnL% seen (for the trailing stop)
  targets_taken  — list of TP levels already sold (so each fires ONCE)

Strategy-specific overrides (stored on position when entry fires):
  strat_sl        — stop-loss %    (e.g. 2.5)   default: config.STOP_LOSS_PERCENT
  strat_tp1/2/3   — TP targets %   (e.g. 8.0)   default: config.TAKE_PROFIT_*
  strat_frac1/2/3 — TP fractions   (e.g. 0.33)
  strat_trail     — trailing stop % (e.g. 5.0)   default: config.TRAILING_STOP_PERCENT
  strat_trail_min — min profit before trail activates (default 3.0%)
  strat_max_hold_h— max hold hours (e.g. 96.0)   default: config.MAX_HOLD_TIME_HOURS

evaluate() returns (should_exit, fraction, reason, meta) where `meta` tells the
caller what to persist: an updated peak_pnl, and either a target_level (a TP
partial) or close=True (a full exit).
"""
import time
from config import config


def _pos_get(position, key, default):
    """Read a strategy override or fall back to the provided default."""
    val = position.get(key)
    return val if val is not None else default


def evaluate(position, price):
    entry = position["entry_price"]
    side  = position.get("side", "LONG")

    if side == "SHORT":
        pnl = (entry - price) / entry * 100 if entry else 0.0
    else:
        pnl = (price - entry) / entry * 100 if entry else 0.0

    age_h    = (time.time() - position.get("opened_at", time.time())) / 3600
    prev_peak = position.get("peak_pnl")
    peak = pnl if prev_peak is None else max(prev_peak, pnl)
    taken = set(position.get("targets_taken", []) or [])
    meta  = {"peak_pnl": round(peak, 3)}

    # Per-strategy overrides (fall back to global config if not set)
    sl_pct      = _pos_get(position, "strat_sl",        config.STOP_LOSS_PERCENT)
    max_hold_h  = _pos_get(position, "strat_max_hold_h", config.MAX_HOLD_TIME_HOURS)
    trail_pct   = _pos_get(position, "strat_trail",     config.TRAILING_STOP_PERCENT)
    trail_min   = _pos_get(position, "strat_trail_min", 3.0)

    tp_ladder = [
        (1,
         _pos_get(position, "strat_tp1",   config.TAKE_PROFIT_TARGET_1_PERCENT),
         _pos_get(position, "strat_frac1", 0.33)),
        (2,
         _pos_get(position, "strat_tp2",   config.TAKE_PROFIT_TARGET_2_PERCENT),
         _pos_get(position, "strat_frac2", 0.33)),
        (3,
         _pos_get(position, "strat_tp3",   config.TAKE_PROFIT_TARGET_3_PERCENT),
         _pos_get(position, "strat_frac3", 0.34)),
    ]

    # ── Forced exits ──────────────────────────────────────────────────────────
    if pnl <= -sl_pct:
        strat_tag = position.get("strat_name", "")
        return True, 1.0, \
               f"stop loss hit ({pnl:.1f}% ≤ -{sl_pct:.1f}%{' ' + strat_tag if strat_tag else ''})", \
               {**meta, "close": True}

    if age_h >= max_hold_h:
        return True, 1.0, \
               f"max hold {max_hold_h:.0f}h reached (pnl {pnl:.1f}%)", \
               {**meta, "close": True}

    # ── Take-profit ladder ────────────────────────────────────────────────────
    for lvl, pct, frac in tp_ladder:
        if pct > 0 and pnl >= pct and lvl not in taken:
            return True, frac, \
                   f"take-profit T{lvl} at {pct:.0f}% (pnl {pnl:.1f}%)", \
                   {**meta, "target_level": lvl}

    # ── Trailing stop ─────────────────────────────────────────────────────────
    if pnl >= trail_min and (peak - pnl) >= trail_pct:
        return True, 1.0, \
               f"trailing stop (peak {peak:.1f}% → {pnl:.1f}%, trail {trail_pct:.1f}%)", \
               {**meta, "close": True}

    return False, 0.0, f"hold (pnl {pnl:.1f}%, peak {peak:.1f}%)", meta
