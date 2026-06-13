"""
MiniSim v5 — system orchestrator.

One think-cycle per coin:
  MCP feeds -> analysts -> regime -> CEO decision -> risk -> execute -> log
Plus a fast exit-watch over open positions, and a status file for the dashboards.

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

log = get_logger("main")


def analyse_coin(mcp, coin):
    candles = mcp.candles(coin, 200)
    ticker = mcp.ticker(coin)
    ob = mcp.orderbook(coin)
    price = ticker["price"]

    verdicts = [
        tech.analyze(coin, candles),
        volume_analyst(coin, candles),
        order_book_analyst(coin, ob),
        on_chain_analyst(coin, ticker),
        sentiment_analyst(coin, mcp),
    ]
    regime = regime_detector.detect(candles)["regime"]
    decision = engine.decide(coin, verdicts, regime)
    return decision, price, verdicts, regime


def run_cycle(mcp):
    if kill_switch.is_active():
        log.warning("KILL SWITCH active — skipping trading this cycle")
        return "kill-switch"
    regime_seen = "—"
    for coin in config.TRACKED_COINS:
        try:
            decision, price, verdicts, regime = analyse_coin(mcp, coin)
            regime_seen = regime
            rec = decision_log.log_decision(
                coin, decision["action"], decision["confidence"],
                decision["reasoning"],
                extra={"analysts": [{"a": v["analyst"], "v": v["verdict"],
                                     "c": v["confidence"]} for v in verdicts]})
            log.info("%s -> %s (conf %.2f)", coin, decision["action"], decision["confidence"])

            if decision["action"] in ("ENTRY_BUY", "ENTRY_SELL"):
                bal = mcp.balance()
                pos = mcp.positions()
                qty, verdict, why = risk_manager.check(coin, decision["action"], price, bal, pos)
                if qty <= 0:
                    log.info("  risk veto: %s", why)
                    continue
                if verdict == "hold_for_approval":
                    log.info("  big trade — needs human approval (skipped in auto run): %s", why)
                    continue
                side = "BUY" if decision["action"] == "ENTRY_BUY" else "SELL"
                if side == "SELL":      # spot: ENTRY_SELL only reduces an existing long
                    if not any(p["coin"] == coin for p in pos):
                        continue
                if kill_switch.is_active():     # re-check immediately before placing
                    log.warning("  kill switch tripped mid-cycle — aborting orders")
                    break
                fill = order_executor.execute(mcp, rec["signal_id"], coin, side, qty, "entry")
                if fill.get("status") == "filled":
                    tax_ledger.record_trade(coin, side,
                                            fill.get("quantity", qty), fill.get("price", price))
        except Exception as e:  # noqa
            log.exception("coin %s failed: %s", coin, e)
    return regime_seen


def run_exits(mcp):
    if kill_switch.is_active():
        return
    for p in mcp.positions():
        coin = p["coin"]
        price = p["current_price"]
        should, frac, reason, meta = exit_manager.evaluate(p, price)
        # always persist the updated trailing-stop peak
        try:
            mcp.update_meta(coin, peak_pnl=meta.get("peak_pnl"))
        except Exception:  # noqa
            pass
        if not should:
            continue
        if kill_switch.is_active():     # re-check right before placing the order
            log.warning("kill switch tripped — aborting exit orders")
            break
        lvl = meta.get("target_level")
        qty = round(p["quantity"] * frac, 6)
        log.info("EXIT %s frac %.2f — %s", coin, frac, reason)
        sig = decision_log.log_decision(coin, "EXIT", 1.0, reason)
        trigger = f"tp{lvl}" if lvl is not None else "exit"
        fill = order_executor.execute(mcp, sig["signal_id"], coin, "SELL", qty, trigger)
        if fill.get("status") == "filled":
            # mark the TP level taken ONLY after a real fill, so a timeout/
            # rejection doesn't permanently skip an unsold tranche.
            if lvl is not None:
                mcp.update_meta(coin, add_target=lvl)
            tax_ledger.record_trade(coin, "SELL",
                                    fill.get("quantity", qty), fill.get("price", price))
        else:
            log.warning("EXIT %s not filled (%s) — will retry next pass (sells are "
                        "clamped to holdings, so re-try is bounded)", coin, fill.get("status"))


def preflight(mcp):
    """Safety gate before trading.
    1) Assert the exchange server is actually running in OUR configured mode
       (catches the MCP subprocess defaulting to paper while we think we're on
       testnet/live).
    2) In testnet/live, refuse to start unless we can read the REAL exchange."""
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run a single cycle then exit")
    args = ap.parse_args()

    log.info("MiniSim v%s starting in %s mode", config.VERSION, config.MODE)
    mcp = get_client()
    log.info("MCP transport: %s", mcp.status())
    preflight(mcp)

    if args.once:
        run_exits(mcp)
        regime = run_cycle(mcp)
        status_writer.write_status(mcp, regime=regime, last_cycle="#1")
        log.info("single cycle complete (--once)")
        return

    import threading
    stop = threading.Event()
    shared = {"regime": "—", "cycle": 0}

    def exit_loop():
        """Runs on its OWN thread so stop-losses are checked every
        EXIT_WATCH_INTERVAL even while the think-cycle is busy with the LLM."""
        while not stop.is_set():
            try:
                run_exits(mcp)
                status_writer.write_status(mcp, regime=shared["regime"],
                                           last_cycle=f"#{shared['cycle']}")
            except Exception:  # noqa
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
