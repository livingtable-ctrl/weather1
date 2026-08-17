---
type: community
cohesion: 0.16
members: 22
---

# Community 146

**Cohesion:** 0.16 - loosely connected
**Members:** 22 nodes

## Members
- [[A sampled market whose bypass-resolved method is currently retired must be…]] - rationale - tests/test_retirement_probation.py
- [[If the bypass-resolved method for a sampled market isn't in the retired set, it…]] - rationale - tests/test_retirement_probation.py
- [[Isolate the probation state file and the retired-strategiespins files this…]] - rationale - tests/test_retirement_probation.py
- [[No currently-retired method - must not even fetch markets.]] - rationale - tests/test_retirement_probation.py
- [[None means not enough fresh evidence yet -- must not unretire.]] - rationale - tests/test_retirement_probation.py
- [[Once brier_score_probation_rolling() reports a recovered score, the method must…]] - rationale - tests/test_retirement_probation.py
- [[Tests for check_retirement_probation() — once-per-day generation of fresh,…]] - rationale - tests/test_retirement_probation.py
- [[_market()]] - code - tests/test_retirement_probation.py
- [[_mock_client()_2]] - code - tests/test_retirement_probation.py
- [[_today()_2]] - code - tests/test_retirement_probation.py
- [[fixture_2]] - code
- [[test_auto_unretires_when_probation_brier_clears_threshold()]] - code - tests/test_retirement_probation.py
- [[test_does_not_unretire_when_insufficient_probation_samples()]] - code - tests/test_retirement_probation.py
- [[test_does_not_unretire_when_probation_brier_still_bad()]] - code - tests/test_retirement_probation.py
- [[test_gated_to_run_once_per_day()_1]] - code - tests/test_retirement_probation.py
- [[test_logs_probation_prediction_for_retired_method()]] - code - tests/test_retirement_probation.py
- [[test_never_raises_on_broken_state_file()]] - code - tests/test_retirement_probation.py
- [[test_noop_when_nothing_retired()]] - code - tests/test_retirement_probation.py
- [[test_retirement_probation.py]] - code - tests/test_retirement_probation.py
- [[test_runs_again_on_a_new_day()]] - code - tests/test_retirement_probation.py
- [[test_skips_market_whose_method_is_not_retired()]] - code - tests/test_retirement_probation.py
- [[tmp_retirement_state()]] - code - tests/test_retirement_probation.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_146
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 3]]

## Top bridge nodes
- [[test_retirement_probation.py]] - degree 20, connects to 2 communities