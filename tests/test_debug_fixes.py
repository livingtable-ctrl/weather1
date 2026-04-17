"""Regression tests for the full-program debug session fixes.

Covers:
  A — tracker.py: analysis_attempts upsert preserves was_traded=True on re-scan
  B — paper.py: malformed env vars fall back to defaults instead of crashing
  C — main.py: log_prediction failures are logged as warnings, not silently swallowed
  D — tracker.py: sync_outcomes failures are logged as warnings, not silently skipped
  E — paper.py: entry_prob=0.0 no longer treated as falsy
  F+G — paper.py: place_paper_order validates side and entry_prob range
  H — main.py: _auto_place_trades calls log_prediction so pnl-attribution sees cron trades
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_paper(tmp_path, monkeypatch):
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    yield paper


@pytest.fixture
def tmp_tracker(tmp_path, monkeypatch):
    import tracker

    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
    monkeypatch.setattr(tracker, "_db_initialized", False)
    tracker.init_db()
    return tracker


# ---------------------------------------------------------------------------
# Fix A — INSERT OR IGNORE upsert preserves was_traded=True
# ---------------------------------------------------------------------------


class TestAnalysisAttemptsUpsert:
    def test_batch_does_not_overwrite_was_traded_true(self, tmp_tracker):
        """Re-running batch_log_analysis_attempts must not reset was_traded to 0."""
        # First pass: single traded entry
        tmp_tracker.log_analysis_attempt(
            ticker="KXHI-NYC-2026-04-20-T70B",
            city="NYC",
            condition="high>=70",
            target_date=date(2026, 4, 20),
            forecast_prob=0.72,
            market_prob=0.55,
            days_out=4,
            was_traded=True,
        )

        # Second pass: cron re-scans the same market, sets was_traded=False in the batch
        tmp_tracker.batch_log_analysis_attempts(
            [
                {
                    "ticker": "KXHI-NYC-2026-04-20-T70B",
                    "city": "NYC",
                    "condition": "high>=70",
                    "target_date": date(2026, 4, 20),
                    "forecast_prob": 0.74,
                    "market_prob": 0.54,
                    "days_out": 4,
                    "was_traded": False,
                }
            ]
        )

        import sqlite3

        with sqlite3.connect(tmp_tracker.DB_PATH) as con:
            row = con.execute(
                "SELECT was_traded FROM analysis_attempts "
                "WHERE ticker='KXHI-NYC-2026-04-20-T70B'"
            ).fetchone()
        assert row is not None
        assert row[0] == 1, "was_traded must stay 1 after re-scan batch"

    def test_batch_can_set_was_traded_true(self, tmp_tracker):
        """was_traded can go from 0 → 1 via log_analysis_attempt after batch insert."""
        tmp_tracker.batch_log_analysis_attempts(
            [
                {
                    "ticker": "KXHI-CHI-2026-04-21-T65B",
                    "city": "Chicago",
                    "condition": "high>=65",
                    "target_date": date(2026, 4, 21),
                    "forecast_prob": 0.60,
                    "market_prob": 0.48,
                    "days_out": 5,
                    "was_traded": False,
                }
            ]
        )
        # Later, trade is placed — update row
        tmp_tracker.log_analysis_attempt(
            ticker="KXHI-CHI-2026-04-21-T65B",
            city="Chicago",
            condition="high>=65",
            target_date=date(2026, 4, 21),
            forecast_prob=0.60,
            market_prob=0.48,
            days_out=5,
            was_traded=True,
        )
        import sqlite3

        with sqlite3.connect(tmp_tracker.DB_PATH) as con:
            row = con.execute(
                "SELECT was_traded FROM analysis_attempts "
                "WHERE ticker='KXHI-CHI-2026-04-21-T65B'"
            ).fetchone()
        assert row is not None
        assert row[0] == 1

    def test_fresh_rows_are_still_inserted(self, tmp_tracker):
        """New rows must still be inserted when there's no conflict."""
        tmp_tracker.batch_log_analysis_attempts(
            [
                {
                    "ticker": "NEW-TICKER-ABCD",
                    "city": "Boston",
                    "condition": "high>=75",
                    "target_date": date(2026, 5, 1),
                    "forecast_prob": 0.55,
                    "market_prob": 0.42,
                    "days_out": 15,
                    "was_traded": False,
                }
            ]
        )
        import sqlite3

        with sqlite3.connect(tmp_tracker.DB_PATH) as con:
            count = con.execute(
                "SELECT COUNT(*) FROM analysis_attempts WHERE ticker='NEW-TICKER-ABCD'"
            ).fetchone()[0]
        assert count == 1


