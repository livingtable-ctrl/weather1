---
type: community
cohesion: 0.05
members: 56
---

# Cron Integration Tests

**Cohesion:** 0.05 - loosely connected
**Members:** 56 nodes

## Members
- [[2026-07-12 a KalshiWebSocket started this cycle must be stopped before…]] - rationale - tests/test_cron_integration.py
- [[A full cmd_cron() run producing a real STRONG signal must write its JSONL entry…]] - rationale - tests/test_cron_integration.py
- [[A market whose adjusted_edge clears STRONG_EDGE must be auto-placed (L2-E).]] - rationale - tests/test_cron_integration.py
- [[A market whose net_edge clears STRONG_EDGE but adjusted_edge does not must NOT…]] - rationale - tests/test_cron_integration.py
- [[A market with zero volumeopen-interest closing within 60 minutes must never…]] - rationale - tests/test_cron_integration.py
- [[An accuracy halt must not skip settlement — the halt is computed from settled…]] - rationale - tests/test_cron_integration.py
- [[An anomaly halt (declined in non-interactiveloop mode) must still settle.]] - rationale - tests/test_cron_integration.py
- [[Deep-review followup when an earlier soft-halt (accuracy halt here) already…]] - rationale - tests/test_cron_integration.py
- [[End-to-end regression for near_settlement_log being silently broken since it…]] - rationale - tests/test_cron_integration.py
- [[End-to-end version of the test above exercises the REAL _cmd_cron_body…]] - rationale - tests/test_cron_integration.py
- [[Full cron run with a mocked strong signal _auto_place_trades called with…]] - rationale - tests/test_cron_integration.py
- [[If kill switch file exists, cmd_cron must return without calling…]] - rationale - tests/test_cron_integration.py
- [[Integration tests for cmd_cron() orchestration layer. All external calls…]] - rationale - tests/test_cron_integration.py
- [[Isolate cmd_cron from real data, networks, and alerts.]] - rationale - tests/test_cron_integration.py
- [[Lock must be cleaned up even if cron is interrupted mid-run.]] - rationale - tests/test_cron_integration.py
- [[P1-12 kill switch created during scan must break the analysis loop.]] - rationale - tests/test_cron_integration.py
- [[P1-15 empty anomaly list must not halt — cron continues normally.]] - rationale - tests/test_cron_integration.py
- [[P1-15 when run_anomaly_check returns anomalies, cron must halt before…]] - rationale - tests/test_cron_integration.py
- [[Shared fake marketenrichedanalysis triple for a STRONG-tier YES signal on a…]] - rationale - tests/test_cron_integration.py
- [[The WS cleanup must run via the existing finally block even when _cmd_cron_body…]] - rationale - tests/test_cron_integration.py
- [[Unlike the soft halts, the kill switch remains a full stop by design — it's the…]] - rationale - tests/test_cron_integration.py
- [[When Brier drift is detected, cmd_cron logs the tightened STRONG_EDGE threshold.]] - rationale - tests/test_cron_integration.py
- [[When drawdown guard is active, _auto_place_trades returns 0 and places nothing.]] - rationale - tests/test_cron_integration.py
- [[_fake_strong_signal()]] - code - tests/test_cron_integration.py
- [[check_market_anomalies returns only signals with drift  0.12.]] - rationale - tests/test_cron_integration.py
- [[cmd_cron must call paper.check_paper_position_exits() and actually close a…]] - rationale - tests/test_cron_integration.py
- [[cmd_cron()'s settlement-lag-signal consumer (~cron.py1396) must pass a…]] - rationale - tests/test_cron_integration.py
- [[cron_env()]] - code - tests/test_cron_integration.py
- [[fixture_5]] - code
- [[integration]] - code
- [[report_anomalies prints ticker and drift for markets 12pp from model.]] - rationale - tests/test_cron_integration.py
- [[test_accuracy_halt_still_runs_settlement()]] - code - tests/test_cron_integration.py
- [[test_anomaly_halt_still_runs_settlement()]] - code - tests/test_cron_integration.py
- [[test_anomaly_override_prompt_skipped_when_already_halted()]] - code - tests/test_cron_integration.py
- [[test_check_market_anomalies_filters_by_threshold()]] - code - tests/test_cron_integration.py
- [[test_cmd_cron_body_registers_real_websocket_before_cleanup()]] - code - tests/test_cron_integration.py
- [[test_cmd_cron_stops_active_websocket_on_exit()]] - code - tests/test_cron_integration.py
- [[test_cmd_cron_stops_websocket_even_on_body_exception()]] - code - tests/test_cron_integration.py
- [[test_cron_closes_position_via_check_paper_position_exits()]] - code - tests/test_cron_integration.py
- [[test_cron_drawdown_guard_blocks_auto_trades()]] - code - tests/test_cron_integration.py
- [[test_cron_drift_tightens_effective_edge()]] - code - tests/test_cron_integration.py
- [[test_cron_gate_allows_when_adjusted_edge_above_threshold()]] - code - tests/test_cron_integration.py
- [[test_cron_gate_blocks_when_adjusted_edge_below_threshold()]] - code - tests/test_cron_integration.py
- [[test_cron_integration.py]] - code - tests/test_cron_integration.py
- [[test_cron_kill_switch_halts_before_scan()]] - code - tests/test_cron_integration.py
- [[test_cron_lock_released_on_keyboard_interrupt()]] - code - tests/test_cron_integration.py
- [[test_cron_logs_near_settlement_row_with_real_trade_fields()]] - code - tests/test_cron_integration.py
- [[test_cron_places_paper_trade_on_strong_signal()]] - code - tests/test_cron_integration.py
- [[test_cron_reads_settlement_signals_with_generous_staleness_window()]] - code - tests/test_cron_integration.py
- [[test_cron_skips_stale_markets_before_analysis()]] - code - tests/test_cron_integration.py
- [[test_cron_strong_signal_does_not_write_to_real_production_cron_log()]] - code - tests/test_cron_integration.py
- [[test_kill_switch_still_skips_settlement()]] - code - tests/test_cron_integration.py
- [[test_p1_12_kill_switch_mid_scan_breaks_loop()]] - code - tests/test_cron_integration.py
- [[test_p1_15_anomaly_check_halts_cron()]] - code - tests/test_cron_integration.py
- [[test_p1_15_empty_anomaly_list_does_not_halt()]] - code - tests/test_cron_integration.py
- [[test_report_anomalies_prints_drifted_markets()]] - code - tests/test_cron_integration.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Cron_Integration_Tests
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 109]]

## Top bridge nodes
- [[test_cron_integration.py]] - degree 28, connects to 1 community