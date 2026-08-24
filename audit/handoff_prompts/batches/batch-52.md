# Batch 52: Miami hourly onboarding + Kalshi Weather Index feed (Track C — strictly after batch 51)

## Context

Repo: weather1. Source: Expansion Dossier B6 (score 7.4, rank 6), Rev 4, 2026-08-24. Runs strictly after batch 51 (same registry region; uses 51's drift/settlement-source watcher). Assumes batches 31-48 landed — **verify specifically** that audit L-17's registry-sync gap (`_KXTEMP_HOURLY_CITY` not tied to `KNOWN_WEATHER_SERIES` — adding a 6th hourly series naively bypasses both the shadow gate and the hourly analysis branch) was actually fixed in the 31-48 window; if not, fixing it (with the missing test) is item 0 of this batch, not optional. Also relevant: audit M-12 (contaminated METAR lock-in calibration) — confirm the clean weekly refit landed before touching the lock-in path.

Files: `weather_markets.py` (hourly registry + `_analyze_hourly_trade` + lock-in source abstraction), a NEW module for the Kalshi live-data feed (suggest `kalshi_weather_index.py`), `metar.py` (only if the source abstraction requires an interface change), `kalshi_client.py` (one public GET — coordinate with batch 49 if in flight; additive, keep-both on rebase).

Ceremony: full 29-step workflow, opus review effort=high — touches the METAR lock-in path, the sharpest safety surface in the repo (see backlog L26674's open veto-gap there; do not widen that hole).

## The core fact (why this family is different)

`KXTEMPMIAH` launched for real (66K contracts/100 markets, ~6-7K/day, 5¢ median spreads — more than NYC hourly) and settles on **"Synoptic Data ... in accordance with the Kalshi Weather Index Methodology"** — a 5-contributor QC'd multi-station index, NOT KMIA METAR, NOT NWS CLI. Kalshi serves the settlement value in real time: `GET /trade-api/v2/live_data/weather/miami` (public, verified 2026-08-23/24; minute-resolution `{t, v, contributors, status}` timeseries; `config_version: miami-temperature-v1.0-qc-20260818`; the endpoint's own error message confirms miami is the only supported city today). Modeling this family off KMIA METAR is modeling the wrong variable.

## Items

1. **Decision experiment FIRST (go/no-go, <1 day):** poll the live_data endpoint alongside KMIA METAR for one afternoon; measure divergence at the market target hours. Outcomes: divergence ≥1°F at any settle hour → the index feed is mandatory, build items 2-4 in full. Divergence consistently <0.5°F → existing METAR logic suffices for the observation side; build only items 2 (registration) and 4 (feed as settlement cross-check), skip the lock-in abstraction. In-between → put it to the user. **This experiment's result also gates batch 56** (Synoptic nearby-station batch) — record the number in backlog.txt either way.
2. **Register Miami as the 6th hourly city:** `KXTEMPMIAH` into `_KXTEMP_HOURLY_CITY` + `KNOWN_WEATHER_SERIES` (with the L-17 registry tie verified/fixed per Context), hourly target-hour refresh, shadow-only through the existing hourly gates. KXTEMPBOSH stays out (still 0 markets since April, re-verified 2026-08-24).
3. **Index-aware observation source:** new module consuming the live_data endpoint (respect its unknown rate limits — poll modestly, cache like the METAR fetchers, circuit-breaker on failures, and treat `config_version` changes as an alert-worthy event via batch 51's settlement-source watcher). Abstract the hourly path's observation source per-city (Miami→index, others→METAR) WITHOUT restructuring `_metar_lock_in` for the other 5 cities — smallest possible seam.
4. **Settlement monitor:** for Miami hourly, settle/verify against the index value (or record both index and METAR and alert on disagreement) rather than METAR alone.

## Key risks to encode

- Methodology is v1.0 and days old — config_version churn is expected; the code must surface a version change loudly, not silently keep trading.
- The endpoint is documented only in the API changelog; it could become gated. Fail toward "no lock-in for Miami" (conservative), never toward falling back to METAR silently for a market that doesn't settle on METAR.
- One-city capacity: keep the build proportionate (this is rank 6, not rank 1).

## Constraints

- Shadow-only; no live orders. Hourly probability model reuse — no new model design in this batch.
- Scoped tests: `tests/test_weather_markets.py` hourly/lock-in tests, new test file for the feed module, grep for `_KXTEMP_HOURLY_CITY`/`refresh_hourly_target_hours`/lock-in transitive test callers. **Never the full suite.**
- backlog.txt: file the divergence number, the batch-56 gate verdict, and any index-methodology observations; run `python backlog_index.py`.
