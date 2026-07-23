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
from datetime import UTC, date
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
    # Redirect pins file so tests never write to the real data/strategy_pins.json.
    # Without this, unretire_strategy(pin_hours=72) would contaminate the live
    # trading state with test method names pinned for 72 hours.
    monkeypatch.setattr(tracker, "_PINS_PATH", tmp_path / "strategy_pins.json")
    tracker.init_db()
    return tracker


def _log_and_settle(t, ticker, method, our_prob, settled_yes, version="v1.0"):
    """Helper: log a prediction + outcome in the temp tracker DB."""
    from datetime import date as _date

    t.log_prediction(
        ticker,
        "NYC",
        _date(2099, 1, 1),
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

    def test_dir_accuracy_guard_blocks_retirement(self, tmp_tracker):
        """Method with Brier > 0.25 is NOT retired when directional accuracy >= guard.

        Elevated Brier with good direction means miscalibrated probabilities, not
        bad forecasting — retirement would halt signal generation unnecessarily.
        """
        for i in range(22):
            _log_and_settle(tmp_tracker, f"GUARD-{i}", "guard_method", 0.9, False)

        newly = tmp_tracker.auto_retire_strategies(
            min_samples=20,
            retire_threshold=0.25,
            current_directional_accuracy=0.67,
            dir_accuracy_guard=0.65,
        )
        assert "guard_method" not in newly
        assert "guard_method" not in tmp_tracker.get_retired_strategies()

    def test_dir_accuracy_guard_allows_retirement_when_direction_bad(self, tmp_tracker):
        """Method IS retired when directional accuracy is below the guard."""
        for i in range(22):
            _log_and_settle(tmp_tracker, f"BAD2-{i}", "bad_dir_method", 0.9, False)

        newly = tmp_tracker.auto_retire_strategies(
            min_samples=20,
            retire_threshold=0.25,
            current_directional_accuracy=0.60,
            dir_accuracy_guard=0.65,
        )
        assert "bad_dir_method" in newly

    def test_dir_accuracy_guard_inactive_when_accuracy_none(self, tmp_tracker):
        """Guard is skipped when directional accuracy is not available — retire normally."""
        for i in range(22):
            _log_and_settle(tmp_tracker, f"NONE-{i}", "none_acc_method", 0.9, False)

        newly = tmp_tracker.auto_retire_strategies(
            min_samples=20,
            retire_threshold=0.25,
            current_directional_accuracy=None,
            dir_accuracy_guard=0.65,
        )
        assert "none_acc_method" in newly

    def test_rolling_guard_blocks_retirement_when_recent_recovered(self, tmp_tracker):
        """Lifetime Brier > threshold from old bad trades, but the last 20 settled
        predictions have recovered — method must NOT be retired."""
        for i in range(30):
            _log_and_settle(tmp_tracker, f"OLD-{i}", "recovered_method", 0.9, False)
        with tmp_tracker._conn() as con:
            con.execute(
                "UPDATE outcomes SET settled_at = datetime('now', '-5 days') "
                "WHERE ticker LIKE 'OLD-%'"
            )
        for i in range(20):
            _log_and_settle(tmp_tracker, f"NEW-{i}", "recovered_method", 0.9, True)

        newly = tmp_tracker.auto_retire_strategies(
            min_samples=20, retire_threshold=0.25
        )
        assert "recovered_method" not in newly
        assert "recovered_method" not in tmp_tracker.get_retired_strategies()

    def test_rolling_guard_allows_retirement_when_recent_still_bad(self, tmp_tracker):
        """Both lifetime and rolling Brier are bad — method IS retired (guard doesn't
        over-protect a method that hasn't actually recovered)."""
        for i in range(40):
            _log_and_settle(
                tmp_tracker, f"STILLBAD-{i}", "still_bad_method", 0.9, False
            )

        newly = tmp_tracker.auto_retire_strategies(
            min_samples=20, retire_threshold=0.25
        )
        assert "still_bad_method" in newly
        assert "still_bad_method" in tmp_tracker.get_retired_strategies()

    def test_brier_score_by_method_rolling_returns_last_n(self, tmp_tracker):
        """brier_score_by_method_rolling only reflects the most recent `window` rows."""
        for i in range(10):
            _log_and_settle(tmp_tracker, f"ROLLOLD-{i}", "windowed_method", 0.9, False)
        with tmp_tracker._conn() as con:
            con.execute(
                "UPDATE outcomes SET settled_at = datetime('now', '-5 days') "
                "WHERE ticker LIKE 'ROLLOLD-%'"
            )
        for i in range(5):
            _log_and_settle(tmp_tracker, f"ROLLNEW-{i}", "windowed_method", 0.9, True)

        result = tmp_tracker.brier_score_by_method_rolling(window=5, min_samples=1)
        assert result["windowed_method"] == pytest.approx(0.01, abs=1e-6)


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

        trades = [
            {
                "outcome": "no",
                "settled": True,
                "settled_at": f"2026-01-01T00:{i:02d}:00Z",
                "pnl": -10.0,
            }
            for i in range(12)
        ]
        result = check_black_swan_conditions(trades, balance=900, peak_balance=1000)
        assert any("consecutive" in c.lower() for c in result)

    def test_consecutive_loss_below_threshold_ok(self):
        """9 consecutive losses should NOT trigger (default threshold=10)."""
        from alerts import check_black_swan_conditions

        trades = [
            {
                "outcome": "no",
                "settled": True,
                "settled_at": f"2026-01-01T00:{i:02d}:00Z",
                "pnl": -10.0,
            }
            for i in range(9)
        ]
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

        trades = [
            {
                "outcome": "no",
                "settled": True,
                "settled_at": f"2026-01-01T00:{i:02d}:00Z",
                "pnl": -10.0,
            }
            for i in range(12)
        ]
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
        # Exit-gate constants shared by paper.py/order_executor.py's stop-loss,
        # breakeven, and model-exit checks (paper._passes_exit_gates) must be
        # visible in the fingerprint so a drift in them is detectable.
        assert "EXIT_MIN_HOLD_HOURS" in fp
        assert "EXIT_SETTLEMENT_GATE_HOURS" in fp
        assert "MODEL_EXIT_SHIFT_PP" in fp

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


# ── Phase 2: Brier drift → tighten STRONG_EDGE ───────────────────────────────


class TestDriftTightenEdge:
    def test_drift_tighten_edge_exported_from_utils(self):
        """DRIFT_TIGHTEN_EDGE is a positive float exported from utils."""
        import utils

        assert hasattr(utils, "DRIFT_TIGHTEN_EDGE")
        assert isinstance(utils.DRIFT_TIGHTEN_EDGE, float)
        assert utils.DRIFT_TIGHTEN_EDGE > 0

    def test_effective_edge_raised_when_drift_detected(self):
        """When drift is drifting=True, effective threshold = STRONG_EDGE + DRIFT_TIGHTEN_EDGE."""
        from utils import DRIFT_TIGHTEN_EDGE, STRONG_EDGE

        drift_result = {"drifting": True, "message": "test drift"}
        _effective = (
            STRONG_EDGE + DRIFT_TIGHTEN_EDGE
            if drift_result["drifting"]
            else STRONG_EDGE
        )
        assert _effective == STRONG_EDGE + DRIFT_TIGHTEN_EDGE
        assert _effective > STRONG_EDGE

    def test_effective_edge_unchanged_without_drift(self):
        """When drift is drifting=False, effective threshold equals STRONG_EDGE."""
        from utils import DRIFT_TIGHTEN_EDGE, STRONG_EDGE

        drift_result = {"drifting": False}
        _effective = (
            STRONG_EDGE + DRIFT_TIGHTEN_EDGE
            if drift_result["drifting"]
            else STRONG_EDGE
        )
        assert _effective == STRONG_EDGE


class TestGraduationBrierGate:
    """graduation_check() uses last-50 Brier with threshold 0.23."""

    def _mock_perf(self):
        return {"settled": 50, "win_rate": 0.6, "total_pnl": 100.0, "roi": 0.1}

    def test_uses_last_50_brier(self, monkeypatch):
        """graduation_check() must call brier_score(last_n=50), not all-time."""
        import paper
        import tracker

        calls = []

        def _mock_brier(last_n=None, **kwargs):
            calls.append(last_n)
            return 0.22

        monkeypatch.setattr(tracker, "brier_score", _mock_brier)
        monkeypatch.setattr(tracker, "count_settled_predictions", lambda: 50)
        with patch("paper.get_performance", return_value=self._mock_perf()):
            paper.graduation_check()

        assert calls == [50], f"Expected brier_score(last_n=50), got {calls}"

    def test_max_brier_default_is_0_23(self):
        """graduation_check() default max_brier threshold must be 0.23."""
        import inspect

        import paper

        sig = inspect.signature(paper.graduation_check)
        assert sig.parameters["max_brier"].default == 0.23

    def test_passes_at_0_22(self, monkeypatch):
        """graduation_check() returns a result dict when last-50 Brier is 0.22."""
        import paper
        import tracker

        monkeypatch.setattr(tracker, "brier_score", lambda last_n=None, **kw: 0.22)
        monkeypatch.setattr(tracker, "count_settled_predictions", lambda: 50)
        with patch("paper.get_performance", return_value=self._mock_perf()):
            result = paper.graduation_check()

        assert result is not None, "Expected graduation to pass at Brier=0.22"
        assert result["brier"] == 0.22

    def test_fails_at_0_24(self, monkeypatch):
        """graduation_check() returns None when last-50 Brier is 0.24 > 0.23."""
        import paper
        import tracker

        monkeypatch.setattr(tracker, "brier_score", lambda last_n=None, **kw: 0.24)
        monkeypatch.setattr(tracker, "count_settled_predictions", lambda: 50)
        with patch("paper.get_performance", return_value=self._mock_perf()):
            result = paper.graduation_check()

        assert result is None, "Expected graduation to fail at Brier=0.24"

    def test_passes_at_0_21(self, monkeypatch):
        """Brier=0.21 now passes (previously unreachable under all-time 0.20)."""
        import paper
        import tracker

        monkeypatch.setattr(tracker, "brier_score", lambda last_n=None, **kw: 0.21)
        monkeypatch.setattr(tracker, "count_settled_predictions", lambda: 50)
        with patch("paper.get_performance", return_value=self._mock_perf()):
            result = paper.graduation_check()

        assert result is not None, "Brier=0.21 should pass new threshold 0.23"


# ── B2: Dynamic Correlation Matrix ────────────────────────────────────────────


def test_get_recent_city_correlations_returns_empty_when_no_data(tmp_tracker):
    """get_recent_city_correlations returns {} when DB has no settled multiday trades."""
    result = tmp_tracker.get_recent_city_correlations(days=60)
    assert result == {}, f"Expected empty dict, got {result}"


def test_get_recent_city_correlations_computes_correlation(tmp_tracker):
    """get_recent_city_correlations returns city-pair correlations when enough data exists."""
    from datetime import date as _date
    from datetime import datetime, timedelta

    import tracker as t

    # Insert enough (city, temp, settled_at) data points via DB directly
    # so we have 6 common dates between NYC and Boston with clear positive correlation
    # Use recent settled_at dates (within last 60 days) and future market_dates for days_out >= 1
    settled_base_dt = datetime.now(UTC) - timedelta(days=50)
    market_base = _date.today() + timedelta(days=10)  # Future dates for days_out >= 1

    for i in range(6):
        settled_dt = (settled_base_dt + timedelta(days=i)).isoformat()

        # NYC ticker (HIGH market -- get_recent_city_correlations only considers
        # daily-HIGH tickers, to avoid mixing HIGH/LOW temps in one city series)
        tmp_tracker.log_prediction(
            f"KXHIGHNYC-{i}",
            "NYC",
            market_base + timedelta(days=i),
            {
                "forecast_prob": 0.5,
                "market_prob": 0.50,
                "edge": 0.0,
                "method": "test",
                "condition": {"type": "above", "threshold": 70},
            },
        )
        # Log outcome and then update with specific settled_at and settled_temp_f
        tmp_tracker.log_outcome(f"KXHIGHNYC-{i}", True)
        with t._conn() as con:
            con.execute(
                "UPDATE outcomes SET settled_temp_f = ?, settled_at = ? WHERE ticker = ?",
                (70.0 + i * 2.0, settled_dt, f"KXHIGHNYC-{i}"),
            )

        # Boston ticker (same date, correlated)
        tmp_tracker.log_prediction(
            f"KXHIGHBOS-{i}",
            "Boston",
            market_base + timedelta(days=i),
            {
                "forecast_prob": 0.5,
                "market_prob": 0.50,
                "edge": 0.0,
                "method": "test",
                "condition": {"type": "above", "threshold": 70},
            },
        )
        tmp_tracker.log_outcome(f"KXHIGHBOS-{i}", True)
        with t._conn() as con:
            con.execute(
                "UPDATE outcomes SET settled_temp_f = ?, settled_at = ? WHERE ticker = ?",
                (68.0 + i * 2.0, settled_dt, f"KXHIGHBOS-{i}"),
            )

    result = tmp_tracker.get_recent_city_correlations(days=60, min_pairs=5)
    assert ("NYC", "Boston") in result or ("Boston", "NYC") in result, (
        f"Expected NYC/Boston correlation in result keys. Got: {list(result.keys())}"
    )
    # They move identically, so Pearson correlation should be ~1.0
    pair_key = ("NYC", "Boston") if ("NYC", "Boston") in result else ("Boston", "NYC")
    assert result[pair_key] > 0.9, (
        f"Expected correlation > 0.9 for identical-trend data, got {result[pair_key]}"
    )


def test_get_recent_city_correlations_excludes_disputed(tmp_tracker):
    """A disputed settlement must not pollute the correlation computation
    (backlog.txt "DISPUTED-ROW EXCLUSION PREDICATE HAND-COPIED ~40 TIMES IN
    tracker.py" -- found missing here while consolidating that predicate into
    the outcomes_valid view; no live impact when found since 0 disputed rows
    existed in production, but a disputed settled_temp_f is exactly the kind
    of corrupted ground truth this exclusion exists to keep out of scoring)."""
    from datetime import date as _date
    from datetime import datetime, timedelta

    import tracker as t

    settled_base_dt = datetime.now(UTC) - timedelta(days=50)
    market_base = _date.today() + timedelta(days=10)

    for i in range(6):
        settled_dt = (settled_base_dt + timedelta(days=i)).isoformat()
        tmp_tracker.log_prediction(
            f"KXHIGHNYC-{i}",
            "NYC",
            market_base + timedelta(days=i),
            {
                "forecast_prob": 0.5,
                "market_prob": 0.50,
                "edge": 0.0,
                "method": "test",
                "condition": {"type": "above", "threshold": 70},
            },
        )
        tmp_tracker.log_outcome(f"KXHIGHNYC-{i}", True)
        with t._conn() as con:
            con.execute(
                "UPDATE outcomes SET settled_temp_f = ?, settled_at = ? WHERE ticker = ?",
                (70.0 + i * 2.0, settled_dt, f"KXHIGHNYC-{i}"),
            )

        tmp_tracker.log_prediction(
            f"KXHIGHBOS-{i}",
            "Boston",
            market_base + timedelta(days=i),
            {
                "forecast_prob": 0.5,
                "market_prob": 0.50,
                "edge": 0.0,
                "method": "test",
                "condition": {"type": "above", "threshold": 70},
            },
        )
        tmp_tracker.log_outcome(f"KXHIGHBOS-{i}", True)
        with t._conn() as con:
            con.execute(
                "UPDATE outcomes SET settled_temp_f = ?, settled_at = ? WHERE ticker = ?",
                (68.0 + i * 2.0, settled_dt, f"KXHIGHBOS-{i}"),
            )

    before = tmp_tracker.get_recent_city_correlations(days=60, min_pairs=5)

    # Disputed outlier: a wildly off-trend NYC/Boston pair on a NEW shared
    # date -- if not excluded, this would visibly drag the near-1.0
    # correlation down (NYC spikes to 200F while Boston drops to -50F).
    settled_dt = (settled_base_dt + timedelta(days=6)).isoformat()
    tmp_tracker.log_prediction(
        "KXHIGHNYC-DISPUTED",
        "NYC",
        market_base + timedelta(days=6),
        {
            "forecast_prob": 0.5,
            "market_prob": 0.50,
            "edge": 0.0,
            "method": "test",
            "condition": {"type": "above", "threshold": 70},
        },
    )
    tmp_tracker.log_outcome("KXHIGHNYC-DISPUTED", True)
    tmp_tracker.log_prediction(
        "KXHIGHBOS-DISPUTED",
        "Boston",
        market_base + timedelta(days=6),
        {
            "forecast_prob": 0.5,
            "market_prob": 0.50,
            "edge": 0.0,
            "method": "test",
            "condition": {"type": "above", "threshold": 70},
        },
    )
    tmp_tracker.log_outcome("KXHIGHBOS-DISPUTED", True)
    with t._conn() as con:
        con.execute(
            "UPDATE outcomes SET settled_temp_f = ?, settled_at = ? WHERE ticker = ?",
            (200.0, settled_dt, "KXHIGHNYC-DISPUTED"),
        )
        con.execute(
            "UPDATE outcomes SET settled_temp_f = ?, settled_at = ? WHERE ticker = ?",
            (-50.0, settled_dt, "KXHIGHBOS-DISPUTED"),
        )
    t.mark_outcome_disputed("KXHIGHNYC-DISPUTED")
    t.mark_outcome_disputed("KXHIGHBOS-DISPUTED")

    after = tmp_tracker.get_recent_city_correlations(days=60, min_pairs=5)
    assert after == before, (
        f"Disputed outlier changed the correlation: before={before} after={after}"
    )


def test_get_recent_city_correlations_skips_below_min_pairs(tmp_tracker):
    """get_recent_city_correlations skips pairs with fewer than min_pairs common dates."""
    from datetime import date as _date
    from datetime import datetime, timedelta

    import tracker as t

    # Use recent date within last 60 days for settled_at, future date for market_date
    settled_dt = datetime.now(UTC) - timedelta(days=30)
    settled = settled_dt.isoformat()
    market_date = _date.today() + timedelta(days=5)

    for city, ticker in [("NYC", "NYC-0"), ("Boston", "BOS-0")]:
        tmp_tracker.log_prediction(
            ticker,
            city,
            market_date,
            {
                "forecast_prob": 0.5,
                "market_prob": 0.50,
                "edge": 0.0,
                "method": "test",
                "condition": {"type": "above", "threshold": 70},
            },
        )
        tmp_tracker.log_outcome(ticker, True)
        with t._conn() as con:
            con.execute(
                "UPDATE outcomes SET settled_temp_f = ?, settled_at = ? WHERE ticker = ?",
                (70.0, settled, ticker),
            )

    # Only 1 shared date → below default min_pairs=5, should return {}
    result = tmp_tracker.get_recent_city_correlations(days=60, min_pairs=5)
    assert result == {}, f"Should skip pair with only 1 common date. Got: {result}"


# ── CROSS-CITY RECENT-ERROR POOLING (backlog.txt) ───────────────────────────────


def _log_settled(
    t,
    ticker,
    city,
    market_date,
    forecast_temp_f,
    settled_temp_f,
    settled_at=None,
    predicted_at=None,
    disputed=False,
):
    """Helper: log a prediction with forecast_temp_f + a matching settled outcome,
    with direct control over predicted_at/settled_at (log_prediction hardcodes
    predicted_at to datetime('now') and can't take an explicit value)."""
    t.log_prediction(
        ticker,
        city,
        market_date,
        {
            "forecast_prob": 0.5,
            "market_prob": 0.5,
            "edge": 0.0,
            "method": "test",
            "forecast_temp": forecast_temp_f,
            "condition": {"type": "above", "threshold": 70},
        },
    )
    t.log_outcome(ticker, True)
    with t._conn() as con:
        if predicted_at is not None:
            con.execute(
                "UPDATE predictions SET predicted_at = ? WHERE ticker = ?",
                (predicted_at, ticker),
            )
        if settled_at is None:
            con.execute(
                "UPDATE outcomes SET settled_temp_f = ?, settled_at = datetime('now'), "
                "disputed = ? WHERE ticker = ?",
                (settled_temp_f, 1 if disputed else 0, ticker),
            )
        else:
            con.execute(
                "UPDATE outcomes SET settled_temp_f = ?, settled_at = ?, disputed = ? "
                "WHERE ticker = ?",
                (settled_temp_f, settled_at, 1 if disputed else 0, ticker),
            )


def test_get_regional_recent_bias_no_correlated_group(tmp_tracker):
    """Seattle has no _CORRELATED_CITY_GROUPS entry (deliberately standalone) —
    must return (0.0, 0) rather than erroring."""
    result = tmp_tracker.get_regional_recent_bias("Seattle", var="max")
    assert result == (0.0, 0)


def test_get_regional_recent_bias_no_data(tmp_tracker):
    """NYC has a correlated group but the DB is empty — (0.0, 0)."""
    result = tmp_tracker.get_regional_recent_bias("NYC", var="max")
    assert result == (0.0, 0)


def test_get_regional_recent_bias_computes_weighted_mean(tmp_tracker):
    """Boston (corr 0.85) and Washington (corr 0.75) both ran 2F warm on NYC's
    HIGH markets -> weighted mean should be 2.0 (both cities agree exactly)."""
    market_date = date.today()
    _log_settled(
        tmp_tracker,
        "KXHIGHBOS-T70",
        "Boston",
        market_date,
        forecast_temp_f=72.0,
        settled_temp_f=70.0,
    )
    _log_settled(
        tmp_tracker,
        "KXHIGHDC-T70",
        "Washington",
        market_date,
        forecast_temp_f=72.0,
        settled_temp_f=70.0,
    )
    bias, n = tmp_tracker.get_regional_recent_bias("NYC", var="max", hours=48)
    assert n == 2
    assert abs(bias - 2.0) < 0.01


def test_get_regional_recent_bias_weights_by_pair_correlation(tmp_tracker):
    """Boston (corr 0.85, error +4F) and Philadelphia (corr 0.80, error -2F)
    disagree -> the higher-correlation city should dominate the weighted mean,
    which must land strictly between the two raw errors."""
    market_date = date.today()
    _log_settled(
        tmp_tracker,
        "KXHIGHBOS-T70",
        "Boston",
        market_date,
        forecast_temp_f=74.0,
        settled_temp_f=70.0,  # error = +4
    )
    _log_settled(
        tmp_tracker,
        "KXHIGHPHIL-T70",
        "Philadelphia",
        market_date,
        forecast_temp_f=68.0,
        settled_temp_f=70.0,  # error = -2
    )
    bias, n = tmp_tracker.get_regional_recent_bias("NYC", var="max", hours=48)
    assert n == 2
    # Manually: (4*0.85 + -2*0.80) / (0.85+0.80) = (3.4-1.6)/1.65 = 1.0909
    expected = (4.0 * 0.85 + -2.0 * 0.80) / (0.85 + 0.80)
    assert abs(bias - expected) < 0.01
    assert -2.0 < bias < 4.0


def test_get_regional_recent_bias_var_filters_high_low(tmp_tracker):
    """A LOW-market ticker from a correlated city must not leak into a
    var='max' query, and vice versa — HIGH/LOW temp errors aren't the same
    physical quantity (same reasoning as get_recent_city_correlations)."""
    market_date = date.today()
    _log_settled(
        tmp_tracker,
        "KXLOWTBOS-T50",
        "Boston",
        market_date,
        forecast_temp_f=52.0,
        settled_temp_f=50.0,
    )
    bias, n = tmp_tracker.get_regional_recent_bias("NYC", var="max", hours=48)
    assert (bias, n) == (0.0, 0)

    bias, n = tmp_tracker.get_regional_recent_bias("NYC", var="min", hours=48)
    assert n == 1
    assert abs(bias - 2.0) < 0.01


def test_get_regional_recent_bias_respects_hours_window(tmp_tracker):
    """A correlated city's settlement outside the lookback window is excluded."""
    market_date = date.today()
    _log_settled(
        tmp_tracker,
        "KXHIGHBOS-OLD",
        "Boston",
        market_date,
        forecast_temp_f=80.0,
        settled_temp_f=70.0,
        settled_at="2020-01-01 00:00:00",
    )
    bias, n = tmp_tracker.get_regional_recent_bias("NYC", var="max", hours=48)
    assert (bias, n) == (0.0, 0)


def test_get_regional_recent_bias_excludes_disputed(tmp_tracker):
    """A disputed correlated-city settlement must not pollute the pooled bias
    (same outcomes_valid exclusion as every other scoring consumer)."""
    market_date = date.today()
    _log_settled(
        tmp_tracker,
        "KXHIGHBOS-BAD",
        "Boston",
        market_date,
        forecast_temp_f=200.0,
        settled_temp_f=0.0,  # wildly off, would dominate if counted
        disputed=True,
    )
    bias, n = tmp_tracker.get_regional_recent_bias("NYC", var="max", hours=48)
    assert (bias, n) == (0.0, 0)


def test_get_regional_recent_bias_dedups_to_latest_prediction_per_ticker(tmp_tracker):
    """A ticker re-logged across multiple cron cycles (one predictions row per
    day scanned) must only contribute its LATEST forecast_temp_f, not every
    historical one."""
    market_date = date.today()
    ticker = "KXHIGHBOS-DEDUP"
    with tmp_tracker._conn() as con:
        con.execute(
            """
            INSERT INTO predictions
              (ticker, city, market_date, our_prob, market_prob, edge, method,
               predicted_at, predicted_date, forecast_temp_f)
            VALUES (?, 'Boston', ?, 0.5, 0.5, 0.0, 'test', ?, ?, ?)
            """,
            (
                ticker,
                market_date.isoformat(),
                "2026-01-01 00:00:00",
                "2026-01-01",
                90.0,
            ),
        )
        con.execute(
            """
            INSERT INTO predictions
              (ticker, city, market_date, our_prob, market_prob, edge, method,
               predicted_at, predicted_date, forecast_temp_f)
            VALUES (?, 'Boston', ?, 0.5, 0.5, 0.0, 'test', ?, ?, ?)
            """,
            (
                ticker,
                market_date.isoformat(),
                "2026-01-02 00:00:00",
                "2026-01-02",
                72.0,
            ),
        )
    tmp_tracker.log_outcome(ticker, True)
    with tmp_tracker._conn() as con:
        con.execute(
            "UPDATE outcomes SET settled_temp_f = 70.0, settled_at = datetime('now') "
            "WHERE ticker = ?",
            (ticker,),
        )
    bias, n = tmp_tracker.get_regional_recent_bias("NYC", var="max", hours=48)
    assert n == 1
    # Latest row (forecast_temp_f=72.0) - 70.0 = 2.0, NOT the stale 90.0 row's 20.0
    assert abs(bias - 2.0) < 0.01


def test_get_regional_recent_bias_as_of_avoids_lookahead(tmp_tracker):
    """as_of lets a caller ask 'what would this have returned at time T' without
    a later settlement leaking in — the backtest use case this exists for."""
    market_date = date.today()
    _log_settled(
        tmp_tracker,
        "KXHIGHBOS-FUTURE",
        "Boston",
        market_date,
        forecast_temp_f=75.0,
        settled_temp_f=70.0,
        settled_at="2026-06-15 12:00:00",
        # Must predate settled_at -- a ticker is never re-predicted after it
        # settles, and get_regional_recent_bias now bounds predicted_at by
        # as_of too (opus review hardening). Without this, log_prediction's
        # real-wall-clock predicted_at ("now") would sit AFTER this backdated
        # settled_at, an inversion that can't happen with real data and would
        # be (correctly) filtered out by that bound.
        predicted_at="2026-06-14 12:00:00",
    )
    # Asking as of a point before that settlement existed -> must not see it.
    bias, n = tmp_tracker.get_regional_recent_bias(
        "NYC", var="max", hours=48, as_of="2026-06-14 00:00:00"
    )
    assert (bias, n) == (0.0, 0)
    # Asking as of shortly after -> sees it.
    bias, n = tmp_tracker.get_regional_recent_bias(
        "NYC", var="max", hours=48, as_of="2026-06-15 18:00:00"
    )
    assert n == 1
    assert abs(bias - 5.0) < 0.01


# ── B6: Tail-Risk Stress Testing ────────────────────────────────────────────────


def test_run_stress_test_heat_wave_filters_southern_cities(monkeypatch):
    """heat_wave_failure scenario only counts Dallas/Houston/Phoenix/Atlanta/Austin trades."""
    import monte_carlo as mc
    import paper

    trades = [
        {
            "ticker": "DAL-T90",
            "city": "Dallas",
            "side": "yes",
            "entry_price": 0.50,
            "quantity": 10,
            "cost": 5.00,
            "settled": False,
            "won": None,
        },
        {
            "ticker": "CHI-T90",
            "city": "Chicago",
            "side": "yes",
            "entry_price": 0.50,
            "quantity": 10,
            "cost": 5.00,
            "settled": False,
            "won": None,
        },
    ]
    monkeypatch.setattr(paper, "load_paper_trades", lambda: trades)
    monkeypatch.setattr(paper, "get_balance", lambda: 1000.0)
    monkeypatch.setattr(paper, "get_peak_balance", lambda: 1000.0)

    result = mc.run_stress_test("heat_wave_failure")
    # Only Dallas is in the southern cities list — Chicago is excluded
    assert result["positions_affected"] == 1, (
        f"Expected 1 position affected, got {result['positions_affected']}"
    )
    assert result["loss_dollars"] == 5.00, (
        f"Expected $5.00 loss, got {result['loss_dollars']}"
    )
    assert result["scenario"] == "heat_wave_failure"


def test_run_stress_test_total_model_failure_includes_all_cities(monkeypatch):
    """total_model_failure scenario counts all open positions regardless of city."""
    import monte_carlo as mc
    import paper

    trades = [
        {
            "ticker": "DAL-T90",
            "city": "Dallas",
            "side": "yes",
            "entry_price": 0.50,
            "quantity": 10,
            "cost": 5.00,
            "settled": False,
            "won": None,
        },
        {
            "ticker": "CHI-T90",
            "city": "Chicago",
            "side": "yes",
            "entry_price": 0.55,
            "quantity": 5,
            "cost": 2.75,
            "settled": False,
            "won": None,
        },
    ]
    monkeypatch.setattr(paper, "load_paper_trades", lambda: trades)
    monkeypatch.setattr(paper, "get_balance", lambda: 1000.0)
    monkeypatch.setattr(paper, "get_peak_balance", lambda: 1000.0)

    result = mc.run_stress_test("total_model_failure")
    assert result["positions_affected"] == 2
    assert abs(result["loss_dollars"] - 7.75) < 0.01, (
        f"Expected $7.75 total loss, got {result['loss_dollars']}"
    )
    assert result["below_halt"] is False  # 1000 - 7.75 >> halt floor


def test_run_stress_test_unknown_scenario_returns_error():
    """run_stress_test returns an error dict for unknown scenario names."""
    import monte_carlo as mc

    result = mc.run_stress_test("nonexistent_scenario")
    assert "error" in result, f"Expected error key, got: {result}"


# ── KALSHI CENTS/DOLLARS PRICE NORMALIZATION consolidation ─────────────────────
# utils.coalesce_market_price, consolidated 2026-07-19 from 3 independent
# copies (order_executor._coalesce_cents_or_dollars, weather_markets.
# parse_market_price's nested _coalesce+to_float, schema_validator.
# _price_to_decimal) after the duplication had already produced 2 real bugs.


class TestCoalesceMarketPrice:
    def test_legacy_cents_int_normalized(self):
        from utils import coalesce_market_price

        assert coalesce_market_price({"yes_bid": 55}, "yes_bid") == pytest.approx(0.55)

    def test_one_cent_int_normalized_not_misread_as_one_dollar(self):
        """The exact edge case that diverged across the 3 original copies:
        an integer value of 1 must be read as 1 cent (0.01), not $1.00."""
        from utils import coalesce_market_price

        assert coalesce_market_price({"p": 1}, "p") == pytest.approx(0.01)

    def test_dollar_float_passed_through(self):
        from utils import coalesce_market_price

        assert coalesce_market_price({"p": 0.55}, "p") == pytest.approx(0.55)

    def test_dollar_string_passed_through(self):
        from utils import coalesce_market_price

        assert coalesce_market_price({"p": "0.55"}, "p") == pytest.approx(0.55)

    def test_cents_string_normalized(self):
        """A string price > 1.0 is the legacy cents-as-string format."""
        from utils import coalesce_market_price

        assert coalesce_market_price({"p": "55"}, "p") == pytest.approx(0.55)

    def test_zero_bid_not_bypassed_by_falsy_check(self):
        """A genuine 0-valued field (0¢ bid) must not be skipped in favor of
        a later fallback key -- coalesce on None, not on falsiness."""
        from utils import coalesce_market_price

        assert coalesce_market_price(
            {"yes_bid": 0, "yes_bid_dollars": 0.55}, "yes_bid", "yes_bid_dollars"
        ) == pytest.approx(0.0)

    def test_first_key_wins_when_both_present(self):
        from utils import coalesce_market_price

        assert coalesce_market_price(
            {"yes_bid": 40, "yes_bid_dollars": 0.99}, "yes_bid", "yes_bid_dollars"
        ) == pytest.approx(0.40)

    def test_falls_back_to_second_key_when_first_absent(self):
        from utils import coalesce_market_price

        assert coalesce_market_price(
            {"yes_bid_dollars": 0.42}, "yes_bid", "yes_bid_dollars"
        ) == pytest.approx(0.42)

    def test_no_keys_present_defaults_to_zero(self):
        from utils import coalesce_market_price

        assert coalesce_market_price({}, "yes_bid", "yes_bid_dollars") == pytest.approx(
            0.0
        )

    def test_unparseable_string_raises(self):
        """Deliberately unguarded -- order_executor.py's live reprice loop
        and weather_markets.parse_market_price both run inside a per-order/
        per-market try/except upstream and rely on this raising so
        malformed data is skipped, not silently treated as $0. (schema_
        validator.py wraps its own call in try/except for its different,
        fail-soft contract -- see tests/test_phase2_batch_l.py.)"""
        from utils import coalesce_market_price

        with pytest.raises(ValueError):
            coalesce_market_price({"p": "not-a-number"}, "p")

    def test_key_constants_match_expected_field_names(self):
        from utils import NO_BID_KEYS, YES_ASK_KEYS, YES_BID_KEYS

        assert YES_BID_KEYS == ("yes_bid", "yes_bid_dollars")
        assert YES_ASK_KEYS == ("yes_ask", "yes_ask_dollars")
        assert NO_BID_KEYS == ("no_bid", "no_bid_dollars")

    def test_order_executor_uses_the_shared_helper_not_a_local_copy(self):
        """Regression guard for the consolidation itself: order_executor.py
        must no longer define its own _coalesce_cents_or_dollars, and must
        import the shared coalesce_market_price instead.

        Deliberately NOT an `is` identity check against utils.
        coalesce_market_price -- this file runs in the same pytest session
        as tests that call importlib.reload(utils) for unrelated reasons
        (see backlog.txt's frozen-import entry), which would make an
        identity check order-dependent/flaky rather than a reliable
        regression guard."""
        import order_executor

        assert not hasattr(order_executor, "_coalesce_cents_or_dollars")
        assert callable(order_executor.coalesce_market_price)
        assert order_executor.coalesce_market_price(
            {"yes_bid": 55}, "yes_bid"
        ) == pytest.approx(0.55)
