---
source_file: "tests/test_phase2_batch_d.py"
type: "code"
community: "Community 22"
location: "L23"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Community_22
---

# ._call_metar_lock_in()

## Connections
- [[dot-test_between_daily_extreme_zero_is_not_treated_as_missing()]] - `calls` [EXTRACTED]
- [[dot-test_between_falls_back_to_current_temp_when_daily_extreme_missing()]] - `calls` [EXTRACTED]
- [[dot-test_between_hour_boundary_13_vs_14()]] - `calls` [EXTRACTED]
- [[dot-test_between_lock_in_reenabled_uses_daily_extreme_not_current_temp()]] - `calls` [EXTRACTED]
- [[dot-test_between_low_market_ticker_prefix_selects_min_not_max()]] - `calls` [EXTRACTED]
- [[dot-test_between_no_daily_extreme_blocks_yes_lock()]] - `calls` [EXTRACTED]
- [[dot-test_between_no_lock_boundary_just_under_margin_not_locked()]] - `calls` [EXTRACTED]
- [[dot-test_between_no_lock_does_not_reintroduce_unsafe_direction_high_market()]] - `calls` [EXTRACTED]
- [[dot-test_between_no_lock_does_not_reintroduce_unsafe_direction_low_market()]] - `calls` [EXTRACTED]
- [[dot-test_between_no_lock_high_market_daily_high_cleared_upper_margin()]] - `calls` [EXTRACTED]
- [[dot-test_between_no_lock_low_market_boundary_margin_not_shrunk()]] - `calls` [EXTRACTED]
- [[dot-test_between_no_lock_low_market_daily_low_cleared_lower_margin()]] - `calls` [EXTRACTED]
- [[dot-test_between_stale_prior_day_obs_not_locked()]] - `calls` [EXTRACTED]
- [[dot-test_between_ticker_ambiguous_not_locked()]] - `calls` [EXTRACTED]
- [[dot-test_between_too_early_hour_not_locked()]] - `calls` [EXTRACTED]
- [[dot-test_between_yes_lock_boundary_at_exact_midpoint()]] - `calls` [EXTRACTED]
- [[dot-test_between_yes_lock_high_market_inside_safe_half()]] - `calls` [EXTRACTED]
- [[dot-test_between_yes_lock_low_market_inside_safe_half()]] - `calls` [EXTRACTED]
- [[dot-test_between_yes_margin_scales_with_band_width_not_hardcoded()]] - `calls` [EXTRACTED]
- [[dot-test_between_yes_not_locked_insufficient_clearance()]] - `calls` [EXTRACTED]
- [[dot-test_no_lock_confidence_matches_dynamic()]] - `calls` [EXTRACTED]
- [[dot-test_yes_lock_confidence_matches_dynamic()]] - `calls` [EXTRACTED]
- [[Drive _metar_lock_in with fully mocked dependencies.…]] - `rationale_for` [EXTRACTED]
- [[TestBetweenLockInDynamicConfidence]] - `method` [EXTRACTED]
- [[ZoneInfo]] - `calls` [INFERRED]

#graphify/code #graphify/EXTRACTED #community/Community_22