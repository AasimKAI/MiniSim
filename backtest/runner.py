"""
MiniSim backtester — arithmetic-only (no LLM), 15-minute candles.

Fetches up to N days of 15m OHLCV data from Binance for each tracked coin,
slides the same 300-candle analysis window the live system uses, and applies
the same technical + volume analysts and decision logic.

The LLM CEO is skipped for speed; the blended arithmetic score drives entries
directly. All production filters apply:
  • confidence threshold (default 0.68, pass --old-settings for 0.65)
  • 2-of-3 confirmation gate  (--old-settings disables)
  • time-of-day gate 00:00-03:59 UTC  (--old-settings disables)
  • ATR-based dynamic stop loss
  • full TP ladder (TP1 5% / TP2 10% / TP3 15%, fractions 33/33/34%)
  • trailing stop 3% after 3% profit
  • max hold 48 h

Macro vetoes are skipped (no historical macro data available).

Usage:
  python -m backtest.runner                        # 90 days, all coins
  python -m backtest.runner --days 180             # 6 months
  python -m backtest.runner --coins BTC ETH SOL   # specific coins
  python -m backtest.runner --fee 0.001            # 0.1% per trade
  python -m backtest.runner --compare              # new vs old settings
"""
from __future__ import annotations
import argparse, datetime, hashlib, json, math, os, sys, time
from dataclasses import dataclass, field
from typing import Optional

# ── paths ────────────────────────────────────────────────────────────────────
_HERE     = os.path.dirname(os.path.abspath(__file__))
_ROOT     = os.path.dirname(_HERE)
_OUTDIR   = os.path.join(_ROOT, "data", "backtest_results")
_CACHE    = os.path.join(_ROOT, ".bt_cache", "candles")
sys.path.insert(0, _ROOT)
os.makedirs(_CACHE, exist_ok=True)

from analysts import technical_analyst as tech
from analysts.other_analysts import volume_analyst
from analysts import indicators as ind
from decision.engine import blend, ANALYST_WEIGHTS

os.makedirs(_OUTDIR, exist_ok=True)


# ── candle fetching ───────────────────────────────────────────────────────────
def _fetch_candles_coin(coin: str, days: int, interval: str = "15m") -> list[dict]:
    """Fetch up to `days` of historical candles from Binance (paginated, disk-cached by day)."""
    import httpx
    # Cache key includes coin, days, interval, and UTC day — stale after midnight
    day_str  = datetime.datetime.utcnow().strftime("%Y%m%d")
    key      = hashlib.md5(f"{coin}|{days}|{interval}|{day_str}".encode()).hexdigest()[:12]
    cache_f  = os.path.join(_CACHE, f"{key}_{coin}.json")
    if os.path.exists(cache_f):
        with open(cache_f) as f:
            return json.load(f)

    symbol   = f"{coin}USDT"
    end_ms   = int(time.time() * 1000)
    start_ms = end_ms - days * 86_400_000
    candles  = []
    cur      = start_ms
    while cur < end_ms:
        try:
            r = httpx.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": symbol, "interval": interval,
                        "startTime": cur, "limit": 1000},
                timeout=20.0,
            )
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            for k in rows:
                candles.append({
                    "timestamp": datetime.datetime.fromtimestamp(
                        k[0] / 1000, tz=datetime.timezone.utc).isoformat(),
                    "open":   float(k[1]),
                    "high":   float(k[2]),
                    "low":    float(k[3]),
                    "close":  float(k[4]),
                    "volume": float(k[5]),
                })
            cur = rows[-1][6] + 1   # closeTime of last row + 1ms
        except Exception as e:
            print(f"  WARNING: fetch error for {coin}: {e}")
            break

    if candles:
        with open(cache_f, "w") as f:
            json.dump(candles, f)
    return candles


