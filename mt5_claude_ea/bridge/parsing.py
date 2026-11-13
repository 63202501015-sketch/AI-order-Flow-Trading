"""Strict parsing of model output. Anything unexpected raises -> caller returns HOLD."""
from __future__ import annotations

import json

from pydantic import ValidationError

from .models import AISignal

MAX_RAW_CHARS = 4000

# Schema sent as output_config.format. Structured outputs do not enforce numeric
# ranges or string lengths, so AISignal re-validates everything afterwards.
SIGNAL_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "signal": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["signal", "confidence", "reason"],
    "additionalProperties": False,
}


class SignalParseError(ValueError):
    pass


def _no_dupes(pairs):
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise SignalParseError("duplicate key")
        seen[k] = v
    return seen


def _reject_constant(_):
    raise SignalParseError("NaN/Infinity not allowed")


def parse_signal(raw: str) -> AISignal:
    """Accept exactly one JSON object with exactly signal/confidence/reason.

    No markdown stripping, no 'find the first brace' recovery, no defaults:
    a response that needs repairing is treated as a failed response.
    """
    if not isinstance(raw, str):
        raise SignalParseError("not text")
    raw = raw.strip()
    if not raw or len(raw) > MAX_RAW_CHARS:
        raise SignalParseError("empty or oversized response")
    try:
        obj = json.loads(raw, object_pairs_hook=_no_dupes, parse_constant=_reject_constant)
    except SignalParseError:
        raise
    except (ValueError, RecursionError) as exc:
        raise SignalParseError("invalid JSON") from exc
    if not isinstance(obj, dict):
        raise SignalParseError("not an object")
    try:
        return AISignal.model_validate(obj)
    except ValidationError as exc:
        raise SignalParseError("schema violation") from exc
