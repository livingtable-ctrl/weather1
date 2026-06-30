# Grade Audit — circuit_breaker.py

Graded: 2026-06-29
Grader: claude-sonnet-4-6

---

## TIER 1 Functions

---

### [circuit_breaker.py] CircuitBreaker.is_open() L:151–172  ★ T1

```
Score: 8/10  |  Confidence: Confirmed
AC: AC1 PASS — OPEN state returns True, blocking callers; AC2 PASS — HALF-OPEN set on exactly
    one caller (self._half_open = True then returns False for that caller only; subsequent callers
    hit the `if self._half_open: return True` guard); AC3 N/A (handled in record_failure);
    AC4 FAIL (INFO) — recovery_timeout is a constructor param, not read from .env — see note
Red flag: NONE
Invariants: I2 PASS — entire body under self._lock
STRENGTHS:
• Correct three-state machine: CLOSED (opened_at is None), HALF-OPEN transition (first caller
  past timeout), OPEN for all subsequent callers while half-open is in flight.
• suppress_probe path correctly keeps circuit OPEN during analysis phase.
• Monotonic clock used for elapsed check (immune to wall-clock drift / NTP jumps).
• INFO log on HALF-OPEN transition helps operators see recovery attempts.
WEAKNESSES:
• line 169: _failure_count reset to 0 here inside is_open() rather than in record_success().
  This is a side effect in a read-like method that could confuse readers and makes unit testing
  state transitions slightly fragile, but does not cause a live bug.
• line 170: _save_state() called inside is_open() while holding self._lock. _save_state()
  acquires _CB_STATE_FILE_LOCK (a different lock). This is safe because the ordering is always
  self._lock then _CB_STATE_FILE_LOCK, but the nested locking is non-obvious and undocumented.
• AC4 (INFO): failure_threshold and recovery_timeout are constructor params defaulting to 5/300.
  The module-level singletons in weather_markets.py presumably pass explicit values, but those
  values are not sourced from .env — hardcoded at call site. Operationally this means changing
  thresholds requires a code push, not a config change. Flag as INFO per AC4 note.
FAILURE SCENARIO (score is 8, not required, but noting the side effect risk):
  If is_open() is called concurrently from two threads at the exact moment elapsed >= timeout,
  the first one sets _half_open=True and returns False (probe); the second hits the
  `if self._half_open: return True` guard and returns True. This is the correct intended
  behavior — the lock ensures only one caller wins the HALF-OPEN transition.
VERDICT: keep as-is
```

---

### [circuit_breaker.py] CircuitBreaker.record_failure() L:174–225  ★ T1

```
Score: 8/10  |  Confidence: Confirmed
AC: AC1 PASS — OPEN state is set here, callers will see is_open()=True after this;
    AC2 PASS — probe failure path at L176–195 reopens correctly with incremented trip_count
               and backoff applied; AC3 PASS — burst_window check at L197–204 de-duplicates
               parallel failures within the window; AC4 FAIL (INFO) — same as is_open()
Red flag: NONE
Invariants: I2 PASS — entire body under self._lock
STRENGTHS:
• Burst window logic correctly uses wall-clock (time.time()) so it survives across
  brief process restarts (persisted _last_failure_at is reloaded from disk).
• Probe-failure path (L176–195) correctly increments trip_count and applies backoff before
  reopening — exponential backoff accumulates across open/close cycles as intended.
• `if self._opened_at is None` guard at L208 prevents re-tripping an already-open circuit
  from re-incrementing trip_count on every failure — correct.
• WARNING log on open with failure count and retry time — good operator visibility.
WEAKNESSES:
• line 207: `if self._failure_count >= self.failure_threshold` — the burst window absorbs
  rapid parallel failures, but if burst_window=0 (default), three parallel failures all
  record and increment _failure_count. This is documented intentional behavior (burst_window
  defaults to 0), but callers must opt in. The default of 0 means a thundering herd against
  a fresh CircuitBreaker(burst_window=0) WILL count each failure separately. Whether
  module-level singletons set burst_window correctly is outside this file.
• line 225: _save_state() is called outside the HALF-OPEN branch (it's at the end of the
  normal path). For the burst window early-return at L204, _save_state() is NOT called —
  this means _last_failure_at is updated in memory but not persisted immediately. If the
  process crashes within the burst window, the next restart might double-count the same
  parallel burst as two events. Low-probability but possible.
FAILURE SCENARIO:
  Process restarts between two parallel failures of the same batch (both within burst_window):
  restart 1 records failure 1 and persists last_failure_at. The second failure lands after
  restart but within burst_window — still correctly absorbed. However if the restart happens
  AFTER failure 2's burst-window early-return but BEFORE its _save_state() would have been
  called in a normal path, the last_failure_at for that batch is not updated on disk. Next
  failure batch would be treated as a new event. Net effect: one extra failure event counted
  across a crash boundary. Low severity.
VERDICT: keep as-is (the burst_window early-return no-save is an acceptable trade-off)
```

