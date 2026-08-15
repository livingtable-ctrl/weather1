---
type: community
cohesion: 0.14
members: 21
---

# Community 149

**Cohesion:** 0.14 - loosely connected
**Members:** 21 nodes

## Members
- [[dot-_cooldown_path()]] - code - tests/test_notify.py
- [[dot-test_concurrent_threads_only_one_fires()]] - code - tests/test_notify.py
- [[dot-test_cooldown_elapses_after_the_full_window()]] - code - tests/test_notify.py
- [[dot-test_corrupt_cooldown_file_fails_open()]] - code - tests/test_notify.py
- [[dot-test_distinct_cooldown_keys_do_not_interfere()]] - code - tests/test_notify.py
- [[dot-test_first_call_for_new_key_fires_and_persists()]] - code - tests/test_notify.py
- [[dot-test_missing_cooldown_file_fails_open()]] - code - tests/test_notify.py
- [[dot-test_missing_parent_directory_is_created()]] - code - tests/test_notify.py
- [[dot-test_non_dict_json_fails_open()]] - code - tests/test_notify.py
- [[dot-test_read_failure_does_not_clobber_other_keys()]] - code - tests/test_notify.py
- [[dot-test_second_call_within_cooldown_is_suppressed()]] - code - tests/test_notify.py
- [[dot-test_this_is_the_actual_regression_this_entry_is_about()]] - code - tests/test_notify.py
- [[A corruptunparseable cooldown file must never block a real system alert --…]] - rationale - tests/test_notify.py
- [[A transient read failure (circuit_breaker.py documents a real observed Windows…]] - rationale - tests/test_notify.py
- [[Direct tests of the new disk-persisted cooldown check. Each test redirects…]] - rationale - tests/test_notify.py
- [[End-to-end behavior check -- the parent-directory creation itself happens…]] - rationale - tests/test_notify.py
- [[No prior cooldown file at all (e.g. first-ever run) must fire, not silently…]] - rationale - tests/test_notify.py
- [[TestSystemCooldownElapsed]] - code - tests/test_notify.py
- [[The lock's actual job (thread-level, not cross-process -- see…]] - rationale - tests/test_notify.py
- [[The whole point of this fix a second, independent lookup against the SAME…]] - rationale - tests/test_notify.py
- [[Valid JSON that isn't a dict (e.g. `null` or a bare list) must not crash with…]] - rationale - tests/test_notify.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_149
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 96]]

## Top bridge nodes
- [[TestSystemCooldownElapsed]] - degree 14, connects to 1 community