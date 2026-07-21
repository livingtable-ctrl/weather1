"""
Tests for acis_precip.py (backlog.txt "RAIN / SNOW / HURRICANE MARKETS"
Step 2): ACIS StnData fetch/parse, Open-Meteo Seasonal fetch, and the
bootstrap/tilt math the monthly-rain probability model is built on.
"""

from __future__ import annotations

import random
from unittest.mock import MagicMock, patch

import pytest

import acis_precip


class TestStationSidForCity:
    def test_strips_leading_k(self):
        with patch.dict("metar.MARKET_STATION_MAP", {"Denver": "KDEN"}, clear=False):
            assert acis_precip._station_sid_for_city("Denver") == "DEN"

    def test_nyc_case(self):
        with patch.dict("metar.MARKET_STATION_MAP", {"NYC": "KNYC"}, clear=False):
            assert acis_precip._station_sid_for_city("NYC") == "NYC"

    def test_unmapped_city_returns_none(self):
        assert acis_precip._station_sid_for_city("Nowhereville") is None

    def test_code_without_leading_k_passed_through(self):
        with patch.dict("metar.MARKET_STATION_MAP", {"Weird": "XYZ"}, clear=False):
            assert acis_precip._station_sid_for_city("Weird") == "XYZ"


class TestParsePcpnValue:
    def test_trace_is_zero(self):
        assert acis_precip._parse_pcpn_value("T") == 0.0

    def test_missing_is_none(self):
        assert acis_precip._parse_pcpn_value("M") is None

    def test_accumulated_sentinel_is_none(self):
        assert acis_precip._parse_pcpn_value("S") is None

    def test_empty_string_is_none(self):
        assert acis_precip._parse_pcpn_value("") is None

    def test_none_is_none(self):
        assert acis_precip._parse_pcpn_value(None) is None

    def test_numeric_string(self):
        assert acis_precip._parse_pcpn_value("0.06") == 0.06

    def test_float_passthrough(self):
        assert acis_precip._parse_pcpn_value(0.42) == 0.42

    def test_int_passthrough(self):
        assert acis_precip._parse_pcpn_value(1) == 1.0

    def test_garbage_string_is_none_not_a_crash(self):
        assert acis_precip._parse_pcpn_value("garbage") is None


class TestHistoricalRemainingAndFullMonthSums:
    def test_hand_computed_sums(self):
        # July (month=7), days_in_month=31, remaining_start_day=20.
        # Year A: every day = 1.0 -> remaining (20-31, 12 days) = 12.0, full = 31.0
        # Year B: every day = 0.0 -> remaining = 0.0, full = 0.0
        history = {
            2000: {700 + d: 1.0 for d in range(1, 32)},
            2001: {700 + d: 0.0 for d in range(1, 32)},
        }
        remaining, full = acis_precip.historical_remaining_and_full_month_sums(
            history, month=7, remaining_start_day=20, days_in_month=31
        )
        assert sorted(remaining) == [0.0, 12.0]
        assert sorted(full) == [0.0, 31.0]

    def test_year_excluded_when_missing_fraction_too_high(self):
        # 31-day remaining range, 7 missing (>20%) -> excluded.
        history = {
            2000: {
                **{700 + d: 1.0 for d in range(1, 25)},
                **{700 + d: None for d in range(25, 32)},
            }
        }
        remaining, full = acis_precip.historical_remaining_and_full_month_sums(
            history, month=7, remaining_start_day=1, days_in_month=31
        )
        assert remaining == []
        assert full == []

    def test_year_included_at_missing_fraction_boundary(self):
        # Remaining range [22, 31] = 10 days, exactly 2 missing (20%, not >
        # 20%) -> included. Full range [1, 31] must ALSO stay under the
        # threshold (both remaining_sums/full_month_sums are excluded
        # together for a year, per the function's index-aligned contract) --
        # days 1-21 are fully present so the full range's own missing
        # fraction is well under 20% too.
        history = {
            2000: {
                **{700 + d: 1.0 for d in range(1, 22)},  # days 1-21 present
                **{700 + d: 1.0 for d in range(22, 30)},  # 8 of the 10 remaining days
                700 + 30: None,
                700 + 31: None,
            }
        }
        remaining, full = acis_precip.historical_remaining_and_full_month_sums(
            history, month=7, remaining_start_day=22, days_in_month=31
        )
        assert len(remaining) == 1

    def test_remaining_range_ok_but_full_range_too_missing_excludes_both(self):
        """Review-caught coverage gap: the remaining_start_day=1 cases above
        make remaining_range == full_range, never isolating the "one range
        is fine, the OTHER range is too-missing" cross-exclusion this
        function's docstring promises. Remaining range [25, 31] = 7 days,
        all present (0% missing) -- but full range [1, 31] has 10 missing
        days out of 31 (~32%, > 20%). Both lists must still end up empty
        for this year, not just full_month_sums."""
        history = {
            2000: {
                **{700 + d: None for d in range(1, 11)},  # days 1-10 missing
                **{700 + d: 1.0 for d in range(11, 32)},  # days 11-31 present
            }
        }
        remaining, full = acis_precip.historical_remaining_and_full_month_sums(
            history, month=7, remaining_start_day=25, days_in_month=31
        )
        assert remaining == []
        assert full == []

    def test_full_range_ok_but_remaining_range_too_missing_excludes_both(self):
        """The reverse cross-exclusion case: full range [1, 31] is fully
        present (0% missing), but remaining range [25, 31] has 5 of 7 days
        missing (~71%, > 20%). Both lists must still end up empty."""
        history = {
            2000: {
                **{700 + d: 1.0 for d in range(1, 25)},  # days 1-24 present
                700 + 25: 1.0,
                700 + 26: None,
                700 + 27: None,
                700 + 28: None,
                700 + 29: None,
                700 + 30: None,
                700 + 31: 1.0,
            }
        }
        remaining, full = acis_precip.historical_remaining_and_full_month_sums(
            history, month=7, remaining_start_day=25, days_in_month=31
        )
        assert remaining == []
        assert full == []

    def test_missing_days_excluded_from_sum_not_treated_as_zero(self):
        # 4 present days (1.0 each) + 1 missing day = 20% missing, at the
        # inclusion boundary. The sum must reflect only the present days
        # (4.0), not error and not silently coerce the missing day to 0.0
        # in the sum itself (the exclusion-decision logic is separate from
        # the summing logic).
        history = {
            2000: {
                700 + 1: 1.0,
                700 + 2: 1.0,
                700 + 3: 1.0,
                700 + 4: 1.0,
                700 + 5: None,
            }
        }
        remaining, full = acis_precip.historical_remaining_and_full_month_sums(
            history, month=7, remaining_start_day=1, days_in_month=5
        )
        assert remaining == [4.0]
        assert full == [4.0]


