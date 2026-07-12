"""
Strategy Router — LLM decides which strategies to deploy based on:
  • current market state (direction, regime, per-coin data)
  • recent performance of each strategy
  • available strategy catalogue

The router is called once per hour (or on regime change), not per trade.
Selected strategy set is persisted to data/strategy_state.json and read
by decision/engine.py for every coin-level decision.

Usage:
    from strategies.router import get_active_strategies, refresh_if_stale
    active = get_active_strategies()        # fast — reads cached state
    active = refresh_if_stale(coin_candles) # may call LLM if >60 min old
"""
from __future__ import annotations
import os, time, json
from strategies import REGISTRY
from common import get_logger, read_json, atomic_write_json as write_json

log = get_logger("strategy_router")

STATE_FILE   = os.path.join(os.path.dirname(__file__), "..", "data", "strategy_state.json")
REFRESH_SECS = 3600   # re-run router every 60 min
MIN_SECS     = 900    # never re-run more frequently than 15 min


# ── Performance summary ───────────────────────────────────────────────────────
def _strategy_performance() -> dict:
    """
    Compute per-strategy stats from FIFO-matched closed trades in the tax
    ledger (entries carry a 'strategy' tag since v7 — the old decision-log
    scan looked for a pnl_usd field that nothing ever wrote).
    Returns: {strategy_name: {trades, wins, pnl_usd, win_rate, recent_n}}
    """
    perf: dict = {name: {"trades": 0, "wins": 0, "pnl_usd": 0.0} for name in REGISTRY}

    try:
        from records.performance import recent_closed_trades
        closed = recent_closed_trades(500)
    except Exception:
        closed = []

    for t in closed:
        strat = t.get("strategy")
        if strat not in perf:
            continue
        pnl_usd = t["qty"] * t["open_price"] * t["pnl_pct"] / 100
        perf[strat]["trades"] += 1
        perf[strat]["pnl_usd"] = round(perf[strat]["pnl_usd"] + pnl_usd, 4)
        if t["pnl_pct"] > 0:
            perf[strat]["wins"] += 1

    for name, p in perf.items():
        t = p["trades"]
        p["win_rate"] = round(p["wins"] / t * 100, 1) if t > 0 else 0.0
        p["recent_n"] = t

    return perf


