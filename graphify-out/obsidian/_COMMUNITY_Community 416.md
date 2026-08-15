---
type: community
cohesion: 0.22
members: 9
---

# Community 416

**Cohesion:** 0.22 - loosely connected
**Members:** 9 nodes

## Members
- [[dot-test_halt_creates_kill_switch_file()]] - code - tests/test_web_app.py
- [[dot-test_halt_no_leftover_tmp_file()]] - code - tests/test_web_app.py
- [[dot-test_resume_removes_kill_switch_file()]] - code - tests/test_web_app.py
- [[dot-test_status_includes_kill_switch_active()]] - code - tests/test_web_app.py
- [[GET apistatus includes kill_switch_active field (False when no file).]] - rationale - tests/test_web_app.py
- [[P1-16 atomic write must not leave a .tmp file after successful halt.]] - rationale - tests/test_web_app.py
- [[POST apihalt writes the kill-switch file with reason and timestamp.]] - rationale - tests/test_web_app.py
- [[POST apiresume removes the kill-switch file.]] - rationale - tests/test_web_app.py
- [[TestKillSwitchAPI]] - code - tests/test_web_app.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_416
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 43]]

## Top bridge nodes
- [[TestKillSwitchAPI]] - degree 5, connects to 1 community