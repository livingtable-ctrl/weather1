"""Tests for mos.py's NBP (NBM probabilistic quantiles) parsing -- the core
logic behind backlog.txt's "NBM PROBABILISTIC QUANTILES -- ORPHANED
CONVERTER, MISSING FETCHER" entry.

Unlike NBS (test_mos_nbs.py), IEM has no JSON API for this product (its
api/1/mos.json `model` parameter is hard-restricted server-side to
^(AVN|GFS|ETA|NAM|NBS|NBE|ECM|LAV|MEX)$, confirmed live 2026-07-24 -- NBP is
rejected with a 422). This parses the raw AFOS text bulletin instead, so the
critical correctness properties under test are different from NBS's: correct
TXNP1/2/5/7/9 -> 10th/25th/50th/75th/90th percentile mapping (confirmed
against NOAA's own NBM text-card docs, not inferred), the 00Z=max/12Z=min
column-parity convention (same rule NBS already relies on, re-derived here
independently via each column's FHR offset from the bulletin's own run-time
header rather than trusting the bulletin's human-readable day-of-week
labels), and graceful degradation on missing/malformed rows rather than
silently misaligned columns."""

from __future__ import annotations

import logging
from datetime import date
from unittest.mock import patch

import mos

# A 2-day-group NBP bulletin fixture, structurally faithful to a real
# fetched bulletin (KMDW, 2026-07-24) but trimmed to 2 groups and simplified
# values. Run time 2026-07-18 07:00 UTC:
#   group 1: FHR 17 -> 2026-07-19 00:00 UTC (00Z/max, local EDT date 07-18)
#            FHR 29 -> 2026-07-19 12:00 UTC (12Z/min, local EDT date 07-19)
#   group 2: FHR 41 -> 2026-07-20 00:00 UTC (00Z/max, local EDT date 07-19)
#            FHR 53 -> 2026-07-20 12:00 UTC (12Z/min, local EDT date 07-20)
_RAW_BULLETIN = """000
FEUS18 KWNO 180700
NBPUSA
KNYC    NBM V5.0 NBP GUIDANCE    7/18/2026  0700 UTC
FRI 19| SAT 20
UTC    00  12| 00  12
FHR    17  29| 41  53
TXNMN  80  63| 85  67
TXNSD   2   2|  2   2
TXNP1  79  62| 82  65
TXNP2  81  63| 84  67
TXNP5  84  65| 87  70
TXNP7  87  68| 90  73
TXNP9  90  71| 93  76
"""


def _wrap_html(pre_text: str) -> str:
    return f'<html><body><pre class="afos-pre">{pre_text}</pre></body></html>'


class TestSplitNbpRow:
    def test_well_formed_groups(self):
        line = "TXNP1  79  62| 82  65"
        assert mos._split_nbp_row(line) == [79.0, 62.0, 82.0, 65.0]

    def test_missing_value_group_becomes_none_pair(self):
        """A group that doesn't split into exactly 2 numeric tokens must not
        silently shift every later column's alignment -- it becomes an
        explicit (None, None) placeholder instead."""
        line = "TXNP1  79    | 82  65"
        assert mos._split_nbp_row(line) == [None, None, 82.0, 65.0]

    def test_special_missing_code_becomes_none(self):
        line = "TXNP1   M  62| 82  65"
        assert mos._split_nbp_row(line) == [None, 62.0, 82.0, 65.0]