# ── LLM router call ───────────────────────────────────────────────────────────
def _call_router(market_state: dict, perf: dict) -> dict:
    """Call the LLM to select active strategies. Returns router response dict."""
    from llm.quantized_client import chat_json

    strategies_desc = "\n".join(
        f"  • {s.name} [{'/'.join(s.best_for)}]: {s.description}"
        for s in REGISTRY.values()
    )

    perf_lines = "\n".join(
        f"  {name}: {p['recent_n']} trades, {p['win_rate']:.0f}% wr, "
        f"P&L ${p['pnl_usd']:+.2f}"
        for name, p in perf.items()
    )

    ms = market_state

    # Macro context block
    fng      = ms.get("fear_greed", {})
    funding  = ms.get("funding_rates", {})
    dom      = ms.get("dominance", {})
    tradfi   = ms.get("tradfi", {})
    ls       = ms.get("long_short_ratio", {})

    fng_val  = fng.get("value", 50)
    fng_lbl  = fng.get("label", "Neutral")
    vals     = list(funding.values())
    avg_fund = round(sum(vals) / len(vals) * 100, 4) if vals else None
    btc_dom  = dom.get("btc_dominance", 0.0)
    alt_dom  = dom.get("alt_dominance", 0.0)
    mcap_chg = dom.get("mcap_change_24h_pct", 0.0)
    vix      = tradfi.get("vix",   {}).get("price", 0.0)
    vix_chg  = tradfi.get("vix",   {}).get("change_pct", 0.0)
    dxy      = tradfi.get("dxy",   {}).get("price", 0.0)
    dxy_chg  = tradfi.get("dxy",   {}).get("change_pct", 0.0)
    sp500_chg = tradfi.get("sp500", {}).get("change_pct", 0.0)
    btc_ls   = ls.get("BTC", {})
    btc_lp   = btc_ls.get("long_pct", 0.5) * 100

    macro_lines = [f"  Fear & Greed: {fng_val} — {fng_lbl}"]

    if avg_fund is not None:
        bias = ("long_crowded" if avg_fund > 0.05
                else "short_crowded" if avg_fund < -0.03
                else "neutral")
        macro_lines.append(f"  Avg Funding:  {avg_fund:+.4f}%/8h ({bias})")
        if avg_fund > 0.10:
            macro_lines.append("  ⚠ Funding very high — longs crowded, squeeze risk; prefer SHORT strategies")
        elif avg_fund < -0.05:
            macro_lines.append("  ⚠ Funding very negative — shorts crowded; prefer LONG strategies")

    if btc_dom > 0:
        dom_signal = ("btc_season" if btc_dom >= 58 else "alt_season" if btc_dom <= 48 else "neutral")
        macro_lines.append(f"  BTC dominance: {btc_dom:.1f}%  |  Alt: {alt_dom:.1f}%  "
                           f"|  MCap 24h: {mcap_chg:+.2f}%  ({dom_signal})")
        if dom_signal == "btc_season":
            macro_lines.append("  ⚠ BTC season — alts underperform; prefer BTC or reduce alt longs")
        elif dom_signal == "alt_season":
            macro_lines.append("  ⚠ Alt season — alts outperforming; LONG altcoins favoured")

    if vix > 0:
        macro_lines.append(f"  VIX: {vix:.1f} ({vix_chg:+.2f}%)  |  "
                           f"DXY: {dxy:.2f} ({dxy_chg:+.2f}%)  |  S&P500: {sp500_chg:+.2f}%")
        if vix > 30:
            macro_lines.append("  ⚠ VIX >30 — extreme TradFi fear, risk-off; prefer SHORT or cash")
        elif vix > 25:
            macro_lines.append("  ⚠ VIX elevated — risk-off signal; reduce longs, lower risk_level")
        if dxy_chg > 0.5:
            macro_lines.append("  ⚠ DXY rising sharply — strong crypto headwind; prefer SHORT strategies")
        elif dxy_chg < -0.5:
            macro_lines.append("  ✓ DXY falling — crypto tailwind; LONG strategies favoured")

    if btc_lp > 0:
        macro_lines.append(f"  BTC L/S: {btc_lp:.0f}% long / {100-btc_lp:.0f}% short")
        if btc_lp > 70:
            macro_lines.append("  ⚠ BTC longs very crowded — squeeze risk high; contrarian SHORT signal")
        elif btc_lp < 35:
            macro_lines.append("  ⚠ BTC shorts very crowded — short squeeze risk; contrarian LONG signal")

    if fng_val <= 20:
        macro_lines.append("  ⚠ Extreme Fear — contrarian buy signal; favour LONG or bounce strategies")
    elif fng_val >= 80:
        macro_lines.append("  ⚠ Extreme Greed — contrarian sell signal; favour SHORT or scalp strategies")

    macro_block = "Macro context:\n" + "\n".join(macro_lines)

    per_coin_lines = "\n".join(
        f"  {coin}: {d['direction']} | regime-proxy ADX={d.get('adx','?')} | "
        f"7d={d.get('ret_7d',0):+.1f}%"
        for coin, d in ms.get("per_coin", {}).items()
    )

    from config import config as cfg
    position_usd = getattr(cfg, "POSITION_SIZE_USD", 100)
    max_exp_usd  = getattr(cfg, "MAX_EXPOSURE_USD", 500)
    account_note = ""
    if position_usd <= 25 or max_exp_usd <= 200:
        account_note = (
            f"\nSMALL ACCOUNT NOTE: position size is ${position_usd}, max exposure ${max_exp_usd}. "
            f"Prefer capital-preservation strategies (MicroScalp, VolBreakout, RangeScalp) with "
            f"tight stop-losses. Avoid stacking more than 2 simultaneous positions. "
            f"Keep risk_level ≤ 0.8 unless the setup is extremely clean."
        )

    sysmsg = (
        "You are the strategy director of an automated crypto trading desk. "
        "Your job is to select 1-3 trading strategies from the available catalogue "
        "that best match current market conditions. Rules:\n"
        "1. Choose strategies whose 'best_for' list matches the current direction/regime.\n"
        "2. Do NOT simultaneously select both TrendShort and MomentumLong — they are opposite bets.\n"
        "3. Do NOT select OversoldBounce and MomentumLong together — conflicting.\n"
        "4. Prefer strategies with recent positive win rates; avoid those bleeding P&L.\n"
        "5. In volatile/uncertain markets, select at most 1 strategy and keep risk_level ≤ 0.8.\n"
        "6. If no strategy fits well, return only RangeScalp with risk_level 0.5.\n"
        "7. Be conservative — fewer, better-fit strategies beat trying to cover all bases."
        + account_note
    )

    user = f"""Market state:
  Direction:  {ms['direction']} ({ms['bear_coins']} bear / {ms['bull_coins']} bull / {ms['neutral_coins']} neutral out of {ms['total_coins']} coins)
  Regime:     {ms['regime']}
  BTC 7d:     {ms['btc_7d']:+.1f}%  |  BTC 24h: {ms['btc_24h']:+.1f}%
  Market avg 7d: {ms['avg_7d']:+.1f}%  |  BTC direction: {ms['btc_direction']}

{macro_block}

Per-coin direction:
{per_coin_lines}

Strategy performance (all-time since deployment):
{perf_lines}

Available strategies:
{strategies_desc}

Respond with JSON containing:
  active_strategies: list of strategy names to activate (1-3, must exist in catalogue)
  reasoning:         one-sentence explanation
  risk_level:        position-sizing multiplier 0.5-2.0 (1.0 = normal $100/trade)
"""

    schema = {
        "type": "object",
        "required": ["active_strategies", "reasoning", "risk_level"],
        "properties": {
            "active_strategies": {
                "type": "array",
                "items": {"type": "string", "enum": list(REGISTRY.keys())},
                "minItems": 1, "maxItems": 3,
            },
            "reasoning":  {"type": "string"},
            "risk_level": {"type": "number", "minimum": 0.5, "maximum": 2.0},
        },
    }

    try:
        result = chat_json(sysmsg, user, schema=schema)
        # Validate returned names are real (None/malformed output → default)
        valid = [n for n in (result.get("active_strategies") or []) if n in REGISTRY]
        if not valid:
            valid = ["RangeScalp"]
        result["active_strategies"] = valid
        return result
    except Exception as e:
        log.warning(f"Router LLM call failed ({e}) — falling back to RangeScalp")
        return {
            "active_strategies": ["RangeScalp"],
            "reasoning":  f"LLM unavailable — defaulting to conservative range strategy ({e})",
            "risk_level": 0.5,
        }


