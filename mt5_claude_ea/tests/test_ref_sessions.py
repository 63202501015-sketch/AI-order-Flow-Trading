from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from bridge.sessions import LONDON, NEW_YORK
from refmodel.sessions import (eu_dst, london_offset, new_york_offset, server_to_utc,
                               session_allowed, us_dst)


def test_offsets_match_iana_every_hour_2015_2040():
    lon, ny = ZoneInfo("Europe/London"), ZoneInfo("America/New_York")
    t = datetime(2015, 1, 1, tzinfo=timezone.utc)
    end = datetime(2040, 1, 1, tzinfo=timezone.utc)
    n = 0
    while t < end:
        ts = int(t.timestamp())
        assert london_offset(ts) == t.astimezone(lon).utcoffset().total_seconds(), t
        assert new_york_offset(ts) == t.astimezone(ny).utcoffset().total_seconds(), t
        t += timedelta(hours=1)
        n += 1
    assert n > 200000


def test_session_gate_matches_iana_sessions_2024_2027():
    t = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2027, 1, 1, tzinfo=timezone.utc)
    while t < end:
        ts = int(t.timestamp())
        expected = LONDON.is_open(ts) or NEW_YORK.is_open(ts)
        assert session_allowed(ts)[0] == expected, t
        t += timedelta(minutes=15)


def ts(y, mo, d, h, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp())


def test_dst_transition_edges_2026():
    assert not eu_dst(ts(2026, 3, 29, 0, 59)) and eu_dst(ts(2026, 3, 29, 1, 0))
    assert eu_dst(ts(2026, 10, 25, 0, 59)) and not eu_dst(ts(2026, 10, 25, 1, 0))
    assert not us_dst(ts(2026, 3, 8, 6, 59)) and us_dst(ts(2026, 3, 8, 7, 0))
    assert us_dst(ts(2026, 11, 1, 5, 59)) and not us_dst(ts(2026, 11, 1, 6, 0))


def test_london_open_shifts_with_dst():
    # 08:00 London = 08:00 UTC in winter, 07:00 UTC in summer
    assert session_allowed(ts(2026, 1, 14, 7, 30), new_york=False)[0] is False
    assert session_allowed(ts(2026, 1, 14, 8, 0), new_york=False) == (True, "LONDON")
    assert session_allowed(ts(2026, 7, 15, 7, 0), new_york=False) == (True, "LONDON")
    assert session_allowed(ts(2026, 7, 15, 16, 0), new_york=False)[0] is False


def test_us_eu_dst_gap_weeks():
    # 2026-03-16: US already on DST, EU not yet. NY 08:00 = 12:00 UTC; London still UTC.
    assert session_allowed(ts(2026, 3, 16, 11, 59), london=False)[0] is False
    assert session_allowed(ts(2026, 3, 16, 12, 0), london=False) == (True, "NEW_YORK")


def test_asia_blocked_by_default_and_weekend_closed():
    asia = ts(2026, 7, 15, 2, 0)                      # 11:00 Tokyo, 03:00 London, 22:00 NY (prev day)
    assert session_allowed(asia) == (False, "NONE")
    assert session_allowed(asia, asia=True) == (True, "ASIA")
    assert session_allowed(ts(2026, 7, 18, 12, 0))[0] is False      # Saturday
    assert session_allowed(ts(2026, 7, 19, 12, 0))[0] is False      # Sunday


def test_server_to_utc_manual_modes():
    # Typical broker: UTC+2 winter / UTC+3 summer following US DST
    assert server_to_utc(ts(2026, 1, 14, 12, 0), 2, "US") == ts(2026, 1, 14, 10, 0)
    assert server_to_utc(ts(2026, 7, 15, 12, 0), 2, "US") == ts(2026, 7, 15, 9, 0)
    assert server_to_utc(ts(2026, 3, 16, 12, 0), 2, "US") == ts(2026, 3, 16, 9, 0)
    assert server_to_utc(ts(2026, 3, 16, 12, 0), 2, "EU") == ts(2026, 3, 16, 10, 0)
    assert server_to_utc(ts(2026, 7, 15, 12, 0), 0, "NONE") == ts(2026, 7, 15, 12, 0)
