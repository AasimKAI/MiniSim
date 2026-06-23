#!/usr/bin/env python3
"""
MiniSim v5 — historical backtest with bear / bull / ranging period comparison.

Decision pipeline: technical + volume + on_chain (arithmetic only, no LLM) →
rule-based CEO → SL/TP/trail exit simulation.

Usage
─────
  python backtest.py                              # last 30 days
  python backtest.py --days 7                     # last 7 days
  python backtest.py --period bear_2022_q2        # named period
  python backtest.py --from 2022-06-01 --to 2022-07-01
  python backtest.py --compare                    # all presets side by side
  python backtest.py --compare --coins BTC,ETH,SOL
  python backtest.py --period bear_2022_q2 --no-cache
"""
import sys, os, time, argparse, json, hashlib, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx
from config import config
from analysts import technical_analyst as tech
from analysts.other_analysts import volume_analyst, on_chain_analyst
from analysts import regime_detector
from decision.engine import blend, regime_allows

# ── Trade parameters (mirror live config) ──────────────────────────────────────
WARMUP     = 200
STRIDE     = 4            # check every 4 × 15m = 1 h
POS_USD    = 100.0
MAX_EXPO   = 500.0
SL_PCT     = 0.02
TP1_PCT    = 0.05;  TP1_FRAC = 0.33
TP2_PCT    = 0.10;  TP2_FRAC = 0.33
TP3_PCT    = 0.15;  TP3_FRAC = 0.34
TRAIL_PCT  = 0.03
MAX_HOLD_C = 48 * 4
CONF_MIN   = 0.45

ALL_COINS = config.TRACKED_COINS
_BINANCE_SYMBOLS = {
    "BTC": "BTCUSDT",  "ETH": "ETHUSDT",  "XRP": "XRPUSDT",
    "ADA": "ADAUSDT",  "SOL": "SOLUSDT",  "BNB": "BNBUSDT",
    "DOGE":"DOGEUSDT", "AVAX":"AVAXUSDT", "DOT": "DOTUSDT",
    "LINK":"LINKUSDT", "LTC": "LTCUSDT",  "NEAR":"NEARUSDT",
    "UNI": "UNIUSDT",  "ARB": "ARBUSDT",  "ATOM":"ATOMUSDT",
}

# ── Named historical periods ───────────────────────────────────────────────────
def _ms(date_str):
    """'2022-06-01' → Unix ms."""
    return int(datetime.datetime.strptime(date_str, "%Y-%m-%d")
               .replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)

PERIODS = {
    # ── Bear markets ──────────────────────────────────────────────────────────
    "bear_2022_q1": {
        "label": "Bear 2022 Q1 — rate-hike panic (Jan–Mar 2022)",
        "start": "2022-01-15", "end": "2022-03-15", "type": "bear",
        "note":  "BTC 43k → 37k, high macro fear, trending down",
    },
    "bear_2022_q2": {
        "label": "Bear 2022 Q2 — Luna collapse (Apr–Jun 2022)",
        "start": "2022-04-01", "end": "2022-06-15", "type": "bear",
        "note":  "BTC 46k → 22k, UST/Luna implosion",
    },
    "bear_2022_crash": {
        "label": "Bear 2022 worst crash (Jun–Jul 2022)",
        "start": "2022-06-01", "end": "2022-07-15", "type": "bear",
        "note":  "BTC 30k → 17k, Celsius/3AC, deepest drawdown",
    },
    "bear_ftx": {
        "label": "FTX collapse (Nov 2022)",
        "start": "2022-11-01", "end": "2022-11-30", "type": "bear",
        "note":  "BTC 20k → 15k in 2 weeks, contagion",
    },
    "bear_2024_q3": {
        "label": "Correction 2024 Q3 (Jul–Sep 2024)",
        "start": "2024-07-01", "end": "2024-09-01", "type": "bear",
        "note":  "BTC 68k → 56k, post-ETF cooldown",
    },
    # ── Bull markets ──────────────────────────────────────────────────────────
    "bull_2023_q1": {
        "label": "Bull recovery 2023 Q1 (Jan–Mar 2023)",
        "start": "2023-01-01", "end": "2023-03-31", "type": "bull",
        "note":  "BTC 16k → 28k, relief rally after FTX",
    },
    "bull_2024_q1": {
        "label": "Bull 2024 Q1 — ATH run (Jan–Mar 2024)",
        "start": "2024-01-01", "end": "2024-03-31", "type": "bull",
        "note":  "BTC 42k → 71k, ETF approval euphoria",
    },
    # ── Ranging / choppy ─────────────────────────────────────────────────────
    "range_2023_q3": {
        "label": "Ranging 2023 Q3 (Jul–Sep 2023)",
        "start": "2023-07-01", "end": "2023-09-30", "type": "range",
        "note":  "BTC 26k–30k, choppy, low volatility",
    },
    "range_2022_h2_mid": {
        "label": "Dead-cat bounce Oct 2022",
        "start": "2022-10-01", "end": "2022-10-31", "type": "range",
        "note":  "BTC 18k–21k sideways before FTX",
    },
}

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".bt_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


