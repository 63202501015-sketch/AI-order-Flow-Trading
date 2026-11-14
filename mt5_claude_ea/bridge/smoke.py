"""One REAL request per configured model, to verify key, model ids, structured output,
latency and cost before the EA depends on them. Costs a few cents. Never places trades.

    python -m bridge.smoke            (uses .env; needs ANTHROPIC_API_KEY, ignores AI_ENABLED)
"""
from __future__ import annotations

import asyncio
import sys
import time

from .config import ConfigError, load_settings
from .parsing import SignalParseError, parse_signal
from .prompt import PROMPT_VERSION, build_user_content
from .providers import AnthropicProvider
from .retry import ProviderError

HINTS = {
    "auth": "API key rejected: check ANTHROPIC_API_KEY in .env (Console > API Keys).",
    "not_found": "Model id not available to this key: change ANTHROPIC_MODEL / VOTE_MODELS.",
    "bad_request": "Request rejected (400/402/413): most often no credit on the account, or an unsupported parameter.",
    "rate_limit": "Rate limited (429): the account tier is too low for this call rate.",
    "overloaded": "API overloaded (529): temporary, try again later.",
    "timeout": "Timed out: raise AI_TIMEOUT or check the network.",
    "connection": "Cannot reach the API: check network / proxy / firewall.",
    "refusal": "The model declined to answer this request.",
    "invalid_output": "Model answered but not in the required format.",
}


def sample_content(price_mode: str) -> str:
    closes = [2650.0 + 0.35 * i + (0.4 if i % 3 == 0 else -0.2) for i in range(20)]
    opens = [2649.8] + closes[:-1]
    highs = [max(o, c) + 0.3 for o, c in zip(opens, closes)]
    lows = [min(o, c) - 0.3 for o, c in zip(opens, closes)]
    return build_user_content(symbol="XAUUSD", opens=opens, highs=highs, lows=lows, closes=closes,
                              atr=0.9, spread_points=25, point=0.01, digits=2,
                              bar_close_utc=13 * 3600, sessions_open=["LONDON", "NEW_YORK"],
                              price_mode=price_mode)


async def run(provider, models, prices, price_mode: str, deadline: float, out=print) -> bool:
    ok_all = True
    content = sample_content(price_mode)
    for m in models:
        t0 = time.monotonic()
        try:
            await provider.verify_model(m)
            res = await provider.complete(m, content)
            sig = parse_signal(res.text)
        except ProviderError as exc:
            ok_all = False
            out(f"FAIL {m}: {exc.kind} (http {exc.status}) - {HINTS.get(exc.kind, 'see bridge audit log')}")
            continue
        except SignalParseError as exc:
            ok_all = False
            out(f"FAIL {m}: unusable output ({exc})")
            continue
        dt = time.monotonic() - t0
        pin, pout = prices.get(m) or max(prices.values())
        cost = (res.input_tokens * pin + res.output_tokens * pout) / 1e6
        slow = "  <-- slower than the decision deadline" if dt > deadline else ""
        out(f"OK   {m}: {sig.signal} conf={sig.confidence:.0f} latency={dt:.1f}s "
            f"tokens={res.input_tokens}+{res.output_tokens} est_cost=${cost:.4f} "
            f"(~${cost * 288:.2f}/day at one call per M5 bar){slow}")
        out(f"     reason: {sig.reason}")
        ok_all = ok_all and not slow
    return ok_all


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv()
    try:
        s = load_settings()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    if not s.has_key:
        print("ANTHROPIC_API_KEY is not set in .env", file=sys.stderr)
        return 2
    print(f"prompt {PROMPT_VERSION}, effort={s.effort}, price_mode={s.prompt_price_mode}, "
          f"models={', '.join(s.active_models)}")
    provider = AnthropicProvider(s.api_key, s.request_timeout, s.effort, s.max_tokens)
    ok = asyncio.run(run(provider, s.active_models, s.prices, s.prompt_price_mode, s.decision_deadline))
    print("SMOKE TEST PASSED" if ok else "SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
