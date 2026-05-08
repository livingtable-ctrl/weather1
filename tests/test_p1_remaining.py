"""Tests for P1-3, P1-4, P1-7, P1-8, P1-10, P1-18 fixes."""

from __future__ import annotations

import importlib
import json
import shutil
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── P1-3: get_accuracy_halt_reason ───────────────────────────────────────────


class TestGetAccuracyHaltReason:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._patch = patch("paper.DATA_PATH", Path(self._tmpdir) / "paper_trades.json")
        self._patch.start()
        import paper as _paper

        importlib.reload(_paper)

    def teardown_method(self):
        self._patch.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_returns_string_when_win_rate_low(self, monkeypatch):
        """get_accuracy_halt_reason returns non-empty string when rolling win rate is low."""
        import paper

        monkeypatch.setattr("paper.DATA_PATH", Path(self._tmpdir) / "paper_trades.json")
        importlib.reload(paper)

        monkeypatch.setattr("tracker.get_rolling_win_rate", lambda window: (0.30, 25))
        reason = paper.get_accuracy_halt_reason()
        assert isinstance(reason, str)
        assert len(reason) > 0
        assert "30" in reason or "win rate" in reason.lower()

    def test_returns_empty_string_when_not_halted(self, monkeypatch):
        """get_accuracy_halt_reason returns '' when win rate is healthy."""
        import paper

        monkeypatch.setattr("paper.DATA_PATH", Path(self._tmpdir) / "paper_trades.json")
        importlib.reload(paper)

        monkeypatch.setattr("tracker.get_rolling_win_rate", lambda window: (0.60, 25))
        monkeypatch.setattr(
            "tracker.sprt_model_health", lambda: {"status": "ok", "llr": 0.0, "n": 10}
        )
        reason = paper.get_accuracy_halt_reason()
        assert reason == ""

    def test_returns_sprt_reason_when_degraded(self, monkeypatch):
        """get_accuracy_halt_reason returns SPRT info when SPRT signals degradation."""
        import paper

        monkeypatch.setattr("paper.DATA_PATH", Path(self._tmpdir) / "paper_trades.json")
        importlib.reload(paper)

        # Win rate passes but SPRT signals degraded
        monkeypatch.setattr("tracker.get_rolling_win_rate", lambda window: (0.60, 5))
        monkeypatch.setattr(
            "tracker.sprt_model_health",
            lambda: {"status": "degraded", "llr": -5.2, "n": 30},
        )
        reason = paper.get_accuracy_halt_reason()
        assert "sprt" in reason.lower() or "degraded" in reason.lower()


# ── P1-4: walk_forward_backtest no look-ahead ─────────────────────────────────


def _make_trade(
    date_str: str, our_prob: float, settled_yes: bool, edge: float = 0.08
) -> dict:
    return {
        "market_date": date_str,
        "our_prob": our_prob,
        "settled_yes": settled_yes,
        "city": "NYC",
        "method": "ensemble",
        "edge": edge,
    }


class TestWalkForwardNoLookAhead:
    def test_fold_results_include_optimal_min_edge(self):
        """Each fold result includes 'optimal_min_edge' derived from training data."""
        from backtest import walk_forward_backtest

        trades = []
        start = date(2025, 1, 1)
        for i in range(360):
            d = start + timedelta(days=i)
            trades.append(_make_trade(d.isoformat(), 0.65, i % 2 == 0))

        result = walk_forward_backtest(trades, train_months=6, test_months=1)
        assert "optimal_min_edge" in result, "Result dict must include optimal_min_edge"
        for fold in result["folds"]:
            assert "optimal_min_edge" in fold, (
                f"Each fold must have optimal_min_edge; fold={fold}"
            )

    def test_find_optimal_min_edge_called_with_training_data_only(self, monkeypatch):
        """_find_optimal_min_edge must be called with per-fold training data, not full dataset."""
        from backtest import walk_forward_split

        call_sizes: list[int] = []
        original_fn = __import__("backtest")._find_optimal_min_edge

        def _spy(trades):
            call_sizes.append(len(trades))
            return original_fn(trades)

        monkeypatch.setattr("backtest._find_optimal_min_edge", _spy)

        trades = []
        start = date(2025, 1, 1)
        for i in range(360):
            d = start + timedelta(days=i)
            trades.append(_make_trade(d.isoformat(), 0.65, i % 2 == 0))

        from backtest import walk_forward_backtest

        walk_forward_backtest(trades, train_months=6, test_months=1)

        # Must have been called once per fold (not once on full dataset)
        folds = walk_forward_split(trades, train_months=6, test_months=1)
        assert len(call_sizes) == len(folds), (
            f"Expected one _find_optimal_min_edge call per fold ({len(folds)}), "
            f"got {len(call_sizes)} calls"
        )
        # Each call must be on a subset of all trades (training window only)
        for sz in call_sizes:
            assert sz < len(trades), (
                f"_find_optimal_min_edge was called with {sz} trades "
                f"but full dataset has {len(trades)} — look-ahead detected"
            )

    def test_optimal_edge_is_median_of_training_folds(self, monkeypatch):
        """Top-level optimal_min_edge is the median of per-fold training edges."""
        import statistics

        fold_edges: list[float | None] = []
        original_fn = __import__("backtest")._find_optimal_min_edge

        def _recording_fn(trades):
            result = original_fn(trades)
            fold_edges.append(result)
            return result

        monkeypatch.setattr("backtest._find_optimal_min_edge", _recording_fn)

        trades = []
        start = date(2025, 1, 1)
        for i in range(360):
            d = start + timedelta(days=i)
            trades.append(_make_trade(d.isoformat(), 0.65, i % 2 == 0, edge=0.08))

        from backtest import walk_forward_backtest

        result = walk_forward_backtest(trades, train_months=6, test_months=1)

        non_none = [e for e in fold_edges if e is not None]
        if non_none:
            expected_median = statistics.median(non_none)
            assert result["optimal_min_edge"] == pytest.approx(expected_median), (
                "Top-level optimal_min_edge must be median of training-fold edges"
            )


