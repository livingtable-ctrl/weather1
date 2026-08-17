---
type: community
cohesion: 0.12
members: 21
---

# Community 155

**Cohesion:** 0.12 - loosely connected
**Members:** 21 nodes

## Members
- [[dot-_run()]] - code - tests/test_phase2_batch_f.py
- [[dot-test_cholesky_correlated()]] - code - tests/test_phase2_batch_f.py
- [[dot-test_cholesky_failure_logs_warning()]] - code - tests/test_phase2_batch_f.py
- [[dot-test_cholesky_identity()]] - code - tests/test_phase2_batch_f.py
- [[dot-test_cholesky_returns_none_for_non_pd()]] - code - tests/test_phase2_batch_f.py
- [[dot-test_correlation_applied_false_when_cholesky_fails()]] - code - tests/test_phase2_batch_f.py
- [[dot-test_correlation_applied_false_when_no_city()]] - code - tests/test_phase2_batch_f.py
- [[dot-test_correlation_applied_false_when_no_trades()]] - code - tests/test_phase2_batch_f.py
- [[dot-test_correlation_applied_true_when_cholesky_succeeds()]] - code - tests/test_phase2_batch_f.py
- [[dot-test_simulate_result_has_required_keys()]] - code - tests/test_phase2_batch_f.py
- [[A non-positive-definite matrix must log a WARNING, not fail silently.]] - rationale - tests/test_phase2_batch_f.py
- [[Empty trade list must return correlation_applied=False (or absent).]] - rationale - tests/test_phase2_batch_f.py
- [[P2-1 Cholesky decomposition produces correct L @ L.T == mat.]] - rationale - tests/test_phase2_batch_f.py
- [[P2-1 correlation_applied must reflect whether Cholesky actually succeeded.]] - rationale - tests/test_phase2_batch_f.py
- [[TestCorrelationAppliedFlag]] - code - tests/test_phase2_batch_f.py
- [[TestCorrelationMatrixIntegrity]] - code - tests/test_phase2_batch_f.py
- [[Trades with no city correlation_applied must be False even if Cholesky would…]] - rationale - tests/test_phase2_batch_f.py
- [[When Cholesky returns None (not positive-definite), correlation_applied must be…]] - rationale - tests/test_phase2_batch_f.py
- [[When Cholesky succeeds and trades have cities, correlation_applied must be True.]] - rationale - tests/test_phase2_batch_f.py
- [[_make_trade()_2]] - code - tests/test_phase2_batch_f.py
- [[simulate_portfolio must always return correlation_applied in the result.]] - rationale - tests/test_phase2_batch_f.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_155
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[TestCorrelationAppliedFlag]] - degree 8, connects to 1 community
- [[_make_trade()_2]] - degree 6, connects to 1 community
- [[TestCorrelationMatrixIntegrity]] - degree 6, connects to 1 community