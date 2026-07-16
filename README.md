# MiniSim v6

Automated cryptocurrency trading-signal system built to run on a **Raspberry Pi 5
(16GB RAM / NVMe SSD)**. Paper trading by default — no real money is touched until
you explicitly change one line in `config.py` and supply Binance credentials.

> **Accounts & API keys:** paper mode needs none. For testnet/live/Hyperliquid,
> see **[ACCOUNTS.md](ACCOUNTS.md)** — which accounts to create and where the
> login details go (`config/secrets.py`, never committed).

---

## What it does

MiniSim watches 15 coins simultaneously, runs a full analysis pipeline every ~22
minutes, and manages open positions on a faster 30-second loop. It uses a local
AI model (no cloud) and a market-adaptive strategy selection system to decide when
to enter and exit trades.

The default outcome is always **STAND_DOWN** — the system has to overcome multiple
independent checks to place an order. It is designed to skip a trade rather than
force one.

---

## Version history

| Version | Headline change |
|---------|----------------|
| v4 | Ollama (Docker), basic RSI/MACD/EMA indicators, planned dashboard |
| v5 | Quantized on-device GGUF model, 14-indicator suite, MCP server architecture, two live dashboards, 40/40 tests, two independent code-review cycles |
| v6 | Multi-strategy system — 6 named strategies, hourly LLM router, bull/bear/neutral market classifier, per-position SL/TP overrides, historical backtester, strategies panel on both dashboards |
| **v7** | **Wiring & honesty release** — fixes from a full v6 code review: strategy router / per-strategy exits / short-cover flip actually execute now; per-strategy P&L feedback and risk_level sizing are live; exits use fresh ≤20s mark prices; kill switch keeps protective exits running; synthetic-data entry veto; no canned headlines outside fixture mode; paper fills charge fees + slippage; live orders respect LOT_SIZE; unknown orders logged for reconciliation |

---

## System overview

