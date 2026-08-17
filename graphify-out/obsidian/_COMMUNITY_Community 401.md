---
type: community
cohesion: 0.25
members: 9
---

# Community 401

**Cohesion:** 0.25 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-test_double_balance_roughly_doubles_output()]] - code - tests/test_risk_control.py
- [[dot-test_zero_drawdown_scale_returns_zero()]] - code - tests/test_risk_control.py
- [[Redirect paper.DATA_PATH to a per-test temp file. Prevents open trades,…]] - rationale - tests/conftest.py
- [[TestKellyScalesWithBalance]] - code - tests/test_risk_control.py
- [[Write a minimal valid paper_trades.json to path with the given balance.]] - rationale - tests/test_risk_control.py
- [[_write_paper_json()]] - code - tests/test_risk_control.py
- [[isolate_paper_data()]] - code - tests/conftest.py
- [[kelly_bet_dollars output should scale proportionally with paper balance.]] - rationale - tests/test_risk_control.py
- [[paper subcommand group]] - document - COMMANDS.md

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_401
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 4]]
- 2 edges to [[_COMMUNITY_Community 18]]
- 1 edge to [[_COMMUNITY_Community 117]]
- 1 edge to [[_COMMUNITY_Community 526]]

## Top bridge nodes
- [[isolate_paper_data()]] - degree 5, connects to 2 communities
- [[TestKellyScalesWithBalance]] - degree 6, connects to 1 community
- [[_write_paper_json()]] - degree 4, connects to 1 community
- [[paper subcommand group]] - degree 2, connects to 1 community