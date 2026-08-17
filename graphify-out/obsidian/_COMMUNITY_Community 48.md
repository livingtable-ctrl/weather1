---
type: community
cohesion: 0.09
members: 42
---

# Community 48

**Cohesion:** 0.09 - loosely connected
**Members:** 42 nodes

## Members
- [[dot-test_different_series_not_compared()]] - code - tests/test_consistency.py
- [[dot-test_hourly_directional_markets_excluded()]] - code - tests/test_consistency.py
- [[dot-test_hurricane_count_markets_excluded()]] - code - tests/test_consistency.py
- [[dot-test_hurricane_next_event_exclusion_is_mutation_proof()]] - code - tests/test_consistency.py
- [[dot-test_hurricane_next_event_markets_excluded()]] - code - tests/test_consistency.py
- [[dot-test_monthly_rain_different_cities_not_compared()]] - code - tests/test_consistency.py
- [[dot-test_monthly_rain_different_months_not_compared()]] - code - tests/test_consistency.py
- [[dot-test_monthly_rain_irregular_ladder_size_matches_real_st_petersburg_shape()]] - code - tests/test_consistency.py
- [[dot-test_monthly_rain_markets_do_not_log_date_extraction_warning()]] - code - tests/test_consistency.py
- [[dot-test_monthly_rain_markets_grouped_by_city_and_month_no_violation_when_monotone()]] - code - tests/test_consistency.py
- [[dot-test_monthly_rain_missing_floor_strike_excluded()]] - code - tests/test_consistency.py
- [[dot-test_monthly_rain_unexpected_strike_type_excluded()]] - code - tests/test_consistency.py
- [[dot-test_monthly_rain_violation_detected_and_flagged_shadow()]] - code - tests/test_consistency.py
- [[dot-test_no_violation_when_monotone()]] - code - tests/test_consistency.py
- [[dot-test_single_market_no_violation()]] - code - tests/test_consistency.py
- [[dot-test_storm_order_exclusion_is_mutation_proof()]] - code - tests/test_consistency.py
- [[dot-test_storm_order_markets_excluded()]] - code - tests/test_consistency.py
- [[dot-test_violation_detected()]] - code - tests/test_consistency.py
- [[A rain market missing floor_strike (malformedunexpected API shape) must be…]] - rationale - tests/test_consistency.py
- [[A rain market with strike_type != greater (never observed live, but a real…]] - rationale - tests/test_consistency.py
- [[A single market in a series can't violate monotonicity.]] - rationale - tests/test_consistency.py
- [[If P(70)  P(65) we have a monotonicity violation (free arbitrage).]] - rationale - tests/test_consistency.py
- [[Inverted rain ladder (floor_strike=7 priced HIGHER than floor_strike=1) is a…]] - rationale - tests/test_consistency.py
- [[KXRAINM monthly rain-total ladder market. floor_strikestrike_type shape…]] - rationale - tests/test_consistency.py
- [[Markets from different series should never be compared.]] - rationale - tests/test_consistency.py
- [[Opus-review-caught (2026-08-07, MEDIUM) the test above is NOT actually…]] - rationale - tests/test_consistency.py
- [[Rain markets take a dedicated early branch in _group_markets (see the KXRAINM…]] - rationale - tests/test_consistency.py
- [[Same city, different accrual months must never be pooled -- rain-specific case…]] - rationale - tests/test_consistency.py
- [[Same not-actually-mutation-proof concern the sibling hurricane_next_event test…]] - rationale - tests/test_consistency.py
- [[Scan a list of markets and return all monotonicity violations. Only checks…]] - rationale - consistency.py
- [[St. Petersburg's real July 2026 ladder (live-checked 2026-08-06) has exactly 10…]] - rationale - tests/test_consistency.py
- [[TestConsistency]] - code - tests/test_consistency.py
- [[Thresholds T60, T65, T70 should be monotone (higher temp = lower prob of…]] - rationale - tests/test_consistency.py
- [[Two different rain cities in the same month must never be pooled into one group…]] - rationale - tests/test_consistency.py
- [[_market()_1]] - code - tests/test_consistency.py
- [[_rain_market()_1]] - code - tests/test_consistency.py
- [[backlog.txt HOURLY-DIRECTIONAL TEMPERATURE MARKETS Step 1 KXTEMPxxxH…]] - rationale - tests/test_consistency.py
- [[backlog.txt HURRICANE MARKETS -- season-count model (2026-08-03, opus-review-…]] - rationale - tests/test_consistency.py
- [[backlog.txt HURRICANE MARKETS -- storm-order model (2026-08-07)…]] - rationale - tests/test_consistency.py
- [[backlog.txt HURRICANE MARKETS -- time-to-next-event model (2026-08-07)…]] - rationale - tests/test_consistency.py
- [[backlog.txt RAIN MARKETS -- CONSISTENCY.PY'S ARBITRAGE CHECK STILL BLANKET-…_2]] - rationale - tests/test_consistency.py
- [[find_violations()]] - code - consistency.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_48
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Community 363]]
- 3 edges to [[_COMMUNITY_Community 0]]
- 2 edges to [[_COMMUNITY_Community 3]]
- 2 edges to [[_COMMUNITY_Community 313]]
- 1 edge to [[_COMMUNITY_Community 17]]
- 1 edge to [[_COMMUNITY_Community 1]]
- 1 edge to [[_COMMUNITY_Community 312]]
- 1 edge to [[_COMMUNITY_Community 81]]
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[find_violations()]] - degree 32, connects to 9 communities
- [[TestConsistency]] - degree 19, connects to 1 community
- [[_market()_1]] - degree 11, connects to 1 community
- [[_rain_market()_1]] - degree 10, connects to 1 community