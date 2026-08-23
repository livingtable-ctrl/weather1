"""Tests for METAR settlement lag monitoring."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCitySeriesTickerDerivation:
    def test_stale_known_weather_series_raises_at_import(self, monkeypatch):
        """_CITY_SERIES_TICKER is derived from KNOWN_WEATHER_SERIES at import
        time (settlement_monitor.py) — if a city's KXHIGH* ticker is ever
        renamed/retired without updating KNOWN_WEATHER_SERIES to match (the
        exact class of bug that silently dropped KXLOWLAX this week), that
        derivation must fail loudly with a clear AssertionError rather than
        silently producing a stale ticker."""
        import importlib

        import settlement_monitor
        import weather_markets as wm

        # Establish a known-good baseline first: if this test runs before
        # anything else has imported settlement_monitor, the module hasn't
        # executed its derivation loop yet, and the plain `import` above
        # would just cache it — reload here forces one clean execution
        # against real (unpatched) data, regardless of test run order.
        importlib.reload(settlement_monitor)

        stale_series = [t for t in wm.KNOWN_WEATHER_SERIES if t != "KXHIGHNY"]
        monkeypatch.setattr(wm, "KNOWN_WEATHER_SERIES", stale_series)

        try:
            with pytest.raises(AssertionError, match="NYC"):
                importlib.reload(settlement_monitor)
        finally:
            # Restore real state so later tests in this process see a
            # correctly-derived module regardless of this test's outcome.
            monkeypatch.undo()
            importlib.reload(settlement_monitor)


class TestBuildSettlementSignal:
    def test_signal_structure(self):
        """build_settlement_signal returns dict with required keys."""
        from settlement_monitor import build_settlement_signal

        signal = build_settlement_signal(
            ticker="KXHIGHNY-26APR17-T72",
            city="NYC",
            outcome="yes",
            confidence=0.92,
            current_temp_f=80.0,
            threshold_f=72.0,
        )

        assert signal["ticker"] == "KXHIGHNY-26APR17-T72"
        assert signal["city"] == "NYC"
        assert signal["outcome"] == "yes"
        assert signal["confidence"] == 0.92
        assert "created_at" in signal
        assert signal["source"] == "metar_settlement_lag"

    def test_write_settlement_signals_creates_file(self, tmp_path, monkeypatch):
        """write_settlement_signals writes JSON to signals file."""
        import settlement_monitor

        signals_path = tmp_path / "settlement_signals.json"
        monkeypatch.setattr(settlement_monitor, "_SIGNALS_PATH", signals_path)

        from settlement_monitor import build_settlement_signal, write_settlement_signals

        signal = build_settlement_signal("TICKER", "NYC", "yes", 0.92, 80.0, 72.0)
        write_settlement_signals([signal])

        assert signals_path.exists()
        data = json.loads(signals_path.read_text())
        assert len(data["signals"]) == 1
        assert data["signals"][0]["ticker"] == "TICKER"

    def test_read_settlement_signals_empty_on_no_file(self, tmp_path, monkeypatch):
        """read_settlement_signals returns [] when file does not exist."""
        import settlement_monitor

        monkeypatch.setattr(
            settlement_monitor, "_SIGNALS_PATH", tmp_path / "nonexistent.json"
        )

        from settlement_monitor import read_settlement_signals

        assert read_settlement_signals() == []

    def test_signals_expire_after_window(self, tmp_path, monkeypatch):
        """Signals older than max_age_minutes are filtered out."""
        from datetime import timedelta

        import settlement_monitor

        signals_path = tmp_path / "settlement_signals.json"
        monkeypatch.setattr(settlement_monitor, "_SIGNALS_PATH", signals_path)

        # Write a signal with an old timestamp
        old_time = (datetime.now(UTC) - timedelta(minutes=90)).isoformat()
        signals_path.write_text(
            json.dumps(
                {
                    "signals": [
                        {"ticker": "OLD", "created_at": old_time, "outcome": "yes"}
                    ]
                }
            )
        )

        from settlement_monitor import read_settlement_signals

        result = read_settlement_signals(max_age_minutes=60)
        assert all(s["ticker"] != "OLD" for s in result)


class TestCheckBetweenSettlement:
    """Unit tests for _check_between_settlement (between-bucket lockout logic).

    Rewritten 2026-08-09 (backlog.txt "SETTLEMENT_MONITOR.PY'S OWN
    BETWEEN-BUCKET LOCK...") — the function now keys off max_temp_f (the
    running daily high), not current_temp_f, since locking off the
    instantaneous reading was the AC3 bug this rewrite fixes.
    """

    def test_max_temp_inside_band_with_full_clearance_locks_yes(self):
        """max_temp_f at the lower edge → max clearance to the at-risk upper
        edge (full band width) → locked YES."""
        from settlement_monitor import _check_between_settlement

        # risk_clearance = upper(71.5) - max(69.5) = 2.0 >= margin (band
        # width / 2 = 1.0)
        result = _check_between_settlement(
            current_temp_f=69.5, lower_f=69.5, upper_f=71.5, max_temp_f=69.5
        )
        assert result["locked"] is True
        assert result["outcome"] == "yes"
        assert result["confidence"] == pytest.approx(0.80, abs=0.001)

    def test_max_temp_at_yes_margin_boundary_locks_yes(self):
        """max_temp_f exactly at the half-band-width margin → locks (>=, not >)."""
        from settlement_monitor import _check_between_settlement

        # risk_clearance = 71.5 - 70.5 = 1.0 == margin (2.0/2) exactly
        result = _check_between_settlement(
            current_temp_f=70.5, lower_f=69.5, upper_f=71.5, max_temp_f=70.5
        )
        assert result["locked"] is True
        assert result["outcome"] == "yes"
        assert result["confidence"] == pytest.approx(0.75, abs=0.001)

    def test_max_temp_just_under_yes_margin_not_locked(self):
        """max_temp_f just inside the at-risk edge of the margin → not locked."""
        from settlement_monitor import _check_between_settlement

        # risk_clearance = 71.5 - 70.51 = 0.99 < margin (1.0)
        result = _check_between_settlement(
            current_temp_f=70.51, lower_f=69.5, upper_f=71.5, max_temp_f=70.51
        )
        assert result["locked"] is False

    def test_yes_requires_real_max_temp_not_current_temp_fallback(self):
        """AC3 regression guard: an in-band INSTANTANEOUS reading alone must
        never lock YES — only a real max_temp_f can. Positive control: the
        identical band/current_temp_f locks YES once a real max_temp_f
        (test_max_temp_inside_band_with_full_clearance_locks_yes, same
        current_temp_f=69.5) is supplied, proving this isn't vacuously
        unlocked for some unrelated reason."""
        from settlement_monitor import _check_between_settlement

        result = _check_between_settlement(
            current_temp_f=69.5, lower_f=69.5, upper_f=71.5, max_temp_f=None
        )
        assert result["locked"] is False

    def test_max_temp_cleared_upper_edge_with_margin_locks_no(self):
        """max_temp_f >2°F above the upper edge → locked=True, outcome=no."""
        from settlement_monitor import _check_between_settlement

        # clearance = 73.6 - 71.5 = 2.1 >= margin(1.0) + 1.0 = 2.0
        result = _check_between_settlement(
            current_temp_f=73.6, lower_f=69.5, upper_f=71.5, max_temp_f=73.6
        )
        assert result["locked"] is True
        assert result["outcome"] == "no"
        assert result["confidence"] == pytest.approx(0.663, abs=0.001)

    def test_max_temp_just_under_no_margin_not_locked(self):
        """max_temp_f just under the NO margin → not locked."""
        from settlement_monitor import _check_between_settlement

        # clearance = 73.4 - 71.5 = 1.9 < 2.0
        result = _check_between_settlement(
            current_temp_f=73.4, lower_f=69.5, upper_f=71.5, max_temp_f=73.4
        )
        assert result["locked"] is False

    def test_max_temp_at_exact_no_margin_boundary_locks_no(self):
        """max_temp_f exactly at the NO margin boundary → locks (>=, not >).
        Mutation guard: a `>` mutant of the NO branch's `>=` comparison
        passes every other test in this class (all use clearance strictly
        above or below 2.0) but fails this one."""
        from settlement_monitor import _check_between_settlement

        # clearance = 73.5 - 71.5 = 2.0 == margin exactly
        result = _check_between_settlement(
            current_temp_f=73.5, lower_f=69.5, upper_f=71.5, max_temp_f=73.5
        )
        assert result["locked"] is True
        assert result["outcome"] == "no"

    def test_no_lock_fallback_stays_unlocked_when_current_temp_below_band(self):
        """The exact fallback path the OLD code got wrong: max_temp_f
        unavailable, current_temp_f well below the band. Must NOT lock NO
        (current_temp_f below the band says nothing about whether the real
        high already passed through/above it earlier in the day) — only
        current_temp_f ABOVE the band with margin is a safe NO fallback."""
        from settlement_monitor import _check_between_settlement

        result = _check_between_settlement(
            current_temp_f=76.0, lower_f=85.5, upper_f=87.5, max_temp_f=None
        )
        assert result["locked"] is False

    def test_no_lock_falls_back_to_current_temp_when_max_temp_unavailable(self):
        """When max_temp_f is unavailable, the NO direction safely falls back
        to current_temp_f (current_temp_f <= true daily high always, so a
        cleared margin on current_temp_f guarantees the real high cleared it
        too)."""
        from settlement_monitor import _check_between_settlement

        # clearance = 74.0 - 71.5 = 2.5 >= 2.0
        result = _check_between_settlement(
            current_temp_f=74.0, lower_f=69.5, upper_f=71.5, max_temp_f=None
        )
        assert result["locked"] is True
        assert result["outcome"] == "no"

    def test_running_high_inside_band_locks_yes_despite_evening_cooling(self):
        """AC3 regression guard, reproducing the entry's own concrete failure
        scenario: the real daily high (86.5°F) occurred earlier and sits
        safely inside the band, but the station has since cooled well below
        the band's lower edge by evening. The old (buggy) instantaneous-
        reading logic would have locked NO here (wrong — the real answer is
        YES); the fixed logic must lock YES from the real max_temp_f."""
        from settlement_monitor import _check_between_settlement

        result = _check_between_settlement(
            current_temp_f=76.0, lower_f=85.5, upper_f=87.5, max_temp_f=86.5
        )
        assert result["locked"] is True
        assert result["outcome"] == "yes"

    def test_running_high_still_below_band_stays_uncertain_not_locked(self):
        """AC3 regression guard: a running high that hasn't reached the band
        yet must NOT lock NO (the true high can still rise into or past the
        band later in the day) — even though the old instantaneous-reading
        logic's symmetric clearance check would have locked NO here."""
        from settlement_monitor import _check_between_settlement

        result = _check_between_settlement(
            current_temp_f=80.0, lower_f=85.5, upper_f=87.5, max_temp_f=80.0
        )
        assert result["locked"] is False

    def test_yes_gated_on_max_temp_not_current_temp_when_current_exceeds_max(self):
        """AUD-0016 regression guard: a still-rising instantaneous reading
        (current_temp_f=67.0) that is IN-band must not lock YES when the
        independently-cached authoritative running high (max_temp_f=65.0)
        is still below the band — the exact scenario the audit reproduced.
        Before the fix, comp_temp = max(current_temp_f, max_temp_f) reduced
        to current_temp_f here and the lock fired off the instantaneous
        reading alone, contradicting this function's own 'YES only from a
        REAL max_temp_f' invariant."""
        from settlement_monitor import _check_between_settlement

        result = _check_between_settlement(
            current_temp_f=67.0, lower_f=66.5, upper_f=68.5, max_temp_f=65.0
        )
        assert result["locked"] is False

    def test_yes_lock_uses_comp_temp_for_clearance_and_reporting(self):
        """AUD-0016 round-2 fix: clearance (and the reported comp_temp_f)
        is measured against comp_temp = max(current_temp_f, max_temp_f),
        not max_temp_f alone -- current_temp_f=70.0 is fresher/higher than
        max_temp_f=69.5 but still within the band (<= upper_f=71.5), so
        the lock still fires, but with the NARROWER clearance the fresher
        reading actually leaves (1.5, not the 2.0 max_temp_f alone would
        suggest), and comp_temp_f correctly reports 70.0 (the value the
        confidence was actually computed from), not the stale 69.5."""
        from settlement_monitor import _check_between_settlement

        # comp_temp = max(70.0, 69.5) = 70.0; clearance = 71.5-70.0 = 1.5
        # >= margin (1.0) -> locks YES.
        result = _check_between_settlement(
            current_temp_f=70.0, lower_f=69.5, upper_f=71.5, max_temp_f=69.5
        )
        assert result["locked"] is True
        assert result["outcome"] == "yes"
        assert result["confidence"] == pytest.approx(0.775, abs=0.001)
        assert result["comp_temp_f"] == pytest.approx(70.0)

    def test_yes_lock_still_fires_for_a_small_stale_max_disagreement(self):
        """Positive control: a SMALL disagreement between current_temp_f
        and max_temp_f (0.5°F) doesn't automatically block the lock --
        only when the remaining clearance actually drops below the margin
        (see the next test) does it refuse. Proves the mechanism is
        "insufficient remaining margin", not "any divergence at all"."""
        from settlement_monitor import _check_between_settlement

        # max_temp_f=66.5 is at the lower edge of [66.5, 68.5]; comp_temp
        # = max(67.0, 66.5) = 67.0; clearance = 68.5-67.0 = 1.5 >= margin
        # (1.0) -> still locks YES.
        result = _check_between_settlement(
            current_temp_f=67.0, lower_f=66.5, upper_f=68.5, max_temp_f=66.5
        )
        assert result["locked"] is True
        assert result["outcome"] == "yes"

    def test_yes_refused_when_fresher_current_temp_eats_the_full_margin(self):
        """Round-2 independent-review regression guard: the FIRST version
        of the AUD-0016 fix measured clearance against max_temp_f alone
        (not comp_temp), which made the gate MORE permissive than pre-fix
        HEAD in exactly this scenario -- current_temp_f=68.0 is fresher/
        higher than max_temp_f=66.5 and still within the band, but a
        clearance measured against the stale max_temp_f (2.0) would
        overstate the true margin; measured correctly against comp_temp
        (0.5), it's below the 1.0 margin and must NOT lock. The first fix
        incorrectly locked this at confidence 0.80 -- exactly cron.py's
        force-close threshold."""
        from settlement_monitor import _check_between_settlement

        # comp_temp = max(68.0, 66.5) = 68.0; clearance = 68.5-68.0 = 0.5
        # < margin (1.0) -> must NOT lock.
        result = _check_between_settlement(
            current_temp_f=68.0, lower_f=66.5, upper_f=68.5, max_temp_f=66.5
        )
        assert result["locked"] is False

    def test_yes_refused_when_current_temp_has_cleared_the_band_entirely(self):
        """Round-1 independent-review regression guard (the original
        counter-example): current_temp_f=70.0 has already cleared
        upper_f=68.5 entirely, while max_temp_f=66.5 is stale and still
        shows in-band. comp_temp=70.0 pushes clearance negative
        (68.5-70.0=-1.5), which fails the margin check outright -- no
        separate veto needed once clearance is measured against comp_temp
        rather than max_temp_f."""
        from settlement_monitor import _check_between_settlement

        result = _check_between_settlement(
            current_temp_f=70.0, lower_f=66.5, upper_f=68.5, max_temp_f=66.5
        )
        assert result["locked"] is False


