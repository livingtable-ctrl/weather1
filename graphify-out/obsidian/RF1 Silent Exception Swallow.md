---
source_file: "docs/grade_audit/outputs"
type: "document"
community: "Community 171"
tags:
  - graphify/document
  - graphify/EXTRACTED
  - community/Community_171
---

# RF1: Silent Exception Swallow

## Connections
- [[_find_order_by_client_id() RF1 Bare Except (710)]] - `references` [EXTRACTED]
- [[_get_obs_station() RF1 Silent Station Lookup Failure (410)]] - `references` [EXTRACTED]
- [[_load_dynamic_correlations() RF1 Bare Except (610)]] - `references` [EXTRACTED]
- [[_load_temperature_scale() RF1 Bare Except No Log (510)]] - `references` [EXTRACTED]
- [[_paper_min_edge_default() RF1 Promotion (410)]] - `references` [EXTRACTED]
- [[_send_discord() RF1 + Uncaught ImportError Risk (510)]] - `references` [EXTRACTED]
- [[_ws_listener() Per-Message Parse Error at DEBUG (610)]] - `references` [EXTRACTED]
- [[add_live_loss() RF1 warnings.warn Not Logged (510)]] - `references` [EXTRACTED]
- [[alert_strong_signal() RF1 Promotion (610)]] - `references` [EXTRACTED]
- [[apply_ml_prob_correction() RF1 DEBUG on Model Failure (610)]] - `references` [EXTRACTED]
- [[check_exit_targets() RF1 Bare Except Continue (610)]] - `references` [EXTRACTED]
- [[cmd_balance() RF1 Paper Balance Failure Silent (510)]] - `references` [EXTRACTED]
- [[cmd_history() RF1 Promotion (510)]] - `references` [EXTRACTED]
- [[cmd_positions() RF1 Exit Signal Hidden on Failure (510)]] - `references` [EXTRACTED]
- [[get_order_by_id() RF1 DEBUG Instead of WARNING (610)]] - `references` [EXTRACTED]
- [[load_correlations_from_backtest() RF1 Bare Except (610)]] - `references` [EXTRACTED]
- [[load_swept_min_edge() RF1 Corrupt Results Silently Discarded (510)]] - `references` [EXTRACTED]
- [[place_paper_order() AB Test Update Silently Swallowed (710)]] - `references` [EXTRACTED]
- [[read_orderbook_cache() RF1 Zero Log on Exception (510)]] - `references` [EXTRACTED]
- [[send_system_alert() RF1 Promotion (610)]] - `references` [EXTRACTED]
- [[update_orderbook_cache() RF1 DEBUG on Disk Write Failure (510)]] - `references` [EXTRACTED]

#graphify/document #graphify/EXTRACTED #community/Community_171