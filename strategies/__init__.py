"""
Strategy registry — single import point.

REGISTRY maps strategy name → Strategy instance.
"""
from strategies.bear_trend_short import _instance as TrendShort
from strategies.bear_scalp       import _instance as BreakdownScalp
from strategies.bear_bounce      import _instance as OversoldBounce
from strategies.bull_momentum    import _instance as MomentumLong
from strategies.bull_dip         import _instance as DipBuy
from strategies.range_scalp      import _instance as RangeScalp

REGISTRY: dict = {
    s.name: s for s in [
        TrendShort,
        BreakdownScalp,
        OversoldBounce,
        MomentumLong,
        DipBuy,
        RangeScalp,
    ]
}

__all__ = ["REGISTRY"]
