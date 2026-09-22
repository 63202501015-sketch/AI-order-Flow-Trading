import pandas as pd

from smc.liquidity import find_consolidation_ranges, find_equal_highs_lows
from smc.structure import SwingPoint


def test_find_equal_highs_lows_clusters_close_swing_highs():
    swings = [
        SwingPoint(index=1, time=pd.Timestamp("2024-01-01 01:00"), price=100.0, kind="high"),
        SwingPoint(index=5, time=pd.Timestamp("2024-01-01 05:00"), price=100.05, kind="high"),
        SwingPoint(index=9, time=pd.Timestamp("2024-01-01 09:00"), price=90.0, kind="low"),
    ]
    pools = find_equal_highs_lows(swings, tolerance_pct=0.01, min_touches=2)
    assert len(pools) == 1
    assert pools[0].kind == "buy_side"
    assert pools[0].touches == 2


def test_find_consolidation_ranges_flags_tight_segment():
    idx = pd.date_range("2024-01-01", periods=20, freq="h")
    rows = []
    for i in range(20):
        if i < 12:
            rows.append({"open": 10, "high": 10.2, "low": 9.8, "close": 10})
        else:
            rows.append({"open": 10 + i, "high": 10 + i + 1, "low": 10 + i - 1, "close": 10 + i})
    df = pd.DataFrame(rows, index=idx)

    ranges = find_consolidation_ranges(df, window=10, range_atr_mult=1.5)
    assert ranges
    assert ranges[0].high - ranges[0].low < 1.0
