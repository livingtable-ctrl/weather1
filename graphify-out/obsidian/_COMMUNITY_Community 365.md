---
type: community
cohesion: 0.20
members: 10
---

# Community 365

**Cohesion:** 0.20 - loosely connected
**Members:** 10 nodes

## Members
- [[Phase 2 HIGH Issues Summary]] - document - docs/audit_findings.md
- [[`alerts.py`]] - document - docs/audit_findings.md
- [[`circuit_breaker.py`]] - document - docs/audit_findings.md
- [[`consistency.py`]] - document - docs/audit_findings.md
- [[`metar.py`]] - document - docs/audit_findings.md
- [[`nws.py`]] - document - docs/audit_findings.md
- [[`settlement_monitor.py`]] - document - docs/audit_findings.md
- [[`system_health.py`]] - document - docs/audit_findings.md
- [[`trading_gates.py`]] - document - docs/audit_findings.md
- [[`weather_markets.py`]] - document - docs/audit_findings.md

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_365
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 446]]

## Top bridge nodes
- [[Phase 2 HIGH Issues Summary]] - degree 10, connects to 1 community