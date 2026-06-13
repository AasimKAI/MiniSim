# MiniSim v5 — Review Fixes Log

An independent code review (see `CODE_REVIEW.md`) flagged issues in the first
v5 build. This log records what was changed in response. All fixes are covered
by regression tests in `tests/run_tests.py` (now 35 tests, all passing).

## Critical
- **C1 — broken exit ladder / dead trailing stop.** Take-profit progress
  (`targets_taken`) and the trailing-stop high-water mark (`peak_pnl`) are now
  persisted in `state/position_meta.json` via a new `update_meta` exchange tool.
  Each take-profit level fires exactly once; the trailing stop now triggers on a
  pullback from the peak. *(tests: "C1 T1 fires once", "C1 T1 does NOT re-fire",
  "trailing stop fires on pullback")*
- **C2 — testnet/live ran on phantom paper state.** `balance()`/`positions()`
  now use real ccxt data in testnet/live (`_ccxt_balance`, `_ccxt_positions`),
  and `main.preflight()` refuses to start if the real exchange can't be read.
  *(test: "preflight blocks testnet without exchange")*
- **C3 — double-execution on timeout.** `place_order` is in the MCP client's
  `_NON_RETRYABLE` set: on a transport error it returns `status:"unknown"` and is
  never re-executed. `_ccxt_order` has no internal retry.
- **C4 — paper ran on fake prices silently.** Market data now uses CoinGecko
  `market_chart` (enough points), caches quotes (`MARKET_CACHE_SEC`) to stop API
  spam, and labels the source (`coingecko` vs `synthetic(fallback)`), surfaced in
  `status.json` and on both dashboards. *(test: "data source is labelled")*

## High
- **H1 — stop-loss could stall behind the LLM.** The exit watch runs on its own
  thread; the LLM has a hard wall-clock timeout on every backend (abandons a slow
  model and falls back safely); the model loads in one process only (sentiment
  scoring moved out of the news server). Also fails fast when the model file is
  absent. *(verified: 30s hang returns in ~2s)*
- **H2 — dashboard control was unprotected.** `/api/kill` and `/api/resume` now
  require a per-process CSRF token (injected into the page), pass an Origin check,
  and a Host allow-list (anti DNS-rebinding). Read endpoints take the optional
  shared token. *(verified: 4 attack vectors return 403, legit control 200)*
- **H3 — stored XSS from LLM output.** Dashboards HTML-escape all dynamic values;
  the CEO/sentiment verdicts are validated to the allowed enum before entering any
  record. *(test: "hostile LLM verdict sanitised to neutral")*
- **H4 — naked spot short.** Sells are clamped to the held base quantity on both
  the paper simulator and ccxt.
- **H5 — wallet write race.** All wallet/meta mutations run under a cross-process
  file lock (`fcntl`), so the exit thread and think-cycle can't corrupt state.

## Medium / Low
- **M1** MCP client uses an explicit `_LIST_TOOLS` set (one-element lists stay
  lists). *(test)* · **M2** Supertrend rewritten with proper band carry-over. ·
  **M3** StochRSI now has real %K/%D smoothing (k≠d). *(test)* · **M4** divergence
  uses confirmed swing pivots. *(test)* · **M5** hard post-trade exposure cap.
  *(test)* · **M6** kill switch re-checked immediately before every order. ·
  **M7** tax ledger records the actual fill price/qty, not the decision-time
  snapshot. · **L3** 24h change computed by timestamp, not a fixed index. · Also:
  regime-aware oscillators (RSI/StochRSI confirm trends instead of fighting them).

## Still honest about limits
- Real CoinGecko latency / rate limits and real `llama.cpp` inference speed must
  be measured on your actual Pi (the sandbox can't reach the network or load the
  model). Per-candle volume from the public feed is approximate, so OBV/VWAP are
  best-effort; price-based indicators are real.
- testnet/live ccxt order sizing, symbol filters and min-notional still need
  verification against the live test exchange before relying on them.
- No real money has been traded. Use at your own risk; no warranty.

---

# Round 2 — Independent Re-review Fixes

A second independent review verified round 1 and found new issues (mostly
introduced by the fixes). All now fixed; test suite is 40/40.

- **NEW-1 (CRITICAL) — MCP subprocesses didn't inherit the run mode.** The SDK
  strips the child environment, so in testnet/live the exchange server silently
  defaulted to the PAPER simulator (re-opening C2), and preflight passed on the
  fake $10k. Fixed: the client now forwards `MINISIM_*` env (and an explicit
  `MINISIM_MODE`) to every server subprocess, and `preflight()` asserts the
  exchange server's reported mode matches `config.MODE` — aborting on mismatch.
  *(test: "NEW-1 preflight blocks mode mismatch"; verified subprocess now reports
  testnet)*
- **NEW-3 (HIGH) — LLM timeout freed the caller but the single worker stayed
  stuck**, so later calls queued behind abandoned inference and silently all fell
  to neutral. Fixed with a single-flight, time-boxed gate: if the one worker is
  busy or a call exceeds the budget, it returns the safe fallback immediately —
  no queue, no thread pile-up. *(test: "NEW-3 busy model returns immediate
  fallback"; verified 3 concurrent calls, none stalled)*
- **NEW-2 (MEDIUM) — take-profit marked taken before the order**, so a
  timeout/rejection skipped that tranche forever (0% sold). Fixed: the level is
  marked taken ONLY after a confirmed fill; an unfilled exit logs and retries
  (sells are clamped to holdings, so retries are bounded). *(tests for both
  filled and failed cases)*
- **NEW-4 (LOW) — cache could return a shorter slice than requested.** Fixed: the
  cache is only reused when it holds at least the requested length, else it
  refetches; synthetic series are padded to >= the request. *(test)*
- Cleanup: removed dead `_news_core.sentiment()` (model-loading code no longer
  wired as a tool, keeping the "one process loads the model" guarantee).

Remaining low/informational items (orphaned meta keys self-heal; `unknown` order
outcomes could be logged for reconciliation) are noted for a future pass and do
not affect paper-mode correctness.
