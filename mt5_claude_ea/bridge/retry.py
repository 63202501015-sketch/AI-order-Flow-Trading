"""Exponential backoff with full jitter + circuit breaker. Runs only in the bridge worker."""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, TypeVar

T = TypeVar("T")


class ProviderError(Exception):
    """Normalised provider failure. `detail` must never contain secrets."""

    def __init__(self, kind: str, status: Optional[int] = None, retryable: bool = False,
                 retry_after: Optional[float] = None, detail: str = ""):
        super().__init__(f"{kind}:{status}")
        self.kind = kind            # auth | rate_limit | overloaded | server | timeout | connection | bad_request | invalid_output | refusal | not_found | unknown
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after
        self.detail = detail


class CircuitOpenError(Exception):
    pass


@dataclass
class RetryPolicy:
    max_retries: int = 5        # retries AFTER the first attempt
    base_delay: float = 0.5
    max_delay: float = 8.0
    retry_after_cap: float = 15.0

    def delay(self, attempt: int, rng: random.Random, retry_after: Optional[float] = None) -> float:
        """Full jitter: U(0, min(max_delay, base * 2**attempt)); honours Retry-After as a floor."""
        ceiling = min(self.max_delay, self.base_delay * (2 ** attempt))
        d = rng.uniform(0.0, ceiling)
        if retry_after is not None and retry_after > 0:
            d = max(d, min(retry_after, self.retry_after_cap))
        return d


class CircuitBreaker:
    """closed -> open after N consecutive failures -> half-open (one probe) after cooldown."""

    def __init__(self, failure_threshold: int = 5, cooldown_sec: float = 300.0,
                 clock: Callable[[], float] = time.monotonic):
        self.failure_threshold = failure_threshold
        self.cooldown_sec = cooldown_sec
        self._clock = clock
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._probe_in_flight = False

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self.cooldown_sec:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        s = self.state
        if s == "closed":
            return True
        if s == "half_open" and not self._probe_in_flight:
            self._probe_in_flight = True
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._probe_in_flight = False

    def record_failure(self, fatal: bool = False) -> None:
        self._probe_in_flight = False
        self._failures += 1
        if fatal or self._failures >= self.failure_threshold or self._opened_at is not None:
            self._opened_at = self._clock()


async def call_with_retry(fn: Callable[[], Awaitable[T]], policy: RetryPolicy, *,
                          deadline: float, rng: random.Random,
                          sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                          clock: Callable[[], float] = time.monotonic,
                          on_attempt: Optional[Callable[[int], None]] = None) -> T:
    """Call fn; retry only ProviderError(retryable=True); never sleep past `deadline`."""
    attempt = 0
    while True:
        if on_attempt:
            on_attempt(attempt + 1)
        try:
            return await fn()
        except ProviderError as exc:
            if not exc.retryable or attempt >= policy.max_retries:
                raise
            d = policy.delay(attempt, rng, exc.retry_after)
            if clock() + d >= deadline:
                raise ProviderError("timeout", exc.status, False, detail="deadline exceeded during backoff") from exc
            await sleep(d)
            attempt += 1