```
┌─────────────────────────────────────────────────────────────┐
│                        MiniSim v6                           │
│                                                             │
│  ┌──────────────┐   ┌───────────────────────────────────┐  │
│  │ Strategy     │   │  Think-cycle  (~22 min, per coin) │  │
│  │ Router       │   │                                   │  │
│  │ (hourly LLM) │──▶│  MCP feeds → 5 analysts → regime │  │
│  └──────────────┘   │  → strategy signals → CEO (LLM)  │  │
│         ▲           │  → risk manager → order executor  │  │
│         │           └──────────────────┬────────────────┘  │
│  ┌──────┴───────┐                      │                   │
│  │ Market state │             ┌─────────▼──────────┐       │
│  │ detector     │             │  Exit watch loop   │       │
│  │ (bull/bear/  │             │  (30s, all coins)  │       │
│  │  neutral)    │             │  SL / TP / trail   │       │
│  └──────────────┘             └────────────────────┘       │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Dashboards  (port 8770)                             │  │
│  │  /pi  — Pi touchscreen kiosk                        │  │
│  │  /    — mobile browser (phone on same Wi-Fi)        │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## End-to-end pipeline

### 1. Data collection — MCP servers

Three local subprocesses expose data over **Model Context Protocol (stdio)**:

| Server | Tools provided |
|--------|---------------|
| `market_data_server` | `get_candles` (300 × 15m OHLCV), `get_ticker`, `get_orderbook` |
| `news_sentiment_server` | `get_headlines` (CoinGecko news + RSS) |
| `exchange_server` | `balance`, `positions`, `place_order`, `update_meta` |

`mcp_client/client.py` is the **only** place the rest of the system touches data or
the exchange. If the MCP transport fails, the client falls back to running the same
logic in-process — the trader never goes down due to a subprocess crash.

Data is cached within a cycle (`MARKET_CACHE_SEC = 600`) so all 15 coins see the
same data vintage. The source is labelled (`coingecko` / `synthetic(fallback)`) and
surfaced on both dashboards.

---

### 2. Analysis — 5 independent analysts

Each analyst returns `bullish / bearish / neutral` with a confidence score (0–1).
They are independent; they do not see each other's output.

#### Technical analyst (`analysts/technical_analyst.py`)

Runs 14 indicators on 300 × 15m candles:

| Group | Indicators |
|-------|-----------|
| Trend | EMA 20/50/200, Supertrend (ATR-based, proper band carry-over) |
| Momentum | RSI (14), MACD (12/26/9), Stochastic RSI (%K/%D smoothed) |
| Volatility | Bollinger Bands (20, 2σ), Keltner Channels |
| Volume | OBV (on-balance volume), VWAP |
| Structure | ADX/+DI/−DI (directional strength), RSI divergence (confirmed swing pivots) |
| Multi-timeframe | Higher-timeframe Supertrend confirmation — signal dampened if HTF disagrees |

**Regime-aware oscillators:** in a strong trend (ADX > 25) RSI/StochRSI extremes
*confirm* the trend rather than generate reversal signals. This prevents "oversold in
a downtrend" from producing false buy votes.

#### Volume analyst (`analysts/other_analysts.py`)

Compares current volume to the 20-candle average. Spike + price direction → signal.
Also evaluates OBV slope over 10 candles.

#### Order book analyst

Bid/ask depth imbalance and spread as a fraction of price. Excess bid depth → bullish;
excess ask depth → bearish.

#### On-chain analyst

Price vs 24h change; extreme moves flag a reversal risk. Also reads funding rate and
open interest where available from the ticker.

#### Sentiment analyst (`analysts/sentiment_analyst.py`)

Passes the latest headlines for the coin + recent trading performance to the quantized
LLM. Returns sentiment verdict + confidence.

---

### 3. Regime detection (`analysts/regime_detector.py`)

Runs on the same candle data. ADX > 25 with directional bias → `trending`.
ADX < 20 with price oscillating inside Bollinger Bands → `ranging`. Used by:
- The regime filter (blocks entries in weak/unfavourable regimes when `REGIME_FILTER_STRICT`)
- The market state detector to classify bull/bear/neutral per coin

---

### 4. Strategy system (v6)

#### Market state detection (`strategies/market_state.py`)

Runs once per cycle across all tracked coins. Per coin:
- EMA stack (20 vs 50, 50 vs 200, price vs 200) — 3 directional scores
- Supertrend direction — 1 score
- ADX/+DI/−DI balance — 1 score
- 7-day return sign — 1 score

Aggregated across coins → `bull / bear / neutral` direction + regime string.
BTC gets extra weight as the market bellwether.

#### Strategy router (`strategies/router.py`)

Runs an LLM call **once per hour** (not in the hot path). Receives:
- Current market direction + regime
- Per-strategy performance from the last N decisions (trades, win rate, realised P&L)

Returns which 1–3 strategies to activate and a risk multiplier (0.5×–2.0×). Result
is cached to `data/strategy_state.json`. `get_active_strategies()` reads the cache
instantly — zero LLM cost during the think-cycle. If the LLM fails, falls back to
RangeScalp (safe, both sides).

#### The 6 strategies

Each strategy uses a **two-stage signal pipeline**:

1. **Arithmetic hard gates** — fast kill-off with no LLM cost (RSI gate, EMA
   alignment, ADX gate). If gates fail, return HOLD immediately.
2. **Arithmetic scoring** — builds a 0–1 pre-screen confidence from weighted
   indicator checks. If score < 0.35 (`LLM_TRIGGER_CONF`), return HOLD.
3. **LLM confirmation** — when the pre-screen passes, the LLM receives all
   computed indicator values, the strategy's `philosophy` string, side constraint,
   regime, and the arithmetic pre-screen result. It independently decides
   `BUY / SELL / HOLD` with its own confidence and one-sentence reasoning.
   The LLM can reject a signal the arithmetic would have taken.
4. **Fallback** — if the LLM is unavailable, the arithmetic result is used.

Side constraints are enforced in code after the LLM responds — a LONG-only
strategy cannot return `SELL` regardless of what the model outputs.

| Strategy | Side | Best for | SL | TP targets | Trail | Max hold |
|----------|------|----------|----|-----------|-------|---------|
| **TrendShort** | SHORT only | Bear + trending | 2.5% | 8 / 15 / 25% | 5% | 4 days |
| **BreakdownScalp** | SHORT only | Bear + ranging | 1.5% | 3 / 6% | — | 24h |
| **OversoldBounce** | LONG only | Bear + ranging | 1.5% | 3 / 6% | — | 16h |
| **MomentumLong** | LONG only | Bull + trending | 2.5% | 8 / 15 / 25% | 5% | 4 days |
| **DipBuy** | LONG only | Bull + ranging | 2.0% | 5 / 10% | 3% | 48h |
| **RangeScalp** | BOTH | Ranging | 1.5% | 3 / 5% | — | 20h |

**TrendShort**: arithmetic screens for EMA20 < 50 < 200, price below EMA200,
Supertrend bearish on 15m and 4h, MACD < 0, ADX > 25 with −DI > +DI.
LLM evaluates the full indicator picture and regime fit before confirming.

**BreakdownScalp**: arithmetic screens for price below Bollinger lower band,
volume spike (1.3–2.5× average), MACD histogram negative, RSI 30–55.
LLM judges whether it is a genuine breakdown or a false break.

**OversoldBounce**: hard gate RSI < 30 (no LLM cost above this). Arithmetic
scores RSI depth, StochK position, BB extension, RSI bullish divergence.
LLM confirms whether a bounce is likely or the bear trend continues.

**MomentumLong**: mirror of TrendShort but bullish — EMA20 > 50 > 200, price
above EMA200, Supertrend up, MACD > 0, ADX > 20 with +DI > −DI.
LLM evaluates trend maturity and entry quality.

**DipBuy**: hard gates price > EMA200 AND RSI ≤ 52. Arithmetic scores proximity
to EMA50, StochRSI turn, MACD histogram improving, RSI divergence.
LLM assesses whether this is a real pullback entry or a trend reversal.

**RangeScalp**: hard gate ADX < 25. Arithmetic scores RSI/BB/StochRSI/Keltner
extremes on both sides. LLM confirms range structure and rejects breakouts.

---

### 5. CEO decision (`decision/engine.py`)

The **arithmetic blend** weights the 5 analyst verdicts:

| Analyst | Weight |
|---------|--------|
| Technical | 1.4 |
| Sentiment | 0.9 |
| Volume | 0.7 |
| Order book | 0.7 |
| On-chain | 0.5 |

This produces a signed score in [−1, +1] and a direction (`bullish / bearish / neutral`).

The **LLM CEO** sees: analyst verdicts, regime, active strategy signals (action,
confidence, reason per strategy), strategy SL/TP params, and recent trading
performance for this coin. It returns a verdict + confidence + the strategy name
whose parameters to use.

**Agreement rule:** the CEO must agree with the arithmetic direction. If they
disagree, confidence is zeroed and no trade fires. This means the LLM can only
*confirm*, not override, the quantitative signal.

Final confidence = 0.7 × arithmetic + 0.3 × CEO (only if agreement).

If confidence ≥ `ROUTINE_SIGNAL_CONFIDENCE_MIN` (0.65) and regime allows → action.

---

### 6. Risk manager (`execution/risk_manager.py`)

Before any order:
- Position size = `POSITION_SIZE_USD` (£100 default), scaled by strategy risk multiplier
- Total exposure cap: `MAX_EXPOSURE_USD` (£500) — refuses entry if already at limit
- Big trade gate: orders > `BIG_TRADE_THRESHOLD_USD` (£1,000) require human approval
- Duplicate check: skips if already long/short this coin

---

### 7. Order execution (`execution/order_executor.py`)

Calls the exchange MCP server with a **client order ID** (signal_id + coin + side +
timestamp). `place_order` is marked non-retryable — on any transport error it returns
`status: "unknown"` and the order is never re-sent, preventing double-execution.

**Paper mode**: full simulated fills with slippage model, running wallet and positions
stored in `state/` under a cross-process file lock.

**Testnet/Live**: routes through `ccxt` to Binance. Preflight on startup reads the
real exchange balance and aborts if it can't, or if the exchange reports a different
mode than `config.MODE`.

When a position opens, the chosen strategy's parameters are stored on the position
record via `mcp.update_meta()`:

```
strat_name, strat_sl, strat_tp1/2/3, strat_frac1/2/3,
strat_trail, strat_trail_min, strat_max_hold_h
```

---

### 8. Exit watch (`execution/exit_manager.py`)

Runs on its own thread, every 30 seconds — independent of the think-cycle so a slow
LLM call never delays a stop-loss.

Per open position, reads strategy overrides first, falls back to global config:

| Exit condition | Check |
|---------------|-------|
| Stop loss | `pnl ≤ −strat_sl` (or `−STOP_LOSS_PERCENT`) |
| Max hold | `age_hours ≥ strat_max_hold_h` (or `MAX_HOLD_TIME_HOURS`) |
| Take-profit T1 | `pnl ≥ strat_tp1` and T1 not yet taken → sell `strat_frac1` |
| Take-profit T2 | `pnl ≥ strat_tp2` and T2 not yet taken → sell `strat_frac2` |
| Take-profit T3 | `pnl ≥ strat_tp3` and T3 not yet taken → sell `strat_frac3` |
| Trailing stop | `pnl ≥ trail_min` and `peak_pnl − pnl ≥ strat_trail` |

Take-profit levels are marked taken **only after a confirmed fill** — an unfilled
partial retries on the next pass. `peak_pnl` is persisted across cycles so the
trailing stop never resets.

---

### 9. Records

| File | Contents |
|------|---------|
| `data/decision_log.jsonl` | Every decision: coin, action, confidence, reasoning, analysts, strategy tag |
| `data/tax_ledger.jsonl` | Every fill: coin, side, quantity, actual fill price |
| `state/status.json` | Latest equity, positions, regime, uptime — read by dashboards |
| `state/equity_history.json` | Timestamped equity snapshots — drives the chart |
| `data/strategy_state.json` | Router cache: active strategies, direction, risk level, per-strategy P&L |

---

## Backtesting (`backtest.py`)

Fetches historical OHLCV from Binance public klines. Results are disk-cached
(`.bt_cache/`, keyed by MD5 of coin+range) so reruns are instant.

```bash
python backtest.py --compare                    # all 9 periods in a cross-table
python backtest.py --period bear_2022_q1        # single named period
python backtest.py --from 2024-01-01 --days 90  # custom range
python backtest.py --coins BTC ETH SOL          # coin subset
python backtest.py --no-cache                   # force re-fetch
```

**Named periods:**

| Period | Dates | Type |
|--------|-------|------|
| bear_2022_q1 | Jan–Mar 2022 | Bear |
| bear_2022_q2 | Apr–Jun 2022 | Bear |
| bear_2022_crash | Jun 2022 | Bear (crash) |
| bear_ftx | Nov 2022 | Bear (FTX collapse) |
| bear_2024_q3 | Jul–Sep 2024 | Bear |
| bull_2023_q1 | Jan–Mar 2023 | Bull |
| bull_2024_q1 | Jan–Mar 2024 | Bull |
| range_2023_q3 | Jul–Sep 2023 | Ranging |
| range_2022_h2_mid | Aug–Oct 2022 | Ranging |

**Key finding:** strategy short signals achieve 60.5% win rate in bear periods vs
45.4% in bull periods. Average P&L: +$151.79 (bear) vs −$247.29 (bull) across
15 coins.

---

## Dashboards

One FastAPI process (`dashboard/server.py`, port 8770). The trader never calls the
dashboard; it reads only from files the engine writes.

### `/` — Mobile view (phone on same Wi-Fi)

- **Portfolio** — equity figure, delta vs session start, cash/positions/cycle/uptime
  line, 100px sparkline chart with labelled axis
- **Open Positions** — per-position card with side badge, entry/current price, PnL%,
  progress bar
- **Market Signals** — 3×5 coin grid; each cell has coloured initial dot (no CDN),
  coin name, price, signal label + confidence, 5 analyst dots, signal age (red if stale)
- **Strategies** — router state (direction, risk, timestamp, reasoning); all 6
  strategies listed with active/idle dot indicator, LONG/SHORT/BOTH badge, SL%, TP
  ladder, trade count, win rate, P&L from `last_perf`
- **Performance** — win/loss donut, stats grid, scrollable recent trade list
- **System** — MCP transport, LLM backend, data source, uptime, version chips
- **Kill switch** — fixed bottom bar, one tap stops all trading

### `/pi` — Pi kiosk (800×480, fixed-height, no scroll)

- **Header** — brand, regime badge (colour-coded), cycle arc (progress through 15
  coins), MCP/LLM status pills, clock, split-screen toggle, minimise/close buttons
- **Regime bar** — 3px gradient strip under header, changes colour with market regime
- **Top band** — equity card (equity, delta, cash line, sparkline) + open positions
  panel (scrollable position cards with coloured dots)
- **Mid row** — 5×3 coin grid; click a cell to open candlestick modal; in split mode
  grid becomes 3×3 and a live chart panel opens alongside
- **Footer** — win-rate donut, stats chips (trades / avg PnL / realized / coins),
  **⚡ STRAT chip** → opens strategy overlay modal, kill switch button
- **Strategy modal** — market direction, risk level, router reasoning, full strategy
  list with active indicator, params, and per-strategy stats

Both dashboards:
- No external CDN dependencies — coin icons are offline coloured initial-letter dots
- CSRF token protection on all state-changing endpoints
- Origin and Host allow-list blocks DNS-rebinding and cross-site control
- Optional `MINISIM_DASH_TOKEN` shared secret for read endpoints

---

## Architecture

```
MiniSim-v6/
  config/
    config.py                  # all settings, plain-English comments
    secrets.example.py         # copy to secrets.py, add Binance keys

  llm/
    quantized_client.py        # GGUF via llama-cpp-python; 3 backends + safe fallback

  analysts/
    indicators.py              # 14 indicators (EMA, RSI, MACD, BB, KC, ADX, Supertrend,
                               #   StochRSI, OBV, VWAP, RSI divergence, resample)
    technical_analyst.py       # regime-aware signal assembly + multi-timeframe confirm
    other_analysts.py          # volume, order-book, on-chain analysts
    sentiment_analyst.py       # LLM-backed headline sentiment + coin performance context
    regime_detector.py         # trending / ranging classifier

  strategies/
    base.py                    # Strategy ABC, StrategyParams, Signal dataclasses
    __init__.py                # REGISTRY dict of all 6 strategy instances
    market_state.py            # bull / bear / neutral detector across all coins
    router.py                  # hourly LLM strategy selector; caches to strategy_state.json
    bear_trend_short.py        # TrendShort  (SHORT, bear+trending)
    bear_scalp.py              # BreakdownScalp (SHORT, bear+ranging)
    bear_bounce.py             # OversoldBounce (LONG, bear+ranging)
    bull_momentum.py           # MomentumLong (LONG, bull+trending)
    bull_dip.py                # DipBuy  (LONG, bull+ranging)
    range_scalp.py             # RangeScalp (BOTH, ranging)

  decision/
    engine.py                  # blend → CEO (LLM) → agree check → action + strategy tag

  execution/
    risk_manager.py            # position sizing, exposure cap, human-approval gate
    exit_manager.py            # SL / TP ladder / trailing stop (per-position strategy params)
    order_executor.py          # idempotent order dispatch; non-retryable place_order

  records/
    decision_log.py            # append-only JSONL decision log
    performance.py             # per-coin/per-strategy stats from the log; CEO context
    tax_ledger.py              # fill-price trade record for tax reporting

  operations/
    kill_switch.py             # file-based kill; survives process restart
    status_writer.py           # writes state/status.json each cycle for dashboards

  mcp_servers/
    market_data_server.py      # FastMCP wrapper
    _marketdata_core.py        # CoinGecko + Binance klines, candle cache
    news_sentiment_server.py
    _news_core.py              # RSS + CoinGecko news headlines
    exchange_server.py
    _exchange_core.py          # paper wallet / ccxt; file-locked mutations

  mcp_client/
    client.py                  # launches servers, calls tools, in-process fallback

  dashboard/
    server.py                  # FastAPI; /api/status /decisions /performance
                               #   /equity_history /prices /candles /strategy_state
                               #   /kill /resume /wm/minimize
    mobile/index.html          # single-file mobile dashboard
    pi/index.html              # single-file Pi kiosk

  schemas/
    validators.py              # verdict/confidence schema validation at boundaries

  backtest.py                  # historical backtester with disk cache
  main.py                      # orchestrator: think-cycle thread + exit-watch thread

  data/                        # decision_log.jsonl, tax_ledger.jsonl, strategy_state.json
  state/                       # status.json, equity_history.json, positions.json,
                               #   position_meta.json, kill_switch.lock
  models/                      # qwen2.5-3b-instruct-q4_k_m.gguf (downloaded separately)
  tests/
    run_tests.py               # 40 tests covering all critical and high-severity paths
