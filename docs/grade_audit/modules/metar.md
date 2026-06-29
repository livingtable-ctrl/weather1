# MODULE: metar.py

## Before You Start
Read `tests/test_metar.py` before grading.

## TIER 1 Functions
`fetch_metar()`, `check_metar_lockout()`, `record_observation()`,
`get_station_bias()`, `_dynamic_lock_in_confidence()`.

## TIER 2 Functions
`_load_obs()`, `_save_obs()`, `_load_obs_nolock()`, `_save_obs_nolock()`,
`_safe_extreme()`, `get_obs_count()`.

## Acceptance Criteria
A function CANNOT score above 7 if it fails any of these.

- AC1: `fetch_metar()` handles a failed or None METAR response without returning a
  value that could be mistaken for a valid observation. Must return `None` or raise —
  not a default temperature value that would silently produce a wrong probability.
- AC2: `check_metar_lockout()` uses the city's local timezone date, not UTC date, to
  determine whether lockout applies. A UTC mismatch would lock in on the wrong calendar
  day for cities with large UTC offsets.
- AC3: `record_observation()` uses an atomic write path for any persistence — partial
  writes to the observation file must not corrupt the historical record.
- AC4: `get_station_bias()` returns `None` (not `0.0`) when no bias data exists for a
  city/month combination. A default of `0.0` would silently suppress the bias
  correction rather than falling through gracefully.
