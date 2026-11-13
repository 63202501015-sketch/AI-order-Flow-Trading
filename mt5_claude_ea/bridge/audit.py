"""Append-only JSONL audit log with secret redaction."""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Iterable

_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)(x-api-key|authorization|x-bridge-token|api[_-]?key|token)(\"?\s*[:=]\s*\"?)([^\s\",}]+)"),
]


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    for s in secrets:
        if s and len(s) >= 6:
            text = text.replace(s, "[REDACTED]")
    text = _PATTERNS[0].sub("[REDACTED]", text)
    text = _PATTERNS[1].sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", text)
    return text


class AuditLog:
    def __init__(self, path: str, secrets: Iterable[str] = ()):
        self.path = path
        self._secrets = [s for s in secrets if s]
        self._lock = threading.Lock()
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)

    def write(self, event: str, **fields: Any) -> None:
        rec = {"ts_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "event": event}
        rec.update(fields)
        line = redact(json.dumps(rec, separators=(",", ":"), default=str, allow_nan=False), self._secrets)
        with self._lock, open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
