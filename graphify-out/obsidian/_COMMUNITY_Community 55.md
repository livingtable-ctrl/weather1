---
type: community
cohesion: 0.08
members: 39
---

# Community 55

**Cohesion:** 0.08 - loosely connected
**Members:** 39 nodes

## Members
- [[dot-isolated_temp_paths()]] - code - tests/test_ml_bias.py
- [[dot-test_count_emos_variance_ready_predictions_requires_ens_var()]] - code - tests/test_ml_bias.py
- [[dot-test_deactivate_emos_archives_to_history_before_unlink()]] - code - tests/test_ml_bias.py
- [[dot-test_deactivate_emos_noop_when_already_inactive()]] - code - tests/test_ml_bias.py
- [[dot-test_deactivate_emos_removes_file_and_returns_true_when_active()]] - code - tests/test_ml_bias.py
- [[dot-test_emos_exceedance_prob_called_via_load_emos_params()]] - code - tests/test_ml_bias.py
- [[dot-test_get_emos_status_active_returns_all_fields()]] - code - tests/test_ml_bias.py
- [[dot-test_get_emos_status_inactive_when_file_missing()]] - code - tests/test_ml_bias.py
- [[dot-test_get_emos_training_data_excludes_null_ens_mean()]] - code - tests/test_ml_bias.py
- [[dot-test_load_emos_params_picks_up_change_without_process_restart()]] - code - tests/test_ml_bias.py
- [[dot-test_load_emos_params_returns_none_when_file_missing()]] - code - tests/test_ml_bias.py
- [[dot-test_reset_temperature_scale_handles_missing_file()]] - code - tests/test_ml_bias.py
- [[dot-test_reset_temperature_scale_migrates_old_single_value_format()]] - code - tests/test_ml_bias.py
- [[dot-test_reset_temperature_scale_sets_identity_preserves_sameday()]] - code - tests/test_ml_bias.py
- [[dot-test_reset_temperature_scale_snapshots_prior_values()]] - code - tests/test_ml_bias.py
- [[dot-test_restore_from_emos_snapshot_noop_when_no_snapshot()]] - code - tests/test_ml_bias.py
- [[dot-test_restore_from_emos_snapshot_restores_and_consumes_it()]] - code - tests/test_ml_bias.py
- [[dot-test_save_and_reload_emos_params()]] - code - tests/test_ml_bias.py
- [[A long-running process (loopwatch) must see a savedeactivate made by a…]] - rationale - tests/test_ml_bias.py
- [[First-ever activation's params must survive deactivation --…]] - rationale - tests/test_ml_bias.py
- [[Old format is {T x, n_samples y} -- NOT {T x, n y}. Must match…]] - rationale - tests/test_ml_bias.py
- [[Persist EMOS parameters and clear the in-process cache.]] - rationale - ml_bias.py
- [[Remove emos_params.json, reverting multi-day abovebelowbetween predictions to…]] - rationale - ml_bias.py
- [[Reset T_globalT_aboveT_belowT_between to 1.0 (identityno-op) in…]] - rationale - ml_bias.py
- [[Restore globalabovebelowbetween to their pre-EMOS-activation T values from…]] - rationale - ml_bias.py
- [[Return cached (a, b, c, d) from emos_params.json, or None if not trained. Re-…]] - rationale - ml_bias.py
- [[Return {active bool, abcdnmean_crpsfitted_at ...}…]] - rationale - ml_bias.py
- [[Shared isolation for resetdeactivate tests -- patches every module-level…]] - rationale - tests/test_ml_bias.py
- [[TestEmos]] - code - tests/test_ml_bias.py
- [[The stricter count (what actually gates EMOS's cd variance fit) must exclude…]] - rationale - tests/test_ml_bias.py
- [[_load_emos_params must return the cache when _EMOS_CACHE is populated.]] - rationale - tests/test_ml_bias.py
- [[_load_emos_params()]] - code - ml_bias.py
- [[deactivate_emos()]] - code - ml_bias.py
- [[fixture_16]] - code
- [[get_emos_status()]] - code - ml_bias.py
- [[globalabovebelowbetween all reset to T=1.0 (EMOS covers all 4 -- 'between'…]] - rationale - tests/test_ml_bias.py
- [[reset_temperature_scale_for_emos()]] - code - ml_bias.py
- [[restore_temperature_scale_from_emos_snapshot()]] - code - ml_bias.py
- [[save_emos_params()]] - code - ml_bias.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_55
SORT file.name ASC
```

## Connections to other communities
- 12 edges to [[_COMMUNITY_Community 0]]
- 7 edges to [[_COMMUNITY_Community 99]]
- 6 edges to [[_COMMUNITY_Community 230]]
- 6 edges to [[_COMMUNITY_Community 82]]
- 3 edges to [[_COMMUNITY_Community 8]]
- 2 edges to [[_COMMUNITY_Community 5]]
- 1 edge to [[_COMMUNITY_Community 255]]

## Top bridge nodes
- [[save_emos_params()]] - degree 15, connects to 6 communities
- [[reset_temperature_scale_for_emos()]] - degree 13, connects to 4 communities
- [[deactivate_emos()]] - degree 11, connects to 3 communities
- [[_load_emos_params()]] - degree 10, connects to 3 communities
- [[get_emos_status()]] - degree 9, connects to 3 communities