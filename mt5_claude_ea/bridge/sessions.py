"""Trading sessions defined in IANA time zones (DST handled by zoneinfo/tzdata).

The bridge only reports the session in its audit log; the EA enforces the gate itself
(EA/Include/ClaudeEA/Sessions.mqh) because the EA must not depend on the bridge for guards.
refmodel/sessions.py mirrors the EA's calendar arithmetic and is tested against this module."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Session:
    name: str
    tz: str
    start_min: int  # minutes after local midnight, inclusive
    end_min: int    # exclusive

    def is_open(self, utc_epoch: int) -> bool:
        local = datetime.fromtimestamp(utc_epoch, timezone.utc).astimezone(ZoneInfo(self.tz))
        if local.weekday() >= 5:
            return False
        m = local.hour * 60 + local.minute
        return self.start_min <= m < self.end_min


LONDON = Session("LONDON", "Europe/London", 8 * 60, 17 * 60)
NEW_YORK = Session("NEW_YORK", "America/New_York", 8 * 60, 17 * 60)
DEFAULT_SESSIONS = (LONDON, NEW_YORK)  # Asia is blocked by default: simply not listed.


def open_sessions(utc_epoch: int, sessions=DEFAULT_SESSIONS) -> list[str]:
    return [s.name for s in sessions if s.is_open(utc_epoch)]
