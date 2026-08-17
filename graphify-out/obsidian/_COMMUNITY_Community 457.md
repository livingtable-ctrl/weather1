---
type: community
cohesion: 0.32
members: 8
---

# Community 457

**Cohesion:** 0.32 - loosely connected
**Members:** 8 nodes

## Members
- [[dot-_run_fetch()]] - code - tests/test_backtest_stratified.py
- [[dot-test_ensemble_centred_near_forecast()]] - code - tests/test_backtest_stratified.py
- [[dot-test_ensemble_not_centred_on_actual()]] - code - tests/test_backtest_stratified.py
- [[Ensemble mean must NOT be within 1°F of the actual temperature (exact_val).…]] - rationale - tests/test_backtest_stratified.py
- [[Ensemble mean must be within 5°F of the surrounding-day average (proxy…]] - rationale - tests/test_backtest_stratified.py
- [[L6-A synthetic ensemble must be centred on a forecast, not the actual outcome.]] - rationale - tests/test_backtest_stratified.py
- [[Monkeypatch requests.get so fetch_archive_temps uses controlled data, then…]] - rationale - tests/test_backtest_stratified.py
- [[TestFetchArchiveTempsEnsembleCenter]] - code - tests/test_backtest_stratified.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_457
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 8]]

## Top bridge nodes
- [[TestFetchArchiveTempsEnsembleCenter]] - degree 5, connects to 1 community
- [[dot-_run_fetch()]] - degree 5, connects to 1 community