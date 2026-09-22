import pandas as pd

from smc.structure import Trend, StructureEventType, detect_structure_events, find_swing_points


def _bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


def make_df(rows: list[dict]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="h")
    return pd.DataFrame(rows, index=idx)


def test_find_swing_points_detects_local_extremes():
    rows = [
        _bar(10, 10, 9, 10),
        _bar(10, 11, 10, 11),
        _bar(11, 13, 11, 12),  # swing high at index 2
        _bar(12, 12, 10, 10),
        _bar(10, 10, 8, 9),  # swing low at index 4
        _bar(9, 11, 9, 11),
        _bar(11, 12, 10, 11),
    ]
    df = make_df(rows)
    swings = find_swing_points(df, left=2, right=2)
    kinds_at = {s.index: s.kind for s in swings}
    assert kinds_at.get(2) == "high"
    assert kinds_at.get(4) == "low"


def test_detect_structure_events_flags_bos_after_uptrend_established():
    # Rising sequence of higher highs / higher lows, each new high closing
    # above the previous swing high should register as BOS once trend is UP.
    closes = [10, 11, 9, 12, 10, 15, 11, 18, 13, 22]
    rows = []
    for c in closes:
        rows.append(_bar(c - 0.5, c + 0.5, c - 1, c))
    df = make_df(rows)

    swings = find_swing_points(df, left=1, right=1)
    events = detect_structure_events(df, swings)

    assert len(events) >= 1
    assert all(e.direction == Trend.UP for e in events)
    # first event that establishes the trend, later ones continuing it
    assert events[-1].type in (StructureEventType.BOS, StructureEventType.CHOCH)


def test_detect_structure_events_flags_choch_on_reversal():
    # Uptrend, then a sharp break below the last swing low -> CHoCH to DOWN.
    up = [10, 12, 11, 14, 12, 17]
    down = [16, 10, 15, 5]
    closes = up + down
    rows = [_bar(c - 0.5, c + 0.5, c - 1, c) for c in closes]
    df = make_df(rows)

    swings = find_swing_points(df, left=1, right=1)
    events = detect_structure_events(df, swings)

    assert any(e.type == StructureEventType.CHOCH and e.direction == Trend.DOWN for e in events)
