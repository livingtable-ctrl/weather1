# Grade Audit — forecast_cache.py
**Graded:** 2026-06-29
**Model:** claude-sonnet-4-6
**File:** `forecast_cache.py` (114 lines)
**Module spec:** `docs/grade_audit/modules/forecast_cache.md`

---

## Summary

`forecast_cache.py` is a small, standalone module: a single class (`ForecastCache[T]`) with 9
methods. Its entire purpose is to be a thread-safe in-memory TTL cache used concurrently by the
cron loop and background NWS fetch threads.

Per the module spec, **every function that reads or writes the cache under concurrent access is TIER 1**.
That is effectively every public method of the class, since all of them touch `self._store`. The
private helper `_evict_oldest` is also graded because it is called from within `set()` and
`set_with_ttl()` while the lock is held.

---

## TIER 1 Functions

---

### `[forecast_cache.py] ForecastCache.__init__() L:15–19  ★ T1`
```
Score: 9/10  |  Confidence: Confirmed
AC: ALL PASS
Red flag: NONE
Invariants: AC1 PASS (lock created here), AC2 N/A (constructor), AC3 N/A (constructor)

STRENGTHS:
• Creates a threading.Lock at construction time — lock is always available before any
  read/write path is entered.
• Sensible defaults: 4-hour TTL, max_size=500, both are configurable by callers.
• _store is a plain dict — deterministic iteration order (Python 3.7+), fast O(1) access.

WEAKNESSES:
• line 18: No validation that ttl_secs > 0 or max_size > 0. A caller passing ttl_secs=0
  would cause every entry to expire instantly (time.monotonic() - ts > 0 is immediately
  true) — effectively disabling the cache. This is unlikely in production but
  not guarded against.

VERDICT: keep as-is (the missing guard is minor; callers pass sensible constants)
```

---

### `[forecast_cache.py] ForecastCache.get() L:21–37  ★ T1`
```
Score: 8/10  |  Confidence: Confirmed
AC: ALL PASS
Red flag: NONE
Invariants: AC1 PASS (with self._lock), AC2 PASS (del under lock before returning None), AC3 N/A

STRENGTHS:
• Entire body executes under self._lock — no gap between read and conditional delete.
• Correctly handles both 2-tuple (class-default TTL) and 3-tuple (per-entry TTL) storage
  formats in a single code path.
• Expired entries are deleted on access (lazy eviction) — prevents unbounded growth even
  without explicit prune_expired() calls.
• Clear inline comment explaining the 2-tuple vs 3-tuple distinction (L5-A note).

WEAKNESSES:
• line 28: len(entry) == 3 discriminator is fragile. If a value is ever stored as a
  tuple with exactly 3 elements (e.g. a NWS forecast triple), the cache will
  misinterpret it as a per-entry-TTL entry. The third element would be used as
  effective_ttl and time.monotonic() - ts > weather_triple[2] would almost certainly
  fire immediately (most forecast values are not in the range of seconds-since-epoch
  when used as TTL). This is a latent bug: no production key currently stores a 3-tuple
  value, but the schema is fragile.
• No test for the concurrent-access path (two goroutines racing on the same key). The
  existing tests are single-threaded, so AC1 is structurally correct but not
  regression-tested.

FAILURE SCENARIO:
A caller stores a value that happens to be a 3-element tuple, e.g.:
  cache.set("KORD", (temp_f, dew_f, wind_mph))
get() sees len(entry)==3, treats wind_mph as a TTL in seconds. If wind_mph is 12.0,
the entry expires in 12 seconds regardless of the configured TTL. The caller gets None
after 12 seconds thinking the cache missed, falls through to the NWS network call,
and hammers the API every 12 seconds instead of every 4 hours.

VERDICT: fix before live — the value discriminator should use a wrapper type or a
dedicated sentinel field, not len(tuple).
```

---

