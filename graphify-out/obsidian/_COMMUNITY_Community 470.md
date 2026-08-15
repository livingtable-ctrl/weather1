---
type: community
cohesion: 0.29
members: 7
---

# Community 470

**Cohesion:** 0.29 - loosely connected
**Members:** 7 nodes

## Members
- [[dot-test_accuracy_halt_skips_placement_but_still_scans()]] - code - tests/test_main_cron_smoke.py
- [[dot-test_empty_market_list_runs_cleanly()]] - code - tests/test_main_cron_smoke.py
- [[dot-test_kill_switch_blocks_market_scan()]] - code - tests/test_main_cron_smoke.py
- [[An accuracy halt must still scansettle — only placement is skipped. Settlement…]] - rationale - tests/test_main_cron_smoke.py
- [[TestCmdCronGuards]] - code - tests/test_main_cron_smoke.py
- [[cmd_cron exits early when the kill switch file is present.]] - rationale - tests/test_main_cron_smoke.py
- [[cmd_cron with no markets returned completes without error.]] - rationale - tests/test_main_cron_smoke.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_470
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 40]]

## Top bridge nodes
- [[TestCmdCronGuards]] - degree 4, connects to 1 community