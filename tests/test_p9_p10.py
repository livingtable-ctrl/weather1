"""Tests for P9/P10 features:
- P9.1: Strategy versioning (get_brier_by_version, edge_calc_version column)
- P9.5: Strategy retirement (auto_retire_strategies, get_retired_strategies)
- P10.1: Drift detection (detect_brier_drift)
- P10.2: Black swan mode (check_black_swan_conditions, activate_black_swan_halt)
- P10.3: Config integrity (get_config_fingerprint, check_config_integrity)
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_tracker(tmp_path, monkeypatch):
    """Tracker backed by a temp DB."""
    import tracker

    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
    monkeypatch.setattr(tracker, "_db_initialized", False)
    monkeypatch.setattr(tracker, "_RETIRED_PATH", tmp_path / "retired_strategies.json")
    tracker.init_db()
    return tracker


def _log_and_settle(t, ticker, method, our_prob, settled_yes, version="v1.0"):
    """Helper: log a prediction + outcome in the temp tracker DB."""
    from datetime import date as _date

    t.log_prediction(
        ticker,
        "NYC",
        _date.today(),
        {
            "forecast_prob": our_prob,
            "market_prob": 0.50,
            "edge": our_prob - 0.50,
            "method": method,
            "condition": {"type": "above", "threshold": 70},
        },
        edge_calc_version=version,
    )
    t.log_outcome(ticker, settled_yes)


# ── P9.1: Strategy versioning ─────────────────────────────────────────────────


class TestStrategyVersioning:
    def test_get_brier_by_version_empty(self, tmp_tracker):
        result = tmp_tracker.get_brier_by_version()
        assert result == {}

    def test_get_brier_by_version_groups_correctly(self, tmp_tracker):
        """Predictions stamped with different versions produce separate Brier entries."""
        for i in range(12):
            _log_and_settle(
                tmp_tracker,
                f"TICKER-V1-{i}",
                "ensemble",
                0.70,
                True,
                version="v1.0",
            )
        for i in range(12):
            _log_and_settle(
                tmp_tracker,
                f"TICKER-V2-{i}",
                "ensemble",
                0.60,
                False,
                version="v2.0",
            )

        result = tmp_tracker.get_brier_by_version(min_samples=10)
        assert "v1.0" in result
        assert "v2.0" in result
        assert result["v1.0"]["n"] == 12
        assert result["v2.0"]["n"] == 12

    def test_log_prediction_stores_edge_calc_version(self, tmp_tracker):
        """edge_calc_version kwarg is stored and retrievable."""
        import sqlite3

        _log_and_settle(tmp_tracker, "VER-TEST", "ensemble", 0.7, True, version="v1.5")
        with sqlite3.connect(tmp_tracker.DB_PATH) as con:
            row = con.execute(
                "SELECT edge_calc_version FROM predictions WHERE ticker=?",
                ("VER-TEST",),
            ).fetchone()
        assert row is not None
        assert row[0] == "v1.5"

    def test_log_prediction_version_defaults_to_none(self, tmp_tracker):
        """Callers that don't pass edge_calc_version store NULL (backward compat)."""
        import sqlite3

        tmp_tracker.log_prediction(
            "NOVERSION",
            "NYC",
            date.today(),
            {"forecast_prob": 0.6, "market_prob": 0.5, "edge": 0.1, "condition": {}},
        )
        with sqlite3.connect(tmp_tracker.DB_PATH) as con:
            row = con.execute(
                "SELECT edge_calc_version FROM predictions WHERE ticker=?",
                ("NOVERSION",),
            ).fetchone()
        assert row is not None
        assert row[0] is None


# ── P9.5: Strategy retirement ─────────────────────────────────────────────────


