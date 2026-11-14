"""Bar-level replay of the EA rules (refmodel) over pre-generated signals.

Timing (no look-ahead): signal of bar i (known at its close) -> entry at OPEN of bar i+1.
Intrabar order is unknown on OHLC data, so the simulator is pessimistic: within a bar the
stop is checked before the target and the trailing stop only advances on the bar close.
This is an approximation of the MT5 tester, not a substitute for it.

  python -m replay.backtest --bars replay/data/SYNTHETIC_XAUUSD_M5.csv --signals replay/out/signals.csv
"""
from __future__ import annotations

import argparse
import json
import os
import random
from dataclasses import asdict, dataclass, field
from typing import Optional

from refmodel.risk import (DailyGuard, GateInput, entry_gate, initial_stops, normalize_volume,
                           quick_profit_hit, reverse_plan, stops_valid, trail_sl, volume_for_risk)
from refmodel.sessions import session_allowed

from . import metrics as M
from .dataset import Bar, load_bars
from .generate import WINDOW, atr14, read_signals


@dataclass
class Params:
    point: float = 0.01
    tick_size: float = 0.01
    tick_value: float = 1.0            # account currency per tick per 1.0 lot
    vol_min: float = 0.01
    vol_max: float = 100.0
    vol_step: float = 0.01
    stops_level_points: float = 0.0
    risk_money: float = 25.0           # fixed risk per trade in account currency
    max_spread_points: float = 35.0
    min_confidence: float = 60.0
    max_trades_per_day: int = 6
    cooldown_sec: int = 900
    daily_profit: float = 200.0
    daily_loss: float = 100.0
    quick_profit: bool = False
    quick_profit_money: float = 9.0
    reverse: bool = False
    hold_closes: bool = False
    commission_per_lot: float = 7.0    # round trip
    slippage_points: float = 5.0       # adverse, applied to every market fill
    sl_mult: float = 1.0
    tp_mult: float = 3.0


@dataclass
class Trade:
    side: str
    signal_bar: int
    entry_time: int
    entry: float
    volume: float
    atr: float
    confidence: float
    sl: float
    tp: float
    exit_time: int = 0
    exit: float = 0.0
    exit_reason: str = ""
    gross: float = 0.0
    commission: float = 0.0
    spread_cost: float = 0.0
    slippage_cost: float = 0.0
    sl_history: list = field(default_factory=list)

    @property
    def net(self) -> float:
        return self.gross - self.commission


def _money(p: Params, price_diff: float, volume: float) -> float:
    return price_diff / p.tick_size * p.tick_value * volume


