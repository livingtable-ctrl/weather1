# Batch 56: Synoptic Data nearby-station observations (GATED — only if batch 52's divergence test triggers it)

## Context

Repo: weather1. Source: Expansion Dossier B9 (score 5.8, rank 11). **Hard gate: run only if batch 52's index-vs-METAR experiment recorded ≥1°F divergence at settle hours** (check backlog.txt for the number batch 52 filed). If divergence was small, this batch stays closed — for 39 of 40 tracked series the settlement variable is a single station the bot already reads directly.

Files: NEW module (suggest `synoptic_obs.py`), `weather_markets.py` obs-weight integration (the predictions schema already has `obs_weight_used`), config for the API key. Parallel-safe with everything except concurrent edits to the same weather_markets.py regions.

Ceremony: full 29-step workflow if wired into any live probability; LOW-tier if data-collection-only (recommend starting data-collection-only).

## The idea

Synoptic Data PBC aggregates ASOS + CWOP + state mesonets; free open-access tier = 5,000 API requests + 5M service units/month (synopticdata.com/pricing + /open-access-program, verified 2026-08). Extra relevance: Kalshi's Miami index is itself Synoptic-sourced — this API reads the settlement network directly for that family. SynopticPy (pip, maintained) lowers integration cost; Windows-fine.

Build (if gated open): pull the 5-10 nearest stations around the settlement point for target cities on a budgeted cadence (5,000 req/month ≈ 6.9/hour sustained — batch stations per request, poll only near settle windows); distance-weighted blend as a supplementary short-horizon observation signal, data-collected and accuracy-tracked BEFORE any probability wiring.

## Go/no-go validation (<1 day)

Free-tier key; 24h of the nearest stations around KMIA plus KMIA itself; measure whether the distance-weighted blend tracks the Kalshi Miami index better than KMIA alone (RMSE at minute resolution vs the live_data feed). Gate: blend beats single-station by ≥0.3°F RMSE. Fail → close the batch, file the numbers.

## Constraints

- CWOP quality is uneven (unaspirated sensors, siting bias) — apply Synoptic's QC flags; a bad station must not degrade a calibrated pipeline. Data-collection-first exists precisely so this is measured, not assumed.
- Free tier only; flag immediately if any needed capability turns out paid.
- Scoped tests: new module tests only. **Never the full suite.**
