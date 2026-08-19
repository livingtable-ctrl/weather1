# Batch 7: Timezone / UTC-vs-local sweep

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch comes from the 2026-08-18 max-depth forensic audit (`audit/AUDIT_REPORT.md` / `.json`). It groups 4 finding(s) that share **main.py, tracker.py, web_app.py** -- doing them together means you only load this subsystem's context once, and avoids two different sessions independently editing the same file in parallel. Live trading is currently dormant (`LIVE_TRADING_ENABLED` unset) -- no active financial exposure today for any item below, but treat items tagged HIGH/MEDIUM as touching a real live-order/live-money surface once trading is enabled.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. AUD-0017 [MEDIUM | VERY HIGH | E2 | CONFIRMED]: _target_date_due() still compares city-local target_date against UTC-today, missed by the 0100bffe/6364b38b fix sweep

**Files:** main.py  
**Lines:** 467-483; 874-893; 7230-7256

**Problem:** main.py's _target_date_due(target_date_str, today_date) is called from exactly two sites: cmd_watch_settle's _pending() closure (main.py:886-892) and the main-menu due-today-trades banner (main.py:7251-7255). Both compute today_date via utils.utc_today() (a UTC calendar date) and compare it against t.get(target_date), which is stored on paper trade dicts as analyze_trade's target_date.isoformat() -- a CITY-LOCAL calendar date parsed from the market ticker (order_executor.py:3101). This is the identical bug class that commits 0100bffe and 6364b38b fixed at every other target_date-vs-today comparison site -- but these two call sites were missed. The docstring/comments at both sites still assert the pre-fix UTC-anchored rationale.

**Root cause:** _target_date_due's only two callers construct their today via utils.utc_today() instead of a per-trade city-local today (ZoneInfo keyed off the trade's city), unlike every other target_date comparison site fixed by 0100bffe/6364b38b.

**Evidence:** Reproduced directly by re-running audit/reproductions/repro_target_date_due.py this session: `py audit/reproductions/repro_target_date_due.py` -> 'compared against UTC-today (2026-08-18) -> due=True' vs 'compared against NY-local-today (2026-08-17) -> due=False'. Also confirmed via git show --stat/diff on 0100bffe (touches tracker.py only via log_prediction; commit message explicitly defers main.py/monte_carlo.py sites to a separate backlog entry) and 6364b38b (fixes only _feature_importance_days_out and monte_carlo.py's simulate_portfolio, not _target_date_due) that neither fix commit ever touched these two call sites.

**Financial risk:** Low/indirect -- neither call site gates an order or a real settlement action; cmd_watch_settle's loop just runs longer than necessary and the banner only misinforms the operator.

**Recommendation:** Compute today_date via ZoneInfo keyed off each trade's own city, mirroring the local-today pattern already used elsewhere in this fix chain, with a UTC fallback on ZoneInfo failure.

**Limitations noted by the audit:** Verified at the comparison-function level via direct execution rather than end-to-end through a live cmd_watch_settle polling loop.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0017`), `audit/AUDIT_REPORT.md`.

### 2. AUD-0044 [LOW | HIGH | E1 | CONFIRMED]: tracker.py Previous-Runs-API helpers still use UTC-anchored day arithmetic against a city-local target_date, with stale comments asserting the opposite

**Files:** tracker.py  
**Lines:** 4195-4200; 4277-4283

**Problem:** _fetch_previous_run_daily (used by an offline backfill loop) and _fetch_previous_run_leads (used live by the FORECAST RUN-TO-RUN TREND shadow signal via get_forecast_run_trend_from_analysis) both compute past_days/forecast_days as (target_date - utils.utc_today()).days [+1]. Their inline comments justify this by citing analyze_trade's UTC-based days_out computation -- true before 0100bffe, but that commit changed analyze_trade to use city-local today instead, and the target_date fed into this signal is the same city-local value used elsewhere in analyze_trade's pipeline.

**Root cause:** These helpers were not part of 0100bffe's traced call-graph sweep, so their UTC-based arithmetic and comments were left unchanged after target_date's semantics changed everywhere else.

**Evidence:** Static read of tracker.py:4178-4283 cross-referenced against 0100bffe's diff (git show 0100bffe -- tracker.py shows only log_prediction changed) and get_forecast_run_trend_from_analysis (tracker.py:4426-4451), which extracts analysis[target_date] -- the same city-local value analyze_trade now produces.

**Financial risk:** Very low -- the consuming signal's own docstring (tracker.py, get_forecast_run_trend) states it is 'log-only today ... and must never block a trade decision'; the backfill path only affects historical training data.

**Recommendation:** Apply the same ZoneInfo-based local-today pattern used elsewhere in this fix chain, or document why these callers are exempt.

**Limitations noted by the audit:** Did not verify whether the Previous Runs API itself tolerates a 1-day-short forecast_days window in practice.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0044`), `audit/AUDIT_REPORT.md`.