---

### [circuit_breaker.py] CircuitBreaker.record_success() L:227–238  ★ T1

```
Score: 9/10  |  Confidence: Confirmed
AC: AC1 N/A (success path); AC2 PASS — was_half_open tracked, INFO log on probe success,
    _trip_count intentionally preserved (documented); AC3 N/A; AC4 N/A
Red flag: NONE
Invariants: I2 PASS — entire body under self._lock
STRENGTHS:
• Clear reset: _failure_count=0, _opened_at=None, _wall_opened_at=None — circuit is fully
  closed after success.
• was_half_open saved before clearing _half_open — allows correct conditional log without
  re-reading mutable state.
• Intentionally preserves _trip_count and _current_timeout so backoff accumulates — comment
  explains this explicitly.
• Single INFO log on probe success gives operators visibility into recovery.
WEAKNESSES:
• line 237: Only logs when was_half_open. If record_success() is called on a CLOSED circuit
  (e.g., during normal operation), it silently resets _failure_count. This is correct behavior
  but means a partial-failure streak (e.g., 3 out of 5) is silently forgiven on the next
  success. Could mask flapping behavior from operators. Minor gap.
VERDICT: keep as-is
```

---

### [circuit_breaker.py] CircuitBreaker.execute() L:261–275  ★ T1

```
Score: 8/10  |  Confidence: Confirmed
AC: AC1 PASS — raises CircuitOpenError immediately when is_open(); no "log and proceed"
    path exists; AC2 PASS — is_open() handles HALF-OPEN transition; record_success/failure
    called correctly; AC3 N/A (burst handled in record_failure); AC4 N/A
Red flag: NONE
Invariants: I2 N/A (execute() delegates state reads to is_open()); I10 N/A (gate is in
  calling code — execute() is the mechanism, not the paper/live gate)
STRENGTHS:
• Clean try/except/raise pattern — records failure then re-raises, preserving original
  exception for callers.
• CircuitOpenError is a named exception subclass with source name — callers can distinguish
  circuit-open from other errors.
• record_success() called only on the happy path — correct.
WEAKNESSES:
• line 272: bare `except Exception` catches all exceptions including KeyboardInterrupt
  subclasses that happen to inherit from Exception. In Python 3, KeyboardInterrupt does not
  inherit from Exception, so this is actually safe. But a SystemExit or similar that does not
  inherit from BaseException could be swallowed. In practice this is fine for the Kalshi API
  call context.
• execute() does not log the CircuitOpenError it raises — the caller sees the exception but
  there is no WARNING at the point of rejection. Operators relying on logs to see rejection
  events will need to check the caller's handling of CircuitOpenError.
VERDICT: keep as-is
```

---

### [circuit_breaker.py] FlashCrashCB.check() L:334–358  ★ T1

```
Score: 7/10  |  Confidence: Confirmed
AC: AC1 PASS — returns True on crash (caller is responsible for blocking trades, but the
    method correctly signals); AC2 N/A; AC3 N/A; AC4 FAIL (INFO) — threshold_pct,
    window_seconds, cooldown_seconds are constructor params, not sourced from .env
Red flag: NONE
Invariants: I2 N/A (no _DATA_LOCK here — FlashCrashCB is single-instance and not thread-safe,
  but per-market flash crash checks are called from the single scan loop, so this is acceptable)
STRENGTHS:
• Correct sliding window: prunes old observations before comparing, immune to stale history.
• Detects both upward and downward moves (abs() on the delta).
• oldest_price <= 0 guard prevents division by zero on bad market data.
• WARNING log with exact percentage, window, and cooldown — good operator visibility.
• Persists cooldowns to disk — survives process restarts.
WEAKNESSES:
• line 344: compares current_price against the OLDEST price in the window, not against a
  recent anchor. This means a gradual 5%+5%+10% drift over 5 minutes (20% total) trips the
  breaker at the third observation, but a 19% drop followed by a 1% recovery does not re-trip.
  This is a design choice but it means the circuit can be "confused" by noise if the window
  contains a very old outlier. Possible but not necessarily wrong.
• line 342: `if len(self._history[ticker]) < 2: return False` — if the history was just
  pruned to 1 element (old data), a new crash happening right now would not be detected on
  this call. The next call would detect it. One-tick blind spot on re-entry after window expiry.
• FlashCrashCB is not thread-safe (no lock). If check() is ever called from multiple threads
  simultaneously for different tickers, _history and _cooldowns could be corrupted. Current
  usage is single-threaded scan loop so this is acceptable.
• AC4 (INFO): all three thresholds are constructor params. The module-level singleton
  `flash_crash_cb = FlashCrashCB()` uses hardcoded defaults (threshold_pct=0.20,
  window_seconds=300, cooldown_seconds=600). Changing these requires code push.
FAILURE SCENARIO:
  A market spikes from 0.50 → 0.65 in one minute (within window). Window expires (300s later).
  New observation arrives at 0.65. History is pruned to just this one entry. Next tick: market
  drops to 0.40 (-38%). Because history has only 1 entry, this call returns False (L342 guard).
  Only the call AFTER that would detect the 38% move (comparing 0.65 vs 0.40). One-tick blind
  spot on window re-entry. In fast-moving markets this could miss the first tick of a crash.
VERDICT: keep as-is (one-tick blind spot is tolerable; thread-safety acceptable given usage)
```

