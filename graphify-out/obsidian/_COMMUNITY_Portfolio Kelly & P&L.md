---
type: community
cohesion: 0.04
members: 62
---

# Portfolio Kelly & P&L

**Cohesion:** 0.04 - loosely connected
**Members:** 62 nodes

## Members
- [[15 Calculate realised P&L from a trade dict using the actual fill price.]] - rationale - paper.py
- [[51 Compute correlation-adjusted Kelly fractions for a list of positions.]] - rationale - paper.py
- [[51 portfolio_kelly returns correlation-adjusted Kelly fractions.]] - rationale - tests/test_trading.py
- [[.test_all_fractions_non_negative()]] - code - tests/test_trading.py
- [[.test_capped_at_0_05()]] - code - tests/test_trading.py
- [[.test_correlated_positions_reduce_fractions()]] - code - tests/test_trading.py
- [[.test_empty_positions_returns_empty_list()]] - code - tests/test_trading.py
- [[.test_falls_back_to_entry_price_when_no_actual_fill()]] - code - tests/test_trading.py
- [[.test_near_zero_for_single_contract()]] - code - tests/test_trading.py
- [[.test_no_side_win()]] - code - tests/test_trading.py
- [[.test_returns_same_length_as_input()]] - code - tests/test_trading.py
- [[.test_single_position_returns_list_of_one()]] - code - tests/test_trading.py
- [[.test_slippage_increases_with_quantity()]] - code - tests/test_trading.py
- [[.test_yes_loss_uses_actual_fill_price()]] - code - tests/test_trading.py
- [[.test_yes_win_with_actual_fill_price()]] - code - tests/test_trading.py
- [[.test_zero_at_depth_scale()]] - code - tests/test_trading.py
- [[A single contract (quantity=1) should have essentially zero slippage.]] - rationale - tests/test_trading.py
- [[After a paper position settles, was_traded_today() must still block re-entry]] - rationale - tests/test_trading.py
- [[All returned fractions must be = 0.]] - rationale - tests/test_trading.py
- [[Apply the common monkeypatches needed for L7-B _auto_place_trades tests.]] - rationale - tests/test_trading.py
- [[Empty input returns empty output.]] - rationale - tests/test_trading.py
- [[Exactly at depth_scale (50) contracts no slippage.]] - rationale - tests/test_trading.py
- [[Highly correlated city pair should produce lower fractions than independent.]] - rationale - tests/test_trading.py
- [[If updated prob shifts 25pp against position, close_paper_early is called.]] - rationale - tests/test_trading.py
- [[Larger orders should have more slippage.]] - rationale - tests/test_trading.py
- [[NO side, settled NO → win. Fee applied to winnings.]] - rationale - tests/test_trading.py
- [[Output list length must match input list length.]] - rationale - tests/test_trading.py
- [[Regression for L7-B for NO trades, entry_price must equal no_ask = 1 - yes_bid]] - rationale - tests/test_trading.py
- [[Regression for L7-B for YES trades, entry_price passed to place_paper_order]] - rationale - tests/test_trading.py
- [[Should not place trades when MAX_DAILY_SPEND is already reached.]] - rationale - tests/test_trading.py
- [[Single uncorrelated position returns its own Kelly fraction unchanged.]] - rationale - tests/test_trading.py
- [[Slippage should never exceed 0.05.]] - rationale - tests/test_trading.py
- [[TestCalcTradePnl]] - code - tests/test_trading.py
- [[TestEstimateSlippage]] - code - tests/test_trading.py
- [[TestPortfolioKelly_1]] - code - tests/test_trading.py
- [[Tests for Phase 5 trading improvements   39  bayesian_kelly_fraction   49]] - rationale - tests/test_trading.py
- [[When actual_fill_price is absent, uses entry_price. Fee applied on win.]] - rationale - tests/test_trading.py
- [[With many samples the shrinkage factor is negligible — bias stays near its]] - rationale - tests/test_trading.py
- [[With only min_samples rows, the returned bias must be strictly smaller in     m]] - rationale - tests/test_trading.py
- [[YES side, settled NO → loss. No fee on losses.]] - rationale - tests/test_trading.py
- [[YES side, settled YES, actual_fill_price=0.62 on 10 contracts.         calc_tra]] - rationale - tests/test_trading.py
- [[_auto_place_trades must log paper orders to execution_log so was_traded_today()]] - rationale - tests/test_trading.py
- [[_auto_place_trades with cap=20.0 should call kelly_quantity with cap=20.0.]] - rationale - tests/test_trading.py
- [[_l7b_common_patches()]] - code - tests/test_trading.py
- [[calc_trade_pnl()]] - code - paper.py
- [[check_model_exits must include 'market' key in each recommendation (L3-B).]] - rationale - tests/test_trading.py
- [[get_quintile_bias must ignore rows where city IS NULL even when no city filter]] - rationale - tests/test_trading.py
- [[log_prediction(city=None) must write nothing to the DB (L4-B).]] - rationale - tests/test_trading.py
- [[portfolio_kelly()]] - code - paper.py
- [[test_auto_place_trades_logs_paper_order_to_execution_log()]] - code - tests/test_trading.py
- [[test_auto_place_trades_med_tier_uses_20_cap()]] - code - tests/test_trading.py
- [[test_auto_place_trades_stops_at_daily_spend_cap()]] - code - tests/test_trading.py
- [[test_auto_place_uses_no_ask_not_mid_for_no_trades()]] - code - tests/test_trading.py
- [[test_auto_place_uses_yes_ask_not_mid_for_yes_trades()]] - code - tests/test_trading.py
- [[test_check_early_exits_closes_position_when_prob_flips()]] - code - tests/test_trading.py
- [[test_check_model_exits_includes_market_in_rec()]] - code - tests/test_trading.py
- [[test_get_bias_near_full_strength_for_large_samples()]] - code - tests/test_trading.py
- [[test_get_bias_shrinks_toward_zero_for_small_samples()]] - code - tests/test_trading.py
- [[test_get_quintile_bias_excludes_null_city_rows()]] - code - tests/test_trading.py
- [[test_log_prediction_with_null_city_is_noop()]] - code - tests/test_trading.py
- [[test_trading.py]] - code - tests/test_trading.py
- [[test_was_traded_today_blocks_reentry_after_settlement()]] - code - tests/test_trading.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Portfolio_Kelly__PL
SORT file.name ASC
```

## Connections to other communities
- 13 edges to [[_COMMUNITY_Paper Trading & Exits]]
- 3 edges to [[_COMMUNITY_Module tests]]
- 3 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_AB Testing System]]
- 2 edges to [[_COMMUNITY_CLI & Preload Pipeline]]
- 2 edges to [[_COMMUNITY_Kelly Criterion Sizing]]
- 2 edges to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]
- 1 edge to [[_COMMUNITY_Module tests]]

## Top bridge nodes
- [[test_trading.py]] - degree 39, connects to 12 communities
- [[test_check_early_exits_closes_position_when_prob_flips()]] - degree 5, connects to 3 communities
- [[portfolio_kelly()]] - degree 10, connects to 2 communities
- [[calc_trade_pnl()]] - degree 8, connects to 1 community
- [[test_auto_place_trades_stops_at_daily_spend_cap()]] - degree 3, connects to 1 community