# ── position simulation ───────────────────────────────────────────────────────
@dataclass
class _Pos:
    coin:        str
    side:        str           # 'LONG' | 'SHORT'
    entry_price: float
    entry_idx:   int
    entry_time:  str
    sl_pct:      float = 2.0
    tp1_pct:     float = 5.0
    tp2_pct:     float = 10.0
    tp3_pct:     float = 15.0
    frac1:       float = 0.33
    frac2:       float = 0.33
    frac3:       float = 0.34
    trail_pct:   float = 3.0
    trail_min:   float = 3.0
    max_hold_c:  int   = 192   # 48h × 4 candles/h
    peak_pnl:    float = 0.0
    targets_done: set  = field(default_factory=set)
    exits:        list = field(default_factory=list)  # (price, fraction)
    remaining:    float = 1.0

    def _pnl(self, price: float) -> float:
        if self.side == "LONG":
            return (price - self.entry_price) / self.entry_price * 100
        return (self.entry_price - price) / self.entry_price * 100

    def step(self, candle: dict, idx: int, fee_pct: float) -> Optional[dict]:
        """
        Evaluate one candle. Returns a closed-trade dict when the position
        is fully closed, else None (may have recorded partial exits internally).
        """
        hi = candle["high"]; lo = candle["low"]; ts = candle["timestamp"]

        # intra-candle price for LONG: worst move is low, best is high
        # for SHORT: worst move is high, best is low
        worst_px  = lo  if self.side == "LONG" else hi
        best_px   = hi  if self.side == "LONG" else lo
        close_px  = candle["close"]

        worst_pnl = self._pnl(worst_px)
        best_pnl  = self._pnl(best_px)
        self.peak_pnl = max(self.peak_pnl, best_pnl)

        # stop loss (use worst intra-candle)
        if worst_pnl <= -self.sl_pct:
            stop_px = self.entry_price * (1 - self.sl_pct / 100) if self.side == "LONG" \
                      else self.entry_price * (1 + self.sl_pct / 100)
            self.exits.append((stop_px, self.remaining))
            return self._close("stop_loss", ts, idx, fee_pct)

        # max hold
        if idx - self.entry_idx >= self.max_hold_c:
            self.exits.append((close_px, self.remaining))
            return self._close("max_hold", ts, idx, fee_pct)

        # TP ladder (use best intra-candle to check if hit)
        tp_ladder = [
            (1, self.tp1_pct, self.frac1),
            (2, self.tp2_pct, self.frac2),
            (3, self.tp3_pct, self.frac3),
        ]
        for lvl, pct, frac in tp_ladder:
            if pct > 0 and lvl not in self.targets_done and best_pnl >= pct:
                tp_px = self.entry_price * (1 + pct / 100) if self.side == "LONG" \
                        else self.entry_price * (1 - pct / 100)
                sold  = min(frac, self.remaining)
                self.exits.append((tp_px, sold))
                self.remaining -= sold
                self.targets_done.add(lvl)
                if self.remaining <= 0.01:
                    return self._close(f"tp{lvl}_full", ts, idx, fee_pct)

        # trailing stop
        if self.peak_pnl >= self.trail_min and (self.peak_pnl - self._pnl(close_px)) >= self.trail_pct:
            self.exits.append((close_px, self.remaining))
            return self._close("trailing_stop", ts, idx, fee_pct)

        return None

    def _close(self, reason: str, ts: str, idx: int, fee_pct: float) -> dict:
        if not self.exits:
            return {}
        total_val  = sum(px * fr for px, fr in self.exits)
        total_frac = sum(fr for _, fr in self.exits)
        avg_exit   = total_val / total_frac if total_frac else self.entry_price
        pnl_pct    = self._pnl(avg_exit) - fee_pct * 200   # entry + exit fee (both sides)
        pnl_usd    = 100 * pnl_pct / 100   # normalised to $100 position
        return {
            "coin":         self.coin,
            "side":         self.side,
            "entry_time":   self.entry_time,
            "exit_time":    ts,
            "entry_price":  round(self.entry_price, 6),
            "exit_price":   round(avg_exit, 6),
            "pnl_pct":      round(pnl_pct, 4),
            "pnl_usd":      round(pnl_usd, 4),
            "exit_reason":  reason,
            "hold_candles": idx - self.entry_idx,
            "hold_hours":   round((idx - self.entry_idx) * 0.25, 1),
        }