class TestBootstrapCiMonthTotal:
    def test_too_few_years_returns_wide_ci(self):
        remaining_sums = [1.0] * 10  # < 15
        ci = acis_precip.bootstrap_ci_month_total(remaining_sums, 0.0, 5.0)
        assert ci == (0.0, 1.0)

    def test_ci_contains_point_estimate(self):
        random.seed(42)
        remaining_sums = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
        month_to_date = 0.0
        threshold = 6.0
        point_estimate = sum(
            1 for s in remaining_sums if month_to_date + s > threshold
        ) / len(remaining_sums)
        ci_low, ci_high = acis_precip.bootstrap_ci_month_total(
            remaining_sums, month_to_date, threshold
        )
        assert ci_low <= point_estimate <= ci_high

    def test_deterministic_point_estimate_hand_check(self):
        # Not the bootstrap CI itself -- the underlying exceedance-fraction
        # math the CI resamples, hand-verified directly.
        remaining_sums = [0, 1, 2, 3, 10]
        month_to_date_actual = 4.0
        threshold = 6.0
        totals = [month_to_date_actual + s for s in remaining_sums]
        # totals = [4, 5, 6, 7, 14] -> exceed 6.0: {7, 14} -> 2/5 = 0.40
        ens_prob = sum(1 for t in totals if t > threshold) / len(totals)
        assert ens_prob == 0.40


