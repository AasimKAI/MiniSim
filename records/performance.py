"""Performance tracker.

Reads the decision log and tax ledger to compute recent trading outcomes:
  - Per-coin: closed trade P&L, win rate, streak
  - Per-analyst: accuracy (did their verdict predict the profitable direction?)
  - Per-regime: win rate in trending vs ranging markets

Results are formatted as compact text injected into LLM prompts so the model
can bias its reasoning toward strategies that have been working and away from
those that have been losing — a lightweight prompt-based feedback loop.

All I/O is read-only; this module never writes to disk.
"""
import json, os
from config import config
from common import get_logger

log = get_logger("performance")


# ---------- loaders ----------

def _iter_jsonl(path):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except Exception:
                    pass


def _load_fills():
    return list(_iter_jsonl(config.TAX_LEDGER))


def _load_decisions():
    return list(_iter_jsonl(config.DECISION_LOG))


# ---------- trade matching ----------

def _match_trades(fills):
    """FIFO-match BUY/SELL pairs (longs) and SHORT/COVER pairs (shorts) per coin.
    Returns list of closed-trade dicts with a 'direction' field ('long'|'short')."""
    from collections import deque
    buy_queues   = {}   # coin -> deque of {price, qty, ts}
    short_queues = {}   # coin -> deque of {price, qty, ts}
    closed = []

    for f in sorted(fills, key=lambda x: x.get("timestamp", "")):
        coin = f["coin"]
        side = f["side"]
        price = float(f.get("price_usd", 0))
        qty = float(f.get("quantity", 0))
        ts = f.get("timestamp", "")

        if side == "BUY":
            buy_queues.setdefault(coin, deque()).append(
                {"price": price, "qty": qty, "ts": ts,
                 "strategy": f.get("strategy")})

        elif side == "SHORT":
            short_queues.setdefault(coin, deque()).append(
                {"price": price, "qty": qty, "ts": ts,
                 "strategy": f.get("strategy")})

        elif side == "SELL" and buy_queues.get(coin):
            remaining = qty
            total_cost = 0.0; total_qty = 0.0; open_ts = ""; strat = None
            while remaining > 1e-9 and buy_queues[coin]:
                buy = buy_queues[coin][0]
                take = min(remaining, buy["qty"])
                total_cost += buy["price"] * take
                total_qty += take
                open_ts = open_ts or buy["ts"]
                strat = strat or buy.get("strategy")
                buy["qty"] -= take; remaining -= take
                if buy["qty"] <= 1e-9:
                    buy_queues[coin].popleft()
            if total_qty > 1e-9:
                avg_buy = total_cost / total_qty
                pnl_pct = (price - avg_buy) / avg_buy * 100 if avg_buy else 0.0
                closed.append({"coin": coin, "direction": "long",
                                "open_price": round(avg_buy, 6), "close_price": price,
                                "buy_price": round(avg_buy, 6), "sell_price": price,  # compat
                                "pnl_pct": round(pnl_pct, 2), "qty": round(total_qty, 8),
                                "strategy": strat,
                                "buy_ts": open_ts, "sell_ts": ts})

        elif side == "COVER" and short_queues.get(coin):
            remaining = qty
            total_proceeds = 0.0; total_qty = 0.0; open_ts = ""; strat = None
            while remaining > 1e-9 and short_queues[coin]:
                short = short_queues[coin][0]
                take = min(remaining, short["qty"])
                total_proceeds += short["price"] * take
                total_qty += take
                open_ts = open_ts or short["ts"]
                strat = strat or short.get("strategy")
                short["qty"] -= take; remaining -= take
                if short["qty"] <= 1e-9:
                    short_queues[coin].popleft()
            if total_qty > 1e-9:
                avg_short = total_proceeds / total_qty
                pnl_pct = (avg_short - price) / avg_short * 100 if avg_short else 0.0
                closed.append({"coin": coin, "direction": "short",
                                "open_price": round(avg_short, 6), "close_price": price,
                                "buy_price": round(avg_short, 6), "sell_price": price,  # compat
                                "pnl_pct": round(pnl_pct, 2), "qty": round(total_qty, 8),
                                "strategy": strat,
                                "buy_ts": open_ts, "sell_ts": ts})
    return closed


