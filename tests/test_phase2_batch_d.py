"""Phase 2 Batch D regression tests: P2-6, P2-15."""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(__file__[: __file__.rfind("tests")]))


# ── P2-6: "between" lock-in uses dynamic confidence ───────────────────────────


class TestBetweenLockInDynamicConfidence:
    """P2-6: between-market METAR lock-in must call _dynamic_lock_in_confidence."""

    def _call_metar_lock_in(
        self,
        current_temp,
        lo,
        hi,
        local_hour,
        ticker="?",
        max_temp_f=None,
        min_temp_f=None,
        obs_date=None,
    ):
        """Drive _metar_lock_in with fully mocked dependencies.

        ticker/max_temp_f/min_temp_f/obs_date default to the "no daily
        extreme available, no ticker prefix, same-day obs" shape the original
        4 tests in this class relied on -- extended (not replaced) so the
        re-enabled between-branch tests below can also drive the HIGH/LOW
        ticker-prefix selection and the per-observation date guard.
        """
        import metar as _metar
        import weather_markets as wm

        # _metar_lock_in gates on city-local ("America/New_York" for NYC)
        # calendar date, not UTC -- matches the ZoneInfo convention already
        # used throughout this file.
        today = datetime.now(ZoneInfo("America/New_York")).date()
        fake_obs_time = MagicMock()
        fake_obs_local = MagicMock(hour=local_hour)
        fake_obs_local.date.return_value = obs_date if obs_date is not None else today
        fake_obs_time.astimezone.return_value = fake_obs_local

        obs = {"current_temp_f": current_temp, "obs_time": fake_obs_time}
        if max_temp_f is not None:
            obs["max_temp_f"] = max_temp_f
        if min_temp_f is not None:
            obs["min_temp_f"] = min_temp_f

        with patch.object(wm, "_metar_station_for_city", return_value="KJFK"):
            with patch.object(_metar, "fetch_metar", return_value=obs):
                return wm._metar_lock_in(
                    city="NYC",
                    target_date=today,
                    condition={"type": "between", "lower": lo, "upper": hi},
                    ticker=ticker,
                )

    def test_yes_lock_confidence_matches_dynamic(self):
        """Inside a WIDE bucket (half-width 3.0°F, same as the NO-side
        _margin default): confidence must equal _dynamic_lock_in_confidence
        using the one-sided at-risk-edge clearance and _yes_inband_margin —
        not the old min-distance-to-either-edge formula, and not the NO-side
        `_margin`. A real ticker is required now that an unresolvable ticker
        ("?") correctly refuses to lock (see
        test_between_ticker_ambiguous_not_locked below) — the width-6 band
        makes _yes_inband_margin (3.0) equal `_margin` (3.0) by construction,
        so this test alone can't catch the wrong-margin-argument bug; that's
        covered separately by test_between_yes_lock_high_market_inside_safe_half
        below on a 2°F band where the two values differ.
        """
        import metar as _metar

        current_temp, lo, hi, hour = 71.0, 68.0, 74.0, 15  # width 6, half 3.0
        risk_clearance = hi - current_temp  # 3.0 -- exactly the YES boundary
        yes_inband_margin = (hi - lo) / 2.0  # 3.0
        expected = _metar._dynamic_lock_in_confidence(
            risk_clearance, hour, yes_inband_margin
        )

        # Old hardcoded value was 0.95 — verify dynamic is different (test sanity)
        assert abs(expected - 0.95) > 0.001

        locked, _prob, details = self._call_metar_lock_in(
            current_temp,
            lo,
            hi,
            hour,
            ticker="KXHIGHNY-26AUG10-B71.0",
            max_temp_f=current_temp,
        )
        assert locked and details["outcome"] == "yes", (
            f"expected a YES lock at the exact margin boundary, got {details}"
        )
        assert abs(details["confidence"] - expected) < 0.001, (
            f"YES lock confidence {details['confidence']:.3f} != dynamic {expected:.3f}; "
            "old hardcoded 0.95 (or the wrong clearance/margin) may still be in place"
        )

    def test_no_lock_confidence_matches_dynamic(self):
        """Outside bucket >3°F: confidence must equal _dynamic_lock_in_confidence, not 0.92."""
        import metar as _metar

        current_temp, lo, hi, hour = 80.0, 68.0, 74.0, 17  # 6°F above hi
        clearance = current_temp - hi  # 6.0
        expected = _metar._dynamic_lock_in_confidence(clearance, hour)

        assert abs(expected - 0.92) > 0.001

        locked, _prob, details = self._call_metar_lock_in(
            current_temp,
            lo,
            hi,
            hour,
            ticker="KXHIGHNY-26AUG10-B71.0",
            max_temp_f=current_temp,
        )
        assert locked and details["outcome"] == "no", (
            f"expected a NO lock 6°F past the upper edge, got {details}"
        )
        assert abs(details["confidence"] - expected) < 0.001, (
            f"NO lock confidence {details['confidence']:.3f} != dynamic {expected:.3f}; "
            "old hardcoded 0.92 may still be in place"
        )

    def test_dynamic_confidence_increases_with_clearance_generic(self):
        """Generic property of _dynamic_lock_in_confidence itself (not tied to
        the between branch's own clearance formula, which is one-sided —
        see test_between_yes_lock_high_market_inside_safe_half below for that):
        larger clearance past the margin must yield higher confidence."""
        import metar as _metar

        conf_wide = _metar._dynamic_lock_in_confidence(clearance_f=6.0, local_hour=16)
        conf_near_edge = _metar._dynamic_lock_in_confidence(
            clearance_f=0.5, local_hour=16
        )
        assert conf_wide > conf_near_edge, (
            "Larger clearance past the margin must produce higher confidence"
        )

    def test_no_clearance_scales_with_distance_outside(self):
        """NO clearance increases with distance outside bucket → higher confidence."""
        import metar as _metar

        # 4°F outside (clearance 4): barely over the 3°F threshold
        conf_near = _metar._dynamic_lock_in_confidence(clearance_f=4.0, local_hour=16)
        # 10°F outside (clearance 10): clearly outside
        conf_far = _metar._dynamic_lock_in_confidence(clearance_f=10.0, local_hour=16)
        assert conf_far > conf_near, (
            "Larger clearance outside bucket must yield higher confidence"
        )

    def test_dynamic_confidence_range(self):
        """_dynamic_lock_in_confidence must stay in [0.72, 0.97]."""
        import metar as _metar

        for clearance in (0.0, 3.0, 6.0, 13.0, 20.0):
            for hour in (14, 16, 18, 20, 22):
                conf = _metar._dynamic_lock_in_confidence(clearance, hour)
                assert 0.72 <= conf <= 0.97, (
                    f"conf={conf:.3f} out of [0.72,0.97] for clearance={clearance}, hour={hour}"
                )

    HIGH_TICKER = "KXHIGHNY-26AUG10-B86.5"
    LOW_TICKER = "KXLOWCHI-26AUG10-B64.5"

    def test_between_lock_in_reenabled_uses_daily_extreme_not_current_temp(self):
        """Between-market METAR lock-in is RE-ENABLED (backlog.txt "BETWEEN-
        BUCKET MARKETS ... METAR LOCK-IN WAS DISABLED"), fixing the AC3
        violation (comparing current_temp_f instead of the daily extreme) that
        got it disabled 2026-06-29. This is the positive control for that
        fix: max_temp_f (the daily extreme) is set high enough to trigger a
        monotonic-safe NO, while current_temp_f alone (squarely inside the
        bucket) would have triggered the disabled implementation's YES —
        proving the daily extreme, not the instantaneous reading, drives the
        outcome now.
        """
        locked, prob, details = self._call_metar_lock_in(
            current_temp=91.0,  # squarely inside [90.5, 92.5] -- irrelevant now
            lo=90.5,
            hi=92.5,
            local_hour=19,
            ticker=self.HIGH_TICKER,
            max_temp_f=97.0,  # daily high already 4.5°F past the upper edge
        )
        assert locked
        assert details["outcome"] == "no"
        assert 0.0 < prob < 0.5
        assert "high-so-far" in details["reason"]

    def test_between_ticker_ambiguous_not_locked(self):
        """A ticker that says neither HIGH nor LOW (e.g. the "?" default a
        caller might pass) must refuse to lock rather than silently guessing
        HIGH -- even with a temp deep in what would be NO territory for a
        HIGH market."""
        locked, _prob, details = self._call_metar_lock_in(
            current_temp=95.0,
            lo=63.5,
            hi=65.5,
            local_hour=16,
            ticker="?",
            max_temp_f=95.0,
        )
        assert not locked, f"ambiguous ticker must not lock, got {details}"
        assert "cannot determine" in details["reason"]

    def test_between_malformed_condition_missing_bounds_fails_closed(self):
        """A "between" condition missing lower/upper (a malformed/synthetic
        caller -- _parse_market_condition always sets both for a real
        ticker) must refuse to lock, not silently default to a fake
        [0.0, 0.0] band -- with this branch now actually reachable, that
        default would produce a confident, wrong NO lock for almost any
        real temperature (comp_temp >= 0.0 + 3.0 margin)."""
        import metar as _metar
        import weather_markets as wm

        today = datetime.now(ZoneInfo("America/New_York")).date()
        fake_obs_time = MagicMock()
        fake_obs_local = MagicMock(hour=16)
        fake_obs_local.date.return_value = today
        fake_obs_time.astimezone.return_value = fake_obs_local

        with patch.object(wm, "_metar_station_for_city", return_value="KJFK"):
            with patch.object(
                _metar,
                "fetch_metar",
                return_value={
                    "current_temp_f": 95.0,  # would be a confident NO if lo=hi=0.0
                    "obs_time": fake_obs_time,
                },
            ):
                locked, prob, details = wm._metar_lock_in(
                    city="NYC",
                    target_date=today,
                    condition={"type": "between"},  # no "lower"/"upper" keys
                    ticker=self.HIGH_TICKER,
                )

        assert not locked, f"malformed condition must not lock, got {details}"
        assert prob == 0.0

    def test_between_no_lock_high_market_daily_high_cleared_upper_margin(self):
        """HIGH-var between market: daily-high-so-far >= upper+3°F is a safe,
        monotonic NO lock (running max cannot decrease)."""
        locked, _prob, details = self._call_metar_lock_in(
            current_temp=90.0,
            lo=85.5,
            hi=87.5,
            local_hour=16,
            ticker=self.HIGH_TICKER,
            max_temp_f=90.5,  # exactly hi + margin (3.0) -- boundary, inclusive
        )
        assert locked
        assert details["outcome"] == "no"
        assert "high-so-far" in details["reason"]

    def test_between_no_lock_boundary_just_under_margin_not_locked(self):
        """Mutation-test the NO boundary: 0.01°F under hi+margin must NOT lock
        (proves the >= boundary is real, not a typo for a looser comparison)."""
        locked, _prob, details = self._call_metar_lock_in(
            current_temp=90.0,
            lo=85.5,
            hi=87.5,
            local_hour=16,
            ticker=self.HIGH_TICKER,
            max_temp_f=90.49,  # hi(87.5) + margin(3.0) - 0.01
        )
        assert not locked, f"expected no lock just under the margin, got {details}"
        assert "NO safety margin" in details["reason"], (
            f"expected the else-branch reason (proves this didn't accidentally "
            f"take an earlier guard for the wrong reason), got {details}"
        )

    def test_between_no_lock_low_market_daily_low_cleared_lower_margin(self):
        """LOW-var between market: daily-low-so-far <= lower-3°F is a safe,
        monotonic NO lock (running min cannot increase). Ticker must contain
        "LOW" to route to min_temp_f instead of max_temp_f."""
        locked, _prob, details = self._call_metar_lock_in(
            current_temp=60.0,
            lo=63.5,
            hi=65.5,
            local_hour=16,
            ticker=self.LOW_TICKER,
            min_temp_f=60.5,  # exactly lo(63.5) - margin(3.0) -- boundary
        )
        assert locked
        assert details["outcome"] == "no"
        assert "low-so-far" in details["reason"]

    def test_between_no_lock_low_market_boundary_margin_not_shrunk(self):
        """Mutation-test the LOW-side NO margin itself: at min_temp_f=61.0,
        the real 3.0°F margin (lo-margin=60.5) must NOT lock (61.0 > 60.5),
        but a shrunk margin of 1.0-2.0°F (lo-margin=61.5-62.5) WOULD lock
        (61.0 <= 61.5/62.5) -- the existing boundary test at exactly 60.5
        can't distinguish "margin=3.0" from a smaller one that also happens
        to include 60.5."""
        locked, _prob, details = self._call_metar_lock_in(
            current_temp=61.0,
            lo=63.5,
            hi=65.5,
            local_hour=16,
            ticker=self.LOW_TICKER,
            min_temp_f=61.0,
        )
        assert not locked, (
            f"LOW-side NO margin appears shrunk below 3.0°F, got {details}"
        )

    def test_between_no_lock_does_not_reintroduce_unsafe_direction_high_market(self):
        """The deleted original implementation's NO branch ALSO fired when the
        temp was below the lower edge by margin -- unsafe for a HIGH market,
        since a running max that hasn't reached the band yet can still rise
        into or past it. Must NOT lock here (regression guard against
        reintroducing that bug, per this backlog entry's explicit warning)."""
        locked, _prob, details = self._call_metar_lock_in(
            current_temp=80.0,
            lo=85.5,
            hi=87.5,
            local_hour=16,
            ticker=self.HIGH_TICKER,
            max_temp_f=80.0,  # 5.5°F BELOW the lower edge -- not yet in the band
        )
        assert not locked, (
            "HIGH-var between market locked on the unsafe below-lower-edge "
            f"direction — reintroduced the deleted implementation's bug: {details}"
        )

    def test_between_no_lock_does_not_reintroduce_unsafe_direction_low_market(self):
        """LOW-market mirror of the test above: a running daily-low-so-far
        ABOVE the upper edge must NOT lock NO -- the low hasn't reached the
        band yet and can still fall into or past it later in the day."""
        locked, _prob, details = self._call_metar_lock_in(
            current_temp=70.0,
            lo=63.5,
            hi=65.5,
            local_hour=16,
            ticker=self.LOW_TICKER,
            min_temp_f=70.0,  # 4.5°F ABOVE the upper edge -- not yet in the band
        )
        assert not locked, (
            "LOW-var between market locked on the unsafe above-upper-edge "
            f"direction: {details}"
        )

    def test_between_yes_lock_high_market_inside_safe_half(self):
        """HIGH-var between market: daily-high-so-far in the band's safer
        half (closer to the entry/lower edge than the at-risk/upper edge)
        locks YES, with confidence computed from _yes_inband_margin (1.0),
        NOT the NO-side `_margin` (3.0) -- those differ for a 2°F band, so
        this test also catches the wrong-margin-argument bug directly."""
        import metar as _metar

        locked, _prob, details = self._call_metar_lock_in(
            current_temp=86.0,
            lo=85.5,
            hi=87.5,
            local_hour=16,
            ticker=self.HIGH_TICKER,
            max_temp_f=86.0,  # risk_clearance = hi - 86.0 = 1.5 >= margin (1.0)
        )
        assert locked
        assert details["outcome"] == "yes"
        assert "high-so-far" in details["reason"]

        expected = _metar._dynamic_lock_in_confidence(1.5, 16, 1.0)
        wrong_margin = _metar._dynamic_lock_in_confidence(1.5, 16, 3.0)
        assert abs(expected - wrong_margin) > 0.001, (
            "test sanity: yes_inband_margin and the NO-side margin must "
            "produce different confidence values for this input"
        )
        assert abs(details["confidence"] - expected) < 0.001, (
            f"YES confidence {details['confidence']:.4f} != expected "
            f"{expected:.4f} (using _yes_inband_margin) -- got wrong_margin "
            f"value {wrong_margin:.4f} instead? passing _margin (3.0) instead "
            "of _yes_inband_margin (1.0) would silently flatten this"
        )

    def test_between_yes_lock_low_market_inside_safe_half(self):
        """LOW-var between market: daily-low-so-far in the band's safer half
        (closer to the entry/upper edge than the at-risk/lower edge) locks
        YES."""
        locked, _prob, details = self._call_metar_lock_in(
            current_temp=65.0,
            lo=63.5,
            hi=65.5,
            local_hour=16,
            ticker=self.LOW_TICKER,
            min_temp_f=65.0,  # risk_clearance = 65.0 - 63.5 = 1.5 >= margin (1.0)
        )
        assert locked
        assert details["outcome"] == "yes"
        assert "low-so-far" in details["reason"]

    def test_between_yes_not_locked_insufficient_clearance(self):
        """Inside the band but past the midpoint (closer to the at-risk upper
        edge than the margin allows) must NOT lock YES."""
        locked, _prob, details = self._call_metar_lock_in(
            current_temp=87.0,
            lo=85.5,
            hi=87.5,
            local_hour=16,
            ticker=self.HIGH_TICKER,
            max_temp_f=87.0,  # risk_clearance = 87.5 - 87.0 = 0.5 < margin (1.0)
        )
        assert not locked, (
            f"expected no lock with insufficient clearance, got {details}"
        )
        assert "clearance to at-risk edge" in details["reason"]

    def test_between_yes_lock_boundary_at_exact_midpoint(self):
        """Mutation-test the YES boundary: exactly at the band midpoint
        (risk_clearance == margin == half the band width) must lock; 0.01°F
        past it must not."""
        locked_at, _prob_at, details_at = self._call_metar_lock_in(
            current_temp=86.5,
            lo=85.5,
            hi=87.5,
            local_hour=16,
            ticker=self.HIGH_TICKER,
            max_temp_f=86.5,  # exactly the midpoint: risk_clearance = 1.0 == margin
        )
        assert locked_at and details_at["outcome"] == "yes", (
            f"expected lock exactly at the midpoint boundary, got {details_at}"
        )

        locked_past, _prob_past, details_past = self._call_metar_lock_in(
            current_temp=86.51,
            lo=85.5,
            hi=87.5,
            local_hour=16,
            ticker=self.HIGH_TICKER,
            max_temp_f=86.51,  # 0.01°F past the midpoint: risk_clearance = 0.99
        )
        assert not locked_past, (
            f"expected no lock 0.01°F past the midpoint boundary, got {details_past}"
        )
        assert "clearance to at-risk edge" in details_past["reason"]

    def test_between_yes_margin_scales_with_band_width_not_hardcoded(self):
        """Mutation-test that _yes_inband_margin is derived as (hi-lo)/2, not
        hardcoded at 1.0: on a WIDE 6°F band, a risk_clearance of 2.0°F is
        below the real proportional margin (3.0) and must NOT lock -- but
        WOULD lock under a hardcoded 1.0°F margin (2.0 >= 1.0). Every other
        YES test in this file uses a 2°F band where the real margin (1.0)
        happens to equal what a hardcoded constant would also be, so none of
        them alone can catch this."""
        locked, _prob, details = self._call_metar_lock_in(
            current_temp=64.0,
            lo=60.0,
            hi=66.0,  # width 6.0, half 3.0
            local_hour=16,
            ticker=self.HIGH_TICKER,
            max_temp_f=64.0,  # risk_clearance = 66.0 - 64.0 = 2.0
        )
        assert not locked, (
            "YES lock fired with only 2.0°F clearance on a 6°F-wide band "
            f"(needs 3.0°F) -- margin may be hardcoded instead of "
            f"proportional to band width: {details}"
        )

    def test_between_stale_prior_day_obs_not_locked(self):
        """A METAR observation whose own local date doesn't match target_date
        (the exact OKC/SATX bug from e395392) must not lock, even with a
        temp deep in NO territory."""
        from datetime import timedelta

        yesterday = datetime.now(ZoneInfo("America/New_York")).date() - timedelta(
            days=1
        )
        locked, _prob, details = self._call_metar_lock_in(
            current_temp=95.0,
            lo=85.5,
            hi=87.5,
            local_hour=19,
            ticker=self.HIGH_TICKER,
            max_temp_f=95.0,
            obs_date=yesterday,
        )
        assert not locked, f"stale prior-day obs must not lock, got {details}"
        assert "!=" in details["reason"]

    def test_between_too_early_hour_not_locked(self):
        """Before 14:00 local, even a deep-NO daily extreme must not lock."""
        locked, _prob, details = self._call_metar_lock_in(
            current_temp=95.0,
            lo=85.5,
            hi=87.5,
            local_hour=10,
            ticker=self.HIGH_TICKER,
            max_temp_f=95.0,
        )
        assert not locked, f"pre-14:00 obs must not lock, got {details}"
        assert "too early" in details["reason"]

    def test_between_hour_boundary_13_vs_14(self):
        """Mutation-test the 14:00 hour boundary directly: hour 13 must not
        lock, hour 14 (same deep-NO temp) must lock -- catches a shift of
        the cutoff to e.g. 15 or 16 that the other tests (which all use
        hour 16/17/19) wouldn't notice."""
        locked_13, _p13, details_13 = self._call_metar_lock_in(
            current_temp=95.0,
            lo=85.5,
            hi=87.5,
            local_hour=13,
            ticker=self.HIGH_TICKER,
            max_temp_f=95.0,
        )
        assert not locked_13, f"hour 13 must not lock, got {details_13}"
        assert "too early" in details_13["reason"]

        locked_14, _p14, details_14 = self._call_metar_lock_in(
            current_temp=95.0,
            lo=85.5,
            hi=87.5,
            local_hour=14,
            ticker=self.HIGH_TICKER,
            max_temp_f=95.0,
        )
        assert locked_14, f"hour 14 must lock (>= the 14:00 gate), got {details_14}"

    def test_between_falls_back_to_current_temp_when_daily_extreme_missing(self):
        """When max_temp_f/min_temp_f is absent from the METAR observation
        (e.g. a station that doesn't report it), the NO branches still fire
        off the current_temp_f fallback -- sound because the instantaneous
        reading is always a valid lower bound on the true daily max (or
        upper bound on the true daily min), so if IT already cleared the
        margin the true extreme has too."""
        locked, _prob, details = self._call_metar_lock_in(
            current_temp=95.0,  # no max_temp_f/min_temp_f supplied
            lo=85.5,
            hi=87.5,
            local_hour=16,
            ticker=self.HIGH_TICKER,
        )
        assert locked
        assert details["outcome"] == "no"
        # Reason must NOT claim "daily high-so-far" here -- no real daily
        # extreme was available, so the log should honestly say the
        # instantaneous reading was used as a (still-sound) bound instead.
        assert "no daily extreme available" in details["reason"]
        assert "high-so-far" not in details["reason"]

    def test_between_no_daily_extreme_blocks_yes_lock(self):
        """Unlike the NO branches, a YES lock CANNOT safely use the
        current_temp_f fallback (an instantaneous in-band reading says
        nothing about whether the actual daily extreme already exceeded the
        band earlier today) -- must not lock even though this current temp
        alone would have satisfied the YES clearance requirement."""
        locked, _prob, details = self._call_metar_lock_in(
            current_temp=86.0,  # no max_temp_f supplied -- would satisfy YES if used
            lo=85.5,
            hi=87.5,
            local_hour=16,
            ticker=self.HIGH_TICKER,
        )
        assert not locked, (
            f"YES lock fired without a real daily extreme available: {details}"
        )
        assert "no daily extreme available" in details["reason"]

    def test_between_daily_extreme_zero_is_not_treated_as_missing(self):
        """A daily extreme of exactly 0.0°F (a legitimate, if unusual,
        reading) must be used as-is, not treated as falsy/missing and
        replaced by current_temp_f -- mutation-tests the `is not None` check
        against an `or`-based falsy check, which would use current_temp_f
        (20.0, deep in NO territory) instead of the real 0.0°F extreme
        (nowhere near the band, so genuinely undetermined -- not locked)."""
        locked, _prob, details = self._call_metar_lock_in(
            current_temp=20.0,  # would lock NO if wrongly used instead of 0.0
            lo=5.5,
            hi=7.5,
            local_hour=16,
            ticker=self.HIGH_TICKER,
            max_temp_f=0.0,
        )
        assert not locked, (
            f"0.0°F daily extreme appears to have been treated as missing "
            f"(fell back to current_temp_f=20.0 instead): {details}"
        )

    def test_between_low_market_ticker_prefix_selects_min_not_max(self):
        """A LOW-series ticker must read min_temp_f, ignoring max_temp_f even
        when max_temp_f alone would suggest a HIGH-side NO lock."""
        locked, _prob, details = self._call_metar_lock_in(
            current_temp=65.0,
            lo=63.5,
            hi=65.5,
            local_hour=16,
            ticker=self.LOW_TICKER,
            max_temp_f=95.0,  # would be a HIGH-market NO lock if wrongly used
            min_temp_f=65.0,  # inside the band, safe half (risk_clearance=1.5) -> YES
        )
        assert locked
        assert details["outcome"] == "yes", (
            f"LOW-ticker market used max_temp_f instead of min_temp_f: {details}"
        )