class TestBTickerParsing:
    """B-ticker (between-bucket) detection in check_city_settlement."""

    def test_b_ticker_outside_near_edge_not_locked(self):
        """B-ticker market with daily high just outside band (clearance <
        2°F) → no signal."""
        from datetime import datetime
        from unittest.mock import patch

        import settlement_monitor as sm

        fake_obs = {
            "current_temp_f": 73.0,  # 1.5°F above upper=71.5 → clearance < 2.0
            "obs_time": datetime.now(UTC),
        }
        mock_market = {
            "direction": "between",
            "lower": 69.5,
            "upper": 71.5,
            "ticker": "KXHIGHNY-26MAY17-B70.5",
            "threshold": None,
        }

        with (
            patch("metar.fetch_metar", return_value=fake_obs),
            patch("metar.fetch_metar_daily_extreme", return_value=73.0),
        ):
            signals = sm.check_city_settlement("NYC", [mock_market])

        assert signals == []

    def test_b_ticker_yes_signal_when_max_temp_inside(self):
        """B-ticker locked YES when the real daily high (from
        fetch_metar_daily_extreme, NOT fetch_metar()'s own max_temp_f field)
        is inside the band with sufficient clearance to the at-risk edge."""
        from datetime import datetime
        from unittest.mock import patch

        import settlement_monitor as sm

        fake_obs = {
            # Deliberately <= max_temp_f below, so comp_temp's
            # max(current_temp_f, max_temp_f) hardening doesn't override
            # the daily-high value this test means to exercise.
            "current_temp_f": 68.0,
            "obs_time": datetime.now(UTC),
        }
        mock_market = {
            "direction": "between",
            "lower": 69.5,
            "upper": 71.5,
            "ticker": "KXHIGHNY-26MAY17-B70.5",
            "threshold": None,
        }

        with (
            patch("metar.fetch_metar", return_value=fake_obs),
            patch("metar.fetch_metar_daily_extreme", return_value=69.5),
        ):
            signals = sm.check_city_settlement("NYC", [mock_market])

        assert len(signals) == 1
        assert signals[0]["outcome"] == "yes"
        assert signals[0]["ticker"] == "KXHIGHNY-26MAY17-B70.5"
        assert signals[0]["comp_temp_f"] == pytest.approx(69.5)
        assert signals[0]["max_temp_f"] == pytest.approx(69.5)

    def test_b_ticker_log_labels_daily_high_when_comp_temp_is_max_temp(self, caplog):
        """Round-3 independent-review regression guard (F2): the log-label
        fix (settlement_monitor.py's check_city_settlement) was previously
        untested -- a mutation reverting its condition to the weaker
        `max_temp_f is not None` check survived the full suite. When
        comp_temp_f actually equals max_temp_f (the ordinary case), the
        log line must say "daily-high"."""
        import logging
        from datetime import datetime
        from unittest.mock import patch

        import settlement_monitor as sm

        fake_obs = {"current_temp_f": 68.0, "obs_time": datetime.now(UTC)}
        mock_market = {
            "direction": "between",
            "lower": 69.5,
            "upper": 71.5,
            "ticker": "KXHIGHNY-26MAY17-B70.5",
            "threshold": None,
        }

        with (
            patch("metar.fetch_metar", return_value=fake_obs),
            patch("metar.fetch_metar_daily_extreme", return_value=69.5),
            caplog.at_level(logging.INFO, logger="settlement_monitor"),
        ):
            signals = sm.check_city_settlement("NYC", [mock_market])

        assert len(signals) == 1
        assert any("daily-high" in r.message for r in caplog.records), (
            "expected the log line to label comp_temp_f as daily-high"
        )
        assert not any("current reading" in r.message for r in caplog.records)

    def test_b_ticker_log_labels_current_reading_when_comp_temp_is_current_temp(
        self, caplog
    ):
        """Positive control for the above: when current_temp_f is FRESHER/
        higher than max_temp_f (comp_temp_f ends up equal to
        current_temp_f, not max_temp_f), the log line must say "current
        reading", not "daily-high" -- proving the label condition actually
        distinguishes the two sources rather than only checking whether
        max_temp_f was available."""
        import logging
        from datetime import datetime
        from unittest.mock import patch

        import settlement_monitor as sm

        # current_temp_f=70.0 > max_temp_f=69.5 -> comp_temp_f=70.0.
        fake_obs = {"current_temp_f": 70.0, "obs_time": datetime.now(UTC)}
        mock_market = {
            "direction": "between",
            "lower": 69.5,
            "upper": 71.5,
            "ticker": "KXHIGHNY-26MAY17-B70.5",
            "threshold": None,
        }

        with (
            patch("metar.fetch_metar", return_value=fake_obs),
            patch("metar.fetch_metar_daily_extreme", return_value=69.5),
            caplog.at_level(logging.INFO, logger="settlement_monitor"),
        ):
            signals = sm.check_city_settlement("NYC", [mock_market])

        assert len(signals) == 1
        assert signals[0]["comp_temp_f"] == pytest.approx(70.0)
        assert any("current reading" in r.message for r in caplog.records), (
            "expected the log line to label comp_temp_f as current reading"
        )
        assert not any("daily-high" in r.message for r in caplog.records)

    def test_b_ticker_no_signal_when_max_temp_unavailable_despite_in_band_reading(
        self,
    ):
        """AC3 regression guard at the check_city_settlement integration
        level: an in-band instantaneous reading with no daily-extreme data
        available (station doesn't report it / fetch failed) must NOT
        produce a YES signal — mirrors
        test_yes_requires_real_max_temp_not_current_temp_fallback but through
        the full fetch → signal pipeline."""
        from datetime import datetime
        from unittest.mock import patch

        import settlement_monitor as sm

        fake_obs = {
            "current_temp_f": 70.5,
            "obs_time": datetime.now(UTC),
        }
        mock_market = {
            "direction": "between",
            "lower": 69.5,
            "upper": 71.5,
            "ticker": "KXHIGHNY-26MAY17-B70.5",
            "threshold": None,
        }

        with (
            patch("metar.fetch_metar", return_value=fake_obs),
            patch("metar.fetch_metar_daily_extreme", return_value=None),
        ):
            signals = sm.check_city_settlement("NYC", [mock_market])

        assert signals == []

    def test_b_ticker_locks_yes_from_max_temp_despite_evening_cooling(self):
        """Integration-level version of the entry's own failure scenario:
        real daily high sits inside the band, station has since cooled well
        below the band by evening. Must produce a YES signal, not the old
        code's wrong NO."""
        from datetime import datetime
        from unittest.mock import patch

        import settlement_monitor as sm

        fake_obs = {
            "current_temp_f": 76.0,
            "obs_time": datetime.now(UTC),
        }
        mock_market = {
            "direction": "between",
            "lower": 85.5,
            "upper": 87.5,
            "ticker": "KXHIGHNY-26MAY17-B86.5",
            "threshold": None,
        }

        with (
            patch("metar.fetch_metar", return_value=fake_obs),
            patch("metar.fetch_metar_daily_extreme", return_value=86.5),
        ):
            signals = sm.check_city_settlement("NYC", [mock_market])

        assert len(signals) == 1
        assert signals[0]["outcome"] == "yes"
        assert signals[0]["comp_temp_f"] == pytest.approx(86.5)

    def test_b_ticker_malformed_band_missing_bounds_fails_closed(self):
        """A between market dict missing 'lower'/'upper' must be skipped,
        not silently default to a fake [0.0, 0.0] band (which would
        confidently lock NO for almost any real temperature)."""
        from datetime import datetime
        from unittest.mock import patch

        import settlement_monitor as sm

        fake_obs = {
            "current_temp_f": 70.5,
            "obs_time": datetime.now(UTC),
        }
        mock_market = {
            "direction": "between",
            "ticker": "KXHIGHNY-26MAY17-B70.5",
            "threshold": None,
            # lower/upper deliberately omitted
        }

        with (
            patch("metar.fetch_metar", return_value=fake_obs),
            patch("metar.fetch_metar_daily_extreme", return_value=70.5),
        ):
            signals = sm.check_city_settlement("NYC", [mock_market])

        assert signals == []

    def test_t_ticker_still_works_as_before(self, monkeypatch):
        """T-ticker (above/below) markets are unaffected by the B-ticker changes."""
        from datetime import datetime
        from unittest.mock import patch

        import settlement_monitor as sm

        # Isolate from the real on-disk calibration model this test doesn't
        # care about -- otherwise it silently depends on whatever's in the
        # main clone's data/metar_lockout_calibration.json (opus review
        # finding, 2026-08-16). This test only checks outcome/count, but a
        # future assertion on confidence here would be flaky against live
        # file state without this.
        monkeypatch.setattr(sm, "_load_metar_calibration", lambda: None)

        fake_obs = {
            "current_temp_f": 80.0,
            "obs_time": datetime.now(UTC),
        }
        fake_lockout = {"locked": True, "outcome": "yes", "confidence": 0.95}
        mock_market = {
            "direction": "above",
            "threshold": 72.0,
            "ticker": "KXHIGHNY-26MAY17-T72",
        }

        with (
            patch("metar.fetch_metar", return_value=fake_obs),
            patch("metar.check_metar_lockout", return_value=fake_lockout),
        ):
            signals = sm.check_city_settlement("NYC", [mock_market])

        assert len(signals) == 1
        assert signals[0]["outcome"] == "yes"


