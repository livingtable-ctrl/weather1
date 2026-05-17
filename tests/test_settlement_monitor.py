"""Tests for METAR settlement lag monitoring."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


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
    """Unit tests for _check_between_settlement (between-bucket lockout logic)."""

    def test_inside_band_locks_yes(self):
        """Temp inside band → locked=True, outcome=yes (any clearance suffices)."""
        from settlement_monitor import _check_between_settlement

        # clearance from lower = 70.5 - 69.5 = 1.0, from upper = 71.5 - 70.5 = 1.0
        result = _check_between_settlement(70.5, lower_f=69.5, upper_f=71.5)
        assert result["locked"] is True
        assert result["outcome"] == "yes"
        assert result["confidence"] > 0.7

    def test_inside_at_edge_still_locks_yes(self):
        """Temp at the very edge of the band (clearance=0) still locks YES."""
        from settlement_monitor import _check_between_settlement

        # Exactly at lower edge — outcome uncertain but still "inside"
        result = _check_between_settlement(69.5, lower_f=69.5, upper_f=71.5)
        assert result["locked"] is True
        assert result["outcome"] == "yes"
        assert result["confidence"] == pytest.approx(0.70, abs=0.01)

    def test_outside_with_sufficient_clearance_locks_no(self):
        """Temp >2°F below lower edge → locked=True, outcome=no."""
        from settlement_monitor import _check_between_settlement

        # clearance = 69.5 - 67.0 = 2.5 ≥ margin(1.0) + 1.0 = 2.0
        result = _check_between_settlement(67.0, lower_f=69.5, upper_f=71.5)
        assert result["locked"] is True
        assert result["outcome"] == "no"

    def test_outside_too_close_to_edge_not_locked(self):
        """Temp just outside lower edge (clearance < margin+1°F) → not locked."""
        from settlement_monitor import _check_between_settlement

        # clearance = 69.5 - 69.0 = 0.5 < 2.0 → uncertain
        result = _check_between_settlement(69.0, lower_f=69.5, upper_f=71.5)
        assert result["locked"] is False

    def test_above_band_with_clearance_locks_no(self):
        """Temp well above upper edge → locked=True, outcome=no."""
        from settlement_monitor import _check_between_settlement

        # clearance = 74.0 - 71.5 = 2.5 ≥ 2.0
        result = _check_between_settlement(74.0, lower_f=69.5, upper_f=71.5)
        assert result["locked"] is True
        assert result["outcome"] == "no"


class TestBTickerParsing:
    """B-ticker (between-bucket) detection in check_city_settlement."""

    def test_b_ticker_outside_near_edge_not_locked(self):
        """B-ticker market with temp just outside band (clearance < 2°F) → no signal."""
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

        with patch("metar.fetch_metar", return_value=fake_obs):
            signals = sm.check_city_settlement("NYC", [mock_market])

        assert signals == []

    def test_b_ticker_yes_signal_when_temp_inside(self):
        """B-ticker locked YES when temp is inside the band."""
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

        with patch("metar.fetch_metar", return_value=fake_obs):
            signals = sm.check_city_settlement("NYC", [mock_market])

        assert len(signals) == 1
        assert signals[0]["outcome"] == "yes"
        assert signals[0]["ticker"] == "KXHIGHNY-26MAY17-B70.5"

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
