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

    def test_t_ticker_still_works_as_before(self):
        """T-ticker (above/below) markets are unaffected by the B-ticker changes."""
        from datetime import datetime
        from unittest.mock import patch

        import settlement_monitor as sm

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
