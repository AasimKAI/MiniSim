# Crypto Signal System — v5

Cryptocurrency trading-signal system, evolved from v4. Same safety-first 6-layer
design, with four headline upgrades for the Raspberry Pi 5 (16GB / NVMe):

| Area | v4 | v5 |
|------|----|----|
| **AI / LLM** | Ollama server (Docker) running llama2 | On-device **quantized GGUF** model via `llama-cpp-python` — no Docker, no server, runs on the Pi's SSD |
| **Indicators** | RSI, MACD, EMA, Bollinger, ATR | **+ Stochastic RSI, ADX/DMI, proper Supertrend, VWAP, OBV, Ichimoku, Keltner, RSI divergence, multi-timeframe confirmation, and regime-aware oscillators** |
| **Data / exchange access** | Direct REST API calls | **MCP servers** (Model Context Protocol) wrapping market data, news/sentiment and the exchange; the system is an MCP **client** |
| **Dashboard** | Planned / disabled | **Two tailored web views** — a compact Pi-screen kiosk and a mobile-optimised phone view, both live over your LAN |

> **Status:** runs end-to-end in `paper` mode out of the box (no internet, no keys,
> no money). An independent code review was applied and its findings fixed — see
> `FIXES.md` (35/35 tests). `testnet`/`live` require Binance credentials, deliberate
> opt-in, and pass a startup preflight against the real exchange.

---

## The four v5 upgrades in detail

### 1. Quantized on-device LLM (`llm/quantized_client.py`)
Replaces Ollama with `llama-cpp-python` loading a quantized **GGUF** model directly
(default: Qwen2.5-3B-Instruct Q4_K_M, ~2GB, stored on the NVMe). Benefits: no Docker,
no background server, lower memory, fully offline. Three selectable backends
(`llamacpp` / `ollama` / `stub`) and a **deterministic safe fallback** — if the model
is missing or slow, every LLM call returns a neutral "stand-down" rather than crashing
the trader. On a Pi 5 16GB you can swap up to a 7B Q4 model by editing `LLM_MODEL_PATH`.

### 2. Better indicators (`analysts/indicators.py`, `analysts/technical_analyst.py`)
New indicators listed above, plus two qualitative improvements:
- **Multi-timeframe confirmation** — the higher timeframe must agree, otherwise the
  signal is dampened.
- **Regime-aware oscillators** — RSI/StochRSI extremes are treated as *reversal*
  signals only in ranging markets; in a strong trend (high ADX) they *confirm* the
  trend instead of fighting it. This fixed a real v4-style weakness where "RSI oversold"
  produced buy votes inside clear downtrends.

### 3. MCP servers instead of REST (`mcp_servers/`, `mcp_client/`)
Three FastMCP servers expose tools over stdio:
- `market_data_server` — `get_candles`, `get_ticker`, `get_orderbook`
- `news_sentiment_server` — `get_headlines`, `sentiment` (LLM-backed)
- `exchange_server` — `balance`, `positions`, `place_order` (paper sim or ccxt)

The rest of the system **only** touches `mcp_client.client`, which launches these
servers and calls their tools. If the MCP transport is unavailable, the client
transparently falls back to running the same logic in-process, so the trader never
goes down. Each server's logic lives in a plain `_*_core.py` module so it is unit-testable
and reusable by both the MCP wrapper and the fallback.

### 4. Two dashboards (`dashboard/`)
One FastAPI backend (`dashboard/server.py`) serves:
- `/pi` — high-contrast kiosk for the Pi touchscreen (big equity number, positions,
  signals, health, kill switch).
- `/` — mobile-optimised view for your phone on the same Wi-Fi.

Both read the `status.json` the engine writes each cycle (so the dashboard never
interferes with trading) and can trigger the kill switch. Optional shared-token auth
via `DASHBOARD_TOKEN`.

---

## Architecture

```
MiniSim-v5/
  config/            config.py (all settings), secrets.example.py
  llm/               quantized_client.py        # v5 quantized LLM
  analysts/          indicators.py, technical_analyst.py, other_analysts.py,
                     sentiment_analyst.py, regime_detector.py
  decision/          engine.py                  # regime filter + researchers + CEO
  execution/         risk_manager.py, exit_manager.py, order_executor.py
  records/           decision_log.py, tax_ledger.py
  operations/        kill_switch.py, status_writer.py
  schemas/           validators.py
  mcp_servers/       market_data_server.py, news_sentiment_server.py,
                     exchange_server.py + _*_core.py logic
  mcp_client/        client.py                  # the only data/exchange entry point
  dashboard/         server.py, pi/index.html, mobile/index.html
  scripts/           download_model.sh, install_services.sh, run_all.sh
  tests/             run_tests.py               # 25 tests
  main.py            orchestrator
```

## Quick start

**One-click (Raspberry Pi):** copy the folder to the Pi and double-click
`install.sh` → *Execute in Terminal* (or `bash install.sh`). It installs system
packages, builds the venv, installs deps, downloads the quantized model, runs the
tests, enables auto-start on boot, and creates Desktop shortcuts. Plain-English
walkthrough in `SETUP_GUIDE.md`.

**Manual (developers):**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
bash scripts/download_model.sh        # ~2GB GGUF onto the SSD
python tests/run_tests.py             # expect 40 passed
python main.py --once                 # single cycle
python main.py                        # run forever (paper mode)
python -m dashboard.server            # http://<pi-ip>:8770  and  /pi
```

## The think-cycle
For each coin: MCP feeds → 5 analysts (technical, volume, order-book, on-chain,
sentiment) → regime detector → CEO decision (arithmetic blend + LLM, must agree) →
risk manager (size / veto / approval) → exchange MCP order → decision log + tax ledger.
A faster exit-watch loop manages open positions (profit ladder, trailing stop, stop
loss, max hold) with priority. Default outcome is **STAND_DOWN** unless confidence
clears the configured thresholds.

## Safety (unchanged philosophy from v4)
Kill switch (survives restart), idempotent client-order-IDs, atomic file writes,
exposure caps, regime filter, confidence thresholds, big-trade human approval,
schema validation at boundaries, and an LLM that fails safe to "stand down".

## Honest limits (not exercised in this build)
1. **Real LLM latency on the Pi** — measure `llama.cpp` inference time on your exact
   board; raise `LLM_TIMEOUT_SEC` if needed. The build was tested with the safe
   fallback (model not present in CI), so verify real inference speed.
2. **Live MCP throughput** — the MCP transport is verified working, but sustained
   multi-hour stability on the Pi under load is not yet measured.
3. **Real market-data feeds** — `paper`/`testnet` will try CoinGecko; rate limits and
   outages are handled by falling back to synthetic candles, which are **not** real
   prices. Wire real feeds before trusting signals.
4. **Exchange execution** — `testnet`/`live` route through ccxt; symbol filters, min
   notional and latency need target-environment verification.
5. **No real money has been traded.** Use at your own risk; no warranty.

## License
MIT. v5.0.0 (June 2026).
