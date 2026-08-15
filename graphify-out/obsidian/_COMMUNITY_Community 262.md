---
type: community
cohesion: 0.14
members: 14
---

# Community 262

**Cohesion:** 0.14 - loosely connected
**Members:** 14 nodes

## Members
- [[dot-test_b_ticker_locks_yes_from_max_temp_despite_evening_cooling()]] - code - tests/test_settlement_monitor.py
- [[dot-test_b_ticker_malformed_band_missing_bounds_fails_closed()]] - code - tests/test_settlement_monitor.py
- [[dot-test_b_ticker_no_signal_when_max_temp_unavailable_despite_in_band_reading()]] - code - tests/test_settlement_monitor.py
- [[dot-test_b_ticker_outside_near_edge_not_locked()]] - code - tests/test_settlement_monitor.py
- [[dot-test_b_ticker_yes_signal_when_max_temp_inside()]] - code - tests/test_settlement_monitor.py
- [[dot-test_t_ticker_still_works_as_before()]] - code - tests/test_settlement_monitor.py
- [[A between market dict missing 'lower''upper' must be skipped, not silently…]] - rationale - tests/test_settlement_monitor.py
- [[AC3 regression guard at the check_city_settlement integration level an in-band…]] - rationale - tests/test_settlement_monitor.py
- [[B-ticker (between-bucket) detection in check_city_settlement.]] - rationale - tests/test_settlement_monitor.py
- [[B-ticker locked YES when the real daily high (from fetch_metar_daily_extreme,…]] - rationale - tests/test_settlement_monitor.py
- [[B-ticker market with daily high just outside band (clearance  2°F) → no signal.]] - rationale - tests/test_settlement_monitor.py
- [[Integration-level version of the entry's own failure scenario real daily high…]] - rationale - tests/test_settlement_monitor.py
- [[T-ticker (abovebelow) markets are unaffected by the B-ticker changes.]] - rationale - tests/test_settlement_monitor.py
- [[TestBTickerParsing]] - code - tests/test_settlement_monitor.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_262
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_METAR Settlement Monitoring]]

## Top bridge nodes
- [[TestBTickerParsing]] - degree 8, connects to 1 community