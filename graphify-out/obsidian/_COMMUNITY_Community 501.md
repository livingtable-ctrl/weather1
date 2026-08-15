---
type: community
cohesion: 0.33
members: 6
---

# Community 501

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[101 Remove stray .paper_trades_ temp files left by interrupted atomic…]] - rationale - paper.py
- [[Copy predictions.db and paper_trades.json to databackups on startup. 103…]] - rationale - main.py
- [[Re-open a backed-up predictions.db, count rows in predictions table. Logs…]] - rationale - main.py
- [[auto_backup()]] - code - main.py
- [[cleanup_temp_files()]] - code - paper.py
- [[verify_db_backup()]] - code - main.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_501
SORT file.name ASC
```

## Connections to other communities
- 4 edges to [[_COMMUNITY_Black Swan Halt State]]
- 1 edge to [[_COMMUNITY_Community 132]]
- 1 edge to [[_COMMUNITY_Community 460]]
- 1 edge to [[_COMMUNITY_Climatology & Climate Index Fetching]]
- 1 edge to [[_COMMUNITY_Circuit Breaker & Session Retry Infrastructure]]
- 1 edge to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]

## Top bridge nodes
- [[auto_backup()]] - degree 8, connects to 4 communities
- [[verify_db_backup()]] - degree 4, connects to 2 communities
- [[cleanup_temp_files()]] - degree 4, connects to 2 communities