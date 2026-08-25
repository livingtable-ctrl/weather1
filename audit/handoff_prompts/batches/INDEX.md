# Batch handoff prompts -- 105 backlog items in 21 conflict-free groups

> ## ⚠️ Completion status — read before picking up ANY batch file
>
> **As of 2026-08-25, master `e9d4f9f7` + batch 66.** This directory holds 66 batch
> files and **~50 are already implemented and merged.** (The file count read "60" until 2026-08-25; it was stale — recounted from disk, not incremented.) Nothing inside an
> individual `batch-NN.md` says so — they are frozen handoffs, not living
> documents.
>
> | Batches | Status |
> |---|---|
> | **01-21** | ✅ **DONE** — the 2026-08-18 max-depth audit set. Their commit subjects name `AUD-XXXX` ids, **not** `batch-NN`, so `git log --grep="batch-01"` finds nothing and they look unstarted. They are not. |
> | **31-52** | ✅ **DONE** |
> | **56-63** | ✅ **DONE** |
> | **53, 54** | ⏸ **Deferred** — [INDEX-ROADMAP.md](INDEX-ROADMAP.md). 53 waits for the calibration cluster's slot (its replay experiment may run any idle day); 54 is optional/no-deadline. **Correction:** an earlier version of this row said 54 and 55 collide with 56's `weather_markets.py` registry region — they do not. Batch 56 shipped as a standalone `nearby_station_obs.py` and never touched `weather_markets.py`. |
> | **55** | 🚫 **DECLINED 2026-08-25** — design batch, user go/no-go answered **no**; zero production code changed. Full reasoning in `backlog.txt`, entry "BATCH-55: KXAVGT WEEKLY AVERAGE-TEMPERATURE CONSECUTIVE-DAY STREAK MARKETS -- DECLINED". Short version: the family is eight days old, 53 of 55 brackets in its only completed week settled at ~1¢/~99¢, the book has no exit liquidity, and its settlement source (The Weather Company dailies) is not readable from this repo. Do not re-pick it up without re-running the four re-check questions in that entry. |
> | **68** | ✅ **DONE 2026-08-25** — A13 settlement-source audit + A15a station bias. **Verdict: the primary grading label is clean** — `outcomes.settled_yes` is Kalshi's own `result`, single writer, never accepted until `status="finalized"` and ≥1h past close. **No regrade; batches 65-67's numbers stand.** The audit did find and fix two derived-path defects: a stale frozen copy of the label in `ensemble_member_scores.actual_temp` (228 of 507 rows) feeding the live bias corrector, and the hourly branch reading a METAR proxy where Kalshi's `expiration_value` was available all along. **Batch 74 (A9) inherits one rule:** METAR is a legitimate pre-settlement *trading signal* but is NOT a settlement source for any family this bot trades — not even the hourly ones. |
> | **67** | ✅ **DONE 2026-08-25** — A11 exit-timing advantage + A16 strike-ladder view, plus the (city, date) → (city, date, var) event-key fix its grouping question exposed in `compute_market_implied_distributions` (a city-day's HIGH and LOW ladders were fitted as one Normal; 16 such city-days in `predictions`). A11's answer on 111 eligible settled trades: **no rule beats holding**. |
> | **66** | ✅ **DONE 2026-08-25** — the go/no-go for track D, and it returned **NO-GO for 72-74**. Conditioning A14's Brier on the SIZE of our disagreement with the price makes the model look *worse*, not better: skill −0.179 pooled → −0.233 at ≥0.20 → −0.431 at ≥0.30 (n=214), with model Brier *rising* (0.2596 → 0.2864 → 0.3105) while the market's stays near 0.220. The settled population is also *already* the tail — 100% of rows clear the 0.07 live floor. The P&L half agrees: capture ratio 0.378 over 243 settled trades, mean realized return **−0.040** per dollar of cost. See `tracker.get_model_vs_market_brier`'s `conditioned` ladder, `paper.get_edge_capture`, and the resolved backlog entry *"MEASURE BRIER SKILL CONDITIONED ON THE SIZE OF OUR DISAGREEMENT WITH THE PRICE"*. |
> | **64-65, 70-71** | 🟢 **READY** — [INDEX-PANEL-BACKENDS.md](INDEX-PANEL-BACKENDS.md). Start with 64 (decaying sample clock). |
> | **72-74** | 🔴 **BLOCKED on the 66 verdict above** — they are machinery for *collecting* edge more efficiently, and 66 found no measured edge to collect. Do not start them without an explicit user decision to override. |
> | **69** | ✅ **DONE** — A6 alert rules/evaluation/delivery log, A5 correlated-exposure measurement. **Two things are deliberately dormant and need an operator action to go live:** the whole alert engine is gated on `ALERT_RULES_ENABLED` (default **off**; use `py main.py alert-check --dry-run` to read real evaluation output first), and the `cron_gap` rule ships disabled because its out-of-band scheduler entry is **not registered** — it is the one rule the cron cycle cannot honestly evaluate. Populate A5's table with `py main.py correlations` (monthly at most). Sizing is unchanged: `paper.py` has a zero-line diff. |
> | **75** | 🟢 **READY** — standalone, no index file. Filed 2026-08-25 from batch-53's replay fallout: the METAR lock's *running* daily extreme is persisted as `forecast_temp_f` and reaches `get_dynamic_station_bias` via `ensemble_member_scores`' `model='blended'` rows, so it adjusts live forecasts. Backlog entry is Priority **HIGH**. Opens with two `AskUserQuestion` decisions; includes a schema migration. |
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
