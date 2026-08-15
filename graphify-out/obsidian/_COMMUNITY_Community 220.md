---
type: community
cohesion: 0.16
members: 16
---

# Community 220

**Cohesion:** 0.16 - loosely connected
**Members:** 16 nodes

## Members
- [[If _get_consensus_probs raises, it must be logged — not silently defaulted.]] - rationale - tests/test_silent_failures.py
- [[If climatological_prob raises, the failure must be logged.]] - rationale - tests/test_silent_failures.py
- [[If log_api_request raises inside _request_with_retry, it must be logged.]] - rationale - tests/test_silent_failures.py
- [[If log_price_improvement raises after a paper order, it must be logged.]] - rationale - tests/test_silent_failures.py
- [[If nws_prob raises, the failure must be logged.]] - rationale - tests/test_silent_failures.py
- [[Minimal enriched dict that passes all analyze_trade gates.]] - rationale - tests/test_silent_failures.py
- [[Return a stack of patches that let analyze_trade reach the risky sections.]] - rationale - tests/test_silent_failures.py
- [[Tests for P0.4 — Silent failure elimination. Every failure in the trading path…]] - rationale - tests/test_silent_failures.py
- [[_make_enriched()_1]] - code - tests/test_silent_failures.py
- [[_patch_analyze_prereqs()]] - code - tests/test_silent_failures.py
- [[test_analyze_trade_logs_climatological_failure()]] - code - tests/test_silent_failures.py
- [[test_analyze_trade_logs_consensus_failure()]] - code - tests/test_silent_failures.py
- [[test_analyze_trade_logs_nws_prob_failure()]] - code - tests/test_silent_failures.py
- [[test_kalshi_client_api_log_failure_is_logged()]] - code - tests/test_silent_failures.py
- [[test_paper_price_improvement_log_failure_is_logged()]] - code - tests/test_silent_failures.py
- [[test_silent_failures.py]] - code - tests/test_silent_failures.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_220
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Community 52]]
- 1 edge to [[_COMMUNITY_Community 40]]

## Top bridge nodes
- [[test_silent_failures.py]] - degree 11, connects to 3 communities
- [[test_analyze_trade_logs_consensus_failure()]] - degree 5, connects to 1 community
- [[test_analyze_trade_logs_climatological_failure()]] - degree 4, connects to 1 community
- [[test_analyze_trade_logs_nws_prob_failure()]] - degree 4, connects to 1 community