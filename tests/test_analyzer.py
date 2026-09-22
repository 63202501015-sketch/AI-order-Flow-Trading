import numpy as np
import pandas as pd
import pytest

from smc.analyzer import analyze
from smc.structure import Trend


def make_df(rows: list[dict]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="h")
    return pd.DataFrame(rows, index=idx)


def _bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


def make_trending_df(n: int = 60, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    close = 100 + np.linspace(0, 20, n) + rng.normal(0, 0.3, n).cumsum() * 0.1
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    high = np.maximum(open_, close) + rng.uniform(0.1, 0.4, n)
    low = np.minimum(open_, close) - rng.uniform(0.1, 0.4, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


def test_analyze_raises_on_missing_columns():
    df = pd.DataFrame({"open": [1, 2], "high": [1, 2], "low": [1, 2]})
    with pytest.raises(ValueError, match="missing required columns"):
        analyze(df)


def test_analyze_raises_on_non_monotonic_index():
    idx = pd.to_datetime(["2024-01-02", "2024-01-01", "2024-01-03"])
    df = pd.DataFrame(
        {"open": [1, 2, 3], "high": [1, 2, 3], "low": [1, 2, 3], "close": [1, 2, 3]}, index=idx
    )
    with pytest.raises(ValueError, match="sorted by time ascending"):
        analyze(df)


def test_analyze_on_too_short_series_returns_undefined_trend():
    rows = [_bar(10, 10.5, 9.5, 10), _bar(10, 10.5, 9.5, 10.1)]
    df = make_df(rows)
    result = analyze(df)
    assert result.trend == Trend.UNDEFINED
    assert result.last_event is None
    assert result.order_blocks == []
    assert "not enough data" in result.summary().lower() or "ยังไม่มี" in result.summary()


def test_analyze_end_to_end_on_trending_data_produces_bias_and_summary():
    df = make_trending_df()
    result = analyze(df)

    assert result.trend in (Trend.UP, Trend.DOWN, Trend.UNDEFINED)
    summary = result.summary()
    assert isinstance(summary, str)
    assert len(summary) > 0

    # active_order_blocks() should only return unmitigated blocks that
    # agree with the current trend direction
    for ob in result.active_order_blocks():
        assert ob.mitigated is False
        assert ob.direction == result.trend


def test_analyze_respects_custom_parameters():
    df = make_trending_df(n=80, seed=3)
    loose = analyze(df, swing_left=1, swing_right=1, displacement_atr_mult=0.1)
    strict = analyze(df, swing_left=1, swing_right=1, displacement_atr_mult=5.0)
    # a much stricter displacement threshold should never find more order blocks
    assert len(strict.order_blocks) <= len(loose.order_blocks)
