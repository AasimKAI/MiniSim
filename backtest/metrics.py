"""
Backtest performance metrics.
Calculated from a list of closed trade records.
"""

import math
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional


def calculate(
    trades: List[Dict],
    initial_equity: float = 10_000.0,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict:
    """
    Compute performance metrics from a list of closed trade records.

    Each trade record must have: entry_price, exit_price, quantity, side,
    entry_ts, exit_ts, pnl_usd.

    start_date / end_date (YYYY-MM-DD): when provided, the equity curve is
    filled for every calendar day in the range so Sharpe uses the full period
    rather than only days with closing trades.
    """
    if not trades:
        return _empty(initial_equity)

    closed = [t for t in trades if t.get("status") == "closed"]
    if not closed:
        return _empty(initial_equity)

    equity_curve = _build_equity_curve(closed, initial_equity, start_date, end_date)

    total_return_pct = (
        (equity_curve[-1]["equity"] - initial_equity) / initial_equity * 100
        if equity_curve
        else 0.0
    )

    max_drawdown_pct = _max_drawdown(equity_curve, initial_equity)
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
        "equity_curve": equity_curve,
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


def _build_equity_curve(
    closed: List[Dict],
    initial_equity: float,
    start_date: Optional[str],
    end_date: Optional[str],
) -> List[Dict]:
    """
    Build a daily equity curve covering every calendar day in the backtest range.
    Days with no closing trades carry forward the previous equity (zero PnL day).
    This ensures Sharpe is computed over the full period, not just trading days.
    """
    if not closed:
        return []

    # PnL aggregated by exit date
    by_date: Dict[str, float] = {}
    for t in closed:
        d = _to_date(t.get("exit_ts", ""))
        by_date[d] = by_date.get(d, 0.0) + t.get("pnl_usd", 0.0)

    # Determine the date range to fill
    trade_dates = sorted(by_date)
    range_start = start_date or trade_dates[0]
    range_end = end_date or trade_dates[-1]

    try:
        cur = datetime.strptime(range_start, "%Y-%m-%d").date()
        end = datetime.strptime(range_end, "%Y-%m-%d").date()
    except ValueError:
        cur = date.fromisoformat(trade_dates[0])
        end = date.fromisoformat(trade_dates[-1])

    equity = initial_equity
    curve = []
    while cur <= end:
        ds = cur.isoformat()
        equity += by_date.get(ds, 0.0)
        curve.append({"date": ds, "equity": round(equity, 2)})
        cur += timedelta(days=1)

    return curve


def _max_drawdown(equity_curve: List[Dict], initial_equity: float) -> float:
    """Max drawdown as a negative percentage. Peak initialised at initial_equity."""
    if not equity_curve:
        return 0.0
    peak = initial_equity  # start from capital before any trades
    max_dd = 0.0
    for point in equity_curve:
        e = point["equity"]
        if e > peak:
            peak = e
        if peak > 0:
            dd = (peak - e) / peak * 100
            if dd > max_dd:
                max_dd = dd
    return -max_dd  # negative convention


def _sharpe(equity_curve: List[Dict], risk_free_rate: float = 0.0) -> float:
    """
    Annualised Sharpe ratio from the full daily equity curve.
    Uses sample variance (N-1, Bessel's correction).
    """
    if len(equity_curve) < 2:
        return 0.0
    equities = [p["equity"] for p in equity_curve]
    returns = [
        (equities[i] - equities[i - 1]) / equities[i - 1]
        for i in range(1, len(equities))
        if equities[i - 1] > 0
    ]
    n = len(returns)
    if n < 2:
        return 0.0
    mean_r = sum(returns) / n
    # Sample variance (N-1)
    variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
    std_r = math.sqrt(variance)
    if std_r == 0:
        return 0.0
    daily_rf = risk_free_rate / 365
    return (mean_r - daily_rf) / std_r * math.sqrt(365)


def _to_date(ts: str) -> str:
    if not ts:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        return ts[:10]
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
