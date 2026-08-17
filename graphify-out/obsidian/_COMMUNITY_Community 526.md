---
type: community
cohesion: 0.29
members: 7
---

# Community 526

**Cohesion:** 0.29 - loosely connected
**Members:** 7 nodes

## Members
- [[dot-test_demo_env_uses_demo_base_url()]] - code - tests/test_risk_control.py
- [[dot-test_paper_mode_never_calls_place_live_order()]] - code - tests/test_risk_control.py
- [[dot-test_prod_env_uses_prod_base_url()]] - code - tests/test_risk_control.py
- [[Sanity check KALSHI_ENV=prod must give the production URL.]] - rationale - tests/test_risk_control.py
- [[TestPaperLiveSeparation]] - code - tests/test_risk_control.py
- [[When KALSHI_ENV=demo the MARKET_BASE_URL must point to demo.kalshi.co.]] - rationale - tests/test_risk_control.py
- [[_auto_place_trades(live=False) must never call _place_live_order.]] - rationale - tests/test_risk_control.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_526
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 186]]
- 1 edge to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 401]]

## Top bridge nodes
- [[TestPaperLiveSeparation]] - degree 6, connects to 2 communities
- [[dot-test_paper_mode_never_calls_place_live_order()]] - degree 3, connects to 1 community