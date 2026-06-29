# MODULE: forecast_cache.py

## Before You Start
Read `tests/test_forecast_cache.py` before grading.

## TIER 1 Functions
Any function that reads or writes the in-memory cache under concurrent access.

## Acceptance Criteria
A function CANNOT score above 7 if it fails any of these.

- AC1: All cache read and write operations are protected by a threading lock. The cron
  loop and background NWS fetch threads access the cache concurrently — an unprotected
  cache can return stale or partially-written data.
- AC2: Cache invalidation on TTL expiry is atomic — a thread reading an expired entry
  while another is refreshing it must get either the old value or the new value, never
  a partially-overwritten one.
- AC3: If the cache fetch raises an exception, the caller receives a graceful fallback
  (None or a sentinel) — not an unhandled exception that aborts the cron cycle.
