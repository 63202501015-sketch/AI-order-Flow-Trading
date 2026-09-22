"""Optional chart rendering for an AnalysisResult (requires mplfinance)."""

from __future__ import annotations

from typing import Optional

import pandas as pd

from .analyzer import AnalysisResult
from .structure import Trend


def plot(df: pd.DataFrame, result: AnalysisResult, save_path: Optional[str] = None):
    try:
        import mplfinance as mpf
    except ImportError as exc:
        raise ImportError("plotting requires mplfinance: pip install mplfinance") from exc

    fig, axes = mpf.plot(
        df,
        type="candle",
        style="charles",
        returnfig=True,
        volume="volume" in df.columns,
    )
    ax = axes[0]

    for ob in result.order_blocks:
        color = "tab:blue" if ob.direction == Trend.UP else "tab:red"
        ax.axhspan(ob.bottom, ob.top, color=color, alpha=0.15 if ob.mitigated else 0.35)

    for pool in result.liquidity_pools:
        ax.axhline(pool.price, linestyle="--", linewidth=0.8, color="gray")

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")

    return fig, ax