# ---------- analyst accuracy ----------

def _analyst_accuracy(closed_trades, decisions, lookback=30):
    """For each analyst, score how often their verdict predicted the profitable
    direction. 'Correct' = analyst said bullish and trade was profitable, or
    analyst said bearish and trade was a loss (i.e., we avoided a bad entry)."""
    if not closed_trades or not decisions:
        return {}

    # Build a lookup: (coin, approx_ts) -> closed trade P&L
    # Match the decision closest in time before the BUY
    entry_decisions = [d for d in decisions
                       if d.get("action") in ("ENTRY_BUY", "ENTRY_SELL")][-lookback:]

    # Index closed trades by (coin, sell_ts)
    by_coin = {}
    for t in closed_trades:
        by_coin.setdefault(t["coin"], []).append(t)

    scores = {}  # analyst -> {"correct": int, "total": int}

    for dec in entry_decisions:
        coin = dec.get("coin")
        action = dec.get("action")
        dec_ts = dec.get("timestamp", "")
        trades = by_coin.get(coin, [])
        if not trades:
            continue
        # Find the first closed trade whose sell happened after this decision
        matched = next((t for t in sorted(trades, key=lambda x: x["sell_ts"])
                        if t["sell_ts"] >= dec_ts), None)
        if not matched:
            continue

        profitable = matched["pnl_pct"] > 0
        correct_direction = "bullish" if (action == "ENTRY_BUY" and profitable) or \
                                         (action == "ENTRY_SELL" and not profitable) else "bearish"

        for av in dec.get("analysts", []):
            name = av.get("a", av.get("analyst", ""))
            if not name:
                continue
            verdict = av.get("v", av.get("verdict", "neutral"))
            s = scores.setdefault(name, {"correct": 0, "total": 0})
            s["total"] += 1
            if verdict == correct_direction:
                s["correct"] += 1

    return scores


# ---------- regime performance ----------

def _regime_performance(closed_trades, decisions):
    """Win rate per regime from closed trades matched to their entry decisions."""
    regime_stats = {}  # regime -> {"wins": int, "total": int}
    decisions_by_id = {d.get("signal_id"): d for d in decisions}

    entry_decisions = {d.get("signal_id"): d for d in decisions
                       if d.get("action") in ("ENTRY_BUY", "ENTRY_SELL")}
    if not entry_decisions or not closed_trades:
        return {}

    # For each closed trade, find the nearest ENTRY decision for that coin
    by_coin_dec = {}
    for dec in entry_decisions.values():
        by_coin_dec.setdefault(dec.get("coin"), []).append(dec)

    for trade in closed_trades:
        coin = trade["coin"]
        decs = sorted(by_coin_dec.get(coin, []),
                      key=lambda d: d.get("timestamp", ""))
        matched_dec = next((d for d in reversed(decs)
                            if d.get("timestamp", "") <= trade["sell_ts"]), None)
        if not matched_dec:
            continue
        regime = matched_dec.get("regime") or \
                 (matched_dec.get("reasoning", "").split("regime=")[-1].split(" ")[0]
                  if "regime=" in matched_dec.get("reasoning", "") else "unknown")
        rs = regime_stats.setdefault(regime, {"wins": 0, "total": 0})
        rs["total"] += 1
        if trade["pnl_pct"] > 0:
            rs["wins"] += 1

    return regime_stats


# ---------- public interface ----------

def recent_closed_trades(n=50):
    """Closed trades (both long and short) for dashboard consumption."""
    return _match_trades(_load_fills())[-n:]


