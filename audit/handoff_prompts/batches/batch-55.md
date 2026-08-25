# Batch 55: KXAVGT weekly average-temperature streak markets (DESIGN BATCH — optional, largest build in the roadmap)

> 🚫 **DECLINED 2026-08-25 — do not implement this batch.** Its go/no-go was put
> to the user and answered **no**; zero production code was changed. The full
> reasoning, including six live-data findings that contradict the volume and
> tractability framing below, is in `backlog.txt` under "BATCH-55: KXAVGT WEEKLY
> AVERAGE-TEMPERATURE CONSECUTIVE-DAY STREAK MARKETS -- DECLINED". Read that
> entry before acting on anything in this file — several of its claims are stale
> or were wrong (the ladder is 2+..6+ not 3..6+; the family launched 2026-08-17
> so only one completed week exists; Atlanta already has no open event).

## Context

Repo: weather1. Source: Expansion Dossier B8 (score 6.1, rank 10 — worst effort-to-capacity ratio on the list; that's why it's a design batch with a user go/no-go, not a build order). Like batch 40's shape: starts with AskUserQuestion decisions, not code. Live-verified 2026-08-24: **11 weekly city series** (KXAVGTK: LAS, IAH, SAT, AUS, SAN, MSY, DEN, DFW, PHX, OKC + KXAVGTATL), real volume (Austin 124K, Houston 50K, San Antonio 38K, Vegas 16K, San Diego 17K, NOLA 16K, Atlanta 13K per recent week).

Files if built: `weather_markets.py` (registry + new condition type + streak evaluator), new settlement fetch for Weather-Company daily means, `monte_carlo.py` or a sibling for joint day-probabilities, tracker settlement. Overlaps Track C's registry region — strictly after 51/52.

Ceremony: full 29-step workflow, opus review effort=high (new trade-entry path + new settlement variable).

## What makes this one genuinely different (the design problem)

Settlement variable is NEW: "a day's average temperature is the arithmetic mean of the hourly temperature values reported by The Weather Company ... rounded to the nearest whole degree," with a data-quality rule — **"a day with fewer than 18 reported hourly values does not satisfy the condition and breaks a streak."** Contracts are **consecutive-day streak** ladders (N = 3..6+ days above X°F within the week), i.e. path-dependent joint probabilities, not marginals. Mid-week, the streak state is partially observed; late-week many brackets are decided arithmetic.

## Decisions to put to the user (with recommendations) before any code

1. Go/no-go at all, given rank 10 and effort L vs ~$100-300K/week family volume.
2. Observation source for realized daily means: weather.com/kalshi observed data vs reconstructing from hourly METAR (they can differ; the market settles on the former).
3. Joint model shape: hourly-ensemble-derived daily means + AR(1) day-to-day correlation into a Monte-Carlo streak evaluator (recommended — reuses existing machinery) vs anything fancier.
4. City scope for wave 1 (recommend the 3-4 highest-volume: AUS/IAH/SAT + one more; San Diego needs new-city registry work — defer it).

## Go/no-go validation (<1 day, run before the decisions are even asked)

For one city: reconstruct the last 3 weeks of daily means from weather.com/kalshi observed data; price the current week's ladder via hourly-ensemble draws with AR(1) day correlation; compare vs live prices. Gate: any bracket mispriced >10¢ under sane calibration. If the ladder tracks the model everywhere, file the numbers and close.

## Constraints

- Shadow-only behind its own 20-settled gate (weekly cadence → pooled ~7-11 settles/week across cities; gate fills in ~2-3 weeks — one of the few slow-cadence families where the gate is actually reachable fast, note it).
- The 18-hourly-values rule must be modeled as a streak-breaking event, not ignored.
- Scoped tests only. **Never the full suite.**
