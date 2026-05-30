---
type: community
cohesion: 0.05
members: 59
---

# A/B Testing System

**Cohesion:** 0.05 - loosely connected
**Members:** 59 nodes

## Members
- [[.check()_1]] - code - trading_gates.py
- [[.check_or_raise()]] - code - trading_gates.py
- [[.summary()]] - code - ab_test.py
- [[.test_cents_converted_to_decimal()]] - code - tests/test_weather_markets.py
- [[.test_implied_prob_is_midpoint()]] - code - tests/test_weather_markets.py
- [[.test_l2d_integer_1_converted_to_1_cent()]] - code - tests/test_weather_markets.py
- [[.test_l2d_zero_bid_not_bypassed_by_or()]] - code - tests/test_weather_markets.py
- [[.test_mid_falls_back_to_yes_bid_when_no_ask()]] - code - tests/test_weather_markets.py
- [[.test_missing_fields_fall_back_to_zero()]] - code - tests/test_weather_markets.py
- [[.test_returns_dict_with_expected_keys()]] - code - tests/test_weather_markets.py
- [[.test_string_prices_parsed()]] - code - tests/test_weather_markets.py
- [[ABTest]] - code - ab_test.py
- [[Auto-place paper or live trades for signals not already held.     Called from c]] - rationale - order_executor.py
- [[Check fill status of all pending live orders and update execution_log.      Al]] - rationale - order_executor.py
- [[Count live orders with status 'pending' — enforces max_open_positions limit.]] - rationale - order_executor.py
- [[Extract yesno bid prices and implied probability from a market.]] - rationale - weather_markets.py
- [[Integer values  1 are treated as cents and divided by 100.]] - rationale - tests/test_weather_markets.py
- [[L2-D a valid 0¢ bid must not be bypassed by the or-fallback.          When ye]] - rationale - tests/test_weather_markets.py
- [[L2-D integer value 1 (= 1¢) must be divided by 100, not returned as 1.0.]] - rationale - tests/test_weather_markets.py
- [[Missing price fields default to 0.0 without raising.]] - rationale - tests/test_weather_markets.py
- [[Place a live Kalshi order with hard-stop guards.      Returns (placed, dollar_]] - rationale - order_executor.py
- [[Pre-trade live safety gate — single call point before every live order.]] - rationale - trading_gates.py
- [[Raise RuntimeError if any live trading gate is not satisfied.]] - rationale - trading_gates.py
- [[Re-analyze all open paper positions. If the updated model probability has     s]] - rationale - order_executor.py
- [[Result must be a dict containing the standard price keys.]] - rationale - tests/test_weather_markets.py
- [[Return (allowed, reason). Fail-closed any exception → blocked.]] - rationale - trading_gates.py
- [[Return True if balance has fallen more than MAX_DRAWDOWN_FRACTION from the]] - rationale - paper.py
- [[Return a string identifier for the current NWS forecast cycle.      NWS model]] - rationale - order_executor.py
- [[Return midpoint of current bidask for the given side, rounded to 2dp.      Ka]] - rationale - order_executor.py
- [[Return summary statistics for all variants.]] - rationale - ab_test.py
- [[Scale Kelly down when the bid-ask spread eats a significant fraction of edge.]] - rationale - paper.py
- [[Simple bandit-style AB test across strategy parameter variants.     Tracks win]] - rationale - ab_test.py
- [[String-format prices (e.g. '0.55') are parsed correctly.]] - rationale - tests/test_weather_markets.py
- [[Sum of paper trade costs placed today (UTC date). Used for daily spend cap.]] - rationale - order_executor.py
- [[TestParseMarketPrice]] - code - tests/test_weather_markets.py
- [[When yes_ask is 0 the mid falls back to yes_bid.]] - rationale - tests/test_weather_markets.py
- [[_auto_place_trades()]] - code - order_executor.py
- [[_check_early_exits()]] - code - order_executor.py
- [[_count_open_live_orders()]] - code - order_executor.py
- [[_current_forecast_cycle()]] - code - order_executor.py
- [[_daily_paper_spend()]] - code - order_executor.py
- [[_midpoint_price()]] - code - order_executor.py
- [[_place_live_order()]] - code - order_executor.py
- [[_poll_pending_orders()]] - code - order_executor.py
- [[bool_18]] - code - order_executor.py
- [[bool_22]] - code - trading_gates.py
- [[float_23]] - code - order_executor.py
- [[implied_prob equals the mid-price of yes_bid and yes_ask.]] - rationale - tests/test_weather_markets.py
- [[int_18]] - code - order_executor.py
- [[is_paused_drawdown()]] - code - paper.py
- [[order_executor.py]] - code - order_executor.py
- [[order_executor.py — Automated order placement and lifecycle management.  Extra]] - rationale - order_executor.py
- [[parse_market_price()]] - code - weather_markets.py
- [[place_paper_order()]] - code - order_executor.py
- [[pre_live_trade_check()]] - code - trading_gates.py
- [[spread_kelly_multiplier()]] - code - paper.py
- [[str_22]] - code - order_executor.py
- [[str_31]] - code - trading_gates.py
- [[trading_gates.py]] - code - trading_gates.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/A/B_Testing_System
SORT file.name ASC
```

## Connections to other communities
- 34 edges to [[_COMMUNITY_Python Types & Utilities]]
- 31 edges to [[_COMMUNITY_Paper Trading & Exits]]
- 17 edges to [[_COMMUNITY_AB Test Module]]
- 8 edges to [[_COMMUNITY_CLI & Preload Pipeline]]
- 6 edges to [[_COMMUNITY_Forecast Analysis Engine]]
- 5 edges to [[_COMMUNITY_Cron Scheduler]]
- 4 edges to [[_COMMUNITY_Module frosty]]
- 4 edges to [[_COMMUNITY_Module tests]]
- 4 edges to [[_COMMUNITY_Tracker Analytics (BrierBias)]]
- 4 edges to [[_COMMUNITY_Module frosty]]
- 3 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Portfolio Kelly & P&L]]
- 2 edges to [[_COMMUNITY_SnowPrecip Physics]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module frosty]]
- 1 edge to [[_COMMUNITY_Module frosty]]
- 1 edge to [[_COMMUNITY_Module frosty]]
- 1 edge to [[_COMMUNITY_Module tests]]

## Top bridge nodes
- [[order_executor.py]] - degree 41, connects to 14 communities
- [[parse_market_price()]] - degree 33, connects to 9 communities
- [[_auto_place_trades()]] - degree 32, connects to 9 communities
- [[_check_early_exits()]] - degree 10, connects to 5 communities
- [[ABTest]] - degree 32, connects to 4 communities