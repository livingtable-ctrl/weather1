---
type: community
cohesion: 0.10
members: 29
---

# Community 86

**Cohesion:** 0.10 - loosely connected
**Members:** 29 nodes

## Members
- [[dot-_find_order_by_client_id()]] - code - kalshi_client.py
- [[dot-_get()]] - code - kalshi_client.py
- [[dot-_validate()]] - code - kalshi_client.py
- [[dot-get_balance()]] - code - kalshi_client.py
- [[dot-get_candlesticks()]] - code - kalshi_client.py
- [[dot-get_events()]] - code - kalshi_client.py
- [[dot-get_market()]] - code - kalshi_client.py
- [[dot-get_markets()]] - code - kalshi_client.py
- [[dot-get_open_orders()]] - code - kalshi_client.py
- [[dot-get_order()]] - code - kalshi_client.py
- [[dot-get_orderbook()]] - code - kalshi_client.py
- [[dot-get_positions()]] - code - kalshi_client.py
- [[dot-get_series_list()]] - code - kalshi_client.py
- [[dot-get_trades()]] - code - kalshi_client.py
- [[dot-place_maker_order()]] - code - kalshi_client.py
- [[dot-place_order()]] - code - kalshi_client.py
- [[dot-test_validate_emits_log_error_not_warning()]] - code - tests/test_phase3_batch_a.py
- [[dot-test_validate_no_warning_on_schema_change()]] - code - tests/test_phase3_batch_a.py
- [[Fetch a single order by ID from the Kalshi portfolio API. Returns the inner…]] - rationale - kalshi_client.py
- [[GET marketstrades -- public trade-flow history for a single market…]] - rationale - kalshi_client.py
- [[GET series{series_ticker}markets{ticker}candlesticks -- OHLC price…]] - rationale - kalshi_client.py
- [[P3-21 _validate must log an error, not emit a warning.]] - rationale - tests/test_phase3_batch_a.py
- [[Place a limit order with a deterministic idempotency key. Uses Kalshi's V2…]] - rationale - kalshi_client.py
- [[Place a passive limit (maker) order at the specified price. Uses…]] - rationale - kalshi_client.py
- [[Return the order matching client_order_id, or None if not found. Checks resting…]] - rationale - kalshi_client.py
- [[TestKalshiClientValidateLogsError]] - code - tests/test_phase3_batch_a.py
- [[Validate a Kalshi market dict has required fields and sane prices. Returns True…]] - rationale - schema_validator.py
- [[Warn (don't crash) if the API response shape has changed.]] - rationale - kalshi_client.py
- [[validate_market()]] - code - schema_validator.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_86
SORT file.name ASC
```

## Connections to other communities
- 17 edges to [[_COMMUNITY_Black Swan Halt State]]
- 4 edges to [[_COMMUNITY_Community 298]]
- 2 edges to [[_COMMUNITY_Community 59]]
- 1 edge to [[_COMMUNITY_Community 351]]
- 1 edge to [[_COMMUNITY_Community 226]]
- 1 edge to [[_COMMUNITY_Community 225]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 1 edge to [[_COMMUNITY_Community 458]]
- 1 edge to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Community 417]]
- 1 edge to [[_COMMUNITY_Community 80]]
- 1 edge to [[_COMMUNITY_Community 57]]

## Top bridge nodes
- [[validate_market()]] - degree 11, connects to 7 communities
- [[dot-place_order()]] - degree 8, connects to 4 communities
- [[dot-_get()]] - degree 17, connects to 3 communities
- [[TestKalshiClientValidateLogsError]] - degree 5, connects to 2 communities
- [[dot-_validate()]] - degree 13, connects to 1 community