# ── Public API ────────────────────────────────────────────────────────────────
def get_active_strategies() -> list:
    """Return currently active Strategy instances (reads cached state)."""
    state = read_json(STATE_FILE, {})
    names = state.get("active_strategies", ["RangeScalp"])
    return [REGISTRY[n] for n in names if n in REGISTRY]


def get_risk_level() -> float:
    """Return the current position-sizing multiplier (default 1.0)."""
    state = read_json(STATE_FILE, {})
    return float(state.get("risk_level", 1.0))


def refresh_if_stale(coin_candles: dict | None = None, force: bool = False) -> list:
    """
    Re-run the LLM router if the last selection is >REFRESH_SECS old.
    coin_candles: {coin: [candle, ...]} — if None, skip market_state detection.
    Returns active Strategy instances.
    """
    state    = read_json(STATE_FILE, {})
    last_run = state.get("last_run", 0)
    age      = time.time() - last_run

    if not force and age < MIN_SECS:
        return get_active_strategies()

    if not force and age < REFRESH_SECS:
        return get_active_strategies()

    log.info("Strategy router: refreshing …")

    market_state: dict = {}
    if coin_candles:
        try:
            from strategies import market_state as ms_mod
            market_state = ms_mod.detect(coin_candles)
            log.info(f"Market state: {market_state['direction']} "
                     f"({market_state['bear_coins']}B/{market_state['bull_coins']}L/"
                     f"{market_state['neutral_coins']}N)")
        except Exception as e:
            log.warning(f"market_state.detect failed: {e}")
            market_state = {
                "direction": "neutral", "regime": "unknown",
                "bear_coins": 0, "bull_coins": 0, "neutral_coins": 0,
                "total_coins": 0, "bear_pct": 0, "bull_pct": 0,
                "avg_7d": 0, "avg_24h": 0, "btc_7d": 0, "btc_24h": 0,
                "btc_direction": "neutral", "per_coin": {},
            }
    else:
        # Use last-known state if available
        market_state = state.get("last_market_state", {
            "direction": "neutral", "regime": "unknown",
            "bear_coins": 0, "bull_coins": 0, "neutral_coins": 0,
            "total_coins": 0, "bear_pct": 0, "bull_pct": 0,
            "avg_7d": 0, "avg_24h": 0, "btc_7d": 0, "btc_24h": 0,
            "btc_direction": "neutral", "per_coin": {},
        })

    # Attach latest macro data to market_state for the LLM prompt
    try:
        from mcp_client.client import get_client as _get_mc
        _mc = _get_mc()
        market_state["fear_greed"]       = _mc.fear_greed()
        market_state["funding_rates"]    = _mc.funding_rates()
        market_state["dominance"]        = _mc.dominance()
        market_state["long_short_ratio"] = _mc.long_short_ratio()
        market_state["tradfi"]           = _mc.tradfi()
    except Exception as _me:
        log.debug("Router: macro fetch skipped (%s)", _me)

    perf   = _strategy_performance()
    result = _call_router(market_state, perf)

    new_state = {
        "active_strategies":  result["active_strategies"],
        "reasoning":          result.get("reasoning", ""),
        "risk_level":         result.get("risk_level", 1.0),
        "last_run":           time.time(),
        "last_market_state":  market_state,
        "last_perf":          perf,
    }
    write_json(STATE_FILE, new_state)
    log.info(f"Active strategies: {result['active_strategies']} "
             f"(risk×{result.get('risk_level',1.0)}) — {result.get('reasoning','')}")

    return [REGISTRY[n] for n in result["active_strategies"] if n in REGISTRY]


def current_state_summary() -> str:
    """Human-readable summary of current router state (for dashboard/logs)."""
    state = read_json(STATE_FILE, {})
    if not state:
        return "Strategy router: no state yet"
    ms   = state.get("last_market_state", {})
    names = state.get("active_strategies", [])
    rl   = state.get("risk_level", 1.0)
    age  = int((time.time() - state.get("last_run", 0)) / 60)
    return (f"[{ms.get('direction','?').upper()} {ms.get('regime','?')}]  "
            f"Active: {', '.join(names)}  risk×{rl}  ({age}m ago)")
