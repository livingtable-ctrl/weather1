---
type: community
cohesion: 0.06
members: 51
---

# Community 34

**Cohesion:** 0.06 - loosely connected
**Members:** 51 nodes

## Members
- [[dot-_market()]] - code - tests/test_hurricane_markets.py
- [[dot-_market()_1]] - code - tests/test_hurricane_markets.py
- [[dot-_market()_2]] - code - tests/test_hurricane_markets.py
- [[dot-test_cat5_series_parses_correctly()]] - code - tests/test_hurricane_markets.py
- [[dot-test_degraded_hurricane_count_market_does_not_reach_temperature_pipeline()]] - code - tests/test_hurricane_markets.py
- [[dot-test_degraded_hurricane_count_market_fails_closed_at_dispatcher()]] - code - tests/test_hurricane_markets.py
- [[dot-test_degraded_market_fails_closed_at_dispatcher_not_fallthrough()]] - code - tests/test_hurricane_markets.py
- [[dot-test_degraded_market_fails_closed_at_dispatcher_not_fallthrough()_1]] - code - tests/test_hurricane_markets.py
- [[dot-test_dispatches_via_parse_market_condition()]] - code - tests/test_hurricane_markets.py
- [[dot-test_dispatches_via_parse_market_condition()_1]] - code - tests/test_hurricane_markets.py
- [[dot-test_dispatches_via_parse_market_condition()_2]] - code - tests/test_hurricane_markets.py
- [[dot-test_empty_storm_name_fails_closed()]] - code - tests/test_hurricane_markets.py
- [[dot-test_full_valid_market_parses_correctly()]] - code - tests/test_hurricane_markets.py
- [[dot-test_greater_or_equal_is_accepted_defensively()]] - code - tests/test_hurricane_markets.py
- [[dot-test_hurricane_series_parses_correctly()]] - code - tests/test_hurricane_markets.py
- [[dot-test_missing_close_time_does_not_block_the_parse()]] - code - tests/test_hurricane_markets.py
- [[dot-test_missing_close_time_fails_closed()]] - code - tests/test_hurricane_markets.py
- [[dot-test_missing_custom_strike_fails_closed()]] - code - tests/test_hurricane_markets.py
- [[dot-test_missing_floor_strike_returns_none()]] - code - tests/test_hurricane_markets.py
- [[dot-test_no_kt_field_in_condition()]] - code - tests/test_hurricane_markets.py
- [[dot-test_non_hurricane_count_ticker_returns_none_silently()]] - code - tests/test_hurricane_markets.py
- [[dot-test_non_next_event_ticker_returns_none_silently()]] - code - tests/test_hurricane_markets.py
- [[dot-test_non_numeric_floor_strike_returns_none()]] - code - tests/test_hurricane_markets.py
- [[dot-test_non_storm_order_ticker_returns_none_silently()]] - code - tests/test_hurricane_markets.py
- [[dot-test_parses_correctly()]] - code - tests/test_hurricane_markets.py
- [[dot-test_position_matches_the_last_name_in_the_list()]] - code - tests/test_hurricane_markets.py
- [[dot-test_season_year_mismatch_with_close_time_fails_closed()]] - code - tests/test_hurricane_markets.py
- [[dot-test_season_year_mismatched_with_close_time_fails_closed()]] - code - tests/test_hurricane_markets.py
- [[dot-test_season_year_within_one_year_of_close_time_is_accepted()]] - code - tests/test_hurricane_markets.py
- [[dot-test_unexpected_strike_type_fails_closed()]] - code - tests/test_hurricane_markets.py
- [[dot-test_unknown_season_year_fails_closed()]] - code - tests/test_hurricane_markets.py
- [[dot-test_unknown_storm_name_fails_closed()]] - code - tests/test_hurricane_markets.py
- [[dot-test_unparseable_close_time_fails_closed()]] - code - tests/test_hurricane_markets.py
- [[A 1-year mismatch (e.g. a market closing just after a UTC-vs- ticker-local year…]] - rationale - tests/test_hurricane_markets.py
- [[A season_year not yet in _ATLANTIC_STORM_NAMES_BY_SEASON must never silently…]] - rationale - tests/test_hurricane_markets.py
- [[Confirmed live 2026-08-03 every one of these 5 series' open+ settled markets…]] - rationale - tests/test_hurricane_markets.py
- [[End-to-end through the real dispatcher, confirms the branch is actually wired…]] - rationale - tests/test_hurricane_markets.py
- [[End-to-end through the real dispatcher, confirms the branch is actually wired…_1]] - rationale - tests/test_hurricane_markets.py
- [[End-to-end through the real dispatcher, not just the dedicated function…]] - rationale - tests/test_hurricane_markets.py
- [[Every other branch in _parse_market_condition returns None silently for a non-…]] - rationale - tests/test_hurricane_markets.py
- [[Opus-review-caught (2026-08-03) season_year is derived from a bare 2-digit…]] - rationale - tests/test_hurricane_markets.py
- [[Opus-review-caught (2026-08-03, HIGH) a hurricane-count series ticker whose…]] - rationale - tests/test_hurricane_markets.py
- [[Same KXHURCAT-bug-class concern the hurricane-count branch's own test…]] - rationale - tests/test_hurricane_markets.py
- [[Same KXHURCAT-bug-class concern the sibling branches' own tests document a…]] - rationale - tests/test_hurricane_markets.py
- [[Same cross-check discipline _parse_hurricane_count_condition established a…]] - rationale - tests/test_hurricane_markets.py
- [[Same finding as above, exercised through the full analyze_trade() dispatch a…]] - rationale - tests/test_hurricane_markets.py
- [[TestParseHurricaneCountCondition]] - code - tests/test_hurricane_markets.py
- [[TestParseHurricaneNextEventCondition]] - code - tests/test_hurricane_markets.py
- [[TestParseStormOrderCondition]] - code - tests/test_hurricane_markets.py
- [[The cross-check is defense-in-depth, not a hard requirement -- a market with no…]] - rationale - tests/test_hurricane_markets.py
- [[kt is deliberately derived downstream from event_type via…]] - rationale - tests/test_hurricane_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_34
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 90]]

## Top bridge nodes
- [[TestParseHurricaneCountCondition]] - degree 14, connects to 1 community
- [[TestParseStormOrderCondition]] - degree 12, connects to 1 community
- [[TestParseHurricaneNextEventCondition]] - degree 10, connects to 1 community