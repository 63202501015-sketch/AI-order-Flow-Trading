import json
import random

import pytest

from refmodel.risk import (DailyGuard, GateInput, entry_gate, initial_stops, normalize_volume,
                           quick_profit_hit, reverse_plan, round_to_tick, stops_valid, trail_sl,
                           volume_for_risk)

TICK = 0.01


# ---- volume / price ------------------------------------------------------------------------
@pytest.mark.parametrize("vol,expected", [
    (0.017, 0.01), (0.0199999, 0.01), (0.02, 0.02), (0.009, 0.0), (0, 0.0), (-1, 0.0),
    (250.0, 100.0), (0.30000000000000004, 0.30), (1.239, 1.23),
])
def test_normalize_volume(vol, expected):
    assert normalize_volume(vol, 0.01, 100.0, 0.01) == pytest.approx(expected)


def test_normalize_volume_never_rounds_up_property():
    rng = random.Random(3)
    for _ in range(5000):
        step = rng.choice([0.01, 0.1, 0.05, 1.0])
        vmin = step * rng.choice([1, 2, 10])
        v = rng.uniform(0, 5)
        out = normalize_volume(v, vmin, 3.0, step)
        assert out <= v + 1e-9 and out <= 3.0 + 1e-9
        assert out == 0.0 or out >= vmin - 1e-9
        assert abs(out / step - round(out / step)) < 1e-6


def test_volume_for_risk():
    # XAUUSD-like: tick 0.01, tick value $1 per lot; SL 2.00 away; risk $50 -> 0.25 lot
    assert volume_for_risk(50, 2.0, 0.01, 1.0) == pytest.approx(0.25)
    assert volume_for_risk(50, 0, 0.01, 1.0) == 0.0


def test_round_to_tick_modes():
    assert round_to_tick(2650.127, 0.05, "down") == pytest.approx(2650.10)
    assert round_to_tick(2650.127, 0.05, "up") == pytest.approx(2650.15)
    assert round_to_tick(2650.127, 0.05) == pytest.approx(2650.15)


# ---- initial stops ---------------------------------------------------------------------------
def test_initial_stops_1atr_3atr():
    assert initial_stops("BUY", 2650.00, 2.0, TICK) == (pytest.approx(2648.00), pytest.approx(2656.00))
    assert initial_stops("SELL", 2650.00, 2.0, TICK) == (pytest.approx(2652.00), pytest.approx(2644.00))


def test_stops_valid_respects_stop_level():
    assert stops_valid("BUY", 2650.00, 2650.30, 2648.00, 2656.00, 0.50)
    assert not stops_valid("BUY", 2650.00, 2650.30, 2649.80, 2656.00, 0.50)
    assert stops_valid("SELL", 2650.00, 2650.30, 2652.00, 2644.00, 0.50)
    assert not stops_valid("SELL", 2650.00, 2650.30, 2650.50, 2644.00, 0.50)
    assert not stops_valid("BUY", 2650.00, 2650.30, 0.0, 2656.00, 0.50)


# ---- break-even / trailing ----------------------------------------------------------------------
def test_buy_be_and_trailing_levels():
    e, atr, sl = 2650.0, 2.0, 2648.0
    assert trail_sl("BUY", e, sl, 2651.99, atr, TICK) is None                 # < +1 ATR
    assert trail_sl("BUY", e, sl, 2652.00, atr, TICK) == pytest.approx(2650.00)   # BE, buffer 0
    assert trail_sl("BUY", e, 2650.0, 2652.90, atr, TICK) is None             # already at BE
    assert trail_sl("BUY", e, 2650.0, 2653.00, atr, TICK) == pytest.approx(2651.00)   # +1.5 ATR -> price-1ATR
    assert trail_sl("BUY", e, 2651.0, 2655.50, atr, TICK) == pytest.approx(2653.50)


def test_sell_be_and_trailing_levels():
    e, atr, sl = 2650.0, 2.0, 2652.0
    assert trail_sl("SELL", e, sl, 2648.01, atr, TICK) is None
    assert trail_sl("SELL", e, sl, 2648.00, atr, TICK) == pytest.approx(2650.00)
    assert trail_sl("SELL", e, 2650.0, 2647.00, atr, TICK) == pytest.approx(2649.00)


def test_be_buffer_is_optional_and_tick_aware():
    assert trail_sl("BUY", 2650.0, 2648.0, 2652.0, 2.0, 0.05, be_buffer_ticks=4) == pytest.approx(2650.20)
    assert trail_sl("SELL", 2650.0, 2652.0, 2648.0, 2.0, 0.05, be_buffer_ticks=4) == pytest.approx(2649.80)