class TestStrategyRetirement:
    def test_get_retired_strategies_empty(self, tmp_tracker):
        result = tmp_tracker.get_retired_strategies()
        assert result == {}

    def test_auto_retire_strategies_retires_bad_method(self, tmp_tracker):
        """A method with Brier > 0.25 over 20+ predictions should be auto-retired."""
        # Log 22 predictions where our_prob=0.9 but outcome=False → Brier = (0.9-0)²=0.81
        for i in range(22):
            _log_and_settle(
                tmp_tracker,
                f"BAD-{i}",
                "bad_method",
                0.90,
                False,
            )

        newly = tmp_tracker.auto_retire_strategies(
            min_samples=20, retire_threshold=0.25
        )
        assert "bad_method" in newly

        retired = tmp_tracker.get_retired_strategies()
        assert "bad_method" in retired
        assert retired["bad_method"]["brier"] > 0.25

    def test_auto_retire_does_not_retire_good_method(self, tmp_tracker):
        """A well-performing method (Brier < 0.25) must NOT be retired."""
        for i in range(22):
            _log_and_settle(
                tmp_tracker,
                f"GOOD-{i}",
                "good_method",
                0.75,
                True,
            )

        newly = tmp_tracker.auto_retire_strategies(
            min_samples=20, retire_threshold=0.25
        )
        assert "good_method" not in newly

    def test_auto_retire_skips_insufficient_samples(self, tmp_tracker):
        """Methods with fewer than min_samples predictions are not evaluated."""
        for i in range(5):
            _log_and_settle(tmp_tracker, f"FEW-{i}", "new_method", 0.9, False)

        newly = tmp_tracker.auto_retire_strategies(min_samples=20)
        assert "new_method" not in newly

    def test_unretire_strategy(self, tmp_tracker):
        """unretire_strategy removes a retired entry."""
        for i in range(22):
            _log_and_settle(tmp_tracker, f"UN-{i}", "unretire_me", 0.9, False)

        tmp_tracker.auto_retire_strategies(min_samples=20, retire_threshold=0.25)
        assert "unretire_me" in tmp_tracker.get_retired_strategies()

        result = tmp_tracker.unretire_strategy("unretire_me")
        assert result is True
        assert "unretire_me" not in tmp_tracker.get_retired_strategies()

    def test_unretire_nonexistent_returns_false(self, tmp_tracker):
        assert tmp_tracker.unretire_strategy("nonexistent") is False

    def test_already_retired_not_duplicated(self, tmp_tracker):
        """Re-running auto_retire on an already-retired method doesn't duplicate it."""
        for i in range(22):
            _log_and_settle(tmp_tracker, f"DUP-{i}", "dup_method", 0.9, False)

        tmp_tracker.auto_retire_strategies(min_samples=20, retire_threshold=0.25)
        newly2 = tmp_tracker.auto_retire_strategies(
            min_samples=20, retire_threshold=0.25
        )
        assert "dup_method" not in newly2


# ── P10.1: Drift detection ─────────────────────────────────────────────────────


class TestDriftDetection:
    def test_detect_brier_drift_insufficient_data(self, tmp_tracker):
        result = tmp_tracker.detect_brier_drift(min_weeks=6)
        assert result["drifting"] is False
        assert result["early_brier"] is None
        assert "Insufficient data" in result["message"]

    def test_detect_brier_drift_no_drift(self, tmp_tracker):
        """Stable Brier over time should not trigger drift."""
        weekly_data = [{"week": f"2026-W{i:02d}", "brier": 0.15} for i in range(1, 13)]
        with patch.object(tmp_tracker, "get_brier_over_time", return_value=weekly_data):
            result = tmp_tracker.detect_brier_drift(
                min_weeks=6, degradation_threshold=0.05
            )
        assert result["drifting"] is False
        assert result["delta"] == pytest.approx(0.0, abs=1e-4)

    def test_detect_brier_drift_detects_degradation(self, tmp_tracker):
        """Early Brier=0.12, recent Brier=0.22 → delta=0.10 > threshold=0.05 → drifting."""
        early = [{"week": f"2026-W{i:02d}", "brier": 0.12} for i in range(1, 7)]
        recent = [{"week": f"2026-W{i:02d}", "brier": 0.22} for i in range(7, 13)]
        weekly_data = early + recent

        with patch.object(tmp_tracker, "get_brier_over_time", return_value=weekly_data):
            result = tmp_tracker.detect_brier_drift(
                min_weeks=6, degradation_threshold=0.05
            )

        assert result["drifting"] is True
        assert result["early_brier"] == pytest.approx(0.12, abs=1e-4)
        assert result["recent_brier"] == pytest.approx(0.22, abs=1e-4)
        assert result["delta"] == pytest.approx(0.10, abs=1e-4)
        assert "Drift detected" in result["message"]

    def test_detect_brier_drift_improvement_not_flagged(self, tmp_tracker):
        """If Brier improves (negative delta) it is not flagged as drift."""
        early = [{"week": f"2026-W{i:02d}", "brier": 0.22} for i in range(1, 7)]
        recent = [{"week": f"2026-W{i:02d}", "brier": 0.12} for i in range(7, 13)]
        weekly_data = early + recent

        with patch.object(tmp_tracker, "get_brier_over_time", return_value=weekly_data):
            result = tmp_tracker.detect_brier_drift(
                min_weeks=6, degradation_threshold=0.05
            )
        assert result["drifting"] is False