# ── signal logic ──────────────────────────────────────────────────────────────
def _signal(coin: str, window: list[dict], conf_min: float,
            use_gate: bool, use_tod: bool) -> tuple[str, float]:
    """
    Returns (direction, confidence) where direction is 'bullish'|'bearish'|'neutral'.
    """
    if len(window) < 60:
        return "neutral", 0.0

    tv = tech.analyze(coin, window)
    vv = volume_analyst(coin, window)

    # Blended arithmetic score (only 2 analysts — normalise weights)
    _SIGN = {"bullish": 1, "bearish": -1, "neutral": 0}
    w_t = ANALYST_WEIGHTS.get("technical", 1.4)
    w_v = ANALYST_WEIGHTS.get("volume", 0.7)
    score = (w_t * _SIGN[tv["verdict"]] * tv["confidence"]
           + w_v * _SIGN[vv["verdict"]] * vv["confidence"]) / (w_t + w_v)
    direction  = "bullish" if score > 0.25 else "bearish" if score < -0.25 else "neutral"
    arith_conf = min(1.0, abs(score))

    if direction == "neutral" or arith_conf < conf_min:
        return "neutral", arith_conf

    # Time-of-day gate
    if use_tod:
        try:
            ts = window[-1]["timestamp"]
            utc_h = datetime.datetime.fromisoformat(ts).hour
            if 0 <= utc_h < 4:
                return "neutral", arith_conf
        except Exception:
            pass

    # Confirmation gate: technical must agree (conf>0.45) AND volume must agree
    if use_gate:
        tech_ok = tv["verdict"] == direction and tv["confidence"] > 0.45
        vol_ok  = vv["verdict"] == direction
        if not (tech_ok and vol_ok):
            return "neutral", arith_conf

    # HTF alignment: block entry when higher timeframe directly opposes LTF signal
    if tv.get("metrics", {}).get("htf_conflict"):
        return "neutral", arith_conf

    return direction, arith_conf


# ── ATR-based stop ────────────────────────────────────────────────────────────
def _atr_stop(window: list[dict], base_sl: float = 2.0) -> float:
    h = [c["high"]  for c in window[-50:]]
    l = [c["low"]   for c in window[-50:]]
    c = [c["close"] for c in window[-50:]]
    a = ind.atr(h, l, c, 14)
    if a and c[-1] > 0:
        atr_pct = a / c[-1] * 100
        return max(base_sl, round(1.5 * atr_pct, 3))
    return base_sl


# ── per-coin backtest ─────────────────────────────────────────────────────────
def _backtest_coin(coin: str, candles: list[dict], cfg: dict) -> list[dict]:
    conf_min  = cfg["conf_min"]
    use_gate  = cfg["use_gate"]
    use_tod   = cfg["use_tod"]
    fee_pct   = cfg["fee_pct"]
    base_sl   = cfg["sl_pct"]
    tp1, tp2, tp3 = cfg["tp1"], cfg["tp2"], cfg["tp3"]
    trail     = cfg["trail"]
    trail_min = cfg["trail_min"]
    max_hold_c = cfg["max_hold_candles"]

    WINDOW = 300
    # Signal step: only evaluate entry every 4 candles (1 hour) to avoid
    # recomputing rsi_divergence O(n²) on every single 15-min bar.
    # Exit is still evaluated every candle for accurate stop/TP simulation.
    SIGNAL_STEP = 4
    trades: list[dict] = []
    pos: Optional[_Pos] = None

    for i in range(WINDOW, len(candles)):
        cur = candles[i]

        # 1. Exit check every candle (accurate intra-candle stop/TP)
        if pos is not None:
            result = pos.step(cur, i, fee_pct)
            if result:
                trades.append(result)
                pos = None
            continue   # never enter on the same candle we just closed

        # 2. Entry check only every SIGNAL_STEP candles
        if (i - WINDOW) % SIGNAL_STEP != 0:
            continue

        window    = candles[i - WINDOW: i]
        direction, conf = _signal(coin, window, conf_min, use_gate, use_tod)
        if direction == "neutral":
            continue

        sl_pct = _atr_stop(window, base_sl)
        pos = _Pos(
            coin=coin, side="LONG" if direction == "bullish" else "SHORT",
            entry_price=cur["close"], entry_idx=i, entry_time=cur["timestamp"],
            sl_pct=sl_pct, tp1_pct=tp1, tp2_pct=tp2, tp3_pct=tp3,
            frac1=0.33, frac2=0.33, frac3=0.34,
            trail_pct=trail, trail_min=trail_min, max_hold_c=max_hold_c,
        )

    # Force-close any open position at last candle
    if pos is not None:
        last = candles[-1]
        pos.exits.append((last["close"], pos.remaining))
        result = pos._close("end_of_data", last["timestamp"], len(candles) - 1, fee_pct)
        if result:
            result["exit_reason"] = "open_at_end"
            trades.append(result)

    return trades


