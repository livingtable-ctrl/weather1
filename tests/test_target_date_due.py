"""Tests for main._target_date_due (backlog.txt "RAIN / SNOW / HURRICANE
MARKETS" Step 2, Bug A fix): the shared date-comparison helper for
cmd_watch_settle's _pending() and the main-menu "due today" banner. Both
call sites used to compare target_date as a raw string against today's ISO
string -- a non-day-granular ISO value (e.g. a month-only string) would
compare as a string prefix and sort incorrectly against a full
"YYYY-MM-DD" value.

AUD-0017 (2026-08-18 max-depth forensic audit): target_date_str is
CITY-LOCAL (weather_markets.py's analyze_trade stores
parse_city_date().isoformat()), but both call sites used to compare it
against utils.utc_today() -- the one target_date comparison site the
0100bffe/6364b38b fix sweep missed. Fixed by changing the signature from
(target_date_str, today_date) to (target_date_str, city), self-computing
a ZoneInfo-based city-local "today" internally, mirroring
_feature_importance_days_out's established pattern exactly (see
test_feature_importance_days_out.py for the sibling test suite this one
is modeled on).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import _target_date_due


class TestTargetDateDue:
    def test_none_is_not_due(self):
        assert _target_date_due(None, "NYC") is False

    def test_empty_string_is_not_due(self):
        assert _target_date_due("", "NYC") is False

    def test_past_date_is_due(self):
        mock_dt = Mock()
        mock_dt.now.return_value = datetime(2026, 7, 20)
        with patch("main.datetime", mock_dt):
            assert _target_date_due("2026-07-19", "NYC") is True

    def test_today_is_due(self):
        mock_dt = Mock()
        mock_dt.now.return_value = datetime(2026, 7, 20)
        with patch("main.datetime", mock_dt):
            assert _target_date_due("2026-07-20", "NYC") is True

    def test_future_date_is_not_due(self):
        mock_dt = Mock()
        mock_dt.now.return_value = datetime(2026, 7, 20)
        with patch("main.datetime", mock_dt):
            assert _target_date_due("2026-07-21", "NYC") is False

    def test_unparseable_string_falls_back_to_string_compare_no_crash(self):
        # Must not raise -- the whole point of the try/except fallback.
        mock_dt = Mock()
        mock_dt.now.return_value = datetime(2026, 7, 20)
        with patch("main.datetime", mock_dt):
            result = _target_date_due("not-a-date", "NYC")
        assert isinstance(result, bool)

    def test_unknown_city_falls_back_to_america_new_york(self):
        """A city missing from _CITY_TZ (e.g. None, for hurricane/storm_order
        tickers with no per-city target) must fall back to America/New_York,
        mirroring _feature_importance_days_out's own `city or ""` coercion
        and _CITY_TZ.get default.

        Opus-review-caught: the original version of this test used a plain
        Mock whose .now() returns the same value for ANY tz argument, so it
        could not tell "resolved to NY" apart from "resolved to anything, or
        nothing at all" -- changing the fallback default to a different zone
        left every assertion here passing. Fixed with a fixed-instant
        subclass at 2026-07-10 02:00 UTC, where NY (EDT, UTC-4) is still
        2026-07-09 while UTC itself has already rolled to 07-10 -- a target
        of 07-10 is due under a UTC-anchored (or wrong-zone) comparison but
        NOT YET due under a genuine NY-anchored one, so this only passes if
        the fallback really resolves to America/New_York specifically."""
        fixed_instant = datetime(2026, 7, 10, 2, 0, tzinfo=UTC)

        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return fixed_instant.replace(tzinfo=None)
                return fixed_instant.astimezone(tz)

        with patch("main.datetime", _FixedDatetime):
            # NY-local today is still 07-09 at this instant -- 07-10 is NOT
            # yet due (a UTC-anchored or wrong-zone fallback would say True).
            assert _target_date_due("2026-07-10", None) is False
            # 07-09 is NY's actual local today -- due.
            assert _target_date_due("2026-07-09", None) is True

    def test_zoneinfo_failure_falls_back_to_utc(self):
        """If ZoneInfo construction raises for any reason, the helper must
        fall back to UTC's today rather than propagate the exception or
        return a wrong value silently.

        Opus-review-caught: a plain Mock's .now() ignores its tz argument
        entirely, so it can't actually exercise "real ZoneInfo conversion"
        vs "UTC fallback" as distinct code paths -- both would have returned
        the same mocked value even if the fallback were broken. Fixed with a
        fixed-instant subclass (matching this file's other rollover tests)
        at 2026-07-20 00:00 UTC, where Phoenix (UTC-7, no DST) is genuinely
        still 2026-07-19 -- if the fallback ever silently used a real
        ZoneInfo(Phoenix) conversion instead of UTC, "2026-07-20" would flip
        from due to not-yet-due."""
        fixed_instant = datetime(2026, 7, 20, 0, 0, tzinfo=UTC)

        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return fixed_instant.replace(tzinfo=None)
                return fixed_instant.astimezone(tz)

        with patch("zoneinfo.ZoneInfo", side_effect=RuntimeError("boom")):
            with patch("main.datetime", _FixedDatetime):
                # UTC's own today (07-20) is used, NOT Phoenix's real local
                # today (07-19, which the failed ZoneInfo() call would have
                # produced had it not raised).
                assert _target_date_due("2026-07-20", "Phoenix") is True
                assert _target_date_due("2026-07-21", "Phoenix") is False

    def test_utc_rollover_window_uses_city_local_today(self):
        """Regression for the real bug (AUD-0017). At 2026-07-10 02:00 UTC:
        UTC has already rolled over to 2026-07-10, but LA (UTC-7, PDT) is
        still 2026-07-09. Using "LA" (whose zone genuinely differs from both
        UTC and the function's own America/New_York fallback default)
        proves the fix does a REAL per-city ZoneInfo lookup: a trade whose
        target_date is 2026-07-09 must still read as due (LA's actual local
        today), where a UTC-anchored comparison would wrongly report it as
        not-yet-due (target 07-09 < UTC today 07-10 would still say due=True
        for THIS case, so the sharper regression is the inverse below)."""
        fixed_instant = datetime(2026, 7, 10, 2, 0, tzinfo=UTC)

        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return fixed_instant.replace(tzinfo=None)
                return fixed_instant.astimezone(tz)

        with patch("main.datetime", _FixedDatetime):
            # UTC has rolled to 07-10; LA local time has not. A target_date
            # of 07-10 is NOT yet due in LA's own local calendar, even
            # though it already is in UTC's.
            assert _target_date_due("2026-07-10", "LA") is False
            # 07-09 is LA's actual local today -- due.
            assert _target_date_due("2026-07-09", "LA") is True

    def test_utc_rollover_window_matches_analyze_trade_local_today(self):
        """Cross-check against weather_markets.py's own post-fix local-today
        computation for the same city/instant, proving this helper's due-ness
        is consistent with analyze_trade's gate rather than independently
        reimplementing (and potentially disagreeing with) the same
        city-local-today concept.

        Opus-review-caught: the original version only asserted the True case
        (target == local-today), which a UTC-anchored comparison ALSO
        returns True for at this exact instant (07-09 <= UTC's already-rolled
        07-10) -- so it passed under the pre-fix code too and proved nothing
        by itself. Added the discriminating case: local-today + 1 day must
        NOT be due yet, which a UTC-anchored comparison would have wrongly
        called due."""
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        from weather_markets import _CITY_TZ as _wm_city_tz

        fixed_instant = datetime(2026, 7, 10, 2, 0, tzinfo=UTC)

        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return fixed_instant.replace(tzinfo=None)
                return fixed_instant.astimezone(tz)

        analyze_trade_local_today = fixed_instant.astimezone(
            ZoneInfo(_wm_city_tz.get("LA", "America/New_York"))
        ).date()

        with patch("main.datetime", _FixedDatetime):
            assert _target_date_due(analyze_trade_local_today.isoformat(), "LA") is True
            # The discriminating case: LA's local tomorrow is NOT due yet,
            # even though UTC has already rolled over to it.
            not_yet_due = analyze_trade_local_today + timedelta(days=1)
            assert _target_date_due(not_yet_due.isoformat(), "LA") is False
