---
type: community
cohesion: 0.11
members: 18
---

# Community 192

**Cohesion:** 0.11 - loosely connected
**Members:** 18 nodes

## Members
- [[--force bypasses the floor refusal and reaches the normal confirm prompt (still…]] - rationale - tests/test_main_cron_smoke.py
- [[dot-test_activate_confirmed_writes_params_and_resets_temperature_scale()]] - code - tests/test_main_cron_smoke.py
- [[dot-test_activate_declined_writes_nothing()]] - code - tests/test_main_cron_smoke.py
- [[dot-test_activate_eof_on_prompt_cancels_without_crashing()]] - code - tests/test_main_cron_smoke.py
- [[dot-test_activate_force_overrides_variance_floor()]] - code - tests/test_main_cron_smoke.py
- [[dot-test_activate_refuses_below_variance_floor()]] - code - tests/test_main_cron_smoke.py
- [[dot-test_activate_refuses_while_cron_is_running()]] - code - tests/test_main_cron_smoke.py
- [[dot-test_activate_rolls_back_if_temperature_reset_fails()]] - code - tests/test_main_cron_smoke.py
- [[dot-test_dry_run_does_not_write_params_file()]] - code - tests/test_main_cron_smoke.py
- [[dot-test_dry_run_never_prompts()]] - code - tests/test_main_cron_smoke.py
- [[A dry run must not even reach a confirmation prompt -- activation requires the…]] - rationale - tests/test_main_cron_smoke.py
- [[Activating mid-scan would split one cron cycle across two probability methods…]] - rationale - tests/test_main_cron_smoke.py
- [[Fewer than 40 ens_var rows must refuse activation outright (not just warn) --…]] - rationale - tests/test_main_cron_smoke.py
- [[If reset_temperature_scale_for_emos() raises after save_emos_params() already…]] - rationale - tests/test_main_cron_smoke.py
- [[Running --activate non-interactively (e.g. piped through cron) must not…]] - rationale - tests/test_main_cron_smoke.py
- [[TestEmosActivationGate]] - code - tests/test_main_cron_smoke.py
- [[_cmd_emos_train's dry-run--activate confirmation gate. Before this, running…]] - rationale - tests/test_main_cron_smoke.py
- [[between' IS EMOS-covered (weather_markets.py calls emos_interval_prob for it)…]] - rationale - tests/test_main_cron_smoke.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_192
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 207]]

## Top bridge nodes
- [[TestEmosActivationGate]] - degree 11, connects to 1 community