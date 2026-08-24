# Batch 36: Weather-data fetch layer

## Context

Repo: weather1. Written 2026-08-23 against master `f4291771` — re-verify before starting. Source: `audit/POST_MERGE_REVIEW.md` (M-18 umbrella + B-data LOWs). Files owned: `nws.py`, `metar.py`, `mos.py`, `climatology.py`, `climate_indices.py`, `acis_precip.py`, `acis_snow.py`, `hurricane_climatology.py`, `forecast_cache.py`, `schema_validator.py`. Parallel-safe with 33-35/37-39.

## Items

### 1. M-18a [MEDIUM]: `validate_nws_response` is too shallow to deliver batch-13's fail-closed intent

**Files:** `nws.py:242-246`, `schema_validator.py:173-196`. Batch `53fb26e7`.
The AUD-0060 wiring is correct, but the validator only checks `properties` is a dict — `{"properties": {}}` passes, credits `_nws_cb.record_success()`, and `nws.py:275` caches `{}` for the full 3600s TTL (`:217-219` returns it — `{}` is not None). A city silently loses its NWS forecast for an hour with the breaker showing healthy. Fix: validate `periods` exists/non-empty in `validate_nws_response`, and treat a validated-but-empty result as a failure (no cache write, `record_failure`).

### 2. M-18b [MEDIUM]: `metar.py`'s two naive-datetime parsing gaps