def test_stop_level_and_freeze_level():
    # BE wanted at 2650.00 but broker needs 2.50 distance from Bid 2652.00 -> clamp to 2649.50
    assert trail_sl("BUY", 2650.0, 2648.0, 2652.0, 2.0, TICK, min_dist=2.5) == pytest.approx(2649.50)
    # clamp would not improve the SL -> no modification
    assert trail_sl("BUY", 2650.0, 2649.6, 2652.0, 2.0, TICK, min_dist=2.5) is None
    # price inside freeze distance of current SL -> no modification attempt
    assert trail_sl("BUY", 2650.0, 2651.8, 2652.0, 0.1, TICK, freeze_dist=0.5) is None


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_sl_is_monotonic_on_random_paths(side):
    rng = random.Random(11)
    sign = 1 if side == "BUY" else -1
    for _ in range(300):
        entry, atr = 2650.0, rng.uniform(0.5, 4.0)
        sl = entry - sign * atr
        price = entry
        for _ in range(400):
            price += rng.gauss(0.02 * sign, 0.6)
            new = trail_sl(side, entry, sl, price, atr, TICK,
                           min_dist=rng.choice([0.0, 0.3]), be_buffer_ticks=rng.choice([0, 5]))
            if new is not None:
                assert (new - sl) * sign >= TICK - 1e-9          # strictly better, never worse
                assert (price - new) * sign >= -1e-9             # never beyond current price
                assert abs(new / TICK - round(new / TICK)) < 1e-6
                sl = new


# ---- daily stop -----------------------------------------------------------------------------------
def test_daily_latch_profit_and_loss(tmp_path):
    g = DailyGuard(str(tmp_path / "d.json"))
    assert g.update(20261113, 150.0, 49.99) is False
    assert g.update(20261113, 150.0, 50.0) is True                 # realized + floating = +200
    assert g.update(20261113, 0.0, 0.0) is True                    # stays latched even if P/L falls back
    g2 = DailyGuard(str(tmp_path / "l.json"))
    assert g2.update(20261113, -60.0, -39.0) is False
    assert g2.update(20261113, -60.0, -40.0) is True


def test_daily_latch_survives_restart_and_resets_next_broker_day(tmp_path):
    p = str(tmp_path / "d.json")
    assert DailyGuard(p).update(20261113, -100.0, 0.0) is True
    restarted = DailyGuard(p)                                       # new process
    assert restarted.state.latched and restarted.update(20261113, 0.0, 0.0) is True
    assert restarted.update(20261114, 0.0, 0.0) is False
    assert DailyGuard(p).state == restarted.state


def test_corrupt_daily_state_fails_closed(tmp_path):
    p = tmp_path / "d.json"
    p.write_text("{not json")
    assert DailyGuard(str(p)).update(20261113, 0.0, 0.0) is True


def test_daily_state_file_is_valid_json(tmp_path):
    p = tmp_path / "d.json"
    DailyGuard(str(p)).update(20261113, 500.0, 0.0)
    assert json.loads(p.read_text()) == {"day": 20261113, "latched": True, "reason": "daily profit target"}


def test_quick_profit_optional():
    assert quick_profit_hit(False, 50.0) is False
    assert quick_profit_hit(True, 8.99) is False and quick_profit_hit(True, 9.0) is True


# ---- entry gate ---------------------------------------------------------------------------------------
def good() -> GateInput:
    return GateInput(signal="BUY", confidence=70, signal_bar_time=1000, last_closed_bar_time=1000,
                     signal_age_sec=10, allow_orders=True, session_ok=True, spread_points=20,
                     max_spread_points=35, trades_today=0, max_trades_per_day=3, cooldown_sec=900,
                     min_confidence=60, max_signal_age_sec=120, volume=0.1, stops_ok=True, margin_ok=True)


def test_gate_passes_when_everything_is_ok():
    assert entry_gate(good()) == (True, "ok")


def test_gate_default_input_blocks():
    assert entry_gate(GateInput())[0] is False


@pytest.mark.parametrize("field,value,reason", [
    ("signal", "HOLD", "HOLD"), ("signal", "CLOSE_ALL", "HOLD"),
    ("allow_orders", False, "not enabled"), ("trade_permitted", False, "not permitted"),
    ("symbol_allowed", False, "allowlisted"),
    ("signal_bar_time", 700, "last closed bar"), ("signal_age_sec", 121, "stale"),
    ("last_order_bar_time", 1000, "dedup"), ("confidence", 59.9, "confidence"),
    ("daily_latched", True, "daily stop"), ("session_ok", False, "sessions"),
    ("spread_points", 36, "spread"), ("max_spread_points", 0, "spread"),
    ("trades_today", 3, "cap"), ("sec_since_last_entry", 899, "cooldown"),
    ("foreign_position_on_netting", True, "netting"), ("managed_positions", 1, "already open"),
    ("volume", 0.0, "minimum"), ("stops_ok", False, "stop level"), ("margin_ok", False, "margin"),
])
def test_gate_each_guard_blocks(field, value, reason):
    g = good()
    setattr(g, field, value)
    ok, why = entry_gate(g)
    assert ok is False and reason in why


def test_reverse_plan():
    assert reverse_plan(False, None, "BUY") == "ENTER"
    assert reverse_plan(False, "BUY", "BUY") == "NONE"
    assert reverse_plan(False, "BUY", "SELL") == "IGNORE_OPPOSITE"      # default: reverse OFF
    assert reverse_plan(True, "BUY", "SELL") == "CLOSE_THEN_RECHECK"
    assert reverse_plan(True, "SELL", "HOLD") == "NONE"                 # HOLD never closes by default
