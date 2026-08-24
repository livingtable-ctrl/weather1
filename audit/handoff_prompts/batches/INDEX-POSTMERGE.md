# Post-merge audit fix batches — batches 31-40

Source: `audit/POST_MERGE_REVIEW.md` (2026-08-23 whole-program post-merge audit of `f4291771`; every CRITICAL/HIGH adversarially re-verified with executed repros — skeptic verdicts and tier corrections are baked into the item texts). This index maps only the NEW batches; the 2026-08-18 effort's batches 1-21 live in `INDEX.md` (batches 22-30 were implemented from handoffs that were never committed here).

**Commit prerequisite:** `audit/POST_MERGE_REVIEW.md` + `audit/POST_MERGE_REVIEW_COVERAGE.md` + these batch files must be committed to master before parallel worktree sessions start — worktrees can't see the main clone's uncommitted files.

**3 operator quick-actions that need no session** (also embedded in their owning batches, skip there if already done):
1. `del data\walk_forward_params.json` — it is test-fixture output written into the real data dir on 2026-08-23 (claims 6 folds; the real corpus can produce 0). `PAPER_MIN_EDGE` falls back to param_sweep/0.05 default. [M-20, batch 37]
2. `.venv\Scripts\pip install properscoring` — in requirements.txt:16, missing from the venv; 22 EMOS tests currently error. [M-23c, batch 38]
3. `cd frontend && npm install` — vitest is a declared devDependency but not installed; `npm test` fails on the live tree. [M-23g, batch 34]

## Sequencing