class TestParseNbpBulletin:
    def test_correct_percentile_mapping_and_dates(self):
        """TXNP1/2/5/7/9 must map to 10th/25th/50th/75th/90th respectively
        (confirmed against NOAA's NBM text-card docs) -- a mutation swapping
        any two would produce a non-monotonic quantile ladder here since all
        5 values are deliberately distinct and increasing."""
        result = mos._parse_nbp_bulletin(_RAW_BULLETIN, "America/New_York")
        assert result == {
            (date(2026, 7, 18), "max"): {
                10: 79.0,
                25: 81.0,
                50: 84.0,
                75: 87.0,
                90: 90.0,
            },
            (date(2026, 7, 19), "min"): {
                10: 62.0,
                25: 63.0,
                50: 65.0,
                75: 68.0,
                90: 71.0,
            },
            (date(2026, 7, 19), "max"): {
                10: 82.0,
                25: 84.0,
                50: 87.0,
                75: 90.0,
                90: 93.0,
            },
            (date(2026, 7, 20), "min"): {
                10: 65.0,
                25: 67.0,
                50: 70.0,
                75: 73.0,
                90: 76.0,
            },
        }

    def test_pacific_timezone_shifts_local_dates(self):
        """Same UTC bulletin, different station timezone -- local dates must
        shift accordingly (America/Los_Angeles is UTC-7 in July), proving
        the FHR-derived date computation is genuinely timezone-aware, not
        hardcoded to Eastern."""
        result = mos._parse_nbp_bulletin(_RAW_BULLETIN, "America/Los_Angeles")
        # 2026-07-19 00:00 UTC (group 1 max slot) -> 2026-07-18 17:00 PDT -> still 07-18
        assert (date(2026, 7, 18), "max") in result
        # 2026-07-19 12:00 UTC (group 1 min slot) -> 2026-07-19 05:00 PDT -> still 07-19
        assert (date(2026, 7, 19), "min") in result
        assert result[(date(2026, 7, 18), "max")][50] == 84.0

    def test_max_min_assignment_is_not_arbitrary(self):
        """Mutation-proof: if the even/odd-index -> max/min assignment were
        flipped, this test would fail (values deliberately unequal)."""
        result = mos._parse_nbp_bulletin(_RAW_BULLETIN, "America/New_York")
        assert result[(date(2026, 7, 18), "max")][50] == 84.0
        assert result[(date(2026, 7, 19), "min")][50] == 65.0
        assert (date(2026, 7, 18), "min") not in result
        assert (date(2026, 7, 19), "max") not in result or result[
            (date(2026, 7, 19), "max")
        ][50] != 65.0

    def test_missing_header_returns_none(self):
        lines = [ln for ln in _RAW_BULLETIN.splitlines() if "NBP GUIDANCE" not in ln]
        text = "\n".join(lines)
        assert mos._parse_nbp_bulletin(text, "America/New_York") is None

    def test_missing_header_logs_a_format_drift_warning(self, caplog):
        """Opus review finding: a header-pattern miss on real bulletin text
        means IEM changed the format, not routine no-coverage -- silent None
        would be indistinguishable from the latter forever (same class of
        gap the sibling NBS parser's own "format may have changed" warning
        exists to prevent, see _fetch_nbs_daily_extremes)."""
        lines = [ln for ln in _RAW_BULLETIN.splitlines() if "NBP GUIDANCE" not in ln]
        text = "\n".join(lines)
        with caplog.at_level(logging.WARNING, logger="mos"):
            mos._parse_nbp_bulletin(text, "America/New_York")
        assert any(
            "may have changed the NBP bulletin format" in r.message
            for r in caplog.records
        )

    def test_missing_percentile_row_returns_none(self):
        """A partial percentile ladder (e.g. TXNP9 row absent) can't feed
        nws_prob_from_quantiles' expected 5-point shape reliably -- must
        fail closed (None) rather than return a degraded/partial dict."""
        lines = [ln for ln in _RAW_BULLETIN.splitlines() if not ln.startswith("TXNP9")]
        text = "\n".join(lines)
        assert mos._parse_nbp_bulletin(text, "America/New_York") is None

    def test_missing_fhr_row_returns_none(self):
        lines = [ln for ln in _RAW_BULLETIN.splitlines() if not ln.startswith("FHR")]
        text = "\n".join(lines)
        assert mos._parse_nbp_bulletin(text, "America/New_York") is None

    def test_missing_fhr_row_logs_a_format_drift_warning(self, caplog):
        lines = [ln for ln in _RAW_BULLETIN.splitlines() if not ln.startswith("FHR")]
        text = "\n".join(lines)
        with caplog.at_level(logging.WARNING, logger="mos"):
            mos._parse_nbp_bulletin(text, "America/New_York")
        assert any(
            "may have changed the NBP bulletin format" in r.message
            for r in caplog.records
        )

    def test_all_columns_failing_hour_check_returns_none_and_warns(self, caplog):
        """Header/FHR/percentile rows all present but every FHR value
        produces a valid_utc hour that doesn't match the 00Z/12Z convention
        -- e.g. IEM shifted the FHR base away from the header's own
        issuance time. Must return None (not a bogus partial dict) AND
        warn, since this is NOT the routine "no coverage" case (that one
        stays silent -- only a total, otherwise-well-formed failure warns)."""
        # Replace the FHR row's offsets with values that land on 06Z/18Z
        # instead of 00Z/12Z for every column.
        bad_bulletin = _RAW_BULLETIN.replace(
            "FHR    17  29| 41  53", "FHR     6  18| 30  42"
        )
        with caplog.at_level(logging.WARNING, logger="mos"):
            result = mos._parse_nbp_bulletin(bad_bulletin, "America/New_York")
        assert result is None
        assert any(
            "zero columns passed the 00Z/12Z hour check" in r.message
            for r in caplog.records
        )

    def test_no_warning_for_routine_no_data_case(self, caplog):
        """A bulletin with a real header but zero day-groups at all (e.g. an
        FHR row with no values) is routine -- must NOT warn, only the
        all-present-but-all-failed case above should."""
        bulletin = (
            _RAW_BULLETIN.replace("FHR    17  29| 41  53", "FHR    ")
            .replace("TXNP1  79  62| 82  65", "TXNP1  ")
            .replace("TXNP2  81  63| 84  67", "TXNP2  ")
            .replace("TXNP5  84  65| 87  70", "TXNP5  ")
            .replace("TXNP7  87  68| 90  73", "TXNP7  ")
            .replace("TXNP9  90  71| 93  76", "TXNP9  ")
        )
        with caplog.at_level(logging.WARNING, logger="mos"):
            result = mos._parse_nbp_bulletin(bulletin, "America/New_York")
        assert result is None
        assert not any(
            "may have changed the NBP bulletin format" in r.message
            for r in caplog.records
        )

    def test_bad_timezone_returns_none(self):
        assert mos._parse_nbp_bulletin(_RAW_BULLETIN, "Not/ARealZone") is None

    def test_column_with_missing_percentile_value_excluded_from_result(self):
        """A single blank percentile value within an otherwise-present row
        must drop just that one column (fewer than 5 quantiles collected),
        not silently substitute None into nws_prob_from_quantiles' input."""
        lines = _RAW_BULLETIN.splitlines()
        lines = [
            ln.replace("TXNP9  90  71| 93  76", "TXNP9      | 93  76")
            if ln.startswith("TXNP9")
            else ln
            for ln in lines
        ]
        text = "\n".join(lines)
        result = mos._parse_nbp_bulletin(text, "America/New_York")
        # The 07-18 max column lost its 90th percentile -> excluded entirely.
        assert (date(2026, 7, 18), "max") not in result
        # The 07-19 max column (second group) is unaffected.
        assert (date(2026, 7, 19), "max") in result


