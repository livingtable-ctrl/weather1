---
type: community
cohesion: 0.16
members: 14
---

# Community 253

**Cohesion:** 0.16 - loosely connected
**Members:** 14 nodes

## Members
- [[dot-test_auto_settle_called_after_sync_outcomes()]] - code - tests/test_cron_trade_updates.py
- [[dot-test_cmd_cron_calls_auto_settle_paper_trades()]] - code - tests/test_cron_trade_updates.py
- [[dot-test_cron_prints_signal_count_when_markets_found()]] - code - tests/test_cron_trade_updates.py
- [[dot-test_per_ticker_print_code_exists_in_cron()]] - code - tests/test_cron_trade_updates.py
- [[Stub out all guards that can cause cmd_cron to exit early. Without these stubs,…]] - rationale - tests/test_cron_trade_updates.py
- [[TestCronPrintPlacedTrades]] - code - tests/test_cron_trade_updates.py
- [[TestCronSettlesPaperTrades]] - code - tests/test_cron_trade_updates.py
- [[Tests for cron trade update fixes.]] - rationale - tests/test_cron_trade_updates.py
- [[_apply_cron_isolation()]] - code - tests/test_cron_trade_updates.py
- [[auto_settle_paper_trades must be called in the same cron cycle as sync_outcomes.]] - rationale - tests/test_cron_trade_updates.py
- [[cmd_cron must call auto_settle_paper_trades so paper trades get marked wonlost.]] - rationale - tests/test_cron_trade_updates.py
- [[cmd_cron must emit output describing scan results and any placement activity.]] - rationale - tests/test_cron_trade_updates.py
- [[cron.py must track placement count and include it in the run summary.]] - rationale - tests/test_cron_trade_updates.py
- [[test_cron_trade_updates.py]] - code - tests/test_cron_trade_updates.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_253
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 109]]

## Top bridge nodes
- [[test_cron_trade_updates.py]] - degree 5, connects to 1 community