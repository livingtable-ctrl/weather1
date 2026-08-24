# Batch 44: Data-shape robustness — crash-on-guard, CSS token drift, alert schema mismatch (MEDIUM)

## Context

Repo: weather1. Written 2026-08-23 against master `aecbe5454277` — re-verify current before starting. Source: `FRONTEND_REVIEW_HANDOFF.md`. Files owned: `frontend/src/tabs/RiskTab.jsx`, `frontend/src/tabs/ForecastTab.jsx`, `frontend/src/tabs/ActivityTab.jsx`, `frontend/src/shared.jsx` (specifically `SystemEventsCard`), `frontend/src/useData.js` (mapper functions). Parallel-safe with batch-43 and batch-46; overlaps `ActivityTab.jsx`/`shared.jsx` with batch-45/batch-48 — sequence after those if working the same day, or coordinate on which item touches which lines.

## Items

### 1. M-3 [MEDIUM]: a guard clause that crashes on exactly the malformed-response shape it was written to guard against

**Files:** `tabs/RiskTab.jsx`.

The scan-filter section is wrapped in:

```js
M.scanStats && (M.scanStats.total_scanned > 0 || Object.keys(M.scanStats.filters).length > 0)
```

If `/api/scan-stats` ever returns an object without a `filters` key, `Object.keys(M.scanStats.filters)` throws on `undefined` — **the check written to prevent a crash on malformed data is itself the line that crashes on malformed data.** The same section then reads `M.scanStats.gate_counts` unguarded a few lines further down; the anomaly card in the same tab reads `window_trades.length`, `anomaly_messages.length`, `halt_threshold`, `min_samples` the same unguarded way. `useData.js`'s mappers for both endpoints only check `!raw.error` before passing the payload through — no field-level normalization happens anywhere upstream.

Same defect class, different endpoint and file: `tabs/ForecastTab.jsx` computes `f.high_range[1] - f.high_range[0]` and `f.high_f.toFixed(1)` with no defaults, iterating `Object.entries(data)` on a key that `mapForecasts` only ever sets when non-empty (so the presence check that exists doesn't protect the per-field access). One city missing `high_range` in a response takes the whole tab down into the ErrorBoundary.

**Fix direction:** normalise in the `useData.js` mappers, not at each render site — coerce missing/malformed fields to safe defaults (or drop the malformed row entirely) so tabs render partial data instead of crashing. This is the right layer because it fixes every current and future consumer of these endpoints at once, rather than adding guard clauses per render site that the next new consumer will forget.

### 2. M-1 [MEDIUM, confirmed one instance — worth a full sweep]: undefined CSS custom property renders as invisible text in dark mode

**Files:** `tabs/RiskTab.jsx:394` uses `var(--text-default)`.

The theme object (`App.jsx`'s `THEMES`) defines `--text`, `--text-muted`, `--text-faint` — there is no `--text-default`. An undefined CSS variable falls through to the browser/element default, which happens to be dark-on-transparent. Light mode hides the bug by accident; in dark mode, the scan-filter labels using this token render near-black text on a `#181b22` card — effectively invisible.

The source review confirmed this one instance by spot-checking plausible near-miss names, not by diffing all ~472 `var(--*)` references against the nine `THEMES` keys — **treat this as a sample finding, not an exhaustive list.**

**Fix direction:** fix the one confirmed instance (`var(--text-default)` → `var(--text)` or whichever was intended). Then do the full sweep: grep every `var(--*)` reference across `frontend/src/`, diff the referenced token names against `THEMES`'s actual key set, and fix every mismatch found — not just the one already caught.

### 3. M-5 [MEDIUM]: two consumers of `M.alerts` disagree with each other about the field names and severity vocabulary in the same array

**Files:** `tabs/ActivityTab.jsx` (reads `e.text`; levels `error`/`warn`/`info`/`good`) vs. `shared.jsx`'s `SystemEventsCard` (reads `evt.message || evt.msg || evt.text`; levels `error`/`warning`/`info`).

Same array, same backend endpoint, two different schemas assumed by two different consumers. If the backend sends `message` (not `text`), Activity's search box matches nothing and every row renders empty. If the backend sends `warning` (not `warn`), Activity's warn-filter **and its warning count** both silently read zero — a warning counter that reads 0 during an actual warning storm is a worse failure than an obviously broken UI, because nothing visibly indicates the count is wrong.

**Fix direction:** normalise both `level` and the message field in the `useData.js` mapper for this endpoint (same layer as item 1's fix) — pick one vocabulary (recommend matching whatever the backend actually sends, confirm by reading the real `/api/*` response shape rather than guessing), and have both consumers read the normalised shape. Delete the `SystemEventsCard`-side fallback chain once the mapper guarantees a single field name — a three-way `||` fallback that's needed today is a symptom of the schema disagreement, not a fix for it.

## Process

Full 29-step workflow qualifies for the LOW-tier downgrade (self-review + 1 review agent) for items 2 (M-1, mechanical token sweep) — keep items 1 and 3 (M-3, M-5) at full ceremony since they change what data reaches every consumer of two endpoints and a wrong normalization could hide a real backend problem instead of surfacing it gracefully. Re-verify claims live first, including re-running M-1's sweep from scratch rather than trusting "one confirmed instance" as the full scope. Tests: `cd frontend && npm test`, and add new test cases for the mapper normalization (malformed `scanStats`/`forecasts`/`alerts` payloads → graceful partial render, not a crash) — this is exactly the kind of regression a test should pin down since it won't reproduce visually except under a real malformed backend response. Lint via the real pre-commit interpreter. Rebuild `static/dist` in the same commit. Confirm before commit. Full workflow: `memory/feedback_implementation_workflow.md`.