class TestFetchNbpPercentiles:
    def setup_method(self):
        mos._NBP_CACHE.clear()

    def test_parses_real_shaped_html_response(self):
        with patch.object(mos._session, "get") as mock_get:
            mock_get.return_value.text = _wrap_html(_RAW_BULLETIN)
            mock_get.return_value.raise_for_status.return_value = None
            result = mos._fetch_nbp_percentiles("KNYC", "America/New_York")
        assert result[(date(2026, 7, 18), "max")][50] == 84.0

    def test_unknown_station_pil_returns_none(self):
        """IEM's error page for an unmatched PIL has no <pre class="afos-pre">
        block -- must be distinguished from a real bulletin, not crash."""
        with patch.object(mos._session, "get") as mock_get:
            mock_get.return_value.text = "<html><body>Service Notice</body></html>"
            mock_get.return_value.raise_for_status.return_value = None
            result = mos._fetch_nbp_percentiles("KZZZZ", "America/New_York")
        assert result is None

    def test_bad_station_suffix_length_returns_none_without_network_call(self):
        """Every station this bot uses is K + 3 letters; a station that
        doesn't fit must fail closed before ever making a request."""
        with patch.object(mos._session, "get") as mock_get:
            result = mos._fetch_nbp_percentiles("KABCDE", "America/New_York")
        assert result is None
        mock_get.assert_not_called()

    def test_network_failure_returns_none_and_caches_the_miss(self):
        with patch.object(mos._session, "get", side_effect=OSError("boom")):
            result = mos._fetch_nbp_percentiles("KNYC", "America/New_York")
        assert result is None
        with patch.object(mos._session, "get") as mock_get:
            mos._fetch_nbp_percentiles("KNYC", "America/New_York")
            mock_get.assert_not_called()

    def test_repeat_calls_within_ttl_hit_cache_not_network(self):
        with patch.object(mos._session, "get") as mock_get:
            mock_get.return_value.text = _wrap_html(_RAW_BULLETIN)
            mock_get.return_value.raise_for_status.return_value = None
            mos._fetch_nbp_percentiles("KNYC", "America/New_York")
            mos._fetch_nbp_percentiles("KNYC", "America/New_York")
        assert mock_get.call_count == 1

    def test_pil_derived_from_station_suffix(self):
        """KMDW -> pil=NBPMDW, matching NBS's own K-prefix-stripped
        station-suffix convention."""
        with patch.object(mos._session, "get") as mock_get:
            mock_get.return_value.text = _wrap_html(_RAW_BULLETIN)
            mock_get.return_value.raise_for_status.return_value = None
            mos._fetch_nbp_percentiles("KMDW", "America/Chicago")
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["pil"] == "NBPMDW"


