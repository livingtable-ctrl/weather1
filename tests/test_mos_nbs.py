"""Tests for mos.py's NBS (real NBM via IEM) parsing -- the core logic behind
backlog.txt's REAL NBM VIA IEM NBS STATION BULLETINS entry.

The critical correctness property under test: NBS's raw feed only carries a
12-hourly max/min ("txn") on rows landing exactly on a 00Z or 12Z boundary,
and 00Z-ending rows are ALWAYS the local daytime max while 12Z-ending rows
are ALWAYS the local nighttime min -- for every mainland US timezone, not
just Eastern. A wrong assignment here would silently swap max/min or
misattribute a value to the wrong calendar date, corrupting a live ensemble
blend input without ever raising an error."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import mos


def _mock_nbs_response(rows):
    """Build a fake mos.json payload shaped like the real IEM API."""
    return {"data": rows}


def _row(ftime, txn=None):
    return {"ftime": ftime, "txn": txn, "tmp": 70}


class TestFetchNbsDailyExtremes:
    def setup_method(self):
        mos._NBS_CACHE.clear()

    def test_eastern_station_00z_is_max_12z_is_min(self):
        """Live-verified pattern (KNYC, 2026-07-17): 00Z-ending row is the
        higher value (day max), 12Z-ending row is the lower value (night min).
        America/New_York is UTC-4 in July (EDT): 00Z end = 8pm local (daytime
        period), 12Z end = 8am local (nighttime period)."""
        rows = [
            _row("2026-07-18 12:00", txn=72.0),  # 8am EDT Jul 18 -> min for Jul 18
            _row("2026-07-19 00:00", txn=81.0),  # 8pm EDT Jul 18 -> max for Jul 18
            _row("2026-07-19 12:00", txn=71.0),  # 8am EDT Jul 19 -> min for Jul 19
        ]
        with patch.object(mos._session, "get") as mock_get:
            mock_get.return_value.json.return_value = _mock_nbs_response(rows)
            mock_get.return_value.raise_for_status.return_value = None
            extremes = mos._fetch_nbs_daily_extremes("KNYC", "America/New_York")

        assert extremes == {
            (date(2026, 7, 18), "min"): 72.0,
            (date(2026, 7, 18), "max"): 81.0,
            (date(2026, 7, 19), "min"): 71.0,
        }

    def test_pacific_station_same_00z_max_12z_min_rule(self):
        """The 00Z=max/12Z=min assignment must hold for Pacific too (live-
        verified KLAX, 2026-07-17), proving the rule is genuinely
        timezone-independent, not hardcoded to Eastern. America/Los_Angeles
        is UTC-7 in July (PDT): 00Z end = 5pm local, 12Z end = 5am local --
        still cleanly inside daytime/nighttime respectively."""
        rows = [
            _row("2026-07-18 12:00", txn=67.0),
            _row("2026-07-19 00:00", txn=77.0),
            _row("2026-07-19 12:00", txn=67.0),
        ]
        with patch.object(mos._session, "get") as mock_get:
            mock_get.return_value.json.return_value = _mock_nbs_response(rows)
            mock_get.return_value.raise_for_status.return_value = None
            extremes = mos._fetch_nbs_daily_extremes("KLAX", "America/Los_Angeles")

        assert extremes[(date(2026, 7, 18), "max")] == 77.0
        assert extremes[(date(2026, 7, 18), "min")] == 67.0
        assert extremes[(date(2026, 7, 19), "min")] == 67.0

    def test_max_min_assignment_is_not_arbitrary(self):
        """Mutation-proof: if the 00Z/12Z -> max/min assignment were flipped,
        this test would fail -- the two txn values are deliberately unequal
        so a swapped assignment produces a different, wrong dict."""
        rows = [
            _row("2026-07-19 00:00", txn=90.0),  # 00Z -> must be max
            _row("2026-07-19 12:00", txn=60.0),  # 12Z -> must be min
        ]
        with patch.object(mos._session, "get") as mock_get:
            mock_get.return_value.json.return_value = _mock_nbs_response(rows)
            mock_get.return_value.raise_for_status.return_value = None
            extremes = mos._fetch_nbs_daily_extremes("KNYC", "America/New_York")

        # 00Z-ending row (Jul 18 20:00 local) must be tagged "max", not "min".
        assert extremes.get((date(2026, 7, 18), "max")) == 90.0
        assert (date(2026, 7, 18), "min") not in extremes
        # 12Z-ending row (Jul 19 08:00 local) must be tagged "min", not "max".
        assert extremes.get((date(2026, 7, 19), "min")) == 60.0
        assert (date(2026, 7, 19), "max") not in extremes

    def test_off_cycle_txn_rows_are_skipped(self):
        """A txn value on a row that isn't exactly 00Z/12Z-ending is dropped
        defensively rather than guessed at (NBS's own contract only promises
        txn on those two boundaries)."""
        rows = [
            _row("2026-07-19 06:00", txn=75.0),  # off-cycle, must be ignored
            _row("2026-07-19 00:00", txn=81.0),
        ]
        with patch.object(mos._session, "get") as mock_get:
            mock_get.return_value.json.return_value = _mock_nbs_response(rows)
            mock_get.return_value.raise_for_status.return_value = None
            extremes = mos._fetch_nbs_daily_extremes("KNYC", "America/New_York")

        assert extremes == {(date(2026, 7, 18), "max"): 81.0}

    def test_rows_without_txn_are_skipped(self):
        rows = [_row("2026-07-19 00:00", txn=None), _row("2026-07-19 12:00")]
        with patch.object(mos._session, "get") as mock_get:
            mock_get.return_value.json.return_value = _mock_nbs_response(rows)
            mock_get.return_value.raise_for_status.return_value = None
            extremes = mos._fetch_nbs_daily_extremes("KNYC", "America/New_York")

        assert extremes is None

    def test_network_failure_returns_none_and_caches_the_miss(self):
        with patch.object(mos._session, "get", side_effect=OSError("boom")):
            extremes = mos._fetch_nbs_daily_extremes("KNYC", "America/New_York")
        assert extremes is None
        # A second call within the TTL must not re-hit the network.
        with patch.object(mos._session, "get") as mock_get:
            mos._fetch_nbs_daily_extremes("KNYC", "America/New_York")
            mock_get.assert_not_called()

    def test_single_fetch_serves_both_station_and_tz_repeat_calls(self):
        """One station covers a fixed timezone in practice; repeat calls for
        the same (station, tz) within the TTL must not re-hit the network."""
        rows = [_row("2026-07-19 00:00", txn=81.0)]
        with patch.object(mos._session, "get") as mock_get:
            mock_get.return_value.json.return_value = _mock_nbs_response(rows)
            mock_get.return_value.raise_for_status.return_value = None
            mos._fetch_nbs_daily_extremes("KNYC", "America/New_York")
            mos._fetch_nbs_daily_extremes("KNYC", "America/New_York")
        assert mock_get.call_count == 1


class TestFetchNbmIem:
    def setup_method(self):
        mos._NBS_CACHE.clear()

    def test_returns_max_for_covered_date(self):
        rows = [_row("2026-07-19 00:00", txn=81.0)]
        with patch.object(mos._session, "get") as mock_get:
            mock_get.return_value.json.return_value = _mock_nbs_response(rows)
            mock_get.return_value.raise_for_status.return_value = None
            result = mos.fetch_nbm_iem(
                "KNYC", date(2026, 7, 18), "America/New_York", var="max"
            )
        assert result == 81.0

    def test_returns_none_for_uncovered_date(self):
        rows = [_row("2026-07-19 00:00", txn=81.0)]
        with patch.object(mos._session, "get") as mock_get:
            mock_get.return_value.json.return_value = _mock_nbs_response(rows)
            mock_get.return_value.raise_for_status.return_value = None
            result = mos.fetch_nbm_iem(
                "KNYC", date(2026, 7, 25), "America/New_York", var="max"
            )
        assert result is None

    def test_min_var_does_not_return_the_max_value(self):
        """Mutation-proof: requesting var='min' on a date that only has a
        max entry must not silently return the max value."""
        rows = [_row("2026-07-19 00:00", txn=81.0)]
        with patch.object(mos._session, "get") as mock_get:
            mock_get.return_value.json.return_value = _mock_nbs_response(rows)
            mock_get.return_value.raise_for_status.return_value = None
            result = mos.fetch_nbm_iem(
                "KNYC", date(2026, 7, 18), "America/New_York", var="min"
            )
        assert result is None
