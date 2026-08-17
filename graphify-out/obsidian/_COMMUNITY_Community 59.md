---
type: community
cohesion: 0.07
members: 36
---

# Community 59

**Cohesion:** 0.07 - loosely connected
**Members:** 36 nodes

## Members
- [[-999 (HURDAT2's missing-value sentinel) must never be treated as a real wind…]] - rationale - tests/test_hurricane_climatology.py
- [[dot-test_absurdly_high_wind_rejected()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_basin_and_year_extracted_from_id()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_calendar_year_with_zero_storms_counts_as_zero_not_dropped()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_cat5_threshold_day_captured()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_counts_only_storms_that_crossed_threshold_by_that_day()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_end_year_defaults_to_last_year_from_real_clock()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_hurricane_count_is_a_subset_of_tropical_storm_count()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_leap_year_alignment_not_off_by_one()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_matches_hand_computed_counts_per_year()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_max_wind_is_the_storm_peak()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_missing_wind_sentinel_excluded()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_never_exceeds_season_end_count()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_parses_all_storms()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_remaining_is_never_negative()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_storm_with_all_missing_wind_has_none_max()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_threshold_day_is_first_crossing_not_max_day()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_tilted_mode_adds_current_count_to_historical_remaining()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_truncated_file_does_not_crash()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_unconditional_mode_returns_raw_season_end_counts()]] - code - tests/test_hurricane_climatology.py
- [[dot-test_window_years_caps_history_to_most_recent()]] - code - tests/test_hurricane_climatology.py
- [[A header claiming more rows than actually exist (corrupt truncated download)…]] - rationale - tests/test_hurricane_climatology.py
- [[AL012001 crosses 34kt on Aug 1 and 64kt on Aug 5 -- threshold_day must record…]] - rationale - tests/test_hurricane_climatology.py
- [[Every count type is at least this strength, cumulative -- a storm counted as…]] - rationale - tests/test_hurricane_climatology.py
- [[For each historical year, remaining = season_end - to_date(same monthday);…]] - rationale - tests/test_hurricane_climatology.py
- [[Opus-review-caught (2026-08-03, real live CPAC bias) the window must be built…]] - rationale - tests/test_hurricane_climatology.py
- [[Opus-review-caught comparing raw tm_yday ordinals across a leapnon-leap year…]] - rationale - tests/test_hurricane_climatology.py
- [[Opus-review-caught only the exact -999 sentinel was rejected -- a corrupted…]] - rationale - tests/test_hurricane_climatology.py
- [[Sanity check the default (no explicit end_year) doesn't crash and produces a…]] - rationale - tests/test_hurricane_climatology.py
- [[TestCountAsOfDay]] - code - tests/test_hurricane_climatology.py
- [[TestParseHurdat2]] - code - tests/test_hurricane_climatology.py
- [[TestSeasonEndCounts]] - code - tests/test_hurricane_climatology.py
- [[TestSeasonEndTotalDistribution]] - code - tests/test_hurricane_climatology.py
- [[_fixture_storms()]] - code - tests/test_hurricane_climatology.py
- [[count_as_of_day is always = season_end_counts by construction, so remaining =…]] - rationale - tests/test_hurricane_climatology.py
- [[threshold_day is built from the union of COUNT_THRESHOLDS_KT (346496) and…]] - rationale - tests/test_hurricane_climatology.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_59
SORT file.name ASC
```

## Connections to other communities
- 6 edges to [[_COMMUNITY_Community 43]]

## Top bridge nodes
- [[_fixture_storms()]] - degree 15, connects to 1 community
- [[TestParseHurdat2]] - degree 10, connects to 1 community
- [[TestSeasonEndTotalDistribution]] - degree 7, connects to 1 community
- [[TestCountAsOfDay]] - degree 4, connects to 1 community
- [[TestSeasonEndCounts]] - degree 3, connects to 1 community