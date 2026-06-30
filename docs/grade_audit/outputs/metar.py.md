# Grade Audit — metar.py
Generated: 2026-06-29

---

## Summary

| Function | Tier | Score |
|---|---|---|
| `_dynamic_lock_in_confidence()` | T1 | 9/10 |
| `fetch_metar()` | T1 | 8/10 |
| `check_metar_lockout()` | T1 | 8/10 |
| `record_observation()` | T1 | 8/10 |
| `get_station_bias()` | T1 | 7/10 |
| `_load_obs()` | T2 | 6/10 |
| `_load_obs_nolock()` | T2 | 7/10 |
| `_save_obs_nolock()` | T2 | 7/10 |
| `_save_obs()` | T2 | 6/10 |
| `_safe_extreme()` (nested in fetch_metar) | T2 | 8/10 |
| `get_obs_count()` | T2 | 7/10 |

---

## TIER 1 Functions

---

### `_dynamic_lock_in_confidence()` L:24–50  ★ T1

```
[metar.py] _dynamic_lock_in_confidence() L:24–50  ★ T1
Score: 9/10  |  Confidence: Confirmed
AC: N/A (no AC assigned to this function specifically)
Red flag: NONE
Invariants: None directly applicable (does not touch trading gates, balance, DB, or
  Kelly formula — it computes a probability scalar that is consumed by check_metar_lockout)
STRENGTHS:
• Clean, well-documented formula with concrete worked examples in the docstring
  (0.720 to 0.970 range explicitly called out)
• min/max clamps prevent out-of-range returns even with pathological inputs
• Separates two orthogonal factors (clearance, hour) rather than a magic table
• round(…, 3) prevents floating-point noise from propagating into confidence values
• Regression test suite in TestDynamicLockInConfidence covers: near-threshold early
  afternoon, large clearance late evening, monotonicity in clearance, monotonicity in hour
WEAKNESSES:
• line 48: h_factor saturates at hour 20 (8 PM): (local_hour - 14) / 6.0.  An
  observation at hour 23 gives h_factor=1.0 same as hour 20 — this is intentional
  saturation, but after hour 20 confidence will not continue to increase even with a
  larger spread. Documented by comment but not in the docstring.
• The constant 6.0 divisor is implicit "8 PM saturates" logic buried in arithmetic;
  a named constant (_LOCK_IN_SATURATION_HOUR = 20) would make the invariant explicit.
VERDICT: keep as-is
```

---

### `fetch_metar()` L:74–205  ★ T1

```
[metar.py] fetch_metar() L:74–205  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: AC1 PASS — returns None on HTTP failure (line 102), empty response (line 106),
  missing temp_c (line 114), implausible range (line 125-128), unparseable/missing obsTime
  (line 153-159), stale observation >90 min (line 166-168)
Red flag: RF1 — POSSIBLE (see Weaknesses below; marginal)
Invariants: None of I1–I10 directly applicable to this HTTP-fetching utility.
STRENGTHS:
• Staleness gate is robust: rejects missing obsTime, unparseable obsTime, and
  observations older than 90 minutes — never silently uses a stale reading
• Celsius fallback conversion is correct (line 115)
• Plausibility bounds (-80°F to +140°F) prevent physically impossible values
• In-process cache with 15-minute TTL avoids redundant HTTP calls across markets
• All None-return paths are logged at WARNING or DEBUG
• dew_point_f extraction handles both dwpf (°F) and dwpt (°C) fields with separate
  try/except for each
• Nested _safe_extreme() applies plausibility check to min/max fields too
• AC1 is cleanly satisfied: no default temperature value is ever returned on failure
WEAKNESSES:
• line 99-102: The broad `except Exception` at the HTTP layer logs at DEBUG, not
  WARNING.  A network outage or TLS error would be invisible in production logs without
  debug logging enabled.  This is a recurring loss-of-observability issue: same-day
  lock-in silently fails and falls back to multi-day model without any operator alert.
  (RF1 is borderline: there is a log, but at DEBUG — not WARNING or above)
• lines 136-152: The obsTime fallback chain (int epoch → ISO string → reportTime ISO)
  is correct but has three bare `except Exception: pass` blocks with no logging.
  A corrupted obsTime field would silently fall through all three and then emit one
  WARNING at line 154.  This is acceptable overall since the final gate logs, but the
  intermediate silences make debugging API format changes harder.
• line 84-89: Cache is a module-level dict with no lock. Two threads calling fetch_metar
  concurrently for the same station could both miss the cache and make duplicate HTTP
  calls, or one could read a partially-written entry. In practice the weather-market
  scan is single-threaded for METAR lookups, so this has not fired. The risk is real
  under H11's ThreadPoolExecutor (8 concurrent NWS workers), but NWS and METAR are
  separate paths — low risk currently.
FAILURE SCENARIO:
  A transient network blip causes all METAR fetches to fail during the 2 PM–10 PM
  lock-in window. With DEBUG-only logging, the operator sees nothing in standard logs.
  The bot falls through to multi-day probability logic for same-day markets and places
  trades at a blended 0.55 instead of 0.92, losing edge without any alert.
VERDICT: keep as-is — raise HTTP exception log level to WARNING before scaling to
  more same-day markets
```