class TestCheckCitySettlementDateGuard:
    """Backlog.txt "METAR above/below same-day lock-in has no per-observation
    local-date guard" (batch-27 item 1): check_city_settlement had NO
    per-observation local-date guard on EITHER branch -- a METAR obs_time
    near local midnight converts to ~11 PM the PRIOR local calendar day, and
    nothing here checked that before this fix. Its result force-closes paper
    positions via cron.py's >=0.80 gate, so a stale-obs false lock here is a
    live-money-adjacent bug, not just a signal-quality one."""

    def _stale_obs_time(self, hour=23, minute=53, tz="America/Chicago"):
        """OKC's real tz (America/Chicago) -- matches the actual OKC/SATX
        incident's own CDT-based numbers, not an arbitrary stand-in zone."""
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        yesterday_local = (datetime.now(ZoneInfo(tz)) - timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        return yesterday_local.astimezone(UTC)

    def test_t_ticker_skipped_when_obs_from_prior_local_day(self, caplog):
        """The literal historical repro: current=85.0, threshold=91.0,
        direction='above', obs from ~23:53 the PRIOR local day. Before this
        fix, check_metar_lockout still fired (locked=True, outcome='no')
        because its own local_time.hour (23) computed from that same
        prior-day obs_time passes the >=14 gate -- these are the literal
        OKC/SATX numbers already in backlog.txt."""
        import logging
        from unittest.mock import patch

        import settlement_monitor as sm

        fake_obs = {"current_temp_f": 85.0, "obs_time": self._stale_obs_time()}
        mock_market = {
            "direction": "above",
            "threshold": 91.0,
            "ticker": "KXHIGHOKC-26JUN25-T91",
        }

        with (
            patch("metar.fetch_metar", return_value=fake_obs),
            caplog.at_level(logging.INFO, logger="settlement_monitor"),
        ):
            signals = sm.check_city_settlement("OKC", [mock_market])

        assert signals == []
        assert any("prior-day temp cannot confirm" in r.message for r in caplog.records)

    def test_between_ticker_skipped_when_obs_from_prior_local_day(self):
        """Same stale-obs scenario, routed through the between-bucket path
        instead -- _check_between_settlement itself has no date-awareness
        at all, so the guard must live in check_city_settlement before
        either branch runs.

        Opus-review finding (F9): current_temp_f is kept safely inside the
        band (not exactly at the YES-lock clearance boundary, which
        _check_between_settlement would ALSO lock at today, making this
        test pass for the wrong reason if the date guard were ever removed
        and the boundary math tightened from >= to >)."""
        from unittest.mock import patch

        import settlement_monitor as sm

        fake_obs = {"current_temp_f": 86.0, "obs_time": self._stale_obs_time()}
        mock_market = {
            "direction": "between",
            "lower": 85.5,
            "upper": 87.5,
            "ticker": "KXHIGHOKC-26JUN25-B86.5",
            "threshold": None,
        }

        with (
            patch("metar.fetch_metar", return_value=fake_obs),
            patch("metar.fetch_metar_daily_extreme", return_value=86.0),
        ):
            signals = sm.check_city_settlement("OKC", [mock_market])

        assert signals == []

    def test_same_day_obs_still_produces_a_signal_as_before(self):
        """Positive control: a genuine same-day obs (datetime.now(UTC), the
        pattern every other passing test in this file already uses) must
        not be blocked by the new guard."""
        from unittest.mock import patch

        import settlement_monitor as sm

        fake_obs = {"current_temp_f": 85.0, "obs_time": datetime.now(UTC)}
        mock_market = {
            "direction": "above",
            "threshold": 91.0,
            "ticker": "KXHIGHOKC-26JUN25-T91",
        }
        fake_lockout = {"locked": True, "outcome": "no", "confidence": 0.9}

        with (
            patch("metar.fetch_metar", return_value=fake_obs),
            patch("metar.check_metar_lockout", return_value=fake_lockout),
        ):
            signals = sm.check_city_settlement("OKC", [mock_market])

        assert len(signals) == 1
        assert signals[0]["outcome"] == "no"


class TestMetarSettlementCalibration:
    """backlog.txt L4: settlement_monitor.py's T-ticker force-close path
    must apply the same METAR beta-calibration weather_markets.py's
    analyze_trade uses for fresh entries, so cron.py's >=0.80 force-close
    gate isn't evaluating a known-overconfident raw number while entries
    are priced under the calibrated one."""

    # Real production coefficients (data/metar_lockout_calibration.json as
    # of 2026-08-16, n=33) -- same values test_weather_markets.py's own
    # regression tests use, so a real orientation or cap bug here would
    # also be caught by hand-computable, cross-checked numbers rather than
    # an arbitrary toy model.
    _REAL_PARAMS = (0.22619580826228397, 0.22619580826228397, 0.4000758536385143)

    def _run(
        self, monkeypatch, outcome, confidence, params, ticker="KXHIGHNY-26MAY17-T72"
    ):
        from datetime import datetime
        from unittest.mock import patch

        import settlement_monitor as sm

        monkeypatch.setattr(sm, "_load_metar_calibration", lambda: params)
        fake_obs = {"current_temp_f": 80.0, "obs_time": datetime.now(UTC)}
        fake_lockout = {"locked": True, "outcome": outcome, "confidence": confidence}
        mock_market = {"direction": "above", "threshold": 72.0, "ticker": ticker}

        with (
            patch("metar.fetch_metar", return_value=fake_obs),
            patch("metar.check_metar_lockout", return_value=fake_lockout),
        ):
            signals = sm.check_city_settlement("NYC", [mock_market])

        assert len(signals) == 1
        return signals[0]

    def test_no_lock_orientation_round_trip_not_inverted(self, monkeypatch):
        """Regression guard for the exact bug class two opus reviews caught
        twice already this session: a NO-lock's confidence is P(NO), not
        P(YES) -- apply_metar_calibration must see raw_p_yes = 1-confidence,
        and the result must be converted back the same way. With the real
        (asymmetric-in-c) coefficients, the naive "apply directly to
        confidence" computation and the correct orientation-aware one
        diverge (0.728 vs 0.546) -- if this test only checked "changed from
        raw," an inverted implementation would pass it too."""
        signal = self._run(monkeypatch, "no", 0.93, self._REAL_PARAMS)
        assert signal["confidence"] == pytest.approx(0.5461, abs=1e-3)
        assert signal["confidence"] != pytest.approx(0.7281, abs=1e-3), (
            "confidence matches the WRONG (non-orientation-aware) computation "
            "-- NO-lock correction was applied without flipping to P(YES) first"
        )

    def test_yes_lock_calibration_crosses_the_080_gate(self, monkeypatch):
        """cron.py force-closes at confidence >= 0.80. A raw YES-lock
        confidence of 0.90 clears that gate; the real fitted model corrects
        it to ~0.71, which does NOT -- this is the actual, measurable
        behavior change the backlog entry calls out (fewer settlement-lag
        force-closes firing), not just a magnitude tweak."""
        signal = self._run(monkeypatch, "yes", 0.90, self._REAL_PARAMS)
        assert 0.90 >= 0.80, "test setup sanity: raw confidence must clear the gate"
        assert signal["confidence"] == pytest.approx(0.7103, abs=1e-3)
        assert signal["confidence"] < 0.80, (
            "calibrated confidence still clears cron.py's >=0.80 force-close "
            "gate -- the wiring isn't actually changing gate behavior"
        )

    def test_no_calibration_model_leaves_confidence_unchanged(self, monkeypatch):
        """Fresh install / below the fit's data floor -- no calibration file
        on disk yet must leave the raw confidence untouched, not raise."""
        signal = self._run(monkeypatch, "yes", 0.95, None)
        assert signal["confidence"] == pytest.approx(0.95)

    def test_magnitude_cap_uses_metar_limit_not_generic_030(self, monkeypatch):
        """Regression test for the exact HIGH finding the entry-path fix's
        review caught: reusing the generic 0.30 cap here would silently
        skip every real NO-lock correction (delta ~0.375 on this example)
        while still applying YES-lock ones. Must use the METAR-specific
        0.60 cap instead, so this correction actually applies."""
        signal = self._run(monkeypatch, "no", 0.97, self._REAL_PARAMS)
        assert signal["confidence"] != pytest.approx(0.97, abs=1e-3), (
            "a real NO-lock correction (delta ~0.375) was skipped -- check "
            "the cap constant is 0.60, not the generic 0.30"
        )
        assert signal["confidence"] == pytest.approx(0.5954, abs=1e-3)

    def test_magnitude_cap_still_skips_pathological_correction(self, monkeypatch):
        """The cap must still actually cap something -- a correction whose
        delta exceeds 0.60 (not just 0.30) must still be skipped."""
        signal = self._run(monkeypatch, "yes", 0.85, (1.0, 1.0, -10.0))
        assert signal["confidence"] == pytest.approx(0.85)

    def test_magnitude_cap_boundary_just_under_060_applies(self, monkeypatch):
        """Tighten the cap value itself, not just bracket it loosely: a
        delta of 0.59 (just under 0.60) must be applied. Opus review found
        the two tests above only prove the cap sits somewhere in
        [0.375, 0.85) -- this pins it to (0.59, 0.61), i.e. actually 0.60."""
        # a=b=1 (Platt identity slope), c solved so apply(0.90, params)
        # lands at exactly 0.31 -- delta 0.59 from raw 0.90.
        signal = self._run(monkeypatch, "yes", 0.90, (1.0, 1.0, -2.9973438774483325))
        assert signal["confidence"] == pytest.approx(0.31, abs=1e-3)

    def test_magnitude_cap_boundary_just_over_060_skips(self, monkeypatch):
        """Mirror of the test above: a delta of 0.61 (just over 0.60) must
        be skipped, keeping the raw confidence."""
        # Same construction, c solved so apply(0.90, params) lands at
        # exactly 0.29 -- delta 0.61 from raw 0.90.
        signal = self._run(monkeypatch, "yes", 0.90, (1.0, 1.0, -3.092608624391061))
        assert signal["confidence"] == pytest.approx(0.90, abs=1e-3)

    def test_between_path_not_calibrated(self, monkeypatch):
        """Scope boundary: the `between` path uses its own separate
        confidence formula and must NOT be run through METAR beta-
        calibration, even when a model is loaded and would otherwise apply."""
        from datetime import datetime
        from unittest.mock import patch

        import settlement_monitor as sm

        monkeypatch.setattr(sm, "_load_metar_calibration", lambda: self._REAL_PARAMS)
        fake_obs = {"current_temp_f": 68.0, "obs_time": datetime.now(UTC)}
        mock_market = {
            "direction": "between",
            "ticker": "KXHIGHNY-26MAY17-B70.5",
            "lower": 69.5,
            "upper": 71.5,
        }

        with (
            patch("metar.fetch_metar", return_value=fake_obs),
            patch("metar.fetch_metar_daily_extreme", return_value=69.5),
        ):
            signals = sm.check_city_settlement("NYC", [mock_market])

        assert len(signals) == 1
        # _check_between_settlement's own formula: min(0.95, 0.70 + clearance*0.05)
        # -- known-good value from TestCheckBetweenSettlement's identical inputs.
        # If calibration had leaked into this path, applying the real model
        # (a=b=0.226, c=0.400) to 0.80 would instead produce ~0.671.
        assert signals[0]["confidence"] == pytest.approx(0.80, abs=0.001)

    def test_calibration_failure_fails_closed(self, monkeypatch):
        """If _load_metar_calibration (or the calibration call itself)
        raises unexpectedly, the raw confidence must be used, not propagate
        the exception and drop the settlement signal entirely."""
        from datetime import datetime
        from unittest.mock import patch

        import settlement_monitor as sm

        def _boom():
            raise RuntimeError("disk read failed")

        monkeypatch.setattr(sm, "_load_metar_calibration", _boom)
        fake_obs = {"current_temp_f": 80.0, "obs_time": datetime.now(UTC)}
        fake_lockout = {"locked": True, "outcome": "yes", "confidence": 0.88}
        mock_market = {
            "direction": "above",
            "threshold": 72.0,
            "ticker": "KXHIGHNY-26MAY17-T72",
        }

        with (
            patch("metar.fetch_metar", return_value=fake_obs),
            patch("metar.check_metar_lockout", return_value=fake_lockout),
        ):
            signals = sm.check_city_settlement("NYC", [mock_market])

        assert len(signals) == 1
        assert signals[0]["confidence"] == pytest.approx(0.88)


@pytest.mark.skipif(
    sys.platform != "win32", reason="cross-process lock uses msvcrt (Windows-only)"
)
class TestSettlementMonitorLock:
    """AUD-0051: settlement_monitor.py had no application-level guard against
    two overlapping runs -- protection relied entirely on Windows Task
    Scheduler's (never explicitly set) default overlap policy. Held for the
    whole run, same pattern as cron.py's LOCK_PATH."""

    def test_run_settlement_monitor_acquires_lock_and_runs_loop(
        self, tmp_path, monkeypatch
    ):
        """Positive control for the skip-test below: proves the loop DOES
        run in the normal (uncontended) case, so a later assertion that it
        did NOT run under contention is actually discriminating."""
        import settlement_monitor as sm

        lock_path = tmp_path / ".settlement_monitor.lock"
        monkeypatch.setattr(sm, "_SETTLEMENT_LOCK_PATH", lock_path)

        calls = []
        monkeypatch.setattr(
            sm,
            "_run_settlement_monitor_loop",
            lambda client, duration_minutes: calls.append((client, duration_minutes)),
        )

        client = object()
        sm.run_settlement_monitor(client, duration_minutes=5)

        assert calls == [(client, 5)]

        from safe_io import CrossProcessLock

        # Lock must be released afterward -- immediately re-acquirable.
        lock = CrossProcessLock(lock_path, timeout=2.0)
        assert lock.acquire() is True
        lock.release()

    def test_second_call_skips_loop_while_first_holds_lock(
        self, tmp_path, monkeypatch, caplog
    ):
        """Mutation-tested: without the lock wrap in run_settlement_monitor,
        this test's `calls` would be non-empty (the loop always runs) --
        the assertion only holds because the fix makes an already-locked
        instance skip immediately instead of racing the holder."""
        import settlement_monitor as sm
        from safe_io import CrossProcessLock

        lock_path = tmp_path / ".settlement_monitor.lock"
        monkeypatch.setattr(sm, "_SETTLEMENT_LOCK_PATH", lock_path)
        # Opus review: don't burn 5 real seconds waiting out the production
        # contention deadline just to prove the skip path.
        monkeypatch.setattr(sm, "_SETTLEMENT_LOCK_TIMEOUT_SECONDS", 0.2)

        calls = []
        monkeypatch.setattr(
            sm,
            "_run_settlement_monitor_loop",
            lambda client, duration_minutes: calls.append(1),
        )

        holder = CrossProcessLock(lock_path, timeout=2.0)
        assert holder.acquire() is True
        try:
            with caplog.at_level("ERROR"):
                sm.run_settlement_monitor(object(), duration_minutes=5)
        finally:
            holder.release()

        assert not calls, (
            "the monitoring loop must not run while another instance holds "
            "the exclusivity lock"
        )
        assert any(
            "lock" in r.message.lower()
            for r in caplog.records
            if r.levelname == "ERROR"
        ), "must log at ERROR when skipping due to contention"


class TestSettlementMonitorPollingErrorVisibility:
    """AUD-0047: the two exception handlers in the polling loop's per-city
    body used to log at DEBUG only -- invisible on console (main.py's
    console handler is INFO-level) for a task that runs unattended daily."""

    @staticmethod
    def _isolate_single_city(monkeypatch, sm):
        """One fake city, monitoring window forced wide open so the real
        wall-clock hour never gates the per-city body out."""
        monkeypatch.setattr(
            sm,
            "_MONITOR_CITIES",
            {"NYC": {"station": "KNYC", "tz": "America/New_York"}},
        )
        monkeypatch.setattr(sm, "_CITY_SERIES_TICKER", {"NYC": "KXHIGHNY"})
        monkeypatch.setattr(sm, "_MONITOR_START_HOUR", 0)
        monkeypatch.setattr(sm, "_MONITOR_END_HOUR", 24)

    @staticmethod
    def _stop_after_one_pass(monkeypatch, sm):
        """time.sleep is called exactly once per while-loop pass, at the very
        end -- raising from it deterministically stops the loop after
        processing every city exactly once, with no real waiting and no need
        to fake datetime.now() itself."""

        class _StopLoop(Exception):
            pass

        def _stop(*_a, **_kw):
            raise _StopLoop

        monkeypatch.setattr(sm.time, "sleep", _stop)
        return _StopLoop

    def test_market_fetch_failure_logs_at_warning_not_debug(self, monkeypatch, caplog):
        import logging

        import settlement_monitor as sm

        self._isolate_single_city(monkeypatch, sm)
        stop_loop = self._stop_after_one_pass(monkeypatch, sm)

        class _FakeClient:
            def get_markets(self, **_kwargs):
                raise RuntimeError("simulated network blip")

        with (
            caplog.at_level(logging.DEBUG, logger="settlement_monitor"),
            pytest.raises(stop_loop),
        ):
            sm._run_settlement_monitor_loop(_FakeClient(), duration_minutes=120)

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("market fetch" in r.message for r in warnings), (
            "a market-fetch failure must log at WARNING, not DEBUG, to be "
            "visible on an unattended daily cron run's console"
        )
        # Positive control: prove DEBUG-level records ARE being captured at
        # all here (caplog is at DEBUG level) -- otherwise the assertion
        # above could pass vacuously if this handler silently stopped
        # logging altogether instead of merely logging at the wrong level.
        assert any("market fetch" in r.message for r in caplog.records), (
            "the market-fetch failure must be logged at SOME level"
        )

    def test_general_per_city_error_logs_at_warning_not_debug(
        self, monkeypatch, caplog
    ):
        import logging

        import settlement_monitor as sm

        self._isolate_single_city(monkeypatch, sm)
        stop_loop = self._stop_after_one_pass(monkeypatch, sm)

        # Market fetch itself succeeds (empty result) so the INNER handler
        # never fires -- isolates the OUTER per-city handler specifically.
        def _boom(_city, _active_tickers):
            raise RuntimeError("simulated settlement-check crash")

        monkeypatch.setattr(sm, "check_city_settlement", _boom)

        class _FakeClient:
            def get_markets(self, **_kwargs):
                return []

        with (
            caplog.at_level(logging.DEBUG, logger="settlement_monitor"),
            pytest.raises(stop_loop),
        ):
            sm._run_settlement_monitor_loop(_FakeClient(), duration_minutes=120)

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("NYC error" in r.message for r in warnings), (
            "a general per-city error must log at WARNING, not DEBUG, to be "
            "visible on an unattended daily cron run's console"
        )
        assert any("NYC error" in r.message for r in caplog.records), (
            "the per-city error must be logged at SOME level"
        )