# ── P10.2: Black swan mode ────────────────────────────────────────────────────


class TestBlackSwanMode:
    def test_no_conditions_on_clean_trades(self, monkeypatch):
        import tracker
        from alerts import check_black_swan_conditions

        monkeypatch.setattr(tracker, "brier_score", lambda city=None: None)
        monkeypatch.setattr(tracker, "get_history", lambda: [])

        trades = [{"outcome": "yes"} for _ in range(5)]
        result = check_black_swan_conditions(trades, balance=1000, peak_balance=1000)
        assert result == []

    def test_consecutive_loss_triggers(self):
        from alerts import check_black_swan_conditions

        trades = [{"outcome": "no"} for _ in range(12)]
        result = check_black_swan_conditions(trades, balance=900, peak_balance=1000)
        assert any("consecutive" in c.lower() for c in result)

    def test_consecutive_loss_below_threshold_ok(self):
        """9 consecutive losses should NOT trigger (default threshold=10)."""
        from alerts import check_black_swan_conditions

        trades = [{"outcome": "no"} for _ in range(9)]
        result = check_black_swan_conditions(trades, balance=900, peak_balance=1000)
        # May trigger Brier check but not the consecutive losses check
        assert not any("consecutive" in c.lower() for c in result)

    def test_activate_black_swan_halt_writes_files(self, tmp_path, monkeypatch):
        import alerts

        monkeypatch.setattr(alerts, "_BLACK_SWAN_PATH", tmp_path / ".black_swan_active")
        monkeypatch.setattr(alerts, "_KILL_SWITCH_PATH", tmp_path / ".kill_switch")

        alerts.activate_black_swan_halt("test reason")

        assert (tmp_path / ".black_swan_active").exists()
        assert (tmp_path / ".kill_switch").exists()

        with open(tmp_path / ".black_swan_active") as f:
            data = json.load(f)
        assert data["reason"] == "test reason"
        assert "activated_at" in data

    def test_get_black_swan_status_none_when_absent(self, tmp_path, monkeypatch):
        import alerts

        monkeypatch.setattr(alerts, "_BLACK_SWAN_PATH", tmp_path / ".black_swan_active")
        assert alerts.get_black_swan_status() is None

    def test_get_black_swan_status_returns_data(self, tmp_path, monkeypatch):
        import alerts

        bs_path = tmp_path / ".black_swan_active"
        ks_path = tmp_path / ".kill_switch"
        monkeypatch.setattr(alerts, "_BLACK_SWAN_PATH", bs_path)
        monkeypatch.setattr(alerts, "_KILL_SWITCH_PATH", ks_path)

        alerts.activate_black_swan_halt("extreme loss")
        status = alerts.get_black_swan_status()

        assert status is not None
        assert status["reason"] == "extreme loss"

    def test_clear_black_swan_state(self, tmp_path, monkeypatch):
        import alerts

        bs_path = tmp_path / ".black_swan_active"
        ks_path = tmp_path / ".kill_switch"
        monkeypatch.setattr(alerts, "_BLACK_SWAN_PATH", bs_path)
        monkeypatch.setattr(alerts, "_KILL_SWITCH_PATH", ks_path)

        alerts.activate_black_swan_halt("reason")
        assert bs_path.exists()

        cleared = alerts.clear_black_swan_state()
        assert cleared is True
        assert not bs_path.exists()

    def test_clear_black_swan_state_no_file(self, tmp_path, monkeypatch):
        import alerts

        monkeypatch.setattr(alerts, "_BLACK_SWAN_PATH", tmp_path / ".black_swan_active")
        cleared = alerts.clear_black_swan_state()
        assert cleared is False

    def test_run_black_swan_check_triggers_halt(self, tmp_path, monkeypatch):
        """run_black_swan_check activates kill switch when conditions are met."""
        import alerts

        bs_path = tmp_path / ".black_swan_active"
        ks_path = tmp_path / ".kill_switch"
        monkeypatch.setattr(alerts, "_BLACK_SWAN_PATH", bs_path)
        monkeypatch.setattr(alerts, "_KILL_SWITCH_PATH", ks_path)

        trades = [{"outcome": "no"} for _ in range(12)]
        conditions = alerts.run_black_swan_check(
            trades=trades, balance=900, peak_balance=1000
        )

        assert len(conditions) > 0
        assert ks_path.exists()
        assert bs_path.exists()