### `[forecast_cache.py] ForecastCache._evict_oldest() L:39–44  ★ T1`
```
Score: 8/10  |  Confidence: Confirmed
AC: ALL PASS (called while lock is already held by set/set_with_ttl)
Red flag: NONE
Invariants: AC1 PASS (lock held by caller)

STRENGTHS:
• Docstring explicitly states "Must hold _lock" — correct contract documentation.
• Guards against empty store before calling min().
• Uses entry[1] (the timestamp field) for LRU selection — correctly evicts oldest entry.

WEAKNESSES:
• line 43: min() over all keys is O(N) — for max_size=500 this is negligible, but there
  is no comment explaining why a full scan was chosen over a sorted structure.
• The "Must hold _lock" contract is enforced by convention only — no assertion or
  type-level enforcement. A future caller could invoke _evict_oldest() without holding
  the lock.

VERDICT: keep as-is
```

---

### `[forecast_cache.py] ForecastCache.set() L:46–50  ★ T1`
```
Score: 8/10  |  Confidence: Confirmed
AC: ALL PASS
Red flag: NONE
Invariants: AC1 PASS (with self._lock), AC2 PASS (atomic tuple write under lock), AC3 N/A

STRENGTHS:
• Entire body under self._lock — no partial-write window.
• Calls _evict_oldest() before insert when at capacity — store never exceeds max_size.
• Eviction only triggers when the key is NEW (key not in self._store check) — updating
  an existing key does not count against capacity, which is the correct LRU policy.

WEAKNESSES:
• line 48: The eviction guard `key not in self._store` is evaluated inside the lock,
  which is correct. However, _evict_oldest() uses entry[1] (index 1 of tuple) as
  the timestamp. If a 3-tuple entry is the oldest, entry[1] still points to the
  timestamp (the second element), so eviction logic is correct for both formats.
• Same len(tuple) fragility inherited from the storage format (see get() weakness).

VERDICT: keep as-is
```

---

### `[forecast_cache.py] ForecastCache.set_with_ttl() L:52–61  ★ T1`
```
Score: 8/10  |  Confidence: Confirmed
AC: ALL PASS
Red flag: NONE
Invariants: AC1 PASS (with self._lock), AC2 PASS (atomic 3-tuple write under lock), AC3 N/A

STRENGTHS:
• Clear docstring explaining the L5-A cycle-alignment use case.
• Correctly stores a 3-tuple (value, ts, ttl_secs) — consistent with get() parser.
• Lock discipline identical to set() — no gap.
• Eviction guard present and correct.

WEAKNESSES:
• line 61: No validation that ttl_secs > 0. A caller passing ttl_secs=0 silently creates
  an entry that expires before it can be read. Low probability in current code; callers
  use _ttl_until_next_cycle() which has a 1800s floor.

VERDICT: keep as-is
```

---

### `[forecast_cache.py] ForecastCache.set_at() L:63–66  ★ T1`
```
Score: 7/10  |  Confidence: Confirmed
AC: FAIL AC1 — lock IS present, so AC1 technically passes, but see weakness below
Red flag: NONE
Invariants: AC1 PASS (with self._lock)

STRENGTHS:
• Allows restoring cache entries from disk with their original timestamp — correct
  use case for restart/warm-up scenarios.
• Lock acquired correctly.

WEAKNESSES:
• line 65: set_at() does not enforce max_size — it bypasses the eviction guard entirely.
  A bulk restore from disk (e.g., 1000 entries) would silently push the store past
  max_size, making subsequent evictions less effective and potentially causing memory
  growth. This is a correctness gap if set_at() is ever called in a loop.
• No test coverage for set_at(). There is no test that calls set_at() and verifies
  subsequent get() behavior or TTL correctness.
• The ts parameter is documented as a monotonic timestamp, but nothing prevents a caller
  from passing a wall-clock timestamp (time.time()), which would cause incorrect TTL
  calculations since TTL checks compare against time.monotonic().

FAILURE SCENARIO:
A caller restores 600 entries via set_at() during a warm-up routine. The store silently
grows to 600 entries, exceeding max_size=500. Subsequent set() calls trigger eviction
of entries that may still be valid. The mismatch could cause excess NWS API calls
during the first cron cycle after restart.

VERDICT: fix before live — add eviction guard consistent with set() and add a note that
ts must be a monotonic timestamp.
```

---

