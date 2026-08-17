---
type: community
cohesion: 0.27
members: 11
---

# Community 347

**Cohesion:** 0.27 - loosely connected
**Members:** 11 nodes

## Members
- [[dot-test_auth_still_required()]] - code - tests/test_p0_16_cron_endpoint.py
- [[dot-test_concurrent_guard_checked_before_rate_limit()]] - code - tests/test_p0_16_cron_endpoint.py
- [[dot-test_returns_409_when_cron_already_running()]] - code - tests/test_p0_16_cron_endpoint.py
- [[dot-test_starts_successfully_when_no_cron_running()]] - code - tests/test_p0_16_cron_endpoint.py
- [[409 must be returned even when the per-IP rate limit is not yet exceeded.]] - rationale - tests/test_p0_16_cron_endpoint.py
- [[Concurrent guard must not bypass authentication.]] - rationale - tests/test_p0_16_cron_endpoint.py
- [[If _is_cron_running() returns False and no rate limit, cron spawns.]] - rationale - tests/test_p0_16_cron_endpoint.py
- [[If _is_cron_running() returns True, endpoint must return 409.]] - rationale - tests/test_p0_16_cron_endpoint.py
- [[TestRunCronConcurrentGuard]] - code - tests/test_p0_16_cron_endpoint.py
- [[_auth_headers()]] - code - tests/test_p0_16_cron_endpoint.py
- [[_make_app()_1]] - code - tests/test_p0_16_cron_endpoint.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_347
SORT file.name ASC
```

## Connections to other communities
- 3 edges to [[_COMMUNITY_Community 41]]

## Top bridge nodes
- [[_make_app()_1]] - degree 5, connects to 1 community
- [[TestRunCronConcurrentGuard]] - degree 5, connects to 1 community
- [[_auth_headers()]] - degree 4, connects to 1 community