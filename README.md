# MiniSim — v6

Cryptocurrency trading-signal system running on a **Raspberry Pi 5 (16GB / NVMe)**.
Paper trading by default; `testnet`/`live` require Binance credentials and deliberate opt-in.

| Area | v5 | v6 |
|------|----|----|
| **Strategy** | Single signal path — analysts → CEO → trade | **6 named strategies** (bear/bull/ranging) + **LLM router** selects 1–3 active strategies per hour |
| **Market regime** | Regime detector (trending/ranging) | **Full bull/bear/neutral classifier** using EMA stack, Supertrend, ADX, and 7-day returns across all tracked coins |
| **Exit management** | Global config SL/TP/trail | **Per-position strategy params** — chosen strategy's SL, TP ladder and trail stored at entry; exit manager reads them, falls back to config |
| **Backtesting** | None | **Historical backtest framework** with named bear/bull/ranging periods, disk cache, and cross-period comparison |
| **Dashboards** | Equity, positions, signals, health | **+ Strategies panel** on both views; coin icons replaced with offline coloured dots; Pi view adds ⚡ STRAT chip |

> **Status:** runs end-to-end in `paper` mode (no keys, no money). 35/35 code-review
> findings fixed — see `FIXES.md`. Backtest confirmed bear-market outperformance:
> avg P&L +$151 (bear periods) vs −$247 (bull periods) at 60.5% short win rate in bear.

---

## How v6 works

### Think-cycle (per coin, every ~15 min)

```
MCP feeds → 5 analysts → regime → active strategy signals → CEO → risk → execute → log
```

1. **5 analysts** (technical, volume, order-book, on-chain, sentiment) each return
   `bullish / bearish / neutral` with a confidence score.
2. **Regime detector** classifies the market as `trending / ranging`.
3. **Strategy signals** — each of the 1–3 active strategies runs its own fast
   arithmetic signal on the same candles and returns `BUY / SELL / HOLD`.
4. **CEO (LLM)** receives analyst verdicts + strategy signals. It must agree with the
   arithmetic blend for a trade to fire. It also names which strategy's params to use.
5. **Risk manager** sizes the position; big trades need human approval.
6. **Exit manager** reads the position's stored `strat_sl / strat_tp / strat_trail`
   to manage the profit ladder and trailing stop independently of the think-cycle.

### Strategy router (hourly LLM call)

`strategies/router.py` calls the LLM once per hour (or when forced) with:
- Current market direction (bull / bear / neutral) from `strategies/market_state.py`
- Per-strategy performance from the decision log (trades, win rate, P&L)

The LLM returns which 1–3 strategies to activate and a risk multiplier.
The result is cached to `data/strategy_state.json`; `get_active_strategies()` reads
it instantly — no LLM call in the hot path.

### The 6 strategies

| Name | Side | Best for | SL | TP |
|------|------|----------|----|----|
| `trend_short` — TrendShort | SHORT | Bear, trending | 2.5% | 8/15/25% + 5% trail |
| `breakdown_scalp` — BreakdownScalp | SHORT | Bear, ranging | 1.5% | 3/6% |
| `oversold_bounce` — OversoldBounce | LONG | Bear, ranging | 1.5% | 3/6% |
| `momentum_long` — MomentumLong | LONG | Bull, trending | 2.5% | 8/15/25% + 5% trail |
| `dip_buy` — DipBuy | LONG | Bull, ranging | 2.0% | 5/10% + 3% trail |
| `range_scalp` — RangeScalp | BOTH | Ranging | 1.5% | 3/5% |

Each strategy enforces its side constraint (a LONG-only strategy will never produce
an `ENTRY_SELL`). Signals use only arithmetic indicators — no LLM in the hot path.

### Market state detection (`strategies/market_state.py`)

Per coin: EMA20/50/200 stack, Supertrend direction, ADX/+DI/−DI, 7-day return.
Aggregated across all tracked coins + BTC regime → `bull / bear / neutral` direction
and `trending / ranging` regime. Used by the router and logged in strategy state.