### `[forecast_cache.py] ForecastCache.get_with_ts() L:68–90  ★ T1`
```
Score: 9/10  |  Confidence: Confirmed
AC: ALL PASS
Red flag: NONE
Invariants: AC1 PASS (with self._lock), AC2 PASS (del under lock before returning miss), AC3 N/A

STRENGTHS:
• Excellent docstring explaining the wall-clock conversion and why it reflects store time
  not call time.
• Correctly handles both 2-tuple and 3-tuple formats — consistent with get().
• The wall-clock derivation (time.time() - age) is correct and is verified by the test
  test_get_with_ts_wall_clock_reflects_original_store_time.
• Returns a clean sentinel (None, False, 0.0) on miss or expiry.
• Expired entries are deleted lazily under the lock — same guarantee as get().
• Good test coverage: 5 distinct tests cover miss, hit, expiry, wall-clock accuracy, and
  per-entry TTL. This is the best-tested method in the file.

WEAKNESSES:
• Minor: line 88-89 calls time.monotonic() twice (once for expiry check at line 85, once
  for age at line 88). In theory a sleep could occur between the two calls causing a
  tiny drift in the returned wall_clock_ts. In practice this is nanoseconds and
  irrelevant, but a single local `now = time.monotonic()` at the top of the lock block
  would be cleaner.

VERDICT: keep as-is
```

---

### `[forecast_cache.py] ForecastCache.prune_expired() L:92–105  ★ T1`
```
Score: 7/10  |  Confidence: Confirmed
AC: ALL PASS
Red flag: NONE
Invariants: AC1 PASS (with self._lock), AC2 PASS (build list then delete under single lock), AC3 N/A

STRENGTHS:
• Captures now = time.monotonic() BEFORE acquiring the lock — this is intentional and
  correct: it prevents time from advancing between the snapshot and the comparisons,
  giving a consistent expiry horizon for the entire prune operation.
• Builds the expired list first, then deletes — correct two-phase approach inside
  a single lock acquisition, so no concurrent modification during iteration.
• Returns count of removed entries — useful for logging/metrics by callers.

WEAKNESSES:
• line 94: now = time.monotonic() is called OUTSIDE the lock. In theory, entries could
  be inserted between line 94 and lock acquisition that have a ts > now (impossible
  since ts = time.monotonic() at insert time ≥ now). This is actually safe — new
  entries inserted after now will have ts > now and won't be expired. But the pattern
  looks wrong at first glance and lacks a comment.
• No test coverage for prune_expired(). There is no test that:
  - Verifies it returns the correct count
  - Verifies expired entries are gone after calling it
  - Verifies non-expired entries survive
• The line 100 inline lambda `entry[2] if len(entry) == 3 else self._ttl` duplicates the
  TTL resolution logic from get() and get_with_ts() — a shared helper would reduce
  duplication and eliminate the len(tuple) fragility in one place.

FAILURE SCENARIO:
With no test coverage, a future refactor of the storage format (e.g., switching to a
dataclass) could break prune_expired() silently while get() and get_with_ts() continue
to pass their tests.

VERDICT: fix before live — add tests for prune_expired() and extract TTL resolution to
a shared helper to eliminate the three-site len(entry) == 3 pattern.
```

---

### `[forecast_cache.py] ForecastCache.clear() L:107–109  ★ T1`
```
Score: 9/10  |  Confidence: Confirmed
AC: ALL PASS
Red flag: NONE
Invariants: AC1 PASS (with self._lock)

STRENGTHS:
• Minimal and correct — dict.clear() under lock is atomic from the perspective of other
  threads.
• Covered by test_clear_empties_cache which verifies len() == 0 after clearing multiple
  entries.

WEAKNESSES:
• Extremely minor: no return value — callers cannot know how many entries were cleared.
  This is stylistic, not a bug.

VERDICT: keep as-is
```

---

### `[forecast_cache.py] ForecastCache.__len__() L:111–113  ★ T1`
```
Score: 9/10  |  Confidence: Confirmed
AC: ALL PASS
Red flag: NONE
Invariants: AC1 PASS (with self._lock)

STRENGTHS:
• Lock acquired for len() — prevents torn reads during concurrent insert/delete.
• Used in test_clear_empties_cache (len(c) == 0 assertion), so there is test coverage.

WEAKNESSES:
• None significant. len() of a dict is O(1) in CPython.

VERDICT: keep as-is
```

---

## Cross-Cutting Issues

### Issue 1 — Storage format fragility (len(tuple) discriminator)

**Affected lines:** 28, 79, 100
**Confidence:** Confirmed

