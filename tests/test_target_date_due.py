"""Tests for main._target_date_due (backlog.txt "RAIN / SNOW / HURRICANE
MARKETS" Step 2, Bug A fix): the shared date-comparison helper for
cmd_watch_settle's _pending() and the main-menu "due today" banner. Both
call sites used to compare target_date as a raw string against today's ISO
string -- a non-day-granular ISO value (e.g. a month-only string) would
compare as a string prefix and sort incorrectly against a full
"YYYY-MM-DD" value.
"""

from __future__ import annotations

from datetime import date, timedelta

from main import _target_date_due


class TestTargetDateDue:
    def test_none_is_not_due(self):
        assert _target_date_due(None, date(2026, 7, 20)) is False

    def test_empty_string_is_not_due(self):
        assert _target_date_due("", date(2026, 7, 20)) is False

    def test_past_date_is_due(self):
        today = date(2026, 7, 20)
        assert _target_date_due("2026-07-19", today) is True

    def test_today_is_due(self):
        today = date(2026, 7, 20)
        assert _target_date_due("2026-07-20", today) is True

    def test_future_date_is_not_due(self):
        today = date(2026, 7, 20)
        assert _target_date_due("2026-07-21", today) is False

    def test_unparseable_string_falls_back_to_string_compare_no_crash(self):
        # Must not raise -- the whole point of the try/except fallback.
        result = _target_date_due("not-a-date", date(2026, 7, 20))
        assert isinstance(result, bool)

    def test_boundary_around_today(self):
        today = date.today()
        yesterday = (today - timedelta(days=1)).isoformat()
        tomorrow = (today + timedelta(days=1)).isoformat()
        assert _target_date_due(yesterday, today) is True
        assert _target_date_due(today.isoformat(), today) is True
        assert _target_date_due(tomorrow, today) is False