**Do first, in order, by one session with continuity (they gate live enablement):**
- [Batch 31](batch-31.md) — Live-order crash-recovery & exit serialization (contains the audit's only CRITICAL)
- [Batch 32](batch-32.md) — Config validation & CLI operator control (contains the only HIGH)

**Then safe to run in parallel with each other** (constructed file-disjoint; the one exception is noted):

| Batch | Name | Sev ceiling | Items | Files |
|---|---|---|---|---|
| [33](batch-33.md) | Cron, alerting & backup reliability | MEDIUM | 9 | cron.py, alerts.py, notify.py, trade_cycle.py, cloud_backup.py |
| [34](batch-34.md) | Dashboard & web order-path hardening | MEDIUM | 8 | web_app.py, frontend/src/* |
| [35](batch-35.md) | weather_markets internal correctness + regime | MEDIUM | 6 | weather_markets.py, regime.py |
| [36](batch-36.md) | Weather-data fetch layer | MEDIUM | 9 | nws.py, metar.py, mos.py, climatology.py, climate_indices.py, acis_precip.py, acis_snow.py, hurricane_climatology.py, forecast_cache.py, schema_validator.py |
| [37](batch-37.md) | Calibration & analytics data integrity | MEDIUM | 9 | calibration.py, ml_bias.py, backtest.py, param_sweep.py, settlement_monitor.py, monte_carlo.py, tracker.py (+1-line main.py — run AFTER batch 32) |
| [38](batch-38.md) | Test & environment hygiene | MEDIUM | 8 | tests/*, safe_io.py, .github/workflows/ci.yml, pyproject.toml, pdf_report.py, output_formatters.py |
| [39](batch-39.md) | Docs & backlog accuracy | LOW | 7 | LIVE_TRADING_RUNBOOK.md, README.md, docs/*, backlog.txt, paths.py, restore_window.ps1 |

**Deferred decision batch (run only after 35-37 land, and only when the user wants to invest in the between family):**
- [Batch 40](batch-40.md) — Between-bracket calibration design (M-14/WM2-F2 — architectural; needs user design decisions, overlaps weather_markets.py/tracker.py/metar.py with 35/36/37)

## Batches 41-48 — frontend review (2026-08-23, post-port)

Source: `FRONTEND_REVIEW_HANDOFF.md` (2026-08-23 frontend review of pushed `master @ aecbe5454277` — post-port, V3 now lives in `frontend/src/`). This review's own header states its relationship to the audit above: that audit's frontend items are M-8, M-9, M-10, M-11, and two entries inside L-17 (all in **batch-34**, written pre-port against the old monolith); everything in batches 41-48 below is net-new on top of that, except where a batch explicitly says it re-locates and supersedes one of batch-34's items post-port (batch-34's own header now cross-references each). `AnalyticsTab.jsx` (67 KB) logic itself was not reviewed — its two entries below (H-2, M-2) come from targeted pattern-grep only, not a full read.

**Unlike batches 31-40, these are NOT constructed to be file-disjoint** — several share `App.jsx`, `SignalsTab.jsx`, `PositionsTab.jsx`, or `RiskTab.jsx` with each other, because the source review's own "Suggested order" (reproduced below) is inherently sequential, not parallel. Follow the suggested order below rather than running these in parallel; where two batches touch the same file, rebase onto whichever landed first rather than editing in parallel.

**Suggested order** (from the source review):

| Batch | Name | Sev | Items | Files |
|---|---|---|---|---|
| [41](batch-41.md) | Bulk-action order-path integrity — client guards + server halves | CRITICAL | C-1, C-2, C-3, audit M-9, audit M-10, audit M-11 | SignalsTab.jsx, PositionsTab.jsx, useData.js, web_app.py |
| [42](batch-42.md) | Cheap high-value correctness — row keys, keyboard hijack, sign/colour | HIGH | H-1, H-3, H-4 | PositionsTab.jsx, SignalsTab.jsx, ActivityTab.jsx, SettingsTab.jsx, shared.jsx, App.jsx (keydown only) |
| [43](batch-43.md) | The entire app re-renders once per second | HIGH | H-2 | App.jsx |
| [44](batch-44.md) | Data-shape robustness — crash-on-guard, CSS token drift, alert schema | MEDIUM | M-3, M-1, M-5 | RiskTab.jsx, ForecastTab.jsx, ActivityTab.jsx, shared.jsx, useData.js |
| [45](batch-45.md) | Operator-trust items — silent failures dressed as success | MEDIUM | M-4, M-6, M-7, M-8, audit M-8, audit F-M7 | OverviewTab.jsx, RiskTab.jsx, TradesTab.jsx, SignalsTab.jsx, SettingsTab.jsx, App.jsx |
| [46](batch-46.md) | Dark-mode token promotion — mechanical sweep | MEDIUM | M-2 | shared.jsx, AnalyticsTab.jsx, RiskTab.jsx, OverviewTab.jsx, SettingsTab.jsx, ActivityTab.jsx |
| [47](batch-47.md) | Polling architecture, NaN math, tab-registry duplication, bundle size | MEDIUM | M-9 (frontend-doc numbering) | App.jsx, OverviewTab.jsx, useData.js |
| [48](batch-48.md) | Misc small-fix sweep | MEDIUM/LOW | M-10 (frontend-doc numbering), audit F-M4 | SignalsTab.jsx, PositionsTab.jsx, RiskTab.jsx, TradesTab.jsx, shared.jsx, App.jsx, index.html |

**Naming collision to watch for:** `FRONTEND_REVIEW_HANDOFF.md` has its own C-1..C-3/H-1..H-4/M-1..M-10 numbering, independent of `POST_MERGE_REVIEW.md`'s M-1..M-31. Where both appear in the same batch (41, 45, 48), each item is explicitly labeled "audit M-N" vs. the bare frontend-doc numbering to disambiguate — don't conflate e.g. frontend-doc M-9 (batch 47, polling/NaN/bundle) with audit M-9 (batch 41, `/api/close-position` gates).

**Pattern worth naming, per the source review:** most of C-1, C-2, C-3, H-1, H-4, M-4, and M-5 above are the same shape — a careful implementation exists somewhere in the file, and a second code path doing the same job skips the care (single close vs. bulk close, the Edge detail panel vs. the Edge table cell, `rowKey` vs. `key={i}`, Overview's Brier labels vs. Risk's, `SystemEventsCard`'s field fallback vs. Activity's bare `e.text`). When fixing any of these, look for the correct sibling implementation in the same file first — it's usually already there.

## Notes

- Item texts include the skeptic agents' verdicts and corrections — several findings were deliberately downgraded from their original reviewer tier (e.g. T-ticker settlement → LOW, micro-live gates → LOW, dashboard kill button → MEDIUM). Do not re-escalate without new evidence; the attack transcripts' conclusions are summarized per item.
- Batches 31-34 touch live-order/safety-gate surfaces: full 29-step `feedback-implementation-workflow` ceremony, opus review at effort=high. Batches 35-37: full ceremony (trade-entry pricing surfaces). Batches 38-39: LOW-tier downgrade allowed (self-review + 1 review agent) EXCEPT batch 38's item on the settled_at guard test, which mirrors batch 31's money-path work.
- **Never run the full test suite** — scope pytest to the specific files each item touches. This includes not running all 162 files in batches; the user has explicitly forbidden it twice.
- Every batch that edits backlog.txt: run `python backlog_index.py` afterward and verify BACKLOG_OPEN.md.
- backlog.txt is append-contended across parallel sessions — expect keep-both conflicts on rebase, same as batches 11-30.

## Cross-group parallel safety: batches 41-48 vs. 31-40

- **Batches 41-48 are parallel-safe with 31, 32, 33, 35, 36, 37, 38, 39, 40** — no file overlap (those own `order_executor.py`/`execution_log.py`, `config.py`/`main.py`, `cron.py`/`alerts.py`/`notify.py`/`trade_cycle.py`/`cloud_backup.py`, `weather_markets.py`/`regime.py`, the weather-data-fetch files, calibration/ml/backtest files, tests+lint infra, and docs respectively — none touch `frontend/src/*` or `web_app.py`).
- **Batch 34 is the one real conflict.** Its two still-valid items (M-7 at `web_app.py:2104-2106,2516-2518`; the L-17 web sweep at `web_app.py:2781-3053` and change) share `web_app.py` with batch-41's server-side items (audit M-9 at `:3127-3169`, audit M-10 at `:2909-2962`) — and L-17(c) at `:2969` sits inside batch-41's M-10 range specifically. **Do not run batch-34 and batch-41 in parallel** — sequence them; whichever lands second rebases onto the first.
- **41-48 are not parallel-safe with each other**, independent of what else is running — see the "NOT constructed to be file-disjoint" note above. Work them in the suggested order regardless of what else is in flight from the 31-40 group.
