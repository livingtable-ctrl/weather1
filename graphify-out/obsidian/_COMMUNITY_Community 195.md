---
type: community
cohesion: 0.13
members: 17
---

# Community 195

**Cohesion:** 0.13 - loosely connected
**Members:** 17 nodes

## Members
- [[I3 Atomic Write (os.replace)]] - document - docs/grade_audit/outputs
- [[RF1 Silent Exception Swallow]] - document - docs/grade_audit/outputs
- [[_get_obs_station() RF1 Silent Station Lookup Failure (410)]] - document - docs/grade_audit/outputs/nws.py.md
- [[_paper_min_edge_default() RF1 Promotion (410)]] - document - docs/grade_audit/outputs/config.py.md
- [[_send_discord() RF1 + Uncaught ImportError Risk (510)]] - document - docs/grade_audit/outputs/notify.py.md
- [[add_live_loss() RF1 warnings.warn Not Logged (510)]] - document - docs/grade_audit/outputs/execution_log.py.md
- [[alert_strong_signal() RF1 Promotion (610)]] - document - docs/grade_audit/outputs/notify.py.md
- [[check_exit_targets() RF1 Bare Except Continue (610)]] - document - docs/grade_audit/outputs/paper.py.md
- [[cmd_balance() RF1 Paper Balance Failure Silent (510)]] - document - docs/grade_audit/outputs/output_formatters.py.md
- [[cmd_history() RF1 Promotion (510)]] - document - docs/grade_audit/outputs/output_formatters.py.md
- [[cmd_positions() RF1 Exit Signal Hidden on Failure (510)]] - document - docs/grade_audit/outputs/output_formatters.py.md
- [[get_order_by_id() RF1 DEBUG Instead of WARNING (610)]] - document - docs/grade_audit/outputs/execution_log.py.md
- [[load_swept_min_edge() RF1 Corrupt Results Silently Discarded (510)]] - document - docs/grade_audit/outputs/param_sweep.py.md
- [[place_paper_order() AB Test Update Silently Swallowed (710)]] - document - docs/grade_audit/outputs/paper.py.md
- [[save_correlations() Non-Atomic Write, AC4 FAIL (410)]] - document - docs/grade_audit/outputs/monte_carlo.py.md
- [[send_system_alert() RF1 Promotion (610)]] - document - docs/grade_audit/outputs/notify.py.md
- [[update_orderbook_cache() RF1 DEBUG on Disk Write Failure (510)]] - document - docs/grade_audit/outputs/kalshi_ws.py.md

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_195
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Black Swan Halt State]]
- 3 edges to [[_COMMUNITY_Community 181]]
- 3 edges to [[_COMMUNITY_Community 198]]
- 3 edges to [[_COMMUNITY_Community 96]]
- 2 edges to [[_COMMUNITY_Execution Log Live-Loss Tracking]]
- 2 edges to [[_COMMUNITY_ML Bias Multiday-Predictions Filter]]
- 1 edge to [[_COMMUNITY_Community 129]]
- 1 edge to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 1 edge to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 1 edge to [[_COMMUNITY_Community 32]]
- 1 edge to [[_COMMUNITY_Community 351]]

## Top bridge nodes
- [[RF1 Silent Exception Swallow]] - degree 21, connects to 4 communities
- [[send_system_alert() RF1 Promotion (610)]] - degree 3, connects to 2 communities
- [[_paper_min_edge_default() RF1 Promotion (410)]] - degree 3, connects to 1 community
- [[update_orderbook_cache() RF1 DEBUG on Disk Write Failure (510)]] - degree 3, connects to 1 community
- [[alert_strong_signal() RF1 Promotion (610)]] - degree 3, connects to 1 community