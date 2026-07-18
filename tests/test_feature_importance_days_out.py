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
"""

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import main


class TestFeatureImportanceDaysOut:
    def test_none_returns_zero(self):
        assert main._feature_importance_days_out(None) == 0

    def test_empty_string_returns_zero(self):
        assert main._feature_importance_days_out("") == 0

    def test_parses_iso_string_and_subtracts_utc_today(self):
        """The core bug fix: target_date_str must be parsed to a date
        before arithmetic, and compared against utc_today() not
        date.today(). Mocking utc_today() to a fixed value and checking
        the exact days_out proves both: (a) the string got parsed
        successfully (no TypeError), and (b) the subtraction used the
        mocked utc_today(), not the real local date."""
        mocked_utc_today = date(2026, 7, 10)
        with patch("utils.utc_today", return_value=mocked_utc_today):
            result = main._feature_importance_days_out("2026-07-15")
        assert result == 5

    def test_target_date_in_past_gives_negative_days_out(self):
        mocked_utc_today = date(2026, 7, 10)
        with patch("utils.utc_today", return_value=mocked_utc_today):
            result = main._feature_importance_days_out("2026-07-05")
        assert result == -5

    def test_malformed_string_returns_zero_not_raise(self):
        """A malformed/unexpected target_date value must not raise --
        record_feature_contribution is a best-effort logging call, not
        critical trading logic."""
        assert main._feature_importance_days_out("not-a-date") == 0
        assert main._feature_importance_days_out("2026-13-99") == 0

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
        assert isinstance(main._feature_importance_days_out(target_date_str), int)
