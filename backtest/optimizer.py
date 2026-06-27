"""
MiniSim parameter optimizer — sweeps SL/TP combinations to find profitable exits.

The expensive part (signal computation) runs once per coin. Every parameter
combination then only re-simulates exits from the same precomputed entry list,
making a 72-point grid search feasible on a Pi 5.

Grid covers:
  • SL:   1.5 / 2.0 / 2.5 / 3.0 %
  • TP1:  2.0 / 2.5 / 3.0 / 4.0 / 5.0 / 6.0 %
  • Exit: all-at-TP1  |  50/50 at TP1+TP2  |  33/33/34 at TP1/TP2/TP3

Usage:
  python -m backtest.optimizer               # 90 days, all coins
  python -m backtest.optimizer --days 60
  python -m backtest.optimizer --top 15      # show top 15 combos
"""
from __future__ import annotations
import argparse, json, os, sys, time
from dataclasses import dataclass, field
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from backtest.runner import (
    _fetch_candles_coin, _signal, _atr_stop, _Pos, _stats,
)
from analysts import indicators as ind


# ── parameter grid ────────────────────────────────────────────────────────────
def _build_grid(fee_pct: float) -> list[dict]:
    grid = []
    SLS  = [1.5, 2.0, 2.5, 3.0]
    TP1S = [2.0, 2.5, 3.0, 4.0, 5.0, 6.0]

    for sl in SLS:
        for tp1 in TP1S:
            base = dict(sl=sl, tp1=tp1, trail=max(sl * 0.75, 1.0),
                        trail_min=tp1 * 0.6, fee_pct=fee_pct,
                        max_hold_candles=192)

            # A: exit 100% at TP1, no further targets
            grid.append({**base,
                "label": f"SL{sl:.1f}_TP{tp1:.1f}_ALL",
                "frac1": 1.0, "frac2": 0.0, "frac3": 0.0,
                "tp2": 0.0,   "tp3": 0.0,
                "trail_min": 999.0})   # no trail when exiting all at TP1

            # B: 50% at TP1, 50% at TP2, then trail the rest
            grid.append({**base,
                "label": f"SL{sl:.1f}_TP{tp1:.1f}_50/50",
                "frac1": 0.5, "frac2": 0.5, "frac3": 0.0,
                "tp2": tp1 * 2, "tp3": 0.0})

            # C: 33/33/34 ladder (current approach, varied params)
            grid.append({**base,
                "label": f"SL{sl:.1f}_TP{tp1:.1f}_LADDER",
                "frac1": 0.33, "frac2": 0.33, "frac3": 0.34,
                "tp2": tp1 * 2, "tp3": tp1 * 3})

    return grid


# ── precompute entries ────────────────────────────────────────────────────────
SIGNAL_STEP = 4
WINDOW      = 300
CONF_MIN    = 0.68


def _precompute_entries(coin: str, candles: list[dict]) -> list[tuple]:
    """
    Run the signal pipeline on every SIGNAL_STEP candle.
    Returns list of (candle_idx, direction, raw_atr_pct).
    Expensive — call once per coin.
    """
    entries = []
    for i in range(WINDOW, len(candles), SIGNAL_STEP):
        window    = candles[i - WINDOW: i]
        direction, _ = _signal(coin, window, CONF_MIN,
                               use_gate=True, use_tod=True)
        if direction == "neutral":
            continue
        h = [c["high"]  for c in window[-50:]]
        l = [c["low"]   for c in window[-50:]]
        c_ = [c["close"] for c in window[-50:]]
        atr_v   = ind.atr(h, l, c_, 14)
        raw_atr = atr_v / candles[i]["close"] * 100 if (atr_v and candles[i]["close"]) else 0.0
        entries.append((i, direction, raw_atr))
    return entries


# ── simulate exits for one param combo ───────────────────────────────────────
def _simulate(coin: str, candles: list[dict],
              entries: list[tuple], p: dict) -> list[dict]:
    """
    Replay `entries` against `candles` using exit params from `p`.
    Only the cheap exit arithmetic runs here — signals are already precomputed.
    """
    trades: list[dict] = []
    pos: Optional[_Pos] = None
    entry_set = {idx: (d, r) for idx, d, r in entries}
    entry_indices = sorted(entry_set.keys())
    ei = 0   # pointer into entry_indices

    for i in range(WINDOW, len(candles)):
        cur = candles[i]

        if pos is not None:
            result = pos.step(cur, i, p["fee_pct"])
            if result:
                trades.append(result)
                pos = None
            continue   # never enter same candle we closed on

        # Advance entry pointer to current candle
        while ei < len(entry_indices) and entry_indices[ei] < i:
            ei += 1
        if ei >= len(entry_indices) or entry_indices[ei] != i:
            continue

        direction, raw_atr = entry_set[i]
        sl_pct = max(p["sl"], round(1.5 * raw_atr, 3)) if raw_atr else p["sl"]
        pos = _Pos(
            coin=coin, side="LONG" if direction == "bullish" else "SHORT",
            entry_price=cur["close"], entry_idx=i, entry_time=cur["timestamp"],
            sl_pct=sl_pct,
            tp1_pct=p["tp1"],  tp2_pct=p.get("tp2", 0.0), tp3_pct=p.get("tp3", 0.0),
            frac1=p["frac1"],  frac2=p.get("frac2", 0.0),  frac3=p.get("frac3", 0.0),
            trail_pct=p["trail"], trail_min=p["trail_min"],
            max_hold_c=p["max_hold_candles"],
        )
        ei += 1   # consumed this entry

    if pos is not None:
        last = candles[-1]
        pos.exits.append((last["close"], pos.remaining))
        r = pos._close("end_of_data", last["timestamp"], len(candles)-1, p["fee_pct"])
        if r:
            r["exit_reason"] = "open_at_end"
            trades.append(r)

    return trades


