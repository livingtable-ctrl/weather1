# Batch 48: Misc small-fix sweep (MEDIUM/LOW)

## Context

Repo: weather1. Written 2026-08-23 against master `aecbe5454277` — re-verify current before starting. Source: `FRONTEND_REVIEW_HANDOFF.md` (item M-10 in that doc's numbering), plus one item from `audit/POST_MERGE_REVIEW.md` re-located post-port. Files owned: `frontend/src/tabs/SignalsTab.jsx`, `frontend/src/tabs/PositionsTab.jsx`, `frontend/src/tabs/RiskTab.jsx`, `frontend/src/tabs/TradesTab.jsx`, `frontend/src/shared.jsx`, `frontend/src/App.jsx` (Enter-key handler + confirm-modal focus only), `frontend/index.html`. Run after batch-41/42/45/47 to minimize conflicts — this batch touches nearly every file the others do, in small unrelated ways, so it's the natural "do last, mop up" batch.

**This batch supersedes batch-34's item #8 (F-M4: SignalsTab submits orders from a detached stale opportunity object)**, re-located post-port. It does **not** touch batch-34's item #2 (M-7-audit, `web_app.py`'s `unlink()` missing `missing_ok`) or the `web_app.py`-only parts of item #7 (L-17 web sweep) — those files weren't touched by the V3 port, so batch-34's line cites for them are still valid; leave them there.

## Items

### 1. Confirm-modal Enter key doesn't work — likely the same bug as a pre-port finding, not a new one

**Files:** `SignalsTab.jsx` — the confirm modal's own code comment claims Enter confirms the action; the handler is actually attached to an unfocusable `div`, so it never fires.

`audit/POST_MERGE_REVIEW.md`'s L-17 sweep independently flagged "`App.jsx:1223` confirm-modal Enter handler dead (no tabIndex)" against the pre-port monolith. **Check whether this is the literal same code relocated during the port before fixing it as new** — if the `div`/handler in `SignalsTab.jsx` today is recognizably the same code that used to live at `App.jsx:1223`, this is one bug with two citations, not two bugs. Fix once regardless of which citation "owns" it, and note in the commit which citation(s) it resolves so neither audit trail double-counts it.

**Fix:** attach `tabIndex={-1}` (or make the modal itself focus-trapped and attach the keydown listener to the modal container) so Enter actually triggers confirm. While in this component, also address the modal accessibility gaps noted elsewhere in this handoff if not already covered by another batch: command-palette-style result rows using `div onClick` instead of `button` (unreachable by keyboard, invisible to screen readers), and the modal itself missing `role="dialog"` and a focus trap.

### 2. `PositionsTab.jsx` paints "available" balance green even when it's negative

A straightforward missing conditional — negative available balance is a signal something's wrong (overcommitted, or a display bug elsewhere), and painting it the same green as a healthy positive balance hides that signal.

**Fix:** conditionally colour the "available" value based on sign, matching the pattern used elsewhere in this codebase for other signed values (see batch-42's `fmtSigned` helper if it's landed by the time this batch runs — reuse it rather than adding a fourth ad hoc sign-to-colour mapping).

### 3. `RiskTab.jsx`'s `heatPct` is compared as a string

`heatPct` is produced via `.toFixed(...)` (a string) and then compared numerically against `80` — the comparison only works because JS coerces the string during the comparison. Fragile: any refactor that changes the comparison operator or wraps the value differently will silently break the comparison with no type error.

**Fix:** keep the numeric value around separately from its display-formatted (`toFixed`) string, and compare the numeric value explicitly.

### 4. `TradesTab.jsx` CSV export revokes its blob URL before some browsers finish the download

`handleExportCSV` calls `URL.revokeObjectURL` synchronously immediately after `.click()` on the download link. Some browsers treat a synchronous revoke as a cancelled download since the click's navigation hasn't necessarily completed yet.

**Fix:** defer the revoke — either a `setTimeout` of a second or two, or listen for the appropriate completion signal if the download approach supports one.

### 5. Position alerts persist to `localStorage` and are never evaluated; the row bell doesn't prefill

Alerts an operator sets from a position row are written to `localStorage` but nothing reads them back to actually check if a threshold has been crossed — they're stored and forgotten. Separately, clicking a row's alert bell opens the alerts panel without prefilling that row's ticker, so the operator has to re-select it manually even though they just clicked it from that specific row.

**Fix:** either wire up real evaluation (compare live quotes against stored thresholds on each poll, surface a notification when crossed) or, if that's out of scope for this batch, at minimum prefill the ticker field when opening from a row's bell icon so the existing UI doesn't feel broken. Flag the missing-evaluation half to the user/backlog if full evaluation logic is a bigger lift than fits this batch's scope — don't silently drop it.

### 6. `addToast` uses `Date.now()` as both the React key and the removal id

Two toasts fired within the same millisecond share a key, and the first one's removal timeout removes both.

**Fix:** use a monotonic counter or a proper UUID for toast ids instead of `Date.now()`.

### 7. `applyTheme` writes CSS variables from a `useEffect`, causing an unthemed first paint and a white flash for dark-mode users

First paint happens before the effect runs, and the initial default is the literal string `'light'` rather than respecting `prefers-color-scheme` — so a dark-mode OS user sees a white flash on every reload before the effect corrects it.

**Fix:** read `prefers-color-scheme` (or a stored preference) synchronously before first paint — e.g. inline a small script in `frontend/index.html` that sets the theme attribute/class before React mounts, rather than waiting for a `useEffect` after mount.

### 8. `OverviewTab.jsx` checks `/health` once on mount and never again

Cron-staleness is only checked at initial mount; the banner it drives is dismissible but never returns once dismissed, even if the underlying condition (trading silently paused) is still true or recurs.

**Fix:** fold `/health` into the existing 60-second batch poll (coordinate with batch-47 if it's mid-flight on the polling loop consolidation) so staleness is re-checked on a normal cadence, and make the banner re-appear if the condition re-triggers after a dismissal rather than staying permanently dismissed for the session.

### 9. Missing font stylesheet — the serif headline silently falls back to Georgia

`frontend/index.html` loads no font stylesheet, but `App.jsx` requests Inter and `OverviewTab.jsx` requests Source Serif 4. Neither is ever fetched, so both render in browser-default fallback fonts (Georgia for the serif headline).

**Fix:** either add the missing font `<link>` (Google Fonts or a self-hosted equivalent, consistent with whatever the rest of the app's asset strategy is) or drop the serif font request from `OverviewTab.jsx` if the Georgia fallback is actually acceptable — pick one rather than leaving the mismatch.

### 10. `shared.jsx`'s `TableSkeleton` re-injects duplicate `@keyframes pulse` per instance

The `@keyframes` block is defined inside the component body, so every mounted instance of `TableSkeleton` injects its own copy into the page.

**Fix:** hoist the `@keyframes pulse` definition to a module-level stylesheet injection (once, on module load) or a static CSS file, not per-render/per-instance.

### 11. Audit F-M4 [MEDIUM, stretch — re-located from batch-34, post-port]: SignalsTab submits orders from a detached, potentially stale opportunity object

**Files (pre-port, now stale — re-locate):** was `App.jsx:959,964,1087,1092`. Per this handoff's own note, this logic likely now lives in `tabs/SignalsTab.jsx` — confirm before editing.

Identity-compare selection plus a `confirmPending`-style state that freezes the *entire* opportunity object (including its quoted price) at the moment Approve is clicked. If the confirm modal stays open across a 60-second poll or a scan re-fetch, the order books at the stale, pre-refresh quote — bounded only by the server's ±0.15 deviation check (fixed as part of batch-41's item 5, if that batch has landed by the time this one runs). `PositionsTab.jsx` was already rewritten to use `selectedId` + `useMemo` (deriving the live object from current data by id, rather than freezing a stale copy) specifically to avoid this class of bug — generalize the same pattern to `SignalsTab.jsx`.

**Fix direction:** replace the frozen-object confirm state with an id-based selection (`selectedOppId`) and a `useMemo` that derives the current opportunity object from live data by that id, matching `PositionsTab.jsx`'s existing pattern. If the referenced opportunity disappears from live data entirely (e.g. the scan aged it out) while the confirm modal is open, decide explicitly what happens (recommend: close the modal with a toast explaining why, rather than either crashing or silently confirming against `undefined`).

## Process

Full 29-step workflow qualifies for the LOW-tier downgrade (self-review + 1 review agent) for the whole batch except item 11 (F-M4) — that one touches the same order-confirmation path as batch-41's CRITICAL items and should get at least one independent review pass at a higher bar given its proximity to real order submission, even though it's tagged MEDIUM/stretch. Re-verify claims live first, especially item 11's re-location and item 1's cross-reference to the pre-port L-17 finding. Tests: `cd frontend && npm test`. Lint via the real pre-commit interpreter. Rebuild `static/dist` in the same commit. Confirm before commit. Full workflow: `memory/feedback_implementation_workflow.md`.
