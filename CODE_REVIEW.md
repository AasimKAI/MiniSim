# MiniSim v5 — Independent Code Review (Fable 5)

> RESOLUTION: the findings below were addressed in a follow-up pass — see `FIXES.md`. Test suite now 35/35.

Reviewer: a fresh Claude Fable 5 instance, reviewing the code it did not write.
Findings verified by executing the code in a sandbox where possible.

## Verdict
**Not ship-ready even for paper mode** as-is. The architecture is sound (MCP wiring
works, in-process fallback is a good safety net, kill switch persists, atomic writes
used), but the execution/exit/accounting layer was never exercised across multiple
cycles, and the testnet/live path is wired to paper-mode state. Treat the current
build as a **fixture-mode demo**, not a trading system, until the items below are fixed.

---

## CRITICAL
- **C1 — Exit ladder state never persisted.** `targets_taken` / `peak_pnl` are read by
  `exit_manager.evaluate()` but nothing writes them back. Result: the take-profit T1
  re-fires every 10s (selling 33% of the remainder forever), and the trailing stop is
  dead code that can never trigger. *(verified)*
- **C2 — testnet/live read paper state.** `balance()`/`positions()` always load the
  paper wallet even in testnet/live, so risk limits see ~$0 exposure (→ unlimited
  buying) and the exit loop sees no positions (→ no stop-loss ever runs on real money).
- **C3 — Fallback re-executes orders on timeout.** `MCPClient.call()` falls back to
  in-process execution on *any* transport error, including a `place_order` timeout
  that may have already filled → double execution. `_ccxt_order` has no local
  idempotency check.
- **C4 — Paper mode runs on synthetic prices.** `real_candles` requests CoinGecko
  `ohlc?days=1` (~48 rows) but gates on `>=60`, so it ALWAYS returns None and falls
  back to synthetic sine-wave prices — while still firing a dead HTTP call (~6+ per
  10s → 429s). Every paper signal/PnL is fiction with no operator indication. *(verified)*

## HIGH
- **H1 — Single-threaded; llama.cpp call has no timeout.** ~10 LLM calls per cycle
  block `run_exits`, so a stop-loss can be missed while the CEO writes narrative.
  `LLM_TIMEOUT_SEC` only applies to the ollama path. Fallback can load the GGUF twice.
- **H2 — Dashboard auth unusable + resume bypass.** `DASHBOARD_TOKEN` defaults to ""
  (no-op); the HTML never sends a token, so enabling it breaks the UI. Unauthenticated
  POST `/api/resume` re-enables trading after a kill (CSRF/DNS-rebind reachable on LAN).
- **H3 — Stored XSS from LLM output.** Unvalidated CEO `verdict`/`reasoning` flows into
  `decision_log.jsonl` → `/api/decisions` → `innerHTML` on the mobile dashboard. A
  hostile headline could make the model emit `<img onerror=fetch('/api/resume'...)>`.
- **H4 — ENTRY_SELL = naked spot short.** On a spot exchange a bearish ENTRY_SELL sells
  base you may not own; no short accounting exists. Paper mode hides it; testnet/live
  would attempt it.
- **H5 — Exit/entry race on the wallet.** Whole-file read-modify-write with no per-coin
  lock; rare today (single process) but live once H1 is fixed with threads.

## MEDIUM
M1 single-item MCP list collapses to a dict *(verified)*; M2 Supertrend off-by-one /
not a true flip algorithm; M3 StochRSI k==d (no smoothing) *(verified)*; M4 RSI
divergence uses absolute min, not swing pivots → false signals at full weight; M5
exposure cap can overshoot by one position; M6 kill switch not re-checked per order;
M7 tax ledger records decision-time price, not fill price.

## LOW
L1 stdio servers can leak on SIGKILL under `Restart=always`; L2 EMA/MACD alignment on
uneven series untested; L3 "24h change" actually 2h (uses `c[-24]` on 5-min candles);
L4 dashboard can briefly render `{}`; L5 confidence double-counts — arith score 0.86+
trades with `agree=False`, contradicting the "require agreement" comment.

## Test-suite blind spots
No test calls `evaluate` twice (C1 invisible); no multi-cycle/state-persistence test;
no real MCP transport test (only the fallback path); no testnet/live guard test; no
dashboard/auth/XSS test; no kill-switch-mid-cycle test; the harness `synth()` builds
mismatched OHLC from separate reseeded calls.

---

### Suggested fix order
1. C4 + C1 (paper results are meaningless until these are fixed)
2. H3 + H2 (LAN-exposed dashboard, kill-switch bypass)
3. Then, before any testnet use: C2, C3, H1, H4, H5.
