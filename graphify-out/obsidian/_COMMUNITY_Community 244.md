---
type: community
cohesion: 0.14
members: 14
---

# Community 244

**Cohesion:** 0.14 - loosely connected
**Members:** 14 nodes

## Members
- [[F8 regression the check used to read os.getenv(MAX_DAILY_SPEND, 0)…]] - rationale - tests/test_spend_validation.py
- [[F8 _check_spend_cap_vs_balance() itself has no internal guard (a…]] - rationale - tests/test_spend_validation.py
- [[No warning when MAX_DAILY_SPEND is 0 (disabled).]] - rationale - tests/test_spend_validation.py
- [[No warning when MAX_DAILY_SPEND is below current balance.]] - rationale - tests/test_spend_validation.py
- [[Tests for the MAX_DAILY_SPEND vs balance validation check in cron.py (re-…]] - rationale - tests/test_spend_validation.py
- [[Warning logged when MAX_DAILY_SPEND exceeds current paper balance.]] - rationale - tests/test_spend_validation.py
- [[_check_spend_cap_vs_balance()_1]] - code - main.py
- [[alerts.py_2]] - code - alerts.py
- [[test_balance_fetch_failure_does_not_crash_full_cron_cycle()]] - code - tests/test_spend_validation.py
- [[test_no_warning_when_spend_cap_below_balance()]] - code - tests/test_spend_validation.py
- [[test_no_warning_when_spend_cap_zero()]] - code - tests/test_spend_validation.py
- [[test_spend_cap_warning_logged_when_exceeds_balance()]] - code - tests/test_spend_validation.py
- [[test_spend_validation.py]] - code - tests/test_spend_validation.py
- [[test_uses_real_utils_default_not_a_second_zero_default()]] - code - tests/test_spend_validation.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_244
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 40]]
- 1 edge to [[_COMMUNITY_Circuit Breaker & Session Retry Infrastructure]]
- 1 edge to [[_COMMUNITY_Community 228]]

## Top bridge nodes
- [[test_spend_validation.py]] - degree 12, connects to 2 communities
- [[alerts.py_2]] - degree 2, connects to 1 community
- [[_check_spend_cap_vs_balance()_1]] - degree 2, connects to 1 community