def overall_stats(closed_trades):
    """Aggregate win rate / realized P&L across the given closed trades."""
    if not closed_trades:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                "avg_pnl_pct": 0.0, "realized_usd": 0.0}
    wins = sum(1 for t in closed_trades if t["pnl_pct"] > 0)
    avg = sum(t["pnl_pct"] for t in closed_trades) / len(closed_trades)
    realized_usd = sum(t["qty"] * t["open_price"] * t["pnl_pct"] / 100
                       for t in closed_trades)
    return {"trades": len(closed_trades), "wins": wins, "losses": len(closed_trades) - wins,
            "win_rate": round(100 * wins / len(closed_trades), 1),
            "avg_pnl_pct": round(avg, 2), "realized_usd": round(realized_usd, 2)}


def coin_summary(coin, closed_trades, n=8):
    """One-line performance summary for a single coin."""
    trades = [t for t in closed_trades if t["coin"] == coin][-n:]
    if not trades:
        return f"{coin}: no closed trades yet"
    wins = sum(1 for t in trades if t["pnl_pct"] > 0)
    avg = sum(t["pnl_pct"] for t in trades) / len(trades)
    recents = " ".join(f"{'+' if t['pnl_pct']>0 else ''}{t['pnl_pct']:.1f}%"
                       for t in trades[-4:])
    streak = 0
    for t in reversed(trades):
        if (t["pnl_pct"] > 0) == (trades[-1]["pnl_pct"] > 0):
            streak += 1
        else:
            break
    streak_word = f"{'win' if trades[-1]['pnl_pct']>0 else 'loss'} streak x{streak}"
    return (f"{coin}: {wins}W/{len(trades)-wins}L  avg {avg:+.1f}%  "
            f"recent [{recents}]  {streak_word}")


def build_context(coin=None, lookback_trades=30):
    """Build a compact performance context string for LLM prompt injection.
    Returns empty string when no history exists yet (first run)."""
    try:
        fills = _load_fills()
        decisions = _load_decisions()
        if not fills and not decisions:
            return ""

        closed = _match_trades(fills)
        analyst_acc = _analyst_accuracy(closed, decisions)
        regime_perf = _regime_performance(closed, decisions)

        lines = []

        # --- coin performance ---
        if closed:
            lines.append("=== Recent Trade Outcomes ===")
            coins = config.TRACKED_COINS if not coin else [coin]
            for c in coins:
                lines.append("  " + coin_summary(c, closed, n=lookback_trades))

        # --- analyst accuracy ---
        if analyst_acc:
            lines.append("=== Analyst Accuracy (recent closed trades) ===")
            for name, s in sorted(analyst_acc.items(),
                                  key=lambda x: -x[1]["correct"] / max(x[1]["total"], 1)):
                pct = 100 * s["correct"] / s["total"] if s["total"] else 0
                lines.append(f"  {name}: {pct:.0f}% correct ({s['correct']}/{s['total']})")

        # --- regime performance ---
        if regime_perf:
            lines.append("=== Regime Win Rate ===")
            for regime, rs in regime_perf.items():
                pct = 100 * rs["wins"] / rs["total"] if rs["total"] else 0
                lines.append(f"  {regime}: {pct:.0f}% ({rs['wins']}/{rs['total']} trades)")

        return "\n".join(lines) if lines else ""

    except Exception as e:
        log.debug("performance.build_context error (non-fatal): %s", e)
        return ""


def coin_context(coin, lookback_trades=10):
    """Coin-specific performance summary only (shorter, for sentiment prompt)."""
    try:
        fills = _load_fills()
        if not fills:
            return ""
        closed = _match_trades(fills)
        coin_trades = [t for t in closed if t["coin"] == coin][-lookback_trades:]
        if not coin_trades:
            return ""
        return "=== Your recent " + coin + " trades ===\n  " + \
               coin_summary(coin, closed, n=lookback_trades)
    except Exception:
        return ""
