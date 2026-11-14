"""AI path: prompt construction, live/replay parity, budget, smoke tool, signal scoring."""
import asyncio
import json
import os
import re

import pytest

from bridge import prompt
from bridge.models import SignalRequest
from bridge.providers import MockProvider
from bridge.retry import ProviderError
from bridge.service import build_user_content
from bridge.smoke import run as smoke_run
from cai_helpers import HDR, NOW_BAR, OK_BUY, client, payload, submit_and_wait
from replay.dataset import Bar, load_bars
from replay.generate import ERROR_SOURCE, HOLD, generate, mock_rule, user_content
from replay.score import outcome, score, signals_from_audit

M = "claude-opus-5-5"
DATA = os.path.join(os.path.dirname(__file__), "..", "replay", "data", "SYNTHETIC_XAUUSD_M5.csv")


def req():
    return SignalRequest.model_validate(payload())


# ---- prompt ---------------------------------------------------------------------------------
def test_prompt_has_no_absolute_time_and_is_numeric():
    r = req()
    text = build_user_content(r)
    d = json.loads(text)
    assert str(NOW_BAR) not in text and not re.search(r"\b1[5-9]\d{8}\b", text)      # no epoch timestamps
    assert "t" not in d["candles_oldest_first"][0] and '"time"' not in text
    assert [c["i"] for c in d["candles_oldest_first"]] == list(range(-19, 1))
    assert 0 <= d["utc_hour"] <= 23 and isinstance(d["sessions_open"], list)
    for c in d["candles_oldest_first"]:
        assert all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in c.values())
    strings = [v for v in d.values() if isinstance(v, str)]
    assert sorted(strings) == sorted([prompt.PROMPT_VERSION, "XAUUSD", "M5", "price"])


def test_features_are_correct_and_lookback_only():
    o = [10, 11, 12, 11, 13.0]
    c = [11, 12, 11, 13, 14.0]
    h = [11.5, 12.5, 12.2, 13.1, 14.5]
    l = [9.5, 10.8, 10.9, 10.7, 12.9]
    f = prompt.features(o, h, l, c, atr=2.0, spread_price=0.5)
    assert f["net_change_atr"] == 2.0 and f["last_bar_change_atr"] == 0.5
    assert f["window_range_atr"] == 2.5 and f["close_position_in_range"] == 0.9
    assert (f["up_bars"], f["down_bars"]) == (4, 1)
    assert (f["bars_since_window_high"], f["bars_since_window_low"]) == (0, 4)
    assert f["spread_to_atr"] == 0.25


def test_normalized_mode_hides_price_level():
    r = req()
    text = build_user_content(r, "normalized")
    d = json.loads(text)
    assert d["candles_oldest_first"][-1]["c"] == 0.0 and d["atr14"] == 1.0
    assert "265" not in text                                   # no raw ~2650 price anywhere
    raw = json.loads(build_user_content(r, "raw"))
    assert d["features"] == raw["features"]                    # features are scale-free in both modes


def test_system_prompt_states_the_rules():
    s = prompt.SYSTEM_PROMPT
    for needle in ("untrusted", "HOLD", "1 ATR", "3 ATR", "spread", "do not assume or recall future prices",
                   "do not control position size"):
        assert needle in s, needle


def test_replay_and_live_send_identical_model_input():
    """A replay must ask the model exactly what live trading would ask for the same bars."""
    r = req()
    window = [Bar(c.time, c.open, c.high, c.low, c.close, r.spread_points) for c in r.candles]
    from replay.generate import atr14
    live = SignalRequest.model_validate({**payload(), "atr": atr14(window)})
    for mode in prompt.PRICE_MODES:
        assert user_content("XAUUSD", window, point=0.01, digits=2, price_mode=mode) == build_user_content(live, mode)


def test_prompt_version_and_settings_are_audited(tmp_path):
    with client(tmp_path, MockProvider({M: [OK_BUY]})) as c:
        submit_and_wait(c, payload())
        h = c.get("/health", headers=HDR).json()
    row = [json.loads(x) for x in (tmp_path / "audit.jsonl").read_text().splitlines()][-1]
    assert row["prompt_version"] == prompt.PROMPT_VERSION and row["price_mode"] == "raw" and row["effort"] == "low"
    assert h["prompt_version"] == prompt.PROMPT_VERSION and h["spend_today_usd"] > 0


# ---- daily AI budget ----------------------------------------------------------------------------
def test_daily_budget_stops_calls_and_survives_restart(tmp_path):
    prov = MockProvider({M: [OK_BUY]})                     # 900 in + 60 out tokens = $0.0048 per call
    with client(tmp_path, prov, max_daily_cost_usd=0.009) as c:
        assert submit_and_wait(c, payload(request_id=f"XAUUSD-M5-{NOW_BAR}-770001"))["signal"] == "BUY"
        assert submit_and_wait(c, payload(request_id=f"XAUUSD-M5-{NOW_BAR}-770002"))["signal"] == "BUY"
        out = submit_and_wait(c, payload(request_id=f"XAUUSD-M5-{NOW_BAR}-770003"))
        assert (out["signal"], out["source"]) == ("HOLD", "budget")
    assert len(prov.calls) == 2
    prov2 = MockProvider({M: [OK_BUY]})
    with client(tmp_path, prov2, max_daily_cost_usd=0.009) as c:       # restart: budget is persisted
        assert submit_and_wait(c, payload(request_id=f"XAUUSD-M5-{NOW_BAR}-770004"))["source"] == "budget"
    assert prov2.calls == []


