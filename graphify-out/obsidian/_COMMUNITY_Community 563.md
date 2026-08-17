---
type: community
cohesion: 0.33
members: 6
---

# Community 563

**Cohesion:** 0.33 - loosely connected
**Members:** 6 nodes

## Members
- [[A full cmd_cron() run producing a real STRONG signal must write its JSONL entry…]] - rationale - tests/test_cron_integration.py
- [[Full cron run with a mocked strong signal _auto_place_trades called with…]] - rationale - tests/test_cron_integration.py
- [[Shared fake marketenrichedanalysis triple for a STRONG-tier YES signal on a…]] - rationale - tests/test_cron_integration.py
- [[_fake_strong_signal()]] - code - tests/test_cron_integration.py
- [[test_cron_places_paper_trade_on_strong_signal()]] - code - tests/test_cron_integration.py
- [[test_cron_strong_signal_does_not_write_to_real_production_cron_log()]] - code - tests/test_cron_integration.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_563
SORT file.name ASC
```

## Connections to other communities
- 5 edges to [[_COMMUNITY_Community 31]]

## Top bridge nodes
- [[_fake_strong_signal()]] - degree 4, connects to 1 community
- [[test_cron_places_paper_trade_on_strong_signal()]] - degree 4, connects to 1 community
- [[test_cron_strong_signal_does_not_write_to_real_production_cron_log()]] - degree 4, connects to 1 community