"""Smart-money / order-flow structure analysis toolkit.

Reads OHLCV price data and reports where "smart money" (institutional
order flow) is likely accumulating or pushing price: market structure
shifts (BOS/CHoCH), order blocks, and liquidity pools.
"""

from .analyzer import AnalysisResult, analyze
from .liquidity import ConsolidationRange, LiquidityPool, find_consolidation_ranges, find_equal_highs_lows
from .order_blocks import OrderBlock, find_order_blocks, update_mitigation
from .structure import StructureEvent, StructureEventType, SwingPoint, Trend, detect_structure_events, find_swing_points
from .forecast import Forecast15m, forecast_15m

__all__ = [
    "analyze",
    "forecast_15m",
    "Forecast15m",
    "AnalysisResult",
    "Trend",
    "StructureEvent",
    "StructureEventType",
    "SwingPoint",
    "find_swing_points",
    "detect_structure_events",
    "OrderBlock",
    "find_order_blocks",
    "update_mitigation",
    "LiquidityPool",
    "ConsolidationRange",
    "find_equal_highs_lows",
    "find_consolidation_ranges",
]
