---
source_file: "tests/test_trade_cycle_engine.py"
type: "code"
community: "Trade Cycle Engine & Arbitrage Gates"
location: "L488"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Trade_Cycle_Engine__Arbitrage_Gates
---

# TestCmdWatchIntegration

## Connections
- [[dot-test_auto_watch_calls_run_trade_cycle_with_liquidity_required()]] - `method` [EXTRACTED]
- [[dot-test_plain_watch_never_calls_run_trade_cycle()]] - `method` [EXTRACTED]
- [[LiveTradingGate]] - `uses` [INFERRED]
- [[Violation]] - `uses` [INFERRED]
- [[cmd_watch must only invoke run_trade_cycle() when auto_trade=True -- plain…]] - `rationale_for` [EXTRACTED]
- [[test_trade_cycle_engine.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Trade_Cycle_Engine__Arbitrage_Gates