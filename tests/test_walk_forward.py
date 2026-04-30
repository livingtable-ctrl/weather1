"""Tests for walk-forward backtesting engine."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_trade(date_str: str, our_prob: float, settled_yes: bool) -> dict:
    """Make a minimal trade record for backtesting."""
    return {
        "market_date": date_str,
        "our_prob": our_prob,
        "settled_yes": settled_yes,
        "city": "NYC",
        "method": "ensemble",
        "edge": abs(our_prob - 0.5),
    }


class TestWalkForwardSplit:
    def test_creates_correct_number_of_folds(self):
        """With 12 months of data and window=6, test_size=1 → 6 folds."""
        from backtest import walk_forward_split

        trades = []
        # One trade per calendar month for exactly 12 distinct months
        for month in range(1, 13):
            d = date(2025, month, 15)
            trades.append(_make_trade(d.isoformat(), 0.65, True))

        folds = walk_forward_split(trades, train_months=6, test_months=1)
        assert len(folds) == 6  # months 7-12 each tested once

    def test_no_data_leakage(self):
        """Test period never overlaps with train period in any fold."""
        from backtest import walk_forward_split

        trades = []
        for month in range(1, 13):
            d = date(2025, month, 15)
            trades.append(_make_trade(d.isoformat(), 0.65, True))

        folds = walk_forward_split(trades, train_months=6, test_months=1)
        for train, test in folds:
            train_dates = {t["market_date"] for t in train}
            test_dates = {t["market_date"] for t in test}
            assert not train_dates.intersection(test_dates), (
                "Data leakage: train/test overlap"
            )

    def test_test_period_advances_each_fold(self):
        """Each fold's test period is one month later than the previous."""
        from backtest import walk_forward_split

        trades = []
        for month in range(1, 13):
            d = date(2025, month, 15)
            trades.append(_make_trade(d.isoformat(), 0.65, True))

        folds = walk_forward_split(trades, train_months=6, test_months=1)
        prev_test_end = None
        for _, test in folds:
            test_months = sorted(set(t["market_date"][:7] for t in test))
            if prev_test_end is not None:
                assert test_months[0] > prev_test_end
            prev_test_end = test_months[-1]

    def test_insufficient_data_returns_empty(self):
        """Less than train_months + test_months of data → empty list."""
        from backtest import walk_forward_split

        trades = [_make_trade("2025-01-15", 0.65, True)]
        folds = walk_forward_split(trades, train_months=6, test_months=1)
        assert folds == []


class TestWalkForwardBacktest:
    def test_returns_results_dict(self):
        """walk_forward_backtest returns a dict with 'folds' list."""
        from backtest import walk_forward_backtest

        trades = []
        start = date(2025, 1, 1)
        for i in range(12):
            d = start + timedelta(days=30 * i)
            trades.append(_make_trade(d.isoformat(), 0.70, True))

        result = walk_forward_backtest(trades, train_months=6, test_months=1)
        assert "folds" in result
        assert isinstance(result["folds"], list)

    def test_each_fold_has_brier_score(self):
        """Each fold in results has 'brier', 'n_test', 'test_period' keys."""
        from backtest import walk_forward_backtest

        trades = []
        start = date(2025, 1, 1)
        for i in range(360):
            d = start + timedelta(days=i)
            trades.append(_make_trade(d.isoformat(), 0.65, i % 2 == 0))

        result = walk_forward_backtest(trades, train_months=6, test_months=1)
        for fold in result["folds"]:
            assert "brier" in fold
            assert "n_test" in fold
            assert "test_period" in fold

    def test_brier_scores_in_valid_range(self):
        """All fold Brier scores are between 0.0 and 1.0."""
        from backtest import walk_forward_backtest

        trades = []
        start = date(2025, 1, 1)
        for i in range(360):
            d = start + timedelta(days=i)
            trades.append(_make_trade(d.isoformat(), 0.65, i % 2 == 0))

        result = walk_forward_backtest(trades, train_months=6, test_months=1)
        for fold in result["folds"]:
            if fold.get("n_test", 0) > 0:
                assert 0.0 <= fold["brier"] <= 1.0

    def test_result_includes_summary(self):
        """Result includes overall mean_brier and std_brier across folds."""
        from backtest import walk_forward_backtest

        trades = []
        start = date(2025, 1, 1)
        for i in range(360):
            d = start + timedelta(days=i)
            trades.append(_make_trade(d.isoformat(), 0.65, True))

        result = walk_forward_backtest(trades, train_months=6, test_months=1)
        assert "mean_brier" in result
        assert "std_brier" in result
        assert "n_folds" in result


def test_walkforward_prints_no_data_message_when_empty(monkeypatch, capsys):
    """When no windows have data, cmd_walkforward should print a clear no-data message."""
    from unittest.mock import MagicMock

    import main

    empty_result = {
        "windows": [],
        "avg_brier": None,
        "avg_win_rate": None,
        "stability_score": None,
        "trend": "unknown",
        "city_win_rates": {},
    }
    monkeypatch.setattr("backtest.run_walk_forward", lambda *a, **kw: empty_result)

    client = MagicMock()
    main.cmd_walkforward(client)
    out = capsys.readouterr().out
    assert (
        "no data" in out.lower()
        or "no settled" in out.lower()
        or "0 windows" in out.lower()
    ), f"Should print a clear no-data message, got:\n{out}"
