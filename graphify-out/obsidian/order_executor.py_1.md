---
source_file: "order_executor.py"
type: "code"
community: "Community 40"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Community_40
---

# order_executor.py

## Connections
- [[LivePositionStore]] - `implements` [EXTRACTED]
- [[Shared Position Read-Model Module]] - `shares_data_with` [EXTRACTED]
- [[_auto_place_trades()]] - `implements` [EXTRACTED]
- [[_prediction_kwargs_from_analysis()]] - `implements` [EXTRACTED]
- [[_rain_gates_active()]] - `shares_data_with` [INFERRED]
- [[_resolve_live_balance()]] - `implements` [EXTRACTED]
- [[_resolve_micro_live_config()]] - `implements` [EXTRACTED]
- [[_sameday_effective_cap()]] - `implements` [EXTRACTED]
- [[run_trade_cycle()]] - `calls` [EXTRACTED]
- [[test_near_settlement_log.py]] - `conceptually_related_to` [EXTRACTED]
- [[test_p0_10_paper_prelog.py]] - `references` [EXTRACTED]
- [[test_p9_p10.py]] - `references` [EXTRACTED]
- [[test_trade_improvements.py]] - `references` [EXTRACTED]
- [[test_trading_gates.py]] - `references` [EXTRACTED]
- [[update_orderbook_cache()]] - `shares_data_with` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Community_40