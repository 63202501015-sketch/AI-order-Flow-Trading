"""High-level entry point: run the full order-flow / smart-money read
on a price series and produce a directional bias plus the zones that
justify it (order blocks, liquidity pools, consolidation ranges).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .liquidity import ConsolidationRange, LiquidityPool, find_consolidation_ranges, find_equal_highs_lows
from .order_blocks import OrderBlock, find_order_blocks, update_mitigation
from .structure import StructureEvent, Trend, detect_structure_events, find_swing_points

REQUIRED_COLUMNS = {"open", "high", "low", "close"}


@dataclass
class AnalysisResult:
    trend: Trend
    last_event: Optional[StructureEvent]
    order_blocks: list[OrderBlock] = field(default_factory=list)
    liquidity_pools: list[LiquidityPool] = field(default_factory=list)
    consolidation_ranges: list[ConsolidationRange] = field(default_factory=list)

    def active_order_blocks(self) -> list[OrderBlock]:
        """Unmitigated order blocks aligned with the current trend —
        the zones still worth watching for an entry."""
        return [ob for ob in self.order_blocks if not ob.mitigated and ob.direction == self.trend]

    def summary(self) -> str:
        if self.last_event is None:
            return "ยังไม่มีโครงสร้างราคาที่ยืนยันได้ (not enough data for a structure read)."

        bias_th = "ขาขึ้น (bullish)" if self.trend == Trend.UP else "ขาลง (bearish)"
        lines = [
            f"Bias ปัจจุบัน: {bias_th} — ยืนยันด้วย {self.last_event.type.value} "
            f"ที่ระดับ {self.last_event.price:.2f} เมื่อ {self.last_event.time}",
        ]

        active = self.active_order_blocks()
        if active:
            nearest = active[-1]
            lines.append(
                f"โซน Order Block ที่ยังไม่ถูกแตะ (watch for entry): "
                f"{nearest.bottom:.2f} - {nearest.top:.2f} (เกิดจาก {nearest.event_type.value} ที่ {nearest.time})"
            )
        else:
            lines.append("ยังไม่พบ Order Block ที่ยังไม่ถูกแตะในทิศทางเดียวกับเทรนด์ปัจจุบัน")

        if self.liquidity_pools:
            pool = self.liquidity_pools[-1]
            side_th = "ฝั่งซื้อ (buy-side, เหนือ equal highs)" if pool.kind == "buy_side" else "ฝั่งขาย (sell-side, ใต้ equal lows)"
            lines.append(
                f"Liquidity pool ล่าสุด: {side_th} รอบราคา {pool.price:.2f} (แตะ {pool.touches} ครั้ง)"
            )

        if self.consolidation_ranges:
            rng = self.consolidation_ranges[-1]
            lines.append(
                f"โซนสะสม/พักตัวล่าสุด: {rng.low:.2f} - {rng.high:.2f} ({rng.start_time} ถึง {rng.end_time})"
            )

        return "\n".join(lines)


def analyze(
    df: pd.DataFrame,
    swing_left: int = 2,
    swing_right: int = 2,
    ob_lookback: int = 10,
    displacement_atr_mult: float = 1.5,
    equal_level_tolerance_pct: float = 0.001,
    consolidation_window: int = 10,
) -> AnalysisResult:
    """Run the structure -> order block -> liquidity pipeline.

    `df` must have columns open/high/low/close (volume optional),
    indexed by time and sorted ascending.
    """
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")
    if not df.index.is_monotonic_increasing:
        raise ValueError("df must be sorted by time ascending")

    swings = find_swing_points(df, left=swing_left, right=swing_right)
    events = detect_structure_events(df, swings)
    order_blocks = find_order_blocks(
        df, events, lookback=ob_lookback, displacement_atr_mult=displacement_atr_mult
    )
    update_mitigation(order_blocks, df)
    liquidity_pools = find_equal_highs_lows(swings, tolerance_pct=equal_level_tolerance_pct)
    consolidation = find_consolidation_ranges(df, window=consolidation_window)

    trend = events[-1].direction if events else Trend.UNDEFINED
    last_event = events[-1] if events else None

    return AnalysisResult(
        trend=trend,
        last_event=last_event,
        order_blocks=order_blocks,
        liquidity_pools=liquidity_pools,
        consolidation_ranges=consolidation,
    )
