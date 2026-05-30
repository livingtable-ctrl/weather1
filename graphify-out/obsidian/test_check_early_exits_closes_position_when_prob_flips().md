---
source_file: "tests/test_trading.py"
type: "code"
community: "Portfolio Kelly & P&L"
location: "L802"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Portfolio_Kelly__PL
---

# test_check_early_exits_closes_position_when_prob_flips()

## Connections
- [[If updated prob shifts 25pp against position, close_paper_early is called.]] - `rationale_for` [EXTRACTED]
- [[_check_early_exits()]] - `calls` [INFERRED]
- [[get_open_trades()]] - `calls` [EXTRACTED]
- [[place_paper_order()_1]] - `calls` [EXTRACTED]
- [[test_trading.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Portfolio_Kelly__PL