The 2-tuple vs 3-tuple discriminator using `len(entry) == 3` appears in three places:
`get()`, `get_with_ts()`, and `prune_expired()`. This is a latent bug:

- Any value that is itself a 3-element tuple will be misread as a per-entry-TTL entry.
- The third element of the value tuple will be used as `effective_ttl` in seconds.
- If the third element is large (e.g., temperature = 95.0), the entry will appear valid
  for 95 seconds instead of the configured TTL. If it is small (e.g., 0.02 probability),
  the entry expires in 20 milliseconds.

**Current exposure:** The cron/NWS path stores GFS ensemble lists, dicts, and floats —
none of which are 3-element tuples today. But weather forecast data structures do
sometimes come in triples (temp, dew, precip). If a future caller stores a 3-tuple
value without using set_with_ttl(), the bug fires silently.

**Fix:**
```python
# Use a named dataclass or a wrapper instead of bare tuples
from dataclasses import dataclass, field

@dataclass
class _CacheEntry:
    value: object
    ts: float
    ttl: float  # always explicit — class default filled in at store time
```
Or simpler: store a dict `{"v": value, "ts": ts, "ttl": effective_ttl}` and fill in
the class-default TTL at `set()` time, eliminating the conditional everywhere.

### Issue 2 — No test for concurrent access

**Confidence:** Confirmed (structural gap)

All 13 tests are single-threaded. The module's primary safety property — that concurrent
reads and writes never produce torn data — is untested. A threading bug introduced in a
refactor would not be caught by the test suite.

A minimal concurrent test:
```python
def test_concurrent_set_get_no_torn_read():
    import threading
    c = ForecastCache(ttl_secs=60)
    errors = []
    def writer():
        for i in range(1000):
            c.set("k", i)
    def reader():
        for _ in range(1000):
            v = c.get("k")
            if v is not None and not isinstance(v, int):
                errors.append(v)
    t1, t2 = threading.Thread(target=writer), threading.Thread(target=reader)
    t1.start(); t2.start(); t1.join(); t2.join()
    assert not errors
```

---

## File-Level Scores

| Function | Score | Tier |
|---|---|---|
| `__init__` | 9/10 | T1 |
| `get` | 8/10 | T1 |
| `_evict_oldest` | 8/10 | T1 |
| `set` | 8/10 | T1 |
| `set_with_ttl` | 8/10 | T1 |
| `set_at` | 7/10 | T1 |
| `get_with_ts` | 9/10 | T1 |
| `prune_expired` | 7/10 | T1 |
| `clear` | 9/10 | T1 |
| `__len__` | 9/10 | T1 |

**File median: 8/10**
**Lowest score: 7/10** (`set_at`, `prune_expired`)

---

## Prioritized Fixes

1. **[MEDIUM] Storage format fragility** — replace the `len(entry) == 3` discriminator
   with a typed wrapper (`_CacheEntry` dataclass or a fixed-schema dict). Affects
   `get()`, `get_with_ts()`, and `prune_expired()`. Risk: low today, but a silent
   correctness bug when any 3-element tuple value is stored.

2. **[LOW] `set_at()` bypasses max_size eviction** — add the same `if key not in
   self._store and len(self._store) >= self._max_size: self._evict_oldest()` guard
   present in `set()` and `set_with_ttl()`.

3. **[LOW] Add tests for `prune_expired()`** — happy path (returns correct count, expired
   gone, non-expired survive) and concurrent access.

4. **[INFO] `set_at()` monotonic vs wall-clock ambiguity** — document that `ts` must be
   a monotonic timestamp, or add an assertion.

---

## Overall Assessment

`forecast_cache.py` is a well-structured, focused module. Lock discipline is correct on
every method — all reads and writes hold `self._lock` for the entire operation.
The per-entry TTL feature (L5-A) is correctly implemented and well-tested. The
`get_with_ts()` wall-clock derivation is the most subtle piece of logic and it is
correct and well-tested.

The one cross-cutting concern is the `len(entry) == 3` storage-format discriminator,
which is a latent bug that would silently corrupt TTL behavior if a 3-element tuple were
ever stored as a value. It is not a live bug today, but the pattern is brittle enough to
fix before the codebase grows.

No red flags (RF1–RF6) fired. No invariant violations found. The module is safe for
continued production use at current trade volume.
