"""Integration: real AnthropicProvider (official SDK) against a mocked Anthropic HTTP API.
No network access and no real key are used."""
import json

import httpx2
import pytest
from anthropic import DefaultAsyncHttpxClient

from bridge.providers import AnthropicProvider
from cai_helpers import client, payload, submit_and_wait

M = "claude-opus-5-5"
FAKE_KEY = "sk-ant-test-0000000000"


def message(text, stop_reason="end_turn", model=M):
    return {"id": "msg_01", "type": "message", "role": "assistant", "model": model,
            "content": [{"type": "thinking", "thinking": "", "signature": "s"},
                        {"type": "text", "text": text}],
            "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 1200, "output_tokens": 80}}


def err(status, etype):
    return httpx2.Response(status, json={"type": "error", "error": {"type": etype, "message": "mock"}},
                           headers={"retry-after": "0"})


class FakeAnthropic:
    def __init__(self, messages_behaviour, models_status=200):
        self.behaviour = messages_behaviour
        self.models_status = models_status
        self.message_requests = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        creds = request.headers.get("x-api-key", "") + request.headers.get("authorization", "")
        assert FAKE_KEY in creds
        if request.url.path.startswith("/v1/models/"):
            if self.models_status != 200:
                return err(self.models_status, "not_found_error")
            mid = request.url.path.rsplit("/", 1)[-1]
            return httpx2.Response(200, json={"id": mid, "type": "model", "display_name": mid,
                                              "created_at": "2026-01-01T00:00:00Z"})
        assert request.url.path == "/v1/messages"
        self.message_requests.append(json.loads(request.content))
        out = self.behaviour(request)
        if isinstance(out, Exception):
            raise out
        return out


def run(tmp_path, fake, **over):
    prov = AnthropicProvider(FAKE_KEY, timeout=2.0, effort="low", max_tokens=4096,
                             http_client=DefaultAsyncHttpxClient(transport=httpx2.MockTransport(fake)))
    with client(tmp_path, prov, cb_threshold=99, **over) as c:
        return submit_and_wait(c, payload())


def test_valid_response_and_request_shape(tmp_path):
    fake = FakeAnthropic(lambda r: httpx2.Response(
        200, json=message('{"signal":"SELL","confidence":61,"reason":"lower highs"}')))
    out = run(tmp_path, fake)
    assert (out["signal"], out["confidence"]) == ("SELL", 61.0)
    body = fake.message_requests[0]
    assert body["model"] == M and body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["effort"] == "low"
    assert not {"temperature", "top_p", "top_k", "tools"} & set(body)      # rejected by current models
    assert "untrusted" in body["system"] and len(body["messages"]) == 1
    json.loads(body["messages"][0]["content"])                             # numeric JSON only


@pytest.mark.parametrize("status,etype,calls", [
    (401, "authentication_error", 1),
    (400, "invalid_request_error", 1),
    (403, "permission_error", 1),
    (404, "not_found_error", 1),
    (429, "rate_limit_error", 6),
    (500, "api_error", 6),
    (529, "overloaded_error", 6),
])
def test_http_errors_hold(tmp_path, status, etype, calls):
    fake = FakeAnthropic(lambda r: err(status, etype))
    out = run(tmp_path, fake)
    assert (out["signal"], out["confidence"]) == ("HOLD", 0.0)
    assert len(fake.message_requests) == calls        # SDK retries are off; bridge owns retries


def test_timeout_holds(tmp_path):
    fake = FakeAnthropic(lambda r: httpx2.ReadTimeout("mock timeout", request=r))
    assert run(tmp_path, fake)["signal"] == "HOLD"
    assert len(fake.message_requests) == 6


def test_connection_error_holds(tmp_path):
    fake = FakeAnthropic(lambda r: httpx2.ConnectError("mock refused", request=r))
    assert run(tmp_path, fake)["signal"] == "HOLD"


@pytest.mark.parametrize("resp", [
    message('{"signal":"BUY","confidence":70,"reason":"x"}', stop_reason="refusal"),
    message('{"signal":"BUY","confidence":70,"rea', stop_reason="max_tokens"),
    message("I think you should buy."),
    {**message("x"), "content": []},
    {"unexpected": "shape"},
])
def test_unusable_200_responses_hold(tmp_path, resp):
    fake = FakeAnthropic(lambda r: httpx2.Response(200, json=resp))
    assert run(tmp_path, fake)["signal"] == "HOLD"
    assert len(fake.message_requests) == 1


def test_html_error_page_holds(tmp_path):
    fake = FakeAnthropic(lambda r: httpx2.Response(502, text="<html>Bad Gateway</html>"))
    assert run(tmp_path, fake)["signal"] == "HOLD"


def test_model_id_unknown_to_models_api_never_reaches_messages(tmp_path):
    fake = FakeAnthropic(lambda r: httpx2.Response(
        200, json=message('{"signal":"BUY","confidence":99,"reason":"x"}')), models_status=404)
    out = run(tmp_path, fake)
    assert out["signal"] == "HOLD" and fake.message_requests == []


def test_recovers_after_529(tmp_path):
    seq = [err(529, "overloaded_error"), err(429, "rate_limit_error"),
           httpx2.Response(200, json=message('{"signal":"BUY","confidence":55,"reason":"x"}'))]
    fake = FakeAnthropic(lambda r: seq.pop(0))
    assert run(tmp_path, fake)["signal"] == "BUY"
