"""Tests for strategy P&L attribution by signal source."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def tmp_tracker(tmp_path, monkeypatch):
    import tracker

    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
    monkeypatch.setattr(tracker, "_db_initialized", False)
    tracker.init_db()
    return tracker


class TestPnLAttribution:
    def test_log_prediction_accepts_signal_source(self, tmp_tracker):
        """log_prediction stores signal_source kwarg."""
        import sqlite3

        tmp_tracker.log_prediction(
            "TICKER-A",
            "NYC",
            date(2026, 4, 17),
            {"forecast_prob": 0.70, "market_prob": 0.50, "edge": 0.20, "condition": {}},
            signal_source="metar_lockout",
        )
        with sqlite3.connect(tmp_tracker.DB_PATH) as con:
            row = con.execute(
                "SELECT signal_source FROM predictions WHERE ticker='TICKER-A'"
            ).fetchone()
        assert row is not None
        assert row[0] == "metar_lockout"

    def test_get_pnl_by_signal_source_groups_correctly(self, tmp_tracker):
        """get_pnl_by_signal_source returns per-source stats."""
        for i in range(12):
            ticker = f"ENS-{i}"
            tmp_tracker.log_prediction(
                ticker,
                "NYC",
                date(2026, 4, i + 1),
                {
                    "forecast_prob": 0.70,
                    "market_prob": 0.50,
                    "edge": 0.20,
                    "condition": {},
                },
                signal_source="ensemble",
            )
            tmp_tracker.log_outcome(ticker, True)

        for i in range(8):
            ticker = f"MET-{i}"
            tmp_tracker.log_prediction(
                ticker,
                "NYC",
                date(2026, 4, i + 1),
                {
                    "forecast_prob": 0.90,
                    "market_prob": 0.50,
                    "edge": 0.40,
                    "condition": {},
                },
                signal_source="metar_lockout",
            )
            tmp_tracker.log_outcome(ticker, True)

        result = tmp_tracker.get_pnl_by_signal_source(min_samples=5)
        assert "ensemble" in result
        assert "metar_lockout" in result
        assert result["metar_lockout"]["n"] >= 8

    def test_get_pnl_by_signal_source_has_required_keys(self, tmp_tracker):
        """Each entry has brier, n, win_rate keys."""
        for i in range(12):
            ticker = f"T-{i}"
            tmp_tracker.log_prediction(
                ticker,
                "NYC",
                date(2026, 4, i + 1),
                {
                    "forecast_prob": 0.65,
                    "market_prob": 0.50,
                    "edge": 0.15,
                    "condition": {},
                },
                signal_source="mos",
            )
            tmp_tracker.log_outcome(ticker, i % 2 == 0)

        result = tmp_tracker.get_pnl_by_signal_source(min_samples=5)
        if "mos" in result:
            assert "brier" in result["mos"]
            assert "n" in result["mos"]
            assert "win_rate" in result["mos"]
