# Batch 47: Polling architecture, NaN math, tab-registry duplication, bundle size (MEDIUM)

## Context

Repo: weather1. Written 2026-08-23 against master `aecbe5454277` — re-verify current before starting. Source: `FRONTEND_REVIEW_HANDOFF.md` (item M-9 in that doc's own numbering — distinct from `audit/POST_MERGE_REVIEW.md`'s M-9, which is the `/api/close-position` gates item handled in batch-41). Files owned: `frontend/src/App.jsx` (polling loops, tab registry, lazy-loading wiring — coordinate with batch-43/45/42, all of which also touch `App.jsx` for unrelated reasons; do this batch's work as a separate, clearly-scoped diff), `frontend/src/tabs/OverviewTab.jsx` (NaN guards), `frontend/src/useData.js` (if polling logic lives there rather than in `App.jsx` — check before assuming).

This batch is four loosely-related structural issues bundled because they all live in the same polling/bootstrap machinery — expect to touch more of `App.jsx` than the other batches that only fix a handler or a render path.

## Items

### 1. Four concurrent poll loops with no visibility-state gating

**Files:** `App.jsx` — `/api/scan-version` every 5s, all 22 endpoints every 60s, weather alerts every 15min, plus an SSE connection and a 3s cron-status poll while a scan is active.

None of these check `document.visibilityState` or pause on `document.hidden`. A background tab left open overnight issues roughly 17,000 `/api/scan-version` requests alone over 24 hours, plus the corresponding load on every other loop. This is server load and battery/bandwidth waste on the client, not a correctness bug, but it's real and cheap to fix.

**Fix direction:** wrap each `setInterval`/polling loop with a visibility check — either skip the tick entirely when `document.hidden`, or (better) clear and re-establish the intervals on `visibilitychange`, doing one immediate refresh on becoming visible again so the operator isn't looking at 8-hour-stale data for the first few seconds after switching back to the tab.

### 2. Unguarded division renders `NaN%` / `Infinity%` into KPI cards

**Files:** `OverviewTab.jsx` — `p.cost / p.qty` and `(balance - starting_balance) / starting_balance`.

Both divisions have no zero-guard. `p.qty === 0` (a data anomaly, but one the frontend shouldn't crash-render on) produces `NaN`; `starting_balance === 0` (plausible on a fresh install before any funding record exists) produces `Infinity%` or `NaN%` rendered directly into a KPI card an operator glances at for a quick health check. Note: `audit/POST_MERGE_REVIEW.md`'s L-17 sweep item independently flagged a divide-by-`p.qty` NaN in the pre-port `App.jsx:533,828,905` — that's very likely the same bug, relocated during the port rather than a second instance. Fix once here; don't also re-fix it if batch-48 (or whoever works batch-34's remaining items) encounters the same pre-port line cite — cross-reference and skip if already done.

**Fix:** guard both divisions (e.g. render "—" or "N/A" when the denominator is 0, rather than letting `NaN`/`Infinity` reach the DOM).

### 3. The tab list is written out four separate times, and has already drifted

**Files:** `App.jsx` — `Nav.TAB_NAMES`, `CommandPalette`, the keydown handler (batch-42 also touches this handler — coordinate), and the `TABS` registry.

Four independent copies of what should be one list. It has already drifted: Settings is excluded by a hand-written `i < 8` bound in one of the four places, and by a separately-truncated array literal in another — two different mechanisms accidentally producing the same current exclusion, which means a future edit to either one in isolation will silently reintroduce the inconsistency rather than fixing it everywhere.

**Fix:** collapse to a single source-of-truth array (id, label, component, hotkey digit) that `Nav`, `CommandPalette`, the keydown handler, and `TABS` all derive from. Confirm Settings' current inclusion/exclusion status is actually intentional (ask the user if unclear — this reads like an accidental omission, not a deliberate one) before consolidating, since the consolidation will make whatever the first list says the behavior everywhere.

### 4. All nine tabs are statically imported — 226 KB of tab source loads to render Overview alone

**Files:** `App.jsx`'s tab imports.

Every tab component is a static top-level import, so visiting the dashboard and landing on Overview pays the full bundle cost of all nine tabs, including the 67 KB `AnalyticsTab.jsx`, before anything renders.

**Fix:** convert each tab import to `React.lazy(() => import('./tabs/XxxTab.jsx'))`, wrapped in `<Suspense>` with the existing `TableSkeleton` component as the fallback (it already exists in `shared.jsx` per other items in this handoff — reuse it, don't build a new loading state). Verify tab-switch latency is acceptable after the change (a lazy-loaded 67 KB chart tab will have a visible load moment the first time it's opened in a session — confirm this is an acceptable tradeoff, e.g. by prefetching Analytics/Overview which are likely the most-visited tabs, or just confirm the `Suspense` fallback reads fine).

## Process

Full 29-step workflow qualifies for the LOW-tier downgrade (self-review + 1 review agent) for items 2 and 3 (NaN guards, tab-registry consolidation — mechanical, low-risk). Keep items 1 and 4 (polling visibility-gating, lazy-loading) at full ceremony since both touch the app's core data-freshness guarantees — a bug in the visibility-gating fix could leave the dashboard silently stale after backgrounding, and a bug in the lazy-loading conversion could break a tab's mount lifecycle in a way unit tests won't necessarily catch. Re-verify claims live first, and check with whichever of batch-42/43/45/48 landed first to minimize `App.jsx` merge conflicts. Tests: `cd frontend && npm test`. Manually verify in a browser: background the tab and confirm polling pauses (check the Network tab), switch tabs and confirm each loads (watch for the `Suspense` fallback), confirm the KPI cards don't show NaN/Infinity with a zero-quantity or zero-balance test case. Lint via the real pre-commit interpreter. Rebuild `static/dist` in the same commit. Confirm before commit. Full workflow: `memory/feedback_implementation_workflow.md`.