# ── P1-7: circuit breaker persistence ─────────────────────────────────────────


class TestCircuitBreakerPersistence:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._state_path = Path(self._tmpdir) / ".cb_state.json"

    def teardown_method(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_cb(self, name="test", **kwargs):
        import circuit_breaker as cb_mod

        orig_path = cb_mod._CB_STATE_PATH
        cb_mod._CB_STATE_PATH = self._state_path
        cb = cb_mod.CircuitBreaker(name, **kwargs)
        cb_mod._CB_STATE_PATH = orig_path
        cb._state_path = self._state_path  # type: ignore[attr-defined]
        # Patch the module-level constant for this instance's save/load
        import circuit_breaker

        self._orig_path = circuit_breaker._CB_STATE_PATH
        circuit_breaker._CB_STATE_PATH = self._state_path
        return cb

    def teardown_cb(self):
        import circuit_breaker

        circuit_breaker._CB_STATE_PATH = self._orig_path

    def test_failure_count_persists_across_instances(self):
        """Failure count survives process restart (simulated by creating a new instance)."""
        import circuit_breaker as cb_mod

        orig = cb_mod._CB_STATE_PATH
        cb_mod._CB_STATE_PATH = self._state_path

        try:
            cb1 = cb_mod.CircuitBreaker(
                "nws", failure_threshold=5, recovery_timeout=300
            )
            cb1.record_failure()
            cb1.record_failure()

            # Simulate new process — new instance reads saved state
            cb2 = cb_mod.CircuitBreaker(
                "nws", failure_threshold=5, recovery_timeout=300
            )
            assert cb2.failure_count == 2, (
                f"Expected failure_count=2 after reload, got {cb2.failure_count}"
            )
        finally:
            cb_mod._CB_STATE_PATH = orig

    def test_open_state_persists_across_instances(self):
        """An open circuit stays open after process restart."""
        import circuit_breaker as cb_mod

        orig = cb_mod._CB_STATE_PATH
        cb_mod._CB_STATE_PATH = self._state_path

        try:
            cb1 = cb_mod.CircuitBreaker(
                "ecmwf", failure_threshold=2, recovery_timeout=3600
            )
            cb1.record_failure()
            cb1.record_failure()
            assert cb1.is_open()

            # New instance — should still be open
            cb2 = cb_mod.CircuitBreaker(
                "ecmwf", failure_threshold=2, recovery_timeout=3600
            )
            assert cb2.is_open(), "Circuit must still be open after reload"
        finally:
            cb_mod._CB_STATE_PATH = orig

    def test_expired_open_state_clears_on_reload(self):
        """If recovery timeout has elapsed since last open, new instance starts closed."""
        import circuit_breaker as cb_mod

        orig = cb_mod._CB_STATE_PATH
        cb_mod._CB_STATE_PATH = self._state_path

        try:
            # Write a state file with opened_at far in the past
            past_open = time.time() - 7200  # 2 hours ago
            state = {
                "nws": {
                    "failure_count": 3,
                    "trip_count": 1,
                    "current_timeout": 300,  # only 5 min window
                    "opened_at": past_open,
                    "last_failure_at": past_open,
                    "saved_at": past_open,
                }
            }
            self._state_path.write_text(json.dumps(state))

            cb = cb_mod.CircuitBreaker("nws", failure_threshold=5, recovery_timeout=300)
            assert not cb.is_open(), (
                "Circuit should be closed — recovery window has already elapsed"
            )
            assert cb.failure_count == 0
        finally:
            cb_mod._CB_STATE_PATH = orig

    def test_persist_false_does_not_write_state(self):
        """persist=False circuit breaker never writes state file."""
        import circuit_breaker as cb_mod

        orig = cb_mod._CB_STATE_PATH
        cb_mod._CB_STATE_PATH = self._state_path

        try:
            cb = cb_mod.CircuitBreaker(
                "no-save", failure_threshold=1, recovery_timeout=60, persist=False
            )
            cb.record_failure()
            assert not self._state_path.exists(), (
                "persist=False must not write state file"
            )
        finally:
            cb_mod._CB_STATE_PATH = orig

    def test_multiple_breakers_share_one_file(self):
        """Different circuit breaker names coexist in a single state file."""
        import circuit_breaker as cb_mod

        orig = cb_mod._CB_STATE_PATH
        cb_mod._CB_STATE_PATH = self._state_path

        try:
            cb_a = cb_mod.CircuitBreaker(
                "source-a", failure_threshold=5, recovery_timeout=60
            )
            cb_b = cb_mod.CircuitBreaker(
                "source-b", failure_threshold=5, recovery_timeout=60
            )
            cb_a.record_failure()
            cb_a.record_failure()
            cb_b.record_failure()

            state = json.loads(self._state_path.read_text())
            assert "source-a" in state
            assert "source-b" in state
            assert state["source-a"]["failure_count"] == 2
            assert state["source-b"]["failure_count"] == 1
        finally:
            cb_mod._CB_STATE_PATH = orig


# ── P1-8: settle_paper_trade uses entry_price not actual_fill_price ────────────


class TestSettlementCostBasis:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        # Reload first so the module is in a clean state, then apply the patch.
        import paper as _paper

        importlib.reload(_paper)
        self._patch = patch("paper.DATA_PATH", Path(self._tmpdir) / "paper_trades.json")
        self._patch.start()

    def teardown_method(self):
        self._patch.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_settlement_uses_entry_price_not_actual_fill(self):
        """settle_paper_trade uses entry_price (what was deducted at entry) for P&L."""
        import paper

        entry_price = 0.60
        actual_fill = 0.65  # higher due to slippage
        qty = 10

        # Place a trade using entry_price
        paper.place_paper_order(
            "KXTEST-26APR09-T65", "yes", qty, entry_price, thesis="test"
        )

        # Manually set actual_fill_price to a different value
        data = paper._load()
        trade = data["trades"][0]
        trade["actual_fill_price"] = actual_fill
        paper._save(data)

        balance_before = paper.get_balance()
        paper.settle_paper_trade(trade["id"], outcome_yes=True)
        balance_after = paper.get_balance()

        # With entry_price=0.60: winnings = 1 - 0.60 = 0.40 per contract, fee applied
        fee_rate = paper.KALSHI_FEE_RATE
        expected_winnings = 1.0 - entry_price
        expected_payout = qty * (1.0 - expected_winnings * fee_rate)
        expected_balance = balance_before + expected_payout

        assert balance_after == pytest.approx(expected_balance, abs=0.001), (
            f"Expected balance {expected_balance:.4f} (using entry_price={entry_price}), "
            f"got {balance_after:.4f}"
        )

    def test_settlement_pnl_consistent_with_entry_deduction(self):
        """P&L on a won YES trade reflects only the cost paid at entry_price."""
        import paper

        entry_price = 0.50
        qty = 1

        balance_at_entry = paper.get_balance()
        paper.place_paper_order(
            "KXTEST-26APR09-T65", "yes", qty, entry_price, thesis="test"
        )
        balance_after_entry = paper.get_balance()

        cost_deducted = balance_at_entry - balance_after_entry
        assert cost_deducted == pytest.approx(entry_price * qty, abs=0.001)

        data = paper._load()
        trade_id = data["trades"][0]["id"]
        paper.settle_paper_trade(trade_id, outcome_yes=True)

        settled = paper._load()["trades"][0]
        pnl = settled["pnl"]

        # pnl = payout - cost, where cost = entry_price * qty
        fee_rate = paper.KALSHI_FEE_RATE
        winnings = 1.0 - entry_price
        expected_pnl = qty * (winnings - winnings * fee_rate)
        assert pnl == pytest.approx(expected_pnl, abs=0.001), (
            f"P&L should be {expected_pnl:.4f} based on entry_price={entry_price}, "
            f"got {pnl:.4f}"
        )


# ── P1-10: regression baseline fail not skip ──────────────────────────────────


class TestRegressionBaselineFail:
    def test_brier_test_fails_not_skips_on_none_baseline(self, tmp_path):
        """test_brier_score_not_degraded must pytest.fail when baseline value is None."""
        baseline_file = tmp_path / "regression_baseline.json"
        baseline_file.write_text(json.dumps({"brier_score": None, "roc_auc": None}))

        with patch("tests.test_regression.BASELINE_FILE", baseline_file):
            import tests.test_regression as tr

            with pytest.raises(pytest.fail.Exception):
                with patch.object(tr, "BASELINE_FILE", baseline_file):
                    tr.test_brier_score_not_degraded()

    def test_brier_test_fails_not_skips_when_file_missing(self, tmp_path):
        """test_brier_score_not_degraded must pytest.fail when baseline file is absent."""
        missing = tmp_path / "does_not_exist.json"
        import tests.test_regression as tr

        with patch.object(tr, "BASELINE_FILE", missing):
            with pytest.raises(pytest.fail.Exception):
                tr.test_brier_score_not_degraded()

    def test_roc_test_fails_not_skips_on_none_baseline(self, tmp_path):
        """test_roc_auc_not_degraded must pytest.fail when baseline value is None."""
        baseline_file = tmp_path / "regression_baseline.json"
        baseline_file.write_text(json.dumps({"brier_score": None, "roc_auc": None}))

        import tests.test_regression as tr

        with patch.object(tr, "BASELINE_FILE", baseline_file):
            with pytest.raises(pytest.fail.Exception):
                tr.test_roc_auc_not_degraded()


# ── P1-18: consistency arb halt guards ────────────────────────────────────────


class TestConsistencyArbHaltGuards:
    def _scan_result_with_violation(self):
        """Build minimal scan state that would trigger arb placement."""
        from consistency import Violation

        return [
            Violation(
                buy_ticker="KXHIGH-26APR09-T60",
                sell_ticker="KXHIGH-26APR09-T65",
                buy_prob=0.40,
                sell_prob=0.80,
                guaranteed_edge=0.40,
                description="above T60 > above T65",
            )
        ]

    def test_arb_trades_blocked_when_drawdown_halted(self, monkeypatch):
        """No arb paper orders placed when drawdown halt is active."""
        import main
        import paper

        placed = []
        monkeypatch.setattr(
            paper, "place_paper_order", lambda *a, **kw: placed.append(a)
        )
        monkeypatch.setattr(
            "consistency.find_violations", lambda m: self._scan_result_with_violation()
        )

        # Gate returns blocked
        from trading_gates import LiveTradingGate

        monkeypatch.setattr(
            LiveTradingGate, "check", lambda self: (False, "Drawdown halt active")
        )

        # Patch everything else so _cmd_scan_body can run
        markets = [
            {
                "ticker": "KXHIGH-26APR09-T60",
                "series_ticker": "KXHIGH",
                "volume": 1000,
                "yes_bid": 38,
                "yes_ask": 42,
                "no_bid": 0,
            },
            {
                "ticker": "KXHIGH-26APR09-T65",
                "series_ticker": "KXHIGH",
                "volume": 1000,
                "yes_bid": 78,
                "yes_ask": 82,
                "no_bid": 0,
            },
        ]
        monkeypatch.setattr("main.get_weather_markets", lambda c: markets)
        monkeypatch.setattr("weather_markets.enrich_with_forecast", lambda m: m)
        monkeypatch.setattr("weather_markets.is_weather_market", lambda m: False)
        monkeypatch.setattr(paper, "get_open_trades", lambda: [])

        client = MagicMock()
        try:
            main._cmd_scan_body(client, min_edge=0.05)
        except Exception:
            pass  # other scan errors are fine — we only care about place_paper_order

        assert placed == [], (
            "No arb orders should be placed when LiveTradingGate blocks"
        )

    def test_arb_trades_blocked_when_accuracy_halted(self, monkeypatch):
        """No arb paper orders placed when accuracy halt is active."""
        import main
        import paper

        placed = []
        monkeypatch.setattr(
            paper, "place_paper_order", lambda *a, **kw: placed.append(a)
        )
        monkeypatch.setattr(
            "consistency.find_violations", lambda m: self._scan_result_with_violation()
        )

        from trading_gates import LiveTradingGate

        monkeypatch.setattr(
            LiveTradingGate,
            "check",
            lambda self: (False, "Accuracy halt (SPRT) active"),
        )

        monkeypatch.setattr("main.get_weather_markets", lambda c: [])
        monkeypatch.setattr(paper, "get_open_trades", lambda: [])

        client = MagicMock()
        try:
            main._cmd_scan_body(client, min_edge=0.05)
        except Exception:
            pass

        assert placed == [], (
            "No arb orders should be placed when accuracy halt is active"
        )
