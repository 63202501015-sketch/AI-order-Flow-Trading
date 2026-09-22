"""Standalone SMC demo — generates synthetic OHLCV and analyzes it.

Self-contained alternative to analyze_sample.py: does not depend on
the smc package, using simpler rolling-window BOS/consolidation logic
and adjacent-candle liquidity matching instead. Kept separate from
analyze_sample.py (which exercises the tested smc.analyze() pipeline)
so both remain available.

Run:
    python examples/analyze_standalone.py

Requirements:
    pip install numpy pandas
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


# ============================================================
# Result object
# ============================================================

@dataclass
class AnalysisResult:
    order_blocks: list = field(default_factory=list)
    liquidity_pools: list = field(default_factory=list)
    consolidation_ranges: list = field(default_factory=list)
    bos_events: list = field(default_factory=list)

    def summary(self) -> str:
        return (
            "=== SMC ANALYSIS ===\n"
            f"Order Blocks         : {len(self.order_blocks)}\n"
            f"Liquidity Pools      : {len(self.liquidity_pools)}\n"
            f"Consolidation Ranges : {len(self.consolidation_ranges)}\n"
            f"BOS Events           : {len(self.bos_events)}"
        )


# ============================================================
# Simple standalone SMC analyzer
# ============================================================

def analyze(df: pd.DataFrame) -> AnalysisResult:
    required = {"open", "high", "low", "close", "volume"}

    missing = required.difference(df.columns)

    if missing:
        raise ValueError(
            f"Missing required columns: {sorted(missing)}"
        )

    if len(df) < 20:
        raise ValueError("Need at least 20 candles for analysis.")

    result = AnalysisResult()

    # --------------------------------------------------------
    # 1. Consolidation detection
    # --------------------------------------------------------

    window = 20

    rolling_high = df["high"].rolling(window).max()
    rolling_low = df["low"].rolling(window).min()

    midpoint = (rolling_high + rolling_low) / 2

    range_pct = (
        (rolling_high - rolling_low)
        / midpoint.replace(0, np.nan)
    )

    consolidation_mask = range_pct < 0.01

    indices = np.where(consolidation_mask.fillna(False))[0]

    if len(indices) > 0:
        first = int(indices[0])

        result.consolidation_ranges.append(
            {
                "index": first,
                "time": df.index[first],
                "high": float(rolling_high.iloc[first]),
                "low": float(rolling_low.iloc[first]),
            }
        )

    # --------------------------------------------------------
    # 2. Break of Structure (BOS)
    # --------------------------------------------------------

    lookback = 20

    previous_high = (
        df["high"]
        .rolling(lookback)
        .max()
        .shift(1)
    )

    previous_low = (
        df["low"]
        .rolling(lookback)
        .min()
        .shift(1)
    )

    bullish_bos = df["close"] > previous_high
    bearish_bos = df["close"] < previous_low

    for i in np.where(bullish_bos.fillna(False))[0]:

        result.bos_events.append(
            {
                "index": int(i),
                "time": df.index[i],
                "direction": "bullish",
                "price": float(df["close"].iloc[i]),
            }
        )

        # Last bearish candle before bullish BOS
        start = max(0, i - 10)

        for j in range(i - 1, start - 1, -1):

            if df["close"].iloc[j] < df["open"].iloc[j]:

                result.order_blocks.append(
                    {
                        "index": int(j),
                        "time": df.index[j],
                        "type": "bullish",
                        "high": float(df["high"].iloc[j]),
                        "low": float(df["low"].iloc[j]),
                    }
                )

                break

    for i in np.where(bearish_bos.fillna(False))[0]:

        result.bos_events.append(
            {
                "index": int(i),
                "time": df.index[i],
                "direction": "bearish",
                "price": float(df["close"].iloc[i]),
            }
        )

        # Last bullish candle before bearish BOS
        start = max(0, i - 10)

        for j in range(i - 1, start - 1, -1):

            if df["close"].iloc[j] > df["open"].iloc[j]:

                result.order_blocks.append(
                    {
                        "index": int(j),
                        "time": df.index[j],
                        "type": "bearish",
                        "high": float(df["high"].iloc[j]),
                        "low": float(df["low"].iloc[j]),
                    }
                )

                break

    # --------------------------------------------------------
    # Remove duplicated OBs
    # --------------------------------------------------------

    unique_ob = {}

    for ob in result.order_blocks:
        key = (ob["index"], ob["type"])
        unique_ob[key] = ob

    result.order_blocks = list(unique_ob.values())

    # --------------------------------------------------------
    # 3. Simple liquidity pool detection
    # Equal highs / equal lows
    # --------------------------------------------------------

    tolerance = 0.0015

    for i in range(2, len(df)):

        high1 = float(df["high"].iloc[i])
        high2 = float(df["high"].iloc[i - 1])

        low1 = float(df["low"].iloc[i])
        low2 = float(df["low"].iloc[i - 1])

        if high2 != 0:

            high_diff = abs(high1 - high2) / abs(high2)

            if high_diff < tolerance:

                result.liquidity_pools.append(
                    {
                        "index": int(i),
                        "time": df.index[i],
                        "type": "buy_side",
                        "price": (high1 + high2) / 2,
                    }
                )

        if low2 != 0:

            low_diff = abs(low1 - low2) / abs(low2)

            if low_diff < tolerance:

                result.liquidity_pools.append(
                    {
                        "index": int(i),
                        "time": df.index[i],
                        "type": "sell_side",
                        "price": (low1 + low2) / 2,
                    }
                )

    return result


# ============================================================
# Generate synthetic OHLCV
# ============================================================

def make_sample_data(seed: int = 7) -> pd.DataFrame:

    rng = np.random.default_rng(seed)

    # Phase 1: accumulation
    accumulation = (
        100
        + rng.normal(0, 0.08, 40).cumsum() * 0.1
    )

    # Phase 2: bearish Order Block
    ob_close = 98.5

    # Phase 3: bullish displacement
    displacement_close = 118.0

    # Phase 4: markup
    markup = (
        displacement_close
        + np.linspace(0, 12, 48)
        + rng.normal(0, 0.4, 48).cumsum() * 0.1
    )

    # Phase 5: pullback
    pullback = (
        markup[-1]
        - np.linspace(0, 15, 40)
        + rng.normal(0, 0.4, 40).cumsum() * 0.1
    )

    close = np.concatenate(
        [
            accumulation,
            [ob_close, displacement_close],
            markup,
            pullback,
        ]
    )

    open_ = np.roll(close, 1)

    open_[0] = close[0]

    # Bearish OB candle
    open_[40] = 100.4

    # Displacement candle
    open_[41] = ob_close

    n = len(close)

    high = (
        np.maximum(open_, close)
        + rng.uniform(0.1, 0.5, n)
    )

    low = (
        np.minimum(open_, close)
        - rng.uniform(0.1, 0.5, n)
    )

    # Tight accumulation wicks
    high[:40] = (
        np.maximum(open_[:40], close[:40])
        + rng.uniform(0.02, 0.1, 40)
    )

    low[:40] = (
        np.minimum(open_[:40], close[:40])
        - rng.uniform(0.02, 0.1, 40)
    )

    # Displacement wick
    high[41] = close[41] + 0.4
    low[41] = open_[41] - 0.3

    volume = rng.uniform(
        1000,
        5000,
        n,
    )

    # Use lowercase "h" for current pandas versions
    time = pd.date_range(
        "2024-01-01",
        periods=n,
        freq="4h",
    )

    df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=time,
    )

    return df


# ============================================================
# Main
# ============================================================

def main() -> None:

    print("Generating sample OHLCV data...")

    df = make_sample_data()

    print(f"Candles generated: {len(df)}")
    print()

    result = analyze(df)

    print(result.summary())

    print()

    print(
        f"Structure events found: "
        f"{len(result.order_blocks)} order block(s), "
        f"{len(result.liquidity_pools)} liquidity pool(s), "
        f"{len(result.consolidation_ranges)} consolidation range(s), "
        f"{len(result.bos_events)} BOS event(s)"
    )

    print("\n--- ORDER BLOCKS ---")

    for ob in result.order_blocks[:10]:
        print(ob)

    print("\n--- BOS EVENTS ---")

    for bos in result.bos_events[:10]:
        print(bos)


if __name__ == "__main__":
    main()