---

### `check_metar_lockout()` L:208–289  ★ T1

```
[metar.py] check_metar_lockout() L:208–289  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: AC2 PASS — line 232 converts obs_time to city local timezone via ZoneInfo(city_tz);
  line 235 gates on local_time.hour, not UTC hour
Red flag: NONE
Invariants: None of I1–I10 directly applicable.
STRENGTHS:
• AC2 satisfied cleanly: ZoneInfo conversion is correct and uses the city_tz parameter
  rather than hardcoding UTC or a fixed offset
• Fallback to UTC on ZoneInfo failure (line 234) is a known-safe degradation path —
  the only consequence is that cities with large UTC offsets (e.g. Pacific) might lock
  in slightly wrong, but the bot won't crash
• The NOT_LOCKED default dict is defined once and spread-merged — prevents accidental
  mutation of a shared sentinel
• All four directional lock-in branches (above/YES, above/NO, below/YES, below/NO) are
  handled symmetrically
• Dynamic confidence via _dynamic_lock_in_confidence() replaces hardcoded 0.90 (L6-D fix)
• Comprehensive test coverage: TestCheckMetarLockout covers early/late, above/below,
  within-margin; TestDynamicLockInConfidence covers monotonicity properties
WEAKNESSES:
• line 233-234: The fallback `except Exception: pass` on ZoneInfo failure produces no
  log. An invalid city_tz string would silently fall back to UTC. For Pacific cities
  this could cause a 7-8 hour local-time error, producing lock-ins at 7 AM local
  (14:00 UTC) — before the 2 PM local gate should fire. No test covers invalid
  city_tz.  This is the main gap.
• line 264-284: The "below" direction logic is correct but is the mirror image of
  "above" with no comment explaining the symmetry. A future maintainer editing one
  branch might forget to update the other.
• No guard for `direction` values other than "above" and "below" — an unexpected
  direction string (e.g. "between") falls through to the final NOT_LOCKED return
  silently. The caller would see locked=False with no explanation of why, which is
  correct behavior but the reason string says "temperature within margin" which is
  misleading.
FAILURE SCENARIO:
  city_tz="America/Los_Angeles" passed with a bad ZoneInfo installation or typo
  (e.g. "America/Los Angeles"). The except block silences the error and obs_time
  stays in UTC. At 14:00 UTC (6 AM PT) the hour check passes (14 >= 14), so lock-in
  fires 8 hours early. The bot places a same-day bet at 6 AM local time when the
  daily high has not peaked yet, potentially losing edge on the direction bet.
VERDICT: keep as-is — add WARNING log on ZoneInfo fallback (matches the known-good
  pattern already in the MEMORY notes: "METAR local-date fix afb7ed8 logs warning")
```

