"""Market structure detection: swing points, trend, BOS and CHoCH.

Implements the core "smart money" read of price structure: locate
swing highs/lows (fractals), track the sequence of highs and lows,
and flag Break of Structure (trend continuation) vs Change of
Character (trend reversal) events.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd


class Trend(Enum):
    UP = "up"
    DOWN = "down"
    UNDEFINED = "undefined"


class StructureEventType(Enum):
    BOS = "BOS"      # Break of Structure - trend continuation
    CHOCH = "CHoCH"  # Change of Character - trend reversal


@dataclass
class SwingPoint:
    index: int
    time: pd.Timestamp
    price: float
    kind: str  # "high" or "low"


@dataclass
class StructureEvent:
    index: int
    time: pd.Timestamp
    price: float
    type: StructureEventType
    direction: Trend  # resulting trend after this event


def find_swing_points(df: pd.DataFrame, left: int = 2, right: int = 2) -> list[SwingPoint]:
    """Fractal swing high/low detection.

    A swing high at i requires high[i] to be the strict max over the
    window [i-left, i+right]; a swing low requires low[i] to be the
    strict min over the same window.
    """
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    n = len(df)
    points: list[SwingPoint] = []
    for i in range(left, n - right):
        window_high = highs[i - left : i + right + 1]
        if highs[i] == window_high.max() and (window_high == highs[i]).sum() == 1:
            points.append(SwingPoint(i, df.index[i], float(highs[i]), "high"))
        window_low = lows[i - left : i + right + 1]
        if lows[i] == window_low.min() and (window_low == lows[i]).sum() == 1:
            points.append(SwingPoint(i, df.index[i], float(lows[i]), "low"))
    points.sort(key=lambda p: p.index)
    return points


def detect_structure_events(df: pd.DataFrame, swings: list[SwingPoint]) -> list[StructureEvent]:
    """Walk price forward and flag each close that breaks the most
    recent unbroken swing high/low.

    Breaking above the reference swing high confirms an uptrend
    (BOS if already trending up, CHoCH if reversing from a downtrend).
    Breaking below the reference swing low confirms a downtrend
    (BOS if already trending down, CHoCH if reversing from an uptrend).
    """
    events: list[StructureEvent] = []
    trend = Trend.UNDEFINED

    swing_highs = [s for s in swings if s.kind == "high"]
    swing_lows = [s for s in swings if s.kind == "low"]

    ref_high: Optional[SwingPoint] = None
    ref_low: Optional[SwingPoint] = None
    hi_ptr = 0
    lo_ptr = 0
    closes = df["close"].to_numpy()

    for i in range(len(df)):
        while hi_ptr < len(swing_highs) and swing_highs[hi_ptr].index <= i:
            candidate = swing_highs[hi_ptr]
            if ref_high is None or candidate.index > ref_high.index:
                ref_high = candidate
            hi_ptr += 1
        while lo_ptr < len(swing_lows) and swing_lows[lo_ptr].index <= i:
            candidate = swing_lows[lo_ptr]
            if ref_low is None or candidate.index > ref_low.index:
                ref_low = candidate
            lo_ptr += 1

        close = closes[i]

        if ref_high is not None and i > ref_high.index and close > ref_high.price:
            event_type = StructureEventType.BOS if trend == Trend.UP else StructureEventType.CHOCH
            trend = Trend.UP
            events.append(StructureEvent(i, df.index[i], float(close), event_type, trend))
            ref_high = None
        elif ref_low is not None and i > ref_low.index and close < ref_low.price:
            event_type = StructureEventType.BOS if trend == Trend.DOWN else StructureEventType.CHOCH
            trend = Trend.DOWN
            events.append(StructureEvent(i, df.index[i], float(close), event_type, trend))
            ref_low = None

    return events