# ── reporting ─────────────────────────────────────────────────────────────────
def _stats(trades: list[dict], label: str = "") -> dict:
    if not trades:
        return {"label": label, "trades": 0}

    wins   = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    pnls   = [t["pnl_pct"] for t in trades]
    pnl_usd = [t["pnl_usd"] for t in trades]

    win_rate   = len(wins) / len(trades) * 100
    avg_win    = sum(t["pnl_pct"] for t in wins)  / len(wins)   if wins   else 0
    avg_loss   = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
    rr         = abs(avg_win / avg_loss) if avg_loss else float("inf")
    total_pnl  = sum(pnl_usd)
    expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)

    # Max drawdown on equity curve
    equity = [0.0]
    for p in pnl_usd:
        equity.append(equity[-1] + p)
    peak = equity[0]; max_dd = 0.0
    for e in equity:
        peak = max(peak, e)
        max_dd = min(max_dd, e - peak)

    # Exit reason breakdown
    reasons: dict = {}
    for t in trades:
        r = t["exit_reason"]; reasons[r] = reasons.get(r, 0) + 1

    # Per-coin
    by_coin: dict = {}
    for t in trades:
        c = t["coin"]
        by_coin.setdefault(c, {"w": 0, "l": 0, "pnl": 0.0})
        if t["pnl_pct"] > 0: by_coin[c]["w"] += 1
        else:                  by_coin[c]["l"] += 1
        by_coin[c]["pnl"] += t["pnl_usd"]

    return {
        "label":       label,
        "trades":      len(trades),
        "wins":        len(wins),
        "losses":      len(losses),
        "win_rate":    round(win_rate, 1),
        "avg_win_pct": round(avg_win, 3),
        "avg_loss_pct":round(avg_loss, 3),
        "rr_ratio":    round(rr, 2),
        "expectancy":  round(expectancy, 3),
        "total_pnl_usd": round(total_pnl, 2),
        "max_drawdown_usd": round(max_dd, 2),
        "exit_reasons": reasons,
        "by_coin": {
            c: {"trades": d["w"]+d["l"], "win_rate": round(d["w"]/(d["w"]+d["l"])*100,1),
                "pnl_usd": round(d["pnl"], 2)}
            for c, d in sorted(by_coin.items(), key=lambda x: -(x[1]["w"]+x[1]["l"]))
        },
    }


def _print_report(s: dict):
    lbl = f" [{s['label']}]" if s.get("label") else ""
    print(f"\n{'='*58}")
    print(f"  BACKTEST RESULTS{lbl}")
    print(f"{'='*58}")
    if s.get("trades", 0) == 0:
        print("  No trades generated."); return
    print(f"  Trades:       {s['trades']}  ({s['wins']}W / {s['losses']}L)")
    print(f"  Win rate:     {s['win_rate']}%")
    print(f"  Avg win:      +{s['avg_win_pct']:.2f}%")
    print(f"  Avg loss:     {s['avg_loss_pct']:.2f}%")
    print(f"  R:R ratio:    {s['rr_ratio']:.2f}")
    print(f"  Expectancy:   {s['expectancy']:+.3f}% per trade")
    print(f"  Total P&L:    ${s['total_pnl_usd']:+.2f}  (@ $100/trade)")
    print(f"  Max drawdown: ${s['max_drawdown_usd']:.2f}")
    print(f"\n  Exit reasons:")
    for reason, cnt in sorted(s["exit_reasons"].items(), key=lambda x: -x[1]):
        print(f"    {reason:<20s} {cnt:>4d}")
    print(f"\n  Per-coin:")
    print(f"    {'Coin':<7} {'Trades':>6} {'WR':>6} {'P&L':>9}")
    print(f"    {'-'*32}")
    for coin, d in s["by_coin"].items():
        print(f"    {coin:<7} {d['trades']:>6} {d['win_rate']:>5.0f}% ${d['pnl_usd']:>+7.2f}")
    print(f"{'='*58}\n")


