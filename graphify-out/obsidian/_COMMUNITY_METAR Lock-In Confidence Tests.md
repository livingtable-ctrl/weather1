---
type: community
cohesion: 0.05
members: 56
---

# METAR Lock-In Confidence Tests

**Cohesion:** 0.05 - loosely connected
**Members:** 56 nodes

## Members
- [[dot-_call_metar_lock_in()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_daily_extreme_zero_is_not_treated_as_missing()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_falls_back_to_current_temp_when_daily_extreme_missing()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_hour_boundary_13_vs_14()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_lock_in_reenabled_uses_daily_extreme_not_current_temp()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_low_market_ticker_prefix_selects_min_not_max()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_malformed_condition_missing_bounds_fails_closed()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_no_daily_extreme_blocks_yes_lock()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_no_lock_boundary_just_under_margin_not_locked()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_no_lock_does_not_reintroduce_unsafe_direction_high_market()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_no_lock_does_not_reintroduce_unsafe_direction_low_market()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_no_lock_high_market_daily_high_cleared_upper_margin()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_no_lock_low_market_boundary_margin_not_shrunk()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_no_lock_low_market_daily_low_cleared_lower_margin()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_stale_prior_day_obs_not_locked()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_ticker_ambiguous_not_locked()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_too_early_hour_not_locked()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_yes_lock_boundary_at_exact_midpoint()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_yes_lock_high_market_inside_safe_half()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_yes_lock_low_market_inside_safe_half()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_yes_margin_scales_with_band_width_not_hardcoded()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_between_yes_not_locked_insufficient_clearance()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_dynamic_confidence_increases_with_clearance_generic()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_dynamic_confidence_range()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_no_clearance_scales_with_distance_outside()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_no_lock_confidence_matches_dynamic()]] - code - tests/test_phase2_batch_d.py
- [[dot-test_yes_lock_confidence_matches_dynamic()]] - code - tests/test_phase2_batch_d.py
- [[A between condition missing lowerupper (a malformedsynthetic caller --…]] - rationale - tests/test_phase2_batch_d.py
- [[A LOW-series ticker must read min_temp_f, ignoring max_temp_f even when…]] - rationale - tests/test_phase2_batch_d.py
- [[A METAR observation whose own local date doesn't match target_date (the exact…]] - rationale - tests/test_phase2_batch_d.py
- [[A daily extreme of exactly 0.0°F (a legitimate, if unusual, reading) must be…]] - rationale - tests/test_phase2_batch_d.py
- [[A ticker that says neither HIGH nor LOW (e.g. the  default a caller might…]] - rationale - tests/test_phase2_batch_d.py
- [[Before 1400 local, even a deep-NO daily extreme must not lock.]] - rationale - tests/test_phase2_batch_d.py
- [[Between-market METAR lock-in is RE-ENABLED (backlog.txt BETWEEN- BUCKET…]] - rationale - tests/test_phase2_batch_d.py
- [[Drive _metar_lock_in with fully mocked dependencies.…]] - rationale - tests/test_phase2_batch_d.py
- [[Generic property of _dynamic_lock_in_confidence itself (not tied to the between…]] - rationale - tests/test_phase2_batch_d.py
- [[HIGH-var between market daily-high-so-far = upper+3°F is a safe, monotonic NO…]] - rationale - tests/test_phase2_batch_d.py
- [[HIGH-var between market daily-high-so-far in the band's safer half (closer to…]] - rationale - tests/test_phase2_batch_d.py
- [[Inside a WIDE bucket (half-width 3.0°F, same as the NO-side _margin default)…]] - rationale - tests/test_phase2_batch_d.py
- [[Inside the band but past the midpoint (closer to the at-risk upper edge than…]] - rationale - tests/test_phase2_batch_d.py
- [[LOW-market mirror of the test above a running daily-low-so-far ABOVE the upper…]] - rationale - tests/test_phase2_batch_d.py
- [[LOW-var between market daily-low-so-far = lower-3°F is a safe, monotonic NO…]] - rationale - tests/test_phase2_batch_d.py
- [[LOW-var between market daily-low-so-far in the band's safer half (closer to…]] - rationale - tests/test_phase2_batch_d.py
- [[Mutation-test that _yes_inband_margin is derived as (hi-lo)2, not hardcoded at…]] - rationale - tests/test_phase2_batch_d.py
- [[Mutation-test the 1400 hour boundary directly hour 13 must not lock, hour 14…]] - rationale - tests/test_phase2_batch_d.py
- [[Mutation-test the LOW-side NO margin itself at min_temp_f=61.0, the real 3.0°F…]] - rationale - tests/test_phase2_batch_d.py
- [[Mutation-test the NO boundary 0.01°F under hi+margin must NOT lock (proves the…]] - rationale - tests/test_phase2_batch_d.py
- [[Mutation-test the YES boundary exactly at the band midpoint (risk_clearance ==…]] - rationale - tests/test_phase2_batch_d.py
- [[NO clearance increases with distance outside bucket → higher confidence.]] - rationale - tests/test_phase2_batch_d.py
- [[Outside bucket 3°F confidence must equal _dynamic_lock_in_confidence, not…]] - rationale - tests/test_phase2_batch_d.py
- [[P2-6 between-market METAR lock-in must call _dynamic_lock_in_confidence.]] - rationale - tests/test_phase2_batch_d.py
- [[TestBetweenLockInDynamicConfidence]] - code - tests/test_phase2_batch_d.py
- [[The deleted original implementation's NO branch ALSO fired when the temp was…]] - rationale - tests/test_phase2_batch_d.py
- [[Unlike the NO branches, a YES lock CANNOT safely use the current_temp_f…]] - rationale - tests/test_phase2_batch_d.py
- [[When max_temp_fmin_temp_f is absent from the METAR observation (e.g. a station…]] - rationale - tests/test_phase2_batch_d.py
- [[_dynamic_lock_in_confidence must stay in 0.72, 0.97.]] - rationale - tests/test_phase2_batch_d.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/METAR_Lock-In_Confidence_Tests
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 64]]
- 1 edge to [[_COMMUNITY_METAR Settlement Monitoring]]
- 1 edge to [[_COMMUNITY_Community 51]]

## Top bridge nodes
- [[TestBetweenLockInDynamicConfidence]] - degree 30, connects to 2 communities
- [[dot-_call_metar_lock_in()]] - degree 25, connects to 1 community
- [[dot-test_between_stale_prior_day_obs_not_locked()]] - degree 4, connects to 1 community
- [[dot-test_between_malformed_condition_missing_bounds_fails_closed()]] - degree 3, connects to 1 community