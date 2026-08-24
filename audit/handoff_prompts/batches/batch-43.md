# Batch 43: The entire app re-renders once per second (HIGH — biggest single perf win available)

## Context

Repo: weather1. Written 2026-08-23 against master `aecbe5454277` — re-verify current before starting. Source: `FRONTEND_REVIEW_HANDOFF.md`. Files owned: `frontend/src/App.jsx`. Single-item batch — kept separate from batch-42/45/47/48 (which also touch `App.jsx`) because this is a structural render-path change, not a leaf-level bugfix, and touching the provider value shape at the same time as unrelated `App.jsx` edits invites a bad merge. Sequence this batch's `App.jsx` work relative to 42/45/47/48 by rebasing, not by parallel editing — check the other frontend batches' status before starting so you're not stacking conflicting `App.jsx` diffs.

## Items

### 1. H-2 [HIGH]: `refreshCountdown`'s 1-second ticker re-renders every context consumer, including a 67 KB chart tab, every second

**Files:** `frontend/src/App.jsx`.

`refreshCountdown` lives in `App` and ticks every 1000 ms via `setInterval`/`setState`. The context provider is handed a fresh object literal on every render — `value={{ ...data, cronState, handleRunCron, handleCancelCron }}` — so its reference identity changes every time `App` re-renders, which is every second because of the countdown state living in the same component. Every context consumer re-renders as a result, regardless of whether it reads `cronState` or anything else in the spread. `AnalyticsTab.jsx` is 67 KB of chart computation, recomputed once a second, to animate a header label that changes once a second.

**Fix direction (two independent parts — do both):**
1. Move the countdown into its own leaf component that owns its own `setInterval` and its own local state, rendered wherever the countdown label is displayed. It should be the *only* thing that re-renders every second.
2. Wrap the context provider's `value` in `useMemo`, keyed on the actual pieces of `data`/`cronState`/the two handlers that matter — not on anything that changes every second. Once part 1 removes the countdown from `App`'s own render cycle, this stops the remaining re-renders on every genuine data refresh from also being an every-second event, but the memoization is still worth doing independently since `data` itself may be a new object reference on every poll even when its contents are unchanged.

**Verification:** before/after, use React DevTools' profiler (or a simple `console.count` in a couple of representative tab components) to confirm `AnalyticsTab`/`RiskTab`/other non-Overview tabs stop re-rendering on the 1-second tick and only re-render on actual data changes (the ~60s poll, or props they genuinely depend on).

## Process

Full 29-step workflow, but this qualifies for the LOW-tier downgrade (self-review + 1 review agent) — it's a pure client-side performance refactor with no data-correctness or safety surface, provided the fix doesn't change what data flows through the context (verify it doesn't: diff the provider's `value` shape before/after, confirm no field was dropped). Re-verify current `App.jsx` structure first — this batch may run after 41/42/45/47/48 have each landed their own `App.jsx` changes; reconcile against whatever the file actually looks like, not this doc's assumptions. Tests: `cd frontend && npm test`. Manually exercise the app in a browser after the fix (per the standing UI-change guidance — start the dev server, click through tabs, confirm the countdown still visibly ticks and data still refreshes on schedule) since a render-path refactor is exactly the kind of change unit tests alone won't catch a regression in. Lint via the real pre-commit interpreter. Rebuild `static/dist` in the same commit. Confirm before commit. Full workflow: `memory/feedback_implementation_workflow.md`.
