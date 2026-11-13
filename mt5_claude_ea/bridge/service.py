"""Decision engine: one bounded, audited decision per request id. Every failure path ends in HOLD."""
from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Awaitable, Callable, Optional

from .audit import AuditLog
from .config import Settings
from .models import AISignal, SignalRequest, SignalResponse, VoteRecord, hold
from .parsing import SignalParseError, parse_signal
from .providers import Provider
from .retry import CircuitBreaker, ProviderError, RetryPolicy, call_with_retry
from .sessions import open_sessions
from .store import DedupStore
from .voting import tally


def build_user_content(req: SignalRequest) -> str:
    """Numbers only, rebuilt from validated fields; no free text from the client reaches the model
    except the symbol, which is regex- and allowlist-checked."""
    return json.dumps({
        "symbol": req.symbol,
        "timeframe": req.timeframe,
        "atr14": req.atr,
        "spread_points": req.spread_points,
        "digits": req.digits,
        "point": req.point,
        "tick_size": req.tick_size,
        "contract_size": req.contract_size,
        "candles_oldest_first": [
            {"t": c.time, "o": c.open, "h": c.high, "l": c.low, "c": c.close} for c in req.candles
        ],
    }, separators=(",", ":"), allow_nan=False)


class Decider:
    def __init__(self, settings: Settings, provider: Optional[Provider], store: DedupStore,
                 audit: AuditLog, *, rng: Optional[random.Random] = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time):
        self.s = settings
        self.provider = provider
        self.store = store
        self.audit = audit
        self.rng = rng or random.Random()
        self.sleep = sleep
        self.clock = clock
        self.wall_clock = wall_clock
        self.breaker = CircuitBreaker(settings.cb_threshold, settings.cb_cooldown, clock)
        self.policy = RetryPolicy(settings.max_retries, settings.backoff_base, settings.backoff_max)
        self._verified: dict[str, bool] = {}

    # ---- synchronous pre-checks (no AI call) -------------------------------------------
    def precheck(self, req: SignalRequest) -> Optional[SignalResponse]:
        rid, bt = req.request_id, req.bar_time
        if req.symbol not in self.s.symbol_allowlist:
            return hold(rid, bt, "symbol not in bridge allowlist", "rejected")
        age = self.wall_clock() - req.bar_close_utc
        if age < -self.s.clock_skew:
            return hold(rid, bt, "bar close is in the future (clock/offset mismatch)", "rejected")
        if age > self.s.stale_max_age:
            return hold(rid, bt, "stale bar", "stale")
        if not self.s.ai_enabled:
            return hold(rid, bt, "AI disabled (AI_ENABLED=false)", "disabled")
        if not self.s.has_key or self.provider is None:
            return hold(rid, bt, "AI provider not configured", "disabled")
        return None

    # ---- model verification --------------------------------------------------------------
    async def _models_ok(self) -> tuple[bool, str]:
        for m in self.s.active_models:
            state = self._verified.get(m)
            if state is True:
                continue
            if state is False:
                return False, f"model id not available: {m}"
            try:
                await asyncio.wait_for(self.provider.verify_model(m), self.s.request_timeout + 1)
                self._verified[m] = True
            except ProviderError as exc:
                if exc.kind == "not_found":
                    self._verified[m] = False  # permanent until restart/config change
                    return False, f"model id not available: {m}"
                return False, f"model verification failed ({exc.kind})"
            except asyncio.TimeoutError:
                return False, "model verification timed out"
        return True, ""

    # ---- one model, with retries ---------------------------------------------------------
    async def _ask(self, model: str, content: str, deadline: float) -> tuple[Optional[AISignal], VoteRecord]:
        rec = VoteRecord(model=model, ok=False)
        t0 = self.clock()

        def on_attempt(n: int) -> None:
            rec.attempts = n

        async def once() -> AISignal:
            budget = min(self.s.request_timeout + 1, deadline - self.clock())
            if budget <= 0:
                raise ProviderError("timeout", None, False, detail="deadline exceeded")
            try:
                res = await asyncio.wait_for(self.provider.complete(model, content), budget)
            except asyncio.TimeoutError:
                raise ProviderError("timeout", None, True) from None
            rec.input_tokens += res.input_tokens
            rec.output_tokens += res.output_tokens
            try:
                return parse_signal(res.text)
            except SignalParseError as exc:
                raise ProviderError("invalid_output", 200, False, detail=str(exc)) from None

        sig: Optional[AISignal] = None
        try:
            sig = await call_with_retry(once, self.policy, deadline=deadline, rng=self.rng,
                                        sleep=self.sleep, clock=self.clock, on_attempt=on_attempt)
            rec.ok, rec.signal, rec.confidence = True, sig.signal, sig.confidence
        except ProviderError as exc:
            rec.error = f"{exc.kind}:{exc.status}" + (f" {exc.detail}" if exc.detail else "")
        except Exception as exc:  # noqa: BLE001 - unknown failure is still just a failed vote
            rec.error = f"unexpected:{type(exc).__name__}"
        rec.latency_ms = int((self.clock() - t0) * 1000)
        pin, pout = self.s.prices.get(model, (0.0, 0.0))
        rec.est_cost_usd = round((rec.input_tokens * pin + rec.output_tokens * pout) / 1e6, 6)
        return sig, rec

    # ---- full decision -------------------------------------------------------------------
    async def decide(self, req: SignalRequest) -> SignalResponse:
        t0 = self.clock()
        votes: list[VoteRecord] = []
        try:
            resp = await self._decide(req, votes)
        except Exception as exc:  # noqa: BLE001
            resp = hold(req.request_id, req.bar_time, f"internal error ({type(exc).__name__})")
        self.finalize(req, resp, votes, int((self.clock() - t0) * 1000))
        return resp

    async def _decide(self, req: SignalRequest, votes: list[VoteRecord]) -> SignalResponse:
        rid, bt = req.request_id, req.bar_time
        if not self.breaker.allow():
            return hold(rid, bt, "circuit breaker open", "circuit_open")
        ok, why = await self._models_ok()
        if not ok:
            self.breaker.record_failure(fatal="not available" in why)
            return hold(rid, bt, why)
        deadline = self.clock() + self.s.decision_deadline
        content = build_user_content(req)
        results = await asyncio.gather(*(self._ask(m, content, deadline) for m in self.s.active_models))
        votes.extend(r for _, r in results)
        failed = [r for _, r in results if not r.ok]
        if failed:
            self.breaker.record_failure(fatal=any((r.error or "").startswith("auth") for r in failed))
            return hold(rid, bt, "AI unavailable or invalid: " + "; ".join(
                f"{r.model}={(r.error or '').split(' ')[0]}" for r in failed))
        self.breaker.record_success()
        if self.s.voting_enabled:
            out = tally([s for s, _ in results])
            return SignalResponse(request_id=rid, status="final", signal=out.signal,
                                  confidence=round(out.confidence, 2), reason=out.reason,
                                  bar_time=bt, source="vote")
        sig = results[0][0]
        return SignalResponse(request_id=rid, status="final", signal=sig.signal,
                              confidence=round(sig.confidence, 2), reason=sig.reason,
                              bar_time=bt, source="single")

    def finalize(self, req: SignalRequest, resp: SignalResponse, votes: list[VoteRecord],
                 latency_ms: int) -> None:
        self.store.finish(req.request_id, resp.model_dump_json())
        names = {v.signal for v in votes if v.ok}
        self.audit.write(
            "decision", request_id=req.request_id, symbol=req.symbol, bar_time=req.bar_time,
            bar_close_utc=req.bar_close_utc, sessions_open=open_sessions(req.bar_close_utc),
            model_ids=list(self.s.active_models), voting=self.s.voting_enabled,
            votes=[v.model_dump() for v in votes], disagreement=len(names) > 1,
            signal=resp.signal, confidence=resp.confidence, source=resp.source, reason=resp.reason,
            latency_ms=latency_ms, est_cost_usd=round(sum(v.est_cost_usd for v in votes), 6),
            circuit=self.breaker.state, spread_points=req.spread_points, atr=req.atr)