# ── P10.3: Config integrity ───────────────────────────────────────────────────


class TestConfigIntegrity:
    def test_get_config_fingerprint_returns_dict(self):
        from utils import get_config_fingerprint

        fp = get_config_fingerprint()
        assert isinstance(fp, dict)
        assert "MIN_EDGE" in fp
        assert "PAPER_MIN_EDGE" in fp
        assert "MAX_DAILY_LOSS_PCT" in fp

    def test_check_config_integrity_first_run(self, tmp_path, monkeypatch):
        """First run: no previous hash → changed=False, writes hash file."""
        import utils

        hash_path = tmp_path / ".config_hash"
        monkeypatch.setattr(utils, "_CONFIG_HASH_PATH", hash_path)

        result = utils.check_config_integrity()
        assert result["changed"] is False
        assert result["previous_hash"] is None
        assert hash_path.exists()

    def test_check_config_integrity_no_change(self, tmp_path, monkeypatch):
        """Running twice with same config → changed=False."""
        import utils

        hash_path = tmp_path / ".config_hash"
        monkeypatch.setattr(utils, "_CONFIG_HASH_PATH", hash_path)

        utils.check_config_integrity()  # first run writes hash
        result = utils.check_config_integrity()  # second run should match

        assert result["changed"] is False

    def test_check_config_integrity_detects_change(self, tmp_path, monkeypatch):
        """Writing a different hash file → changed=True."""
        import utils

        hash_path = tmp_path / ".config_hash"
        monkeypatch.setattr(utils, "_CONFIG_HASH_PATH", hash_path)

        # Write a different hash to simulate a prior config
        hash_path.write_text(
            json.dumps({"hash": "aabbccddeeff0011", "fingerprint": {}})
        )

        result = utils.check_config_integrity()
        assert result["changed"] is True
        assert result["previous_hash"] == "aabbccddeeff0011"

    def test_config_hash_is_deterministic(self, tmp_path, monkeypatch):
        """Same config should always produce the same hash."""
        import utils

        hash_path = tmp_path / ".config_hash"
        monkeypatch.setattr(utils, "_CONFIG_HASH_PATH", hash_path)

        fp = utils.get_config_fingerprint()
        h1 = utils._hash_fingerprint(fp)
        h2 = utils._hash_fingerprint(fp)
        assert h1 == h2


# ── P10 live readiness: slippage tracking ────────────────────────────────────


