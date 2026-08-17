---
type: community
cohesion: 0.08
members: 26
---

# Community 115

**Cohesion:** 0.08 - loosely connected
**Members:** 26 nodes

## Members
- [[apiforecast_quality returns city_heatmap and source_reliability keys.]] - rationale - tests/test_web_app.py
- [[apisignals returns log and alerts keys.]] - rationale - tests/test_web_app.py
- [[apitrades returns open and closed keys as lists.]] - rationale - tests/test_web_app.py
- [[range=1mo returns only points from the last 30 days.]] - rationale - tests/test_web_app.py
- [[range=3mo returns a different (longer) slice than the default 50-point cap.]] - rationale - tests/test_web_app.py
- [[range=3mo returns only points from the last 90 days.]] - rationale - tests/test_web_app.py
- [[Dashboard page returns 200 and contains 'Dashboard'.]] - rationale - tests/test_web_app.py
- [[Forecast page returns 200 and contains 'Forecast'.]] - rationale - tests/test_web_app.py
- [[GET apimodel-attribution returns JSON with at least one city key, each city…]] - rationale - tests/test_web_app.py
- [[GET apiprice-improvement returns JSON with avg_improvement_cents and…]] - rationale - tests/test_web_app.py
- [[GET apistreammarkets returns Content-Type textevent-stream.]] - rationale - tests/test_web_app.py
- [[Risk page returns 200 and contains 'Risk'.]] - rationale - tests/test_web_app.py
- [[Tests for web_app.py dashboard API endpoints.]] - rationale - tests/test_web_app.py
- [[test_api_forecast_quality_returns_correct_shape()]] - code - tests/test_web_app.py
- [[test_api_signals_returns_correct_shape()]] - code - tests/test_web_app.py
- [[test_api_trades_returns_correct_shape()]] - code - tests/test_web_app.py
- [[test_balance_history_range_1mo()]] - code - tests/test_web_app.py
- [[test_balance_history_range_3mo()]] - code - tests/test_web_app.py
- [[test_balance_history_range_3mo_longer_than_default()]] - code - tests/test_web_app.py
- [[test_dashboard_route_returns_200_with_title()]] - code - tests/test_web_app.py
- [[test_forecast_route_returns_200_with_title()]] - code - tests/test_web_app.py
- [[test_model_attribution_endpoint_returns_city_keys()]] - code - tests/test_web_app.py
- [[test_price_improvement_endpoint_returns_valid_json()]] - code - tests/test_web_app.py
- [[test_risk_route_returns_200_with_title()]] - code - tests/test_web_app.py
- [[test_stream_markets_content_type()]] - code - tests/test_web_app.py
- [[test_web_app.py]] - code - tests/test_web_app.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_115
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 590]]
- 2 edges to [[_COMMUNITY_Community 4]]
- 1 edge to [[_COMMUNITY_Community 196]]
- 1 edge to [[_COMMUNITY_Community 332]]
- 1 edge to [[_COMMUNITY_Community 455]]
- 1 edge to [[_COMMUNITY_Community 535]]
- 1 edge to [[_COMMUNITY_Community 643]]
- 1 edge to [[_COMMUNITY_Community 658]]
- 1 edge to [[_COMMUNITY_Community 738]]
- 1 edge to [[_COMMUNITY_Community 739]]
- 1 edge to [[_COMMUNITY_Community 740]]
- 1 edge to [[_COMMUNITY_Community 741]]
- 1 edge to [[_COMMUNITY_Community 742]]
- 1 edge to [[_COMMUNITY_Community 743]]
- 1 edge to [[_COMMUNITY_Community 744]]
- 1 edge to [[_COMMUNITY_Community 745]]
- 1 edge to [[_COMMUNITY_Community 746]]
- 1 edge to [[_COMMUNITY_Community 747]]
- 1 edge to [[_COMMUNITY_Community 748]]
- 1 edge to [[_COMMUNITY_Community 749]]
- 1 edge to [[_COMMUNITY_Community 6]]

## Top bridge nodes
- [[test_web_app.py]] - degree 37, connects to 21 communities