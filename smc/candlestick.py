"""Single-candlestick pattern detection (รูปแบบแท่งเทียนรายแท่ง).

Classifies each completed candle into one of the classic one-bar
patterns — Hammer, Inverted Hammer, Shooting Star, Hanging Man,
Marubozu and Doji — and attaches the context that decides whether the
pattern is worth trading:

- Location: a pattern only counts as reliable when it forms at a key
  support/resistance level (a confirmed swing low/high). A pattern
  floating mid-range is reported but flagged ``at_key_level=False``.
- Prior trend: Hammer vs Hanging Man (and Inverted Hammer vs Shooting
  Star) share the same shape; the location/trend picks the name.
- Trade plan: aggressive entry at the next bar's open, conservative
  entry on a break of the pattern's high (buy) or low (sell), and the
  stop-loss at the tip of the pattern's wick.

Only candles that have already closed are classified, and support /
resistance levels come from swing points confirmed *before* the
pattern bar, so there is no lookahead.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd

from .structure import SwingPoint, Trend, find_swing_points


class CandlePattern(Enum):
    HAMMER = "Hammer"
    INVERTED_HAMMER = "Inverted Hammer"
    SHOOTING_STAR = "Shooting Star"
    HANGING_MAN = "Hanging Man"
    BULLISH_MARUBOZU = "Bullish Marubozu"
    BEARISH_MARUBOZU = "Bearish Marubozu"
    DOJI = "Doji"


PATTERN_TH = {
    CandlePattern.HAMMER: "ค้อน",
    CandlePattern.INVERTED_HAMMER: "ค้อนหงาย",
    CandlePattern.SHOOTING_STAR: "ดาวตก",
    CandlePattern.HANGING_MAN: "คนแขวนคอ",
    CandlePattern.BULLISH_MARUBOZU: "แท่งเต็มบอดี้เขียว",
    CandlePattern.BEARISH_MARUBOZU: "แท่งเต็มบอดี้แดง",
    CandlePattern.DOJI: "โดจิ",
}

REVERSAL_PATTERNS = {
    CandlePattern.HAMMER,
    CandlePattern.INVERTED_HAMMER,
    CandlePattern.SHOOTING_STAR,
    CandlePattern.HANGING_MAN,
}


@dataclass
class CandleSignal:
    index: int
    time: pd.Timestamp
    pattern: CandlePattern
    direction: Trend  # UP = bullish, DOWN = bearish, UNDEFINED = doji (wait for confirmation)
    prior_trend: Trend
    at_key_level: bool
    level: Optional[float]  # the support/resistance level the pattern formed at
    high: float
    low: float
    aggressive_entry: Optional[float]  # next bar's open (bar after confirmation for a doji); None if not open yet
    buy_trigger: Optional[float]  # conservative long entry: break above the pattern high
    sell_trigger: Optional[float]  # conservative short entry: break below the pattern low
    stop_loss: Optional[float]  # wick tip; None for a doji until its direction is confirmed
    confirmed: Optional[bool]  # did the next bar break the trigger? None if no next bar yet

    @property
    def tradeable(self) -> bool:
        """Directional pattern at a key level — the setups worth acting on."""
        return self.at_key_level and self.direction != Trend.UNDEFINED

    def describe(self) -> str:
        name = f"{self.pattern.value} ({PATTERN_TH[self.pattern]})"
        where = (
            f"ที่แนว {self.level:.2f}" if self.at_key_level and self.level is not None
            else "ไม่อยู่ที่แนวรับ/แนวต้านสำคัญ — ระวังสัญญาณหลอก"
        )
        if self.direction == Trend.UP:
            plan = (
                f"Buy: สายซิ่งเข้าที่ open แท่งถัดไป"
                + (f" ({self.aggressive_entry:.2f})" if self.aggressive_entry is not None else "")
                + f", สายชัวร์รอทะลุ High {self.buy_trigger:.2f} | SL {self.stop_loss:.2f}"
            )
        elif self.direction == Trend.DOWN:
            plan = (
                f"Sell: สายซิ่งเข้าที่ open แท่งถัดไป"
                + (f" ({self.aggressive_entry:.2f})" if self.aggressive_entry is not None else "")
                + f", สายชัวร์รอหลุด Low {self.sell_trigger:.2f} | SL {self.stop_loss:.2f}"
            )
        else:
            plan = (
                f"ตลาดลังเล: รอแท่งถัดไปเลือกทาง — ทะลุ {self.buy_trigger:.2f} ฝั่ง Buy "
                f"(SL {self.low:.2f}) / หลุด {self.sell_trigger:.2f} ฝั่ง Sell (SL {self.high:.2f})"
            )
        status = {True: "ยืนยันแล้ว", False: "ยังไม่ยืนยัน", None: "รอแท่งถัดไป"}[self.confirmed]
        return f"{self.time}: {name} {where} — {plan} [{status}]"


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def _shape(
    o: float,
    h: float,
    l: float,
    c: float,
    wick_body_ratio: float,
    small_wick_ratio: float,
    doji_body_ratio: float,
    marubozu_body_ratio: float,
) -> Optional[str]:
    """Return the raw candle shape, ignoring context."""
    rng = h - l
    if rng <= 0:
        return None
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l

    # Pin bars first, so a dragonfly/gravestone doji is read as the pin it is.
    if lower >= wick_body_ratio * body and upper <= small_wick_ratio * rng and lower >= 0.5 * rng:
        return "lower_pin"
    if upper >= wick_body_ratio * body and lower <= small_wick_ratio * rng and upper >= 0.5 * rng:
        return "upper_pin"
    if body <= doji_body_ratio * rng:
        return "doji"
    if body >= marubozu_body_ratio * rng:
        return "marubozu_bull" if c > o else "marubozu_bear"
    return None


def _prior_trend(closes, atr: float, i: int, lookback: int, threshold_atr: float) -> Trend:
    if i - 1 - lookback < 0 or atr <= 0:
        return Trend.UNDEFINED
    move = closes[i - 1] - closes[i - 1 - lookback]
    if move >= threshold_atr * atr:
        return Trend.UP
    if move <= -threshold_atr * atr:
        return Trend.DOWN
    return Trend.UNDEFINED


def _nearest(levels: list[float], ref: float) -> Optional[float]:
    return min(levels, key=lambda p: abs(p - ref)) if levels else None


def find_candle_patterns(
    df: pd.DataFrame,
    swings: Optional[list[SwingPoint]] = None,
    swing_left: int = 2,
    swing_right: int = 2,
    level_lookback: int = 100,
    level_tolerance_atr: float = 0.5,
    trend_lookback: int = 5,
    trend_threshold_atr: float = 1.0,
    min_range_atr: float = 0.5,
    wick_body_ratio: float = 2.0,
    small_wick_ratio: float = 0.1,
    doji_body_ratio: float = 0.1,
    marubozu_body_ratio: float = 0.9,
    require_key_level: bool = False,
) -> list[CandleSignal]:
    """Scan every completed candle for single-bar patterns.

    `df` has open/high/low/close indexed by time ascending; every row is
    treated as a closed candle. Support/resistance levels are swing
    lows/highs within `level_lookback` bars that were already confirmed
    (``swing.index + swing_right < i``) when the candle printed. A
    candle is "at" a support level when its low reaches within
    `level_tolerance_atr` * ATR of it and it closes back at or above it
    (mirrored for resistance). Candles whose range is under
    `min_range_atr` * ATR are skipped as noise.
    """
    if swings is None:
        swings = find_swing_points(df, left=swing_left, right=swing_right)
    atr = _atr(df).to_numpy()
    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    n = len(df)

    signals: list[CandleSignal] = []
    for i in range(n):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        a = float(atr[i - 1]) if i > 0 else float(atr[i])
        if a > 0 and (h - l) < min_range_atr * a:
            continue
        shape = _shape(o, h, l, c, wick_body_ratio, small_wick_ratio, doji_body_ratio, marubozu_body_ratio)
        if shape is None:
            continue

        tol = level_tolerance_atr * a
        known = [s for s in swings if i - level_lookback <= s.index and s.index + swing_right < i]
        supports = [s.price for s in known if s.kind == "low" and l <= s.price + tol and c >= s.price - tol]
        resistances = [s.price for s in known if s.kind == "high" and h >= s.price - tol and c <= s.price + tol]
        support = _nearest(supports, l)
        resistance = _nearest(resistances, h)
        trend = _prior_trend(closes, a, i, trend_lookback, trend_threshold_atr)

        pattern: Optional[CandlePattern] = None
        level: Optional[float] = None
        if shape == "lower_pin":
            if support is not None and (resistance is None or trend != Trend.UP):
                pattern, level = CandlePattern.HAMMER, support
            elif resistance is not None:
                pattern, level = CandlePattern.HANGING_MAN, resistance
            elif trend == Trend.DOWN:
                pattern = CandlePattern.HAMMER
            elif trend == Trend.UP:
                pattern = CandlePattern.HANGING_MAN
        elif shape == "upper_pin":
            if resistance is not None and (support is None or trend != Trend.DOWN):
                pattern, level = CandlePattern.SHOOTING_STAR, resistance
            elif support is not None:
                pattern, level = CandlePattern.INVERTED_HAMMER, support
            elif trend == Trend.UP:
                pattern = CandlePattern.SHOOTING_STAR
            elif trend == Trend.DOWN:
                pattern = CandlePattern.INVERTED_HAMMER
        elif shape == "doji":
            pattern = CandlePattern.DOJI
            level = support if support is not None else resistance
        else:
            # Marubozu is a continuation bar: its key level is the one it closed through.
            bull = shape == "marubozu_bull"
            pattern = CandlePattern.BULLISH_MARUBOZU if bull else CandlePattern.BEARISH_MARUBOZU
            broken = [
                s.price for s in known
                if (bull and s.kind == "high" and o <= s.price < c) or (not bull and s.kind == "low" and c < s.price <= o)
            ]
            level = _nearest(broken, c)

        if pattern is None:
            continue
        at_key_level = level is not None
        if require_key_level and not at_key_level:
            continue

        if pattern in (CandlePattern.HAMMER, CandlePattern.INVERTED_HAMMER, CandlePattern.BULLISH_MARUBOZU):
            direction, stop = Trend.UP, l
        elif pattern == CandlePattern.DOJI:
            direction, stop = Trend.UNDEFINED, None
        else:
            direction, stop = Trend.DOWN, h

        confirmed: Optional[bool] = None
        aggressive = None
        if i + 1 < n:
            aggressive = float(opens[i + 1])
            if direction == Trend.UP:
                confirmed = bool(highs[i + 1] > h)
            elif direction == Trend.DOWN:
                confirmed = bool(lows[i + 1] < l)
            else:
                # A doji picks its side when the next bar closes outside its range,
                # so the earliest entry is the open of the bar after that.
                if closes[i + 1] > h:
                    direction, stop, confirmed = Trend.UP, l, True
                elif closes[i + 1] < l:
                    direction, stop, confirmed = Trend.DOWN, h, True
                else:
                    confirmed = False
                aggressive = float(opens[i + 2]) if confirmed and i + 2 < n else None

        signals.append(
            CandleSignal(
                index=i,
                time=df.index[i],
                pattern=pattern,
                direction=direction,
                prior_trend=trend,
                at_key_level=at_key_level,
                level=level,
                high=float(h),
                low=float(l),
                aggressive_entry=aggressive,
                buy_trigger=float(h) if direction != Trend.DOWN else None,
                sell_trigger=float(l) if direction != Trend.UP else None,
                stop_loss=None if stop is None else float(stop),
                confirmed=confirmed,
            )
        )
    return signals
