"""End-to-end demo: build a synthetic OHLC series that walks through a
textbook smart-money sequence - tight accumulation range, a bearish
"order block" candle, a strong bullish displacement candle that breaks
structure, markup continuation, then a pullback - and run the
analysis on it.

Run with:  python examples/analyze_sample.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from smc import analyze  # noqa: E402


def make_sample_data(seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    # phase 1 (40 bars): tight sideways accumulation around 100.
    accumulation = 100 + rng.normal(0, 0.08, 40).cumsum() * 0.1

    # phase 2 (1 bar): bearish candle right before the break - the
    # order block the algorithm should pick up.
    ob_close = 98.5

    # phase 3 (1 bar): strong bullish displacement candle that breaks
    # the accumulation-range high and confirms the structure shift.
    displacement_close = 118.0

    # phase 4 (48 bars): markup continuation off the new base.
    markup = displacement_close + np.linspace(0, 12, 48) + rng.normal(0, 0.4, 48).cumsum() * 0.1

    # phase 5 (40 bars): pullback into a lower high.
    pullback = markup[-1] - np.linspace(0, 15, 40) + rng.normal(0, 0.4, 40).cumsum() * 0.1

    close = np.concatenate([accumulation, [ob_close, displacement_close], markup, pullback])
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    open_[40] = 100.4  # OB candle opens high, closes low (bearish)
    open_[41] = ob_close  # displacement candle opens where the OB candle closed

    n = len(close)
    high = np.maximum(open_, close) + rng.uniform(0.1, 0.5, n)
    low = np.minimum(open_, close) - rng.uniform(0.1, 0.5, n)
    # tighter wicks during accumulation so the range genuinely coils
    high[:40] = np.maximum(open_[:40], close[:40]) + rng.uniform(0.02, 0.1, 40)
    low[:40] = np.minimum(open_[:40], close[:40]) - rng.uniform(0.02, 0.1, 40)
    high[41] = close[41] + 0.4
    low[41] = open_[41] - 0.3

    volume = rng.uniform(1000, 5000, n)
    time = pd.date_range("2024-01-01", periods=n, freq="4h")

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=time
    )


def main() -> None:
    df = make_sample_data()
    result = analyze(df)
    print(result.summary())
    print()
    print(
        f"Structure events found: {len(result.order_blocks)} order block(s), "
        f"{len(result.liquidity_pools)} liquidity pool(s), "
        f"{len(result.consolidation_ranges)} consolidation range(s)"
    )


if __name__ == "__main__":
    main()