def run(bars: list[Bar], signals: dict[int, tuple], p: Params, state_path: str,
        slip_rng: Optional[random.Random] = None) -> tuple[list[Trade], list[dict]]:
    if os.path.exists(state_path):
        os.remove(state_path)
    guard = DailyGuard(state_path, p.daily_profit, p.daily_loss)
    trades: list[Trade] = []
    gates: list[dict] = []
    pos: Optional[Trade] = None
    last_entry_time, last_order_bar = -10**12, -1
    realized_day, trades_day, cur_day = 0.0, 0, 0

    def slip() -> float:
        pts = p.slippage_points if slip_rng is None else abs(slip_rng.gauss(p.slippage_points, p.slippage_points))
        return pts * p.point

    def close(tr: Trade, t: int, price: float, reason: str, market: bool) -> None:
        nonlocal pos, realized_day
        s = slip() if market or reason == "SL" else 0.0     # TP is a limit: no adverse slippage
        sign = 1 if tr.side == "BUY" else -1
        tr.exit, tr.exit_time, tr.exit_reason = price - sign * s, t, reason
        tr.slippage_cost += _money(p, s, tr.volume)
        tr.gross = _money(p, (tr.exit - tr.entry) * sign, tr.volume)
        tr.commission = p.commission_per_lot * tr.volume
        realized_day += tr.net
        trades.append(tr)
        pos = None

    for i in range(WINDOW - 1, len(bars) - 1):
        sig_bar, nxt = bars[i], bars[i + 1]
        day = nxt.time // 86400
        if day != cur_day:
            cur_day, realized_day, trades_day = day, 0.0, 0
        spread = nxt.spread_points * p.point
        bid_o, ask_o = nxt.open, nxt.open + spread

        def floating(price_bid: float) -> float:
            if pos is None:
                return 0.0
            px = price_bid if pos.side == "BUY" else price_bid + spread
            return _money(p, (px - pos.entry) * (1 if pos.side == "BUY" else -1), pos.volume) \
                - p.commission_per_lot * pos.volume

        # ---- protective management at the open of bar i+1 (runs with or without a signal)
        latched = guard.update(day, realized_day, floating(bid_o))
        if pos and latched:
            close(pos, nxt.time, bid_o if pos.side == "BUY" else ask_o, "DAILY_STOP", True)
        if pos and quick_profit_hit(p.quick_profit, floating(bid_o), p.quick_profit_money):
            close(pos, nxt.time, bid_o if pos.side == "BUY" else ask_o, "QUICK_PROFIT", True)

        # ---- signal of the bar that just closed
        _, name, conf, _src = signals.get(sig_bar.time, (0, "HOLD", "0", "missing"))
        conf = float(conf)
        plan = reverse_plan(p.reverse, pos.side if pos else None, name)
        if pos and name == "HOLD" and p.hold_closes:
            close(pos, nxt.time, bid_o if pos.side == "BUY" else ask_o, "HOLD_CLOSE", True)
        if pos and plan == "CLOSE_THEN_RECHECK":
            close(pos, nxt.time, bid_o if pos.side == "BUY" else ask_o, "REVERSE", True)
            latched = guard.update(day, realized_day, 0.0)      # re-check risk after the close
            plan = "ENTER"
        if plan == "ENTER" and pos is None:
            atr = atr14(bars[i - WINDOW + 1: i + 1])
            entry = (ask_o if name == "BUY" else bid_o)
            sl, tp = initial_stops(name, entry, atr, p.tick_size, p.sl_mult, p.tp_mult)
            vol = normalize_volume(volume_for_risk(p.risk_money, abs(entry - sl), p.tick_size, p.tick_value),
                                   p.vol_min, p.vol_max, p.vol_step)
            ok, why = entry_gate(GateInput(
                signal=name, confidence=conf, signal_bar_time=sig_bar.time, last_closed_bar_time=sig_bar.time,
                signal_age_sec=0, allow_orders=True, session_ok=session_allowed(nxt.time)[0],
                spread_points=nxt.spread_points, max_spread_points=p.max_spread_points, daily_latched=latched,
                trades_today=trades_day, max_trades_per_day=p.max_trades_per_day,
                sec_since_last_entry=nxt.time - last_entry_time, cooldown_sec=p.cooldown_sec,
                managed_positions=0, last_order_bar_time=last_order_bar, min_confidence=p.min_confidence,
                max_signal_age_sec=120, volume=vol,
                stops_ok=stops_valid(name, bid_o, ask_o, sl, tp, p.stops_level_points * p.point), margin_ok=True))
            gates.append({"bar_time": sig_bar.time, "signal": name, "allowed": ok, "reason": why})
            if ok:
                s = slip()
                fill = entry + (s if name == "BUY" else -s)
                pos = Trade(name, sig_bar.time, nxt.time, fill, vol, atr, conf, sl, tp,
                            spread_cost=_money(p, spread, vol), slippage_cost=_money(p, s, vol))
                last_entry_time, last_order_bar, trades_day = nxt.time, sig_bar.time, trades_day + 1

        # ---- path of bar i+1: stop first (pessimistic), then target, then trail on the close
        if pos:
            if pos.side == "BUY":
                if nxt.low <= pos.sl:
                    close(pos, nxt.time, min(pos.sl, nxt.open), "SL", False)
                elif nxt.high >= pos.tp:
                    close(pos, nxt.time, pos.tp, "TP", False)
            else:
                if nxt.high + spread >= pos.sl:
                    close(pos, nxt.time, max(pos.sl, nxt.open + spread), "SL", False)
                elif nxt.low + spread <= pos.tp:
                    close(pos, nxt.time, pos.tp, "TP", False)
        if pos:
            px = nxt.close if pos.side == "BUY" else nxt.close + spread
            new = trail_sl(pos.side, pos.entry, pos.sl, px, pos.atr, p.tick_size,
                           min_dist=p.stops_level_points * p.point)
            if new is not None:
                pos.sl_history.append((nxt.time, pos.sl, new))
                pos.sl = new
    if pos:
        last = bars[-1]
        close(pos, last.time, last.close if pos.side == "BUY" else last.close + last.spread_points * p.point,
              "END_OF_DATA", True)
    return trades, gates


