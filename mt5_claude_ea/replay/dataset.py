"""Bar CSV I/O + reproducible SYNTHETIC data. Synthetic data is for pipeline tests only:
it has no relation to any real market and nothing measured on it says anything about profit."""
from __future__ import annotations

import csv
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Bar:
    time: int      # bar open, epoch seconds (UTC in the synthetic set)
    open: float
    high: float
    low: float
    close: float
    spread_points: float = 25.0


def load_bars(path: str) -> list[Bar]:
    with open(path, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(l for l in fh if not l.startswith("#"))]
    bars = [Bar(int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                float(r.get("spread_points") or 25.0)) for r in rows]
    for a, b in zip(bars, bars[1:]):
        if b.time <= a.time:
            raise ValueError("bars are not strictly ascending")
    for b in bars:
        if not (b.low <= min(b.open, b.close) and b.high >= max(b.open, b.close) and b.low > 0):
            raise ValueError(f"malformed OHLC at {b.time}")
    return bars


def save_bars(path: str, bars: list[Bar], note: str = "") -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        if note:
            fh.write(f"# {note}\n")
        w = csv.writer(fh)
        w.writerow(["time", "open", "high", "low", "close", "spread_points"])
        for b in bars:
            w.writerow([b.time, f"{b.open:.2f}", f"{b.high:.2f}", f"{b.low:.2f}", f"{b.close:.2f}",
                        f"{b.spread_points:.0f}"])


def synthetic_bars(n_days: int = 20, seed: int = 20261113, start: int = 1793577600,
                   price: float = 2650.0) -> list[Bar]:
    """Driftless random walk with volatility clustering, M5, weekdays only. start = Mon 2026-11-02 00:00 UTC."""
    rng = random.Random(seed)
    bars, t, vol = [], start, 0.9
    day = 0
    while day < n_days:
        if ((t // 86400) + 4) % 7 in (0, 6):
            t += 86400
            continue
        for i in range(288):
            vol = max(0.3, min(3.0, vol * (1 + rng.gauss(0, 0.05))))
            o = price
            c = round(o + rng.gauss(0, vol), 2)
            h = round(max(o, c) + abs(rng.gauss(0, vol * 0.5)), 2)
            l = round(min(o, c) - abs(rng.gauss(0, vol * 0.5)), 2)
            bars.append(Bar(t + i * 300, round(o, 2), h, l, c, float(rng.choice([18, 22, 25, 30, 45]))))
            price = c
        t += 86400
        day += 1
    return bars


if __name__ == "__main__":
    import os

    out = os.path.join(os.path.dirname(__file__), "data", "SYNTHETIC_XAUUSD_M5.csv")
    save_bars(out, synthetic_bars(), "SYNTHETIC random walk (seed 20261113). NOT market data. Pipeline testing only.")
    print(out)