### 3. AUD-0045 [LOW | HIGH | E1 | CONFIRMED]: cmd_forecast CLI display starts its 7-day range from UTC-today instead of city-local today

**Files:** main.py  
**Lines:** 3918-3949

**Problem:** cmd_forecast(city) sets today = utils.utc_today() and iterates 7 days from there via get_weather_forecast(city, today+i), with no per-city ZoneInfo adjustment despite city being a known parameter. During the nightly UTC-ahead-of-local window, the row labeled today actually shows tomorrow's local forecast, and the city's real local today is omitted from the displayed window.

**Root cause:** This CLI command predates or was never covered by the city-local-today fix chain and still uses the older utils.utc_today() convention.

**Evidence:** Static read of main.py:3918-3949 showing today = utils.utc_today() with no ZoneInfo use.

**Financial risk:** None -- manual/human-facing display command only.

**Recommendation:** Compute today via ZoneInfo(_CITY_TZ.get(city,...)) for consistency with the rest of the codebase.

**Limitations noted by the audit:** Did not run cmd_forecast interactively during an actual boundary window to visually confirm.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0045`), `audit/AUDIT_REPORT.md`.

### 4. AUD-0046 [LOW | HIGH | E1 | CONFIRMED]: web_app.py dashboard forecast endpoints label per-city forecasts using UTC-today, and their own justifying comment is now stale

**Files:** web_app.py  
**Lines:** 2097-2128; 3184-3222

**Problem:** Both /api/forecast and /api/today_forecasts compute their today/tomorrow date labels via utils.utc_today(), applied uniformly across all cities regardless of timezone. /api/forecast's inline WA-timezone comment acknowledges the mislabeling risk around local midnight but justifies keeping utc_today() by claiming the tracker/analytics side of the codebase standardizes on it -- that premise predates (2026-07-11) and is now contradicted by 0100bffe (2026-08-11), which moved the trading-logic side to city-local comparisons specifically to fix this same mislabeling problem.

**Root cause:** These endpoints predate the audited commit window and were not revisited by the 0100bffe/6364b38b fix chain; the comment's justification was never updated after its premise changed.

**Evidence:** Static read of web_app.py:2097-2128 (api_today_forecasts) and 3184-3227 (api_forecast), cross-referenced with git log -S WA-timezone showing the comment was introduced 2026-07-11 (commit 54b0c576), before 0100bffe changed the codebase-wide convention it cites.

**Financial risk:** None -- dashboard display only.

**Recommendation:** Low priority given this predates the audited window and is display-only; worth a follow-up to fix per-city or at least correct the stale comment.

**Limitations noted by the audit:** Primarily a documentation/consistency observation layered on a pre-existing, already-acknowledged design tradeoff.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0046`), `audit/AUDIT_REPORT.md`.

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

At least one item in this batch touches a live-order/live-money/safety-gate path (or is adjacent enough to warrant it) -- this batch does **not** qualify for the steps 11-12 LOW-tier downgrade. Apply the full ceremony as written, all 29 steps, for the batch as a whole.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
