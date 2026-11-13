"""DST-aware London / New York sessions using calendar arithmetic only (MQL5 has no IANA
database). Mirrors Sessions.mqh; tested against zoneinfo in tests/test_ref_sessions.py."""
from __future__ import annotations

import calendar
from datetime import datetime, timezone

HOUR = 3600


def _utc(y, mo, d, h=0) -> int:
    return calendar.timegm((y, mo, d, h, 0, 0))


def _nth_sunday(year: int, month: int, n: int) -> int:
    """Day of month of the n-th Sunday (n>=1)."""
    first_wd = datetime(year, month, 1).weekday()        # Mon=0 .. Sun=6
    return 1 + (6 - first_wd) % 7 + 7 * (n - 1)


def _last_sunday(year: int, month: int) -> int:
    last = calendar.monthrange(year, month)[1]
    wd = datetime(year, month, last).weekday()
    return last - (wd + 1) % 7


def eu_dst(utc: int) -> bool:
    """EU/UK summer time: last Sunday of March 01:00 UTC -> last Sunday of October 01:00 UTC."""
    y = datetime.fromtimestamp(utc, timezone.utc).year
    return _utc(y, 3, _last_sunday(y, 3), 1) <= utc < _utc(y, 10, _last_sunday(y, 10), 1)


def us_dst(utc: int) -> bool:
    """US daylight time: 2nd Sunday of March 02:00 EST (07:00 UTC) -> 1st Sunday of Nov 02:00 EDT (06:00 UTC)."""
    y = datetime.fromtimestamp(utc, timezone.utc).year
    return _utc(y, 3, _nth_sunday(y, 3, 2), 7) <= utc < _utc(y, 11, _nth_sunday(y, 11, 1), 6)


def london_offset(utc: int) -> int:
    return HOUR if eu_dst(utc) else 0


def new_york_offset(utc: int) -> int:
    return -4 * HOUR if us_dst(utc) else -5 * HOUR


def _in_window(utc: int, offset: int, start_min: int, end_min: int) -> bool:
    local = utc + offset
    dow = (local // 86400 + 4) % 7          # 0=Sunday (1970-01-01 was a Thursday)
    if dow in (0, 6):
        return False
    minute = (local % 86400) // 60
    return start_min <= minute < end_min


def session_allowed(utc: int, *, london=True, new_york=True, asia=False,
                    london_win=(480, 1020), ny_win=(480, 1020), asia_win=(540, 900)) -> tuple[bool, str]:
    """Asia (Tokyo, UTC+9, no DST) is blocked unless explicitly enabled."""
    if london and _in_window(utc, london_offset(utc), *london_win):
        return True, "LONDON"
    if new_york and _in_window(utc, new_york_offset(utc), *ny_win):
        return True, "NEW_YORK"
    if asia and _in_window(utc, 9 * HOUR, *asia_win):
        return True, "ASIA"
    return False, "NONE"


def server_to_utc(server: int, std_offset_hours: int, dst_rule: str = "NONE") -> int:
    """Manual broker-clock conversion. dst_rule: NONE | EU | US (adds +1h while that rule is in DST)."""
    rule = {"NONE": lambda _: False, "EU": eu_dst, "US": us_dst}[dst_rule]
    utc = server - std_offset_hours * HOUR
    utc = server - (std_offset_hours + (1 if rule(utc) else 0)) * HOUR
    return server - (std_offset_hours + (1 if rule(utc) else 0)) * HOUR
