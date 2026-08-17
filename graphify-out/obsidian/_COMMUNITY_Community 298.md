---
type: community
cohesion: 0.17
members: 12
---

# Community 298

**Cohesion:** 0.17 - loosely connected
**Members:** 12 nodes

## Members
- [[C13 · `weather_markets.py` — PlattML corrections applied to already-bias-corrected probabilities]] - document - docs/audit_findings.md
- [[C14 · `weather_markets.py` — Batch prewarm discards ECMWF model weights]] - document - docs/audit_findings.md
- [[C15 · `weather_markets.py` — `range` vs `between` typo disables bucket-market consensus]] - document - docs/audit_findings.md
- [[C16 · `system_health.py` — Health check always returns healthy=True]] - document - docs/audit_findings.md
- [[C17 · `alerts.py` — Safety functions silently return all clear on any exception]] - document - docs/audit_findings.md
- [[C18 · `alerts.py` — Kill switch may silently fail to create the halt file]] - document - docs/audit_findings.md
- [[C19 · `alerts.py` — Black swan daily loss check uses paper P&L not real account equity]] - document - docs/audit_findings.md
- [[C20 · `metar.py` — Proxy observations still feeding bias corruption]] - document - docs/audit_findings.md
- [[C21 · `metar.py` — `get_station_bias()` is a permanent stub returning 0.0]] - document - docs/audit_findings.md
- [[C22 · `settlement_monitor.py` — Wrong series tickers for 3 of 5 monitored cities]] - document - docs/audit_findings.md
- [[C23 · `settlement_monitor.py` — Signals produced but never acted on]] - document - docs/audit_findings.md
- [[Phase 2 CRITICAL Issues]] - document - docs/audit_findings.md

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_298
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 446]]

## Top bridge nodes
- [[Phase 2 CRITICAL Issues]] - degree 12, connects to 1 community