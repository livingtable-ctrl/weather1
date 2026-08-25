# Batch 68: A13 settlement-source audit + A15a station bias — half a day that validates everything above it

## Context

Repo: weather1. Written 2026-08-24 against master `a67a21a6` — **re-verify current before starting** (`git fetch` + `git log origin/master`). Live trading dormant. Item 1 is an audit whose output may be a report and no code change; item 2 is read-only analytics.

Source: Weather V3 additions handoff (A13, A15), re-planned in **Backend Build Order** — https://claude.ai/code/artifact/dc35c571-4d3d-4771-b7f1-95518032a010. See [INDEX-PANEL-BACKENDS.md](INDEX-PANEL-BACKENDS.md).

Files owned: `settlement_monitor.py`, `metar.py` (read-mostly), `tracker.py` (new query function, item 2), `web_app.py`.

**Run this before batch 74** — its findings may change what A9's "high so far" is allowed to trust, and both touch `metar.py`.

## Items

### 1. A13 [HIGH — audit, probably not a build]: confirm every grading consumer reads the official settled value

**Files:** `tracker.py` — `audit_settlement` (~`:4785`), `outcomes.settled_temp_f`, the `outcomes_valid` view; `settlement_monitor.py:495` and `:269`; `metar.py` — `fetch_metar_daily_extreme`; `weather_markets.py:7698`.

**The handoff's premise is largely already handled, and its "⚠ BUILD FIRST, blocks six panels" framing is wrong.** `audit_settlement`'s own docstring records the fix:

> ...reads Kalshi's settlement figure directly once `status="finalized"` — the literal CLI-report figure Kalshi settled on — REPLACES the IEM ASOS raw-METAR archive proxy this branch used before... diverges from Kalshi's real CLI-report-based settlement by ~1 degree near a threshold.

That is exactly the bias A13 warns about, already fixed, with a disputed-row guard (`outcomes_valid`) on top. `paper._score_ensemble_members` correctly reads `settled_temp_f` rather than a live METAR.

**What is genuinely unresolved is whether that holds everywhere.** `settlement_monitor.py` still calls `fetch_metar_daily_extreme()` (`:495`), and `weather_markets.py:7698` calls it too. Those paths may be legitimate (a running-max estimate before the CLI publishes is a reasonable operational read) or may be grading something. The audit is to find out which.

**Fix direction — this is a tracing task, and the deliverable is an answer:**
1. Trace **every** consumer of a settled/observed temperature and record which source each reads. Do not stop at the first two; this codebase has a documented history of "one caller gets missed" (`feedback_trace_all_call_sites`, recurred 5×).
2. Establish whether settlement is **deferred until the CLI publishes** or fires at market close. The handoff flags the CLI typically publishes the following morning; a grade taken at close against a provisional number is the failure mode.
3. Check the **hourly temperature family separately.** The handoff states those settle on a different source entirely (The Weather Company), for which NWS reports are explicitly not authoritative. Confirm against current Kalshi rule text; `audit_settlement`'s docstring already notes Kalshi has no analogous single-hour figure and that the proxy/CLI divergence risk still applies there.
4. Only then decide whether any code change is warranted. **"No change needed, here is the trace" is a valid and likely outcome** — write it up as such rather than manufacturing a fix.

If a real mis-grading is found, a regrade of history is in scope and every calibration number in batches 65-67 must be recomputed after it.

### 2. A15a [MEDIUM]: per-station forecast bias is measurable today and is a free accuracy gain

**Files:** `tracker.py` — `ensemble_member_scores` (schema v34-v36) and a new query function; `web_app.py`.

`ensemble_member_scores` already carries per-model, per-city, per-target_date rows with `var`, `implied_prob` and `brier`, written by `paper._score_ensemble_members()` against the official settled value. Mean error (forecast minus observed) per station per lead is computable from it **now** — the handoff's claim that A15 needs new persistence applies only to the rank histogram, which needs member-level values and is batch 71.

The handoff calls this "a free accuracy gain — subtract it", and it is: a systematic per-station offset is directly correctable.

**Fix direction:** mean error per station per lead, with `n` per cell and the same withhold-below-floor discipline A14 uses. Report it; do **not** wire the correction into the forecast in this batch. Applying a bias correction changes forecasts, which changes trades — that is a separate, deliberate decision, and it needs the significance test rather than a raw mean, because a per-station-per-lead cell will be thin.

**Keep the caveat.** The handoff is emphatic that rank-based and spread-error diagnostics can misdiagnose reliability, and that recent literature argues "underdispersion" is ill-defined when the ensemble mean sits far from climatology. Carry that into the payload's definitions now, so batch 71 inherits it rather than re-deriving it.

## Process — follow the 29-step implementation workflow (`feedback-implementation-workflow`) exactly, in order

Full 29 steps. Item 1 concerns the correctness of the label every calibration number in this set is scored against.

(1) Re-verify: read `audit_settlement` and `settlement_monitor.py`'s METAR call sites directly — this transcription is a summary and the audit's whole value is in not trusting summaries. (3) If the audit finds a divergence, whether to regrade history is an `AskUserQuestion` decision with real consequences, not a call to make silently. (7) For item 2, real mutation-tested tests via Edit-revert with hand-computed expected values. If item 1 produces a code change, its test must reproduce the actual mis-grade (a synthetic row where METAR and CLI disagree across a strike), not merely assert the new source is read. (8) Scoped: `tests/test_tracker.py`, `tests/test_settlement_monitor.py`, `tests/test_metar.py`, `tests/test_disputed_row_guard.py`. **Never the full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high`. (14) Memory before commit — the audit's trace result is worth recording whichever way it lands. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push.

**Deliverable note:** item 1 may produce no diff. Report the trace to the user in full anyway — "verified correct, here is every consumer and what it reads" is the outcome that unblocks trusting batches 65-67, and it is worth writing down even when nothing changes.

Full step list: `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`.
