"""Phase 2 Batch F regression tests: P2-1 (monte_carlo correlation_applied flag)."""

from __future__ import annotations

import sys
from unittest.mock import patch

sys.path.insert(0, str(__file__[: __file__.rfind("tests")]))

_OPEN_TRADE = {
    "ticker": "KXHIGHNY-01JAN26-T70",
    "side": "yes",
    "entry_price": 0.55,
    "cost": 5.50,
    "quantity": 10,
    "city": "NYC",
    "target_date": "2099-01-01",  # far future so skip-past-date logic doesn't fire
    "entry_prob": 0.60,
}


def _make_trade(**overrides):
    t = dict(_OPEN_TRADE)
    t.update(overrides)
    return t


class TestCorrelationAppliedFlag:
    """P2-1: correlation_applied must reflect whether Cholesky actually succeeded."""

    def _run(self, trades, chol_result):
        import monte_carlo

        with patch("paper.get_balance", return_value=500.0):
            with patch.object(monte_carlo, "_cholesky", return_value=chol_result):
                with patch(
                    "paper.position_correlation_matrix",
                    return_value=[[1.0] * len(trades) for _ in trades],
                ):
                    return monte_carlo.simulate_portfolio(trades, n_simulations=50)

    def test_correlation_applied_true_when_cholesky_succeeds(self):
        """When Cholesky succeeds and trades have cities, correlation_applied must be True."""
        trades = [_make_trade(city="NYC"), _make_trade(city="Boston")]
        n = len(trades)
        L = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
        result = self._run(trades, chol_result=L)
        assert result["correlation_applied"] is True, (
            "Cholesky succeeded with city trades — correlation_applied must be True"
        )

    def test_correlation_applied_false_when_cholesky_fails(self):
        """When Cholesky returns None (not positive-definite), correlation_applied must be False."""
        trades = [_make_trade(city="NYC"), _make_trade(city="Boston")]
        result = self._run(trades, chol_result=None)
        assert result["correlation_applied"] is False, (
            "Cholesky failed — independent draws used, correlation_applied must be False"
        )

    def test_correlation_applied_false_when_no_city(self):
        """Trades with no city: correlation_applied must be False even if Cholesky would succeed."""
        trades = [_make_trade(city=""), _make_trade(city="")]
        n = len(trades)
        L = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
        result = self._run(trades, chol_result=L)
        assert result["correlation_applied"] is False, (
            "No cities — correlation logic is a no-op, correlation_applied must be False"
        )

    def test_correlation_applied_false_when_no_trades(self):
        """Empty trade list must return correlation_applied=False (or absent)."""
        import monte_carlo

        with patch("paper.get_balance", return_value=500.0):
            result = monte_carlo.simulate_portfolio([], n_simulations=50)
        # Empty portfolio returns early — flag absent or False
        assert not result.get("correlation_applied", False)

    def test_cholesky_failure_logs_warning(self, caplog):
        """A non-positive-definite matrix must log a WARNING, not fail silently."""
        import logging

        import monte_carlo

        trades = [_make_trade(city="NYC"), _make_trade(city="Boston")]
        with caplog.at_level(logging.WARNING, logger="monte_carlo"):
            with patch("paper.get_balance", return_value=500.0):
                with patch.object(monte_carlo, "_cholesky", return_value=None):
                    with patch(
                        "paper.position_correlation_matrix",
                        return_value=[[1.0, 0.0], [0.0, 1.0]],
                    ):
                        monte_carlo.simulate_portfolio(trades, n_simulations=50)

        assert any(
            "independent" in r.message.lower()
            or "positive-definite" in r.message.lower()
            for r in caplog.records
            if r.levelno >= logging.WARNING
        ), "A warning must be logged when Cholesky fails and independent draws are used"


class TestCorrelationMatrixIntegrity:
    """P2-1: Cholesky decomposition produces correct L @ L.T == mat."""

    def test_cholesky_identity(self):
        import monte_carlo

        mat = [[1.0, 0.0], [0.0, 1.0]]
        L = monte_carlo._cholesky(mat)
        assert L is not None
        # L @ L.T must equal mat
        n = len(mat)
        for i in range(n):
            for j in range(n):
                reconstructed = sum(L[i][k] * L[j][k] for k in range(min(i, j) + 1))
                assert abs(reconstructed - mat[i][j]) < 1e-9

    def test_cholesky_correlated(self):
        import monte_carlo

        rho = 0.7
        mat = [[1.0, rho], [rho, 1.0]]
        L = monte_carlo._cholesky(mat)
        assert L is not None
        n = len(mat)
        for i in range(n):
            for j in range(n):
                reconstructed = sum(L[i][k] * L[j][k] for k in range(min(i, j) + 1))
                assert abs(reconstructed - mat[i][j]) < 1e-9

    def test_cholesky_returns_none_for_non_pd(self):
        import monte_carlo

        # rho=1.0 → singular matrix
        mat = [[1.0, 1.0], [1.0, 1.0]]
        assert monte_carlo._cholesky(mat) is None

    def test_simulate_result_has_required_keys(self):
        """simulate_portfolio must always return correlation_applied in the result."""
        import monte_carlo

        with patch("paper.get_balance", return_value=500.0):
            with patch(
                "paper.position_correlation_matrix",
                return_value=[[1.0]],
            ):
                result = monte_carlo.simulate_portfolio(
                    [_make_trade()], n_simulations=20
                )

        assert "correlation_applied" in result, (
            "simulate_portfolio result must always include 'correlation_applied'"
        )
