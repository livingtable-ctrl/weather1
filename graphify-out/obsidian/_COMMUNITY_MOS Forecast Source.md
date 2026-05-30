---
type: community
cohesion: 0.05
members: 50
---

# MOS Forecast Source

**Cohesion:** 0.05 - loosely connected
**Members:** 50 nodes

## Members
- [[._make_trade()_1]] - code - tests/test_phase2_batch_a.py
- [[.test_M_returns_none()]] - code - tests/test_phase2_batch_a.py
- [[.test_T_returns_none()]] - code - tests/test_phase2_batch_a.py
- [[.test_all_M_codes_returns_none()]] - code - tests/test_phase2_batch_a.py
- [[.test_empty_string_returns_none()]] - code - tests/test_phase2_batch_a.py
- [[.test_is_streak_paused_uses_settled_at_for_magnitude_check()]] - code - tests/test_phase2_batch_a.py
- [[.test_na_returns_none()]] - code - tests/test_phase2_batch_a.py
- [[.test_no_warning_when_env_var_set()]] - code - tests/test_phase2_batch_a.py
- [[.test_no_warning_when_no_file_exists()]] - code - tests/test_phase2_batch_a.py
- [[.test_none_returns_none()]] - code - tests/test_phase2_batch_a.py
- [[.test_rows_with_M_code_are_excluded()]] - code - tests/test_phase2_batch_a.py
- [[.test_sort_key_falls_back_to_entered_at_when_no_settled_at()]] - code - tests/test_phase2_batch_a.py
- [[.test_unknown_code_returns_none()]] - code - tests/test_phase2_batch_a.py
- [[.test_valid_float_string_returns_float()]] - code - tests/test_phase2_batch_a.py
- [[.test_valid_int_returns_float()]] - code - tests/test_phase2_batch_a.py
- [[.test_value_clamped_to_safety_bounds()]] - code - tests/test_phase2_batch_a.py
- [[.test_warns_when_loaded_from_walk_forward_json()]] - code - tests/test_phase2_batch_a.py
- [[B2 Fetch MOS using the best available model for the given days_out.     For da]] - rationale - mos.py
- [[Fetch MOS forecast for a station from the IEM API.      Args         station]] - rationale - mos.py
- [[NOAA MOS (Model Output Statistics) via Iowa Environmental Mesonet API. Station-]] - rationale - mos.py
- [[No file warning when PAPER_MIN_EDGE is set via env var.]] - rationale - tests/test_phase2_batch_a.py
- [[No warning when neither file nor env var — returns hardcoded 0.05.]] - rationale - tests/test_phase2_batch_a.py
- [[P2-11 _parse_temp must handle ASOS special codes without crashing.]] - rationale - tests/test_phase2_batch_a.py
- [[P2-11 fetch_mos must exclude rows with ASOS special temp codes.]] - rationale - tests/test_phase2_batch_a.py
- [[P2-3 is_streak_paused must sort by settled_at when computing streak PnL.]] - rationale - tests/test_phase2_batch_a.py
- [[P2-3 is_streak_paused must sort trades by settled_at, not entered_at.]] - rationale - tests/test_phase2_batch_a.py
- [[P2-9 _paper_min_edge_default must log a warning when loading from file.]] - rationale - tests/test_phase2_batch_a.py
- [[Parse MOS temperature field, handling ASOS special codes.]] - rationale - mos.py
- [[Phase 2 Batch A regression tests P2-3, P2-8, P2-9, P2-11.]] - rationale - tests/test_phase2_batch_a.py
- [[Return True if a fresh MOS cache entry exists for this stationdate (no network]] - rationale - mos.py
- [[Return the ASOS station code for a city, or None if unknown.]] - rationale - mos.py
- [[TestFetchMosSpecialCodes]] - code - tests/test_phase2_batch_a.py
- [[TestMosParseTemp]] - code - tests/test_phase2_batch_a.py
- [[TestPaperMinEdgeWarning]] - code - tests/test_phase2_batch_a.py
- [[TestStreakPausedSortOrder]] - code - tests/test_phase2_batch_a.py
- [[Trades without settled_at fall back to entered_at without crashing.]] - rationale - tests/test_phase2_batch_a.py
- [[Value from file is returned as-is (within 0.03–0.15 bounds already enforced).]] - rationale - tests/test_phase2_batch_a.py
- [[_parse_temp()]] - code - mos.py
- [[bool_16]] - code - mos.py
- [[date_3]] - code - mos.py
- [[fetch_mos()]] - code - mos.py
- [[fetch_mos_best()]] - code - mos.py
- [[float_20]] - code - mos.py
- [[float_41]] - code - tests/test_phase2_batch_a.py
- [[get_mos_station()]] - code - mos.py
- [[is_mos_cached()]] - code - mos.py
- [[mos.py]] - code - mos.py
- [[str_19]] - code - mos.py
- [[str_48]] - code - tests/test_phase2_batch_a.py
- [[test_phase2_batch_a.py]] - code - tests/test_phase2_batch_a.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/MOS_Forecast_Source
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Module tests]]
- 2 edges to [[_COMMUNITY_Kelly Criterion Sizing]]

## Top bridge nodes
- [[test_phase2_batch_a.py]] - degree 8, connects to 1 community
- [[fetch_mos()]] - degree 7, connects to 1 community
- [[mos.py]] - degree 7, connects to 1 community
- [[fetch_mos_best()]] - degree 6, connects to 1 community