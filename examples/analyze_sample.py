"""End-to-end Smart Money Concepts (SMC) demo.

Creates a deterministic synthetic OHLCV series containing:

1. Accumulation
2. Bearish Order Block
3. Bullish Displacement
4. Break of Structure (BOS)
5. Markup
6. Pullback

Run from the repository root:

    python examples/analyze_sample.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# PROJECT PATH
# ============================================================

# Repository root:
#
# AI-order-Flow-Trading/
# ├── smc/
# └── examples/
#     └── analyze_sample.py
#
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# IMPORT SMC ENGINE
# ============================================================

try:
    from smc import analyze
except ImportError as exc:
    raise ImportError(
        "\nUnable to import 'analyze' from the smc package.\n\n"
        f"Repository root detected as:\n{PROJECT_ROOT}\n\n"
        "Check that the project contains either:\n"
        "  smc/__init__.py\n"
        "or a valid installed 'smc' package exposing analyze().\n\n"
        "Run this script from the repository root with:\n"
        "  python examples/analyze_sample.py\n"
    ) from exc


# ============================================================
# SYNTHETIC DATA
# ============================================================

def make_sample_data(seed: int = 7) -> pd.DataFrame:
    """Generate deterministic synthetic OHLCV data."""

    rng = np.random.default_rng(seed)

    # --------------------------------------------------------
    # Phase 1: Accumulation
    # --------------------------------------------------------

    accumulation = (
        100.0
        + rng.normal(
            loc=0.0,
            scale=0.08,
            size=40,
        ).cumsum()
        * 0.1
    )

    # --------------------------------------------------------
    # Phase 2: Bearish Order Block
    # --------------------------------------------------------

    ob_close = 98.5

    # --------------------------------------------------------
    # Phase 3: Bullish displacement / BOS
    # --------------------------------------------------------

    displacement_close = 118.0

    # --------------------------------------------------------
    # Phase 4: Markup
    # --------------------------------------------------------

    markup_noise = (
        rng.normal(
            loc=0.0,
            scale=0.4,
            size=48,
        ).cumsum()
        * 0.1
    )

    markup = (
        displacement_close
        + np.linspace(0.0, 12.0, 48)
        + markup_noise
    )

    # --------------------------------------------------------
    # Phase 5: Pullback
    # --------------------------------------------------------

    pullback_noise = (
        rng.normal(
            loc=0.0,
            scale=0.4,
            size=40,
        ).cumsum()
        * 0.1
    )

    pullback = (
        markup[-1]
        - np.linspace(0.0, 15.0, 40)
        + pullback_noise
    )

    # --------------------------------------------------------
    # Close prices
    # --------------------------------------------------------

    close = np.concatenate(
        (
            accumulation,
            np.array(
                [
                    ob_close,
                    displacement_close,
                ],
                dtype=float,
            ),
            markup,
            pullback,
        )
    ).astype(float)

    # --------------------------------------------------------
    # Open prices
    # --------------------------------------------------------

    open_ = np.empty_like(close)

    open_[0] = close[0]
    open_[1:] = close[:-1]

    # Explicit bearish OB
    open_[40] = 100.4
    close[40] = ob_close

    # Explicit bullish displacement
    open_[41] = ob_close
    close[41] = displacement_close

    n = len(close)

    # --------------------------------------------------------
    # High / Low
    # --------------------------------------------------------

    high = (
        np.maximum(open_, close)
        + rng.uniform(
            low=0.1,
            high=0.5,
            size=n,
        )
    )

    low = (
        np.minimum(open_, close)
        - rng.uniform(
            low=0.1,
            high=0.5,
            size=n,
        )
    )

    # Tight accumulation wicks
    high[:40] = (
        np.maximum(
            open_[:40],
            close[:40],
        )
        + rng.uniform(
            0.02,
            0.10,
            size=40,
        )
    )

    low[:40] = (
        np.minimum(
            open_[:40],
            close[:40],
        )
        - rng.uniform(
            0.02,
            0.10,
            size=40,
        )
    )

    # OB candle wick
    high[40] = max(
        open_[40],
        close[40],
    ) + 0.25

    low[40] = min(
        open_[40],
        close[40],
    ) - 0.25

    # Displacement candle wick
    high[41] = max(
        open_[41],
        close[41],
    ) + 0.40

    low[41] = min(
        open_[41],
        close[41],
    ) - 0.30

    # --------------------------------------------------------
    # Volume
    # --------------------------------------------------------

    volume = rng.uniform(
        low=1000.0,
        high=5000.0,
        size=n,
    )

    # Increase displacement volume
    volume[41] = 9000.0

    # --------------------------------------------------------
    # Timestamp
    # --------------------------------------------------------

    time = pd.date_range(
        start="2024-01-01",
        periods=n,
        freq="4h",
    )

    # --------------------------------------------------------
    # DataFrame
    # --------------------------------------------------------

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

    df.index.name = "time"

    return df


# ============================================================
# DATA VALIDATION
# ============================================================

def validate_ohlcv(df: pd.DataFrame) -> None:
    """Validate OHLCV before sending it to the SMC engine."""

    required = [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    missing = [
        column
        for column in required
        if column not in df.columns
    ]

    if missing:
        raise ValueError(
            f"Missing OHLCV columns: {missing}"
        )

    if df.empty:
        raise ValueError(
            "Generated OHLCV DataFrame is empty."
        )

    if df[required].isnull().any().any():
        raise ValueError(
            "OHLCV data contains NaN values."
        )

    if not np.isfinite(
        df[required].to_numpy(dtype=float)
    ).all():
        raise ValueError(
            "OHLCV data contains non-finite values."
        )

    if (df["high"] < df["low"]).any():
        raise ValueError(
            "Invalid OHLC data: high < low."
        )

    if (
        df["high"]
        < df[["open", "close"]].max(axis=1)
    ).any():
        raise ValueError(
            "Invalid OHLC data: high is below open/close."
        )

    if (
        df["low"]
        > df[["open", "close"]].min(axis=1)
    ).any():
        raise ValueError(
            "Invalid OHLC data: low is above open/close."
        )


# ============================================================
# SAFE LENGTH
# ============================================================

def safe_len(value) -> int:
    """Return len(value), or zero if the result attribute is None."""

    if value is None:
        return 0

    try:
        return len(value)
    except TypeError:
        return 0


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    print("=" * 60)
    print("SMART MONEY CONCEPTS — SYNTHETIC TEST")
    print("=" * 60)

    # Generate sample market
    df = make_sample_data()

    validate_ohlcv(df)

    print(f"\nGenerated candles : {len(df)}")
    print(f"Start              : {df.index[0]}")
    print(f"End                : {df.index[-1]}")
    print(f"Starting price     : {df['close'].iloc[0]:.2f}")
    print(f"Final price        : {df['close'].iloc[-1]:.2f}")

    print("\nRunning SMC analysis...")

    # Run real project analyzer
    result = analyze(df)

    print("\n" + "=" * 60)
    print("ANALYSIS RESULT")
    print("=" * 60)

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    summary_method = getattr(
        result,
        "summary",
        None,
    )

    if callable(summary_method):
        print(summary_method())
    else:
        print(result)

    # --------------------------------------------------------
    # Safely retrieve attributes
    # --------------------------------------------------------

    order_blocks = getattr(
        result,
        "order_blocks",
        [],
    )

    liquidity_pools = getattr(
        result,
        "liquidity_pools",
        [],
    )

    consolidation_ranges = getattr(
        result,
        "consolidation_ranges",
        [],
    )

    print()

    print(
        "Structure events found: "
        f"{safe_len(order_blocks)} order block(s), "
        f"{safe_len(liquidity_pools)} liquidity pool(s), "
        f"{safe_len(consolidation_ranges)} "
        "consolidation range(s)"
    )

    print("\nTest completed successfully.")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
