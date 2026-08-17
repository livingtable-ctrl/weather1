---
source_file: "tests/test_cron_integration.py"
type: "code"
community: "Community 31"
location: "L1"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Community_31
---

# test_cron_integration.py

## Connections
- [[Grade Audit Module Doc cron.py]] - `references` [EXTRACTED]
- [[Integration tests for cmd_cron() orchestration layer. All external calls…]] - `rationale_for` [EXTRACTED]
- [[_fake_strong_signal()]] - `contains` [EXTRACTED]
- [[_run_batch_prewarm()]] - `calls` [EXTRACTED]
- [[backlog.txt]] - `cites` [EXTRACTED]
- [[cron_env()]] - `contains` [EXTRACTED]
- [[kalshi_ws.KalshiWebSocket]] - `references` [EXTRACTED]
- [[logging]] - `imports` [EXTRACTED]
- [[pytest_1]] - `imports` [EXTRACTED]
- [[read_settlement_signals()]] - `calls` [EXTRACTED]
- [[run_anomaly_check()]] - `calls` [EXTRACTED]
- [[run_black_swan_check()]] - `calls` [EXTRACTED]
- [[test_accuracy_halt_still_runs_settlement()]] - `contains` [EXTRACTED]
- [[test_anomaly_halt_still_runs_settlement()]] - `contains` [EXTRACTED]
- [[test_anomaly_override_prompt_skipped_when_already_halted()]] - `contains` [EXTRACTED]
- [[test_check_market_anomalies_filters_by_threshold()]] - `contains` [EXTRACTED]
- [[test_cmd_cron_body_registers_real_websocket_before_cleanup()]] - `contains` [EXTRACTED]
- [[test_cmd_cron_stops_active_websocket_on_exit()]] - `contains` [EXTRACTED]
- [[test_cmd_cron_stops_websocket_even_on_body_exception()]] - `contains` [EXTRACTED]
- [[test_cron_closes_position_via_check_paper_position_exits()]] - `contains` [EXTRACTED]
- [[test_cron_drawdown_guard_blocks_auto_trades()]] - `contains` [EXTRACTED]
- [[test_cron_drift_tightens_effective_edge()]] - `contains` [EXTRACTED]
- [[test_cron_gate_allows_when_adjusted_edge_above_threshold()]] - `contains` [EXTRACTED]
- [[test_cron_gate_blocks_when_adjusted_edge_below_threshold()]] - `contains` [EXTRACTED]
- [[test_cron_kill_switch_halts_before_scan()]] - `contains` [EXTRACTED]
- [[test_cron_lock_released_on_keyboard_interrupt()]] - `contains` [EXTRACTED]
- [[test_cron_logs_near_settlement_row_with_real_trade_fields()]] - `contains` [EXTRACTED]
- [[test_cron_places_paper_trade_on_strong_signal()]] - `contains` [EXTRACTED]
- [[test_cron_reads_settlement_signals_with_generous_staleness_window()]] - `contains` [EXTRACTED]
- [[test_cron_skips_stale_markets_before_analysis()]] - `contains` [EXTRACTED]
- [[test_cron_strong_signal_does_not_write_to_real_production_cron_log()]] - `contains` [EXTRACTED]
- [[test_cron_trade_updates.py]] - `semantically_similar_to` [INFERRED]
- [[test_execution_proof.py]] - `semantically_similar_to` [INFERRED]
- [[test_kill_switch_still_skips_settlement()]] - `contains` [EXTRACTED]
- [[test_p1_12_kill_switch_mid_scan_breaks_loop()]] - `contains` [EXTRACTED]
- [[test_p1_15_anomaly_check_halts_cron()]] - `contains` [EXTRACTED]
- [[test_p1_15_empty_anomaly_list_does_not_halt()]] - `contains` [EXTRACTED]
- [[test_report_anomalies_prints_drifted_markets()]] - `contains` [EXTRACTED]
- [[unittest_mock]] - `imports_from` [EXTRACTED]
- [[utils.DRIFT_TIGHTEN_EDGE]] - `references` [EXTRACTED]
- [[utils.STRONG_EDGE]] - `references` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Community_31