"""Tests for hurricane_climatology.py -- HURDAT2 parsing, season-count
aggregation, and the bootstrap distribution/tilt used by
weather_markets._analyze_hurricane_count_trade (backlog.txt "HURRICANE
MARKETS" -- season-count model, 2026-08-03).

Uses a small synthetic HURDAT2-format fixture (not the real 90K-line NOAA
files) so these tests are fast, deterministic, and network-free. The parser
itself was separately cross-checked live against real published 2023/2024
Atlantic season totals (18/11/5 named-storm/hurricane/major-hurricane counts
for 2024, 20/7/3 for 2023 -- both exact matches) during development; that
live check is not repeated here.
"""

from __future__ import annotations

import hurricane_climatology as hc

# Synthetic 5-season Atlantic (AL) fixture, hand-constructed so every count
# is independently verifiable:
#   2000: 1 storm, max 40kt  (TS only)                 -> ts=1 hu=0 maj=0
#   2001: 1 storm, max 70kt  (hurricane)                -> ts=1 hu=1 maj=0
#   2002: 1 storm, max 100kt (major hurricane)           -> ts=1 hu=1 maj=1
#   2003: 2 storms: 40kt (TS) + 70kt (hurricane)         -> ts=2 hu=1 maj=0
#   2004: 1 storm, max 25kt -- never reaches named-storm strength (a real
#         HURDAT2 year always has at least one tracked system, even a weak
#         one that never gets a name -- there's no "0 storms this year"
#         record shape) -> ts=0 hu=0 maj=0
_FIXTURE = """\
AL012000,            UNNAMED,      1,
20000801, 0000,  , TS, 20.0N,  60.0W,  40, -999
AL012001,            UNNAMED,      2,
20010801, 0000,  , TS, 20.0N,  60.0W,  40, -999
20010805, 0000,  , HU, 20.0N,  61.0W,  70, -999
AL012002,            UNNAMED,      2,
20020801, 0000,  , TS, 20.0N,  60.0W,  40, -999
20020810, 0000,  , HU, 20.0N,  62.0W, 100, -999
AL012003,            UNNAMED,      1,
20030801, 0000,  , TS, 20.0N,  60.0W,  40, -999
AL022003,            UNNAMED,      1,
20030901, 0000,  , HU, 20.0N,  61.0W,  70, -999
AL012004,            UNNAMED,      1,
20040801, 0000,  , TD, 20.0N,  60.0W,  25, -999
"""


def _fixture_storms():
    return hc.parse_hurdat2(_FIXTURE)


class TestParseHurdat2:
    def test_parses_all_storms(self):
        storms = _fixture_storms()
        assert len(storms) == 6
        assert {s["id"] for s in storms} == {
            "AL012000",
            "AL012001",
            "AL012002",
            "AL012003",
            "AL022003",
            "AL012004",
        }

    def test_basin_and_year_extracted_from_id(self):
        storms = _fixture_storms()
        s = next(s for s in storms if s["id"] == "AL012000")
        assert s["basin"] == "AL"
        assert s["year"] == 2000

    def test_max_wind_is_the_storm_peak(self):
        storms = _fixture_storms()
        s2002 = next(s for s in storms if s["id"] == "AL012002")
        assert s2002["max_wind_kt"] == 100

    def test_threshold_day_is_first_crossing_not_max_day(self):
        """AL012001 crosses 34kt on Aug 1 and 64kt on Aug 5 -- threshold_day
        must record when EACH threshold was first crossed, not just tag
        every threshold with the day of the storm's overall peak. Stored as
        a (month, day) tuple, not an ordinal day-of-year -- see
        parse_hurdat2's own docstring for why (leap-year misalignment)."""
        storms = _fixture_storms()
        s = next(s for s in storms if s["id"] == "AL012001")
        assert s["threshold_day"][34] == (8, 1)
        assert s["threshold_day"][64] == (8, 5)
        assert s["threshold_day"][96] is None  # never reached major strength

    def test_missing_wind_sentinel_excluded(self):
        """-999 (HURDAT2's missing-value sentinel) must never be treated as
        a real wind reading, either for max_wind_kt or threshold crossing."""
        storms = hc.parse_hurdat2(
            "AL019999,            UNNAMED,      2,\n"
            "19990801, 0000,  , TS, 20.0N,  60.0W, -999, -999\n"
            "19990802, 0000,  , TS, 20.0N,  60.0W,   40, -999\n"
        )
        s = storms[0]
        assert s["max_wind_kt"] == 40
        assert s["threshold_day"][34] == (8, 2)

    def test_absurdly_high_wind_rejected(self):
        """Opus-review-caught: only the exact -999 sentinel was rejected --
        a corrupted feed reporting a nonsensical wind (e.g. 9999) would
        otherwise be accepted as real, fabricating a major hurricane."""
        storms = hc.parse_hurdat2(
            "AL019996,            UNNAMED,      2,\n"
            "19960801, 0000,  , TS, 20.0N,  60.0W,   40, -999\n"
            "19960802, 0000,  , HU, 20.0N,  60.0W, 9999, -999\n"
        )
        assert storms[0]["max_wind_kt"] == 40
        assert storms[0]["threshold_day"][96] is None

    def test_storm_with_all_missing_wind_has_none_max(self):
        storms = hc.parse_hurdat2(
            "AL019998,            UNNAMED,      1,\n"
            "19980801, 0000,  , LO, 20.0N,  60.0W, -999, -999\n"
        )
        assert storms[0]["max_wind_kt"] is None

    def test_truncated_file_does_not_crash(self):
        """A header claiming more rows than actually exist (corrupt/
        truncated download) must not raise -- uses what was read."""
        storms = hc.parse_hurdat2(
            "AL019997,            UNNAMED,      5,\n"
            "19970801, 0000,  , TS, 20.0N,  60.0W,  40, -999\n"
        )
        assert len(storms) == 1
        assert storms[0]["max_wind_kt"] == 40


