---
type: community
cohesion: 0.07
members: 51
---

# Community 32

**Cohesion:** 0.07 - loosely connected
**Members:** 51 nodes

## Members
- [[dot-__init__()_5]] - code - tests/test_alerts.py
- [[dot-get_market()_3]] - code - tests/test_alerts.py
- [[dot-test_above_direction_does_not_fire_when_price_below_target()]] - code - tests/test_alerts.py
- [[dot-test_above_direction_fires_when_price_at_or_over_target()]] - code - tests/test_alerts.py
- [[dot-test_add_alert_defaults_direction_below_cooldown_60()]] - code - tests/test_alerts.py
- [[dot-test_add_alert_invalid_direction_raises()]] - code - tests/test_alerts.py
- [[dot-test_add_alert_invalid_target_price_raises()]] - code - tests/test_alerts.py
- [[dot-test_add_alert_persists_and_increments_id()]] - code - tests/test_alerts.py
- [[dot-test_add_alert_returns_expected_fields()]] - code - tests/test_alerts.py
- [[dot-test_below_direction_does_not_fire_when_price_above_target()]] - code - tests/test_alerts.py
- [[dot-test_below_direction_fires_when_price_at_or_under_target()]] - code - tests/test_alerts.py
- [[dot-test_mark_triggered_only_affects_matching_id()]] - code - tests/test_alerts.py
- [[dot-test_mark_triggered_sets_flag_and_timestamp()]] - code - tests/test_alerts.py
- [[dot-test_mark_triggered_unknown_id_does_not_raise()]] - code - tests/test_alerts.py
- [[dot-test_no_active_alerts_returns_empty_without_fetching()]] - code - tests/test_alerts.py
- [[dot-test_remove_existing_alert_returns_true_and_removes()]] - code - tests/test_alerts.py
- [[dot-test_remove_nonexistent_alert_returns_false()]] - code - tests/test_alerts.py
- [[dot-test_save_propagates_atomic_write_failure()]] - code - tests/test_alerts.py
- [[dot-test_triggered_alert_after_cooldown_elapses_is_rearmed()]] - code - tests/test_alerts.py
- [[dot-test_triggered_alert_with_zero_cooldown_never_rearms()]] - code - tests/test_alerts.py
- [[dot-test_triggered_alert_within_cooldown_is_excluded()]] - code - tests/test_alerts.py
- [[dot-test_untriggered_alert_is_active()]] - code - tests/test_alerts.py
- [[A triggered alert whose cooldown has NOT yet elapsed must not reappear in the…]] - rationale - tests/test_alerts.py
- [[Add a price alert. Args ticker Market ticker (e.g. KXHIGHNY-26APR09-T72)…]] - rationale - alerts.py
- [[Correctness tests for alerts.py — addremovegetcheckmark_triggered.…]] - rationale - tests/test_alerts.py
- [[Fetch current YES prices for all alert tickers and check which alerts have been…]] - rationale - alerts.py
- [[Mark an alert as triggered. 91 Records triggered_at timestamp for cooldown…]] - rationale - alerts.py
- [[P91 once the cooldown period has passed, the alert must be reset to…]] - rationale - tests/test_alerts.py
- [[Redirect alerts._DATA_PATH to a per-test temp file so tests never touch the…]] - rationale - tests/test_alerts.py
- [[Regression coverage for the OTHER bare os.replace() CALL SITES backlog entry…_1]] - rationale - tests/test_alerts.py
- [[Remove an alert by ID. Returns True if found and removed, False otherwise.]] - rationale - alerts.py
- [[Return all active alerts. 91 An alert with a cooldown is re-armed after the…]] - rationale - alerts.py
- [[TestAddAlert]] - code - tests/test_alerts.py
- [[TestCheckAlerts]] - code - tests/test_alerts.py
- [[TestGetAlertsCooldownRearm]] - code - tests/test_alerts.py
- [[TestMarkTriggered]] - code - tests/test_alerts.py
- [[TestRemoveAlert]] - code - tests/test_alerts.py
- [[TestSaveRoutesThroughSafeIO]] - code - tests/test_alerts.py
- [[_FakeClient_1]] - code - tests/test_alerts.py
- [[_load()_1]] - code - alerts.py
- [[_save()_1]] - code - alerts.py
- [[add_alert()]] - code - alerts.py
- [[check_alerts()]] - code - alerts.py
- [[cooldown_minutes=0 means never re-arm — must stay excluded even long after…]] - rationale - tests/test_alerts.py
- [[fixture_10]] - code
- [[get_alerts()]] - code - alerts.py
- [[isolate_alerts_data()]] - code - tests/test_alerts.py
- [[mark_triggered()]] - code - alerts.py
- [[parametrize_3]] - code
- [[remove_alert()]] - code - alerts.py
- [[test_alerts.py]] - code - tests/test_alerts.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_32
SORT file.name ASC
```

## Connections to other communities
- 9 edges to [[_COMMUNITY_Community 8]]
- 8 edges to [[_COMMUNITY_Community 0]]
- 2 edges to [[_COMMUNITY_Community 3]]
- 1 edge to [[_COMMUNITY_Community 13]]
- 1 edge to [[_COMMUNITY_Community 81]]
- 1 edge to [[_COMMUNITY_Community 4]]

## Top bridge nodes
- [[check_alerts()]] - degree 12, connects to 4 communities
- [[add_alert()]] - degree 20, connects to 3 communities
- [[mark_triggered()]] - degree 6, connects to 3 communities
- [[test_alerts.py]] - degree 16, connects to 2 communities
- [[get_alerts()]] - degree 12, connects to 2 communities