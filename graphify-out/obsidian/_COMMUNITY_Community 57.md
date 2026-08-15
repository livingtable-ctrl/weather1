---
type: community
cohesion: 0.06
members: 38
---

# Community 57

**Cohesion:** 0.06 - loosely connected
**Members:** 38 nodes

## Members
- [[dot-_fake_summary()]] - code - tests/test_phase3_batch_a.py
- [[dot-_run_sim()]] - code - tests/test_phase3_batch_a.py
- [[dot-test_correlation_applied_false_when_cholesky_fails()_1]] - code - tests/test_phase3_batch_a.py
- [[dot-test_correlation_applied_false_when_no_city()_1]] - code - tests/test_phase3_batch_a.py
- [[dot-test_correlation_applied_true_when_cholesky_succeeds_with_city()]] - code - tests/test_phase3_batch_a.py
- [[dot-test_fetch_archive_temps_source_uses_md5()]] - code - tests/test_phase3_batch_a.py
- [[dot-test_kelly_cap_in_utils()]] - code - tests/test_phase3_batch_a.py
- [[dot-test_md5_seed_is_deterministic()]] - code - tests/test_phase3_batch_a.py
- [[dot-test_old_brier_key_absent()]] - code - tests/test_phase3_batch_a.py
- [[dot-test_paper_kelly_sizing_capped()]] - code - tests/test_phase3_batch_a.py
- [[dot-test_pragma_is_full()]] - code - tests/test_phase3_batch_a.py
- [[dot-test_train_brier_key_present()]] - code - tests/test_phase3_batch_a.py
- [[dot-test_two_runs_same_result()]] - code - tests/test_phase3_batch_a.py
- [[dot-test_val_brier_unreliable_false_when_val_n_ge_10()]] - code - tests/test_phase3_batch_a.py
- [[dot-test_val_brier_unreliable_flag_present()]] - code - tests/test_phase3_batch_a.py
- [[dot-test_val_brier_unreliable_true_when_val_n_zero()]] - code - tests/test_phase3_batch_a.py
- [[dot-test_wal_checkpoint_called()]] - code - tests/test_phase3_batch_a.py
- [[dot-test_weather_markets_imports_kelly_cap()]] - code - tests/test_phase3_batch_a.py
- [[Build a minimal run_backtest return dict directly.]] - rationale - tests/test_phase3_batch_a.py
- [[Construct result dict directly to test with val_n = 10.]] - rationale - tests/test_phase3_batch_a.py
- [[No city means correlation is a no-op — must be False even if Cholesky succeeds.]] - rationale - tests/test_phase3_batch_a.py
- [[P3-10 execution_log.db must use PRAGMA synchronous=FULL.]] - rationale - tests/test_phase3_batch_a.py
- [[P3-11 run_backtest must return 'train_brier', not 'brier'.]] - rationale - tests/test_phase3_batch_a.py
- [[P3-13 KELLY_CAP must be 0.25 in utils and used by both modules.]] - rationale - tests/test_phase3_batch_a.py
- [[P3-15 cmd_cron must execute PRAGMA wal_checkpoint(PASSIVE) at end of run.]] - rationale - tests/test_phase3_batch_a.py
- [[P3-19 RNG seed must use hashlib.md5, not hash() (which is PYTHONHASHSEED-…]] - rationale - tests/test_phase3_batch_a.py
- [[P3-20 correlation_applied = chol is not None AND any city present. When…]] - rationale - tests/test_phase3_batch_a.py
- [[Phase 3 Batch A regression tests P3-10, P3-11, P3-13, P3-15, P3-19, P3-20,…]] - rationale - tests/test_phase3_batch_a.py
- [[TestBacktestBrierKeyNaming]] - code - tests/test_phase3_batch_a.py
- [[TestCronWalCheckpoint]] - code - tests/test_phase3_batch_a.py
- [[TestExecutionLogSynchronousFull]] - code - tests/test_phase3_batch_a.py
- [[TestFetchArchiveTempsDeterministicSeed]] - code - tests/test_phase3_batch_a.py
- [[TestKellyCapConstant]] - code - tests/test_phase3_batch_a.py
- [[TestMonteCarloCorrelationApplied]] - code - tests/test_phase3_batch_a.py
- [[Two calls with same target_date must produce identical ensemble.]] - rationale - tests/test_phase3_batch_a.py
- [[Two invocations of fetch_archive_temps with same args produce same list.]] - rationale - tests/test_phase3_batch_a.py
- [[Verify the checkpoint execute call is reached in the finally block.]] - rationale - tests/test_phase3_batch_a.py
- [[test_phase3_batch_a.py]] - code - tests/test_phase3_batch_a.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_57
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_Black Swan Halt State]]
- 2 edges to [[_COMMUNITY_Backtest Engine & Atomic Writes]]
- 2 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Community 86]]

## Top bridge nodes
- [[test_phase3_batch_a.py]] - degree 11, connects to 4 communities
- [[TestBacktestBrierKeyNaming]] - degree 9, connects to 1 community
- [[dot-_fake_summary()]] - degree 7, connects to 1 community
- [[TestMonteCarloCorrelationApplied]] - degree 7, connects to 1 community
- [[TestFetchArchiveTempsDeterministicSeed]] - degree 6, connects to 1 community