"""Replay/backtest invariants: no look-ahead, no duplicate orders, guards hold on every trade."""
import os
from dataclasses import replace

import pytest

from refmodel.sessions import session_allowed
from replay import metrics as M
from replay.backtest import Params, monte_carlo, report, run, walk_forward
from replay.dataset import Bar, load_bars, synthetic_bars
from replay.generate import WINDOW, generate, mock_rule, read_signals, write_signals

DATA = os.path.join(os.path.dirname(__file__), "..", "replay", "data", "SYNTHETIC_XAUUSD_M5.csv")


@pytest.fixture(scope="module")
def bars():
    return load_bars(DATA)


@pytest.fixture(scope="module")
def signals(bars):
    return {r[0]: r for r in generate(bars, mock_rule, "mock")}


def bt(bars, signals, tmp_path, **over):
    return run(bars, signals, replace(Params(), **over), str(tmp_path / "daily.json"))


def test_committed_dataset_is_reproducible_and_labelled_synthetic(bars):
    assert open(DATA).readline().startswith("# SYNTHETIC")
    regen = synthetic_bars()
    assert len(regen) == len(bars) and regen[:50] == bars[:50] and regen[-1] == bars[-1]


# ---- leakage ------------------------------------------------------------------------------------
def test_signals_do_not_depend_on_future_bars(bars):
    full = generate(bars, mock_rule, "mock")
    for cut in (WINDOW, 500, 1234, 4000):
        assert generate(bars[:cut], mock_rule, "mock") == full[:cut - WINDOW + 1]


def test_generator_only_passes_closed_window(bars):
    seen = []

    def spy(window):
        seen.append((window[0].time, window[-1].time, len(window)))
        return mock_rule(window)

    rows = generate(bars[:60], spy, "mock")
    for (first, last, n), row in zip(seen, rows):
        assert n == WINDOW and last == row[0] and first < last


def test_future_bars_cannot_change_past_trades(bars, signals, tmp_path):
    full, _ = bt(bars, signals, tmp_path)
    cut = 3000
    part, _ = bt(bars[:cut], signals, tmp_path)
    horizon = bars[cut - 1].time
    done = [t for t in full if t.exit_time < horizon]
    assert len(done) > 5
    for a, b in zip(done, part):
        assert (a.entry_time, a.entry, a.exit_time, a.exit, a.net) == (b.entry_time, b.entry, b.exit_time, b.exit, b.net)


def test_entries_happen_strictly_after_signal_bar_close(bars, signals, tmp_path):
    trades, _ = bt(bars, signals, tmp_path)
    assert trades
    for t in trades:
        assert t.entry_time >= t.signal_bar + 300 and t.exit_time >= t.entry_time


def test_signal_file_roundtrip(bars, tmp_path):
    rows = generate(bars[:200], mock_rule, "mock")
    p = str(tmp_path / "s.csv")
    write_signals(p, rows)
    assert list(read_signals(p).values()) == [(r[0], r[1], r[2], r[3]) for r in rows]


# ---- guards on every trade ---------------------------------------------------------------------------
def test_trade_invariants(bars, signals, tmp_path):
    p = Params()
    trades, gates = bt(bars, signals, tmp_path)
    by_time = {b.time: b for b in bars}
    assert len({t.signal_bar for t in trades}) == len(trades)             # one order per bar at most
    for prev, cur in zip(trades, trades[1:]):
        assert cur.entry_time >= prev.exit_time                           # never two managed positions
        assert cur.entry_time - prev.entry_time >= p.cooldown_sec
    for t in trades:
        assert session_allowed(t.entry_time)[0]                           # London/NY only, Asia blocked
        assert by_time[t.entry_time].spread_points <= p.max_spread_points
        assert t.confidence >= p.min_confidence
        assert t.volume >= p.vol_min and abs(t.volume / p.vol_step - round(t.volume / p.vol_step)) < 1e-6
        sign = 1 if t.side == "BUY" else -1
        assert abs(abs(t.tp - t.entry) / t.atr - 3.0) < 0.2               # TP ~3 ATR (entry includes slippage)
        last = None
        for _, old, new in t.sl_history:                                  # monotonic SL
            assert (new - old) * sign > 0
            assert last is None or (new - last) * sign > 0
            last = new
    reasons = {g["reason"] for g in gates}
    assert "outside allowed sessions" in reasons and "spread above limit" in reasons