---

## Architecture

```
MiniSim-v6/
  config/            config.py, secrets.example.py
  llm/               quantized_client.py        # GGUF via llama-cpp-python
  analysts/          indicators.py, technical_analyst.py, other_analysts.py,
                     sentiment_analyst.py, regime_detector.py
  strategies/        base.py, __init__.py (REGISTRY)
                     bear_trend_short.py, bear_scalp.py, bear_bounce.py
                     bull_momentum.py, bull_dip.py, range_scalp.py
                     market_state.py, router.py
  decision/          engine.py                  # analysts + strategy signals → CEO
  execution/         risk_manager.py, exit_manager.py, order_executor.py
  records/           decision_log.py, performance.py, tax_ledger.py
  operations/        kill_switch.py, status_writer.py
  schemas/           validators.py
  mcp_servers/       market_data_server.py, news_sentiment_server.py,
                     exchange_server.py + _*_core.py
  mcp_client/        client.py
  dashboard/         server.py, pi/index.html, mobile/index.html
  data/              strategy_state.json (router cache), status.json, equity_history.json
  backtest.py        historical backtester (bear/bull/ranging periods, disk cache)
  main.py            orchestrator
```

---

## Quick start

**Raspberry Pi (one-click):**
```bash
bash install.sh
```
Installs packages, builds venv, downloads quantized model, runs tests, enables boot
service, creates Desktop shortcuts. See `SETUP_GUIDE.md` for a plain-English walkthrough.

**Manual / developers:**
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
bash scripts/download_model.sh        # ~2GB GGUF onto NVMe
python tests/run_tests.py             # expect 40+ passed
python main.py --once                 # single cycle, paper mode
python main.py                        # run forever
python -m dashboard.server            # http://<pi-ip>:8770 (mobile) | /pi (kiosk)
```

**Backtesting:**
```bash
python backtest.py --compare                   # all periods, cross-table
python backtest.py --period bear_2022_q1       # single named period
python backtest.py --from 2024-01-01 --days 90 # custom date range
python backtest.py --coins BTC ETH SOL         # subset of coins
```

---

## Dashboards

One FastAPI server (`dashboard/server.py`, port 8770) serves both views from the
same data; the trader never calls the dashboard.

**`/`** — Mobile view (phone on same Wi-Fi)
- Portfolio equity + sparkline + stat row
- Open positions with PnL bar
- 15-coin signal grid (coloured initial dots, analyst dot row, signal age)
- **Strategies section** — router direction/risk/reasoning, all 6 strategies with
  active indicator, SL/TP params, and per-strategy trade count / win rate / P&L
- Performance (donut + trade list)
- System health chips

**`/pi`** — Pi kiosk (800×480 touchscreen, fixed-height, no scroll)
- Header with regime badge, cycle arc, MCP/LLM pills, clock, split toggle
- Equity card + positions panel (top band)
- 5×3 coin signal grid (or 3×3 in split mode with live chart panel)
- Footer with donut, stats chips, **⚡ STRAT button** → strategy overlay modal
- Kill switch

Both views have no external network dependencies — coin icons are coloured
initial-letter dots (no CDN calls).

---

## Safety

Kill switch (survives restart), idempotent client-order-IDs, atomic file writes,
exposure caps, regime filter, confidence thresholds, big-trade human approval,
schema validation at boundaries, LLM fails safe to "stand down", side-constraint
enforcement (LONG-only strategy can never open a short).

## Honest limits

1. **Real LLM latency** — measure `llama.cpp` inference on your board; raise
   `LLM_TIMEOUT_SEC` if needed. CI tested with stub fallback only.
2. **UK Binance restrictions** — live futures/shorts unavailable; paper mode only
   for SHORT-side strategies in `live`.
3. **Real market feeds** — paper/testnet fall back to synthetic candles on rate-limit;
   these are not real prices. Verify before trusting signals.
4. **No real money has been traded.** Use at your own risk; no warranty.

## License
MIT. v6.0.0 (June 2026).
