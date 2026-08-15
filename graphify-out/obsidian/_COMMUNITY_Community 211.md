---
type: community
cohesion: 0.16
members: 16
---

# Community 211

**Cohesion:** 0.16 - loosely connected
**Members:** 16 nodes

## Members
- [[Between-Market METAR Lock-in Daily-Extreme Bug]] - document - docs/grade_audit/modules/weather_markets.md
- [[Extract a plausible temp_f from a raw METAR obs dict (prefers tmpf °F, else…]] - rationale - metar.py
- [[Fetch every METAR temp_f reading for `station` that falls on the LOCAL calendar…]] - rationale - metar.py
- [[METAR same-day lock-in strategy. After ~2 PM local time, if the daily highlow…]] - rationale - metar.py
- [[Parse a raw METAR obs dict's obsTime (Unix epoch intfloat, or an ISO-8601…]] - rationale - metar.py
- [[Systemic DEBUG-vs-WARNING Gap on IO Failures (_load_obs_save_obs)]] - document - docs/grade_audit/outputs/metar.py.md
- [[_extract_obs_time()]] - code - metar.py
- [[_extract_temp_f()]] - code - metar.py
- [[_fetch_daily_temps_f()]] - code - metar.py
- [[check_metar_lockout() Silent ZoneInfo Fallback (810)]] - document - docs/grade_audit/outputs/metar.py.md
- [[date_1]] - code
- [[datetime_1]] - code
- [[get_station_bias() Unconditional NotImplementedError Stub (710)]] - document - docs/grade_audit/outputs/metar.py.md
- [[metar.py]] - code - metar.py
- [[metar.py File Grade median 810 T1, systemic DEBUG gap in T2]] - document - docs/grade_audit/outputs/metar.py.md
- [[metar.py Grade Audit]] - document - docs/grade_audit/outputs/metar.py.md

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_211
SORT file.name ASC
```

## Connections to other communities
- 8 edges to [[_COMMUNITY_METAR Settlement Monitoring]]
- 1 edge to [[_COMMUNITY_Community 51]]
- 1 edge to [[_COMMUNITY_Community 64]]
- 1 edge to [[_COMMUNITY_Forecasting Persistence Model Tests]]
- 1 edge to [[_COMMUNITY_Community 182]]
- 1 edge to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_Community 99]]
- 1 edge to [[_COMMUNITY_Community 73]]
- 1 edge to [[_COMMUNITY_Community 26]]

## Top bridge nodes
- [[metar.py]] - degree 22, connects to 7 communities
- [[_fetch_daily_temps_f()]] - degree 7, connects to 2 communities
- [[datetime_1]] - degree 3, connects to 1 community
- [[date_1]] - degree 2, connects to 1 community
- [[Between-Market METAR Lock-in Daily-Extreme Bug]] - degree 2, connects to 1 community