# Batch handoff prompts -- 105 backlog items in 21 conflict-free groups

> ## ⚠️ Completion status — read before picking up ANY batch file
>
> **As of 2026-08-25, master `f1803e3e` + batch 54.** This directory holds 66 batch
> files and **~52 are already implemented and merged.** (The file count read "60" until 2026-08-25; it was stale — recounted from disk, not incremented.) Nothing inside an
> individual `batch-NN.md` says so — they are frozen handoffs, not living
> documents.
>
> | Batches | Status |
> |---|---|
> | **01-21** | ✅ **DONE** — the 2026-08-18 max-depth audit set. Their commit subjects name `AUD-XXXX` ids, **not** `batch-NN`, so `git log --grep="batch-01"` finds nothing and they look unstarted. They are not. |
> | **31-52** | ✅ **DONE** |
> | **56-63** | ✅ **DONE** |
> | **54** | ✅ **DONE** 2026-08-25 — KXTORNADO monthly count model, shadow-only behind `TORNADO_TRADING_ENABLED` + a 20-settled-**event** floor. Read the floor's wording before planning around it: all 11-17 brackets of a KXTORNADO month settle from one SPC number, so the counter dedupes to (year, month) EVENTS and 20 samples is ~20 MONTHS. Exactly 2 events have ever settled, so the gate cannot open before ~mid-2028. Its go/no-go passed the literal gate; the numbers, the four graduation criteria and the honest "no skill demonstrated at n=2" prior are in `backlog.txt` under "KXTORNADO MONTHLY TORNADO-COUNT MODEL -- GRADUATION CRITERIA AND THE HONEST TIMELINE". |
> | **53** | ⏸ **PARTIALLY DONE 2026-08-25 — the replay RAN; the idea is CLOSED.** Its go/no-go replay is no longer pending: IDR lost the CRPS gate on clean data (−9.30% vs the reference Gaussian where +5% was required, −14.21% vs the repo's own `fit_emos`, paired t = −3.55), and a learning curve over 40–246 training events shows it converging toward EMOS but never overtaking it, so more data will not change the verdict. **EMOS also fails the same bar** (+3.72%/+4.30%), so neither calibrator earns activation. Numbers and method in `backlog.txt` under *"IDR/EasyUQ AS A CALIBRATION CHALLENGER TO EMOS/TEMPERATURE-SCALING -- GATE FAILED, IDEA CLOSED"*. Productionizing was never started and now should not be. The replay also found the contamination that became **batch 75**. What remains deferred is only the rest of the calibration/ML cluster. **Correction retained from the row this replaced:** an earlier version said 54 and 55 collide with 56's `weather_markets.py` registry region — they do not. Batch 56 shipped as a standalone `nearby_station_obs.py` and never touched `weather_markets.py`. Confirmed independently while landing 54, by reading commit `44221356`'s own `--stat`. |
> | **55** | 🚫 **DECLINED 2026-08-25** — design batch, user go/no-go answered **no**; zero production code changed. Full reasoning in `backlog.txt`, entry "BATCH-55: KXAVGT WEEKLY AVERAGE-TEMPERATURE CONSECUTIVE-DAY STREAK MARKETS -- DECLINED". Short version: the family is eight days old, 53 of 55 brackets in its only completed week settled at ~1¢/~99¢, the book has no exit liquidity, and its settlement source (The Weather Company dailies) is not readable from this repo. Do not re-pick it up without re-running the four re-check questions in that entry. |
> | **68** | ✅ **DONE 2026-08-25** — A13 settlement-source audit + A15a station bias. **Verdict: the primary grading label is clean** — `outcomes.settled_yes` is Kalshi's own `result`, single writer, never accepted until `status="finalized"` and ≥1h past close. **No regrade; batches 65-67's numbers stand.** The audit did find and fix two derived-path defects: a stale frozen copy of the label in `ensemble_member_scores.actual_temp` (228 of 507 rows) feeding the live bias corrector, and the hourly branch reading a METAR proxy where Kalshi's `expiration_value` was available all along. **Batch 74 (A9) inherits one rule:** METAR is a legitimate pre-settlement *trading signal* but is NOT a settlement source for any family this bot trades — not even the hourly ones. |
> | **67** | ✅ **DONE 2026-08-25** — A11 exit-timing advantage + A16 strike-ladder view, plus the (city, date) → (city, date, var) event-key fix its grouping question exposed in `compute_market_implied_distributions` (a city-day's HIGH and LOW ladders were fitted as one Normal; 16 such city-days in `predictions`). A11's answer on 111 eligible settled trades: **no rule beats holding**. |
> | **66** | ✅ **DONE 2026-08-25** — the go/no-go for track D, and it returned **NO-GO for 72-74**. Conditioning A14's Brier on the SIZE of our disagreement with the price makes the model look *worse*, not better: skill −0.179 pooled → −0.233 at ≥0.20 → −0.431 at ≥0.30 (n=214), with model Brier *rising* (0.2596 → 0.2864 → 0.3105) while the market's stays near 0.220. The settled population is also *already* the tail — 100% of rows clear the 0.07 live floor. The P&L half agrees: capture ratio 0.378 over 243 settled trades, mean realized return **−0.040** per dollar of cost. See `tracker.get_model_vs_market_brier`'s `conditioned` ladder, `paper.get_edge_capture`, and the resolved backlog entry *"MEASURE BRIER SKILL CONDITIONED ON THE SIZE OF OUR DISAGREEMENT WITH THE PRICE"*. |
> | **64** | ✅ **DONE 2026-08-25** — the four forward-only writers; their sample clocks are running. `predictions.forecast_run_inits` (the REAL per-model run times — Open-Meteo does NOT return one in its forecast response, contrary to batch-64's own text; it is a separate per-dataset `meta.json` endpoint), `predictions.blend_exclusions`, `ensemble_member_values` (raw members, pre-bias and pre-replication — `n_members` is a weighted count and is NOT usable for a rank histogram), and `orderbook_depth_snapshots` + `kalshi_ws.get_cached_depth()`. Schema **v71** (v66-v71; batch-69 held v62-v65). **Batches 70/71 must check real row counts before starting, not assume a rate**, and neither table has a retention sweep yet (own backlog entry). |
> | **65** | ✅ **DONE 2026-08-25** — A12 scanner funnel + A2 calibration decomposition. `SCAN_GATES` declares all 36 analyze_trade gates in pipeline order with labels beside the gates themselves (an AST test pins both the set AND the order); bounded top-2-per-gate closest-miss retention; `snapshot_scan_funnel()` + `/api/scanner-funnel`. `get_calibration_decomposition()` adds Murphy terms, per-city × per-horizon cells and the halt rule's own weekly series with the per-week `n`. **FINDING: pooled Brier 0.259619 ± 0.015112 — one-sided 95% lower bound 0.2348, above the 0.22 halt threshold — while cron's weekly alert has never fired** (it reads days_out≥1 weekly windows of 2-15 rows). Filed OPEN, not fixed: it is a live-trading safety signal. **No per-city × per-horizon cell is large enough to say anything** (largest n=14; n=11 inside the halt population), so 34 of 38 cells report "not measured". Handoff corrections: `predictions` has no `entry_prob` column (A2 scores `our_prob`); the per-settlement-date cap is in `order_executor`, downstream of `gate_counts` entirely. Three OPEN backlog entries. |
> | **70-71** | 🟡 **PARTIALLY UNBLOCKED 2026-08-26 — check the counts yourself, they moved twice in one day.** Batch-64's writers were producing NOTHING until 2026-08-26 (no scan had run since 64 landed), and `ensemble_member_values` briefly held only synthetic test rows. Both fixed. As of 2026-08-26: `ensemble_member_values` **605 real rows** across 20 cities / 5 models / **4 distinct target_dates**, `forecast_run_inits` and `blend_exclusions` **4 rows each** (W1 records only when a fetch was actually observed, so cache hits legitimately write nothing), `orderbook_depth_snapshots` still **0** — it is written from the WS listener thread and needs live trading. So **70's A3 half has a usable signal and 71's A18 half has an x-axis, but 71's A15b rank histogram does NOT** — 4 target_dates is not months. Re-measure before starting either. |
> | **76-80** | 🟢 **READY 2026-08-26 — a new remediation set, and the only batches in this file that are startable right now.** Derived from the 61 open `backlog.txt` entries by filtering for single-session work, then grouped so no two share a touched file (verified programmatically: 0 conflicts). 13 findings — 2 HIGH, 6 MEDIUM, 5 LOW; **9 of 13 open with an `AskUserQuestion`**. Full writeup in [../../REMEDIATION_REPORT.md](../../REMEDIATION_REPORT.md) + `.json`. **76** METAR side-inversion + KXHOLIDAYTMIN var (HIGH — the recommended side can contradict the lock, verified `entry_side_edge=+0.18` against a settled outcome); **77** the shared `kalshi_api_read` breaker that left 8/8 positions without stop-loss protection (HIGH, observed live); **78** observability + retention; **79** process bootstrap + config durability; **80** frontend/alerting/two vacuous tests (shares no file with anything — safest parallel companion). Two further entries are deferred **only** by file contention, not by data or decisions. |
> | **81** | 🔴 **BLOCKED on 76-80** — the graduation floor, and why the 6x accrual does not reach it. `sample_floor=20` clears at ~27% power; the derived replacement is **86** (80% power). Three of five signals clear it today or within 4 days; `nbm_quantile_prob` — the one that cleared the old floor and fired the activation alert — is 68 days out, i.e. it looked ready because the bar was wrong. Second item is larger: `analysis_attempts` carries **no signal columns**, so 2026-08-26's 5.1x scoring gain bypasses every registry floor; logging signals there would cut time-to-86 from months to ~4 days AND make the rows unbiased. Touches all five files owned by 76-80, so it cannot run in parallel with any of them. |
> | **82** | 🔴 **BLOCKED on 76, 78, 79** — fit same-day blend weights separately, completing an ORIGINAL design intent rather than proposing a new one. Temperature scaling already separates same-day (`sameday` T=3.829 vs `global` 4.601, with an explicit no-fallback rule); blend-weight calibration never did — `calibration.py`'s `_load_rows()` reads `multiday_predictions` and its outputs have no horizon dimension, yet `weather_markets` applies them regardless of `days_out`. **D+0 is 56% of settled volume**, priced by a fit from the other 44%. Supply measured: 77 D+0 rows carry all three blend inputs (all `ensemble`; `metar_lockout` carries none of 106, structurally). Seasonal is fittable today; condition and city are not — hence the one decision: neutral defaults vs multi-day fallback when same-day is thin. |
> | **72-74** | 🔴 **BLOCKED on the 66 verdict above** — they are machinery for *collecting* edge more efficiently, and 66 found no measured edge to collect. Do not start them without an explicit user decision to override. |
> | **69** | ✅ **DONE** — A6 alert rules/evaluation/delivery log, A5 correlated-exposure measurement. **Two things are deliberately dormant and need an operator action to go live:** the whole alert engine is gated on `ALERT_RULES_ENABLED` (default **off**; use `py main.py alert-check --dry-run` to read real evaluation output first), and the `cron_gap` rule ships disabled because its out-of-band scheduler entry is **not registered** — it is the one rule the cron cycle cannot honestly evaluate. Populate A5's table with `py main.py correlations` (monthly at most). Sizing is unchanged: `paper.py` has a zero-line diff. |
> | **75** | ✅ **DONE 2026-08-26** — METAR-lock contamination. Landed `f8bf406d` (fix) + `087af072` (operator-hint correction) + `95b0df4c`. The running daily extreme no longer reaches `predictions.forecast_temp_f`; it moves to `observed_extreme_f` (schema v75) alongside a new raw `model_forecast_temp_f` (v76, added for SAMPLE-ACCRUAL RATE, read by nothing — measure before promoting it). **The finding that was not in the batch file:** six per-model queries each hardcoded `model != 'blended'`, and `get_model_weights` reads its model names FROM THE TABLE — so both new keys would have silently joined the live blend-weight softmax at 10 observations. Replaced with `tracker.NON_MODEL_SCORE_KEYS`. NOT put in `TRACKING_ONLY_MODEL_NAMES`: that set means "a real model we DO fetch", and `batch_prewarm_ensemble` iterates it to issue Open-Meteo requests. Repair pass ran live: 106 predictions rows moved, 69 member-score rows re-keyed, total row count unchanged, second run all zeros. Live effect was exactly one (city, var) — OklahomaCity/max −7.060°F n=10 ACTIVE → 0.000°F n=8 inert. 19 tests, each mutation-tested; three passed with their target deleted and were rewritten. |
>
> **Two traps this table exists to prevent, both hit for real on 2026-08-25:**
>
> 1. **Old batch files embed a `backlog.txt` excerpt frozen at authoring
>    time.** `batch-19.md` reproduces its entry as `[PARTIALLY RESOLVED ...
>    part (c) still open]`. That entry was fully resolved 2026-08-22 and now
>    reads `[RESOLVED ... nothing remains open in this entry]`. Reading the
>    batch file alone would send you to redo shipped work — this actually
>    happened. **Re-read the live entry in `backlog.txt` before starting.**
> 2. **`L`-numbers in any batch file are `backlog.txt` line offsets and
>    drift constantly** — they moved five times in one session on 2026-08-25
>    as parallel sessions appended. **Grep the entry TITLE**, not the line.
>
> Keep this table current when a batch lands; it is the only place that
> distinguishes done from pending.

Source: `audit/AUDIT_REPORT.md`/`.json` (2026-08-18 max-depth audit, 79 items) plus 26 pre-existing `backlog.txt` items, grouped by shared file/subsystem so no two batches touch the same file -- safe to run as parallel worktree sessions. Full per-item detail lives in each `batch-NN.md`; this index is just the map.

**3 items deliberately excluded from batching** -- not code work a session can pick up and execute:
- `backlog.txt` (DEMO_BASE SMOKE TEST) -- needs live/demo credentials and a manual operator action, not a code change
- `backlog.txt` (VM move + its gated process-lifecycle follow-up, 2 items) -- an infrastructure/hosting decision, already tracked separately

`PRE:2720` (EMOS) and `PRE:10000` (forecast run-trend signal) were re-evaluated during this session's triage and found NOT to be pure "wait for data" items after all -- EMOS's 40-row floor already cleared 2026-08-16, and the forecast-trend signal's sample count has moved from 0 to 22 since its entry was written. Both are re-included, in Batch 21, with corrected go-live bars set explicitly by the user (~80 settled trades for EMOS, ~60 rows for the forecast-trend signal -- see Batch 21 for the full staleness notes).

Every batch instructs the recipient session to follow the 29-step `feedback-implementation-workflow` memory in full.

**Later batch sets, indexed separately:** [INDEX-ROADMAP.md](INDEX-ROADMAP.md) (49-56, new market families) · [INDEX-BACKLOG-CLEANUP.md](INDEX-BACKLOG-CLEANUP.md) (57-63, remaining open `backlog.txt` entries) · [INDEX-PANEL-BACKENDS.md](INDEX-PANEL-BACKENDS.md) (64-74, backends for the eighteen proposed console panels — **start with batch 64, it has a decaying sample clock**). Batch **75** is standalone and has no index file of its own.

## Suggested sequencing

**Do first, in order, ideally by one session with continuity across them** (they share the live-position-visibility root cause -- audit's own recommendation is one coordinated fix, not five):
- [Batch 1](batch-01.md) -- Live-position visibility (coordinated root cause)
- [Batch 2](batch-02.md) -- Order lifecycle / crash-recovery
- [Batch 3](batch-03.md) -- Settlement & fee accounting
- [Batch 4](batch-04.md) -- Concurrency / locking

**Safe to run anytime, in parallel with everything else and each other** (no shared files with any batch above or with one another):

| Batch | Name | Source | Items | Shared files |
|---|---|---|---|---|
| [5](batch-05.md) | Live-trading docs & runbook accuracy | audit | 8 | LIVE_TRADING_RUNBOOK.md, README.md, main.py, kalshi_client.py |
| [6](batch-06.md) | Brier/calibration condition_type filter family | audit | 3 | tracker.py |
| [7](batch-07.md) | Timezone / UTC-vs-local sweep | audit | 4 | main.py, tracker.py, web_app.py |
| [8](batch-08.md) | Between-bucket / METAR settlement domain | audit | 4 | settlement_monitor.py, weather_markets.py, metar.py |
| [9](batch-09.md) | Security & config hardening | audit | 4 | kalshi_client.py, .env.example, main.py |
| [10](batch-10.md) | Test-gap sweep | audit | 6 | tests/*.py, conftest.py |
| [11](batch-11.md) | README / docstring accuracy sweep | audit | 8 | README.md, main.py, metar.py, ci.yml, pyproject.toml |
| [12](batch-12.md) | Performance & reliability misc | audit | 7 | order_executor.py, trade_cycle.py, web_app.py, settlement_monitor.py, main.py, execution_log.py, tracker.py |
| [13](batch-13.md) | Rain/hurricane/shadow-signal misc correctness | audit | 7 | weather_markets.py, cron.py, tracker.py, schema_validator.py |
| [14](batch-14.md) | INFO-tier confirmations (verify-and-close, minimal code) | audit | 14 | various |
| [15](batch-15.md) | Rain/snow/hurricane market category expansion | roadmap | 5 | weather_markets.py, cron.py, settlement_monitor.py |
| [16](batch-16.md) | Forecast/ML alpha signal development | roadmap | 6 | weather_markets.py, tracker.py, ml_bias.py |
| [17](batch-17.md) | Public trade-flow / market microstructure signals | roadmap | 3 | kalshi_ws.py, tracker.py |
| [18](batch-18.md) | Position read-model & CLI display consistency | roadmap | 3 | main.py, positions.py |
| [19](batch-19.md) | Signal graduation convention | roadmap | 1 | tracker.py, ml_bias.py |
| [20](batch-20.md) | Same-day sweep coverage | roadmap | 1 | main.py, cron.py |
| [21](batch-21.md) | Calibration go-live decisions | roadmap | 2 | ml_bias.py, tracker.py, main.py |

## All 21 batches

| Batch | Name | Source | Items | Shared files |
|---|---|---|---|---|
| [1](batch-01.md) | Live-position visibility (coordinated root cause) | audit | 6 | paper.py, order_executor.py |
| [2](batch-02.md) | Order lifecycle / crash-recovery | audit | 4 | kalshi_client.py, order_executor.py, main.py (cmd_watch) |
| [3](batch-03.md) | Settlement & fee accounting | audit | 5 | order_executor.py, execution_log.py |
| [4](batch-04.md) | Concurrency / locking | audit | 4 | cron.py, main.py, settlement_monitor.py, paper.py |
| [5](batch-05.md) | Live-trading docs & runbook accuracy | audit | 8 | LIVE_TRADING_RUNBOOK.md, README.md, main.py, kalshi_client.py |
| [6](batch-06.md) | Brier/calibration condition_type filter family | audit | 3 | tracker.py |
| [7](batch-07.md) | Timezone / UTC-vs-local sweep | audit | 4 | main.py, tracker.py, web_app.py |
| [8](batch-08.md) | Between-bucket / METAR settlement domain | audit | 4 | settlement_monitor.py, weather_markets.py, metar.py |
| [9](batch-09.md) | Security & config hardening | audit | 4 | kalshi_client.py, .env.example, main.py |
| [10](batch-10.md) | Test-gap sweep | audit | 6 | tests/*.py, conftest.py |
| [11](batch-11.md) | README / docstring accuracy sweep | audit | 8 | README.md, main.py, metar.py, ci.yml, pyproject.toml |
| [12](batch-12.md) | Performance & reliability misc | audit | 7 | order_executor.py, trade_cycle.py, web_app.py, settlement_monitor.py, main.py, execution_log.py, tracker.py |
| [13](batch-13.md) | Rain/hurricane/shadow-signal misc correctness | audit | 7 | weather_markets.py, cron.py, tracker.py, schema_validator.py |
| [14](batch-14.md) | INFO-tier confirmations (verify-and-close, minimal code) | audit | 14 | various |
| [15](batch-15.md) | Rain/snow/hurricane market category expansion | roadmap | 5 | weather_markets.py, cron.py, settlement_monitor.py |
| [16](batch-16.md) | Forecast/ML alpha signal development | roadmap | 6 | weather_markets.py, tracker.py, ml_bias.py |
| [17](batch-17.md) | Public trade-flow / market microstructure signals | roadmap | 3 | kalshi_ws.py, tracker.py |
| [18](batch-18.md) | Position read-model & CLI display consistency | roadmap | 3 | main.py, positions.py |
| [19](batch-19.md) | Signal graduation convention | roadmap | 1 | tracker.py, ml_bias.py |
| [20](batch-20.md) | Same-day sweep coverage | roadmap | 1 | main.py, cron.py |
| [21](batch-21.md) | Calibration go-live decisions | roadmap | 2 | ml_bias.py, tracker.py, main.py |

## Notes

- Batches were constructed so **no two share a touched file** -- verified programmatically at generation time. If working a batch surfaces a need to touch a file outside its stated scope, stop and check this index for which batch actually owns that file before expanding scope.
- "audit" batches (1-14) come from the 2026-08-18 max-depth forensic audit and each item cites `audit/AUDIT_REPORT.json`/`.md` for full detail. "roadmap" batches (15-21) are pre-existing `backlog.txt` items reproduced verbatim in each batch file -- these are feature/enhancement work, not audit-found bugs. Batch 20 is a single item that didn't cleanly fit any other theme after the VM-move batch it originally shared was removed.
- Batch 21 is the only batch where at least one item is explicitly a go/no-go judgment call rather than pure code work -- both of its items need a live re-check of a settled-trade count against a user-set threshold (see batch-21.md) before any code change, not just an implementation pass.
- Ranked/filterable view of all backlog items (severity, evidence, confidence): the published artifact from this session (ask if you don't have the link).
- AUD-0004 (the single most consequential audit finding -- graduation gate's Brier-score contamination) is already fixed and merged to master (`31e55b1e`) -- not in any batch here.
