"""Performance metrics on a list of per-trade net P/L (account currency)."""
from __future__ import annotations

import math
import random
from typing import Sequence


def max_drawdown(pnl: Sequence[float]) -> float:
    peak = eq = dd = 0.0
    for x in pnl:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return dd


def summary(pnl: Sequence[float]) -> dict:
    n = len(pnl)
    if n == 0:
        return {"trades": 0, "net_profit": 0.0, "expectancy": 0.0, "win_rate": None,
                "profit_factor": None, "max_drawdown": 0.0, "sharpe_per_trade": None}
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x < 0]
    mean = sum(pnl) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in pnl) / (n - 1)) if n > 1 else 0.0
    return {
        "trades": n,
        "net_profit": round(sum(pnl), 2),
        "expectancy": round(mean, 4),
        "win_rate": round(len(wins) / n, 4),
        "profit_factor": round(sum(wins) / -sum(losses), 4) if losses else None,
        "max_drawdown": round(max_drawdown(pnl), 2),
        "sharpe_per_trade": round(mean / sd, 4) if sd > 0 else None,   # not annualised
    }


def bootstrap_ci(pnl: Sequence[float], n_boot: int = 2000, alpha: float = 0.05, seed: int = 1):
    """Percentile bootstrap CI of the mean trade. Assumes i.i.d. trades (optimistic if they cluster)."""
    if len(pnl) < 2:
        return None
    rng = random.Random(seed)
    n = len(pnl)
    means = sorted(sum(rng.choice(pnl) for _ in range(n)) / n for _ in range(n_boot))
    return [round(means[int(alpha / 2 * n_boot)], 4), round(means[int((1 - alpha / 2) * n_boot) - 1], 4)]


def calibration(pairs: Sequence[tuple[float, bool]], edges=(0, 50, 60, 70, 80, 90, 100.0001)) -> list[dict]:
    """Win rate per stated-confidence bucket. Confidence is an uncalibrated self-report until
    this table, on enough real trades, shows otherwise."""
    out = []
    for lo, hi in zip(edges, edges[1:]):
        xs = [w for c, w in pairs if lo <= c < hi]
        out.append({"confidence": f"{lo:g}-{min(hi, 100):g}", "trades": len(xs),
                    "win_rate": round(sum(xs) / len(xs), 4) if xs else None})
    return out
