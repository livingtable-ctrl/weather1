# Batch 51: Market-catalog onboarding wave 1 — daily rain, weekend rain, holiday temps, drift watcher (Track C — DO FIRST, contains the only deadline)

## Context

Repo: weather1. Source: Expansion Dossier B2 (score 7.6, rank 2) + B11 (7.4, rank 7) + exec-summary catalog-gap + graduation A1/A2 riders, Rev 4, 2026-08-24. Assumes batches 31-48 landed — specifically batch 35 (weather_markets correctness) and batch 37 (calibration/analytics integrity).

**Deadline: KXHOLIDAYTMAX/TMIN registration pays off only if it ships before Labor Day (Mon Sep 7, 2026).** If the batch is running long, item 2 alone can be split out and shipped first — it's the smallest item.

Files: `weather_markets.py` (series registries `KNOWN_WEATHER_SERIES`/`KNOWN_UNTRACKED_RAIN_SERIES`, `_parse_market_condition`, `parse_city_date`, precip analyze path, `check_series_drift`), `consistency.py` (exclusion lists), `tracker.py` (daily-precip settlement fetch), `main.py`/`cron.py` only if a scan hook genuinely requires it. Parallel-safe with batches 49-50 per INDEX-ROADMAP; **batch 52 must wait for this batch.**

Ceremony: full 29-step workflow, opus review effort=high — this creates new trade-entry analysis paths (shadow-only, but the analyze/parse surfaces are live-shared).

All new families ship **shadow-only** behind the existing gate conventions (`RAIN_TRADING_ENABLED` + 20 settled for rain; the daily-temp families ride the existing temperature graduation state — confirm with the user whether holiday markets count as "daily temperature" (existing graduated family) or need their own shadow lane; default to shadow lane if unasked).

## Item 1 — Onboard relaunched KXRAIN daily + KXRAINWKND (dossier B2)

Live-verified 2026-08-23/24: `KXRAIN` ("Where will it rain today?") — one YES/NO market per city per day, exactly the bot's 20 cities (ATL AUS BOS CHI DAL DC DEN HOU LAX LV MIA MIN NOLA NYC OKC PHIL PHX SATX SEA SFO), ~2.03M contracts/100 markets, 413K vol on open markets, 1¢ median spread. `KXRAINWKND` — same cities/settlement over a Sat-Sun window ("any day within <Sat> through <Sun> strictly greater than 0 inches"), 21K vol. Settlement: "total precipitation at CLIxxx ... strictly greater than 0 inches", data via The Weather Company at weather.com/kalshi, **trace (T) and missing values count as 0**. Finalized markets expose `result` (yes/no) on the public API (verified).

Repo state to correct: `KNOWN_UNTRACKED_RAIN_SERIES` lists KXRAIN as "the old dead placeholder itself -- 0 open markets, ever" (stale since the relaunch; the 2026-07-20 verification note is now false). The condition parser already documents a `KXRAIN-26APR10-P0.25` explicit-threshold format — the relaunched tickers are `KXRAIN-26AUG24-SFO` (city suffix, implicit >0 threshold) — verify which shapes the current parser actually handles before assuming.

