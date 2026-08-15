---
type: community
cohesion: 0.11
members: 23
---

# Community 131

**Cohesion:** 0.11 - loosely connected
**Members:** 23 nodes

## Members
- [[dot-test_nws_prob_at_median_is_near_half()]] - code - tests/test_nbm.py
- [[dot-test_nws_prob_below_is_complement_of_above()]] - code - tests/test_nbm.py
- [[dot-test_nws_prob_empty_quantiles_returns_half()]] - code - tests/test_nbm.py
- [[dot-test_nws_prob_uses_quantiles_above()]] - code - tests/test_nbm.py
- [[A live-network exception inside the NBM-quantile fetch must not take down the…]] - rationale - tests/test_weather_markets.py
- [[Compute probability from NBM native quantiles using linear ECDF interpolation.…]] - rationale - nws.py
- [[Empty quantile dict should return 0.5 as a safe fallback.]] - rationale - tests/test_nbm.py
- [[No NBP coverage for this stationdate (mos.fetch_nbm_quantiles returns None)…]] - rationale - tests/test_weather_markets.py
- [[P(T  threshold) + P(T  threshold) should approximately equal 1.]] - rationale - tests/test_nbm.py
- [[P(T  median) should be ~0.50 by definition.]] - rationale - tests/test_nbm.py
- [[Regression guard for backlog.txt SEVERAL test_weather_markets.py analyze_trade…]] - rationale - tests/test_weather_markets.py
- [[Shared enriched-market fixture for the nbm_quantile_prob tests below (paired…]] - rationale - tests/test_weather_markets.py
- [[Shared mocks for the nbm_quantile_prob tests below -- same baseline as the…]] - rationale - tests/test_weather_markets.py
- [[TestNBMQuantiles]] - code - tests/test_nbm.py
- [[_analyze_trade_base_mocks()]] - code - tests/test_weather_markets.py
- [[_analyze_trade_enriched_fixture()]] - code - tests/test_weather_markets.py
- [[backlog.txt NBM PROBABILISTIC QUANTILES when mos.fetch_nbm_quantiles returns…]] - rationale - tests/test_weather_markets.py
- [[nws_prob_from_quantiles uses ECDF interpolation for above condition.]] - rationale - tests/test_nbm.py
- [[nws_prob_from_quantiles()]] - code - nws.py
- [[test_analyze_trade_makes_no_real_nws_mos_or_climate_indices_calls()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_nbm_quantile_fetch_exception_does_not_break_analysis()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_result_nbm_quantile_prob_none_when_no_coverage()]] - code - tests/test_weather_markets.py
- [[test_analyze_trade_result_surfaces_nbm_quantile_prob()]] - code - tests/test_weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_131
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_Ensemble Weight Blending Tests]]
- 6 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 2 edges to [[_COMMUNITY_Community 123]]
- 2 edges to [[_COMMUNITY_Community 182]]
- 1 edge to [[_COMMUNITY_Community 51]]
- 1 edge to [[_COMMUNITY_Community 99]]
- 1 edge to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 1 edge to [[_COMMUNITY_Community 331]]

## Top bridge nodes
- [[nws_prob_from_quantiles()]] - degree 15, connects to 7 communities
- [[TestNBMQuantiles]] - degree 6, connects to 2 communities
- [[test_analyze_trade_result_surfaces_nbm_quantile_prob()]] - degree 6, connects to 2 communities
- [[test_analyze_trade_makes_no_real_nws_mos_or_climate_indices_calls()]] - degree 5, connects to 2 communities
- [[test_analyze_trade_nbm_quantile_fetch_exception_does_not_break_analysis()]] - degree 5, connects to 2 communities