---
type: community
cohesion: 0.07
members: 32
---

# Community 71

**Cohesion:** 0.07 - loosely connected
**Members:** 32 nodes

## Members
- [[F8 regression the check used to read os.getenv(MAX_DAILY_SPEND, 0)…]] - rationale - tests/test_spend_validation.py
- [[F8 _check_spend_cap_vs_balance() itself has no internal guard (a…]] - rationale - tests/test_spend_validation.py
- [[If _get_consensus_probs raises, it must be logged — not silently defaulted.]] - rationale - tests/test_silent_failures.py
- [[If climatological_prob raises, the failure must be logged.]] - rationale - tests/test_silent_failures.py
- [[If log_api_request raises inside _request_with_retry, it must be logged.]] - rationale - tests/test_silent_failures.py
- [[If log_price_improvement raises after a paper order, it must be logged.]] - rationale - tests/test_silent_failures.py
- [[If nws_prob raises, the failure must be logged.]] - rationale - tests/test_silent_failures.py
- [[Minimal enriched dict that passes all analyze_trade gates.]] - rationale - tests/test_silent_failures.py
- [[No warning when MAX_DAILY_SPEND is 0 (disabled).]] - rationale - tests/test_spend_validation.py
- [[No warning when MAX_DAILY_SPEND is below current balance.]] - rationale - tests/test_spend_validation.py
- [[Paper Trading Ledger Module]] - code - paper.py
- [[Return a stack of patches that let analyze_trade reach the risky sections.]] - rationale - tests/test_silent_failures.py
- [[STARTING_BALANCE]] - code - paper.py
- [[Tests for P0.4 — Silent failure elimination. Every failure in the trading path…]] - rationale - tests/test_silent_failures.py
- [[Tests for the MAX_DAILY_SPEND vs balance validation check in cron.py (re-…]] - rationale - tests/test_spend_validation.py
- [[Warning logged when MAX_DAILY_SPEND exceeds current paper balance.]] - rationale - tests/test_spend_validation.py
- [[_DEFAULT_CORRELATIONS Dict]] - code - monte_carlo.py
- [[_make_enriched()_2]] - code - tests/test_silent_failures.py
- [[_patch_analyze_prereqs()]] - code - tests/test_silent_failures.py
- [[alerts.py_1]] - code - alerts.py
- [[test_analyze_trade_logs_climatological_failure()]] - code - tests/test_silent_failures.py
- [[test_analyze_trade_logs_consensus_failure()]] - code - tests/test_silent_failures.py
- [[test_analyze_trade_logs_nws_prob_failure()]] - code - tests/test_silent_failures.py
- [[test_balance_fetch_failure_does_not_crash_full_cron_cycle()]] - code - tests/test_spend_validation.py
- [[test_kalshi_client_api_log_failure_is_logged()]] - code - tests/test_silent_failures.py
- [[test_no_warning_when_spend_cap_below_balance()]] - code - tests/test_spend_validation.py
- [[test_no_warning_when_spend_cap_zero()]] - code - tests/test_spend_validation.py
- [[test_paper_price_improvement_log_failure_is_logged()]] - code - tests/test_silent_failures.py
- [[test_silent_failures.py]] - code - tests/test_silent_failures.py
- [[test_spend_cap_warning_logged_when_exceeds_balance()]] - code - tests/test_spend_validation.py
- [[test_spend_validation.py]] - code - tests/test_spend_validation.py
- [[test_uses_real_utils_default_not_a_second_zero_default()]] - code - tests/test_spend_validation.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_71
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 5]]
- 4 edges to [[_COMMUNITY_Community 4]]
- 4 edges to [[_COMMUNITY_Community 6]]
- 1 edge to [[_COMMUNITY_Community 75]]
- 1 edge to [[_COMMUNITY_Community 289]]
- 1 edge to [[_COMMUNITY_Community 41]]
- 1 edge to [[_COMMUNITY_Community 7]]
- 1 edge to [[_COMMUNITY_Community 8]]
- 1 edge to [[_COMMUNITY_Community 85]]
- 1 edge to [[_COMMUNITY_Community 86]]
- 1 edge to [[_COMMUNITY_Community 57]]

## Top bridge nodes
- [[Paper Trading Ledger Module]] - degree 11, connects to 6 communities
- [[test_silent_failures.py]] - degree 13, connects to 4 communities
- [[test_spend_validation.py]] - degree 11, connects to 2 communities
- [[STARTING_BALANCE]] - degree 3, connects to 2 communities
- [[test_analyze_trade_logs_consensus_failure()]] - degree 5, connects to 1 community