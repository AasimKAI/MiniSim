"""
MiniSim v5 — system orchestrator.

One think-cycle per coin:
  MCP feeds -> analysts -> regime -> strategy signals -> CEO decision -> risk -> execute -> log

Strategy router (LLM) runs once per hour and selects which named strategies
are active based on market direction + recent strategy performance.
Active strategy signals feed into the CEO decision alongside analyst verdicts.
When a position opens, the chosen strategy's SL/TP/trail params are stored on
the position so exit_manager can use them instead of config defaults.

Run:
  python main.py                 # runs forever (paper mode by default)
  python main.py --once          # single cycle then exit (handy for testing)
"""
import sys, time, argparse
from config import config
from common import get_logger
from mcp_client.client import get_client
from analysts import technical_analyst as tech
from analysts.other_analysts import volume_analyst, order_book_analyst, on_chain_analyst
from analysts.sentiment_analyst import sentiment_analyst
from analysts import regime_detector
from decision import engine
from execution import risk_manager, exit_manager, order_executor
from records import decision_log, tax_ledger
from operations import kill_switch, status_writer
from strategies import REGISTRY
from strategies.router import (
    get_active_strategies,
    refresh_if_stale  as router_refresh,
    current_state_summary as router_summary,
)

log = get_logger("main")


def _strat_meta(strategy_name: str) -> dict:
    """
    Build the position-metadata dict for a strategy so exit_manager
    can use strategy-specific SL/TP/trail instead of config defaults.
    Returns {} if strategy_name is unknown.
    """
    inst = REGISTRY.get(strategy_name)
    if not inst:
        return {}
    p = inst.params
    return {
        "strat_name":      strategy_name,
        "strat_sl":        round(p.sl_pct    * 100, 3),   # fraction → percent
        "strat_tp1":       round(p.tp1_pct   * 100, 3),
        "strat_tp2":       round(p.tp2_pct   * 100, 3),
        "strat_tp3":       round(p.tp3_pct   * 100, 3),
        "strat_frac1":     p.tp1_frac,
        "strat_frac2":     p.tp2_frac,
        "strat_frac3":     p.tp3_frac,
        "strat_trail":     round(p.trail_pct * 100, 3),
        "strat_trail_min": round(p.tp1_pct   * 100 / 2, 3),  # half of TP1
        "strat_max_hold_h": round(p.max_hold_candles * 0.25, 1),  # 15-min candles → hours
    }


def analyse_coin(mcp, coin, active_strategies=None):
    """
    Run the full analysis pipeline for one coin.

    Returns (decision, price, verdicts, regime, candles).
    Candles are returned so run_cycle can accumulate them for the router.
    """
    candles = mcp.candles(coin, 300)   # 300 × 15 min = 75 h, enough for EMA200 + all indicators
    ticker  = mcp.ticker(coin)
    ob      = mcp.orderbook(coin)
    price   = ticker["price"]

    verdicts = [
        tech.analyze(coin, candles),
        volume_analyst(coin, candles),
        order_book_analyst(coin, ob),
        on_chain_analyst(coin, ticker),
        sentiment_analyst(coin, mcp),
    ]
    regime = regime_detector.detect(candles)["regime"]

    # ── Strategy signals ───────────────────────────────────────────────────────
    strategy_signals = []
    if active_strategies:
        for strat in active_strategies:
            try:
                sig = strat.signal(coin, candles, regime, ticker)
                strategy_signals.append({
                    "action":     sig.action,
                    "confidence": sig.confidence,
                    "reason":     sig.reason,
                    "strategy":   sig.strategy,
                })
            except Exception as e:
                log.debug("Strategy %s signal error for %s: %s", strat.name, coin, e)

    decision = engine.decide(coin, verdicts, regime,
                              strategy_signals=strategy_signals or None)
    return decision, price, verdicts, regime, candles