**Files:** `metar.py:149-175` and `:296-307,:366`.
(a) The `reportTime` staleness fallback parses `"2026-08-23 14:53:00"` (no Z — the real payload shape) into a NAIVE datetime, then `datetime.now(UTC) - obs_time` raises TypeError (repro'd in the venv) — the fallback exists precisely for when `obsTime` is missing, and it crashes instead of degrading. Worse, the crash lands between the two negative-cache writes (`:166`, `:175`), so every market re-issues the ~21s HTTP call each scan. Zero test coverage for `reportTime`.
(b) `_extract_obs_time` has the same gap and fails silently wrong: a naive result hits `.astimezone(tz)` which interprets it as SYSTEM-LOCAL, misdating the observation's city-local date — feeding `fetch_metar_daily_extreme` → `_metar_lock_in`'s YES-lock and `_compute_persistence_prob`. Latent (live `obsTime` is an epoch int) but on the wrong-trade path.
One shared fix: after `fromisoformat`, if `tzinfo is None`, `replace(tzinfo=UTC)` (the API's documented basis) — plus tests for both payload shapes. Also (c) L-2: two `fetch_metar` failure paths (`:122`, `:134`) skip the negative cache — add the `_METAR_CACHE.set(key, None)` both siblings have; and (d) L-3: `check_metar_lockout`'s `local_time = obs_time` UTC fallback (`:453`) would pass the pre-14:00 gate at ~09:00 local — fail closed like the sibling at `:354-356` (mitigated by pinned tzdata; make the policy consistent anyway).

### 3. M-18c [MEDIUM]: `fetch_mos` filters UTC `ftime` rows by the city-local target date

**Files:** `mos.py:191` (vs the same module parsing `ftime` as UTC at `:333`).
The tz threading fixed the sigma lookup but not the row filter that decides which hours the daily max/min is computed over — 7h misaligned in both directions for KLAX. Known residual recorded inside another entry's resolution note (`backlog.txt:12359-12363`) but NEVER filed as its own entry and absent from BACKLOG_OPEN. Fix the filter to convert `ftime` to the city tz before comparing dates; file the backlog entry either way.

### 4. M-18d [MEDIUM]: `apply_pdo_pna_correction` drops the caller's target month

**Files:** `climate_indices.py:627`; sole production caller `weather_markets.py:12424` (do NOT edit that file — batch 35 owns it; the fix is entirely in this module's signature default behavior... if the call site must change, coordinate/sequence with batch 35).
Mixes the target month's seasonal coefficient with the current-UTC-month's index lookback — the same defect class the module already fixed once for `get_indices` (documented at `:135-142`); `temperature_adjustment:442` does it right. `forecast_temp_f` is also a dead parameter. Preferred fix that avoids touching weather_markets.py: have `apply_pdo_pna_correction` pass its existing `month` argument through to `get_pdo_pna(month=...)` (and current year), which already accepts it. Also L-6: the H-17 zero-result cache guard (`:185`) only fires when ALL three indices are 0.0 — a partial outage caches a partial result for 24h; guard per-index or don't cache partials.

### 5. M-18e [MEDIUM]: unguarded `json.load` on the per-city climate cache

**Files:** `climatology.py:89-90`, `:133-134`.
A corrupt/truncated `data/climate_{city}.json` raises out of `load_all_sigmas` while holding `_sigma_lock`, and `weather_markets._load_dynamic_sigma`'s bare except logs at DEBUG → every city silently reverts to static seasonal sigma. The `:133` copy sits inside an except handler and masks the original network error. Mirror `_load_sigma_cache_file`'s (`:315-334`) careful guarding. Also: L-5 — the empty-compute guard at `:479-485` only catches TOTAL failure (`max` populated + `min` empty clobbers a good min table; guard per-var); L-11/L-12 leap-year `tm_yday` window edge and zip-truncation assumption — comment-level fixes at most.

### 6. L-1 [LOW]: ACIS mem-cache pins the stale fallback for the process lifetime

**Files:** `acis_precip.py:190-191,288,364-365`; `acis_snow.py:201-202,303,361-362` (cloned — fix both).
`_MEM_CACHE` is checked before the disk-staleness gate AND populated by `_load_stale_cache_or_none` — one transient ACIS failure at first call serves stale history forever (and freezes `end_year` across New Year). Don't mem-cache the stale-fallback result (or tag it and retry when the breaker recovers). Also the unit guards fail OPEN when `monthly_units` is absent — `is None or !=` makes them fail closed (one word, prevents the exact 10x mis-tilt they were added for).

### 7. L-8 [LOW]: `hurricane_climatology.py` dated HURDAT2 URLs rotate yearly and degrade silently

**Files:** `hurricane_climatology.py:42-45`, `:163`, `:343`.
On NOAA's Jan/Feb filename rotation the fetch 404s, the stale cache serves with no age signal (`_warn_if_stale`'s `current_year - 2` threshold can't see one-season staleness), and the dead URL is re-attempted every call. Fix: warn at `current_year - 1`, back off the dead URL, and add a comment with the rotation pattern (or try the next-year filename automatically).

### 8. L-10/L-3 [LOW]: encoding + docstring consistency
`forecast_cache.py:223` `read_text()` without `encoding="utf-8"` (safe_io writes utf-8) — same at `climatology.py:89/133` and the acis `open(cache)` calls; add the parameter everywhere in this batch's files. `forecast_cache.py:18`'s "LRU eviction" docstring describes FIFO (`_evict_oldest` uses insertion time) — fix the docstring (or implement touch-on-get if trivially safe).

### 9. L-1(nws) [LOW]: `_get_obs` abandons timed-out futures

**Files:** `nws.py:82,149`. Abandoned tasks keep occupying the 4-worker pool; sustained Windows SSL hangs (the pool's own raison d'être per `:79-80`) can permanently consume all 4 workers → every observation call times out while queued, breaker records failures with no distinct signal. Fails closed, so LOW: at minimum log pool saturation distinctly; consider a per-call executor or cancellation.

## Process

Full 29-step workflow (this layer feeds live trade-entry pricing; opus review effort=high). Re-verify claims live. Scoped tests only: `tests/test_metar.py`, `tests/test_forecasting.py`, `tests/test_climatology*.py`, `tests/test_acis*.py`, `tests/test_hurricane*.py`, plus files you touch — **never the full suite**. Lint via the real pre-commit interpreter. Backlog entries (including filing M-18c's missing entry) + `backlog_index.py`. Confirm before commit. Full workflow: `memory/feedback_implementation_workflow.md`.