class TestApplySeasonalTilt:
    def test_none_seasonal_mean_no_ops(self):
        remaining = [1.0, 2.0, 3.0] * 6
        full = [4.0, 5.0, 6.0] * 6
        shifted, applied = acis_precip.apply_seasonal_tilt(remaining, full, None)
        assert applied is False
        assert shifted == remaining

    def test_too_few_years_no_ops(self):
        remaining = [1.0] * 5
        full = [4.0] * 5
        shifted, applied = acis_precip.apply_seasonal_tilt(remaining, full, 100.0)
        assert applied is False
        assert shifted == remaining

    def test_zero_full_month_mean_no_ops(self):
        remaining = [1.0] * 20
        full = [0.0] * 20
        shifted, applied = acis_precip.apply_seasonal_tilt(remaining, full, 100.0)
        assert applied is False
        assert shifted == remaining

    def test_hand_computed_shift(self):
        # full_month_sums average 4.0 in -> 101.6mm climatological mean.
        full = [4.0] * 20
        remaining = [2.0] * 20
        seasonal_mean_mm = 152.4  # ratio = 152.4 / 101.6 = 1.5
        shifted, applied = acis_precip.apply_seasonal_tilt(
            remaining, full, seasonal_mean_mm, tilt_strength=0.5
        )
        assert applied is True
        # raw_shift = (1.5 - 1.0) * mean(remaining) = 0.5 * 2.0 = 1.0
        # damped_shift = 1.0 * 0.5 = 0.5; max_shift = 0.25 * 2.0 = 0.5 -> not clamped further
        assert all(abs(s - 2.5) < 1e-9 for s in shifted)

    def test_ratio_clamp_fires(self):
        # seasonal_mean implies a ratio far above the (0.5, 2.0) clamp.
        full = [4.0] * 20
        remaining = [2.0] * 20
        seasonal_mean_mm = 4 * 101.6  # raw ratio = 4.0, clamped to 2.0
        shifted, applied = acis_precip.apply_seasonal_tilt(
            remaining, full, seasonal_mean_mm, tilt_strength=1.0
        )
        assert applied is True
        # With ratio clamped to 2.0: raw_shift = (2.0-1.0)*2.0 = 2.0, damped (strength=1.0) = 2.0
        # magnitude clamp = 0.25*2.0 = 0.5 -> shift clamped to 0.5, not 2.0
        assert all(abs(s - 2.5) < 1e-9 for s in shifted)

    def test_magnitude_clamp_fires_independently(self):
        # A moderate ratio but tilt_strength=1.0 (no damping) should still be
        # capped by the +/-25% magnitude clamp.
        full = [4.0] * 20
        remaining = [2.0] * 20
        seasonal_mean_mm = 1.8 * 101.6  # ratio = 1.8, within the (0.5, 2.0) clamp
        shifted, applied = acis_precip.apply_seasonal_tilt(
            remaining, full, seasonal_mean_mm, tilt_strength=1.0
        )
        assert applied is True
        # raw_shift = (1.8-1.0)*2.0 = 1.6, damped (strength=1.0) = 1.6
        # magnitude clamp = 0.25*2.0 = 0.5 -> shift clamped to 0.5
        assert all(abs(s - 2.5) < 1e-9 for s in shifted)

    def test_shift_never_makes_a_value_negative(self):
        full = [10.0] * 20
        remaining = [0.1] * 20
        seasonal_mean_mm = 0.1  # tiny -> ratio clamps to 0.5, negative shift
        shifted, applied = acis_precip.apply_seasonal_tilt(
            remaining, full, seasonal_mean_mm, tilt_strength=1.0
        )
        assert applied is True
        assert all(s >= 0.0 for s in shifted)


class TestFetchMonthToDateActual:
    def test_before_first_of_month_returns_none(self):
        result, n_missing = acis_precip.fetch_month_to_date_actual("DEN", 2026, 7, 0)
        assert result is None
        assert n_missing == 0

    def test_sums_parsed_values_and_counts_missing(self):
        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "data": [
                ["2026-07-01", "0.10"],
                ["2026-07-02", "T"],
                ["2026-07-03", "M"],
                ["2026-07-04", "0.20"],
            ]
        }
        fake_resp.raise_for_status.return_value = None
        with patch.object(acis_precip._session, "post", return_value=fake_resp):
            total, n_missing = acis_precip.fetch_month_to_date_actual("DEN", 2026, 7, 4)
        assert total == pytest.approx(0.30)
        assert n_missing == 1

    def test_fetch_exception_returns_none_zero(self):
        with patch.object(acis_precip._session, "post", side_effect=Exception("boom")):
            total, n_missing = acis_precip.fetch_month_to_date_actual("DEN", 2026, 7, 4)
        assert total is None
        assert n_missing == 0


class TestFetchSeasonalPrecipMeanMm:
    def test_parses_matching_month(self):
        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "monthly": {
                "time": ["2026-06-30", "2026-07-31", "2026-08-31"],
                "precipitation_mean": [30.0, 42.6, 53.0],
            }
        }
        fake_resp.raise_for_status.return_value = None
        with patch.object(acis_precip._session, "get", return_value=fake_resp):
            val = acis_precip.fetch_seasonal_precip_mean_mm(
                39.7, -104.9, "America/Denver", 2026, 7
            )
        assert val == 42.6

    def test_month_outside_window_returns_none(self):
        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "monthly": {
                "time": ["2026-06-30", "2026-07-31"],
                "precipitation_mean": [30.0, 42.6],
            }
        }
        fake_resp.raise_for_status.return_value = None
        with patch.object(acis_precip._session, "get", return_value=fake_resp):
            val = acis_precip.fetch_seasonal_precip_mean_mm(
                39.7, -104.9, "America/Denver", 2027, 3
            )
        assert val is None

    def test_fetch_exception_returns_none(self):
        with patch.object(acis_precip._session, "get", side_effect=Exception("boom")):
            val = acis_precip.fetch_seasonal_precip_mean_mm(
                39.7, -104.9, "America/Denver", 2026, 7
            )
        assert val is None
