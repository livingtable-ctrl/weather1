---
type: community
cohesion: 0.18
members: 20
---

# Community 159

**Cohesion:** 0.18 - loosely connected
**Members:** 20 nodes

## Members
- [[dot-_trade()]] - code - tests/test_paper.py
- [[dot-test_missing_ticker_skipped()]] - code - tests/test_paper.py
- [[dot-test_multiple_trades_only_breached_returned()]] - code - tests/test_paper.py
- [[dot-test_stop_loss_result_wires_to_close_paper_early()]] - code - tests/test_paper.py
- [[dot-test_stop_not_triggered_when_multiplier_zero()]] - code - tests/test_paper.py
- [[dot-test_stop_not_triggered_within_range()]] - code - tests/test_paper.py
- [[dot-test_stop_triggers_for_no_trade()]] - code - tests/test_paper.py
- [[dot-test_stop_triggers_when_yes_price_halves()]] - code - tests/test_paper.py
- [[Convert {ticker yes_price} to the {ticker {bid..., ask...}} shape…]] - rationale - tests/test_paper.py
- [[Full chain stop fires → close_paper_early settles the trade and updates…]] - rationale - tests/test_paper.py
- [[NO trade YES price rises sharply → NO value drops → stop fires.]] - rationale - tests/test_paper.py
- [[Only tickers that breach the threshold are returned.]] - rationale - tests/test_paper.py
- [[Return positions whose unrealized loss has breached the stop-loss threshold.…]] - rationale - positions.py
- [[STOP_LOSS_MULT=0 disables stop-losses entirely.]] - rationale - tests/test_paper.py
- [[TestCheckStopLosses]] - code - tests/test_paper.py
- [[Ticker not in current_yes_prices is skipped (no crash).]] - rationale - tests/test_paper.py
- [[YES trade price halved → loss = 50% of cost → stop fires (MULT=2).]] - rationale - tests/test_paper.py
- [[YES trade small adverse move → no stop.]] - rationale - tests/test_paper.py
- [[_flat_prices()]] - code - tests/test_paper.py
- [[check_stop_losses()]] - code - positions.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_159
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 45]]
- 3 edges to [[_COMMUNITY_Community 145]]
- 2 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 2 edges to [[_COMMUNITY_Community 56]]
- 1 edge to [[_COMMUNITY_Community 144]]
- 1 edge to [[_COMMUNITY_Community 158]]
- 1 edge to [[_COMMUNITY_Community 40]]
- 1 edge to [[_COMMUNITY_Community 370]]

## Top bridge nodes
- [[check_stop_losses()]] - degree 18, connects to 7 communities
- [[TestCheckStopLosses]] - degree 10, connects to 2 communities
- [[_flat_prices()]] - degree 8, connects to 1 community
- [[dot-_trade()]] - degree 8, connects to 1 community