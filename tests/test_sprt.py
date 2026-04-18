"""
Tests for SPRT model degradation detection in tracker.py and paper.py.
"""

from __future__ import annotations

from unittest.mock import patch


class TestSprtModelHealth:
    """Tests for tracker.sprt_model_health()."""

    def test_sprt_insufficient_data(self, monkeypatch):
        """Returns insufficient_data when fewer than SPRT_MIN_TRADES records exist."""
        import tracker
        import utils

        monkeypatch.setattr(utils, "SPRT_MIN_TRADES", 5)

        with patch.object(tracker, "_get_recent_win_loss", return_value=(2, 3)):
            result = tracker.sprt_model_health(min_trades=5)

        assert result["status"] == "insufficient_data"
        assert result["n"] == 3

    def test_sprt_ok_on_good_win_rate(self, monkeypatch):
        """Returns 'ok' when win rate is healthy (35/50 = 70%)."""
        import tracker

        with patch.object(tracker, "_get_recent_win_loss", return_value=(35, 50)):
            result = tracker.sprt_model_health(
                p0=0.55, p1=0.35, alpha=0.05, beta=0.20, min_trades=5
            )

        assert result["status"] == "ok"
        assert result["n"] == 50

    def test_sprt_degraded_on_bad_win_rate(self, monkeypatch):
        """Returns 'degraded' when win rate is very low (10/50 = 20%)."""
        import tracker

        with patch.object(tracker, "_get_recent_win_loss", return_value=(10, 50)):
            result = tracker.sprt_model_health(
                p0=0.55, p1=0.35, alpha=0.05, beta=0.20, min_trades=5
            )

        assert result["status"] == "degraded"
        assert result["n"] == 50

    def test_sprt_returns_llr_and_n(self):
        """Result always contains llr and n keys."""
        import tracker

        with patch.object(tracker, "_get_recent_win_loss", return_value=(25, 50)):
            result = tracker.sprt_model_health(min_trades=5)

        assert "llr" in result
        assert "n" in result
        assert isinstance(result["llr"], float)
        assert isinstance(result["n"], int)


class TestIsAccuracyHaltedSprt:
    """Tests for SPRT wired into paper.is_accuracy_halted()."""

    def test_is_accuracy_halted_triggers_on_sprt_degraded(self, monkeypatch):
        """is_accuracy_halted returns True when sprt_model_health returns 'degraded'."""
        import paper
        import tracker
        import utils

        # Ensure rolling win rate check does NOT trigger (returns False)
        monkeypatch.setattr(
            utils, "ACCURACY_MIN_SAMPLE", 100
        )  # set min sample high so rolling check is skipped

        with patch.object(
            tracker,
            "sprt_model_health",
            return_value={"status": "degraded", "llr": -5.0, "n": 50},
        ):
            result = paper.is_accuracy_halted()

        assert result is True

    def test_is_accuracy_halted_not_triggered_when_sprt_ok(self, monkeypatch):
        """is_accuracy_halted returns False when SPRT is ok and rolling rate passes."""
        import paper
        import tracker
        import utils

        monkeypatch.setattr(utils, "ACCURACY_MIN_SAMPLE", 100)  # skip rolling check

        with patch.object(
            tracker,
            "sprt_model_health",
            return_value={"status": "ok", "llr": 2.0, "n": 50},
        ):
            result = paper.is_accuracy_halted()

        assert result is False

    def test_is_accuracy_halted_resilient_to_sprt_exception(self, monkeypatch):
        """is_accuracy_halted returns False if sprt_model_health raises an exception."""
        import paper
        import tracker
        import utils

        monkeypatch.setattr(utils, "ACCURACY_MIN_SAMPLE", 100)

        with patch.object(
            tracker,
            "sprt_model_health",
            side_effect=RuntimeError("DB unavailable"),
        ):
            result = paper.is_accuracy_halted()

        assert result is False