```

---

## Quick start

### Raspberry Pi (one-click)

```bash
bash install.sh
```

Installs system packages, builds Python venv, downloads the quantized model (~2GB,
one-time), runs all tests, enables auto-start on boot via systemd, creates Desktop
shortcuts. Full walkthrough in `SETUP_GUIDE.md`.

### Manual / developers

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
bash scripts/download_model.sh        # downloads GGUF to models/

python tests/run_tests.py             # expect 40 passed

python main.py --once                 # single cycle, paper mode
python main.py                        # runs forever; 15-coin cycle every ~22 min

python -m dashboard.server            # http://<pi-ip>:8770  |  /pi
```

### Adding real Binance credentials

```bash
cp config/secrets.example.py config/secrets.py
nano config/secrets.py                # paste API key + secret
```

Then in `config/config.py`, change `MODE = "paper"` to `"testnet"` (fake money,
real API) or `"live"` (real money — only after weeks of testnet).

---

## Safety design

| Layer | Mechanism |
|-------|----------|
| Default outcome | STAND_DOWN unless confidence clears two independent thresholds |
| Kill switch | File-based; survives process restart; re-checked before every order |
| Idempotent orders | Client order ID = signal_id + coin + side + timestamp; non-retryable |
| Atomic writes | All state files written via temp-file rename; file lock for wallet mutations |
| Exposure cap | Refuses entry if total open exposure ≥ `MAX_EXPOSURE_USD` |
| Regime filter | Blocks entries in unfavourable regimes (configurable strictness) |
| LLM agreement rule | CEO must agree with arithmetic blend; disagreement → no trade |
| Side constraints | LONG-only strategies cannot trigger ENTRY_SELL and vice versa |
| Big-trade gate | Orders > `BIG_TRADE_THRESHOLD_USD` need human approval |
| Schema validation | LLM output validated to enum before entering any record |
| LLM safe fallback | Missing/slow model → neutral stand-down, never a crash |
| Dashboard CSRF | Per-process token required on all state-changing endpoints |
| DNS-rebinding guard | Host allow-list + Origin check on /kill and /resume |
| Mode preflight | Refuses to start if exchange reports a different mode than config |
| XSS prevention | All dynamic values HTML-escaped before rendering |

---

## Honest limits

1. **Real LLM latency** — first call loads the GGUF (~45s on Pi 5). Raise
   `LLM_TIMEOUT_SEC` if inference is slow on your board. CI runs with the stub
   fallback; verify real inference before trusting signals.

2. **UK / Binance restrictions** — live futures shorts are unavailable on UK
   accounts. SHORT-side strategies run in paper mode only.

3. **Real market data** — in `paper` mode the system uses CoinGecko public API.
   Rate limits cause fallback to synthetic candles (labelled on dashboards). Wire
   a paid feed before relying on signals for real money.

4. **Exchange execution** — testnet/live order sizing, symbol filters, and
   minimum notional need verification against the live Binance environment before
   use.

5. **No real money has been traded.** This is experimental software. Use at your
   own risk. No warranty.

---

## License
MIT. v6.0.0 (June 2026).
