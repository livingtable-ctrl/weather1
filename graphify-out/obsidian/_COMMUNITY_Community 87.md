---
type: community
cohesion: 0.09
members: 29
---

# Community 87

**Cohesion:** 0.09 - loosely connected
**Members:** 29 nodes

## Members
- [[dot-test_cholesky_correlated()_1]] - code - tests/test_paper.py
- [[dot-test_cholesky_identity()_1]] - code - tests/test_paper.py
- [[dot-test_cholesky_not_positive_definite_returns_none()]] - code - tests/test_paper.py
- [[dot-test_past_date_only_portfolio_returns_empty_result()]] - code - tests/test_paper.py
- [[dot-test_past_date_trade_excluded_from_simulation()]] - code - tests/test_paper.py
- [[dot-test_portfolio_var_default_n_simulations_is_5000()]] - code - tests/test_phase3_batch_d.py
- [[dot-test_repair_psd_called_in_simulate_portfolio_source()]] - code - tests/test_phase3_batch_d.py
- [[dot-test_repair_psd_identity_unchanged()]] - code - tests/test_phase3_batch_d.py
- [[dot-test_repair_psd_makes_cholesky_succeed()]] - code - tests/test_phase3_batch_d.py
- [[dot-test_repair_psd_renormalizes_to_unit_diagonal()]] - code - tests/test_phase3_batch_d.py
- [[dot-test_simulate_portfolio_correlated_widens_distribution()]] - code - tests/test_paper.py
- [[dot-test_simulate_portfolio_succeeds_with_near_singular_matrix()]] - code - tests/test_phase3_batch_d.py
- [[dot-test_unparseable_target_date_falls_back_to_string_compare_no_crash()]] - code - tests/test_paper.py
- [[A near-singular matrix that fails Cholesky should pass after _repair_psd.]] - rationale - tests/test_phase3_batch_d.py
- [[All-stale portfolio skips every trade and returns the zero-position result.]] - rationale - tests/test_paper.py
- [[Bug A fix (backlog.txt RAIN  SNOW  HURRICANE MARKETS Step 2) a genuinely…]] - rationale - tests/test_paper.py
- [[Correlated positions (same citydate) should widen P&L distribution vs…]] - rationale - tests/test_paper.py
- [[Identity matrix is already PD — repair should return immediately.]] - rationale - tests/test_phase3_batch_d.py
- [[Near-singular correlation matrix completes via PSD repair, not hard crash.]] - rationale - tests/test_phase3_batch_d.py
- [[Nearest-PSD repair via diagonal (ridge) loading add a minimal shift to every…]] - rationale - monte_carlo.py
- [[P3-3 portfolio_var must default to 5000 simulations.]] - rationale - tests/test_phase3_batch_d.py
- [[Pure-Python lower-triangular Cholesky decomposition. Returns L such that L @…]] - rationale - monte_carlo.py
- [[TestMonteCarloCholesky]] - code - tests/test_paper.py
- [[TestPortfolioVarSampleCount]] - code - tests/test_phase3_batch_d.py
- [[The ridge-loading repair must renormalize back to a unit-diagonal correlation…]] - rationale - tests/test_phase3_batch_d.py
- [[Trades whose target_date is in the past are skipped — no forward risk.]] - rationale - tests/test_paper.py
- [[_cholesky()]] - code - monte_carlo.py
- [[_repair_psd()]] - code - monte_carlo.py
- [[simulate_portfolio source must reference _repair_psd (structural check).]] - rationale - tests/test_phase3_batch_d.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_87
SORT file.name ASC
```

## Connections to other communities
- 8 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 3 edges to [[_COMMUNITY_Community 246]]
- 2 edges to [[_COMMUNITY_Community 56]]
- 2 edges to [[_COMMUNITY_Community 181]]
- 2 edges to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 1 edge to [[_COMMUNITY_Community 45]]
- 1 edge to [[_COMMUNITY_Community 328]]

## Top bridge nodes
- [[_cholesky()]] - degree 12, connects to 4 communities
- [[_repair_psd()]] - degree 8, connects to 3 communities
- [[TestMonteCarloCholesky]] - degree 9, connects to 2 communities
- [[dot-test_past_date_only_portfolio_returns_empty_result()]] - degree 4, connects to 2 communities
- [[dot-test_past_date_trade_excluded_from_simulation()]] - degree 4, connects to 2 communities