class TestFetchNbmQuantiles:
    def setup_method(self):
        mos._NBP_CACHE.clear()

    def test_returns_quantiles_for_covered_max_date(self):
        with patch.object(mos._session, "get") as mock_get:
            mock_get.return_value.text = _wrap_html(_RAW_BULLETIN)
            mock_get.return_value.raise_for_status.return_value = None
            result = mos.fetch_nbm_quantiles(
                "KNYC", date(2026, 7, 18), "America/New_York", var="max"
            )
        assert result == {10: 79.0, 25: 81.0, 50: 84.0, 75: 87.0, 90: 90.0}

    def test_min_var_does_not_return_the_max_quantiles(self):
        """Mutation-proof: requesting var='min' on a date that only has a
        max entry must not silently return the max quantiles."""
        with patch.object(mos._session, "get") as mock_get:
            mock_get.return_value.text = _wrap_html(_RAW_BULLETIN)
            mock_get.return_value.raise_for_status.return_value = None
            result = mos.fetch_nbm_quantiles(
                "KNYC", date(2026, 7, 18), "America/New_York", var="min"
            )
        assert result is None

    def test_returns_none_for_uncovered_date(self):
        with patch.object(mos._session, "get") as mock_get:
            mock_get.return_value.text = _wrap_html(_RAW_BULLETIN)
            mock_get.return_value.raise_for_status.return_value = None
            result = mos.fetch_nbm_quantiles(
                "KNYC", date(2026, 8, 1), "America/New_York", var="max"
            )
        assert result is None


class TestNbpFeedsNwsProbFromQuantiles:
    """End-to-end: the fetcher's output shape must be directly consumable by
    nws.nws_prob_from_quantiles() -- the whole point of this entry, giving
    that function its first real caller."""

    def setup_method(self):
        mos._NBP_CACHE.clear()

    def test_quantiles_produce_a_sane_probability(self):
        from nws import nws_prob_from_quantiles

        with patch.object(mos._session, "get") as mock_get:
            mock_get.return_value.text = _wrap_html(_RAW_BULLETIN)
            mock_get.return_value.raise_for_status.return_value = None
            quantiles = mos.fetch_nbm_quantiles(
                "KNYC", date(2026, 7, 18), "America/New_York", var="max"
            )
        # Median is 84.0F -- a threshold well below the whole ladder should
        # give a high P(above), well above should give a low one.
        assert (
            nws_prob_from_quantiles(quantiles, threshold=70.0, condition_type="above")
            > 0.9
        )
        assert (
            nws_prob_from_quantiles(quantiles, threshold=100.0, condition_type="above")
            < 0.1
        )
