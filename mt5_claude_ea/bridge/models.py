"""Strictly typed request/response contracts for the local signal bridge."""
from __future__ import annotations

import math
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SYMBOL_RE = re.compile(r"^[A-Za-z0-9._#\-]{1,30}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._#\-]{8,96}$")
TIMEFRAME_SECONDS = 300  # M5 only
CANDLE_COUNT = 20
REASON_MAX = 300

SignalName = Literal["BUY", "SELL", "HOLD"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Candle(_Strict):
    time: int = Field(gt=0)  # bar OPEN time, broker-server epoch seconds
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)

    @field_validator("open", "high", "low", "close", mode="before")
    @classmethod
    def _int_to_float(cls, v):
        # JSON has one number type; "2650" must be accepted as 2650.0, bool must not.
        if isinstance(v, bool):
            raise ValueError("boolean is not a price")
        if isinstance(v, int):
            return float(v)
        return v

    @model_validator(mode="after")
    def _ohlc_consistent(self) -> "Candle":
        if self.high < max(self.open, self.close, self.low) or self.low > min(self.open, self.close):
            raise ValueError("malformed OHLC")
        return self


class SignalRequest(_Strict):
    request_id: str
    symbol: str
    timeframe: Literal["M5"]
    server_utc_offset_sec: int = Field(ge=-14 * 3600, le=14 * 3600)
    spread_points: float = Field(ge=0, le=100000)
    atr: float = Field(gt=0)
    digits: int = Field(ge=0, le=8)
    point: float = Field(gt=0)
    tick_size: float = Field(gt=0)
    contract_size: float = Field(gt=0)
    candles: list[Candle] = Field(min_length=CANDLE_COUNT, max_length=CANDLE_COUNT)

    @field_validator("spread_points", "atr", "point", "tick_size", "contract_size", mode="before")
    @classmethod
    def _int_to_float(cls, v):
        if isinstance(v, bool):
            raise ValueError("boolean is not a number")
        if isinstance(v, int):
            return float(v)
        return v

    @field_validator("request_id")
    @classmethod
    def _rid(cls, v: str) -> str:
        if not REQUEST_ID_RE.fullmatch(v):
            raise ValueError("bad request_id")
        return v

    @field_validator("symbol")
    @classmethod
    def _sym(cls, v: str) -> str:
        if not SYMBOL_RE.fullmatch(v):
            raise ValueError("bad symbol")
        return v

    @model_validator(mode="after")
    def _series(self) -> "SignalRequest":
        times = [c.time for c in self.candles]
        for a, b in zip(times, times[1:]):
            if b <= a:
                raise ValueError("candles not strictly ascending")
            if (b - a) % TIMEFRAME_SECONDS != 0:
                raise ValueError("candle spacing is not a multiple of M5")
        if any(t % TIMEFRAME_SECONDS != 0 for t in times):
            raise ValueError("candle time not aligned to M5")
        if not all(math.isfinite(x) for c in self.candles for x in (c.open, c.high, c.low, c.close)):
            raise ValueError("non-finite price")
        return self

    @property
    def bar_time(self) -> int:
        """Open time (server clock) of the most recent CLOSED bar."""
        return self.candles[-1].time

    @property
    def bar_close_utc(self) -> int:
        return self.bar_time + TIMEFRAME_SECONDS - self.server_utc_offset_sec


class AISignal(BaseModel):
    """What a model is allowed to say. Nothing else is ever read from model output."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    signal: SignalName
    confidence: float = Field(ge=0, le=100)
    reason: str

    @field_validator("confidence", mode="before")
    @classmethod
    def _int_to_float(cls, v):
        if isinstance(v, bool):
            raise ValueError("boolean is not a confidence")
        if isinstance(v, int):
            return float(v)
        return v

    @field_validator("reason")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = "".join(ch if ch.isprintable() else " " for ch in v)
        return v.strip()[:REASON_MAX]


class SignalResponse(BaseModel):
    """Flat JSON on purpose: the MQL5 parser accepts only a flat object."""

    model_config = ConfigDict(extra="forbid")
    request_id: str
    status: Literal["pending", "final"]
    signal: SignalName = "HOLD"
    confidence: float = Field(default=0.0, ge=0, le=100)
    reason: str = Field(default="", max_length=REASON_MAX)
    bar_time: int = 0
    source: str = ""  # single | vote | disabled | error | circuit_open | stale | restart


def hold(request_id: str, bar_time: int, reason: str, source: str = "error",
         status: Literal["pending", "final"] = "final") -> SignalResponse:
    return SignalResponse(request_id=request_id, status=status, signal="HOLD", confidence=0.0,
                          reason=reason[:REASON_MAX], bar_time=bar_time, source=source)


class VoteRecord(BaseModel):
    model: str
    ok: bool
    signal: Optional[SignalName] = None
    confidence: Optional[float] = None
    error: Optional[str] = None
    attempts: int = 0
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    est_cost_usd: float = 0.0
