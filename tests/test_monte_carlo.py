"""Tests for monte_carlo.py's L-9 nits (batch-37 item 8):
- _DEFAULT_CORRELATIONS must not be mutated cross-call
- n_simulations=0 must not raise
- prob_positive defaults must be consistent across simulate_portfolio's
  degenerate-input early returns
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


def _trade(ticker: str, city: str) -> dict:
    return {
        "ticker": ticker,
        "city": city,
        "side": "yes",
        "entry_price": 0.5,
        "cost": 5.0,
        "quantity": 1,
        "entry_prob": 0.6,
        "target_date": "2099-01-01",
    }


class TestDefaultCorrelationsNotMutatedCrossCall:
    def test_seed_dict_unchanged_after_a_call_with_dynamic_override(self):
        """L-9: simulate_portfolio must not permanently overwrite the
        module-level _DEFAULT_CORRELATIONS seed with a call's dynamic
        estimate -- a later call (or test) must see the same static seed,
        not whatever the previous call's live data happened to compute.

        Mutation-tested: reverting the fix (writing back to
        _DEFAULT_CORRELATIONS directly instead of a local copy) makes this
        fail (the seed's NYC/Boston entry becomes 0.99) -- confirmed via
        Edit revert.
        """
        import monte_carlo

        original_seed = dict(monte_carlo._DEFAULT_CORRELATIONS)
        assert monte_carlo._DEFAULT_CORRELATIONS[("NYC", "Boston")] == 0.85

        trades = [_trade("T1", "NYC"), _trade("T2", "Boston")]
        dynamic = {
            ("NYC", "Boston"): 0.99,
            ("Chicago", "Denver"): 0.99,
            ("LA", "Phoenix"): 0.99,
        }
        with (
            patch("paper.get_balance", return_value=1000.0),
            patch("tracker.get_recent_city_correlations", return_value=dynamic),
        ):
            result = monte_carlo.simulate_portfolio(trades, n_simulations=20)

        assert "median_pnl" in result
        assert monte_carlo._DEFAULT_CORRELATIONS == original_seed, (
            "the module-level seed dict must be unchanged after the call -- "
            f"got {monte_carlo._DEFAULT_CORRELATIONS[('NYC', 'Boston')]}"
        )

    def test_dynamic_override_still_applied_within_the_same_call(self):
        """Positive control: the local-copy fix must still actually APPLY
        the dynamic override for the call it was computed in -- proves the
        fix didn't just silently stop applying overrides at all."""
        import monte_carlo

        trades = [_trade("T1", "NYC"), _trade("T2", "Boston")]
        dynamic = {
            ("NYC", "Boston"): 0.99,
            ("Chicago", "Denver"): 0.99,
            ("LA", "Phoenix"): 0.99,
        }
        captured = {}
        real_cholesky = monte_carlo._cholesky

        def _spy_cholesky(mat):
            captured["mat"] = mat
            return real_cholesky(mat)

        with (
            patch("paper.get_balance", return_value=1000.0),
            patch("tracker.get_recent_city_correlations", return_value=dynamic),
            patch(
                "paper.position_correlation_matrix",
                return_value=[[1.0, 0.0], [0.0, 1.0]],
            ),
            patch("monte_carlo._cholesky", side_effect=_spy_cholesky),
        ):
            monte_carlo.simulate_portfolio(trades, n_simulations=20)

        assert captured["mat"][0][1] == 0.99, (
            "dynamic correlation override was not applied to the matrix "
            "used for this call"
        )


class TestNSimulationsZero:
    def test_n_simulations_zero_does_not_raise(self):
        """L-9: n_simulations=0 used to IndexError on an empty sim_pnls list."""
        import monte_carlo

        trades = [_trade("T1", "NYC")]
        with patch("paper.get_balance", return_value=1000.0):
            result = monte_carlo.simulate_portfolio(trades, n_simulations=0)

        assert result["n_simulations"] == 0
        assert result["median_pnl"] == 0.0
        assert result["prob_positive"] == 0.0


class TestProbPositiveDefaultConsistency:
    def test_no_open_trades_matches_all_past_date_default(self):
        """L-9: the no-open-trades early return (prob_positive=0.5) and the
        all-trades-past-date early return (prob_positive=0.0) both
        represent zero simulated forward risk (flat 0.0 P&L every sim) --
        must use the same convention. The real simulation loop's own rule
        (`p > 0`) treats a flat 0.0 as NOT positive, so 0.0 is correct for
        both.
        """
        import monte_carlo

        with patch("paper.get_balance", return_value=1000.0):
            no_trades_result = monte_carlo.simulate_portfolio([])

            past_date_trade = _trade("T1", "NYC")
            past_date_trade["target_date"] = "2000-01-01"
            past_date_trade["close_time"] = None
            all_past_result = monte_carlo.simulate_portfolio([past_date_trade])

        assert no_trades_result["prob_positive"] == all_past_result["prob_positive"]
        assert no_trades_result["prob_positive"] == 0.0