---

### [circuit_breaker.py] FlashCrashCB.is_in_cooldown() L:360–361  ★ T1

```
Score: 8/10  |  Confidence: Confirmed
AC: AC1 PASS — correctly returns True when ticker is in cooldown, blocking trade logic at
    the caller; AC2 N/A; AC3 N/A; AC4 N/A
Red flag: NONE
Invariants: I2 N/A (see check() note on thread safety)
STRENGTHS:
• Minimal, correct: `time.time() < self._cooldowns.get(ticker, 0)` — defaults to 0 (epoch)
  so an unknown ticker always returns False. No exception possible.
• Implicit cooldown expiry: expired entries are never removed but `get(ticker, 0)` always
  returns a past timestamp for expired cooldowns → False. Clean.
WEAKNESSES:
• _cooldowns dict grows unboundedly — every ticker that ever trips the flash crash breaker
  adds an entry that is never cleaned up in memory (only filtered on _save_cooldowns). For a
  bot scanning many markets over months this is a slow memory leak. Low severity.
VERDICT: keep as-is
```

---

## TIER 2 Functions

---

```
[circuit_breaker.py] CircuitOpenError.__init__() L:34–38  9/10 — Named exception with
  source name; clean, correct, no issues.  [Confidence: C]
```

```
[circuit_breaker.py] CircuitBreaker.__init__() L:42–68  8/10 — Correct initialization of
  all state fields; burst_window default 0.0 (no burst protection unless explicitly set);
  calls _load_state() at end which handles missing file gracefully.  [Confidence: C]
```

```
[circuit_breaker.py] CircuitBreaker._load_state() L:70–112  7/10 — Correctly reconstructs
  monotonic equivalent from wall-clock elapsed; handles backoff_multiplier<=1 vs >1 to respect
  code-level config changes; HALF-OPEN and _probe_enabled not restored (lost across restarts,
  intentional). Gap: exception caught at L111 logs at DEBUG not WARNING — operator cannot see
  corrupt state file without debug logging enabled (RF1 borderline: the state file corruption
  is non-critical and the comment says so, but losing circuit state silently on corruption is
  a Likely/Possible concern rather than a clear RF1 fire).  [Confidence: L]
FIX: circuit_breaker.py:111 — change `_log.debug("CB state load failed...")` to
  `_log.warning("CB state load failed (circuit state reset to default): %s", exc)` so
  operators see when persistence breaks.
```

```
[circuit_breaker.py] CircuitBreaker._save_state() L:114–138  7/10 — Uses atomic_write_json
  (I3 PASS); acquires _CB_STATE_FILE_LOCK before read-modify-write (I2 analog PASS); inner
  json.loads exception caught silently at L123 (resets entire state dict — could lose state
  for other circuit instances if only one instance's file is corrupt). Outer exception at L137
  logs at DEBUG not WARNING — same issue as _load_state().  [Confidence: C]
FIX: circuit_breaker.py:137 — change `_log.debug("CB state save failed...")` to
  `_log.warning(...)` for operator visibility.
```

```
[circuit_breaker.py] CircuitBreaker.suppress_probe() L:140–149  8/10 — Simple, correct,
  thread-safe. Well-documented docstring explains the use case (prewarm phase). No issues.
  [Confidence: C]
```

```
[circuit_breaker.py] CircuitBreaker.failure_count (property) L:240–243  9/10 — Thread-safe
  read under self._lock; returns int copy. No issues.  [Confidence: C]
```

```
[circuit_breaker.py] CircuitBreaker.seconds_open() L:245–250  8/10 — Uses wall-clock
  (time.time()) correctly for operator-facing display; returns 0.0 when closed. Thread-safe.
  [Confidence: C]
```

