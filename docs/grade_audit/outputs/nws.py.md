# Grade Audit — nws.py
Generated: 2026-06-29

---

## TIER 1 Functions

---

### [nws.py] nws_prob() L:260–310  ★ T1
```
Score: 7/10  |  Confidence: Confirmed
AC: ALL PASS
  AC1 PASS — sigma ladder matches exactly: days_out<=0→1.0, days_out==1+between→1.0,
              days_out<=2→2.0, days_out<=5→3.0, else→4.0
  AC2 N/A (obs_prob is a separate function)
  AC3 N/A (weight scaling is handled by _nws_days_out_scale, not nws_prob)
Red flag: NONE
Invariants: None directly applicable (no Kelly, no balance, no DB, no lock, no atomic write)

STRENGTHS:
• AC1-compliant sigma ladder is exactly correct and well-commented — the asymmetry for
  days_out=1+between is explicitly explained in the inline comment (lines 286–289).
• E4 implausible-temperature guard (lines 279–282) prevents a bad NWS feed value from
  entering the CDF.
• Circuit-breaker check at line 267 prevents silently returning stale/None data when
  NWS is unhealthy.
• All three condition types (above/below/between) are handled with correct normal_cdf
  arithmetic (lines 302–309).
• Returns None (not 0.5) when forecast data is missing — callers can distinguish "no
  data" from a meaningful probability.

WEAKNESSES:
• line 224 (inside get_live_observation, different fn) — not applicable here.
• line 290: `days_out = (target_date - _utc_today()).days` — no guard for the case
  where `target_date` is None. If a caller passes None (e.g. from a malformed
  enriched dict), this raises `TypeError: unsupported operand type(s) for -:
  'NoneType' and 'datetime.date'`. The caller (weather_markets.py) should guard
  this, but nws_prob itself has no defensive check.
• No test directly exercises nws_prob() itself. Tests in test_gaussian_prob.py cover
  gaussian_probability and get_historical_sigma in weather_markets; tests in
  test_obs_weight.py test DB column presence. No test file calls nws.nws_prob with
  a real or mocked NWS response. This triggers the TIER 1 coverage rule: cannot
  score >8 without meaningful test coverage.
• The broad Exception catch inside get_nws_daily_forecast (called at line 270) logs
  at WARNING — this is fine. But nws_prob itself has no try/except around the
  get_nws_daily_forecast call. If get_nws_daily_forecast raises (it can if
  validate_nws_response raises after a partial parse), nws_prob propagates the
  exception to the caller uncaught.

FAILURE SCENARIO:
  1. NWS returns a malformed HTTP 200 response that passes raise_for_status() but
     causes validate_nws_response() to raise. get_nws_daily_forecast() does NOT
     catch validate_nws_response exceptions (it only catches the Exception around
     _get() and _get_gridpoint()). The unguarded call at line 270 propagates upward
     through nws_prob() into weather_markets.analyze_trade(), which may not be
     expecting an exception at this call site.
  2. target_date=None passed by a caller → TypeError on line 290 propagates uncaught.

VERDICT: fix before live (low-severity — path 1 is unlikely but silent; add try/except
around line 270 call and return None on exception)
```

---

### [nws.py] obs_prob() L:482–506  ★ T1
```
Score: 8/10  |  Confidence: Confirmed
AC: ALL PASS
  AC2 PASS — sigma=3.5 hardcoded at line 491, with a clear inline comment explaining
              why 1.0 was wrong (lines 483–487).
  AC1 N/A (this is obs_prob, not nws_prob sigma ladder)
  AC3 N/A
Red flag: NONE
Invariants: None directly applicable

STRENGTHS:
• sigma=3.5 is correct and explained — avoids the near-binary 2%/98% failure mode
  that crushed Brier scores (comment at lines 483–487, 499–504).
• All three condition types handled: above, below, between — the between branch uses
  sigma=3.5 consistently (line 505) matching the explicit design note about the
  prior sigma=0.25 regression.
• No I/O or DB access — pure function, cannot fail due to network or disk issues.
• Returns 0.0 as a safe fallback for unknown condition types (line 506), not an
  exception.

WEAKNESSES:
• line 489: `temp = obs["temp_f"]` — KeyError if obs dict is missing "temp_f". The
  callers (weather_markets.analyze_trade) create the obs dict via get_live_observation
  which always sets "temp_f", but there is no defensive check here. If a future
  caller passes a partial dict (e.g. from a deserialized cache), this raises silently.
• No test directly exercises obs_prob(). test_obs_weight.py only checks DB column
  presence; test_gaussian_prob.py only tests gaussian_probability and
  get_historical_sigma in weather_markets. The coverage gap prevents a score above 8
  per the preamble rule.
• The between branch ignores condition["lower"] and condition["upper"] consistency —
  no guard if lower >= upper (would produce a negative probability). Normal CDF
  subtraction can return a small negative if floating-point edge; not clamped to [0,1].

VERDICT: keep as-is (minor robustness gaps, no active bug on current call paths)
```

---