class TestSeasonEndCounts:
    def test_matches_hand_computed_counts_per_year(self):
        storms = _fixture_storms()
        assert hc.season_end_counts(storms, 2000) == {
            "tropical_storm": 1,
            "hurricane": 0,
            "major_hurricane": 0,
        }
        assert hc.season_end_counts(storms, 2001) == {
            "tropical_storm": 1,
            "hurricane": 1,
            "major_hurricane": 0,
        }
        assert hc.season_end_counts(storms, 2002) == {
            "tropical_storm": 1,
            "hurricane": 1,
            "major_hurricane": 1,
        }
        assert hc.season_end_counts(storms, 2003) == {
            "tropical_storm": 2,
            "hurricane": 1,
            "major_hurricane": 0,
        }
        assert hc.season_end_counts(storms, 2004) == {
            "tropical_storm": 0,
            "hurricane": 0,
            "major_hurricane": 0,
        }

    def test_hurricane_count_is_a_subset_of_tropical_storm_count(self):
        """Every count type is "at least this strength", cumulative -- a
        storm counted as a hurricane must also count toward tropical_storm
        for the same year (mutation-guard against ever making these
        mutually-exclusive bins by accident)."""
        storms = _fixture_storms()
        counts = hc.season_end_counts(storms, 2001)
        assert counts["hurricane"] <= counts["tropical_storm"]


class TestCountAsOfDay:
    def test_counts_only_storms_that_crossed_threshold_by_that_day(self):
        storms = _fixture_storms()
        # AL012001 crosses hurricane strength on Aug 5 -- not yet counted on Aug 4.
        assert hc.count_as_of_day(storms, 2001, "hurricane", (8, 4)) == 0
        assert hc.count_as_of_day(storms, 2001, "hurricane", (8, 5)) == 1
        # tropical_storm strength was already reached Aug 1.
        assert hc.count_as_of_day(storms, 2001, "tropical_storm", (8, 1)) == 1

    def test_never_exceeds_season_end_count(self):
        storms = _fixture_storms()
        for count_type in ("tropical_storm", "hurricane", "major_hurricane"):
            assert (
                hc.count_as_of_day(storms, 2003, count_type, (12, 31))
                == hc.season_end_counts(storms, 2003)[count_type]
            )

    def test_leap_year_alignment_not_off_by_one(self):
        """Opus-review-caught: comparing raw tm_yday ordinals across a
        leap/non-leap year pair shifts by 1 day for every date after Feb 29
        -- (month, day) tuples must compare correctly regardless. A storm
        crossing threshold on Mar 1 in a LEAP year (day 61) must still count
        as of Mar 1 in a query, even though Mar 1's ordinal differs (60 in a
        non-leap year, 61 in a leap year)."""
        storms = hc.parse_hurdat2(
            "AL012000,            UNNAMED,      1,\n"  # 2000 is a leap year
            "20000301, 0000,  , HU, 20.0N,  60.0W,   70, -999\n"
        )
        assert hc.count_as_of_day(storms, 2000, "hurricane", (3, 1)) == 1
        assert hc.count_as_of_day(storms, 2000, "hurricane", (2, 28)) == 0


