# Batch 45: Operator-trust items — silent failures dressed as success (MEDIUM)

## Context

Repo: weather1. Written 2026-08-23 against master `aecbe5454277` — re-verify current before starting. Source: `FRONTEND_REVIEW_HANDOFF.md`, plus two items from `audit/POST_MERGE_REVIEW.md` that this batch's source review explicitly re-locates post-port (see below). Files owned: `frontend/src/tabs/OverviewTab.jsx`, `frontend/src/tabs/RiskTab.jsx` (`BrierAlertCard`), `frontend/src/tabs/TradesTab.jsx`, `frontend/src/tabs/SignalsTab.jsx`, `frontend/src/tabs/SettingsTab.jsx`, `frontend/src/App.jsx` (halt/resume/kill button handlers + Nav badge only — do not touch the countdown/render-perf code, that's batch-43's, or the keydown handler, that's batch-42's). Run after batch-41 (shares `SignalsTab.jsx`) and ideally after batch-42/43 land in `App.jsx` to reduce merge friction.

**This batch supersedes batch-34's items #1 (audit M-8: halt/resume/kill buttons discard the server response) and #6 (audit F-M7: Nav badge hardcodes `Demo · Paper`).** Both were written against the pre-port monolith (`App.jsx:238, 1675, 2152, 2156` for M-8; `App.jsx:221` for F-M7) — post-port `App.jsx` is ~22 KB / ~520 lines, so those exact line numbers are almost certainly stale. **Re-locate the four halt/resume/kill call sites and the Nav badge before working those two items; do not assume they're still in `App.jsx` at all** — the frontend review notes this class of code moved into `tabs/SettingsTab.jsx`, `tabs/RiskTab.jsx`, and `App.jsx`'s `Nav` component during the port. Do these two items **here**, not in batch-34; batch-34's other items (#2, #7, #8) are pure-`web_app.py`/unaffected-by-port and still belong there as written (batch-48 supersedes #8 specifically, for a different reason — see that batch).

The common shape across this batch (per the source review's own framing): each of these already has a correct sibling implementation elsewhere in the same file that does the same job with real error handling — the fix is almost always "make this path match its own sibling," not new design.

## Items

### 1. M-4 [MEDIUM]: the same underlying Brier-degradation state is labeled two different severities depending which tab you're on

**Files:** `tabs/OverviewTab.jsx` and `tabs/RiskTab.jsx` (`BrierAlertCard`) each independently compute "consecutive weeks above 0.22" over `slice(-6)` of the same data.

The duplicated computation itself is fine — the problem is the labels disagree for the identical state:

| Weeks above 0.22 | OverviewTab | RiskTab |
|---|---|---|
| 1 | amber "Brier **warning**" | badge "**ALERT**" |
| 2+ | "P10.3 Brier **alert**" | "**DEGRADING**" |

An operator switching tabs sees the severity label change with no change in the underlying state, which reads as either tab being wrong.

**Fix:** one shared helper (in `shared.jsx`, alongside the other formatting helpers this handoff's other batches are adding) returning `{ weeks, tier, label }` from the raw Brier history; both tabs render from it instead of each computing and labeling independently.

### 2. M-6 [MEDIUM]: Trade History's own summary line doesn't add up

**Files:** `tabs/TradesTab.jsx`.

The header reads `{filtered.length} settled · {wins} wins · {losses} losses`, but `wins`/`losses` are computed from the full unfiltered `M.closedTrades` while the leading count respects whatever filter is active. Filter to one city and the numbers stop adding up; the derived `other = filtered.length - wins - losses` can go negative, rendering something like `· -4 breakeven`.

Same root issue, different control: `handleExportCSV` always exports every trade in `M.closedTrades`, even though the export button sits inside the filter row where an operator would reasonably expect it to export what's currently filtered/visible.

**Fix:** compute `wins`/`losses`/`other` from `filtered`, not `M.closedTrades`, so the header's three numbers are internally consistent. For the export: either make it export `filtered` (matching its visual placement) or, if exporting everything is the intended behavior, move the button out of the filter row and label it accordingly so the mismatch isn't implied by placement.

### 3. M-7 [MEDIUM]: "Reject" does nothing, and tells the operator it did

**Files:** `tabs/SignalsTab.jsx` — `handleAction(opp, 'reject')` and `handleBulkReject`.

Both set a success message and return, with no request sent and no state persisted anywhere. The row is unchanged and will reappear identically on the next scan. Sitting beside an Approve button that really places an order, and reporting `✗ Rejected 4 signals` — using the same toast styling as a real action — this reads as a recorded, durable decision when it's actually a no-op.

**Fix:** either persist a real dismissal (server-side or at minimum `localStorage`, scoped and expired sensibly so it doesn't hide a genuinely new signal on a re-scan forever) so a rejected signal actually stops reappearing, or relabel the action as a local/session-only hide (e.g. "Dismiss" instead of "Reject," with copy that doesn't imply persistence) if a real reject isn't in scope for this batch. Pick one — don't leave the current mismatch between the verb and the behavior.

### 4. M-8 [MEDIUM, frontend-doc numbering — distinct from audit M-8 below]: manual trading override is the one destructive action on the page with no confirmation

**Files:** `tabs/SettingsTab.jsx`.

Halt confirms. Resume confirms. Close Position confirms. Setting a manual override — which force-allows trading through an active drawdown halt — fires on a single click with none. Three more issues confirmed in the same file while reviewing this:
- `overrideMsg` renders in green `#16a34a` even when its content is literally `✗ Request failed`.
- `overrideDuration` is coerced with unary `+e.target.value`, so clearing the field posts `duration_minutes: 0` — past the input's own `min="5"` attribute, which only constrains the spinner UI, not what actually gets submitted.
- The bottom Halt/Resume button pair omits the `M.refresh()` call the inline resume button (elsewhere in the same file) makes, so the UI doesn't reflect the new state after using this pair specifically.

**Fix:** add a confirmation step to the override action matching the other three destructive actions' pattern in the same file. Fix `overrideMsg`'s color to be conditional on success/failure, not hardcoded. Validate `overrideDuration >= 5` client-side before submitting (and consider a server-side floor too, though that's outside this batch's file ownership — flag it in the item's commit/backlog note if the server doesn't already enforce it). Add the missing `M.refresh()` to the bottom Halt/Resume pair.

### 5. Audit M-8 [MEDIUM, skeptic-downgraded from HIGH — re-located from batch-34, post-port]: halt/resume/kill buttons discard the server response entirely

**Files (pre-port, now stale — re-locate):** was `App.jsx:238, 1675, 2152, 2156`. Per this handoff's own note, likely now split across `tabs/SettingsTab.jsx` and/or `App.jsx`'s `Nav` — confirm by grepping for the four `fetch('/api/halt'` / `/api/resume` / `/api/kill`-equivalent call sites before editing.

Pattern (from the original audit, still true structurally regardless of which file it now lives in): `window.confirm(...) && fetch('/api/halt', {method:'POST', headers: authHeader()})` — no `.then`/`.catch`/state update. `/api/halt` has a real 500 path server-side that no client code reads; failures are silent and the halt-status badge lags up to the next poll interval. Original skeptic context for the MEDIUM tier (not HIGH): the CLI (`py main.py kill`) is the documented emergency-halt procedure, and a watching operator would notice the badge failing to flip — but a silent failure on a safety-relevant button is still worth fixing, and the fix is trivial once located.

**Fix:** `.then(r => r.ok ? data.refresh() : addToast('Halt FAILED — use py main.py kill', 'error')).catch(...)` (or the equivalent for resume/kill) at all four call sites. `addToast` already exists in scope in this codebase (used elsewhere in the frontend).

### 6. Audit F-M7 [MEDIUM, display — re-located from batch-34, post-port]: Nav badge hardcodes `Demo · Paper` on a `KALSHI_ENV=prod` deployment

**Files (pre-port, now stale — re-locate):** was `App.jsx:221`. `/api/status` already returns `kalshi_env`/`is_live`, and `SettingsTab.jsx` already renders the real value elsewhere on the page — the always-visible header badge contradicts what Settings shows for the same field.

**Fix:** bind the Nav badge to the real `kalshi_env`/`is_live` values from the same data source `SettingsTab.jsx` already reads, instead of a hardcoded string.

## Process

Full 29-step workflow. This batch is squarely about operator trust in what the dashboard tells them — treat items 3, 4, and 5 (Reject no-op, override no-confirm, halt/resume/kill silent failure) at full ceremony including independent opus review at effort=high; items 1, 2, and 6 (Brier label mismatch, Trade History math, Nav badge) qualify for the LOW-tier downgrade (self-review + 1 review agent) since they're display-only with no action or confirmation semantics attached. Re-verify claims live first — items 5 and 6 specifically need re-location before anything else, don't assume the old line numbers are even approximately right. Tests: `cd frontend && npm test`. Lint via the real pre-commit interpreter. Rebuild `static/dist` in the same commit. Confirm before commit. Full workflow: `memory/feedback_implementation_workflow.md`.
