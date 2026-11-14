"""Historical AI replay generator (no look-ahead).

For each bar i the signal is computed from bars[i-19 .. i] ONLY (all closed) and stored
under bar i's open time. The EA (tester) and replay.backtest act on it at the open of bar
i+1. The Strategy Tester cannot call WebRequest, so the tester reads this file.

  python -m replay.generate --bars replay/data/SYNTHETIC_XAUUSD_M5.csv --out replay/out/signals.csv
  python -m replay.generate --provider anthropic --confirm-cost ...   (real API calls, costs money)
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
from typing import Callable, Optional

from bridge.models import AISignal
from bridge.parsing import SignalParseError, parse_signal
from bridge.prompt import build_user_content
from bridge.sessions import open_sessions
from bridge.retry import ProviderError

from .dataset import Bar, load_bars

WINDOW = 20
HOLD = AISignal(signal="HOLD", confidence=0, reason="unavailable")
ERROR_SOURCE = "error"      # rows with this source are re-asked on the next run, never trusted


def atr14(window: list[Bar]) -> float:
    trs = [max(b.high - b.low, abs(b.high - p.close), abs(b.low - p.close))
           for p, b in zip(window[-15:-1], window[-14:])]
    return sum(trs) / len(trs)


def mock_rule(window: list[Bar]) -> AISignal:
    """Deterministic stand-in for the model: 20-bar momentum vs ATR. Not a strategy claim."""
    assert len(window) == WINDOW
    move, atr = window[-1].close - window[0].open, atr14(window)
    strength = abs(move) / atr if atr > 0 else 0.0
    if strength < 2.0:
        return AISignal(signal="HOLD", confidence=round(min(50.0, strength * 20), 1), reason="mock: weak momentum")
    return AISignal(signal="BUY" if move > 0 else "SELL", confidence=round(min(95.0, 40 + strength * 12), 1),
                    reason="mock: momentum")


def user_content(symbol: str, window: list[Bar], *, point: float = 0.01, digits: int = 2,
                 server_utc_offset_sec: int = 0, price_mode: str = "raw") -> str:
    """Same builder as the live bridge (bridge.prompt), so replay == live model input."""
    close_utc = window[-1].time + 300 - server_utc_offset_sec
    return build_user_content(
        symbol=symbol, opens=[b.open for b in window], highs=[b.high for b in window],
        lows=[b.low for b in window], closes=[b.close for b in window], atr=atr14(window),
        spread_points=window[-1].spread_points, point=point, digits=digits,
        bar_close_utc=close_utc, sessions_open=open_sessions(close_utc), price_mode=price_mode)


def generate(bars: list[Bar], decide: Callable[[list[Bar]], AISignal], source: str,
             existing: Optional[dict[int, tuple]] = None) -> list[tuple]:
    rows = []
    for i in range(WINDOW - 1, len(bars)):
        t = bars[i].time
        if existing and t in existing and existing[t][3] != ERROR_SOURCE:
            rows.append(existing[t])
            continue
        window = bars[i - WINDOW + 1: i + 1]          # never touches bars[i+1:]
        s = decide(window)
        failed = s is HOLD                            # provider/parse failure, not a model HOLD
        rows.append((t, s.signal, f"{s.confidence:.1f}", ERROR_SOURCE if failed else source))
    return rows


def write_signals(path: str, rows: list[tuple]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["bar_time", "signal", "confidence", "source"])
        w.writerows(rows)


def read_signals(path: str) -> dict[int, tuple]:
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        out = {}
        for r in csv.DictReader(fh):
            if r["signal"] not in ("BUY", "SELL", "HOLD"):
                raise ValueError("bad signal in replay file")
            out[int(r["bar_time"])] = (int(r["bar_time"]), r["signal"], r["confidence"], r["source"])
        return out


def anthropic_decider(symbol: str, model: str, *, point: float, digits: int,
                      server_utc_offset_sec: int) -> Callable[[list[Bar]], AISignal]:
    """Real API calls through the same provider, prompt and retry policy as the live bridge."""
    import random
    import time

    from bridge.config import load_settings
    from bridge.providers import AnthropicProvider
    from bridge.retry import RetryPolicy, call_with_retry

    s = load_settings()
    if not s.has_key:
        raise SystemExit("ANTHROPIC_API_KEY not set")
    prov = AnthropicProvider(s.api_key, s.request_timeout, s.effort, s.max_tokens)
    policy = RetryPolicy(s.max_retries, s.backoff_base, s.backoff_max)
    rng = random.Random()
    loop = asyncio.new_event_loop()
    loop.run_until_complete(prov.verify_model(model))

    def decide(window: list[Bar]) -> AISignal:
        content = user_content(symbol, window, point=point, digits=digits,
                               server_utc_offset_sec=server_utc_offset_sec, price_mode=s.prompt_price_mode)

        async def once() -> AISignal:
            return parse_signal((await prov.complete(model, content)).text)
        try:
            return loop.run_until_complete(call_with_retry(
                once, policy, deadline=time.monotonic() + s.decision_deadline, rng=rng))
        except (ProviderError, SignalParseError):
            return HOLD
    return decide


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--provider", choices=["mock", "anthropic"], default="mock")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--confirm-cost", action="store_true")
    ap.add_argument("--point", type=float, default=0.01)
    ap.add_argument("--digits", type=int, default=2)
    ap.add_argument("--server-utc-offset-hours", type=float, default=0.0,
                    help="broker server time minus UTC for the exported bars (used for hour/session context)")
    a = ap.parse_args()
    bars = load_bars(a.bars)
    if a.provider == "anthropic":
        if not a.confirm_cost:
            raise SystemExit(f"this makes ~{len(bars) - WINDOW + 1} paid API calls; re-run with --confirm-cost")
        from dotenv import load_dotenv

        load_dotenv()
        decide = anthropic_decider(a.symbol, a.model, point=a.point, digits=a.digits,
                                   server_utc_offset_sec=int(a.server_utc_offset_hours * 3600))
        rows = generate(bars, decide, a.model, read_signals(a.out))
        errs = sum(1 for r in rows if r[3] == ERROR_SOURCE)
        if errs:
            print(f"{errs} bars failed (stored as HOLD/error); re-run the same command to retry only those")
    else:
        rows = generate(bars, mock_rule, "mock")
    write_signals(a.out, rows)
    print(f"{len(rows)} signals -> {a.out}")


if __name__ == "__main__":
    main()
