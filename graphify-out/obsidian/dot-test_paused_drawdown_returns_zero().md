---
source_file: "tests/test_risk_control.py"
type: "code"
community: "Community 186"
location: "L192"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Community_186
---

# .test_paused_drawdown_returns_zero()

## Connections
- [[P2-B is_paused_drawdown=True must block all auto-trades and return 0.]] - `rationale_for` [EXTRACTED]
- [[TestAutoPlaceTradeGuards]] - `method` [EXTRACTED]
- [[_make_opp()_1]] - `calls` [EXTRACTED]
- [[_patch_paper_guards()]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Community_186