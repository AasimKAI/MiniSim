"""
Backtest performance metrics.
Calculated from a list of closed trade records.
"""

import math
from datetime import datetime, timezone
from typing import Dict, List, Optional


def calculate(trades: List[Dict], initial_equity: float = 10_000.0) -> Dict:
    """
    Compute performance metrics from a list of closed trade records.

    Each trade record must have: entry_price, exit_price, quantity, side, entry_ts, exit_ts.
    Returns a metrics dict ready for dashboard display and SQLite indexing.
    """
    if not trades:
        return _empty(initial_equity)

    closed = [t for t in trades if t.get("status") == "closed"]
    if not closed:
        return _empty(initial_equity)

    # Build equity curve (daily buckets)
    equity_curve = _build_equity_curve(closed, initial_equity)

    total_return_pct = (
        (equity_curve[-1]["equity"] - initial_equity) / initial_equity * 100
        if equity_curve
        else 0.0
    )

    max_drawdown_pct = _max_drawdown(equity_curve)
    sharpe = _sharpe(equity_curve)
    wins = sum(1 for t in closed if t.get("pnl_usd", 0) > 0)
    win_rate = wins / len(closed) if closed else 0.0
    total_pnl = sum(t.get("pnl_usd", 0) for t in closed)

    return {
        "trade_count": len(closed),
        "win_count": wins,
        "loss_count": len(closed) - wins,
        "win_rate": round(win_rate, 4),
        "total_pnl_usd": round(total_pnl, 2),
        "total_return_pct": round(total_return_pct, 2),
        "sharpe_ratio": round(sharpe, 3),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "equity_curve": equity_curve,  # list of {"date": str, "equity": float}
        "avg_pnl_per_trade": round(total_pnl / len(closed), 2) if closed else 0.0,
    }


def _empty(initial_equity: float) -> Dict:
    return {
        "trade_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "win_rate": 0.0,
        "total_pnl_usd": 0.0,
        "total_return_pct": 0.0,
        "sharpe_ratio": 0.0,
        "max_drawdown_pct": 0.0,
        "equity_curve": [],
        "avg_pnl_per_trade": 0.0,
    }


def _build_equity_curve(closed: List[Dict], initial_equity: float) -> List[Dict]:
    """Aggregate closed trades by exit date and compute running equity."""
    if not closed:
        return []

    by_date: Dict[str, float] = {}
    for t in sorted(closed, key=lambda x: x.get("exit_ts", "")):
        date = _to_date(t.get("exit_ts", ""))
        by_date[date] = by_date.get(date, 0.0) + t.get("pnl_usd", 0.0)

    equity = initial_equity
    curve = []
    for date in sorted(by_date):
        equity += by_date[date]
        curve.append({"date": date, "equity": round(equity, 2)})
    return curve


def _max_drawdown(equity_curve: List[Dict]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]["equity"]
    max_dd = 0.0
    for point in equity_curve:
        e = point["equity"]
        if e > peak:
            peak = e
        dd = (peak - e) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return -max_dd  # negative convention


def _sharpe(equity_curve: List[Dict], risk_free_rate: float = 0.0) -> float:
    """Annualized Sharpe ratio from daily equity curve."""
    if len(equity_curve) < 2:
        return 0.0
    equities = [p["equity"] for p in equity_curve]
    returns = [
        (equities[i] - equities[i - 1]) / equities[i - 1]
        for i in range(1, len(equities))
        if equities[i - 1] > 0
    ]
    if not returns:
        return 0.0
    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    std_r = math.sqrt(variance)
    if std_r == 0:
        return 0.0
    return (mean_r - risk_free_rate / 365) / std_r * math.sqrt(365)


def _to_date(ts: str) -> str:
    if not ts:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        return ts[:10]  # ISO8601: take YYYY-MM-DD
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