def test_daily_trade_cap_and_daily_stop(bars, signals, tmp_path):
    trades, _ = bt(bars, signals, tmp_path, max_trades_per_day=2, cooldown_sec=0)
    per_day = {}
    for t in trades:
        per_day[t.entry_time // 86400] = per_day.get(t.entry_time // 86400, 0) + 1
    assert max(per_day.values()) <= 2
    trades, _ = bt(bars, signals, tmp_path, daily_loss=30.0, cooldown_sec=0, max_trades_per_day=99)
    day_pnl, stopped = {}, set()
    for t in trades:
        d = t.entry_time // 86400
        assert d not in stopped, "entered after the daily loss latch"
        day_pnl[t.exit_time // 86400] = day_pnl.get(t.exit_time // 86400, 0.0) + t.net
        if day_pnl[t.exit_time // 86400] <= -30.0:
            stopped.add(t.exit_time // 86400)
    assert stopped


def test_deterministic(bars, signals, tmp_path):
    a, _ = bt(bars, signals, tmp_path)
    b, _ = bt(bars, signals, tmp_path)
    assert [(t.entry_time, t.net) for t in a] == [(t.entry_time, t.net) for t in b]


# ---- reverse / HOLD modes on a hand-built tape --------------------------------------------------------
T0 = 1793606400 + 3 * 3600          # Mon 2026-11-02 11:00 UTC, inside the London session


def tape(closes):
    out, price = [], 2650.0
    for i in range(WINDOW + len(closes)):
        c = closes[i - WINDOW] if i >= WINDOW else price + (0.3 if i % 2 else -0.3)
        out.append(Bar(T0 + i * 300, price, max(price, c) + 0.2, min(price, c) - 0.2, c, 20.0))
        price = c
    return out


def sig(bars, mapping):
    return {bars[WINDOW - 1 + k].time: (bars[WINDOW - 1 + k].time, name, "80.0", "test") for k, name in mapping.items()}


FLAT = [2650.0 + (0.05 if i % 2 else -0.05) for i in range(12)]


def test_opposite_signal_ignored_when_reverse_off(tmp_path):
    b = tape(FLAT)
    trades, _ = bt(b, sig(b, {0: "BUY", 3: "SELL"}), tmp_path, cooldown_sec=0)
    assert [(t.side, t.exit_reason) for t in trades] == [("BUY", "END_OF_DATA")]


def test_reverse_closes_then_opens_opposite_never_hedged(tmp_path):
    b = tape(FLAT)
    trades, _ = bt(b, sig(b, {0: "BUY", 3: "SELL"}), tmp_path, cooldown_sec=0, reverse=True)
    assert [(t.side, t.exit_reason) for t in trades] == [("BUY", "REVERSE"), ("SELL", "END_OF_DATA")]
    assert trades[1].entry_time == trades[0].exit_time                    # sequential, not overlapping


def test_reverse_close_without_reentry_when_gate_blocks(tmp_path):
    b = tape(FLAT)
    trades, gates = bt(b, sig(b, {0: "BUY", 3: "SELL"}), tmp_path, reverse=True, cooldown_sec=3600)
    assert [(t.side, t.exit_reason) for t in trades] == [("BUY", "REVERSE")]
    assert gates[-1] == {"bar_time": b[WINDOW + 2].time, "signal": "SELL", "allowed": False, "reason": "cooldown active"}


def test_hold_does_not_close_by_default_but_can_be_enabled(tmp_path):
    b = tape(FLAT)
    s = sig(b, {0: "BUY", 2: "HOLD"})
    assert [t.exit_reason for t in bt(b, s, tmp_path)[0]] == ["END_OF_DATA"]
    assert [t.exit_reason for t in bt(b, s, tmp_path, hold_closes=True)[0]] == ["HOLD_CLOSE"]


def test_same_direction_signal_does_not_stack(tmp_path):
    b = tape(FLAT)
    trades, _ = bt(b, sig(b, {0: "BUY", 1: "BUY", 2: "BUY"}), tmp_path, cooldown_sec=0)
    assert len(trades) == 1


def test_quick_profit_optional(tmp_path):
    up = [2650.0 + 0.6 * (i + 1) for i in range(12)]
    b = tape(up)
    s = sig(b, {0: "BUY"})
    assert "QUICK_PROFIT" not in [t.exit_reason for t in bt(b, s, tmp_path)[0]]
    qp = bt(b, s, tmp_path, quick_profit=True, quick_profit_money=9.0, risk_money=100.0)[0]
    assert qp[0].exit_reason == "QUICK_PROFIT" and qp[0].net > 0


def test_missing_signal_means_no_trade(tmp_path):
    b = tape(FLAT)
    assert bt(b, {}, tmp_path)[0] == []


# ---- metrics ----------------------------------------------------------------------------------------------
def test_metrics_known_values():
    s = M.summary([10, -5, 20, -5, -10])
    assert (s["trades"], s["net_profit"], s["expectancy"], s["win_rate"], s["profit_factor"]) == (5, 10, 2.0, 0.4, 1.5)
    assert M.max_drawdown([10, -5, 20, -5, -10]) == 15
    assert M.summary([])["trades"] == 0
    lo, hi = M.bootstrap_ci([1.0] * 30 + [-1.0] * 30)
    assert lo < 0 < hi
    cal = M.calibration([(65, True), (65, False), (95, True)])
    assert cal[2] == {"confidence": "60-70", "trades": 2, "win_rate": 0.5} and cal[5]["trades"] == 1


def test_report_walkforward_montecarlo_run(bars, signals, tmp_path):
    state = str(tmp_path / "d.json")
    trades, _ = run(bars, signals, Params(), state)
    rep = report(trades)
    assert rep["trades"] == len(trades) and set(rep["costs"]) == {"commission", "spread", "slippage"}
    wf = walk_forward(bars, signals, Params(), 4, state)
    assert [f["fold"] for f in wf] == [1, 2, 3, 4]
    mc = monte_carlo(bars[:1500], signals, Params(), 10, state)
    assert mc["net_p05"] <= mc["net_p50"] <= mc["net_p95"]
