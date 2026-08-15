---
type: community
cohesion: 0.06
members: 36
---

# Community 61

**Cohesion:** 0.06 - loosely connected
**Members:** 36 nodes

## Members
- [[dot-test_confirms_old_parsers_still_falsely_resolve()]] - code - tests/test_hurricane_gating.py
- [[dot-test_daily_high_ticker_unaffected()]] - code - tests/test_hurricane_gating.py
- [[dot-test_hurricane_category_ticker_gates_out_explicitly()]] - code - tests/test_hurricane_gating.py
- [[dot-test_hurricane_count_ticker_no_longer_blanket_gated()]] - code - tests/test_hurricane_gating.py
- [[dot-test_hurricane_landfall_ticker_gates_out_explicitly()]] - code - tests/test_hurricane_gating.py
- [[dot-test_kxfirsthurricane_dispatches_to_the_real_model_end_to_end()]] - code - tests/test_hurricane_gating.py
- [[dot-test_kxfirsthurricane_no_longer_blanket_gated()]] - code - tests/test_hurricane_gating.py
- [[dot-test_kxnamedstorm_no_longer_blanket_gated()]] - code - tests/test_hurricane_gating.py
- [[dot-test_kxnextcat5hurdate_no_longer_blanket_gated()]] - code - tests/test_hurricane_gating.py
- [[dot-test_kxnexthurdate_dispatches_to_the_real_model_end_to_end()]] - code - tests/test_hurricane_gating.py
- [[dot-test_kxnexthurdate_no_longer_blanket_gated()]] - code - tests/test_hurricane_gating.py
- [[dot-test_kxnexthurdate_past_close_time_gates_out_via_own_check()]] - code - tests/test_hurricane_gating.py
- [[dot-test_kxtropstorm_no_longer_blanket_gated()]] - code - tests/test_hurricane_gating.py
- [[dot-test_legacy_unprefixed_hur_ticker_gates_out()]] - code - tests/test_hurricane_gating.py
- [[dot-test_rain_ticker_unaffected()]] - code - tests/test_hurricane_gating.py
- [[dot-test_snow_storm_ticker_unaffected()]] - code - tests/test_hurricane_gating.py
- [[A next-event ticker whose close_time has already passed must be caught by its…]] - rationale - tests/test_hurricane_gating.py
- [[Ground the whole test class the parsers this guard replaces as the safety…]] - rationale - tests/test_hurricane_gating.py
- [[Live-confirmed real ticker with 53 open markets as of 2026-07-26 -- also missed…]] - rationale - tests/test_hurricane_gating.py
- [[Live-confirmed real ticker with 8 open markets as of 2026-07-26 -- the original…]] - rationale - tests/test_hurricane_gating.py
- [[Now one of the 5 season-count series with a real model (2026-08-03) -- same…]] - rationale - tests/test_hurricane_gating.py
- [[Opus-review-caught every other test in this file (and the two…]] - rationale - tests/test_hurricane_gating.py
- [[Regression control for the specific false-positive risk a substring-based check…]] - rationale - tests/test_hurricane_gating.py
- [[Regression control an ordinary daily HIGH ticker must still reach its normal…]] - rationale - tests/test_hurricane_gating.py
- [[Regression control the hurricane marker check must not accidentally collide…]] - rationale - tests/test_hurricane_gating.py
- [[Same reach the real dispatch through the public entry point, not just the…]] - rationale - tests/test_hurricane_gating.py
- [[TestAnalyzeTradeHurricaneGating]] - code - tests/test_hurricane_gating.py
- [[Tests for backlog.txt HURRICANE MARKETS an explicit is_hurricane_ticker()…]] - rationale - tests/test_hurricane_gating.py
- [[The exact reproduction case the second opus review found live HURCAT (no KX…]] - rationale - tests/test_hurricane_gating.py
- [[The other real hurricane shape per-city landfall series (KXHURMIA-style),…]] - rationale - tests/test_hurricane_gating.py
- [[The real, live-confirmed tickertitlestrike shape that defeated the old…]] - rationale - tests/test_hurricane_gating.py
- [[_faustro_hurricane_market()]] - code - tests/test_hurricane_gating.py
- [[backlog.txt HURRICANE MARKETS -- season-count model (2026-08-03) KXHURCTOT…]] - rationale - tests/test_hurricane_gating.py
- [[backlog.txt HURRICANE MARKETS -- time-to-next-event model (2026-08-07)…_1]] - rationale - tests/test_hurricane_gating.py
- [[is_hurricane_ticker() blanket guard]] - code - weather_markets.py
- [[test_hurricane_gating.py]] - code - tests/test_hurricane_gating.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_61
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 2 edges to [[_COMMUNITY_Community 55]]
- 1 edge to [[_COMMUNITY_Community 425]]
- 1 edge to [[_COMMUNITY_Community 397]]
- 1 edge to [[_COMMUNITY_Community 90]]

## Top bridge nodes
- [[test_hurricane_gating.py]] - degree 11, connects to 5 communities