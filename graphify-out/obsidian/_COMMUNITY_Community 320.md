---
type: community
cohesion: 0.17
members: 12
---

# Community 320

**Cohesion:** 0.17 - loosely connected
**Members:** 12 nodes

## Members
- [[50 slippage_adjusted_price uses 0.001  sqrt(quantity) model.]] - rationale - tests/test_trading.py
- [[dot-test_buy_no_decreases_price()]] - code - tests/test_trading.py
- [[dot-test_buy_yes_increases_price()]] - code - tests/test_trading.py
- [[dot-test_clamped_to_0_01_0_99()]] - code - tests/test_trading.py
- [[dot-test_place_paper_order_stores_actual_fill_price()]] - code - tests/test_trading.py
- [[dot-test_zero_slippage_at_quantity_zero()]] - code - tests/test_trading.py
- [[Buying NO subtracts slippage (worse fill for the buyer).]] - rationale - tests/test_trading.py
- [[Buying YES adds slippage to base price.]] - rationale - tests/test_trading.py
- [[Output must always be in 0.01, 0.99.]] - rationale - tests/test_trading.py
- [[TestSlippageAdjustedPrice]] - code - tests/test_trading.py
- [[place_paper_order records actual_fill_price != entry_price for large orders.]] - rationale - tests/test_trading.py
- [[quantity=1 produces 0.001 slippage.]] - rationale - tests/test_trading.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_320
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Community 92]]

## Top bridge nodes
- [[TestSlippageAdjustedPrice]] - degree 7, connects to 1 community
- [[dot-test_buy_no_decreases_price()]] - degree 3, connects to 1 community
- [[dot-test_buy_yes_increases_price()]] - degree 3, connects to 1 community
- [[dot-test_clamped_to_0_01_0_99()]] - degree 3, connects to 1 community
- [[dot-test_zero_slippage_at_quantity_zero()]] - degree 3, connects to 1 community