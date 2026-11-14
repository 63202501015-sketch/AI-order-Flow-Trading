"""Shared builders for bridge tests."""
from __future__ import annotations

import random
import time
from dataclasses import replace

from fastapi.testclient import TestClient

from bridge.config import Settings
from bridge.server import create_app

TOKEN = "t" * 40
HDR = {"X-Bridge-Token": TOKEN}
OK_BUY = '{"signal":"BUY","confidence":72,"reason":"higher lows"}'
OK_SELL = '{"signal":"SELL","confidence":64,"reason":"lower highs"}'
OK_HOLD = '{"signal":"HOLD","confidence":10,"reason":"range"}'


# Frozen wall clock for the bridge (injected into the Decider), so tests never depend on
# where inside a 5-minute window the suite happens to run.
NOW = 1793620810                      # 10 s after an M5 boundary
NOW_BAR = (NOW // 300) * 300 - 300    # open time of the last closed bar (UTC)


def payload(bar_time=None, request_id=None, symbol="XAUUSD", offset=0, **over):
    if bar_time is None:
        bar_time = NOW_BAR + offset   # last closed bar, on the server clock
    candles = []
    for i in range(20):
        t = bar_time - (19 - i) * 300
        o = 2650.0 + i * 0.1
        candles.append({"time": t, "open": o, "high": o + 0.8, "low": o - 0.6, "close": o + 0.2})
    body = {
        "request_id": request_id or f"{symbol}-M5-{bar_time}-770001",
        "symbol": symbol, "timeframe": "M5", "server_utc_offset_sec": offset,
        "spread_points": 25.0, "atr": 1.85, "digits": 2, "point": 0.01, "tick_size": 0.01,
        "contract_size": 100.0, "candles": candles,
    }
    body.update(over)
    return body


async def no_sleep(_):
    return None


def settings(tmp_path, **over) -> Settings:
    base = Settings(bridge_token=TOKEN, ai_enabled=True, api_key="sk-ant-test-0000000000",
                    db_path=str(tmp_path / "state.sqlite3"),
                    audit_path=str(tmp_path / "audit.jsonl"),
                    backoff_base=0.01, backoff_max=0.02, decision_deadline=10.0, request_timeout=2.0)
    return replace(base, **over)


def client(tmp_path, provider, **over) -> TestClient:
    app = create_app(settings(tmp_path, **over), provider,
                     decider_kwargs={"sleep": no_sleep, "rng": random.Random(7), "wall_clock": lambda: NOW},
                     allowed_clients=("testclient",), allowed_hosts=("testserver",))
    return TestClient(app)


def submit_and_wait(c: TestClient, body: dict, timeout: float = 8.0) -> dict:
    r = c.post("/v1/signal", json=body, headers=HDR)
    assert r.status_code in (200, 202), r.text
    data = r.json()
    end = time.time() + timeout
    while data["status"] != "final":
        assert time.time() < end, "decision never became final"
        time.sleep(0.01)
        r = c.get(f"/v1/signal/{body['request_id']}", headers=HDR)
        assert r.status_code == 200
        data = r.json()
    return data