---

### `record_observation()` L:377–423  ★ T1

```
[metar.py] record_observation() L:377–423  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: AC3 PASS — line 416 calls _save_obs_nolock() which uses os.replace() (line 357),
  writes to a .tmp file first, and the lock is held across the entire read-modify-write
  at line 398
Red flag: NONE
Invariants: I2 PASS — _OBS_LOCK held from line 398 across _load_obs_nolock() at line 399
  and _save_obs_nolock() at line 416; no gap in the RMW cycle.
  I3 PASS — _save_obs_nolock() uses os.replace(); writes temp first.
STRENGTHS:
• Full RMW cycle is inside a single `with _OBS_LOCK:` block — no TOCTOU window
• Deduplication logic (lines 401-405) prevents duplicate station+date entries,
  which is correct for idempotent replay of settlement callbacks
• proxy flag is persisted in the record and get_station_bias() explicitly excludes
  proxy records (line 447) — the separation is correct
• Atomic write via _save_obs_nolock() means a crash between write and rename leaves
  a .tmp file rather than a corrupt primary file
• Comment at line 396-397 explains WHY the lock is needed (R17 concurrent settlement)
WEAKNESSES:
• line 359: _save_obs_nolock() logs at DEBUG on exception, not WARNING. If the write
  fails (disk full, permissions), the caller (record_observation) gets no return value
  and no indication the write failed. The observation is silently dropped. Over time
  this could cause the bias model to never accumulate the 200 observations needed
  to activate.
• record_observation() itself has no return value and no test coverage. The function
  is tested indirectly only if another test calls it, but no test in test_metar.py
  covers record_observation(). This is a gap given AC3 requires atomic write.
  (The atomic write is structurally sound, but the lack of a test means a future
  refactor that breaks atomicity would not be caught.)
• line 392: If city is valid but MARKET_STATION_MAP returns None (unexpected city),
  the function silently returns. Correct behavior, but no log at any level — a typo
  in a city name would be invisible.
FAILURE SCENARIO:
  Disk full during _save_obs_nolock(): os.replace() raises OSError. The except at
  line 358-359 swallows it at DEBUG. record_observation() returns normally. The caller
  (settlement path in paper.py or weather_markets.py) sees no error. Observations
  accumulate only in memory until process restart, then are lost permanently.
VERDICT: keep as-is — raise _save_obs_nolock exception log to WARNING
```

---

### `get_station_bias()` L:434–459  ★ T1

```
[metar.py] get_station_bias() L:434–459  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: AC4 PASS — line 449 returns None (not 0.0) when observations < _MIN_OBS_FOR_MODEL;
  line 454 returns None (not 0.0) when month has fewer than 20 records
Red flag: NONE
Invariants: None of I1–I10 directly applicable.
STRENGTHS:
• AC4 is satisfied at both early-exit points — None is returned, not 0.0
• proxy records are excluded from the bias model (line 447) — correct: proxy records
  are threshold-estimated values, not true observations
• _MIN_OBS_FOR_MODEL = 200 threshold prevents premature model activation with noisy
  small-sample bias estimates
• Month-level minimum of 20 rows prevents activating on a single anomalous month
WEAKNESSES:
• line 456-459: The function raises NotImplementedError unconditionally once the
  observation threshold is met. This means the function is currently a stub that will
  crash production code the first time it is called with ≥200 observations. The
  docstring says "activates automatically" but the implementation throws instead.
  This is not dead code — it is broken production code that will fire as observations
  accumulate.
• The NotImplementedError is raised without a log — a caller that does not catch it
  will propagate an unhandled exception up through the same-day trade path.
• No test coverage for the NotImplementedError path or the proxy-exclusion logic.
FAILURE SCENARIO:
  At ~200+ METAR observations (currently far below threshold so dormant), any caller
  that passes a valid city and month will receive a NotImplementedError instead of
  None or a bias value. If the caller does not catch this, the same-day trade path
  crashes entirely, blocking all same-day lock-in trades until the process restarts.
VERDICT: fix before live — wrap the NotImplementedError in a try/except that logs at
  WARNING and returns None, or add a guard: `if _MIN_OBS_FOR_MODEL == 200: return None`
  with a TODO comment, so the crash cannot happen in production before the model is
  implemented.
```

