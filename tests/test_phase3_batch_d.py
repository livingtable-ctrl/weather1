"""Phase 3 Batch D regression tests: P3-3, P3-18, P3-22, P3-23."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── P3-3: portfolio_var uses 5000 simulations + PSD repair ───────────────────


class TestPortfolioVarSampleCount:
    """P3-3: portfolio_var must default to 5000 simulations."""

    def test_portfolio_var_default_n_simulations_is_5000(self):
        import inspect

        from monte_carlo import portfolio_var

        sig = inspect.signature(portfolio_var)
        assert sig.parameters["n_simulations"].default == 5000

    def test_repair_psd_makes_cholesky_succeed(self):
        """A near-singular matrix that fails Cholesky should pass after _repair_psd."""
        from monte_carlo import _cholesky, _repair_psd

        # 2×2 near-singular: eigenvalue ~0
        mat = [[1.0, 1.0 - 1e-12], [1.0 - 1e-12, 1.0]]
        assert _cholesky(mat) is None  # fails raw
        repaired = _repair_psd(mat)
        assert _cholesky(repaired) is not None  # succeeds after repair

    def test_repair_psd_identity_unchanged(self):
        """Identity matrix is already PD — repair should return immediately."""
        from monte_carlo import _cholesky, _repair_psd

        mat = [[1.0, 0.0], [0.0, 1.0]]
        repaired = _repair_psd(mat)
        assert _cholesky(repaired) is not None

    def test_repair_psd_called_in_simulate_portfolio_source(self):
        """simulate_portfolio source must reference _repair_psd (structural check)."""
        import inspect

        from monte_carlo import simulate_portfolio

        src = inspect.getsource(simulate_portfolio)
        assert "_repair_psd" in src, (
            "_repair_psd not called in simulate_portfolio (P3-3)"
        )

    def test_simulate_portfolio_succeeds_with_near_singular_matrix(self):
        """Near-singular correlation matrix completes via PSD repair, not hard crash."""
        from monte_carlo import simulate_portfolio

        trades = [
            {
                "ticker": f"T{i}",
                "city": "NYC",
                "side": "yes",
                "entry_price": 0.5,
                "cost": 5.0,
                "quantity": 1,
                "entry_prob": 0.6,
                "target_date": "2099-01-01",
            }
            for i in range(2)
        ]
        # near-singular 2×2: almost rank-1
        near_singular = [[1.0, 1.0 - 1e-12], [1.0 - 1e-12, 1.0]]
        with (
            patch("paper.get_balance", return_value=1000.0),
            patch("paper.position_correlation_matrix", return_value=near_singular),
        ):
            result = simulate_portfolio(trades, n_simulations=20)
        assert "median_pnl" in result


# ── P3-18: stratified_train_test_split removed from backtest ─────────────────


class TestStratifiedSplitRemoved:
    """P3-18: stratified_train_test_split must not exist in backtest module."""

    def test_function_not_importable(self):
        import backtest

        assert not hasattr(backtest, "stratified_train_test_split"), (
            "stratified_train_test_split is dead code and must be removed (P3-18)"
        )

    def test_backtest_still_importable(self):
        import backtest  # noqa: F401


# ── P3-22: feature_importance log pruning ────────────────────────────────────


class TestFeatureImportancePruning:
    """P3-22: prune_feature_log must keep at most _MAX_LOG_LINES entries."""

    def test_max_log_lines_constant_is_50000(self):
        from feature_importance import _MAX_LOG_LINES

        assert _MAX_LOG_LINES == 50_000

    def test_prune_feature_log_trims_oversized_file(self, tmp_path, monkeypatch):
        import feature_importance

        log_path = tmp_path / "feature_importance.jsonl"
        lines = [f'{{"ts": {i}, "ticker": "T{i}"}}\n' for i in range(200)]
        log_path.write_text("".join(lines), encoding="utf-8")

        monkeypatch.setattr(feature_importance, "_FEATURE_LOG_PATH", log_path)
        pruned = feature_importance.prune_feature_log(max_lines=100)

        assert pruned == 100
        kept = log_path.read_text(encoding="utf-8").splitlines()
        assert len(kept) == 100
        # Kept most recent: lines 100–199
        assert '"ts": 100' in kept[0]

    def test_prune_feature_log_no_op_when_under_limit(self, tmp_path, monkeypatch):
        import feature_importance

        log_path = tmp_path / "feature_importance.jsonl"
        log_path.write_text('{"ts": 1}\n{"ts": 2}\n', encoding="utf-8")

        monkeypatch.setattr(feature_importance, "_FEATURE_LOG_PATH", log_path)
        pruned = feature_importance.prune_feature_log(max_lines=1000)
        assert pruned == 0

    def test_prune_feature_log_missing_file_returns_zero(self, tmp_path, monkeypatch):
        import feature_importance

        monkeypatch.setattr(
            feature_importance,
            "_FEATURE_LOG_PATH",
            tmp_path / "nonexistent.jsonl",
        )
        pruned = feature_importance.prune_feature_log()
        assert pruned == 0

    def test_prune_called_from_cron_on_monday(self):
        """cron.py must call prune_feature_log() in the Monday weekly sweep."""
        import inspect

        import cron

        src = inspect.getsource(cron._cmd_cron_body)
        assert "prune_feature_log" in src, (
            "prune_feature_log not called in cron weekly sweep (P3-22)"
        )


# ── P3-23: pnl_distribution gated behind include_distribution flag ───────────


class TestPnlDistributionGated:
    """P3-23: pnl_distribution must only appear in output when include_distribution=True."""

    def _run_sim(self, include: bool) -> dict:
        from monte_carlo import simulate_portfolio

        trades = [
            {
                "ticker": "T1",
                "city": "NYC",
                "side": "yes",
                "entry_price": 0.5,
                "cost": 5.0,
                "quantity": 10,
                "entry_prob": 0.6,
                "target_date": "2099-01-01",
            }
        ]
        with (
            patch("paper.get_balance", return_value=1000.0),
            patch("paper.position_correlation_matrix", return_value=[[1.0]]),
        ):
            return simulate_portfolio(
                trades, n_simulations=50, include_distribution=include
            )

    def test_distribution_absent_by_default(self):
        result = self._run_sim(include=False)
        assert "pnl_distribution" not in result

    def test_distribution_present_when_requested(self):
        result = self._run_sim(include=True)
        assert "pnl_distribution" in result
        assert isinstance(result["pnl_distribution"], list)
        assert len(result["pnl_distribution"]) == 50

    def test_core_keys_always_present(self):
        result = self._run_sim(include=False)
        for key in (
            "median_pnl",
            "p5_pnl",
            "prob_positive",
            "prob_ruin",
            "n_simulations",
        ):
            assert key in result

    def test_simulate_portfolio_signature_has_include_distribution(self):
        import inspect

        from monte_carlo import simulate_portfolio

        sig = inspect.signature(simulate_portfolio)
        assert "include_distribution" in sig.parameters
        assert sig.parameters["include_distribution"].default is False