```
[circuit_breaker.py] CircuitBreaker.seconds_until_retry() L:252–259  8/10 — Uses monotonic
  clock correctly for interval calculation; max(0.0, remaining) prevents negative return.
  Returns 0.0 for HALF-OPEN (correct — probe is already dispatched). Thread-safe.
  [Confidence: C]
```

```
[circuit_breaker.py] FlashCrashCB.__init__() L:294–305  8/10 — Correct initialization;
  calls _load_cooldowns() to restore persisted state on startup. threshold_pct/window_seconds/
  cooldown_seconds not from .env (AC4 INFO — same as noted in check()).  [Confidence: C]
```

```
[circuit_breaker.py] FlashCrashCB._load_cooldowns() L:307–322  7/10 — Correctly filters
  expired cooldowns on load; logs at INFO when active cooldowns are restored (good operator
  visibility). Exception at L321 logs at DEBUG — same operator visibility gap as _load_state()
  but flash crash cooldown loss is more operationally significant (a market could get traded
  during what should be a cooldown). Borderline RF1.  [Confidence: L]
FIX: circuit_breaker.py:322 — change `_log.debug(...)` to `_log.warning(...)`.
```

```
[circuit_breaker.py] FlashCrashCB._save_cooldowns() L:324–332  7/10 — Uses atomic_write_json
  (I3 PASS); filters expired entries before saving. Exception at L332 logs at DEBUG — same
  operator visibility gap. If save fails silently, a cooldown is not persisted and the market
  could be traded after a restart.  [Confidence: C]
FIX: circuit_breaker.py:332 — change `_log.debug(...)` to `_log.warning(...)`.
```

```
[circuit_breaker.py] flash_crash_cb (module-level singleton) L:365 — Module-level singleton
  constructed with hardcoded defaults (threshold_pct=0.20, window_seconds=300,
  cooldown_seconds=600). AC4 note: changing these requires code push. Acceptable given current
  volume but worth noting for production hardening.
```

---

## Summary Table

| Function | Tier | Score | Verdict |
|---|---|---|---|
| CircuitOpenError.__init__ | T2 | 9/10 | keep |
| CircuitBreaker.__init__ | T2 | 8/10 | keep |
| CircuitBreaker._load_state | T2 | 7/10 | fix (DEBUG→WARNING) |
| CircuitBreaker._save_state | T2 | 7/10 | fix (DEBUG→WARNING) |
| CircuitBreaker.suppress_probe | T2 | 8/10 | keep |
| CircuitBreaker.is_open | T1 | 8/10 | keep |
| CircuitBreaker.record_failure | T1 | 8/10 | keep |
| CircuitBreaker.record_success | T1 | 9/10 | keep |
| CircuitBreaker.failure_count | T2 | 9/10 | keep |
| CircuitBreaker.seconds_open | T2 | 8/10 | keep |
| CircuitBreaker.seconds_until_retry | T2 | 8/10 | keep |
| CircuitBreaker.execute | T1 | 8/10 | keep |
| FlashCrashCB.__init__ | T2 | 8/10 | keep |
| FlashCrashCB._load_cooldowns | T2 | 7/10 | fix (DEBUG→WARNING) |
| FlashCrashCB._save_cooldowns | T2 | 7/10 | fix (DEBUG→WARNING) |
| FlashCrashCB.check | T1 | 7/10 | keep |
| FlashCrashCB.is_in_cooldown | T1 | 8/10 | keep |

**File median: 8/10. No active bugs on live trading paths. Four TIER 2 functions need DEBUG→WARNING log level upgrades for operator visibility.**

---

## Cross-Cutting Findings

**AC4 (INFO — not a deduction):** All thresholds (`failure_threshold`, `recovery_timeout`,
`backoff_multiplier`, `burst_window`, `threshold_pct`, `window_seconds`, `cooldown_seconds`)
are constructor parameters or defaults. None are read from `.env`. The module-level
`flash_crash_cb` singleton uses hardcoded defaults. Changing thresholds in production requires
a code push and process restart. Operationally acceptable but increases response time during
an active outage. Consider adding `.env` override reads in a future hardening pass.

**No RF1–RF6 violations on TIER 1 functions.**

**No I1–I10 violations.**

**Test coverage is solid:** `test_circuit_breaker.py` covers basic open/close/half-open,
backoff accumulation (6 tests), burst window (2 tests), and the weather_markets blend
fallback. `test_flash_crash_cb.py` covers crash detection, cooldown, multi-ticker independence,
cooldown expiry, and upward spikes. The only gap is no test for _load_state()/_save_state()
persistence round-trip, but these are TIER 2 and the gap does not cap any TIER 1 score.