# ── main ──────────────────────────────────────────────────────────────────────
def run(days: int = 90, coins: list[str] | None = None, fee_pct: float = 0.001,
        compare: bool = False):
    from config import config as cfg

    coins = coins or cfg.TRACKED_COINS

    # Settings profiles
    NEW = {
        "conf_min": 0.68, "use_gate": True, "use_tod": True,
        "sl_pct": cfg.STOP_LOSS_PERCENT,
        "tp1": cfg.TAKE_PROFIT_TARGET_1_PERCENT,
        "tp2": cfg.TAKE_PROFIT_TARGET_2_PERCENT,
        "tp3": cfg.TAKE_PROFIT_TARGET_3_PERCENT,
        "trail": cfg.TRAILING_STOP_PERCENT, "trail_min": 3.0,
        "max_hold_candles": cfg.MAX_HOLD_TIME_HOURS * 4,
        "fee_pct": fee_pct,
    }
    OLD = {**NEW, "conf_min": 0.65, "use_gate": False, "use_tod": False}

    profiles = [("new", NEW), ("old", OLD)] if compare else [("new", NEW)]

    all_results = {}
    candle_cache: dict[str, list] = {}

    print(f"\nFetching {days}d of 15m candles for {len(coins)} coins…")
    for coin in coins:
        print(f"  {coin}… ", end="", flush=True)
        c = _fetch_candles_coin(coin, days)
        candle_cache[coin] = c
        print(f"{len(c)} candles")

    for label, profile in profiles:
        print(f"\nRunning backtest [{label} settings]…")
        all_trades: list[dict] = []
        for coin in coins:
            candles = candle_cache[coin]
            if len(candles) < 320:
                print(f"  {coin}: insufficient data, skipping")
                continue
            trades = _backtest_coin(coin, candles, profile)
            print(f"  {coin}: {len(trades)} trades")
            all_trades.extend(trades)

        s = _stats(all_trades, label=label)
        _print_report(s)
        all_results[label] = s

        # Save
        out_path = os.path.join(_OUTDIR, f"trades_{label}.json")
        with open(out_path, "w") as f:
            json.dump({"settings": profile, "stats": s, "trades": all_trades},
                      f, indent=2)
        print(f"  Saved → {out_path}")

    if compare and "new" in all_results and "old" in all_results:
        n, o = all_results["new"], all_results["old"]
        print(f"\n{'─'*40}")
        print("  COMPARISON: new vs old settings")
        print(f"{'─'*40}")
        def _diff(key, fmt="{:.1f}"):
            nv = n.get(key, 0); ov = o.get(key, 0)
            arrow = "↑" if nv > ov else "↓" if nv < ov else "="
            return f"{fmt.format(ov)} → {fmt.format(nv)}  {arrow}"
        print(f"  Trades:    {o['trades']} → {n['trades']}")
        print(f"  Win rate:  {_diff('win_rate')}%")
        print(f"  R:R:       {_diff('rr_ratio', '{:.2f}')}")
        print(f"  Expectancy:{_diff('expectancy', '{:+.3f}')}%")
        print(f"  Total P&L: ${o['total_pnl_usd']:+.2f} → ${n['total_pnl_usd']:+.2f}")
        print(f"{'─'*40}\n")

    return all_results


def main():
    ap = argparse.ArgumentParser(description="MiniSim backtester")
    ap.add_argument("--days",    type=int,   default=90,   help="Days of history (default 90)")
    ap.add_argument("--coins",   nargs="+",  default=None, help="Coins to test (default: all)")
    ap.add_argument("--fee",     type=float, default=0.001,help="Fee per trade side (default 0.001)")
    ap.add_argument("--compare", action="store_true",      help="Also run old settings for comparison")
    args = ap.parse_args()
    run(days=args.days, coins=args.coins, fee_pct=args.fee, compare=args.compare)


if __name__ == "__main__":
    main()