def test_failed_and_retried_calls_count_towards_budget(tmp_path):
    prov = MockProvider({M: [OK_BUY]})
    with client(tmp_path, prov, max_daily_cost_usd=0) as c:            # 0 disables the cap
        for i in range(4):
            assert submit_and_wait(c, payload(request_id=f"XAUUSD-M5-{NOW_BAR}-77001{i}"))["signal"] == "BUY"
    assert len(prov.calls) == 4


def test_unknown_model_price_cannot_bypass_budget(tmp_path):
    prov = MockProvider({"claude-new-x": [OK_BUY]})
    with client(tmp_path, prov, model="claude-new-x", max_daily_cost_usd=0.004) as c:
        assert submit_and_wait(c, payload(request_id=f"XAUUSD-M5-{NOW_BAR}-770001"))["signal"] == "BUY"
        assert submit_and_wait(c, payload(request_id=f"XAUUSD-M5-{NOW_BAR}-770002"))["source"] == "budget"


# ---- replay generator -------------------------------------------------------------------------------
def test_replay_errors_are_marked_and_retried_not_cached():
    bars = load_bars(DATA)[:40]
    calls = {"n": 0}

    def flaky(window):
        calls["n"] += 1
        return HOLD if calls["n"] % 2 else mock_rule(window)

    first = generate(bars, flaky, "m")
    errs = [r for r in first if r[3] == ERROR_SOURCE]
    assert errs and all(r[1] == "HOLD" for r in errs)
    before = calls["n"]
    second = generate(bars, mock_rule, "m", {r[0]: r for r in first})
    assert all(r[3] == "m" for r in second)                        # only failed bars were re-asked
    assert second == generate(bars, mock_rule, "m") and calls["n"] == before


# ---- smoke tool ---------------------------------------------------------------------------------------
def test_smoke_reports_ok_and_failures():
    lines = []
    prov = MockProvider({"good": [OK_BUY], "bad": [ProviderError("auth", 401, False)],
                         "junk": ["not json"]}, unknown_models=["ghost"])
    prices = {"good": (4.0, 20.0)}
    ok = asyncio.run(smoke_run(prov, ["good"], prices, "raw", 75, lines.append))
    assert ok and lines[0].startswith("OK   good: BUY") and "est_cost=$0.0048" in lines[0]
    lines.clear()
    ok = asyncio.run(smoke_run(prov, ["good", "bad", "junk", "ghost"], prices, "raw", 75, lines.append))
    text = "\n".join(lines)
    assert not ok and "FAIL bad: auth" in text and "FAIL junk" in text and "FAIL ghost: not_found" in text


# ---- signal scoring -------------------------------------------------------------------------------------
def tape(moves, start=2650.0):
    bars, price, t = [], start, 1793606400
    for i in range(20):
        bars.append(Bar(t + i * 300, price, price + 0.5, price - 0.5, price, 20.0))
    for k, (hi, lo, cl) in enumerate(moves):
        bars.append(Bar(t + (20 + k) * 300, price, price + hi, price - lo, price + cl, 20.0))
        price += cl
    return bars


def test_outcome_first_touch():
    # ATR of the flat window = 1.0; entry BUY = 2650.20 (ask), SL 2649.20, TP 2653.20
    up = tape([(1.0, 0.2, 0.9), (1.5, 0.1, 1.2), (1.5, 0.1, 1.2)])
    assert outcome(up, 19, "BUY", 0.01, 48) == (3.0, "TP")
    assert outcome(up, 19, "SELL", 0.01, 48) == (-1.0, "SL")
    down = tape([(0.1, 1.5, -1.2)])
    assert outcome(down, 19, "BUY", 0.01, 48) == (-1.0, "SL")
    both = tape([(4.0, 4.0, 0.0)])                      # stop and target inside one bar: stop wins
    assert outcome(both, 19, "BUY", 0.01, 48) == (-1.0, "SL")
    flat = tape([(0.3, 0.3, 0.1)] * 3)
    r, why = outcome(flat, 19, "BUY", 0.01, 2)
    assert why == "TIMEOUT" and r == pytest.approx(0.0)  # +0.2 move minus 0.2 spread, in R
    assert outcome(up, 5, "BUY", 0.01, 48) is None and outcome(up, len(up) - 1, "BUY", 0.01, 48) is None


def test_score_report_and_verdict():
    bars = load_bars(DATA)
    sig = {r[0]: r for r in generate(bars, mock_rule, "mock")}
    rep = score(bars, sig)
    c = rep["signal_counts"]
    assert c["BUY"] + c["SELL"] + c["HOLD"] == len(sig) and c["unmatched"] == 0
    assert rep["directional"]["trades"] == sum(rep["exits"].values())
    assert "below zero" in rep["verdict"] or "includes zero" in rep["verdict"]
    few = score(bars, dict(list(sig.items())[:30]))
    assert "too few" in few["verdict"]


def test_score_from_bridge_audit_log(tmp_path):
    with client(tmp_path, MockProvider({M: [OK_BUY]})) as c:
        submit_and_wait(c, payload())
        c.post("/v1/signal", json=payload(symbol="EURUSD"), headers=HDR)          # rejected: not an AI decision
    sig = signals_from_audit(str(tmp_path / "audit.jsonl"))
    assert sig == {NOW_BAR: (NOW_BAR, "BUY", "72.0", M)}
