---
type: community
cohesion: 0.09
members: 62
---

# Shadow Predictions Auto-Place Trades

**Cohesion:** 0.09 - loosely connected
**Members:** 62 nodes

## Members
- [[A hurricane season-count (KXHURCTOT) opp must be shadow-logged, not placed,…]] - rationale - tests/test_shadow_predictions.py
- [[A monthly-rain (KXRAINM) opp must be shadow-logged, not placed, when…]] - rationale - tests/test_shadow_predictions.py
- [[A monthly-snow (KXDENSNOWM) opp must be shadow-logged, not placed, when…]] - rationale - tests/test_shadow_predictions.py
- [[A signal that _validate_trade_opportunity would reject (here non-positive…]] - rationale - tests/test_shadow_predictions.py
- [[A storm-order (KXFIRSTHURRICANE) opp must be shadow-logged, not placed, when…]] - rationale - tests/test_shadow_predictions.py
- [[A ticker with an existing open position must not get re-logged every cron cycle…]] - rationale - tests/test_shadow_predictions.py
- [[A time-to-next-event (KXNEXTHURDATE) opp must be shadow-logged, not placed,…]] - rationale - tests/test_shadow_predictions.py
- [[All 3 hurricane sub-models' gates are independent -- a sibling model's gate…]] - rationale - tests/test_shadow_predictions.py
- [[An hourly (KXTEMPxxxH) opp must be shadow-logged, not placed, when…]] - rationale - tests/test_shadow_predictions.py
- [[Auto-place paper or live trades for signals not already held. Called from…]] - rationale - order_executor.py
- [[Drawdown halt causes the identical 'no trade placed' staleness problem as…]] - rationale - tests/test_shadow_predictions.py
- [[If the gate's underlying value changed mid-batch (settled count crossing the…]] - rationale - tests/test_shadow_predictions.py
- [[Mirrors test_real_placement_logs_is_shadow_false's full mock setup so a real…]] - rationale - tests/test_shadow_predictions.py
- [[Multiple opps in one call share a single batched DB connection — confirm both…]] - rationale - tests/test_shadow_predictions.py
- [[Once _hourly_gates_active() is True, an hourly opp places exactly like any…]] - rationale - tests/test_shadow_predictions.py
- [[Once _hurricane_count_gates_active() is True, a hurricane-count opp places…]] - rationale - tests/test_shadow_predictions.py
- [[Once _hurricane_next_event_gates_active() is True, a next-event opp places…]] - rationale - tests/test_shadow_predictions.py
- [[Once _rain_gates_active() is True, a rain opp places exactly like any other…]] - rationale - tests/test_shadow_predictions.py
- [[Once _snow_gates_active() is True, a snow opp places exactly like any other…]] - rationale - tests/test_shadow_predictions.py
- [[Once _storm_order_gates_active() is True, a storm-order opp places exactly like…]] - rationale - tests/test_shadow_predictions.py
- [[Regression test each shadow-only gate must be evaluated ONCE per…]] - rationale - tests/test_shadow_predictions.py
- [[Sanity check for the is_shadow column itself a real, successfully placed trade…]] - rationale - tests/test_shadow_predictions.py
- [[Shadow logging must never place an actual order — only observe.]] - rationale - tests/test_shadow_predictions.py
- [[Tests for _log_shadow_predictions when a trade would have been placed but…]] - rationale - tests/test_shadow_predictions.py
- [[The core routing guarantee in one batch, a hurricane-count opp (gate inactive)…]] - rationale - tests/test_shadow_predictions.py
- [[The core routing guarantee in one batch, a rain opp (gate inactive) is shadow-…]] - rationale - tests/test_shadow_predictions.py
- [[The core routing guarantee in one batch, a snow opp (gate inactive) is shadow-…]] - rationale - tests/test_shadow_predictions.py
- [[The core routing guarantee in one batch, an hourly opp (gate inactive) is…]] - rationale - tests/test_shadow_predictions.py
- [[The two hurricane sub-models' gates are independent -- the count model's gate…]] - rationale - tests/test_shadow_predictions.py
- [[_auto_place_trades()]] - code - order_executor.py
- [[_fetch()]] - code - tests/test_shadow_predictions.py
- [[_make_flat_opp()]] - code - tests/test_shadow_predictions.py
- [[_place_everything_setup()]] - code - tests/test_shadow_predictions.py
- [[test_drawdown_halt_also_logs_shadow_prediction()]] - code - tests/test_shadow_predictions.py
- [[test_hourly_ticker_places_normally_when_gate_active()]] - code - tests/test_shadow_predictions.py
- [[test_hourly_ticker_shadow_only_when_gate_inactive()]] - code - tests/test_shadow_predictions.py
- [[test_hurricane_count_gate_evaluated_once_per_batch()]] - code - tests/test_shadow_predictions.py
- [[test_hurricane_count_gate_stable_within_batch_despite_stateful_mock()]] - code - tests/test_shadow_predictions.py
- [[test_hurricane_count_gate_state_does_not_affect_next_event_routing()]] - code - tests/test_shadow_predictions.py
- [[test_hurricane_count_ticker_places_normally_when_gate_active()]] - code - tests/test_shadow_predictions.py
- [[test_hurricane_count_ticker_shadow_only_when_gate_inactive()]] - code - tests/test_shadow_predictions.py
- [[test_hurricane_next_event_ticker_places_normally_when_gate_active()]] - code - tests/test_shadow_predictions.py
- [[test_hurricane_next_event_ticker_shadow_only_when_gate_inactive()]] - code - tests/test_shadow_predictions.py
- [[test_mixed_batch_hourly_shadow_daily_places_normally()]] - code - tests/test_shadow_predictions.py
- [[test_mixed_batch_hurricane_count_shadow_daily_places_normally()]] - code - tests/test_shadow_predictions.py
- [[test_mixed_batch_rain_shadow_daily_places_normally()]] - code - tests/test_shadow_predictions.py
- [[test_mixed_batch_snow_shadow_daily_places_normally()]] - code - tests/test_shadow_predictions.py
- [[test_rain_ticker_places_normally_when_gate_active()]] - code - tests/test_shadow_predictions.py
- [[test_rain_ticker_shadow_only_when_gate_inactive()]] - code - tests/test_shadow_predictions.py
- [[test_real_placement_logs_is_shadow_false()]] - code - tests/test_shadow_predictions.py
- [[test_shadow_predictions.py]] - code - tests/test_shadow_predictions.py
- [[test_sibling_hurricane_gate_state_does_not_affect_storm_order_routing()]] - code - tests/test_shadow_predictions.py
- [[test_snow_ticker_places_normally_when_gate_active()]] - code - tests/test_shadow_predictions.py
- [[test_snow_ticker_shadow_only_when_gate_inactive()]] - code - tests/test_shadow_predictions.py
- [[test_storm_order_ticker_places_normally_when_gate_active()]] - code - tests/test_shadow_predictions.py
- [[test_storm_order_ticker_shadow_only_when_gate_inactive()]] - code - tests/test_shadow_predictions.py
- [[test_trading_paused_does_not_place_trade()]] - code - tests/test_shadow_predictions.py
- [[test_trading_paused_logs_multiple_opps_in_one_batch()]] - code - tests/test_shadow_predictions.py
- [[test_trading_paused_logs_shadow_prediction()]] - code - tests/test_shadow_predictions.py
- [[test_trading_paused_logs_shadow_prediction_tuple_format()]] - code - tests/test_shadow_predictions.py
- [[test_trading_paused_skips_already_open_ticker()]] - code - tests/test_shadow_predictions.py
- [[test_trading_paused_skips_invalid_opp()]] - code - tests/test_shadow_predictions.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Shadow_Predictions_Auto-Place_Trades
SORT file.name ASC
```

## Connections to other communities
- 23 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 7 edges to [[_COMMUNITY_Community 40]]
- 6 edges to [[_COMMUNITY_Execution Log Live-Loss Tracking]]
- 5 edges to [[_COMMUNITY_Black Swan Halt State]]
- 3 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 2 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 2 edges to [[_COMMUNITY_Community 183]]
- 1 edge to [[_COMMUNITY_Weather Probability Math Tests]]
- 1 edge to [[_COMMUNITY_Community 74]]
- 1 edge to [[_COMMUNITY_Community 63]]
- 1 edge to [[_COMMUNITY_Community 85]]
- 1 edge to [[_COMMUNITY_Community 97]]
- 1 edge to [[_COMMUNITY_Community 459]]
- 1 edge to [[_COMMUNITY_Community 250]]
- 1 edge to [[_COMMUNITY_Community 328]]
- 1 edge to [[_COMMUNITY_Tracker SQLite Storage Tests]]
- 1 edge to [[_COMMUNITY_Community 500]]
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 92]]
- 1 edge to [[_COMMUNITY_Community 52]]
- 1 edge to [[_COMMUNITY_Community 248]]
- 1 edge to [[_COMMUNITY_Community 108]]

## Top bridge nodes
- [[_auto_place_trades()]] - degree 90, connects to 22 communities
- [[test_shadow_predictions.py]] - degree 35, connects to 2 communities
- [[_fetch()]] - degree 28, connects to 1 community