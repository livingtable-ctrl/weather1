---
type: community
cohesion: 0.05
members: 66
---

# METAR Settlement Monitoring

**Cohesion:** 0.05 - loosely connected
**Members:** 66 nodes

## Members
- [[dot-test_max_temp_at_exact_no_margin_boundary_locks_no()]] - code - tests/test_settlement_monitor.py
- [[dot-test_max_temp_at_yes_margin_boundary_locks_yes()]] - code - tests/test_settlement_monitor.py
- [[dot-test_max_temp_cleared_upper_edge_with_margin_locks_no()]] - code - tests/test_settlement_monitor.py
- [[dot-test_max_temp_inside_band_with_full_clearance_locks_yes()]] - code - tests/test_settlement_monitor.py
- [[dot-test_max_temp_just_under_no_margin_not_locked()]] - code - tests/test_settlement_monitor.py
- [[dot-test_max_temp_just_under_yes_margin_not_locked()]] - code - tests/test_settlement_monitor.py
- [[dot-test_no_lock_fallback_stays_unlocked_when_current_temp_below_band()]] - code - tests/test_settlement_monitor.py
- [[dot-test_no_lock_falls_back_to_current_temp_when_max_temp_unavailable()]] - code - tests/test_settlement_monitor.py
- [[dot-test_read_settlement_signals_empty_on_no_file()]] - code - tests/test_settlement_monitor.py
- [[dot-test_running_high_inside_band_locks_yes_despite_evening_cooling()]] - code - tests/test_settlement_monitor.py
- [[dot-test_running_high_still_below_band_stays_uncertain_not_locked()]] - code - tests/test_settlement_monitor.py
- [[dot-test_signal_structure()]] - code - tests/test_settlement_monitor.py
- [[dot-test_signals_expire_after_window()]] - code - tests/test_settlement_monitor.py
- [[dot-test_write_settlement_signals_creates_file()]] - code - tests/test_settlement_monitor.py
- [[dot-test_yes_requires_real_max_temp_not_current_temp_fallback()]] - code - tests/test_settlement_monitor.py
- [[AC3 regression guard, reproducing the entry's own concrete failure scenario…]] - rationale - tests/test_settlement_monitor.py
- [[AC3 regression guard a running high that hasn't reached the band yet must NOT…]] - rationale - tests/test_settlement_monitor.py
- [[AC3 regression guard an in-band INSTANTANEOUS reading alone must never lock…]] - rationale - tests/test_settlement_monitor.py
- [[Build a settlement lag signal dict.]] - rationale - settlement_monitor.py
- [[Check METAR for a city and return any new settlement signals. Args city City…]] - rationale - settlement_monitor.py
- [[Check METAR same-day lock-in for a temperature market. Fetches the latest METAR…]] - rationale - weather_markets.py
- [[Compute METAR lock-in confidence from temperature clearance and time of day.…]] - rationale - metar.py
- [[Compute the TRUE running daily extreme (max or min observed temp_f) since LOCAL…]] - rationale - metar.py
- [[Determine if a METAR reading locks in the trade outcome. Lock-in conditions…]] - rationale - metar.py
- [[Determine settlement outcome for a between-bucket market. Returns a dict with…]] - rationale - settlement_monitor.py
- [[Fetch the most recent METAR observation for a station. Returns dict with keys…]] - rationale - metar.py
- [[METAR Lock-In Module]] - code - metar.py
- [[METAR Settlement Lag Monitor — Phase D Settlement & Monitoring. Runs from 5 PM…]] - rationale - settlement_monitor.py
- [[Phase 2 Batch D Regression Tests]] - code - tests/test_phase2_batch_d.py
- [[Phase 2 Batch D regression tests P2-6, P2-15.]] - rationale - tests/test_phase2_batch_d.py
- [[Phase 2 Batch J Regression Tests]] - code - tests/test_phase2_batch_j.py
- [[Phase 2 Batch J regression tests P2-21P2-22P2-23 — METAR pipeline.]] - rationale - tests/test_phase2_batch_j.py
- [[Read active settlement signals, filtering out expired ones. Args…]] - rationale - settlement_monitor.py
- [[Run the settlement lag monitoring loop. Polls METAR every…]] - rationale - settlement_monitor.py
- [[Signals older than max_age_minutes are filtered out.]] - rationale - tests/test_settlement_monitor.py
- [[TestBuildSettlementSignal]] - code - tests/test_settlement_monitor.py
- [[TestCheckBetweenSettlement]] - code - tests/test_settlement_monitor.py
- [[Tests for METAR settlement lag monitoring.]] - rationale - tests/test_settlement_monitor.py
- [[The exact fallback path the OLD code got wrong max_temp_f unavailable,…]] - rationale - tests/test_settlement_monitor.py
- [[Unit tests for _check_between_settlement (between-bucket lockout logic).…]] - rationale - tests/test_settlement_monitor.py
- [[When max_temp_f is unavailable, the NO direction safely falls back to…]] - rationale - tests/test_settlement_monitor.py
- [[Write signals list to the signals file (atomic write).]] - rationale - settlement_monitor.py
- [[_check_between_settlement()]] - code - settlement_monitor.py
- [[_dynamic_lock_in_confidence()]] - code - metar.py
- [[_metar_lock_in()]] - code - weather_markets.py
- [[build_settlement_signal returns dict with required keys.]] - rationale - tests/test_settlement_monitor.py
- [[build_settlement_signal()]] - code - settlement_monitor.py
- [[check_city_settlement()]] - code - settlement_monitor.py
- [[check_metar_lockout()]] - code - metar.py
- [[fetch_metar()]] - code - metar.py
- [[fetch_metar_daily_extreme()]] - code - metar.py
- [[max_temp_f 2°F above the upper edge → locked=True, outcome=no.]] - rationale - tests/test_settlement_monitor.py
- [[max_temp_f at the lower edge → max clearance to the at-risk upper edge (full…]] - rationale - tests/test_settlement_monitor.py
- [[max_temp_f exactly at the NO margin boundary → locks (=, not ). Mutation…]] - rationale - tests/test_settlement_monitor.py
- [[max_temp_f exactly at the half-band-width margin → locks (=, not ).]] - rationale - tests/test_settlement_monitor.py
- [[max_temp_f just inside the at-risk edge of the margin → not locked.]] - rationale - tests/test_settlement_monitor.py
- [[max_temp_f just under the NO margin → not locked.]] - rationale - tests/test_settlement_monitor.py
- [[read_settlement_signals returns  when file does not exist.]] - rationale - tests/test_settlement_monitor.py
- [[read_settlement_signals()]] - code - settlement_monitor.py
- [[run_settlement_monitor()]] - code - settlement_monitor.py
- [[settlement_monitor.py]] - code - settlement_monitor.py
- [[settlement_monitor.py_1]] - code - settlement_monitor.py
- [[test_settlement_monitor.py]] - code - tests/test_settlement_monitor.py
- [[weather_markets._dynamic_lock_in_confidence()]] - code - weather_markets.py
- [[write_settlement_signals writes JSON to signals file.]] - rationale - tests/test_settlement_monitor.py
- [[write_settlement_signals()]] - code - settlement_monitor.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/METAR_Settlement_Monitoring
SORT file.name ASC
```

## Connections to other communities
- 9 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 8 edges to [[_COMMUNITY_Community 211]]
- 6 edges to [[_COMMUNITY_Community 64]]
- 6 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 3 edges to [[_COMMUNITY_Community 388]]
- 3 edges to [[_COMMUNITY_Community 73]]
- 2 edges to [[_COMMUNITY_Community 172]]
- 2 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 2 edges to [[_COMMUNITY_Community 59]]
- 1 edge to [[_COMMUNITY_Community 205]]
- 1 edge to [[_COMMUNITY_METAR Lock-In Confidence Tests]]
- 1 edge to [[_COMMUNITY_Community 236]]
- 1 edge to [[_COMMUNITY_Community 262]]
- 1 edge to [[_COMMUNITY_Community 307]]
- 1 edge to [[_COMMUNITY_Community 51]]
- 1 edge to [[_COMMUNITY_Community 339]]
- 1 edge to [[_COMMUNITY_Weather Probability Math Tests]]
- 1 edge to [[_COMMUNITY_Community 58]]
- 1 edge to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 1 edge to [[_COMMUNITY_Community 47]]
- 1 edge to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 1 edge to [[_COMMUNITY_Backtest Engine & Atomic Writes]]
- 1 edge to [[_COMMUNITY_Community 89]]

## Top bridge nodes
- [[settlement_monitor.py]] - degree 18, connects to 6 communities
- [[fetch_metar()]] - degree 12, connects to 6 communities
- [[_metar_lock_in()]] - degree 17, connects to 5 communities
- [[Phase 2 Batch D Regression Tests]] - degree 10, connects to 5 communities
- [[Phase 2 Batch J Regression Tests]] - degree 9, connects to 5 communities