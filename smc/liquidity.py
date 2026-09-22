"""Liquidity pool detection: equal highs/lows and tight consolidation
ranges, the zones where stop-loss and pending orders are likely to
cluster and where price is often drawn to before reversing.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .structure import SwingPoint


@dataclass
class LiquidityPool:
    price: float
    start_time: pd.Timestamp
    end_time: pd.Timestamp
    kind: str  # "buy_side" (resting above equal highs) or "sell_side" (below equal lows)
    touches: int


@dataclass
class ConsolidationRange:
    start_time: pd.Timestamp
    end_time: pd.Timestamp
    low: float
    high: float


def find_equal_highs_lows(
    swings: list[SwingPoint], tolerance_pct: float = 0.001, min_touches: int = 2
) -> list[LiquidityPool]:
    """Cluster swing highs (or lows) that sit within `tolerance_pct` of
    each other into a single liquidity pool.
    """
    pools: list[LiquidityPool] = []
    for kind, pool_kind in (("high", "buy_side"), ("low", "sell_side")):
        points = sorted((s for s in swings if s.kind == kind), key=lambda s: s.price)
        used = [False] * len(points)
        for i, base in enumerate(points):
            if used[i]:
                continue
            cluster = [base]
            used[i] = True
            for j in range(i + 1, len(points)):
                if used[j]:
                    continue
                if abs(points[j].price - base.price) <= base.price * tolerance_pct:
                    cluster.append(points[j])
                    used[j] = True
            if len(cluster) >= min_touches:
                avg_price = sum(p.price for p in cluster) / len(cluster)
                times = sorted(p.time for p in cluster)
                pools.append(
                    LiquidityPool(
                        price=avg_price,
                        start_time=times[0],
                        end_time=times[-1],
                        kind=pool_kind,
                        touches=len(cluster),
                    )
                )
    pools.sort(key=lambda p: p.end_time)
    return pools


def find_consolidation_ranges(
    df: pd.DataFrame, window: int = 10, range_atr_mult: float = 1.2
) -> list[ConsolidationRange]:
    """Flag stretches where price coils inside a tight range (accumulation)
    ahead of an eventual expansion — a classic pre-markup/mark-down zone.
    """
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.rolling(14, min_periods=1).mean()

    ranges: list[ConsolidationRange] = []
    i = 0
    n = len(df)
    while i < n - window:
        seg = df.iloc[i : i + window]
        seg_range = seg["high"].max() - seg["low"].min()
        local_atr = atr.iloc[i : i + window].mean()
        if local_atr and seg_range <= range_atr_mult * local_atr:
            ranges.append(
                ConsolidationRange(seg.index[0], seg.index[-1], float(seg["low"].min()), float(seg["high"].max()))
            )
            i += window
        else:
            i += 1
    return ranges
