---
type: community
cohesion: 0.05
members: 66
---

# Community 13

**Cohesion:** 0.05 - loosely connected
**Members:** 66 nodes

## Members
- [[dot-_check_error_body()]] - code - kalshi_client.py
- [[dot-_delete()]] - code - kalshi_client.py
- [[dot-_find_order_by_client_id()]] - code - kalshi_client.py
- [[dot-_full_path()]] - code - kalshi_client.py
- [[dot-_get()]] - code - kalshi_client.py
- [[dot-_post()]] - code - kalshi_client.py
- [[dot-_sign_headers()]] - code - kalshi_client.py
- [[dot-_validate()]] - code - kalshi_client.py
- [[dot-amend_order()]] - code - kalshi_client.py
- [[dot-cancel_order()]] - code - kalshi_client.py
- [[dot-get_balance()]] - code - kalshi_client.py
- [[dot-get_candlesticks()]] - code - kalshi_client.py
- [[dot-get_events()]] - code - kalshi_client.py
- [[dot-get_market()_2]] - code - kalshi_client.py
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
- [[Amend a resting order's price andor size atomically via Kalshi's V2 amend…]] - rationale - kalshi_client.py
- [[Build SSE payload. Extracted for testability.]] - rationale - web_app.py
- [[Build signed auth headers for authenticated endpoints.]] - rationale - kalshi_client.py
- [[Call _SESSION.request with automatic retry via HTTPAdapter (67). Falls back to…]] - rationale - kalshi_client.py
- [[Cancel a resting order via Kalshi's V2 endpoint -- the legacy DELETE…]] - rationale - kalshi_client.py
- [[Copy files from sync_folderKalshiBotdata back into local data. Use this…]] - rationale - cloud_backup.py
- [[Each market dict has the minimum keys the rest of the system relies on.]] - rationale - tests/test_integration_live.py
- [[Fetch a single order by ID from the Kalshi portfolio API. Returns the inner…]] - rationale - kalshi_client.py
- [[Fetching weather markets from demo API returns a non-empty list.]] - rationale - tests/test_integration_live.py
- [[GET marketstrades -- public trade-flow history for a single market…]] - rationale - kalshi_client.py
- [[GET series{series_ticker}markets{ticker}candlesticks -- OHLC price…]] - rationale - kalshi_client.py
- [[KalshiClient]] - code - kalshi_client.py
- [[Live Kalshi API integration tests. These tests make real network calls to the…]] - rationale - tests/test_integration_live.py
- [[P3-21 _validate must log an error, not emit a warning.]] - rationale - tests/test_phase3_batch_a.py
- [[Place a limit order with a deterministic idempotency key. Uses Kalshi's V2…]] - rationale - kalshi_client.py
- [[Place a passive limit (maker) order at the specified price. Uses…]] - rationale - kalshi_client.py
- [[Prompt for edge threshold before entering watch mode.]] - rationale - main.py
- [[Prompt for edge threshold before entering watch mode._1]] - rationale - main.py
- [[Raise ValueError if a 200 response contains an error field.]] - rationale - kalshi_client.py
- [[Response]] - code
- [[Return a KalshiClient pointed at the demo environment, or skip if not…]] - rationale - tests/test_integration_live.py
- [[Return the full URL path (e.g. trade-apiv2markets) used in signing.]] - rationale - kalshi_client.py
- [[Return the order matching client_order_id, or None if not found. Checks resting…]] - rationale - kalshi_client.py
- [[Same late-bound-closure shape as _count_signal_column, for the two registry…]] - rationale - weather_markets.py
- [[TestKalshiClientValidateLogsError]] - code - tests/test_phase3_batch_a.py
- [[ValueError]] - code
- [[Waive the accuracy circuit breaker (both the rolling win-rate check and the…]] - rationale - paper.py
- [[Warn (don't crash) if the API response shape has changed.]] - rationale - kalshi_client.py
- [[_build_stream_data()]] - code - web_app.py
- [[_count_model_obs()]] - code - weather_markets.py
- [[_demo_client()]] - code - tests/test_integration_live.py
- [[_menu_watch()]] - code - main.py
- [[_request_with_retry()]] - code - kalshi_client.py
- [[analyze_trade() returns a non-None result for at least one live market.]] - rationale - tests/test_integration_live.py
- [[integration]] - code
- [[override_accuracy_halt()]] - code - paper.py
- [[restore_data()]] - code - cloud_backup.py
- [[test_analyze_trade_returns_dict_for_live_market()]] - code - tests/test_integration_live.py
- [[test_fetch_markets_returns_list()]] - code - tests/test_integration_live.py
- [[test_integration_live.py]] - code - tests/test_integration_live.py
- [[test_market_has_required_fields()]] - code - tests/test_integration_live.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_13
SORT file.name ASC
```

## Connections to other communities
- 40 edges to [[_COMMUNITY_Community 0]]
- 18 edges to [[_COMMUNITY_Community 3]]
- 14 edges to [[_COMMUNITY_Community 5]]
- 11 edges to [[_COMMUNITY_Community 1]]
- 9 edges to [[_COMMUNITY_Community 41]]
- 8 edges to [[_COMMUNITY_Community 6]]
- 6 edges to [[_COMMUNITY_Community 7]]
- 5 edges to [[_COMMUNITY_Community 2]]
- 3 edges to [[_COMMUNITY_Community 187]]
- 3 edges to [[_COMMUNITY_Community 4]]
- 3 edges to [[_COMMUNITY_Community 43]]
- 2 edges to [[_COMMUNITY_Community 248]]
- 2 edges to [[_COMMUNITY_Community 191]]
- 2 edges to [[_COMMUNITY_Community 229]]
- 2 edges to [[_COMMUNITY_Community 8]]
- 1 edge to [[_COMMUNITY_Community 81]]
- 1 edge to [[_COMMUNITY_Community 227]]
- 1 edge to [[_COMMUNITY_Community 20]]
- 1 edge to [[_COMMUNITY_Community 629]]
- 1 edge to [[_COMMUNITY_Community 286]]
- 1 edge to [[_COMMUNITY_Community 388]]
- 1 edge to [[_COMMUNITY_Community 142]]
- 1 edge to [[_COMMUNITY_Community 389]]
- 1 edge to [[_COMMUNITY_Community 521]]
- 1 edge to [[_COMMUNITY_Community 522]]
- 1 edge to [[_COMMUNITY_Community 336]]
- 1 edge to [[_COMMUNITY_Community 658]]
- 1 edge to [[_COMMUNITY_Community 738]]
- 1 edge to [[_COMMUNITY_Community 14]]
- 1 edge to [[_COMMUNITY_Community 30]]
- 1 edge to [[_COMMUNITY_Community 32]]
- 1 edge to [[_COMMUNITY_Community 47]]
- 1 edge to [[_COMMUNITY_Community 51]]
- 1 edge to [[_COMMUNITY_Community 63]]
- 1 edge to [[_COMMUNITY_Community 82]]

## Top bridge nodes
- [[KalshiClient]] - degree 105, connects to 20 communities
- [[ValueError]] - degree 33, connects to 14 communities
- [[_request_with_retry()]] - degree 14, connects to 5 communities
- [[_build_stream_data()]] - degree 7, connects to 5 communities
- [[test_integration_live.py]] - degree 11, connects to 4 communities