### [nws.py] _nws_days_out_scale() — NOT FOUND IN FILE
The module spec lists "_nws_days_out_scale() or equivalent weight scaling function" as
a TIER 1 function. After reading all 508 lines of nws.py, no function named
`_nws_days_out_scale` or equivalent exists in this file. The sigma ladder and
days_out-based sigma selection are embedded directly inside `nws_prob()` (lines
290–300). There is no separate weight-scaling function in nws.py itself.

The NWS weight at days_out=0 (AC3: must return 0 or zero-weight NWS) is controlled
in weather_markets.py where blend weights are assembled, not in nws.py. This is an
architectural choice — nws.py computes probabilities; weight zeroing for days_out=0
is the caller's responsibility. This is not a defect in nws.py but it does mean
AC3 cannot be verified within this file.

---

## TIER 2 Functions

---

```
[nws.py] _load_station_cache() L:67–77  8/10 — Loads persisted JSON station cache
into _station_cache; catches all exceptions and logs at DEBUG.  [Confidence: C]
```
Note: DEBUG log on failure means an operator won't see if the cache file is corrupt.
Low severity — the function degrades gracefully by simply not using the cache. Not
worth a fix, but promoting the except to WARNING would improve observability.

---

```
[nws.py] _save_station_cache() L:80–87  8/10 — Persists station cache to disk
best-effort; swallows all exceptions at DEBUG. Write is NOT atomic (direct write_text,
not temp+rename), but station IDs are stable/immutable so a torn write is harmless
in practice.  [Confidence: C]
```

---

```
[nws.py] _get_obs_lock() L:90–95  9/10 — Thread-safe per-city lock factory using
a module-level mutex; idempotent; no failure paths.  [Confidence: C]
```

---

```
[nws.py] _get() L:105–115  8/10 — HTTP GET helper with (5,8) timeout tuple, slow-
response WARNING at >5s, raise_for_status. No try/except (callers catch). Clean.
[Confidence: C]
```

---

```
[nws.py] _get_obs() L:118–129  8/10 — Wall-clock deadline via ThreadPoolExecutor
future to guard against Windows SSL hangs; re-raises as TimeoutError with WARNING log.
No silent failure.  [Confidence: C]
```

---

```
[nws.py] _get_gridpoint() L:132–140  7/10 — Fetches NWS gridpoint with in-memory
cache; no try/except (callers catch). Missing guard: if NWS /points response is
malformed and "properties" is absent, raises KeyError propagating to callers.
[Confidence: C]
```
FIX: nws.py:137-138 — wrap `props = data["properties"]` in a try/except KeyError,
return None or raise a descriptive ValueError.

---

```
[nws.py] _get_obs_station() L:143–163  7/10 — Fetches nearest observation station
via NWS /points then /observationStations; per-call cache with disk persistence.
Broad Exception caught at line 162 with no log — operator cannot see why station
lookup failed.  [Confidence: C]
RF1 — bare `except Exception: return None` at line 162–163 with no log at WARNING
or above.
```
PROMOTED to note RF1. Score capped at ≤4 per red flag rules.

[nws.py] _get_obs_station() L:143–163  ★ RF1 OVERRIDE
```
Score: 4/10  |  Confidence: Confirmed
AC: N/A
Red flag: RF1 — line 162: `except Exception: return None` — no log at WARNING or above.
  If NWS /points or /observationStations fails, the failure is completely silent.
  Operators cannot diagnose why a city's observation is always None without adding
  debug logging.
Invariants: N/A

STRENGTHS:
• Cache hit path is fast and avoids redundant API calls.
• Disk persistence prevents repeated /points round-trips on process restart.

WEAKNESSES:
• line 162–163: bare `except Exception: return None` with zero logging. If the NWS
  API changes its response shape, or a network issue occurs, the station lookup
  silently returns None. Every downstream caller (get_live_observation,
  get_live_precip_obs) then also returns None. The trade path sees "no observation
  available" rather than a diagnosable error.

FAILURE SCENARIO:
  NWS API changes the "properties.observationStations" key name (has happened in past).
  _get_obs_station returns None silently for all cities. get_live_observation returns
  None for all cities. Same-day METAR lock-in and obs blend fail silently — trades
  are placed with no obs component without any operator alert.

FIX:
  nws.py:162 — replace `except Exception: return None` with:
    except Exception as exc:
        _log.warning("NWS station lookup failed for (%.4f, %.4f): %s", lat, lon, exc)
        return None

VERDICT: fix before live
```

---

```
[nws.py] get_nws_daily_forecast() L:169–228  7/10 — Fetches NWS daily forecast with
in-memory cache, circuit-breaker guard, schema validation before recording success,
temperature unit check, and malformed-period skip. One gap: inner `except Exception:
continue` at line 224 silently skips periods with no log — if all periods are
malformed, result is empty dict and caller gets no forecast without knowing why.
[Confidence: C]
```

---

```
[nws.py] fetch_nbm_forecast() L:231–257  8/10 — Thin wrapper over
get_nws_daily_forecast that extracts a specific date; returns None cleanly when date
not found or daily is empty. No failure paths.  [Confidence: C]
```

---

