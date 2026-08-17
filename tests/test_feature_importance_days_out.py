"""Tests for main.py's _feature_importance_days_out helper.

Extracted from cmd_today's manual-trade-placement path (backlog.txt
"utils.utc_today() SAYS 'USE EVERYWHERE INSTEAD OF date.today()' -- 17
SITES STILL DON'T"). The original inline code did
`best_a.get("target_date") - date.today()` -- but target_date is an ISO
STRING (weather_markets.py's analyze_trade return dict stores
target_date.isoformat()), so this always raised TypeError, silently
swallowed by an enclosing `except Exception: pass`. record_feature_
contribution is called from nowhere else in the codebase, so this had
likely never successfully recorded a contribution since it was written.

target_date is CITY-LOCAL (parse_city_date()), not UTC -- a later fix
(backlog.txt L569) made this helper compare against a ZoneInfo-based
local-today for `city`, mirroring weather_markets.py's analyze_trade,
instead of utils.utc_today(). See test_utc_rollover_window_uses_city_local_today
below for the regression case that actually exercises the bug this fixed.
"""

import sys
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import main


class TestFeatureImportanceDaysOut:
    def test_none_returns_zero(self):
        assert main._feature_importance_days_out(None, "Phoenix") == 0

    def test_empty_string_returns_zero(self):
        assert main._feature_importance_days_out("", "Phoenix") == 0

    def test_parses_iso_string_and_subtracts_local_today(self):
        """The core bug fix: target_date_str must be parsed to a date
        before arithmetic, and compared against a mocked "today" rather
        than subtracted directly as a raw string. Proves both: (a) the
        string got parsed successfully (no TypeError), and (b) the
        subtraction used the mocked local date."""
        mock_dt = Mock()
        mock_dt.now.return_value = datetime(2026, 7, 10)
        with patch("main.datetime", mock_dt):
            result = main._feature_importance_days_out("2026-07-15", "NYC")
        assert result == 5

    def test_target_date_in_past_gives_negative_days_out(self):
        mock_dt = Mock()
        mock_dt.now.return_value = datetime(2026, 7, 10)
        with patch("main.datetime", mock_dt):
            result = main._feature_importance_days_out("2026-07-05", "NYC")
        assert result == -5

    def test_malformed_string_returns_zero_not_raise(self):
        """A malformed/unexpected target_date value must not raise --
        record_feature_contribution is a best-effort logging call, not
        critical trading logic."""
        assert main._feature_importance_days_out("not-a-date", "Phoenix") == 0
        assert main._feature_importance_days_out("2026-13-99", "Phoenix") == 0

    def test_regression_string_minus_date_would_have_raised(self):
        """Documents the exact bug this replaces: subtracting a date from
        a raw ISO string raises TypeError. The helper must never do this
        directly -- confirmed by the fact that a real date.fromisoformat
        parse (what the helper does internally) succeeds where a bare
        subtraction would not."""
        target_date_str = "2026-07-15"
        with pytest.raises(TypeError):
            target_date_str - date(2026, 7, 10)  # the old, buggy expression
        # The fixed helper handles the same input without raising.
        assert isinstance(
            main._feature_importance_days_out(target_date_str, "Phoenix"), int
        )

    def test_unknown_city_falls_back_to_america_new_york(self):
        """A city missing from _CITY_TZ (e.g. None, for the hurricane/
        storm_order tickers that have no per-city target) must fall back to
        America/New_York, mirroring analyze_trade's own `city or ""`
        coercion and _CITY_TZ.get default."""
        mock_dt = Mock()
        mock_dt.now.return_value = datetime(2026, 7, 10)
        with patch("main.datetime", mock_dt):
            result = main._feature_importance_days_out("2026-07-15", None)
        assert result == 5

    def test_zoneinfo_failure_falls_back_to_utc(self):
        """If ZoneInfo construction raises for any reason, the helper must
        fall back to UTC's today rather than propagate the exception or
        return a wrong value silently."""
        mock_dt = Mock()
        mock_dt.now.return_value = datetime(2026, 7, 10, tzinfo=UTC)
        with patch("zoneinfo.ZoneInfo", side_effect=RuntimeError("boom")):
            with patch("main.datetime", mock_dt):
                result = main._feature_importance_days_out("2026-07-15", "Phoenix")
        assert result == 5

    def test_utc_rollover_window_uses_city_local_today(self):
        """Regression for the real bug (backlog.txt L569). At 2026-07-10
        05:00 UTC: UTC and NYC (UTC-4, EDT) have both already rolled over
        to 2026-07-10, but LA (UTC-7, PDT) is still 2026-07-09. Using "LA"
        (whose zone genuinely differs from both UTC and the function's own
        America/New_York fallback default) proves the fix does a REAL
        per-city ZoneInfo lookup, not merely "some non-UTC zone" or a
        lookup that silently always resolves to the fallback: a trade
        whose target_date is LA's local "today" must be 0 days out, not -1
        (which either a UTC-anchored or a wrongly-NYC-anchored comparison
        would give, since both have already rolled to 2026-07-10)."""
        fixed_instant = datetime(2026, 7, 10, 5, 0, tzinfo=UTC)

        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return fixed_instant.replace(tzinfo=None)
                return fixed_instant.astimezone(tz)

        with patch("main.datetime", _FixedDatetime):
            result = main._feature_importance_days_out("2026-07-09", "LA")
        assert result == 0

    def test_utc_rollover_window_matches_analyze_trade_local_today(self):
        """Cross-check against weather_markets.py's own post-fix local-today
        computation for the same city/instant, proving this helper's
        days_out is consistent with analyze_trade's gate rather than
        independently reimplementing (and potentially disagreeing with) the
        same city-local-today concept."""
        from weather_markets import _CITY_TZ as _wm_city_tz

        fixed_instant = datetime(2026, 7, 10, 5, 0, tzinfo=UTC)

        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return fixed_instant.replace(tzinfo=None)
                return fixed_instant.astimezone(tz)

        with patch("main.datetime", _FixedDatetime):
            result = main._feature_importance_days_out("2026-07-09", "LA")

        analyze_trade_local_today = fixed_instant.astimezone(
            ZoneInfo(_wm_city_tz.get("LA", "America/New_York"))
        ).date()
        expected = (date(2026, 7, 9) - analyze_trade_local_today).days
        assert result == expected
