---
type: community
cohesion: 0.14
members: 18
---

# Community 188

**Cohesion:** 0.14 - loosely connected
**Members:** 18 nodes

## Members
- [[dot-test_cholesky_not_positive_definite_returns_none()]] - code - tests/test_paper.py
- [[dot-test_portfolio_var_default_n_simulations_is_5000()]] - code - tests/test_phase3_batch_d.py
- [[dot-test_repair_psd_called_in_simulate_portfolio_source()]] - code - tests/test_phase3_batch_d.py
- [[dot-test_repair_psd_identity_unchanged()]] - code - tests/test_phase3_batch_d.py
- [[dot-test_repair_psd_makes_cholesky_succeed()]] - code - tests/test_phase3_batch_d.py
- [[dot-test_repair_psd_renormalizes_to_unit_diagonal()]] - code - tests/test_phase3_batch_d.py
- [[dot-test_simulate_portfolio_succeeds_with_near_singular_matrix()]] - code - tests/test_phase3_batch_d.py
- [[A near-singular matrix that fails Cholesky should pass after _repair_psd.]] - rationale - tests/test_phase3_batch_d.py
- [[Identity matrix is already PD — repair should return immediately.]] - rationale - tests/test_phase3_batch_d.py
- [[Near-singular correlation matrix completes via PSD repair, not hard crash.]] - rationale - tests/test_phase3_batch_d.py
- [[Nearest-PSD repair via diagonal (ridge) loading add a minimal shift to every…]] - rationale - monte_carlo.py
- [[P3-3 portfolio_var must default to 5000 simulations.]] - rationale - tests/test_phase3_batch_d.py
- [[Pure-Python lower-triangular Cholesky decomposition. Returns L such that L @…]] - rationale - monte_carlo.py
- [[TestPortfolioVarSampleCount]] - code - tests/test_phase3_batch_d.py
- [[The ridge-loading repair must renormalize back to a unit-diagonal correlation…]] - rationale - tests/test_phase3_batch_d.py
- [[_cholesky()]] - code - monte_carlo.py
- [[_repair_psd()]] - code - monte_carlo.py
- [[simulate_portfolio source must reference _repair_psd (structural check).]] - rationale - tests/test_phase3_batch_d.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_188
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 303]]
- 3 edges to [[_COMMUNITY_Community 4]]
- 3 edges to [[_COMMUNITY_Community 209]]
- 2 edges to [[_COMMUNITY_Community 148]]
- 1 edge to [[_COMMUNITY_Community 21]]
- 1 edge to [[_COMMUNITY_Community 335]]

## Top bridge nodes
- [[_cholesky()]] - degree 12, connects to 5 communities
- [[_repair_psd()]] - degree 8, connects to 3 communities
- [[TestPortfolioVarSampleCount]] - degree 8, connects to 1 community
- [[dot-test_repair_psd_called_in_simulate_portfolio_source()]] - degree 3, connects to 1 community
- [[dot-test_simulate_portfolio_succeeds_with_near_singular_matrix()]] - degree 3, connects to 1 community