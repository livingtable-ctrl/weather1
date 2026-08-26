"""Tests for walk-forward backtesting engine."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_trade(
    date_str: str, our_prob: float, settled_yes: bool, side: str | None = None
) -> dict:
    """Make a minimal trade record for backtesting."""
    trade = {
        "market_date": date_str,
        "our_prob": our_prob,
        "settled_yes": settled_yes,
        "city": "NYC",
        "method": "ensemble",
        "edge": abs(our_prob - 0.5),
    }
    if side is not None:
        trade["side"] = side
    return trade


class TestIsWin:
    def test_true_when_outcome_matches_side(self):
        from backtest import _is_win

        assert _is_win({"side": "yes", "settled_yes": True}) is True
        assert _is_win({"side": "no", "settled_yes": False}) is True

    def test_false_when_outcome_diverges_from_side(self):
        """Positive control for the regression test below: a NO-side trade
        that settled YES is a LOSS, even though settled_yes=True."""
        from backtest import _is_win

        assert _is_win({"side": "no", "settled_yes": True}) is False
        assert _is_win({"side": "yes", "settled_yes": False}) is False

    def test_falls_back_to_settled_yes_when_side_absent(self):
        from backtest import _is_win

        assert _is_win({"settled_yes": True}) is True
        assert _is_win({"settled_yes": False}) is False


class TestFindOptimalMinEdgeSideAware:
    def test_scores_side_aware_win_rate_not_yes_settlement_rate(self):
        """L-14: settled_yes alone is the YES-settlement rate, not a win
        rate -- inverted for NO-side trades. 10 NO-side LOSSES (outcome=yes,
        so settled_yes=True) only clear the 0.04 threshold; 10 YES-side WINS
        clear both 0.04 and 0.05.

        Scoring settled_yes directly (the bug) rates threshold 0.04 at 100%
        ("wins") and ties threshold 0.05 at 100% too, picking 0.04 (first
        threshold wins ties). Scoring outcome==side (the fix) rates 0.04 at
        50% (the NO-side losses correctly count as losses) and 0.05 at
        100%, correctly picking the higher threshold that excludes the
        lossy pool.

        Mutation-tested: reverting _find_optimal_min_edge's win sum from
        _is_win(t) to t.get("settled_yes") makes this fail (returns 0.04
        instead of 0.05) -- confirmed via Edit revert.
        """
        from backtest import _find_optimal_min_edge

        no_side_losses = [
            _make_trade(f"2025-01-{i:02d}", 0.54, True, side="no") for i in range(1, 11)
        ]  # edge = |0.54-0.5| = 0.04; side=no, outcome=yes -> loss
        yes_side_wins = [
            _make_trade(f"2025-02-{i:02d}", 0.55, True, side="yes")
            for i in range(1, 11)
        ]  # edge = |0.55-0.5| = 0.05; side=yes, outcome=yes -> win

        result = _find_optimal_min_edge(no_side_losses + yes_side_wins)

        assert result == 0.05, (
            f"expected the side-aware fix to pick 0.05 (excludes the lossy "
            f"NO-side pool); got {result}"
        )


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


def test_run_walk_forward_reads_from_db_not_run_backtest(monkeypatch):
    """run_walk_forward reads settled predictions from the tracker DB directly;
    it does NOT call run_backtest (that API was removed to avoid redundant calls).
    """
    from datetime import date, timedelta
    from unittest.mock import MagicMock, patch

    import backtest

    client = MagicMock()

    # Patch the DB query inside run_walk_forward to return synthetic rows
    today = date.today()
    fake_rows = [
        MagicMock(
            **{
                "__getitem__.side_effect": lambda k: {
                    "our_prob": 0.70,
                    "city": "NYC",
                    "market_date": (today - timedelta(days=d)).isoformat(),
                    "settled_yes": 1,
                }[k]
            }
        )
        for d in [10, 40, 80, 130]
    ]

    run_backtest_called = []

    with (
        patch(
            "backtest.run_backtest",
            side_effect=lambda *a, **kw: run_backtest_called.append(1),
        ),
        patch("sqlite3.connect") as mock_connect,
    ):
        mock_con = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = fake_rows
        mock_con.cursor.return_value = mock_cur
        mock_con.__enter__ = lambda s: s
        mock_con.__exit__ = MagicMock(return_value=False)
        mock_connect.return_value = mock_con

        result = backtest.run_walk_forward(
            client, days_total=180, window_size=60, step_size=30
        )

    assert len(run_backtest_called) == 0, (
        "run_walk_forward must NOT call run_backtest — it reads from DB directly"
    )
    # Result should at minimum have the expected keys
    assert "windows" in result, (
        f"Expected 'windows' key in result; got {list(result.keys())}"
    )


def test_fetch_settled_markets_queries_by_weather_series():
    """_fetch_settled_markets must query by series_ticker, not dump all global markets.
    The global status=settled endpoint returns thousands of non-weather markets and
    buries weather series beyond the page limit."""
    from unittest.mock import MagicMock

    import backtest

    client = MagicMock()
    client._get.return_value = {"markets": [], "cursor": None}

    backtest._fetch_settled_markets(client, max_pages=1)

    assert client._get.called
    # Every call must include a series_ticker param (weather series filter)
    for call in client._get.call_args_list:
        params_used = call[1].get("params") or call[0][1]
        assert "series_ticker" in params_used, (
            f"_fetch_settled_markets must filter by series_ticker; got params: {params_used}"
        )
        assert params_used.get("status") == "settled", (
            f"_fetch_settled_markets must use status='settled'; got {params_used.get('status')!r}"
        )


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


class TestPerConditionBrierIncludesBetween:
    """batch-79 item 3: the per-condition Brier breakdown must not drop 'between'.

    The shared exclusion in tracker._ALWAYS_EXCLUDED_CONDITION_TYPES exists so
    that between-brackets' structurally larger calibration gap cannot distort a
    POOLED Brier standing for overall model quality. This query groups by
    condition_type, so nothing is pooled and that reason cannot apply -- while
    the drop did hide the finding: measured 2026-08-26 against the live DB,
    between was n=114 (33% of settled rows) at Brier 0.2794, worse than above
    (0.2498) and below (0.2657), predicting 20.4% against a 40.4% actual rate.
    """

    @staticmethod
    def _seed_db(path):
        import sqlite3

        con = sqlite3.connect(str(path))
        con.execute(
            "CREATE TABLE predictions (ticker TEXT, our_prob REAL, condition_type TEXT)"
        )
        con.execute("CREATE TABLE outcomes_valid (ticker TEXT, settled_yes INTEGER)")
        rows = []
        # 'above' and 'below' between them clear the block's own >=10-row and
        # >1-group thresholds WITHOUT any 'between' row. That is deliberate:
        # it means re-adding the `condition_type != 'between'` predicate still
        # renders the panel, so the test below fails on 'between' being
        # missing from it rather than on the whole block being skipped.
        #
        # 6 'above' rows, all p=0.8 and all resolved YES.
        #   Brier = (0.8 - 1)^2 = 0.0400
        for i in range(6):
            rows.append((f"A{i}", 0.8, "above", 1))
        # 6 'below' rows, all p=0.6, three resolved YES and three NO.
        #   Brier = (3*(0.6-1)^2 + 3*(0.6-0)^2) / 6
        #         = (3*0.16 + 3*0.36) / 6 = 1.56 / 6 = 0.2600
        #   pred = 60.0%, actual = 50.0%
        for i in range(6):
            rows.append((f"C{i}", 0.6, "below", 1 if i < 3 else 0))
        # 6 'between' rows, all p=0.2, four resolved YES and two NO.
        #   Brier = (4*(0.2-1)^2 + 2*(0.2-0)^2) / 6
        #         = (4*0.64 + 2*0.04) / 6 = 2.64 / 6 = 0.4400
        #   pred = 20.0%, actual = 4/6 = 66.7%
        for i in range(6):
            rows.append((f"B{i}", 0.2, "between", 1 if i < 4 else 0))
        for ticker, prob, cond, settled in rows:
            con.execute("INSERT INTO predictions VALUES (?,?,?)", (ticker, prob, cond))
            con.execute("INSERT INTO outcomes_valid VALUES (?,?)", (ticker, settled))
        con.commit()
        con.close()

    @staticmethod
    def _run(monkeypatch, tmp_path, capsys):
        from unittest.mock import MagicMock

        import main
        import tracker

        TestPerConditionBrierIncludesBetween._seed_db(tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        # The calibration-curve block above the per-condition one runs its own
        # tracker queries against the same DB; stub them to "no data" so this
        # test exercises only the breakdown it is about.
        monkeypatch.setattr(
            tracker, "get_multiday_calibration_cli", lambda *a, **kw: {"n": 0}
        )
        monkeypatch.setattr(
            tracker, "get_sameday_calibration_cli", lambda *a, **kw: {"n": 0}
        )
        monkeypatch.setattr(
            "backtest.run_walk_forward",
            lambda *a, **kw: {
                "windows": [{"n": 12}],
                "avg_brier": 0.24,
                "avg_win_rate": 0.5,
                "stability_score": 0.8,
                "trend": "stable",
                "city_win_rates": {},  # keeps cmd_walkforward off its input() prompt
            },
        )
        main.cmd_walkforward(MagicMock())
        out = capsys.readouterr().out
        return {
            line.strip().split()[0]: line
            for line in out.splitlines()
            if line.strip().startswith(("above", "below", "between"))
        }

    def test_between_appears_with_its_own_hand_computed_brier(
        self, monkeypatch, tmp_path, capsys
    ):
        lines = self._run(monkeypatch, tmp_path, capsys)

        assert "between" in lines, (
            "'between' is missing from a breakdown named 'Per-condition Brier'"
        )
        between = lines["between"]
        assert "0.4400" in between, between
        assert "pred=20.0%" in between, between
        assert "actual=66.7%" in between, between
        assert "N=6" in between, between

    def test_the_other_conditions_keep_their_own_separate_buckets(
        self, monkeypatch, tmp_path, capsys
    ):
        """Positive control: the panel renders and every condition keeps its
        own bucket, so the test above cannot pass on a change that pooled all
        18 rows into a single row that merely happens to be labelled
        'between'. These two rows are also what make the panel survive the
        `!= 'between'` predicate, which is what lets that test fail for the
        right reason."""
        lines = self._run(monkeypatch, tmp_path, capsys)

        assert "above" in lines
        above = lines["above"]
        assert "0.0400" in above, above
        assert "pred=80.0%" in above, above
        assert "actual=100.0%" in above, above
        assert "N=6" in above, above

        assert "below" in lines
        below = lines["below"]
        assert "0.2600" in below, below
        assert "pred=60.0%" in below, below
        assert "actual=50.0%" in below, below
        assert "N=6" in below, below
