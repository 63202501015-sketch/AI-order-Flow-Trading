import pandas as pd

from smc.analyzer import analyze
from smc.candlestick import CandlePattern, find_candle_patterns
from smc.structure import Trend


def _bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


def make_df(rows: list[dict]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="h")
    return pd.DataFrame(rows, index=idx)


def _down(start: float, steps: int) -> list[dict]:
    return [_bar(start - k + 1, start - k + 1.1, start - k - 0.2, start - k) for k in range(1, steps + 1)]


def _up(start: float, steps: int) -> list[dict]:
    return [_bar(start + k - 1, start + k + 0.2, start + k - 1.1, start + k) for k in range(1, steps + 1)]


def _at(signals, index):
    return [s for s in signals if s.index == index]


def test_hammer_at_support_is_bullish_and_confirmed():
    # sell-off to a 100 swing low, bounce, retest 100 with a hammer
    rows = _down(110, 10) + _up(100, 3) + _down(103, 2)
    rows.append(_bar(101.2, 101.5, 99.9, 101.4))  # long lower wick into 100 support
    rows.append(_bar(101.4, 102.5, 101.2, 102.3))  # breaks the hammer high
    df = make_df(rows)
    hammer_idx = len(rows) - 2

    sig = _at(find_candle_patterns(df), hammer_idx)
    assert len(sig) == 1
    s = sig[0]
    assert s.pattern == CandlePattern.HAMMER
    assert s.direction == Trend.UP
    assert s.at_key_level and abs(s.level - 99.8) < 1e-9
    assert s.stop_loss == 99.9  # tip of the lower wick
    assert s.buy_trigger == 101.5
    assert s.aggressive_entry == 101.4
    assert s.confirmed is True
    assert s.tradeable


def test_shooting_star_at_resistance_is_bearish():
    rows = _up(100, 10) + _down(110, 3) + _up(107, 2)
    rows.append(_bar(108.8, 110.1, 108.5, 108.6))  # long upper wick into 110 resistance
    df = make_df(rows)

    sig = _at(find_candle_patterns(df), len(rows) - 1)
    assert len(sig) == 1
    s = sig[0]
    assert s.pattern == CandlePattern.SHOOTING_STAR
    assert s.direction == Trend.DOWN
    assert s.at_key_level
    assert s.stop_loss == 110.1
    assert s.sell_trigger == 108.5
    # last bar: next candle hasn't opened yet
    assert s.aggressive_entry is None and s.confirmed is None


def test_hammer_shape_at_resistance_is_hanging_man():
    rows = _up(100, 10) + _down(110, 3) + _up(107, 2)
    rows.append(_bar(109.6, 110.05, 108.3, 109.9))  # hammer shape, but at the 110 high
    df = make_df(rows)

    s = _at(find_candle_patterns(df), len(rows) - 1)[0]
    assert s.pattern == CandlePattern.HANGING_MAN
    assert s.direction == Trend.DOWN
    assert s.stop_loss == 110.05


def test_shooting_star_shape_at_support_is_inverted_hammer():
    rows = _down(110, 10) + _up(100, 3) + _down(103, 2)
    rows.append(_bar(100.3, 101.8, 99.9, 100.0))
    df = make_df(rows)

    s = _at(find_candle_patterns(df), len(rows) - 1)[0]
    assert s.pattern == CandlePattern.INVERTED_HAMMER
    assert s.direction == Trend.UP
    assert s.stop_loss == 99.9


def test_pattern_away_from_levels_is_flagged_and_filterable():
    rows = _down(120, 12)
    rows.append(_bar(107.8, 108.0, 106.4, 107.9))  # hammer shape mid-trend, no swing low nearby
    df = make_df(rows)
    idx = len(rows) - 1

    s = _at(find_candle_patterns(df), idx)[0]
    assert s.pattern == CandlePattern.HAMMER  # named from the prior downtrend
    assert not s.at_key_level
    assert not s.tradeable
    assert _at(find_candle_patterns(df, require_key_level=True), idx) == []


def test_marubozu_and_doji():
    rows = [_bar(100, 100.5, 99.5, 100)] * 5
    rows.append(_bar(100, 103.02, 99.98, 103))  # bullish marubozu
    rows.append(_bar(103, 104, 102, 103.05))  # doji
    rows.append(_bar(103, 103.2, 101.5, 101.6))  # closes below the doji low
    df = make_df(rows)
    signals = find_candle_patterns(df, min_range_atr=0.0)

    maru = _at(signals, 5)[0]
    assert maru.pattern == CandlePattern.BULLISH_MARUBOZU
    assert maru.direction == Trend.UP and maru.stop_loss == 99.98

    doji = _at(signals, 6)[0]
    assert doji.pattern == CandlePattern.DOJI
    # the next bar closed below the doji, so it resolved bearish
    assert doji.direction == Trend.DOWN and doji.confirmed is True
    assert doji.stop_loss == 104
    # direction is only known after the next bar closes, and there's no bar after it
    assert doji.aggressive_entry is None


def test_no_lookahead_levels():
    # the 100 swing low is only confirmed 2 bars later, so a hammer right
    # after it can't use it as support
    rows = _down(110, 10) + [_bar(100.8, 101.0, 99.3, 100.9)]
    df = make_df(rows)
    s = _at(find_candle_patterns(df), len(rows) - 1)[0]
    assert not s.at_key_level


def test_analyze_exposes_candle_signals_in_summary():
    rows = _down(110, 10) + _up(100, 3) + _down(103, 2)
    rows.append(_bar(101.2, 101.5, 99.9, 101.4))
    rows.append(_bar(101.4, 102.5, 101.2, 102.3))
    result = analyze(make_df(rows))
    assert any(s.pattern == CandlePattern.HAMMER and s.tradeable for s in result.candle_signals)
    assert "Hammer" in result.summary()