Build:
1. Move KXRAIN (and add KXRAINWKND) into tracked series; parse city from the ticker suffix (suffix→city map; note SATX/LV/NOLA/PHIL/MIN/DC abbreviations differ from the temp-series conventions — build the map from live tickers, don't guess).
2. Daily rain-occurrence probability from the existing ensemble precip machinery (`_fetch_ensemble_precip`, `_analyze_precip_trade` dispatch) — P(precip > 0) per city/date, with the trace-counts-as-0 settlement convention explicitly handled (ensemble members produce tiny nonzero QPF; choose and document a wet-threshold, e.g. members ≥ 0.01" count as wet — put the choice to the user via AskUserQuestion with a recommendation).
3. KXRAINWKND = 2-day window: P(any day wet) from the joint (use the multiday precip fetch `_fetch_ensemble_precip_multiday` pattern; day-to-day correlation matters — an independent-days product overstates dryness).
4. Settlement: extend tracker's settlement sync to record daily CLI precip for these (IEM CLI products carry daily precip; the market's own `result` field on finalized markets is also fetchable — use it as the primary settlement source and CLI as cross-check, or vice versa; surface the choice).
5. Exclusions sweep: keep both series out of `compute_market_implied_distributions` and `consistency._group_markets` unless deliberately added (same reason monthly rain is excluded — no ladder structure; these are single binary markets).
6. Shadow-log through the standard prediction pipeline so the existing rain gate's 20-settled counter accrues.

**Go/no-go validation (run first, <1 day):** backtest against the ~60 finalized KXRAIN markets from the public API (`result` field): compute Open-Meteo ensemble P(precip>0) per city/date via the Previous Runs API (tracker.py already uses it) and score Brier vs each market's last price. Gate: model Brier ≤ market Brier on ≥50% of cities. Fail → onboard as track-only logging WITHOUT shadow-trade predictions, and file the model-improvement need to backlog.

## Item 2 — Register KXHOLIDAYTMAX / KXHOLIDAYTMIN (dossier B11) — THE DEADLINE ITEM

Live-verified: 80 TMAX markets (all July 4th event, 561,591 contracts) + 40 TMIN (112,914), ~20 cities, rules identical in form to daily markets ("maximum temperature recorded at San Francisco for Jul 4, 2026 ... according to the Weather Company"). Ticker format packs date+threshold+city: `KXHOLIDAYTMAX-260704100-SFO` (= 2026-07-04, threshold 100, SFO).

Build: series registration + the packed-segment ticker/condition parser + routing into the EXISTING daily TMAX/TMIN analysis path unchanged. Discovery: these list episodically around holidays — the drift watcher (item 4) or a scheduled scan must notice new listings; don't assume a standing daily cadence. Shadow-lane decision per the Context note above.

**Go/no-go validation (<1 day):** replay the ~100 finalized July 4th markets: run the current daily model's probabilities for those city/date/thresholds (Previous-Runs forecasts; settled CLI temps are already in tracker's reach) and score Brier vs final market prices. Gate: model Brier ≤ market Brier overall.

## Item 3 — Hurricane next-event zero-predictions diagnosis (graduation A2 rider)

`_analyze_hurricane_next_event_trade` shipped 2026-08-07 but predictions.db contains ZERO `hurricane_next_event` condition_type rows as of 2026-08-24 (116 hurricane_count + 11 storm_order exist, so the shadow-logging pipeline itself works). Diagnose why: gate check? series scan not matching KXNEXTHURDATE/KXNEXTCAT5HURDATE events? condition parser returning None? the known L185/L4813 defects? Fix if small; file with findings if not. (KXNEXTHURDATE live-verified: 7 open markets, 5K vol — markets exist to analyze.)

## Item 4 — Catalog & settlement-source drift watcher (exec-summary gap; extension of `check_series_drift`)

**Existing-feature disclosure:** `check_series_drift()` exists and watches tracked series. The dossier's finding: six liquid launches (KXRAIN relaunch, KXRAINWKND, KXTEMPMIAH, 11-city KXAVGT, KXHOLIDAYT*, KXTORNADO) and one settlement-source migration (Miami→Synoptic index) all happened without the bot noticing, because untracked series and settlement rules aren't watched.

Build (keep it to alerting, not auto-onboarding):
1. Extend the drift check to alert when any series in the KNOWN_UNTRACKED_* / KNOWN_DEAD_* lists grows open markets with nonzero volume (the exact stale-comment failure this batch corrects), and when a brand-new weather-category series ticker appears that no list contains. Weekly cadence is enough.
2. Snow rider (A1): this same check covers the "re-scout snow in Nov" plan automatically — tracked-city snow series (KXBOSSNOWM etc.) growing real markets will alert. Also add the renamed-Denver check: `KXDENSNOWMB` now exists alongside tracked `KXDENSNOWM`.
3. Settlement-source watch: the Events API now returns a `settlement_sources` array (2026 changelog). Record it per tracked series and alert on change (this is how the next Synoptic-index migration gets caught the day it happens instead of by accident).
4. Refresh the stale registry comments this batch has proven wrong (KXRAIN "0 open markets, ever", KXTEMPMIAH/KXTEMPBOSH "genuinely unlaunched" — Miami launched, Boston still dead as of 2026-08-24).

## Constraints

- No live orders anywhere in this batch; everything shadow/log/alert.
- The wet-threshold (item 1) and shadow-lane (item 2) decisions go to the user via AskUserQuestion with recommendations — don't silently pick.
- Scoped tests: `tests/test_weather_markets.py`, `tests/test_rain_markets.py`, `tests/test_tracker.py`, new files for parsers/drift — then grep tests/ for transitive callers of every edited function (the batch 11-30 lesson: relevantly-named files miss differently-named ones). **Never the full suite.**
- backlog.txt: file follow-ups (rain graduation decision criteria, holiday next-window checklist, next-event findings); run `python backlog_index.py`.