def run_cycle(mcp):
    if kill_switch.is_active():
        log.warning("KILL SWITCH active — skipping trading this cycle")
        return "kill-switch"

    # Fast read from cache — no LLM call here (router refreshes at end of cycle)
    active_strategies = get_active_strategies()
    if active_strategies:
        log.info("Active strategies: %s", [s.name for s in active_strategies])
    else:
        log.info("No active strategies (router not yet initialised — using analyst-only mode)")

    regime_seen  = "—"
    cycle_candles = {}

    for coin in config.TRACKED_COINS:
        try:
            decision, price, verdicts, regime, candles = analyse_coin(
                mcp, coin, active_strategies)
            cycle_candles[coin] = candles
            regime_seen = regime

            chosen_strategy = decision.get("strategy")
            log.info("%s → %s (conf %.2f) [%s]",
                     coin, decision["action"], decision["confidence"],
                     chosen_strategy or "no strategy")

            rec = decision_log.log_decision(
                coin, decision["action"], decision["confidence"],
                decision["reasoning"],
                extra={
                    "strategy": chosen_strategy,
                    "analysts": [{"a": v["analyst"], "v": v["verdict"],
                                  "c": v["confidence"]} for v in verdicts],
                })

            if decision["action"] not in ("ENTRY_BUY", "ENTRY_SELL"):
                continue

            # ── Pre-entry checks ──────────────────────────────────────────────
            bal = mcp.balance()
            pos = mcp.positions()

            has_long  = any(p["coin"] == coin and p.get("side", "LONG") == "LONG"  for p in pos)
            has_short = any(p["coin"] == coin and p.get("side") == "SHORT" for p in pos)

            if decision["action"] == "ENTRY_BUY" and has_short:
                short = next(p for p in pos if p["coin"] == coin and p.get("side") == "SHORT")
                log.info("  bullish flip on %s — covering short (%.6f @ %.4f)",
                         coin, short["quantity"], short["entry_price"])
                cover_sig = decision_log.log_decision(
                    coin, "COVER", 1.0, "bullish flip: covering short position")
                cover_fill = order_executor.execute(
                    mcp, cover_sig["signal_id"], coin, "COVER", short["quantity"], "cover")
                if cover_fill.get("status") == "filled":
                    tax_ledger.record_trade(
                        coin, "COVER",
                        cover_fill.get("quantity", short["quantity"]),
                        cover_fill.get("price", price))
                continue   # long entry on the next cycle once short is cleared

            if decision["action"] == "ENTRY_SELL" and has_short:
                log.info("  already short %s — skipping duplicate", coin)
                continue

            # Determine order side
            if decision["action"] == "ENTRY_BUY":
                order_side = "BUY"
            elif has_long:
                order_side = "SELL"    # close existing long
            else:
                order_side = "SHORT"   # open synthetic short

            qty, verdict, why = risk_manager.check(
                coin, decision["action"], price, bal, pos)
            if qty <= 0:
                log.info("  risk veto: %s", why)
                continue
            if verdict == "hold_for_approval":
                log.info("  big trade — needs human approval (skipped in auto run): %s", why)
                continue

            if kill_switch.is_active():
                log.warning("  kill switch tripped mid-cycle — aborting orders")
                break

            fill = order_executor.execute(
                mcp, rec["signal_id"], coin, order_side, qty, "entry")

            if fill.get("status") == "filled":
                tax_ledger.record_trade(
                    coin, order_side,
                    fill.get("quantity", qty), fill.get("price", price))

                # Store strategy exit params on the position so exit_manager can use them
                if chosen_strategy and order_side in ("BUY", "SHORT"):
                    try:
                        mcp.update_meta(coin, **_strat_meta(chosen_strategy))
                        log.info("  strategy params stored on position: %s", chosen_strategy)
                    except Exception as e:
                        log.warning("  could not store strategy meta: %s", e)

        except Exception as e:
            log.exception("coin %s failed: %s", coin, e)

    # ── Refresh strategy router at end of cycle ───────────────────────────────
    # This is the only place the router LLM is called. It's a no-op if the
    # last selection is <60 min old. Passing cycle_candles lets it detect
    # the current market direction from fresh data.
    try:
        router_refresh(cycle_candles)
        log.info("Router: %s", router_summary())
    except Exception as e:
        log.warning("Strategy router refresh failed: %s", e)

    return regime_seen


