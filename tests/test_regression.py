"""Regression test: Brier score must not degrade more than 1% after refactors."""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date
from pathlib import Path

import pytest

import tracker

BASELINE_FILE = Path(__file__).parent / "fixtures" / "regression_baseline.json"
TOLERANCE = 0.01


def test_brier_score_not_degraded():
    baseline = json.loads(BASELINE_FILE.read_text())
    baseline_bs = baseline.get("brier_score")
    if baseline_bs is None:
        pytest.skip("No baseline Brier score yet")
    from tracker import brier_score

    current = brier_score()
    assert current is not None
    assert current <= baseline_bs + TOLERANCE, (
        f"Brier score degraded: {current:.4f} vs baseline {baseline_bs:.4f}"
    )


def test_roc_auc_not_degraded():
    baseline = json.loads(BASELINE_FILE.read_text())
    baseline_roc = baseline.get("roc_auc")
    if baseline_roc is None:
        pytest.skip("No baseline ROC-AUC yet")
    from tracker import get_roc_auc

    current = get_roc_auc()
    assert current is not None
    assert current >= baseline_roc - TOLERANCE


class TestBrierScoreComputation:
    """Deterministic regression tests using a seeded in-memory DB (#113).

    These tests verify that brier_score() and get_roc_auc() produce the
    mathematically correct value on known data. If the formula changes, these
    will catch it.
    """

    def setup_method(self):
        """Redirect tracker to a fresh temp DB before each test."""
        self._tmpdir = tempfile.mkdtemp()
        self._orig_path = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test.db"
        tracker._db_initialized = False

    def teardown_method(self):
        tracker.DB_PATH = self._orig_path
        tracker._db_initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _seed(self, probs_outcomes):
        """Log predictions+outcomes into the temp DB."""
        for suffix, prob, outcome in probs_outcomes:
            ticker = f"KXTEST-{suffix}"
            tracker.log_prediction(
                ticker,
                "NYC",
                date(2026, 4, 10),
                {
                    "forecast_prob": prob,
                    "market_prob": 0.5,
                    "edge": prob - 0.5,
                    "method": "ensemble",
                    "n_members": 12,
                    "condition": {"type": "above", "threshold": 70.0},
                },
            )
            tracker.log_outcome(ticker, settled_yes=outcome)

    def test_brier_score_known_value(self):
        """BS on [0.9->YES, 0.1->NO, 0.8->YES, 0.2->NO] must equal 0.025."""
        self._seed(
            [
                ("A", 0.9, True),
                ("B", 0.1, False),
                ("C", 0.8, True),
                ("D", 0.2, False),
            ]
        )
        result = tracker.brier_score()
        assert result is not None
        assert result == pytest.approx(0.025, abs=1e-6), (
            f"Expected Brier=0.025, got {result}"
        )

    def test_brier_score_no_data_returns_none(self):
        """brier_score() on empty DB returns None (not 0.0, not error)."""
        result = tracker.brier_score()
        assert result is None

    def test_roc_auc_perfect_classifier(self):
        """AUC=1.0 when high probs always -> YES and low probs always -> NO."""
        self._seed(
            [
                ("E1", 0.9, True),
                ("E2", 0.85, True),
                ("E3", 0.80, True),
                ("E4", 0.75, True),
                ("E5", 0.70, True),
                ("E6", 0.20, False),
                ("E7", 0.15, False),
                ("E8", 0.10, False),
                ("E9", 0.05, False),
                ("E10", 0.02, False),
            ]
        )
        result = tracker.get_roc_auc()
        assert result["auc"] is not None
        assert result["auc"] == pytest.approx(1.0, abs=1e-6), (
            f"Expected AUC=1.0 for perfect classifier, got {result['auc']}"
        )


def test_simulate_uses_series_fetch_not_global_pagination(monkeypatch):
    """cmd_simulate must call backtest._fetch_settled_markets (series-based), not get_markets."""
    from unittest.mock import MagicMock

    import main

    weather_markets_returned = [
        {
            "ticker": "KXHIGHNY-25APR30-T65",
            "title": "High temp NYC above 65",
            "result": "yes",
            "close_time": "2025-04-30T12:00:00Z",
            "yes_ask": 60,
            "yes_bid": 58,
        },
    ]

    fetch_called = {"n": 0}

    def _fake_fetch(client, **kw):
        fetch_called["n"] += 1
        return weather_markets_returned

    monkeypatch.setattr("backtest._fetch_settled_markets", _fake_fetch)
    monkeypatch.setattr("weather_markets.is_weather_market", lambda m: True)
    monkeypatch.setattr("weather_markets.enrich_with_forecast", lambda m: m)
    monkeypatch.setattr(
        "weather_markets.parse_market_price",
        lambda m: {"mid": 0.60, "yes_ask": 60, "yes_bid": 58},
    )

    client = MagicMock()
    monkeypatch.setattr("builtins.input", lambda *a: "s")

    main.cmd_simulate(client)
    assert fetch_called["n"] == 1, (
        "cmd_simulate must call _fetch_settled_markets, not get_markets"
    )
    assert client.get_markets.call_count == 0, "get_markets must NOT be called"


def test_get_weather_markets_does_not_call_global_get_markets(monkeypatch):
    """get_weather_markets must not call client.get_markets() without series_ticker.
    Strategy 1 (global open-market scan) is removed — Strategy 2 covers all known series.
    """
    from unittest.mock import MagicMock

    import weather_markets

    client = MagicMock()
    client.get_markets.return_value = []

    monkeypatch.setattr(weather_markets, "_MARKETS_CACHE", None)

    weather_markets.get_weather_markets(client, force=True)

    for call in client.get_markets.call_args_list:
        kwargs = (
            call.kwargs
            if hasattr(call, "kwargs")
            else (call[1] if len(call) > 1 else {})
        )
        assert "series_ticker" in kwargs, (
            f"get_weather_markets must not call get_markets without series_ticker, got: {call}"
        )
