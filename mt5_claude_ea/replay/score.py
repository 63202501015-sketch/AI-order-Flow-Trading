"""Score AI signals against what price did next, WITHOUT trading them.

Use it while the EA runs with InpAllowOrders=false: collect signals for some weeks, export
bars, and see whether BUY/SELL calls were any better than chance before risking an order.

For each BUY/SELL signal: hypothetical entry at the next bar's open (+spread for BUY),
stop 1 ATR, target 3 ATR, first touch within `horizon` bars (stop wins ties). The result is
in R (multiples of the stop distance), net of spread. With a 1:3 structure the break-even
win rate is 25% before costs.

    python -m replay.score --bars XAUUSD_M5.csv --signals claude_replay_signals.csv
    python -m replay.score --bars XAUUSD_M5.csv --audit logs/bridge_audit.jsonl --server-utc-offset-hours 2
"""
from __future__ import annotations

import argparse
import json

from . import metrics as M
from .dataset import Bar, load_bars
from .generate import WINDOW, atr14, read_signals


def signals_from_audit(path: str, server_utc_offset_sec: int = 0) -> dict[int, tuple]:
    """bridge_audit.jsonl -> {bar_time(server clock): (bar_time, signal, confidence, source)}."""
    out: dict[int, tuple] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("event") != "decision" or r.get("source") not in ("single", "vote"):
                continue
            t = int(r["bar_time"])
            out[t] = (t, r["signal"], str(r["confidence"]), "+".join(r.get("model_ids", [])) or r["source"])
    return out


def outcome(bars: list[Bar], i: int, side: str, point: float, horizon: int,
            sl_mult: float = 1.0, tp_mult: float = 3.0):
    """R result of a signal on bars[i] (entry at bars[i+1].open). None if it cannot be scored."""
    if i < WINDOW - 1 or i + 1 >= len(bars):
        return None
    atr = atr14(bars[i - WINDOW + 1: i + 1])
    if atr <= 0:
        return None
    nxt = bars[i + 1]
    spread = nxt.spread_points * point
    sign = 1 if side == "BUY" else -1
    entry = nxt.open + (spread if side == "BUY" else 0.0)       # BUY fills at ask, SELL at bid
    sl, tp = entry - sign * sl_mult * atr, entry + sign * tp_mult * atr
    risk = sl_mult * atr
    for b in bars[i + 1: i + 1 + horizon]:
        lo, hi = (b.low, b.high) if side == "BUY" else (b.low + spread, b.high + spread)  # exit side
        if (side == "BUY" and lo <= sl) or (side == "SELL" and hi >= sl):
            return -1.0, "SL"
        if (side == "BUY" and hi >= tp) or (side == "SELL" and lo <= tp):
            return tp_mult, "TP"
    last = bars[min(i + horizon, len(bars) - 1)]
    px = last.close if side == "BUY" else last.close + spread
    return (px - entry) * sign / risk, "TIMEOUT"


def score(bars: list[Bar], signals: dict[int, tuple], point: float = 0.01, horizon: int = 48) -> dict:
    index = {b.time: i for i, b in enumerate(bars)}
    rows, counts = [], {"BUY": 0, "SELL": 0, "HOLD": 0, "unmatched": 0}
    for t, (_, name, conf, src) in sorted(signals.items()):
        if t not in index:
            counts["unmatched"] += 1
            continue
        counts[name] += 1
        if name == "HOLD":
            continue
        res = outcome(bars, index[t], name, point, horizon)
        if res is not None:
            rows.append({"bar_time": t, "signal": name, "confidence": float(conf), "source": src,
                         "r": res[0], "exit": res[1]})

    def block(sel) -> dict:
        rs = [r["r"] for r in sel]
        d = M.summary(rs)
        d["expectancy_r_ci95"] = M.bootstrap_ci(rs)
        return d

    report = {
        "NOTE": "Hypothetical first-touch outcomes in R, net of spread only. Not trading results.",
        "signal_counts": counts,
        "directional": block(rows),
        "by_side": {s: block([r for r in rows if r["signal"] == s]) for s in ("BUY", "SELL")},
        "by_source": {s: block([r for r in rows if r["source"] == s]) for s in sorted({r["source"] for r in rows})},
        "calibration": M.calibration([(r["confidence"], r["r"] > 0) for r in rows]),
        "exits": {e: sum(1 for r in rows if r["exit"] == e) for e in ("SL", "TP", "TIMEOUT")},
    }
    lo_hi = report["directional"]["expectancy_r_ci95"]
    n = len(rows)
    if n < 100:
        verdict = f"too few directional signals ({n}) to judge; collect at least 100"
    elif lo_hi and lo_hi[0] > 0:
        verdict = "expectancy CI is above zero on this sample (still not proof; check out-of-sample and costs)"
    elif lo_hi and lo_hi[1] < 0:
        verdict = "expectancy CI is below zero: these signals lost after spread on this sample"
    else:
        verdict = "expectancy CI includes zero: no evidence of an edge on this sample"
    report["verdict"] = verdict
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--signals")
    ap.add_argument("--audit")
    ap.add_argument("--point", type=float, default=0.01)
    ap.add_argument("--horizon", type=int, default=48, help="bars to wait for SL/TP (48 = 4 hours)")
    a = ap.parse_args()
    if bool(a.signals) == bool(a.audit):
        raise SystemExit("give exactly one of --signals or --audit")
    sig = read_signals(a.signals) if a.signals else signals_from_audit(a.audit)
    print(json.dumps(score(load_bars(a.bars), sig, a.point, a.horizon), indent=2))


if __name__ == "__main__":
    main()