def run_exits(mcp):
    if kill_switch.is_active():
        return
    for p in mcp.positions():
        coin  = p["coin"]
        price = p["current_price"]
        should, frac, reason, meta = exit_manager.evaluate(p, price)
        # always persist the updated trailing-stop peak
        try:
            mcp.update_meta(coin, peak_pnl=meta.get("peak_pnl"))
        except Exception:
            pass
        if not should:
            continue
        if kill_switch.is_active():
            log.warning("kill switch tripped — aborting exit orders")
            break
        lvl  = meta.get("target_level")
        qty  = round(p["quantity"] * frac, 6)
        if frac < 1.0 and qty * price < config.MIN_ORDER_NOTIONAL_USD:
            qty = round(p["quantity"], 6)
            lvl = None
        log.info("EXIT %s frac %.2f — %s [%s]",
                 coin, frac, reason, p.get("strat_name", "config-defaults"))
        sig = decision_log.log_decision(coin, "EXIT", 1.0, reason)
        trigger   = f"tp{lvl}" if lvl is not None else "exit"
        exit_side = "COVER" if p.get("side") == "SHORT" else "SELL"
        fill = order_executor.execute(mcp, sig["signal_id"], coin, exit_side, qty, trigger)
        if fill.get("status") == "filled":
            if lvl is not None:
                mcp.update_meta(coin, add_target=lvl)
            tax_ledger.record_trade(coin, "SELL",
                                    fill.get("quantity", qty), fill.get("price", price))
        else:
            log.warning("EXIT %s not filled (%s) — will retry next pass",
                        coin, fill.get("status"))


def preflight(mcp):
    bal = mcp.balance()
    seen_mode = bal.get("mode") if isinstance(bal, dict) else None
    if seen_mode and seen_mode != config.MODE:
        raise SystemExit(
            f"REFUSING TO START: exchange server reports mode '{seen_mode}' but "
            f"config.MODE is '{config.MODE}'. The MCP subprocess did not receive "
            "the right mode — aborting rather than trading on the wrong backend.")
    if config.MODE not in ("testnet", "live"):
        return
    if not isinstance(bal, dict) or bal.get("error") or bal.get("equity_usd") is None:
        raise SystemExit(
            f"REFUSING TO START in {config.MODE} mode: cannot read real exchange "
            f"balance ({bal.get('error') if isinstance(bal, dict) else bal}). "
            "Check config/secrets.py credentials and connectivity.")
    if config.MODE == "live":
        log.warning("LIVE MODE: real money. Equity seen: $%s", bal.get("equity_usd"))


def _warmup_llm():
    if config.LLM_BACKEND != "llamacpp":
        return
    import os
    if not os.path.exists(os.path.abspath(config.LLM_MODEL_PATH)):
        log.warning("LLM model not found — sentiment will use safe fallback")
        return
    log.info("Warming up LLM (loading model into memory)…")
    from llm.quantized_client import chat_json
    result = chat_json("You are a warmup ping.",
                       "Reply with: {\"verdict\":\"neutral\",\"confidence\":0,\"reasoning\":\"ready\"}")
    backend = result.get("_backend", "unknown")
    latency = result.get("_latency_sec", 0)
    log.info("LLM ready — backend=%s load+inference took %.1fs", backend, latency)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run a single cycle then exit")
    args = ap.parse_args()

    log.info("MiniSim v%s starting in %s mode", config.VERSION, config.MODE)
    mcp = get_client()
    log.info("MCP transport: %s", mcp.status())
    preflight(mcp)
    _warmup_llm()

    log.info("Strategy registry: %s", list(REGISTRY.keys()))
    log.info("Router state on startup: %s", router_summary())

    if args.once:
        run_exits(mcp)
        regime = run_cycle(mcp)
        status_writer.write_status(mcp, regime=regime, last_cycle="#1")
        log.info("single cycle complete (--once)")
        return

    import threading
    stop   = threading.Event()
    shared = {"regime": "—", "cycle": 0}

    def exit_loop():
        while not stop.is_set():
            try:
                run_exits(mcp)
                status_writer.write_status(mcp, regime=shared["regime"],
                                           last_cycle=f"#{shared['cycle']}")
            except Exception:
                log.exception("exit-watch error")
            stop.wait(config.EXIT_WATCH_INTERVAL)

    t = threading.Thread(target=exit_loop, daemon=True, name="exit-watch")
    t.start()
    log.info("exit-watch thread started — independent of the think-cycle")

    try:
        while not stop.is_set():
            shared["cycle"] += 1
            shared["regime"] = run_cycle(mcp)
            status_writer.write_status(mcp, regime=shared["regime"],
                                       last_cycle=f"#{shared['cycle']}")
            stop.wait(config.COLLECTOR_INTERVAL)
    except KeyboardInterrupt:
        log.info("shutting down…")
    finally:
        stop.set()


if __name__ == "__main__":
    main()