---

## TIER 2 Functions

---

```
[metar.py] _load_obs() L:322–330  6/10 — Acquires _OBS_LOCK internally, reads file,
  but catches broad Exception at DEBUG; a corrupted JSON file would be silently
  ignored and return [] with no WARNING to the operator.  [Confidence: Confirmed]
FIX: metar.py:329 — change `_log.debug(` to `_log.warning(` for the JSON load failure
```

```
[metar.py] _load_obs_nolock() L:333–341  7/10 — Correct; caller must hold lock
  (documented); same DEBUG-vs-WARNING gap as _load_obs() but this is the inner
  function called under lock, so a single WARNING from the outer caller would
  suffice.  [Confidence: Confirmed]
```

```
[metar.py] _save_obs_nolock() L:344–359  7/10 — Uses os.replace() (I3 PASS);
  writes to .tmp first; lock must be held by caller (documented). Gap: exception
  logged at DEBUG, not WARNING — a disk-full error is invisible in production logs.
  [Confidence: Confirmed]
FIX: metar.py:359 — change `_log.debug(` to `_log.warning(` for save failure
```

```
[metar.py] _save_obs() L:362–374  6/10 — Public-facing save that acquires _OBS_LOCK
  internally. Structural issue: the lock is acquired AFTER tmp.write_text() begins
  (line 368 acquires lock, but line 369 does the write inside the lock — actually
  correct on inspection). Wait — re-reading: line 369-372 show `with _OBS_LOCK:` then
  `tmp.write_text(...)` then `os.replace()` — both the write and the rename are inside
  the lock. This is correct for I3. However _save_obs() is not called anywhere in the
  file (record_observation uses _save_obs_nolock() under its own lock); _save_obs() is
  effectively unused dead code. Also logs at DEBUG on failure. [Confidence: Confirmed]
FIX: metar.py:374 — change `_log.debug(` to `_log.warning(`; consider removing
  _save_obs() if it is not called outside this file
```

```
[metar.py] _safe_extreme() L:170–178 (nested inside fetch_metar)  8/10 — Clean
  one-purpose helper; applies plausibility bounds to optional min/max fields;
  returns None on type/value error; no logging needed for optional fields.
  [Confidence: Confirmed]
```

```
[metar.py] get_obs_count() L:426–431  7/10 — Simple counter; calls _load_obs()
  which acquires _OBS_LOCK internally; no locking gap; correct station filter;
  returns 0 for unknown city. No test coverage but low-stakes utility.
  [Confidence: Confirmed]
```

---

## File-level Observations

**Overall quality:** metar.py is well-structured and safety-conscious. The staleness
gate in fetch_metar() is thorough, the lock discipline in record_observation() is
correct, and the AC2 timezone conversion is properly implemented. The L6-D dynamic
confidence fix is a genuine improvement over the hardcoded 0.90.

**Systemic gap — DEBUG vs WARNING on I/O failures:** Four functions (_load_obs,
_load_obs_nolock, _save_obs_nolock, _save_obs) all log exceptions at DEBUG rather
than WARNING. This means disk errors, permission issues, or JSON corruption in
metar_observations.json would be completely invisible in production logs. A single
pass to change these four to WARNING would fix the observability gap.

**Dormant stub — get_station_bias():** The function will raise NotImplementedError
once the 200-observation threshold is reached. Currently safe (far below threshold),
but should be protected before the observation count climbs.

**No test coverage for record_observation():** The most safety-critical function in
the observation pipeline (write path with lock discipline) has no direct test in
test_metar.py. The atomic write path is correct by inspection, but a refactor could
break it silently.
