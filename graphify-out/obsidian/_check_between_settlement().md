---
source_file: "settlement_monitor.py"
type: "code"
community: "METAR Settlement Monitoring"
location: "L164"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/METAR_Settlement_Monitoring
---

# _check_between_settlement()

## Connections
- [[dot-test_max_temp_at_exact_no_margin_boundary_locks_no()]] - `calls` [EXTRACTED]
- [[dot-test_max_temp_at_yes_margin_boundary_locks_yes()]] - `calls` [EXTRACTED]
- [[dot-test_max_temp_cleared_upper_edge_with_margin_locks_no()]] - `calls` [EXTRACTED]
- [[dot-test_max_temp_inside_band_with_full_clearance_locks_yes()]] - `calls` [EXTRACTED]
- [[dot-test_max_temp_just_under_no_margin_not_locked()]] - `calls` [EXTRACTED]
- [[dot-test_max_temp_just_under_yes_margin_not_locked()]] - `calls` [EXTRACTED]
- [[dot-test_no_lock_fallback_stays_unlocked_when_current_temp_below_band()]] - `calls` [EXTRACTED]
- [[dot-test_no_lock_falls_back_to_current_temp_when_max_temp_unavailable()]] - `calls` [EXTRACTED]
- [[dot-test_running_high_inside_band_locks_yes_despite_evening_cooling()]] - `calls` [EXTRACTED]
- [[dot-test_running_high_still_below_band_stays_uncertain_not_locked()]] - `calls` [EXTRACTED]
- [[dot-test_yes_requires_real_max_temp_not_current_temp_fallback()]] - `calls` [EXTRACTED]
- [[Determine settlement outcome for a between-bucket market. Returns a dict with…]] - `rationale_for` [EXTRACTED]
- [[_metar_lock_in()]] - `conceptually_related_to` [EXTRACTED]
- [[check_city_settlement()]] - `calls` [EXTRACTED]
- [[fetch_metar_daily_extreme()]] - `references` [EXTRACTED]
- [[settlement_monitor.py]] - `contains` [EXTRACTED]
- [[settlement_monitor.py_1]] - `implements` [EXTRACTED]
- [[test_settlement_monitor.py]] - `calls` [EXTRACTED]
- [[weather_markets._dynamic_lock_in_confidence()]] - `conceptually_related_to` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/METAR_Settlement_Monitoring