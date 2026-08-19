# Batch handoff prompts -- 105 backlog items in 21 conflict-free groups

Source: `audit/AUDIT_REPORT.md`/`.json` (2026-08-18 max-depth audit, 79 items) plus 26 pre-existing `backlog.txt` items, grouped by shared file/subsystem so no two batches touch the same file -- safe to run as parallel worktree sessions. Full per-item detail lives in each `batch-NN.md`; this index is just the map.

**3 items deliberately excluded from batching** -- not code work a session can pick up and execute:
- `backlog.txt` (DEMO_BASE SMOKE TEST) -- needs live/demo credentials and a manual operator action, not a code change
- `backlog.txt` (VM move + its gated process-lifecycle follow-up, 2 items) -- an infrastructure/hosting decision, already tracked separately

`PRE:2720` (EMOS) and `PRE:10000` (forecast run-trend signal) were re-evaluated during this session's triage and found NOT to be pure "wait for data" items after all -- EMOS's 40-row floor already cleared 2026-08-16, and the forecast-trend signal's sample count has moved from 0 to 22 since its entry was written. Both are re-included, in Batch 21, with corrected go-live bars set explicitly by the user (~80 settled trades for EMOS, ~60 rows for the forecast-trend signal -- see Batch 21 for the full staleness notes).

Every batch instructs the recipient session to follow the 29-step `feedback-implementation-workflow` memory in full.

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
| [12](batch-12.md) | Performance & reliability misc | audit | 7 | order_executor.py, trade_cycle.py, web_app.py, settlement_monitor.py |
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
| [12](batch-12.md) | Performance & reliability misc | audit | 7 | order_executor.py, trade_cycle.py, web_app.py, settlement_monitor.py |
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