# ── P2-15: get_live_precip_obs caching, locking, circuit breaker ──────────────


def _reset_nws_cb():
    """Reset nws circuit breaker and precip cache to clean state."""
    import nws

    nws._precip_cache.clear()
    cb = nws._nws_cb
    cb._failure_count = 0
    cb._opened_at = None
    cb._wall_opened_at = None


class TestGetLivePrecipObs:
    """P2-15: get_live_precip_obs must have caching, thread safety, and circuit breaker."""

    def setup_method(self):
        _reset_nws_cb()

    def test_result_cached_within_obs_ttl(self):
        """Second call within OBS_TTL must not fetch from network."""
        import nws

        call_count = [0]

        def fake_get(url, *a, **kw):
            call_count[0] += 1
            return {"properties": {"precipitationLastHour": {"value": 2.54}}}

        with patch.object(nws, "_get", fake_get):
            with patch.object(nws, "_get_obs_station", return_value="KJFK"):
                nws.get_live_precip_obs("NYC", (40.7, -74.0, 10))
                first_calls = call_count[0]
                nws.get_live_precip_obs("NYC", (40.7, -74.0, 10))
                assert call_count[0] == first_calls, (
                    "Second call within TTL must serve from cache, not re-fetch"
                )

    def test_cache_expires_after_obs_ttl(self):
        """After OBS_TTL the function must re-fetch."""
        import nws

        call_count = [0]

        def fake_get(url, *a, **kw):
            call_count[0] += 1
            return {"properties": {"precipitationLastHour": {"value": 5.08}}}

        with patch.object(nws, "_get", fake_get):
            with patch.object(nws, "_get_obs_station", return_value="KJFK"):
                nws.get_live_precip_obs("NYC", (40.7, -74.0, 10))
                nws._precip_cache.set_at("NYC", 0.2, time.monotonic() - nws.OBS_TTL - 1)
                nws.get_live_precip_obs("NYC", (40.7, -74.0, 10))
                assert call_count[0] == 2, "Expired cache must trigger a re-fetch"

    def test_circuit_breaker_open_returns_none(self):
        """When circuit is open, must return None without fetching."""
        import nws

        nws._nws_cb._opened_at = time.monotonic()
        nws._nws_cb._wall_opened_at = time.time()

        result = nws.get_live_precip_obs("NYC", (40.7, -74.0, 10))
        assert result is None, "Open circuit must return None"

    def test_exception_triggers_circuit_breaker_failure(self):
        """A fetch exception must call record_failure on the circuit breaker."""
        import nws

        before = nws._nws_cb._failure_count

        with patch.object(nws, "_get", side_effect=RuntimeError("timeout")):
            with patch.object(nws, "_get_obs_station", return_value="KJFK"):
                result = nws.get_live_precip_obs("NYC", (40.7, -74.0, 10))

        assert result is None
        assert nws._nws_cb._failure_count > before, (
            "Exception must increment circuit breaker failure count"
        )

    def test_thread_safe_no_errors(self):
        """Concurrent calls for different cities must not raise."""
        import nws

        def fake_get(url, *a, **kw):
            time.sleep(0.01)
            return {"properties": {"precipitationLastHour": {"value": 0.0}}}

        results = []
        errors = []

        def fetch(city):
            try:
                with patch.object(nws, "_get", fake_get):
                    with patch.object(nws, "_get_obs_station", return_value="KJFK"):
                        r = nws.get_live_precip_obs(city, (40.7, -74.0, 10))
                        results.append(r)
            except Exception as exc:
                errors.append(exc)

        cities = ["NYC", "BOS", "CHI", "LA", "DAL"]
        threads = [threading.Thread(target=fetch, args=(c,)) for c in cities]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Thread errors: {errors}"
        assert len(results) == 5

    def test_6h_fallback_converts_correctly(self):
        """precipitationLast6Hours must divide by 6 and convert mm→inches."""
        import nws

        # 6 * 25.4 mm = 152.4 mm total → avg 25.4 mm/h → 1.0 inch/h
        with patch.object(
            nws,
            "_get",
            return_value={
                "properties": {
                    "precipitationLastHour": {"value": None},
                    "precipitationLast6Hours": {"value": 152.4},
                }
            },
        ):
            with patch.object(nws, "_get_obs_station", return_value="KJFK"):
                result = nws.get_live_precip_obs("NYC", (40.7, -74.0, 10))

        assert result == pytest.approx(1.0, abs=0.001), (
            f"6h fallback: expected 1.0 inch, got {result}"
        )

    def test_precip_cache_exported(self):
        """_precip_cache must exist as a module-level ForecastCache in nws."""
        import nws
        from forecast_cache import ForecastCache

        assert hasattr(nws, "_precip_cache")
        assert isinstance(nws._precip_cache, ForecastCache)
