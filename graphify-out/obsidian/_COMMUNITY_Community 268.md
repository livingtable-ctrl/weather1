---
type: community
cohesion: 0.19
members: 14
---

# Community 268

**Cohesion:** 0.19 - loosely connected
**Members:** 14 nodes

## Members
- [[dot-_gate_fires()]] - code - tests/test_weather_markets.py
- [[dot-test_above_threshold_never_blocked()]] - code - tests/test_weather_markets.py
- [[dot-test_no_bet_low_model_prob_not_blocked()]] - code - tests/test_weather_markets.py
- [[dot-test_no_bet_very_low_model_prob_not_blocked()]] - code - tests/test_weather_markets.py
- [[dot-test_old_condition_would_have_been_wrong()]] - code - tests/test_weather_markets.py
- [[dot-test_yes_bet_low_model_prob_is_blocked()]] - code - tests/test_weather_markets.py
- [[Demonstrates the old condition (market  0.30) was logically inverted. With old…]] - rationale - tests/test_weather_markets.py
- [[Evaluate the corrected gate condition directly.]] - rationale - tests/test_weather_markets.py
- [[TestBetweenFloorGate]] - code - tests/test_weather_markets.py
- [[Verify the 9b between-floor gate only blocks low-confidence YES bets. The…]] - rationale - tests/test_weather_markets.py
- [[blended=10%, market=7% → we'd bet YES with low confidence → gate MUST fire.]] - rationale - tests/test_weather_markets.py
- [[blended=20% (above 15%) → gate never fires regardless of side.]] - rationale - tests/test_weather_markets.py
- [[blended=3%, market=65% → strong NO signal → gate must NOT fire.]] - rationale - tests/test_weather_markets.py
- [[blended=8%, market=45% → we'd bet NO → gate must NOT fire.]] - rationale - tests/test_weather_markets.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_268
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Ensemble Weight Blending Tests]]

## Top bridge nodes
- [[TestBetweenFloorGate]] - degree 8, connects to 1 community