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
from bridge.retry import ProviderError

from .dataset import Bar, load_bars

WINDOW = 20
HOLD = AISignal(signal="HOLD", confidence=0, reason="unavailable")


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


def user_content(symbol: str, window: list[Bar]) -> str:
    import json

    return json.dumps({"symbol": symbol, "timeframe": "M5", "atr14": round(atr14(window), 5),
                       "spread_points": window[-1].spread_points,
                       "candles_oldest_first": [{"t": b.time, "o": b.open, "h": b.high, "l": b.low, "c": b.close}
                                                for b in window]}, separators=(",", ":"))


def generate(bars: list[Bar], decide: Callable[[list[Bar]], AISignal], source: str,
             existing: Optional[dict[int, tuple]] = None) -> list[tuple]:
    rows = []
    for i in range(WINDOW - 1, len(bars)):
        t = bars[i].time
        if existing and t in existing:
            rows.append(existing[t])
            continue
        window = bars[i - WINDOW + 1: i + 1]          # never touches bars[i+1:]
        s = decide(window)
        rows.append((t, s.signal, f"{s.confidence:.1f}", source))
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


def anthropic_decider(symbol: str, model: str) -> Callable[[list[Bar]], AISignal]:
    from bridge.config import load_settings
    from bridge.providers import AnthropicProvider

    s = load_settings()
    if not s.has_key:
        raise SystemExit("ANTHROPIC_API_KEY not set")
    prov = AnthropicProvider(s.api_key, s.request_timeout, s.effort, s.max_tokens)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(prov.verify_model(model))

    def decide(window: list[Bar]) -> AISignal:
        try:
            res = loop.run_until_complete(prov.complete(model, user_content(symbol, window)))
            return parse_signal(res.text)
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
    a = ap.parse_args()
    bars = load_bars(a.bars)
    if a.provider == "anthropic":
        if not a.confirm_cost:
            raise SystemExit(f"this makes ~{len(bars) - WINDOW + 1} paid API calls; re-run with --confirm-cost")
        from dotenv import load_dotenv

        load_dotenv()
        rows = generate(bars, anthropic_decider(a.symbol, a.model), a.model, read_signals(a.out))
    else:
        rows = generate(bars, mock_rule, "mock")
    write_signals(a.out, rows)
    print(f"{len(rows)} signals -> {a.out}")


if __name__ == "__main__":
    main()
