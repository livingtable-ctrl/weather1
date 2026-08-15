---
type: community
cohesion: 0.05
members: 44
---

# Community 43

**Cohesion:** 0.05 - loosely connected
**Members:** 44 nodes

## Members
- [[apibrier_history returns a JSON list of {week, brier} dicts.]] - rationale - tests/test_web_app.py
- [[apiconfig must surface both kalshi_fee_rate (taker, reference) and…]] - rationale - tests/test_web_app.py
- [[apiforecast_quality returns city_heatmap and source_reliability keys.]] - rationale - tests/test_web_app.py
- [[apigraduation returns trades_done, win_rate, ready, fear_greed_score,…]] - rationale - tests/test_web_app.py
- [[apirisk returns city_exposure, directional, expiry_clustering, total_exposure.]] - rationale - tests/test_web_app.py
- [[apisignals returns log and alerts keys.]] - rationale - tests/test_web_app.py
- [[apitrades returns open and closed keys as lists.]] - rationale - tests/test_web_app.py
- [[range=1mo returns only points from the last 30 days.]] - rationale - tests/test_web_app.py
- [[range=3mo returns a different (longer) slice than the default 50-point cap.]] - rationale - tests/test_web_app.py
- [[range=all returns all points.]] - rationale - tests/test_web_app.py
- [[Analytics page returns 200 and contains 'Analytics'.]] - rationale - tests/test_web_app.py
- [[Dashboard page returns 200 and contains 'Dashboard'.]] - rationale - tests/test_web_app.py
- [[Forecast page returns 200 and contains 'Forecast'.]] - rationale - tests/test_web_app.py
- [[GET apimodel-attribution returns JSON with at least one city key, each city…]] - rationale - tests/test_web_app.py
- [[GET apiprice-improvement returns JSON with avg_improvement_cents and…]] - rationale - tests/test_web_app.py
- [[GET apistreammarkets returns Content-Type textevent-stream.]] - rationale - tests/test_web_app.py
- [[Risk page returns 200 and contains 'Risk'.]] - rationale - tests/test_web_app.py
- [[Signals page returns 200 and contains 'Signals'.]] - rationale - tests/test_web_app.py
- [[Tests for web_app.py dashboard API endpoints.]] - rationale - tests/test_web_app.py
- [[Trades page returns 200 and contains 'Trades'.]] - rationale - tests/test_web_app.py
- [[_build_stream_data includes markets key.]] - rationale - tests/test_web_app.py
- [[_get_live_market_snapshot returns list even with no data.]] - rationale - tests/test_web_app.py
- [[test_analytics_route_returns_200_with_title()]] - code - tests/test_web_app.py
- [[test_api_brier_history_returns_list()]] - code - tests/test_web_app.py
- [[test_api_config_includes_both_fee_rates()]] - code - tests/test_web_app.py
- [[test_api_forecast_quality_returns_correct_shape()]] - code - tests/test_web_app.py
- [[test_api_graduation_returns_correct_shape()]] - code - tests/test_web_app.py
- [[test_api_risk_returns_correct_shape()]] - code - tests/test_web_app.py
- [[test_api_signals_returns_correct_shape()]] - code - tests/test_web_app.py
- [[test_api_trades_returns_correct_shape()]] - code - tests/test_web_app.py
- [[test_balance_history_range_1mo()]] - code - tests/test_web_app.py
- [[test_balance_history_range_3mo_longer_than_default()]] - code - tests/test_web_app.py
- [[test_balance_history_range_all()]] - code - tests/test_web_app.py
- [[test_build_stream_data_has_markets_key()]] - code - tests/test_web_app.py
- [[test_dashboard_route_returns_200_with_title()]] - code - tests/test_web_app.py
- [[test_forecast_route_returns_200_with_title()]] - code - tests/test_web_app.py
- [[test_get_live_market_snapshot_returns_list()]] - code - tests/test_web_app.py
- [[test_model_attribution_endpoint_returns_city_keys()]] - code - tests/test_web_app.py
- [[test_price_improvement_endpoint_returns_valid_json()]] - code - tests/test_web_app.py
- [[test_risk_route_returns_200_with_title()]] - code - tests/test_web_app.py
- [[test_signals_route_returns_200_with_title()]] - code - tests/test_web_app.py
- [[test_stream_markets_content_type()]] - code - tests/test_web_app.py
- [[test_trades_route_returns_200_with_title()]] - code - tests/test_web_app.py
- [[test_web_app.py]] - code - tests/test_web_app.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_43
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 2 edges to [[_COMMUNITY_Community 579]]
- 1 edge to [[_COMMUNITY_Community 416]]
- 1 edge to [[_COMMUNITY_Community 493]]
- 1 edge to [[_COMMUNITY_Community 532]]
- 1 edge to [[_COMMUNITY_Community 562]]
- 1 edge to [[_COMMUNITY_Community 638]]
- 1 edge to [[_COMMUNITY_Community 639]]
- 1 edge to [[_COMMUNITY_Community 640]]
- 1 edge to [[_COMMUNITY_Community 641]]
- 1 edge to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 1 edge to [[_COMMUNITY_Community 176]]
- 1 edge to [[_COMMUNITY_Community 52]]

## Top bridge nodes
- [[test_web_app.py]] - degree 38, connects to 13 communities
- [[test_build_stream_data_has_markets_key()]] - degree 3, connects to 1 community
- [[test_get_live_market_snapshot_returns_list()]] - degree 3, connects to 1 community