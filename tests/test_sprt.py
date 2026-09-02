"""
Tests for SPRT model degradation detection in tracker.py and paper.py.
"""

from __future__ import annotations

from unittest.mock import patch


class TestSprtWindowExcludesNonDirectionalFamilies:
    """The SPRT window must exclude the same condition types
    get_rolling_win_rate() excludes.

    These tests bind to the REAL query. Every other test in this file patches
    _get_recent_win_loss, which is exactly why the missing filter survived:
    the query itself had no coverage. Seeds the forbidden rows rather than
    inspecting the SQL text, so a reworded query that still lets them through
    fails.
    """

    @staticmethod
    def _seed(rows):
        """rows: (ticker, condition_type, our_prob, settled_yes, settled_at)."""
        import tracker

        with tracker._conn() as con:
            for tk, ct, prob, yes, at in rows:
                con.execute(
                    "INSERT INTO predictions (ticker, predicted_at, "
                    "condition_type, our_prob, days_out) VALUES (?,?,?,?,?)",
                    (tk, "2026-09-01T00:00:00+00:00", ct, prob, 1),
                )
                con.execute(
                    "INSERT INTO outcomes (ticker, settled_yes, settled_at) "
                    "VALUES (?,?,?)",
                    (tk, yes, at),
                )

    def test_monthly_precip_rows_cannot_enter_the_sprt_window(self):
        """The live 2026-09-02 halt: 49 precip_month_total losses filled the
        window and tripped the breaker while the temperature model was fine."""
        import tracker

        # 6 precip losses settled LAST (so an unfiltered ORDER BY
        # settled_at DESC would take them first), 4 temperature wins before.
        self._seed(
            [
                (f"TEMPWIN{i}", "above", 0.9, 1, f"2026-09-01 00:00:0{i}")
                for i in range(4)
            ]
            + [
                (
                    f"PRECIPLOSS{i}",
                    "precip_month_total",
                    0.9,
                    0,
                    f"2026-09-01 01:00:0{i}",
                )
                for i in range(6)
            ]
        )

        # window=4, NOT 10: the live incident was CROWD-OUT -- the monthly
        # rows consumed the whole LIMIT so zero temperature rows entered.
        # At window=10 nothing is crowded out and `wins` is 4 either way,
        # so only `n` would discriminate. At window=4 the mutation returns
        # (0, 4) -- the four newest rows are all precip losses.
        wins, n = tracker._get_recent_win_loss(4)

        # VALUE first: only the 4 temperature rows survive, and all are wins.
        assert (wins, n) == (4, 4), (
            f"expected the 4 temperature WINS only, got wins={wins} n={n} -- "
            "precip_month_total leaked into the circuit breaker's window"
        )

    def test_tornado_count_also_excluded(self):
        """The live window also carried a tornado_count row."""
        import tracker

        self._seed(
            [
                ("TEMPWIN", "above", 0.9, 1, "2026-09-01 00:00:01"),
                ("TORNADOLOSS", "tornado_count", 0.9, 0, "2026-09-01 02:00:00"),
            ]
        )

        assert tracker._get_recent_win_loss(10) == (1, 1)

    def test_directional_rows_are_still_counted(self):
        """Positive control: the filter must not empty the window. Without
        this, a query returning nothing at all would pass the two tests
        above."""
        import tracker

        self._seed(
            [
                ("A", "above", 0.9, 1, "2026-09-01 00:00:01"),
                ("B", "below", 0.9, 0, "2026-09-01 00:00:02"),
                ("C", "above", 0.2, 0, "2026-09-01 00:00:03"),
            ]
        )

        # A: prob>=.5 & yes -> win. B: prob>=.5 & no -> loss.
        # C: prob<.5 & no -> win.
        assert tracker._get_recent_win_loss(10) == (2, 3)


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

    def test_sprt_degraded_with_tighter_p1(self):
        """P1-17: p1=0.45 fires on moderate degradation that p1=0.35 would miss.

        18/50 = 36% win rate pushes LLR above upper boundary (≈2.81 > 2.77).
        With the old p1=0.35 this same sequence would not trigger degraded.
        """
        import tracker

        with patch.object(tracker, "_get_recent_win_loss", return_value=(18, 50)):
            result = tracker.sprt_model_health(
                p0=0.55, p1=0.45, alpha=0.05, beta=0.20, min_trades=20
            )

        assert result["status"] == "degraded"

    def test_sprt_lower_boundary_returns_cleared(self):
        """P1-17: 29/50 wins pushes LLR below lower boundary → cleared=True."""
        import tracker

        # 29/50 = 58% win rate, LLR ≈ -1.61 < lower ≈ -1.56 → accept H0
        with patch.object(tracker, "_get_recent_win_loss", return_value=(29, 50)):
            result = tracker.sprt_model_health(
                p0=0.55, p1=0.45, alpha=0.05, beta=0.20, min_trades=20
            )

        assert result["status"] == "ok"
        assert result.get("cleared") is True

    def test_sprt_min_trades_default_is_20(self, monkeypatch):
        """P1-17: default SPRT_MIN_TRADES is 20 (was 5)."""
        import utils

        assert utils.SPRT_MIN_TRADES == 20

    def test_sprt_p1_default_is_0_45(self, monkeypatch):
        """P1-17: default SPRT_P1 is 0.45 (was 0.35)."""
        import utils

        assert utils.SPRT_P1 == 0.45

    def test_sprt_insufficient_data_with_new_min_trades(self, monkeypatch):
        """P1-17: 15 trades returns insufficient_data with default min_trades=20."""
        import tracker
        import utils

        monkeypatch.setattr(utils, "SPRT_MIN_TRADES", 20)

        with patch.object(tracker, "_get_recent_win_loss", return_value=(8, 15)):
            result = tracker.sprt_model_health()

        assert result["status"] == "insufficient_data"


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

    def test_is_accuracy_halted_fails_closed_on_sprt_exception(self, monkeypatch):
        """2026-07-09: fail closed, not open -- sprt_model_health raising (a
        Windows Defender DB lock has been observed in production) must halt
        trading as a precaution, not silently let it continue."""
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

        assert result is True