# ── Data fetching + cache ──────────────────────────────────────────────────────
def _cache_key(coin, start_ms, end_ms):
    key = f"{coin}_{start_ms}_{end_ms}"
    return os.path.join(CACHE_DIR, hashlib.md5(key.encode()).hexdigest()[:12] + f"_{coin}.json")

def fetch_candles(coin, start_ms, end_ms, use_cache=True):
    path = _cache_key(coin, start_ms, end_ms)
    if use_cache and os.path.exists(path):
        with open(path) as f:
            return json.load(f)

    symbol = _BINANCE_SYMBOLS[coin]
    step_ms = 15 * 60 * 1000
    all_raw = []
    cursor = start_ms
    while cursor < end_ms:
        r = httpx.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": "15m",
                    "startTime": cursor, "endTime": end_ms, "limit": 1000},
            timeout=20)
        r.raise_for_status()
        raw = r.json()
        if not raw:
            break
        all_raw.extend(raw)
        cursor = int(raw[-1][0]) + step_ms
        if len(raw) < 1000:
            break
        time.sleep(0.2)

    candles = [{"t": int(k[0])//1000, "open": float(k[1]), "high": float(k[2]),
                "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])}
               for k in all_raw]
    if use_cache and candles:
        with open(path, "w") as f:
            json.dump(candles, f)
    return candles


# ── Rule-based CEO (no LLM) ───────────────────────────────────────────────────
def fast_decide(verdicts, regime):
    allowed, _ = regime_allows(regime)
    score = blend(verdicts)
    direction = "bullish" if score > 0.15 else "bearish" if score < -0.15 else "neutral"
    conf = min(1.0, abs(score))
    if not allowed or direction == "neutral" or conf < CONF_MIN:
        return "STAND_DOWN", conf, score
    return ("ENTRY_BUY" if direction == "bullish" else "ENTRY_SELL"), conf, score


# ── Position ──────────────────────────────────────────────────────────────────
class Position:
    def __init__(self, coin, side, qty, entry, idx):
        self.coin = coin; self.side = side
        self.qty = qty; self.entry = entry
        self.enter_idx = idx; self.peak_pnl = 0.0
        self.tp_taken = set(); self.closed_qty = 0.0; self.realised_usd = 0.0

    def pnl(self, price):
        if self.side == "SHORT":
            return (self.entry - price) / self.entry
        return (price - self.entry) / self.entry


# ── Per-coin backtest ─────────────────────────────────────────────────────────
def run_coin(coin, candles, shared_exposure, regime_counts):
    trades = []
    pos = None

    for i in range(WARMUP, len(candles) - 1, STRIDE):
        c_now  = candles[i]
        c_next = candles[i + 1]
        price  = c_now["close"]
        fill   = c_next["open"]

        # exit checks
        if pos:
            pnl = pos.pnl(price)
            pos.peak_pnl = max(pos.peak_pnl, pnl)
            sell_frac = 0.0; reason = None
            remaining = 1.0 - pos.closed_qty / pos.qty

            if remaining > 0.001:
                if pnl >= TP3_PCT and 3 not in pos.tp_taken:
                    sell_frac = TP3_FRAC; reason = "TP3"; pos.tp_taken.add(3)
                elif pnl >= TP2_PCT and 2 not in pos.tp_taken:
                    sell_frac = TP2_FRAC; reason = "TP2"; pos.tp_taken.add(2)
                elif pnl >= TP1_PCT and 1 not in pos.tp_taken:
                    sell_frac = TP1_FRAC; reason = "TP1"; pos.tp_taken.add(1)
                if sell_frac == 0:
                    if pnl <= -SL_PCT:
                        sell_frac = remaining; reason = "SL"
                    elif pos.peak_pnl > TRAIL_PCT and (pos.peak_pnl - pnl) >= TRAIL_PCT:
                        sell_frac = remaining; reason = "TRAIL"
                    elif (i - pos.enter_idx) // STRIDE >= MAX_HOLD_C:
                        sell_frac = remaining; reason = "MAXHOLD"

            if sell_frac > 0.001 and reason:
                close_qty = pos.qty * sell_frac
                fill_pnl = pos.pnl(fill)
                realised = close_qty * pos.entry * fill_pnl
                pos.realised_usd += realised
                pos.closed_qty   += close_qty
                trades.append({
                    "coin": coin, "side": pos.side,
                    "entry": round(pos.entry, 6), "exit": round(fill, 6),
                    "qty": round(close_qty, 8), "pnl_usd": round(realised, 4),
                    "pnl_pct": round(pnl * 100, 2), "reason": reason,
                    "hold_h": round((i - pos.enter_idx) * 15 / 60, 1),
                })
                if 1.0 - pos.closed_qty / pos.qty < 0.01:
                    shared_exposure[0] -= POS_USD
                    pos = None

        # entry
        if not pos:
            if shared_exposure[0] + POS_USD > MAX_EXPO:
                continue
            window = candles[max(0, i - 200):i]
            if len(window) < 50:
                continue
            idx_24h = max(0, i - 96)
            p_24h = candles[idx_24h]["close"]
            ticker = {"coin": coin, "price": price,
                      "change_24h_pct": round((price / p_24h - 1) * 100, 2)}
            try:
                verdicts = [
                    tech.analyze(coin, window),
                    volume_analyst(coin, window),
                    on_chain_analyst(coin, ticker),
                ]
                reg = regime_detector.detect(window)["regime"]
                regime_counts[reg] = regime_counts.get(reg, 0) + 1
                action, conf, score = fast_decide(verdicts, reg)
            except Exception:
                continue

            if action in ("ENTRY_BUY", "ENTRY_SELL"):
                side = "LONG" if action == "ENTRY_BUY" else "SHORT"
                qty = POS_USD / fill
                pos = Position(coin, side, qty, fill, i)
                shared_exposure[0] += POS_USD
                trades.append({
                    "coin": coin, "side": side,
                    "entry": round(fill, 6), "exit": None,
                    "qty": round(qty, 8), "pnl_usd": None, "pnl_pct": None,
                    "reason": "ENTRY", "hold_h": 0,
                })

    # force-close
    if pos:
        last_px = candles[-1]["close"]
        remaining = pos.qty - pos.closed_qty
        pnl = pos.pnl(last_px)
        realised = remaining * pos.entry * pnl
        shared_exposure[0] -= POS_USD
        trades.append({
            "coin": coin, "side": pos.side,
            "entry": round(pos.entry, 6), "exit": round(last_px, 6),
            "qty": round(remaining, 8), "pnl_usd": round(realised, 4),
            "pnl_pct": round(pnl * 100, 2), "reason": "EOD",
            "hold_h": round((len(candles) - 1 - pos.enter_idx) * 15 / 60, 1),
        })

    closed = [t for t in trades if t["pnl_usd"] is not None]
    return trades, closed


# ── Run one full period across all coins ──────────────────────────────────────
def run_period(coins, all_candles, label=""):
    shared_exposure = [0.0]
    regime_counts   = {}
    summary_rows    = []
    all_closed      = []

    for coin in coins:
        candles = all_candles.get(coin, [])
        if len(candles) < WARMUP + 10:
            print(f"  {coin}: insufficient data ({len(candles)} candles)")
            continue
        t0 = time.time()
        trades, closed = run_coin(coin, candles, shared_exposure, regime_counts)
        elapsed = time.time() - t0

        exits   = [t for t in closed if t["reason"] != "ENTRY"]
        longs_  = [t for t in exits if t["side"] == "LONG"]
        shorts_ = [t for t in exits if t["side"] == "SHORT"]
        wins    = [t for t in exits if t["pnl_usd"] > 0]
        losses  = [t for t in exits if t["pnl_usd"] <= 0]
        total_pnl = sum(t["pnl_usd"] for t in exits)
        avg_win  = sum(t["pnl_usd"] for t in wins)  / max(len(wins), 1)
        avg_loss = sum(t["pnl_usd"] for t in losses) / max(len(losses), 1)
        win_rate = len(wins) / len(exits) * 100 if exits else 0
        avg_hold = sum(t["hold_h"] for t in exits)  / max(len(exits), 1)

        long_wr  = (sum(1 for t in longs_  if t["pnl_usd"]>0) / max(len(longs_), 1)) * 100
        short_wr = (sum(1 for t in shorts_ if t["pnl_usd"]>0) / max(len(shorts_),1)) * 100

        all_closed.extend(exits)
        summary_rows.append({
            "coin": coin, "trades": len(exits), "wins": len(wins), "losses": len(losses),
            "win_rate": win_rate, "pnl_usd": total_pnl,
            "avg_win": avg_win, "avg_loss": avg_loss, "avg_hold_h": avg_hold,
            "n_long": len(longs_), "n_short": len(shorts_),
            "long_wr": long_wr, "short_wr": short_wr,
        })
        print(f"  {coin:6s}  {len(exits):>3} trades  "
              f"L:{len(longs_)}({long_wr:.0f}%)  S:{len(shorts_)}({short_wr:.0f}%)  "
              f"wr {win_rate:>5.1f}%  P&L ${total_pnl:>+8.2f}  ({elapsed:.1f}s)")

    return summary_rows, all_closed, regime_counts


# ── Print summary for one period ──────────────────────────────────────────────
def print_summary(summary_rows, all_closed, regime_counts, label, days_span):
    total_trades = sum(r["trades"] for r in summary_rows)
    total_wins   = sum(r["wins"]   for r in summary_rows)
    total_losses = sum(r["losses"] for r in summary_rows)
    total_pnl    = sum(r["pnl_usd"] for r in summary_rows)
    overall_wr   = total_wins / total_trades * 100 if total_trades else 0
    total_long   = sum(r["n_long"]  for r in summary_rows)
    total_short  = sum(r["n_short"] for r in summary_rows)

    wins_pnl  = [t["pnl_usd"] for t in all_closed if t["pnl_usd"] > 0]
    loss_pnl  = [t["pnl_usd"] for t in all_closed if t["pnl_usd"] <= 0]
    avg_w = sum(wins_pnl) / max(len(wins_pnl), 1)
    avg_l = sum(loss_pnl) / max(len(loss_pnl), 1)
    pf = abs(avg_w * total_wins / (avg_l * total_losses)) if total_losses and avg_l else float("inf")

    long_trades  = [t for t in all_closed if t["side"] == "LONG"]
    short_trades = [t for t in all_closed if t["side"] == "SHORT"]
    long_pnl  = sum(t["pnl_usd"] for t in long_trades)
    short_pnl = sum(t["pnl_usd"] for t in short_trades)
    long_wr   = sum(1 for t in long_trades  if t["pnl_usd"]>0) / max(len(long_trades), 1) * 100
    short_wr  = sum(1 for t in short_trades if t["pnl_usd"]>0) / max(len(short_trades),1) * 100

    exit_reasons = {}
    for t in all_closed:
        exit_reasons[t["reason"]] = exit_reasons.get(t["reason"], 0) + 1

    sorted_closed = sorted(all_closed, key=lambda x: x["pnl_usd"])
    worst3 = sorted_closed[:3]
    best3  = sorted_closed[-3:][::-1]

    total_regime = sum(regime_counts.values()) or 1
    regime_pct = {k: v / total_regime * 100 for k, v in regime_counts.items()}

    W = 74
    print("\n" + "═"*W)
    print(f"  {label}")
    print(f"  {'COIN':<6}  {'TR':>3}  {'L(wr%)':>9}  {'S(wr%)':>9}  {'WIN%':>6}  {'P&L USD':>10}  {'AVG_W':>7}  {'AVG_L':>7}")
    print("  " + "─"*(W-2))
    for r in sorted(summary_rows, key=lambda x: x["pnl_usd"], reverse=True):
        print(f"  {r['coin']:<6}  {r['trades']:>3}  "
              f"L{r['n_long']}({r['long_wr']:>4.0f}%)  "
              f"S{r['n_short']}({r['short_wr']:>4.0f}%)  "
              f"{r['win_rate']:>5.1f}%  "
              f"${r['pnl_usd']:>+9.2f}  "
              f"${r['avg_win']:>+6.2f}  "
              f"${r['avg_loss']:>+6.2f}")
    print("  " + "─"*(W-2))
    print(f"  {'TOTAL':<6}  {total_trades:>3}  "
          f"L{total_long}({long_wr:>4.0f}%)  "
          f"S{total_short}({short_wr:>4.0f}%)  "
          f"{overall_wr:>5.1f}%  "
          f"${total_pnl:>+9.2f}  "
          f"${avg_w:>+6.2f}  "
          f"${avg_l:>+6.2f}")
    print("═"*W)

    print(f"\n  Profit factor  : {pf:.2f}")
    avg_hold_all = sum(t["hold_h"] for t in all_closed) / max(len(all_closed), 1)
    print(f"  Avg hold time  : {avg_hold_all:.1f} h")
    print(f"  Return on $500 over {days_span}d  : {total_pnl/500*100:+.1f}%")

    print(f"\n  Long  P&L: ${long_pnl:+.2f} over {len(long_trades)} trades  wr {long_wr:.1f}%")
    print(f"  Short P&L: ${short_pnl:+.2f} over {len(short_trades)} trades  wr {short_wr:.1f}%")

    print(f"\n  Regime when entries triggered:")
    for reg in ("trending", "ranging", "volatile"):
        n = regime_counts.get(reg, 0)
        print(f"    {reg:<12} {n:>4} checks ({regime_pct.get(reg,0):>5.1f}%)")

    print(f"\n  Exit breakdown:")
    for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
        pct = count / total_trades * 100 if total_trades else 0
        print(f"    {reason:<10} {count:>4}  ({pct:.1f}%)")

    print(f"\n  Best 3 trades:")
    for t in best3:
        print(f"    {t['coin']:6s} {t['side']:5s}  in={t['entry']:.4f}  out={t['exit']:.4f}  "
              f"{t['pnl_pct']:>+6.2f}%  ${t['pnl_usd']:>+7.2f}  [{t['reason']}  {t['hold_h']:.1f}h]")
    print(f"  Worst 3 trades:")
    for t in worst3:
        print(f"    {t['coin']:6s} {t['side']:5s}  in={t['entry']:.4f}  out={t['exit']:.4f}  "
              f"{t['pnl_pct']:>+6.2f}%  ${t['pnl_usd']:>+7.2f}  [{t['reason']}  {t['hold_h']:.1f}h]")
    print()

    return {
        "total_trades": total_trades, "total_wins": total_wins,
        "win_rate": overall_wr, "pnl_usd": total_pnl,
        "long_pnl": long_pnl, "short_pnl": short_pnl,
        "long_wr": long_wr, "short_wr": short_wr,
        "profit_factor": pf, "regime": regime_pct,
    }


# ── Fetch data for a period ───────────────────────────────────────────────────
def fetch_period_data(coins, start_ms, end_ms, use_cache=True):
    all_candles = {}
    for coin in coins:
        print(f"  {coin} …", end=" ", flush=True)
        try:
            c = fetch_candles(coin, start_ms, end_ms, use_cache=use_cache)
            all_candles[coin] = c
            dt_s = datetime.datetime.utcfromtimestamp(start_ms//1000).strftime("%Y-%m-%d")
            dt_e = datetime.datetime.utcfromtimestamp(end_ms//1000).strftime("%Y-%m-%d")
            cached = " (cached)" if use_cache else ""
            print(f"{len(c)} candles  [{dt_s} → {dt_e}]{cached}")
        except Exception as e:
            print(f"FAILED ({e})")
            all_candles[coin] = []
        time.sleep(0.1)
    return all_candles


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="MiniSim v5 historical backtest")
    ap.add_argument("--days",    type=int,   default=30,   help="recent N days (default 30)")
    ap.add_argument("--period",  type=str,   default=None, help="named period key (see PERIODS)")
    ap.add_argument("--from",    dest="from_", metavar="YYYY-MM-DD", default=None)
    ap.add_argument("--to",      dest="to_",   metavar="YYYY-MM-DD", default=None)
    ap.add_argument("--compare", action="store_true", help="run all named periods and compare")
    ap.add_argument("--coins",   type=str,   default=None, help="comma-separated coin list")
    ap.add_argument("--no-cache",action="store_true", help="ignore and overwrite disk cache")
    args = ap.parse_args()

    coins = ALL_COINS if not args.coins else [c.strip().upper() for c in args.coins.split(",")]
    use_cache = not args.no_cache

    print(f"\nMiniSim v5 backtest — {len(coins)} coins  "
          f"SL={SL_PCT*100:.0f}%  TP={TP1_PCT*100:.0f}/{TP2_PCT*100:.0f}/{TP3_PCT*100:.0f}%  "
          f"trail={TRAIL_PCT*100:.0f}%  pos=${POS_USD:.0f}  conf≥{CONF_MIN}")

    # ── Compare mode ──────────────────────────────────────────────────────────
    if args.compare:
        print(f"\nComparing {len(PERIODS)} named periods …\n")
        compare_results = []

        for key, meta in PERIODS.items():
            start_ms = _ms(meta["start"])
            end_ms   = _ms(meta["end"])
            days_span = (end_ms - start_ms) // (86400 * 1000)
            label = f"[{meta['type'].upper():^5}] {meta['label']}"
            print(f"\n{'─'*74}")
            print(f"  {label}")
            print(f"  {meta['note']}")
            print(f"  Fetching data …")
            all_candles = fetch_period_data(coins, start_ms, end_ms, use_cache=use_cache)
            print(f"\n  Running …")
            summary_rows, all_closed, regime_counts = run_period(coins, all_candles, label)
            if not all_closed:
                print("  (no closed trades)")
                continue
            res = print_summary(summary_rows, all_closed, regime_counts, label, days_span)
            compare_results.append({"key": key, "meta": meta, "res": res, "days": days_span})

        # ── Comparison table ──────────────────────────────────────────────────
        if compare_results:
            W = 90
            print("\n" + "═"*W)
            print("  CROSS-PERIOD COMPARISON")
            print("  " + "─"*(W-2))
            hdr = f"  {'PERIOD':<32}  {'TYPE':^5}  {'TR':>4}  {'WR%':>5}  {'PNL':>8}  {'L_WR%':>6}  {'S_WR%':>6}  {'PF':>5}  {'TREND%':>7}"
            print(hdr)
            print("  " + "─"*(W-2))
            bear_rows  = [r for r in compare_results if r["meta"]["type"] == "bear"]
            bull_rows  = [r for r in compare_results if r["meta"]["type"] == "bull"]
            range_rows = [r for r in compare_results if r["meta"]["type"] == "range"]

            def _row(r):
                res = r["res"]
                pf_str = f"{res['profit_factor']:.2f}" if res["profit_factor"] != float("inf") else "∞"
                print(f"  {r['meta']['label'][:32]:<32}  {r['meta']['type']:^5}  "
                      f"{res['total_trades']:>4}  {res['win_rate']:>5.1f}  "
                      f"${res['pnl_usd']:>+7.2f}  {res['long_wr']:>6.1f}  "
                      f"{res['short_wr']:>6.1f}  {pf_str:>5}  "
                      f"{res['regime'].get('trending', 0):>6.1f}%")

            for r in bear_rows:  _row(r)
            print("  " + "·"*(W-2))
            for r in bull_rows:  _row(r)
            print("  " + "·"*(W-2))
            for r in range_rows: _row(r)
            print("  " + "─"*(W-2))

            def _avg(rows, key):
                vals = [r["res"][key] for r in rows if r["res"]["total_trades"] > 0]
                return sum(vals) / len(vals) if vals else 0

            print(f"\n  Averages by market type:")
            for mtype, rows in [("bear", bear_rows), ("bull", bull_rows), ("range", range_rows)]:
                if not rows:
                    continue
                avg_wr  = _avg(rows, "win_rate")
                avg_pnl = _avg(rows, "pnl_usd")
                avg_lwr = _avg(rows, "long_wr")
                avg_swr = _avg(rows, "short_wr")
                print(f"    {mtype.upper():5s}   wr={avg_wr:.1f}%  pnl=${avg_pnl:+.2f}  "
                      f"long_wr={avg_lwr:.1f}%  short_wr={avg_swr:.1f}%")

            # bear vs bull verdict
            if bear_rows and bull_rows:
                bear_pnl = _avg(bear_rows, "pnl_usd")
                bull_pnl = _avg(bull_rows, "pnl_usd")
                bear_swr = _avg(bear_rows, "short_wr")
                bull_swr = _avg(bull_rows, "short_wr")
                print(f"\n  BEAR vs BULL verdict:")
                print(f"    Bear avg P&L: ${bear_pnl:+.2f}   Bull avg P&L: ${bull_pnl:+.2f}")
                print(f"    Bear short win rate: {bear_swr:.1f}%   Bull short win rate: {bull_swr:.1f}%")
                verdict = "CONFIRMED — strategy outperforms in bear markets" if bear_pnl > bull_pnl \
                    else "NOT CONFIRMED — bull market performs better on this sample"
                print(f"\n  ➜  Bear-market hypothesis: {verdict}")
            print("═"*W + "\n")
        return

    # ── Single-period mode ─────────────────────────────────────────────────────
    now_ms = int(time.time() * 1000)

    if args.period:
        if args.period not in PERIODS:
            print(f"Unknown period '{args.period}'. Available: {', '.join(PERIODS)}")
            sys.exit(1)
        meta = PERIODS[args.period]
        start_ms = _ms(meta["start"])
        end_ms   = _ms(meta["end"])
        label = f"[{meta['type'].upper()}] {meta['label']}"
        print(f"\n  {label}")
        print(f"  {meta['note']}")
    elif args.from_ and args.to_:
        start_ms = _ms(args.from_)
        end_ms   = _ms(args.to_)
        label = f"Custom {args.from_} → {args.to_}"
    else:
        end_ms   = now_ms
        start_ms = end_ms - args.days * 86400 * 1000
        label = f"Recent {args.days} days"

    days_span = (end_ms - start_ms) // (86400 * 1000)
    print(f"\nFetching {days_span} days of 15m candles …\n")
    all_candles = fetch_period_data(coins, start_ms, end_ms, use_cache=use_cache)

    print(f"\nRunning backtest …\n")
    summary_rows, all_closed, regime_counts = run_period(coins, all_candles, label)

    if not all_closed:
        print("\n  No closed trades in this period.\n")
        return

    print_summary(summary_rows, all_closed, regime_counts, label, days_span)


if __name__ == "__main__":
    main()
