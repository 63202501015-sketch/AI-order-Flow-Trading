"""Order block detection.

An order block is the last "opposite colour" candle immediately
before a displacement (impulsive) move that produces a market
structure event (BOS/CHoCH). Price often returns to that candle's
range before continuing in the direction of the break, so the zone
is treated as a probable institutional entry area (where smart money
is thought to have accumulated its position).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .structure import StructureEvent, StructureEventType, Trend


@dataclass
class OrderBlock:
    index: int
    time: pd.Timestamp
    top: float
    bottom: float
    direction: Trend  # UP = bullish OB (demand), DOWN = bearish OB (supply)
    event_type: StructureEventType
    event_index: int
    mitigated: bool = False


def _is_bullish(row: pd.Series) -> bool:
    return bool(row["close"] >= row["open"])


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def find_order_blocks(
    df: pd.DataFrame,
    events: list[StructureEvent],
    lookback: int = 10,
    displacement_atr_mult: float = 1.5,
) -> list[OrderBlock]:
    """For each structure event, walk back up to `lookback` candles and
    take the last candle of the opposite colour to the break direction.
    The candle only qualifies if the move from it to the break candle
    is a genuine displacement (>= displacement_atr_mult * ATR), which
    filters out order blocks ahead of weak, grindy breaks.
    """
    atr = _atr(df)
    blocks: list[OrderBlock] = []

    for event in events:
        bullish_break = event.direction == Trend.UP
        window_start = max(0, event.index - lookback)
        window = df.iloc[window_start : event.index + 1]

        candidate_pos = None
        for pos in range(len(window) - 1, -1, -1):
            row = window.iloc[pos]
            if bullish_break and not _is_bullish(row):
                candidate_pos = pos
                break
            if not bullish_break and _is_bullish(row):
                candidate_pos = pos
                break

        if candidate_pos is None:
            continue

        candidate_idx = window.index[candidate_pos]
        candle = df.loc[candidate_idx]

        move_range = abs(event.price - candle["open"])
        local_atr = atr.loc[candidate_idx]
        if pd.isna(local_atr) or local_atr == 0 or move_range < displacement_atr_mult * local_atr:
            continue

        blocks.append(
            OrderBlock(
                index=df.index.get_loc(candidate_idx),
                time=candidate_idx,
                top=float(candle["high"]),
                bottom=float(candle["low"]),
                direction=event.direction,
                event_type=event.type,
                event_index=event.index,
            )
        )

    return blocks


def update_mitigation(blocks: list[OrderBlock], df: pd.DataFrame) -> None:
    """Mark an order block as mitigated once price has traded back
    through its range after the displacement that created it has
    played out (i.e. after the confirming structure event, not the
    displacement candle itself).
    """
    for ob in blocks:
        after = df.iloc[ob.event_index + 1 :]
        if ob.direction == Trend.UP:
            touched = after["low"] <= ob.top
        else:
            touched = after["high"] >= ob.bottom
        ob.mitigated = bool(touched.any())
