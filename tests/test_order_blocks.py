import pandas as pd

from smc.order_blocks import find_order_blocks, update_mitigation
from smc.structure import StructureEvent, StructureEventType, Trend, detect_structure_events, find_swing_points


def make_df(rows: list[dict]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="h")
    return pd.DataFrame(rows, index=idx)


def test_find_order_blocks_picks_last_opposite_candle_before_displacement():
    rows = [
        {"open": 10.0, "high": 10.2, "low": 9.8, "close": 10.1},
        {"open": 10.1, "high": 10.3, "low": 9.9, "close": 10.2},
        {"open": 10.2, "high": 11.0, "low": 10.1, "close": 10.8},  # swing high
        {"open": 10.8, "high": 10.9, "low": 10.0, "close": 10.1},
        {"open": 10.1, "high": 10.2, "low": 9.0, "close": 9.2},    # bearish candle -> candidate OB, swing low
        {"open": 9.2, "high": 20, "low": 9.1, "close": 19},        # strong displacement, breaks swing high
        {"open": 19, "high": 21, "low": 18, "close": 20},
        {"open": 20, "high": 20.5, "low": 19.0, "close": 19.5},
    ]
    df = make_df(rows)
    swings = find_swing_points(df, left=2, right=2)
    events = detect_structure_events(df, swings)
    assert events, "expected at least one structure event on this displacement"

    blocks = find_order_blocks(df, events, lookback=5, displacement_atr_mult=1.0)
    assert blocks
    bullish_obs = [b for b in blocks if b.direction == Trend.UP]
    assert bullish_obs
    ob = bullish_obs[0]
    assert ob.bottom <= 9.2 <= ob.top


def test_update_mitigation_flags_when_price_returns_to_zone():
    event = StructureEvent(index=3, time=pd.Timestamp("2024-01-01 03:00"), price=20, type=StructureEventType.BOS, direction=Trend.UP)
    rows = [
        {"open": 10, "high": 10.5, "low": 9.5, "close": 10},
        {"open": 10, "high": 10.2, "low": 9, "close": 9.2},
        {"open": 9.2, "high": 20, "low": 9.1, "close": 19},
        {"open": 19, "high": 21, "low": 18, "close": 20},
        {"open": 20, "high": 20.5, "low": 9.5, "close": 10},  # dips back into the OB range
    ]
    df = make_df(rows)
    blocks = find_order_blocks(df, [event], lookback=5, displacement_atr_mult=0.5)
    assert blocks
    update_mitigation(blocks, df)
    assert blocks[0].mitigated is True
