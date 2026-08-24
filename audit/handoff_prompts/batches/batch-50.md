# Batch 50: WeatherNext 2 track-only + HRRR dedicated-model pin (Track B — model sources)

## Context

Repo: weather1. Source: Expansion Dossier B5 (score 7.5, rank 4) + B4 (7.6, rank 3), Rev 4, 2026-08-24. Assumes batches 31-48 landed — specifically batch 35 (weather_markets internal correctness) and batch 36 (weather-data fetch layer); this batch edits the same file regions batch 36 touched, so verify it landed and rebase onto it.

Files: `weather_markets.py` **model-fetch layer only** (`ENSEMBLE_MODELS*`, `KNOWN_FORECAST_MODEL_NAMES`, `TRACKING_ONLY_MODEL_NAMES`, `_fetch_hrrr_temp`, `_fetch_model_ensemble`, caches/CBs), `tracker.py` (per-model scoring only if a change is even needed — the registries are designed so it isn't). Parallel-safe with batch 49; parallel-OK with 51/52 per the INDEX-ROADMAP weather_markets.py note (distant regions, rebase-checked).

Ceremony: LOW-tier downgrade allowed (self-review + 1 review agent) — both items are track-only/dormant-path; NEITHER touches the live blend weights. If during implementation either item turns out to require touching a live blend computation, STOP and escalate to full ceremony.

## Item 1 — Google WeatherNext 2 as a tracking-only ensemble source (dossier B5)

Verified live 2026-08-23/24: `https://ensemble-api.open-meteo.com/v1/ensemble?...&models=google_weathernext2_ensemble` returns **64 members** of hourly-interpolated 2m temperature; free; same endpoint/JSON shape as the existing sources. Docs (open-meteo.com/en/docs/google-weathernext-api): 0.25°, updates every 12h, 15-day horizon, native 6-hourly steps interpolated to hourly.

Build: register `google_weathernext2_ensemble` following the exact GEM/UKMO onboarding pattern — add to `KNOWN_FORECAST_MODEL_NAMES` AND `TRACKING_ONLY_MODEL_NAMES` (the registries' own comments describe this as "a deliberate one-line update"). Track-only means: accuracy tracked per-model in `ensemble_member_scores`, EXCLUDED from every live blend-weight computation — the audit already verified the three exclusion sites share `TRACKING_ONLY_MODEL_NAMES` as single source of truth; do not add a fourth mechanism. One ensemble fetch per city-cycle against the shared Open-Meteo rate budget — reuse `_om_rate_limit`/session/disk-cache plumbing.

**Go/no-go validation (run first, <1 day):** fetch WN2 for all 20 cities once; per member compute implied daily TMAX/TMIN; quantify (a) fetch latency + failure rate, (b) 6-hourly-native TMAX clipping vs same-day ICON hourly members (median clip bias). Gate: median clipping bias < 1.0°F and fetch < 10s/city. Fail → file to backlog with the numbers, do not onboard.

Known caveats to encode in the tracking metadata/comments: 12-hourly update cadence (stale vs hourly HRRR at short leads); 6-hourly native resolution (interpolation cannot recover a mid-afternoon spike); free tier is non-commercial (flag, as the bot's other Open-Meteo usage already is).

## Item 2 — Activate the dormant HRRR fetch pinned to `ncep_hrrr_conus` (dossier B4)

`_fetch_hrrr_temp` exists but is dormant and calls `models=best_match` (an opaque auto-selection — may silently serve GFS-blend values). Verified live 2026-08-23/24: `models=ncep_hrrr_conus` on `api.open-meteo.com/v1/forecast` returns hourly 2m temperature for CONUS points. open-meteo/open-data README (exact quote): "If you only need 2 days of forecast for North America, use `ncep_hrrr_conus`, but for more than 2 days, you have to add `ncep_gfs013`."

Build: pin the model param; keep the same-day-only scope the function's docstring already declares (2-day horizon cap is a hard model property — never serve it beyond day-1). The existing code comment says activation "happens once HRRR data has been validated against settled same-day trades" — this batch's activation is as a **logged/tracked signal only** (log alongside the other same-day inputs so its accuracy accrues in tracker), NOT as a new blend member. Graduating it into any live probability is a separate future decision with its own gate.

**Go/no-go validation (run first, <1 day):** for all 20 cities at ~15Z, fetch both `ncep_hrrr_conus` and `best_match` daily max/min; at end of day compare both to the METAR-settled extreme. Gate: pinned MAE ≤ best_match MAE, and the two series differ on ≥3 cities (proving the pin matters). If they're bit-identical everywhere, the pin is still correct (attribution) but note it.

## Constraints

- No new dependencies; plain HTTPS via existing session helpers; Windows/py3.12 unaffected.
- Respect the circuit-breaker conventions (each source gets its own CB, following `_nbm_om_cb`/`weatherapi` patterns — batch 35/audit M-15 context: fail toward last-known-good, never fail-open into the blend).
- Scoped tests: `tests/test_weather_markets.py` (model-registry/validation tests), `tests/test_nbm.py`-style new file(s) for the fetchers, plus grep tests/ for `_fetch_hrrr_temp`/`KNOWN_FORECAST_MODEL_NAMES` transitive users. **Never the full suite.**
- backlog.txt: file the "WN2/HRRR graduation decision" follow-ups as entries with their gate criteria; run `python backlog_index.py`.