# ── main ──────────────────────────────────────────────────────────────────────
def run(days: int = 90, coins: list[str] | None = None,
        fee_pct: float = 0.001, top_n: int = 10):
    from config import config as cfg
    coins = coins or cfg.TRACKED_COINS

    # 1. Fetch candles
    print(f"\nFetching {days}d of 15m candles for {len(coins)} coins…")
    candle_cache: dict[str, list] = {}
    for coin in coins:
        print(f"  {coin}… ", end="", flush=True)
        c = _fetch_candles_coin(coin, days)
        candle_cache[coin] = c
        print(f"{len(c)} candles")

    # 2. Precompute entry signals (expensive — once per coin)
    print("\nPrecomputing entry signals…")
    entry_cache: dict[str, list] = {}
    for coin in coins:
        t0 = time.time()
        e = _precompute_entries(coin, candle_cache[coin])
        entry_cache[coin] = e
        print(f"  {coin}: {len(e)} potential entries ({time.time()-t0:.1f}s)")

    total_entries = sum(len(v) for v in entry_cache.values())
    print(f"\nTotal potential entries across all coins: {total_entries}")

    # 3. Grid search — only exit simulation runs per combo
    grid   = _build_grid(fee_pct)
    results = []
    print(f"\nRunning {len(grid)}-point grid search…")
    t_start = time.time()

    for p in grid:
        all_trades: list[dict] = []
        for coin in coins:
            trades = _simulate(coin, candle_cache[coin], entry_cache[coin], p)
            all_trades.extend(trades)
        s = _stats(all_trades)
        s["label"]       = p["label"]
        s["sl"]          = p["sl"]
        s["tp1"]         = p["tp1"]
        s["exit_style"]  = p["label"].split("_")[-1]
        results.append(s)

    elapsed = time.time() - t_start
    print(f"Grid search done in {elapsed:.1f}s")

    # 4. Sort and display
    results.sort(key=lambda x: x.get("expectancy", -99), reverse=True)

    print(f"\n{'='*78}")
    print(f"  TOP {top_n} PARAMETER COMBINATIONS  (sorted by expectancy)")
    print(f"{'='*78}")
    print(f"  {'Label':<28} {'Trades':>6} {'WR':>5} {'AvgW':>6} {'AvgL':>6}"
          f" {'R:R':>5} {'EV':>7} {'P&L':>8}")
    print(f"  {'-'*74}")
    for s in results[:top_n]:
        if s.get("trades", 0) == 0:
            continue
        marker = " ◄" if results.index(s) == 0 else ""
        print(f"  {s['label']:<28} {s['trades']:>6} {s['win_rate']:>4.0f}%"
              f" {s['avg_win_pct']:>+5.2f}% {s['avg_loss_pct']:>+5.2f}%"
              f" {s['rr_ratio']:>5.2f} {s['expectancy']:>+6.3f}%"
              f" ${s['total_pnl_usd']:>+7.2f}{marker}")

    print(f"{'='*78}")

    # Bottom 3 (worst)
    worst = [r for r in results if r.get("trades", 0) > 0][-3:]
    print(f"\n  WORST 3:")
    print(f"  {'-'*74}")
    for s in worst:
        print(f"  {s['label']:<28} {s['trades']:>6} {s['win_rate']:>4.0f}%"
              f" {s['expectancy']:>+6.3f}%  ${s['total_pnl_usd']:>+7.2f}")

    # Positive expectancy combos
    pos_ev = [r for r in results if r.get("expectancy", -99) > 0]
    print(f"\n  {len(pos_ev)} of {len(results)} combinations have positive expectancy")

    # Best combo detail
    best = results[0]
    print(f"\n  BEST COMBO DETAIL: {best['label']}")
    print(f"  Trades: {best['trades']}  ({best['wins']}W / {best['losses']}L)")
    print(f"  Win rate: {best['win_rate']}%")
    print(f"  Avg win: +{best['avg_win_pct']:.3f}%   Avg loss: {best['avg_loss_pct']:.3f}%")
    print(f"  R:R: {best['rr_ratio']:.2f}   Expectancy: {best['expectancy']:+.3f}%/trade")
    print(f"  Total P&L: ${best['total_pnl_usd']:+.2f}   Max drawdown: ${best['max_drawdown_usd']:.2f}")
    print(f"  Exit reasons: {best['exit_reasons']}")
    print()

    # Save
    out = os.path.join(os.path.dirname(_HERE), "data", "backtest_results", "grid_search.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Full grid saved → {out}\n")

    return results


def main():
    ap = argparse.ArgumentParser(description="MiniSim parameter optimizer")
    ap.add_argument("--days",  type=int,   default=90)
    ap.add_argument("--coins", nargs="+",  default=None)
    ap.add_argument("--fee",   type=float, default=0.001)
    ap.add_argument("--top",   type=int,   default=10)
    args = ap.parse_args()
    run(days=args.days, coins=args.coins, fee_pct=args.fee, top_n=args.top)


if __name__ == "__main__":
    main()
