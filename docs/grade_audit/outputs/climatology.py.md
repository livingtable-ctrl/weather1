# Grade Audit — climatology.py
Graded: 2026-06-29 | Tier: TIER 2 file | Auditor: claude-sonnet-4-6

---

## File Overview

`climatology.py` provides the historical-climatology baseline probability used as one
blend component in the multi-day forecast ensemble. It fetches 30 years of daily
high/low data from the Open-Meteo archive API, caches to disk, and exposes
`climatological_prob()` and `persistence_prob()` to callers. It is NOT in the live
trade execution path itself — it feeds into `weather_markets.py` blend weights but does
not touch order placement, sizing, or settlement. All functions are TIER 2 unless a
red flag promotes them.

---

## Function Grades

---

### RF1 PROMOTION — `fetch_historical()` L:52–108  ★ T1 (promoted from T2)

```
[climatology.py] fetch_historical() L:52–108  ★ T1 (RF1 promotion)
Score: 5/10  |  Confidence: Confirmed
AC: N/A
Red flag: RF1 — `except Exception:` at L:94 catches all exceptions and uses
  `print(...)` instead of `_log.warning(...)`. The exception itself is never logged
  at WARNING or above — the `print` only fires if a stale cache exists AND
  cache_age_days > 365. If the download fails and no stale cache exists, the function
  returns None silently with zero operator visibility. If the download fails and a
  fresh-ish stale cache exists (< 1yr), the function returns stale data with zero
  operator visibility.
Invariants: I3 FAIL — L:90 uses plain `open(cache, "w")` + `json.dump()`. If the
  process crashes mid-write the cache file is partially written and will fail to load
  on the next call. Not atomic (no temp-file + os.replace() pattern). Low severity
  for a cache file, but worth noting.
STRENGTHS:
• In-memory cache (_MEM_CACHE) prevents redundant API calls within one process run.
• Correctly falls back to stale disk cache when API is unavailable.
• Prints stale-cache warning when cache is > 365 days old.
• Requests session reuse for connection pooling (#125).
WEAKNESSES:
• line 94: `except Exception:` with no `_log.warning()` (or higher) call. A network
  timeout, DNS failure, JSON parse error, or HTTP 4xx/5xx will swallow the exception
  entirely when a non-stale cache is present. The operator cannot distinguish "API
  down, using 9-month-old cache" from normal operation without inspecting the cache
  file modification time manually.
• line 99–103: The stale-cache print only triggers when cache is > 365 days old and
  the API failed. A 300-day-old cache used silently is a calibration risk — the
  climatology baseline is quietly wrong.
• line 90: Non-atomic write. A crash between `open(cache, "w")` and `f.write()` leaves
  a truncated JSON file. Next call will hit `json.load()` → `JSONDecodeError` (not
  caught), which propagates to `_climatological_prob_inner` → caught by circuit
  breaker. Net effect: city's climatology component disabled silently until cache is
  manually deleted.
FAILURE SCENARIO:
  Open-Meteo API is unreachable (network outage, rate limit). City has a valid cache
  file that is 300 days old. fetch_historical() enters the except block, finds
  cache.exists() == True, cache_age_days ≈ 300 < 365, so no print fires, no log fires.
  Function returns 300-day-old data with zero operator visibility. The climatology
  blend component silently runs on last year's data for every trade during the outage.
FIX:
  climatology.py:94 — replace bare `except Exception:` with:
    except Exception as exc:
        _log.warning("fetch_historical: API failed for %s: %s", city, exc)
  Then at the no-cache branch (L:108), add:
        _log.warning("fetch_historical: API failed for %s and no cache exists — returning None", city)
  For I3: replace L:90–91 with atomic write pattern using temp file + os.replace().
VERDICT: fix before live
```

---

### TIER 2 Functions

```
[climatology.py] _cache_path() L:36–37  9/10 — Trivial path builder, no failure path possible.  [Confidence: Confirmed]
```

```
[climatology.py] _cache_is_stale() L:40–44  9/10 — Correct mtime check; handles missing file; clean boolean return.  [Confidence: Confirmed]
```

```
[climatology.py] climatological_prob() L:111–134  8/10 — Good circuit-breaker wrapper; logs WARNING on exception; clean None return. One minor gap: success is recorded on `_clim_cb` even when `_climatological_prob_inner` returns None (data unavailable), which inflates the circuit breaker's health signal. Not a safety issue today.  [Confidence: Confirmed]
```

```
[climatology.py] _climatological_prob_inner() L:137–188  7/10 — Handles mismatched list lengths with WARNING, guards None values, guards year-boundary DOY wrap, enforces 30-point minimum. Gap: condition dict accessed by key (condition["type"], condition["threshold"], condition["lower"], condition["upper"]) without .get() + default — a malformed condition dict raises KeyError, which propagates up and is caught by the circuit breaker wrapper without identifying which key was missing.  [Confidence: Confirmed]
```

```
[climatology.py] persistence_prob() L:191–225  6/10 — Guards std_dev <= 0 and threshold_hi is None. Gap: does not guard current_value or threshold_lo for None — if upstream METAR returns None for current_value, _normal_cdf receives None and raises TypeError, which is uncaught in this function. The function has no try/except; callers in weather_markets.py would need to handle it. No circuit breaker here.  [Confidence: Likely]
FIX: climatology.py:210 — add guard before the std_dev check:
    if current_value is None or threshold_lo is None:
        return None
```

```
[climatology.py] preload_all() L:228–237  7/10 — Clean admin/startup utility; delegates to fetch_historical() which handles errors. Minor gap: iterates silently over failed cities (fetch_historical returns None on failure, preload_all does not log which cities failed).  [Confidence: Confirmed]
```

---

## Summary

| Function | Score | Tier | Flag |
|---|---|---|---|
| `_cache_path` | 9/10 | T2 | — |
| `_cache_is_stale` | 9/10 | T2 | — |
| `fetch_historical` | 5/10 | T1 (promoted) | RF1, I3 |
| `climatological_prob` | 8/10 | T2 | — |
| `_climatological_prob_inner` | 7/10 | T2 | — |
| `persistence_prob` | 6/10 | T2 | — |
| `preload_all` | 7/10 | T2 | — |

**File median: 7/10.** One RF1 promotion. Two fixes required: `fetch_historical` (RF1
exception logging + I3 atomic write) and `persistence_prob` (None guard on inputs).
The file does not touch order placement, sizing, or settlement — its bugs affect
calibration accuracy over time, not immediate trade safety.
