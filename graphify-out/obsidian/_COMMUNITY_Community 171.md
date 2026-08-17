---
type: community
cohesion: 0.12
members: 19
---

# Community 171

**Cohesion:** 0.12 - loosely connected
**Members:** 19 nodes

## Members
- [[RF1 Silent Exception Swallow]] - document - docs/grade_audit/outputs
- [[_find_order_by_client_id() RF1 Bare Except (710)]] - document - docs/grade_audit/outputs/kalshi_client.py.md
- [[_get_obs_station() RF1 Silent Station Lookup Failure (410)]] - document - docs/grade_audit/outputs/nws.py.md
- [[_load_temperature_scale() RF1 Bare Except No Log (510)]] - document - docs/grade_audit/outputs/ml_bias.py.md
- [[_paper_min_edge_default() RF1 Promotion (410)]] - document - docs/grade_audit/outputs/config.py.md
- [[_send_discord() RF1 + Uncaught ImportError Risk (510)]] - document - docs/grade_audit/outputs/notify.py.md
- [[_ws_listener() Per-Message Parse Error at DEBUG (610)]] - document - docs/grade_audit/outputs/kalshi_ws.py.md
- [[add_live_loss() RF1 warnings.warn Not Logged (510)]] - document - docs/grade_audit/outputs/execution_log.py.md
- [[alert_strong_signal() RF1 Promotion (610)]] - document - docs/grade_audit/outputs/notify.py.md
- [[apply_ml_prob_correction() RF1 DEBUG on Model Failure (610)]] - document - docs/grade_audit/outputs/ml_bias.py.md
- [[check_exit_targets() RF1 Bare Except Continue (610)]] - document - docs/grade_audit/outputs/paper.py.md
- [[cmd_balance() RF1 Paper Balance Failure Silent (510)]] - document - docs/grade_audit/outputs/output_formatters.py.md
- [[cmd_history() RF1 Promotion (510)]] - document - docs/grade_audit/outputs/output_formatters.py.md
- [[cmd_positions() RF1 Exit Signal Hidden on Failure (510)]] - document - docs/grade_audit/outputs/output_formatters.py.md
- [[get_order_by_id() RF1 DEBUG Instead of WARNING (610)]] - document - docs/grade_audit/outputs/execution_log.py.md
- [[load_swept_min_edge() RF1 Corrupt Results Silently Discarded (510)]] - document - docs/grade_audit/outputs/param_sweep.py.md
- [[place_paper_order() AB Test Update Silently Swallowed (710)]] - document - docs/grade_audit/outputs/paper.py.md
- [[read_orderbook_cache() RF1 Zero Log on Exception (510)]] - document - docs/grade_audit/outputs/kalshi_ws.py.md
- [[send_system_alert() RF1 Promotion (610)]] - document - docs/grade_audit/outputs/notify.py.md

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_171
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_Community 6]]
- 3 edges to [[_COMMUNITY_Community 0]]
- 3 edges to [[_COMMUNITY_Community 148]]
- 2 edges to [[_COMMUNITY_Community 30]]
- 2 edges to [[_COMMUNITY_Community 42]]
- 1 edge to [[_COMMUNITY_Community 41]]
- 1 edge to [[_COMMUNITY_Community 445]]

## Top bridge nodes
- [[RF1 Silent Exception Swallow]] - degree 21, connects to 1 community
- [[_paper_min_edge_default() RF1 Promotion (410)]] - degree 3, connects to 1 community
- [[alert_strong_signal() RF1 Promotion (610)]] - degree 3, connects to 1 community
- [[_send_discord() RF1 + Uncaught ImportError Risk (510)]] - degree 3, connects to 1 community
- [[load_swept_min_edge() RF1 Corrupt Results Silently Discarded (510)]] - degree 3, connects to 1 community