class TestSeasonEndTotalDistribution:
    def test_unconditional_mode_returns_raw_season_end_counts(self):
        storms = _fixture_storms()
        dist = hc.season_end_total_distribution(
            storms, "hurricane", window_years=5, end_year=2004
        )
        assert sorted(dist) == [0, 0, 1, 1, 1]  # 2000..2004's hurricane counts

    def test_window_years_caps_history_to_most_recent(self):
        storms = _fixture_storms()
        dist = hc.season_end_total_distribution(
            storms, "tropical_storm", window_years=2, end_year=2004
        )
        # Most recent 2 of {2000..2004} are 2003 (count=2), 2004 (count=0).
        assert sorted(dist) == [0, 2]

    def test_calendar_year_with_zero_storms_counts_as_zero_not_dropped(self):
        """Opus-review-caught (2026-08-03, real live CPAC bias): the window
        must be built from an explicit CALENDAR range, not from
        {s["year"] for s in storms} -- a year with literally no storm of
        this basin's prefix at all (a real, common gap for Central Pacific)
        must contribute a real 0 to the distribution, not be silently
        dropped (which would shrink the sample and skew the exceedance
        probability upward). This fixture has no storm at all for 2001 or
        2003 -- both must still appear as 0 in a 5-year window."""
        storms = hc.parse_hurdat2(
            "AL012000,            UNNAMED,      1,\n"
            "20000801, 0000,  , HU, 20.0N,  60.0W,   70, -999\n"
            "AL012002,            UNNAMED,      1,\n"
            "20020801, 0000,  , HU, 20.0N,  60.0W,   70, -999\n"
            "AL012004,            UNNAMED,      1,\n"
            "20040801, 0000,  , HU, 20.0N,  60.0W,   70, -999\n"
        )
        dist = hc.season_end_total_distribution(
            storms, "hurricane", window_years=5, end_year=2004
        )
        assert sorted(dist) == [0, 0, 1, 1, 1]  # 2001, 2003 real zeros; not [1, 1, 1]

    def test_end_year_defaults_to_last_year_from_real_clock(self):
        """Sanity check the default (no explicit end_year) doesn't crash and
        produces a plausible window -- doesn't assert an exact value since
        that would depend on the real wall clock, banned elsewhere in this
        codebase for determinism but fine as a loose smoke check here."""
        storms = _fixture_storms()
        dist = hc.season_end_total_distribution(storms, "hurricane", window_years=3)
        assert len(dist) == 3

    def test_tilted_mode_adds_current_count_to_historical_remaining(self):
        """For each historical year, remaining = season_end - to_date(same
        month/day); tilted total = current_count + remaining. Verified by
        hand for 2001 as the sole reference year (window_years=1, end_year=
        2001 isolates it): as of Aug 4, 2001's hurricane count-to-date was 0
        and its season-end was 1, so remaining=1 -- a real current_count of
        3 should produce a tilted total of 3+1=4."""
        storms = _fixture_storms()
        dist = hc.season_end_total_distribution(
            storms, "hurricane", window_years=1, end_year=2001
        )
        assert dist == [1]  # sanity: unconditional 2001-only baseline

        tilted = hc.season_end_total_distribution(
            storms,
            "hurricane",
            window_years=1,
            end_year=2001,
            as_of_month_day=(8, 4),
            current_count=3,
        )
        assert tilted == [4]

    def test_remaining_is_never_negative(self):
        """count_as_of_day is always <= season_end_counts by construction,
        so remaining = end - to_date can never go negative -- verify the
        max(0, ...) defensive clamp doesn't mask a real bug by checking the
        unclamped arithmetic directly stays non-negative here."""
        storms = _fixture_storms()
        tilted = hc.season_end_total_distribution(
            storms,
            "hurricane",
            window_years=1,
            end_year=2001,
            as_of_month_day=(1, 1),
            current_count=0,
        )
        # As of Jan 1, 2001's to-date count is 0, season-end is 1 -> remaining=1.
        assert tilted == [1]


class TestExceedanceProbability:
    def test_greater_is_strict(self):
        assert hc.exceedance_probability([5, 6, 7, 8], 6, "greater") == 0.5

    def test_greater_or_equal_includes_boundary(self):
        assert hc.exceedance_probability([5, 6, 7, 8], 6, "greater_or_equal") == 0.75

    def test_clamped_to_one_percent_floor(self):
        assert hc.exceedance_probability([1, 1, 1], 100, "greater") == 0.01

    def test_clamped_to_ninety_nine_percent_ceiling(self):
        assert hc.exceedance_probability([100, 100, 100], 1, "greater") == 0.99

    def test_empty_totals_returns_half(self):
        assert hc.exceedance_probability([], 5, "greater") == 0.5


class TestBootstrapCi:
    def test_too_few_years_returns_degenerate_ci(self):
        assert hc.bootstrap_ci(list(range(10)), 5, "greater") == (0.0, 1.0)

    def test_ci_brackets_point_estimate(self):
        totals = [7, 8, 9, 10, 11] * 6  # 30 values, mean 9
        point = hc.exceedance_probability(totals, 9, "greater")
        lo, hi = hc.bootstrap_ci(totals, 9, "greater")
        assert lo <= point <= hi
        assert 0.0 <= lo <= hi <= 1.0
