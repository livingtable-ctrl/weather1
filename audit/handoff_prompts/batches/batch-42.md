# Batch 42: Cheap high-value correctness — row keys, keyboard hijack, sign/colour (HIGH)

## Context

Repo: weather1. Written 2026-08-23 against master `aecbe5454277` — re-verify current before starting. Source: `FRONTEND_REVIEW_HANDOFF.md`. Files owned: `frontend/src/tabs/PositionsTab.jsx`, `frontend/src/tabs/SignalsTab.jsx`, `frontend/src/tabs/ActivityTab.jsx`, `frontend/src/tabs/SettingsTab.jsx`, `frontend/src/shared.jsx`, `frontend/src/App.jsx` (global keydown handler only — do not touch the countdown/render-perf code there, that's batch-43's). Run after batch-41 lands (batch-41 also edits `SignalsTab.jsx`/`PositionsTab.jsx`; rebase onto it rather than working in parallel to avoid a merge fight on the same files).

The frontend review names the shape shared by three of this batch's four items (H-1, H-4, and — same class — M-4/M-5 in batch-44/45): **a careful implementation exists somewhere in the file, and a second code path doing the same job skips the care.** Keep that framing while fixing — the correct version is usually a few lines away in the same file.

## Items

### 1. H-1 [HIGH]: row keys are array indices, so selection binds to the wrong row after a sort or filter

**Files:** `PositionsTab.jsx` (`<tr key={i}>`), `SignalsTab.jsx` (`renderRows`, `<React.Fragment key={i}>`), `ActivityTab.jsx`.

`PositionsTab` already defines `rowKey = (p) => p.id ?? p.ticker`, with a comment explaining why, and uses it consistently for `selectedId`, `selectedIds`, and `confirmCloseId` — every piece of *state* is keyed correctly. Only the JSX row itself is keyed by array index, over a list that is both filtered and re-sorted by a dropdown. Change the sort order and React reuses row DOM by position while the `checked` prop follows identity: a checked box visually jumps to a different row than the one the operator checked.

**Fix:** key the `<tr>`/`<React.Fragment>` with `rowKey(p)` in each file — the function already exists in `PositionsTab.jsx` and is already trusted for every other piece of state; just point the `key=` prop at it too. Confirm `SignalsTab.jsx`/`ActivityTab.jsx` have (or need) an equivalent stable identity field before keying — don't assume `id ?? ticker` is the right key shape for rows that aren't positions.

### 2. H-3 [HIGH]: global number-key hotkeys hijack every input on the page, including an autoFocused one

**Files:** `App.jsx` — the global keydown handler (fix lives here). Affected fields, for reference when testing:

| File | Line (pre-this-batch) | Field |
|---|---|---|
| `tabs/PositionsTab.jsx` | 513 | close-price input (**`autoFocus`**) |
| `tabs/SignalsTab.jsx` | 216 | per-row order quantity |
| `tabs/PositionsTab.jsx` | 572 | alert threshold |
| `tabs/SettingsTab.jsx` | 148 | override duration |
| `tabs/ActivityTab.jsx` | 85 | log search |

The handler maps digits 1–8 to tab navigation and checks only for modifier keys, never `e.target`. Concretely: typing `12` into the order-quantity field navigates to Positions then Overview mid-keystroke, and the partial value is left behind in `qtyMap` for that ticker. Typing `0.45` into the autoFocused close-price input (which opens focused specifically so the operator can type immediately) navigates away to the Forecast tab partway through.

**Fix:** one guard clause at the top of the handler — bail out when `e.target` is (or is inside) an `input`, `select`, `textarea`, or any `contenteditable` element. Verify all five listed fields (plus any others the same handler might affect — grep for other bare `<input>`/`<textarea>` elements while in the file) stop triggering tab navigation after the fix.

### 3. H-4 [HIGH]: a negative edge renders as `+-3.2%` in green

**Files:** `PositionsTab.jsx` Edge column, `SignalsTab.jsx` Edge column, `SignalsTab.jsx`'s `selectedOpp` detail panel (all three hardcode both sign and colour — `'+'` string-concatenated onto the value, painted `#16a34a` regardless of magnitude).

`SignalsTab`'s own expanded-row detail view — roughly 40 lines below the broken table cell in the same file — formats the identical `edge_pct` field correctly: `o.edge_pct >= 0 ? '+' : ''` with conditional colour. So the app shows the same number two different ways on one screen, and the wrong one is in the sortable column an operator actually scans.

**Fix:** add a shared `fmtSigned` helper in `shared.jsx`, next to the existing `fmtEdge`, returning `{ text, tone }` (or equivalent) with correct sign and colour for any signed value. Replace all three broken sites with it, and consider replacing the already-correct detail-panel formatting with the same helper too (for consistency, not because it's currently wrong).

## Process

Full 29-step workflow — these are pure frontend display/interaction bugs (no live-money path, no server round-trip), so this batch qualifies for the steps 11-12 LOW-tier downgrade **for H-4 only** (self-review + 1 review agent). H-1 and H-3 touch selection-state correctness and global input handling respectively — keep those at full ceremony (independent opus review, effort=high) since a wrong fix could re-break selection tracking or leave another input field vulnerable to the same hijack. Re-verify claims live first (re-locate exact current line numbers — this batch runs after batch-41, whose edits to `SignalsTab.jsx`/`PositionsTab.jsx` will have shifted them). Tests: `cd frontend && npm test` (vitest — 29 tests exist as of the source audit; run `npm install` first if it's missing) — **never the full suite**, and there is no backend suite to run for this batch. Lint via the real pre-commit interpreter. Rebuild `static/dist` in the same commit (repo convention). Confirm before commit. Full workflow: `memory/feedback_implementation_workflow.md`.