```
[nws.py] nws_prob_from_quantiles() L:313–365  7/10 — Computes probability from NBM
native quantiles via linear ECDF interpolation with tail extrapolation. Returns 0.5
for 'between' (documented in docstring). The tail extrapolation clamps at 0.0 via
max(0.0, ...) but does NOT clamp the upper end — can return values >1.0 for extreme
inputs (e.g. t >> temps_sorted[-1]).  [Confidence: C]
```
FIX: nws.py:347 — add `return min(1.0, ...)` wrapper around the upper-tail
extrapolation result to prevent >1.0 returns.

---

```
[nws.py] get_live_observation() L:371–427  7/10 — Thread-safe with per-city lock and
double-check-locking pattern; circuit-breaker guard; E4 implausible-temp check;
WARNING log on failure. One gap: _get_obs_station is called at line 400 without
try/except — if it raises (it shouldn't per its implementation, but if _get raises
inside it), the outer try/except at line 424 catches it correctly. Clean fallback.
[Confidence: C]
```

---

```
[nws.py] get_live_precip_obs() L:430–479  7/10 — Same pattern as get_live_observation:
per-city lock, double-check cache, circuit-breaker, WARNING on failure. Precipitation
unit conversion mm→inches via /25.4 is correct. One nit: p6h averaging (line 470)
assumes the 6-hour total is evenly distributed — this is standard practice but not
documented.  [Confidence: C]
```

---

## Module-Level Items

```
[nws.py] _load_station_cache() at module import L:99 — SIDE EFFECT AT IMPORT TIME.
_load_station_cache() is called at module level (line 99). This is intentional and
benign (reads a JSON file from data/), but it means importing nws.py has a disk
read side effect. This is acceptable given the file is tiny and read-only, and the
function handles FileNotFoundError gracefully.
```

---

## Summary Table

| Function | Tier | Score | Key Issue |
|---|---|---|---|
| nws_prob() | T1 | 7/10 | No test coverage; unguarded validate_nws_response exception path |
| obs_prob() | T1 | 8/10 | No test coverage; KeyError on missing temp_f; between not clamped |
| _nws_days_out_scale() | T1 | N/A — does not exist in file; sigma logic is inlined in nws_prob |
| _load_station_cache() | T2 | 8/10 | Exception logged at DEBUG, not WARNING |
| _save_station_cache() | T2 | 8/10 | Non-atomic write (harmless for stable data) |
| _get_obs_lock() | T2 | 9/10 | Clean |
| _get() | T2 | 8/10 | Clean |
| _get_obs() | T2 | 8/10 | Clean |
| _get_gridpoint() | T2 | 7/10 | KeyError on malformed /points response |
| _get_obs_station() | T2→T1 | 4/10 | RF1: silent exception swallow |
| get_nws_daily_forecast() | T2 | 7/10 | Inner period parse errors silent |
| fetch_nbm_forecast() | T2 | 8/10 | Clean |
| nws_prob_from_quantiles() | T2 | 7/10 | Upper-tail extrapolation can exceed 1.0 |
| get_live_observation() | T2 | 7/10 | Clean with minor nits |
| get_live_precip_obs() | T2 | 7/10 | Clean with minor nits |

---

## AC Compliance Summary

| AC | Result |
|---|---|
| AC1 — sigma ladder exact | PASS — nws_prob() lines 291–300 match exactly |
| AC2 — obs_prob sigma=3.5 | PASS — obs_prob() line 491 hardcodes 3.5 |
| AC3 — NWS weight=0 at days_out=0 | NOT VERIFIABLE IN nws.py — weight zeroing is the caller's responsibility (weather_markets.py blend assembly), not implemented in this file |

---

## Critical Findings

1. **RF1 on _get_obs_station()** (line 162): Silent exception swallow. Station lookup
   failures are invisible to operators. Fix: add WARNING log before returning None.

2. **Zero test coverage for nws_prob() and obs_prob()** (TIER 1 functions):
   test_obs_weight.py only tests DB schema; test_gaussian_prob.py only tests functions
   in weather_markets. Neither test file imports or calls any function from nws.py
   directly. Both TIER 1 functions are untestable in isolation per current test suite.
   Per preamble rules, this caps both at ≤8 and is the primary reason nws_prob scores 7.

3. **nws_prob_from_quantiles() upper-tail extrapolation** (line 347): Can return a
   value >1.0 for temperatures far above the 90th percentile. If this is passed
   directly to a Kelly formula, I5 (Kelly finite guard) in the caller must catch it.
   Recommend clamping to [0,1] here as a defense-in-depth measure.

---

## Overall Module Assessment

nws.py is well-structured for a production trading bot component. The sigma ladder
(AC1) is correctly implemented and well-commented. The circuit-breaker pattern is
applied consistently. Thread safety via per-city locks with double-check-locking is
solid engineering. The main weakness is the absence of any direct unit tests for the
two TIER 1 functions — all tests that touch NWS behavior do so indirectly through
weather_markets. The RF1 on _get_obs_station is a genuine observability gap that
will make debugging harder when NWS API issues arise in production.
