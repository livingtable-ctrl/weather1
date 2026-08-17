---
type: community
cohesion: 0.15
members: 16
---

# Community 225

**Cohesion:** 0.15 - loosely connected
**Members:** 16 nodes

## Members
- [[dot-test_empty_when_no_opportunities()]] - code - tests/test_suggested_bets.py
- [[dot-test_market_fetch_failure_returns_500()]] - code - tests/test_suggested_bets.py
- [[dot-test_returns_top_n_sorted_by_ev()]] - code - tests/test_suggested_bets.py
- [[Ensure KALSHI_ENV=demo so _build_app doesn't require DASHBOARD_PASSWORD.]] - rationale - tests/test_suggested_bets.py
- [[Returns 500 with error key when get_weather_markets raises.]] - rationale - tests/test_suggested_bets.py
- [[Returns empty bets list when analyze_trade returns None for all markets.]] - rationale - tests/test_suggested_bets.py
- [[Returns top-n opportunities ranked by EV = net_edge × kelly_dollars.]] - rationale - tests/test_suggested_bets.py
- [[TestSuggestedBetsEndpoint]] - code - tests/test_suggested_bets.py
- [[Tests for apisuggested_bets.]] - rationale - tests/test_suggested_bets.py
- [[_force_demo_env()]] - code - tests/test_suggested_bets.py
- [[_make_analysis()_1]] - code - tests/test_suggested_bets.py
- [[_make_market()]] - code - tests/test_suggested_bets.py
- [[_no_dashboard_password()]] - code - tests/test_suggested_bets.py
- [[fixture_7]] - code
- [[patch_1]] - code
- [[utils.DASHBOARD_PASSWORD is cached at import time (conftest.py imports main,…]] - rationale - tests/test_suggested_bets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_225
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 4]]
- 3 edges to [[_COMMUNITY_Community 35]]

## Top bridge nodes
- [[dot-test_returns_top_n_sorted_by_ev()]] - degree 6, connects to 1 community
- [[TestSuggestedBetsEndpoint]] - degree 5, connects to 1 community
- [[dot-test_empty_when_no_opportunities()]] - degree 5, connects to 1 community
- [[_force_demo_env()]] - degree 4, connects to 1 community
- [[dot-test_market_fetch_failure_returns_500()]] - degree 4, connects to 1 community