def report(trades: list[Trade], seed: int = 1) -> dict:
    net = [t.net for t in trades]
    rep = M.summary(net)
    rep["costs"] = {"commission": round(sum(t.commission for t in trades), 2),
                    "spread": round(sum(t.spread_cost for t in trades), 2),
                    "slippage": round(sum(t.slippage_cost for t in trades), 2)}
    rep["expectancy_ci95_bootstrap"] = M.bootstrap_ci(net, seed=seed)
    rep["calibration"] = M.calibration([(t.confidence, t.net > 0) for t in trades])
    rep["exit_reasons"] = {r: sum(1 for t in trades if t.exit_reason == r) for r in sorted({t.exit_reason for t in trades})}
    return rep


def walk_forward(bars, signals, p: Params, folds: int, state_path: str) -> list[dict]:
    """Sequential, non-overlapping folds evaluated independently. No parameter is fitted here,
    so every fold is out-of-sample with respect to the EA rules; if you tune any parameter on
    earlier folds, only later folds remain out-of-sample."""
    size = len(bars) // folds
    out = []
    for k in range(folds):
        chunk = bars[k * size:(k + 1) * size]
        tr, _ = run(chunk, signals, p, state_path)
        s = M.summary([t.net for t in tr])
        s["fold"], s["from"], s["to"] = k + 1, chunk[0].time, chunk[-1].time
        out.append(s)
    return out


def monte_carlo(bars, signals, p: Params, runs: int, state_path: str, seed: int = 7,
                skip_prob: float = 0.1) -> dict:
    """Execution stress: random adverse slippage on every fill and random missed entries."""
    rng = random.Random(seed)
    nets, dds = [], []
    for _ in range(runs):
        dropped = {k: v for k, v in signals.items() if rng.random() >= skip_prob}
        tr, _ = run(bars, dropped, p, state_path, slip_rng=random.Random(rng.random()))
        s = M.summary([t.net for t in tr])
        nets.append(s["net_profit"])
        dds.append(s["max_drawdown"])
    nets.sort()
    dds.sort()
    q = lambda xs, a: xs[min(len(xs) - 1, int(a * len(xs)))]  # noqa: E731
    return {"runs": runs, "net_p05": q(nets, 0.05), "net_p50": q(nets, 0.5), "net_p95": q(nets, 0.95),
            "maxdd_p50": q(dds, 0.5), "maxdd_p95": q(dds, 0.95)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--signals", required=True)
    ap.add_argument("--out", default="replay/out")
    ap.add_argument("--oos-split", type=float, default=0.7)
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--mc-runs", type=int, default=200)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    bars, signals, p = load_bars(a.bars), read_signals(a.signals), Params()
    state = os.path.join(a.out, "daily_state.json")
    cut = int(len(bars) * a.oos_split)
    trades, gates = run(bars, signals, p, state)
    result = {
        "WARNING": "Pipeline output only. Not evidence of profitability; see docs/TEST_REPORT.md.",
        "bars": a.bars, "n_bars": len(bars), "params": asdict(p),
        "all": report(trades),
        "in_sample": report(run(bars[:cut], signals, p, state)[0]),
        "out_of_sample": report(run(bars[cut:], signals, p, state)[0]),
        "walk_forward": walk_forward(bars, signals, p, a.folds, state),
        "monte_carlo_execution_stress": monte_carlo(bars, signals, p, a.mc_runs, state),
        "gate_rejections": {r: sum(1 for g in gates if g["reason"] == r) for r in sorted({g["reason"] for g in gates})},
    }
    with open(os.path.join(a.out, "backtest_report.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    with open(os.path.join(a.out, "trades.csv"), "w", encoding="utf-8") as fh:
        fh.write("side,signal_bar,entry_time,entry,volume,exit_time,exit,exit_reason,net\n")
        for t in trades:
            fh.write(f"{t.side},{t.signal_bar},{t.entry_time},{t.entry:.2f},{t.volume},{t.exit_time},"
                     f"{t.exit:.2f},{t.exit_reason},{t.net:.2f}\n")
    print(json.dumps({k: result[k] for k in ("all", "out_of_sample", "monte_carlo_execution_stress")}, indent=2))


if __name__ == "__main__":
    main()
