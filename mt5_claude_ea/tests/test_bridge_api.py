"""Integration tests of the HTTP bridge with a scripted (mock) provider."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from bridge.providers import MockProvider
from bridge.retry import ProviderError
from bridge.server import create_app
from cai_helpers import HDR, NOW_BAR, OK_BUY, OK_HOLD, OK_SELL, client, payload, settings, submit_and_wait

M = "claude-opus-5-5"
V3 = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")


def audit_rows(tmp_path):
    return [json.loads(x) for x in (tmp_path / "audit.jsonl").read_text().splitlines()]


def test_happy_path_single_model(tmp_path):
    prov = MockProvider({M: [OK_BUY]})
    with client(tmp_path, prov) as c:
        body = payload()
        out = submit_and_wait(c, body)
        assert (out["signal"], out["confidence"], out["source"]) == ("BUY", 72.0, "single")
        assert out["request_id"] == body["request_id"] and out["bar_time"] == body["candles"][-1]["time"]
    assert prov.verify_calls == [M]
    row = [r for r in audit_rows(tmp_path) if r["event"] == "decision"][-1]
    assert row["model_ids"] == [M] and row["votes"][0]["input_tokens"] == 900 and row["est_cost_usd"] > 0


# ---- authentication / locality ----------------------------------------------------------
def test_auth_required(tmp_path):
    with client(tmp_path, MockProvider()) as c:
        assert c.post("/v1/signal", json=payload()).status_code == 401
        assert c.post("/v1/signal", json=payload(), headers={"X-Bridge-Token": "wrong"}).status_code == 401
        assert c.get("/health").status_code == 401
        assert c.get("/health", headers=HDR).status_code == 200


def test_no_token_configured_rejects_everything(tmp_path):
    with client(tmp_path, MockProvider(), bridge_token="") as c:
        assert c.post("/v1/signal", json=payload(), headers={"X-Bridge-Token": ""}).status_code == 401


def test_non_loopback_client_and_foreign_host_and_origin_rejected(tmp_path):
    app = create_app(settings(tmp_path), MockProvider())     # production defaults
    with TestClient(app) as c:                               # client host is "testclient"
        assert c.post("/v1/signal", json=payload(), headers=HDR).status_code == 403
    with client(tmp_path, MockProvider()) as c:
        assert c.post("/v1/signal", json=payload(), headers={**HDR, "Origin": "http://evil.example"}).status_code == 403
        assert c.post("/v1/signal", json=payload(), headers={**HDR, "Host": "evil.example"}).status_code == 403


def test_malformed_requests_get_no_signal(tmp_path):
    prov = MockProvider({M: [OK_BUY]})
    with client(tmp_path, prov) as c:
        bad = payload()
        bad["candles"][2]["high"] = 1.0
        assert c.post("/v1/signal", json=bad, headers=HDR).status_code == 422
        assert c.post("/v1/signal", content=b"{not json", headers={**HDR, "content-type": "application/json"}).status_code == 422
        assert c.post("/v1/signal", content=b"x" * 20000, headers={**HDR, "content-type": "application/json"}).status_code == 413
        assert c.get("/v1/signal/unknown-id-123", headers=HDR).status_code == 404
    assert prov.calls == []


# ---- fail-closed provider errors ----------------------------------------------------------
@pytest.mark.parametrize("err,expected_calls", [
    (ProviderError("auth", 401, False), 1),
    (ProviderError("bad_request", 400, False), 1),
    (ProviderError("rate_limit", 429, True, retry_after=0.01), 6),
    (ProviderError("overloaded", 529, True), 6),
    (ProviderError("server", 500, True), 6),
    (ProviderError("server", 503, True), 6),
    (ProviderError("timeout", None, True), 6),
    (ProviderError("connection", None, True), 6),
    (RuntimeError("boom"), 1),
])
def test_provider_errors_hold(tmp_path, err, expected_calls):
    prov = MockProvider({M: [err]})
    with client(tmp_path, prov, cb_threshold=99) as c:
        out = submit_and_wait(c, payload())
    assert (out["signal"], out["confidence"]) == ("HOLD", 0.0)
    assert len(prov.calls) == expected_calls           # 1 try + at most 5 retries


@pytest.mark.parametrize("raw", [
    "not json", '{"signal":"BUY"}', '{"signal":"BUY","confidence":900,"reason":"x"}',
    '```json\n{"signal":"SELL","confidence":70,"reason":"x"}\n```',
    '{"signal":"BUY","confidence":70,"reason":"x","sl":0,"lot":100}',
])
def test_bad_model_output_holds_without_retry(tmp_path, raw):
    prov = MockProvider({M: [raw]})
    with client(tmp_path, prov) as c:
        assert submit_and_wait(c, payload())["signal"] == "HOLD"
    assert len(prov.calls) == 1


def test_slow_provider_times_out_to_hold(tmp_path):
    prov = MockProvider({M: [OK_BUY]}, delay=5)
    with client(tmp_path, prov, request_timeout=1.0, decision_deadline=5.0, max_retries=0) as c:
        assert submit_and_wait(c, payload())["signal"] == "HOLD"


def test_submit_never_blocks_on_the_provider(tmp_path):
    prov = MockProvider({M: [OK_BUY]}, delay=0.6)
    with client(tmp_path, prov) as c:
        body = payload()
        t0 = time.time()
        r = c.post("/v1/signal", json=body, headers=HDR)
        assert r.status_code == 202 and r.json()["status"] == "pending" and r.json()["signal"] == "HOLD"
        assert time.time() - t0 < 0.4
        assert submit_and_wait(c, body)["signal"] == "BUY"


def test_retry_then_success(tmp_path):
    prov = MockProvider({M: [ProviderError("overloaded", 529, True), ProviderError("rate_limit", 429, True), OK_SELL]})
    with client(tmp_path, prov) as c:
        assert submit_and_wait(c, payload())["signal"] == "SELL"
    assert len(prov.calls) == 3


# ---- configuration gates ---------------------------------------------------------------------
def test_ai_disabled_is_hold_and_never_calls_provider(tmp_path):
    prov = MockProvider({M: [OK_BUY]})
    with client(tmp_path, prov, ai_enabled=False) as c:
        r = c.post("/v1/signal", json=payload(), headers=HDR)
        assert r.status_code == 200 and r.json()["signal"] == "HOLD" and r.json()["source"] == "disabled"
    assert prov.calls == []


def test_missing_key_is_hold(tmp_path):
    prov = MockProvider({M: [OK_BUY]})
    with client(tmp_path, prov, api_key="replace_me") as c:
        assert c.post("/v1/signal", json=payload(), headers=HDR).json()["signal"] == "HOLD"
    assert prov.calls == []


def test_symbol_not_allowlisted(tmp_path):
    prov = MockProvider({M: [OK_BUY]})
    with client(tmp_path, prov) as c:
        assert c.post("/v1/signal", json=payload(symbol="EURUSD"), headers=HDR).json()["signal"] == "HOLD"
    assert prov.calls == []


def test_stale_and_future_bars_hold(tmp_path):
    prov = MockProvider({M: [OK_BUY]})
    now_bar = NOW_BAR + 300
    with client(tmp_path, prov) as c:
        old = c.post("/v1/signal", json=payload(bar_time=now_bar - 3000), headers=HDR).json()
        fut = c.post("/v1/signal", json=payload(bar_time=now_bar + 3000), headers=HDR).json()
        assert (old["signal"], old["source"]) == ("HOLD", "stale")
        assert (fut["signal"], fut["source"]) == ("HOLD", "rejected")
        # server clock 3h ahead of UTC: same instant, accepted once the offset is applied
        ok = submit_and_wait(c, payload(offset=10800))
        assert ok["signal"] == "BUY"
    assert len(prov.calls) == 1


def test_unknown_model_id_holds_and_never_trades(tmp_path):
    prov = MockProvider({"claude-made-up-9": [OK_BUY]}, unknown_models=["claude-made-up-9"])
    with client(tmp_path, prov, model="claude-made-up-9") as c:
        out = submit_and_wait(c, payload())
        assert out["signal"] == "HOLD" and "not available" in out["reason"]
    assert prov.calls == []


# ---- de-duplication ---------------------------------------------------------------------------
def test_duplicate_request_id_calls_ai_once(tmp_path):
    prov = MockProvider({M: [OK_BUY, OK_SELL]})
    with client(tmp_path, prov) as c:
        body = payload()
        first = submit_and_wait(c, body)
        for _ in range(5):
            again = c.post("/v1/signal", json=body, headers=HDR)
            assert again.status_code == 200 and again.json() == first
    assert len(prov.calls) == 1


def test_request_id_reuse_with_other_payload_conflicts(tmp_path):
    with client(tmp_path, MockProvider({M: [OK_BUY]})) as c:
        body = payload()
        submit_and_wait(c, body)
        body["atr"] = 9.99
        assert c.post("/v1/signal", json=body, headers=HDR).status_code == 409


def test_dedup_survives_bridge_restart(tmp_path):
    body = payload()
    prov1 = MockProvider({M: [OK_BUY]})
    with client(tmp_path, prov1) as c:
        first = submit_and_wait(c, body)
    prov2 = MockProvider({M: [OK_SELL]})
    with client(tmp_path, prov2) as c:               # new process, same SQLite file
        r = c.post("/v1/signal", json=body, headers=HDR)
        assert r.status_code == 200 and r.json() == first
    assert prov2.calls == []


def test_pending_request_becomes_hold_after_restart(tmp_path):
    body = payload()
    prov = MockProvider({M: [OK_BUY]}, delay=30)
    with client(tmp_path, prov) as c:
        assert c.post("/v1/signal", json=body, headers=HDR).status_code == 202
    prov2 = MockProvider({M: [OK_BUY]})
    with client(tmp_path, prov2) as c:
        out = c.get(f"/v1/signal/{body['request_id']}", headers=HDR).json()
        assert (out["status"], out["signal"], out["source"]) == ("final", "HOLD", "restart")
    assert prov2.calls == []


# ---- circuit breaker ------------------------------------------------------------------------------
def test_circuit_opens_and_stops_calling(tmp_path):
    prov = MockProvider({M: [ProviderError("server", 500, True)]})
    now_bar = NOW_BAR
    with client(tmp_path, prov, cb_threshold=2, max_retries=0) as c:
        for i in range(2):
            submit_and_wait(c, payload(request_id=f"XAUUSD-M5-{now_bar}-77000{i}"))
        assert len(prov.calls) == 2
        out = submit_and_wait(c, payload(request_id=f"XAUUSD-M5-{now_bar}-770009"))
        assert (out["signal"], out["source"]) == ("HOLD", "circuit_open")
        assert c.get("/health", headers=HDR).json()["circuit"] == "open"
    assert len(prov.calls) == 2


def test_auth_error_opens_circuit_immediately(tmp_path):
    prov = MockProvider({M: [ProviderError("auth", 401, False)]})
    now_bar = NOW_BAR
    with client(tmp_path, prov, cb_threshold=50) as c:
        submit_and_wait(c, payload(request_id=f"XAUUSD-M5-{now_bar}-770001"))
        out = submit_and_wait(c, payload(request_id=f"XAUUSD-M5-{now_bar}-770002"))
        assert out["source"] == "circuit_open"
    assert len(prov.calls) == 1


# ---- voting mode ----------------------------------------------------------------------------------
def vote_client(tmp_path, a, b, c3, **over):
    prov = MockProvider({V3[0]: [a], V3[1]: [b], V3[2]: [c3]})
    return prov, client(tmp_path, prov, voting_enabled=True, vote_models=V3, **over)


def test_vote_two_of_three(tmp_path):
    prov, cm = vote_client(tmp_path, OK_BUY, OK_HOLD,
                           '{"signal":"BUY","confidence":60,"reason":"b"}')
    with cm as c:
        out = submit_and_wait(c, payload())
    assert (out["signal"], out["confidence"], out["source"]) == ("BUY", 66.0, "vote")
    assert sorted(m for m, _ in prov.calls) == sorted(V3)
    row = [r for r in audit_rows(tmp_path) if r["event"] == "decision"][-1]
    assert row["disagreement"] is True and len(row["votes"]) == 3


def test_vote_split_is_hold(tmp_path):
    _, cm = vote_client(tmp_path, OK_BUY, OK_SELL, OK_HOLD)
    with cm as c:
        assert submit_and_wait(c, payload())["signal"] == "HOLD"


def test_vote_requires_all_three_responses(tmp_path):
    _, cm = vote_client(tmp_path, OK_BUY, OK_BUY, ProviderError("auth", 401, False))
    with cm as c:
        out = submit_and_wait(c, payload())
    assert out["signal"] == "HOLD"                      # 2 BUY + 1 failure is NOT a majority


def test_vote_one_invalid_output_is_hold(tmp_path):
    _, cm = vote_client(tmp_path, OK_SELL, OK_SELL, "garbage")
    with cm as c:
        assert submit_and_wait(c, payload())["signal"] == "HOLD"


def test_voting_off_by_default_uses_one_model(tmp_path):
    prov = MockProvider({M: [OK_BUY]})
    with client(tmp_path, prov) as c:
        submit_and_wait(c, payload())
    assert [m for m, _ in prov.calls] == [M]


# ---- secrets / prompt hygiene ---------------------------------------------------------------------
def test_no_secrets_in_audit_log_and_prompt_is_numeric(tmp_path):
    prov = MockProvider({M: [OK_BUY]})
    with client(tmp_path, prov) as c:
        submit_and_wait(c, payload())
    text = (tmp_path / "audit.jsonl").read_text()
    assert "sk-ant-test" not in text and "t" * 40 not in text
    sent = json.loads(prov.calls[0][1])
    assert set(sent) == {"symbol", "timeframe", "atr14", "spread_points", "digits", "point",
                         "tick_size", "contract_size", "candles_oldest_first"}
    assert all(set(k) == {"t", "o", "h", "l", "c"} and all(isinstance(v, (int, float)) for v in k.values())
               for k in sent["candles_oldest_first"])
