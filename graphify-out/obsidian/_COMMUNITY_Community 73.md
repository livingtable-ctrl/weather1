---
type: community
cohesion: 0.06
members: 32
---

# Community 73

**Cohesion:** 0.06 - loosely connected
**Members:** 32 nodes

## Members
- [[dot-test_celsius_converted_to_fahrenheit()]] - code - tests/test_metar.py
- [[dot-test_dew_point_f_parsed_from_real_dewp_celsius_field()]] - code - tests/test_metar.py
- [[dot-test_max_min_temp_f_parsed_from_real_api_field_names()]] - code - tests/test_metar.py
- [[dot-test_max_min_temp_f_prefers_fahrenheit_field_if_ever_present()]] - code - tests/test_metar.py
- [[dot-test_negative_caches_failure()]] - code - tests/test_metar.py
- [[dot-test_returns_current_temp_f()]] - code - tests/test_metar.py
- [[dot-test_returns_none_for_implausible_high_temp()]] - code - tests/test_metar.py
- [[dot-test_returns_none_for_implausible_low_temp()]] - code - tests/test_metar.py
- [[dot-test_returns_none_on_empty_response()]] - code - tests/test_metar.py
- [[dot-test_returns_none_on_failure()]] - code - tests/test_metar.py
- [[dot-test_returns_none_when_observation_stale()]] - code - tests/test_metar.py
- [[dot-test_returns_none_when_obstime_missing()]] - code - tests/test_metar.py
- [[dot-test_returns_none_when_obstime_unparseable()]] - code - tests/test_metar.py
- [[dot-test_returns_result_when_observation_fresh()]] - code - tests/test_metar.py
- [[A failed fetch must be negative-cached -- a second call within the TTL must not…_2]] - rationale - tests/test_metar.py
- [[Defensive if the API ever adds a Fahrenheit extreme field, prefer it over…]] - rationale - tests/test_metar.py
- [[Grade Audit Module Doc metar.py]] - document - docs/grade_audit/modules/metar.md
- [[If only Celsius provided, convert to Fahrenheit.]] - rationale - tests/test_metar.py
- [[P1-2 observation 30 minutes old → accepted.]] - rationale - tests/test_metar.py
- [[P1-2 observation older than 90 minutes → None.]] - rationale - tests/test_metar.py
- [[P1-2 response with invalid obsTime string → None.]] - rationale - tests/test_metar.py
- [[P1-2 response with no obsTime key → None (no fabricated timestamp).]] - rationale - tests/test_metar.py
- [[P1-2 temperature above 140°F → None (physically impossible).]] - rationale - tests/test_metar.py
- [[P1-2 temperature below -80°F → None (physically impossible).]] - rationale - tests/test_metar.py
- [[Regression for the field-name bug found by opus review of backlog.txt BETWEEN-…]] - rationale - tests/test_metar.py
- [[Regression for the same field-name bug the real payload's dew point field is…]] - rationale - tests/test_metar.py
- [[Return an obsTime string 15 minutes in the past (always within the 90-min…]] - rationale - tests/test_metar.py
- [[TestFetchMetar]] - code - tests/test_metar.py
- [[Tests for METAR same-day lock-in strategy.]] - rationale - tests/test_metar.py
- [[_fresh_obs_time()]] - code - tests/test_metar.py
- [[fetch_metar returns current_temp_f in Fahrenheit.]] - rationale - tests/test_metar.py
- [[test_metar.py]] - code - tests/test_metar.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_73
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_METAR Settlement Monitoring]]
- 2 edges to [[_COMMUNITY_Community 51]]
- 1 edge to [[_COMMUNITY_Community 182]]
- 1 edge to [[_COMMUNITY_Community 211]]
- 1 edge to [[_COMMUNITY_Forecast Persistent Cache]]
- 1 edge to [[_COMMUNITY_Community 399]]
- 1 edge to [[_COMMUNITY_Community 339]]
- 1 edge to [[_COMMUNITY_Community 367]]
- 1 edge to [[_COMMUNITY_Community 91]]
- 1 edge to [[_COMMUNITY_Community 457]]
- 1 edge to [[_COMMUNITY_ML Bias Correction & Audit Plans]]

## Top bridge nodes
- [[test_metar.py]] - degree 16, connects to 10 communities
- [[TestFetchMetar]] - degree 16, connects to 1 community
- [[Grade Audit Module Doc metar.py]] - degree 2, connects to 1 community