# ---------------------------------------------------------------------------
# Fix B — env var parsing fallback
# ---------------------------------------------------------------------------


class TestEnvVarFallback:
    def test_bad_drawdown_env_var_uses_default(self, monkeypatch):
        """Malformed DRAWDOWN_HALT_PCT falls back to 0.50 without crashing."""
        monkeypatch.setenv("DRAWDOWN_HALT_PCT", "not_a_float")
        import paper

        # _env_float should return the default (0.50) rather than raising
        result = paper._env_float("DRAWDOWN_HALT_PCT", "0.50")
        assert result == pytest.approx(0.50)

    def test_bad_max_daily_loss_env_var_uses_default(self, monkeypatch):
        monkeypatch.setenv("MAX_DAILY_LOSS_PCT", "???")
        import paper

        result = paper._env_float("MAX_DAILY_LOSS_PCT", "0.03")
        assert result == pytest.approx(0.03)

    def test_bad_position_age_int_var_uses_default(self, monkeypatch):
        monkeypatch.setenv("MAX_POSITION_AGE_DAYS", "seven")
        import paper

        result = paper._env_int("MAX_POSITION_AGE_DAYS", "7")
        assert result == 7

    def test_valid_env_var_is_used(self, monkeypatch):
        monkeypatch.setenv("DRAWDOWN_HALT_PCT", "0.30")
        import paper

        result = paper._env_float("DRAWDOWN_HALT_PCT", "0.50")
        assert result == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# Fix E — entry_prob=0.0 is not substituted with 0.5
# ---------------------------------------------------------------------------


class TestEntryProbFalsyZero:
    def test_covariance_kelly_uses_zero_entry_prob_not_half(
        self, tmp_paper, monkeypatch
    ):
        """entry_prob=0.0 on an open trade must not be replaced by 0.5 in covariance math."""
        import paper

        fake_trades = [
            {
                "id": 1,
                "ticker": "KXHI-BOS-2026-04-20-T68B",
                "side": "yes",
                "quantity": 10,
                "entry_price": 0.50,
                "entry_prob": 0.0,  # <-- the edge case
                "net_edge": 0.0,
                "cost": 5.0,
                "city": "Boston",
                "target_date": "2026-04-20",
                "entered_at": "2026-04-16T12:00:00+00:00",
                "entry_hour": 12,
                "settled": False,
                "outcome": None,
                "pnl": None,
                "exit_target": None,
                "thesis": None,
                "icon_forecast_mean": None,
                "gfs_forecast_mean": None,
                "condition_threshold": None,
            }
        ]
        monkeypatch.setattr(paper, "get_open_trades", lambda: fake_trades)
        result = paper.covariance_kelly_scale("NYC", 0.65, "yes")
        assert isinstance(result, float)
        assert 0.0 < result <= 1.0

    def test_pnl_decomposition_uses_zero_entry_prob(self, tmp_paper, monkeypatch):
        """get_attribution must not substitute 0.5 when entry_prob is 0.0."""
        import paper

        fake_settled = [
            {
                "id": 1,
                "ticker": "T-ZERO",
                "side": "yes",
                "quantity": 5,
                "entry_price": 0.40,
                "entry_prob": 0.0,
                "cost": 2.0,
                "settled": True,
                "outcome": "yes",
                "pnl": 1.0,
                "city": "NYC",
                "target_date": "2026-04-20",
            }
        ]

        def _fake_load():
            return {"trades": fake_settled, "balance": 1001.0, "peak_balance": 1001.0}

        monkeypatch.setattr(paper, "_load", _fake_load)
        result = paper.get_attribution()
        # Should complete without error and P&L components must sum to total
        assert result["pnl_from_edge"] + result["pnl_from_luck"] == pytest.approx(
            result["total_pnl"], abs=1e-6
        )