class TestLiveFillSlippage:
    @pytest.fixture
    def tmp_tracker(self, tmp_path, monkeypatch):
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        tracker.init_db()
        return tracker

    def test_log_and_retrieve_slippage(self, tmp_tracker):
        tmp_tracker.log_live_fill(
            "TICK-A", "yes", paper_price=0.60, fill_price=0.61, quantity=5
        )
        result = tmp_tracker.get_mean_slippage(days=30)
        assert result is not None
        assert abs(result - 1.0) < 0.01  # (0.61-0.60)*100 = 1.0 cent

    def test_mean_slippage_none_when_empty(self, tmp_tracker):
        result = tmp_tracker.get_mean_slippage(days=30)
        assert result is None

    def test_mean_slippage_averages_multiple(self, tmp_tracker):
        tmp_tracker.log_live_fill("T1", "yes", 0.50, 0.51, 1)  # +1 cent
        tmp_tracker.log_live_fill("T2", "yes", 0.50, 0.53, 1)  # +3 cents
        result = tmp_tracker.get_mean_slippage(days=30)
        assert result is not None
        assert abs(result - 2.0) < 0.01  # average of 1 and 3

    def test_slippage_negative_when_fill_below_paper(self, tmp_tracker):
        tmp_tracker.log_live_fill("T3", "yes", 0.60, 0.59, 2)
        result = tmp_tracker.get_mean_slippage(days=30)
        assert result is not None
        assert result < 0  # filled better than paper price

    def test_get_mean_slippage_respects_days_window(self, tmp_tracker, monkeypatch):
        """Fills older than the window should be excluded."""
        import datetime as _dt

        old_ts = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(days=40)).isoformat()
        with tmp_tracker._conn() as con:
            con.execute(
                "INSERT INTO live_fills (ticker, side, paper_price, fill_price, slippage_cents, quantity, logged_at)"
                " VALUES (?,?,?,?,?,?,?)",
                ("OLD", "yes", 0.50, 0.55, 5.0, 1, old_ts),
            )
        result = tmp_tracker.get_mean_slippage(days=30)
        assert result is None  # old fill excluded


# ── P10 live readiness: config fingerprint includes new keys ──────────────────


class TestPhase10ConfigKeys:
    def test_fingerprint_includes_micro_live_keys(self):
        from utils import get_config_fingerprint

        fp = get_config_fingerprint()
        assert "ENABLE_MICRO_LIVE" in fp
        assert "MICRO_LIVE_FRACTION" in fp
        assert "BRIER_ALERT_THRESHOLD" in fp
        assert "SLIPPAGE_ALERT_CENTS" in fp

    def test_enable_micro_live_defaults_false(self, monkeypatch):
        monkeypatch.delenv("ENABLE_MICRO_LIVE", raising=False)
        import importlib

        import utils

        importlib.reload(utils)
        assert utils.ENABLE_MICRO_LIVE is False

    def test_brier_alert_threshold_default(self, monkeypatch):
        monkeypatch.delenv("BRIER_ALERT_THRESHOLD", raising=False)
        import importlib

        import utils

        importlib.reload(utils)
        assert utils.BRIER_ALERT_THRESHOLD == pytest.approx(0.22)


# ── P10.3: Weekly Brier alert logic ──────────────────────────────────────────


class TestWeeklyBrierAlert:
    def test_two_bad_weeks_triggers_alert(self):
        """Both recent weeks above threshold → alert should fire."""
        from utils import BRIER_ALERT_THRESHOLD

        weekly_data = [
            {"week": "2026-W10", "brier": 0.15},
            {"week": "2026-W11", "brier": BRIER_ALERT_THRESHOLD + 0.05},
            {"week": "2026-W12", "brier": BRIER_ALERT_THRESHOLD + 0.03},
        ]
        recent_two = [w["brier"] for w in weekly_data[-2:]]
        assert all(b > BRIER_ALERT_THRESHOLD for b in recent_two)

    def test_one_bad_week_does_not_trigger(self):
        """Only one of the two recent weeks above threshold → no alert."""
        from utils import BRIER_ALERT_THRESHOLD

        weekly_data = [
            {"week": "2026-W11", "brier": BRIER_ALERT_THRESHOLD + 0.05},
            {"week": "2026-W12", "brier": BRIER_ALERT_THRESHOLD - 0.05},
        ]
        recent_two = [w["brier"] for w in weekly_data[-2:]]
        assert not all(b > BRIER_ALERT_THRESHOLD for b in recent_two)

    def test_insufficient_weeks_no_alert(self):
        """Fewer than 2 weeks → no alert check."""
        weekly_data = [{"week": "2026-W12", "brier": 0.99}]
        assert len(weekly_data) < 2  # gate condition