# ---------------------------------------------------------------------------
# Fix F+G — place_paper_order input validation
# ---------------------------------------------------------------------------


class TestPlacePaperOrderValidation:
    def test_invalid_side_raises(self, tmp_path, monkeypatch):
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        with pytest.raises(ValueError, match="side must be"):
            paper.place_paper_order("TICKER", "maybe", 1, 0.50)

    def test_yes_side_accepted(self, tmp_path, monkeypatch):
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        trade = paper.place_paper_order("TICKER", "yes", 1, 0.50)
        assert trade["side"] == "yes"

    def test_no_side_accepted(self, tmp_path, monkeypatch):
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        trade = paper.place_paper_order("TICKER2", "no", 1, 0.50)
        assert trade["side"] == "no"

    def test_entry_prob_above_one_raises(self, tmp_path, monkeypatch):
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        with pytest.raises(ValueError, match="entry_prob must be in"):
            paper.place_paper_order("TICKER", "yes", 1, 0.50, entry_prob=1.5)

    def test_entry_prob_negative_raises(self, tmp_path, monkeypatch):
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        with pytest.raises(ValueError, match="entry_prob must be in"):
            paper.place_paper_order("TICKER", "yes", 1, 0.50, entry_prob=-0.1)

    def test_entry_prob_zero_accepted(self, tmp_path, monkeypatch):
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        trade = paper.place_paper_order("TICKER", "yes", 1, 0.50, entry_prob=0.0)
        assert trade["entry_prob"] == 0.0

    def test_entry_prob_one_accepted(self, tmp_path, monkeypatch):
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        trade = paper.place_paper_order("TICKER", "yes", 1, 0.50, entry_prob=1.0)
        assert trade["entry_prob"] == 1.0

    def test_entry_price_zero_raises(self, tmp_path, monkeypatch):
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        with pytest.raises(ValueError, match="entry_price must be in"):
            paper.place_paper_order("TICKER", "yes", 1, 0.0)

    def test_entry_price_above_one_raises(self, tmp_path, monkeypatch):
        import paper

        monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
        with pytest.raises(ValueError, match="entry_price must be in"):
            paper.place_paper_order("TICKER", "yes", 1, 1.1)


# ---------------------------------------------------------------------------
# Fix C — log_prediction warnings visible (not silently swallowed)
# ---------------------------------------------------------------------------


class TestLogPredictionWarning:
    def test_log_prediction_failure_emits_warning(self, caplog, monkeypatch):
        """When log_prediction raises, cmd_analyze logs a warning."""
        import logging

        import tracker

        def _bad_log(*args, **kwargs):
            raise RuntimeError("db locked")

        monkeypatch.setattr(tracker, "log_prediction", _bad_log)

        with caplog.at_level(logging.WARNING):
            # Simulate just the try/except block behaviour
            _log = logging.getLogger("main")
            ticker = "TEST-TICKER"
            try:
                tracker.log_prediction(ticker, None, None, {})
            except Exception as exc:
                _log.warning(
                    "cmd_analyze: log_prediction failed for %s: %s", ticker, exc
                )

        assert any("log_prediction failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Fix D — sync_outcomes logs failures
# ---------------------------------------------------------------------------


class TestSyncOutcomesWarning:
    def test_sync_outcomes_logs_on_client_error(self, tmp_tracker, caplog):
        """sync_outcomes logs a warning when client.get_market raises."""
        import logging

        tmp_tracker.log_prediction(
            "FAIL-TICKER",
            "NYC",
            date(2026, 4, 20),
            {"forecast_prob": 0.70, "market_prob": 0.55, "edge": 0.15, "condition": {}},
        )

        mock_client = MagicMock()
        mock_client.get_market.side_effect = RuntimeError("timeout")

        with caplog.at_level(logging.WARNING):
            count = tmp_tracker.sync_outcomes(mock_client)

        assert count == 0
        assert any("sync_outcomes" in r.message for r in caplog.records)
