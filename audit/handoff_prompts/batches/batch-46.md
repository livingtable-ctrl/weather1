# Batch 46: Dark-mode token promotion — mechanical sweep (MEDIUM)

## Context

Repo: weather1. Written 2026-08-23 against master `aecbe5454277` — re-verify current before starting. Source: `FRONTEND_REVIEW_HANDOFF.md`. Files owned: `frontend/src/shared.jsx`, `frontend/src/tabs/AnalyticsTab.jsx`, `frontend/src/tabs/RiskTab.jsx`, `frontend/src/tabs/OverviewTab.jsx`, `frontend/src/tabs/SettingsTab.jsx`, `frontend/src/tabs/ActivityTab.jsx`, plus `App.jsx`'s `THEMES` object (add new tokens there). Single coherent mechanical pass — the review recommends doing this "in one pass" rather than splitting it, so it's kept as one batch despite touching many files.

## Items

### 1. M-2 [MEDIUM]: dark mode is half wired — the theme covers nine surface/text variables, but every semantic colour is a hardcoded hex

**Files and confirmed offenders:**

- `stroke="white"` on chart dots — **8 sites**: `shared.jsx:215,218,243,425`; `AnalyticsTab.jsx:75,404,928`; `RiskTab.jsx:90`. Should be `var(--bg-card)` (or a dedicated dot-stroke token if `--bg-card` doesn't read right against every chart background — check visually).
- `#92400e` (a near-black brown) rendered on translucent amber — **4 sites**: `OverviewTab.jsx:156`, `SettingsTab.jsx:134`, `RiskTab.jsx:360`, `AnalyticsTab.jsx:1068`.
- `shared.jsx`'s `SystemEventsCard.badgeStyle` — light-mode-only fills (`#fee2e2`, `#fef9c3`, `#dbeafe`) paired with dark text, so the badge is illegible once the surrounding page goes dark.
- `ActivityTab.jsx:192` — error-row text uses `#fca5a5` on a white card background, roughly 2:1 contrast. Error text — arguably the highest-priority text on the page — is currently the least legible.

**Fix direction:** promote the semantic colour set into `App.jsx`'s `THEMES` object as `--pos` / `--neg` / `--warn` / `--accent`, each with a per-mode value, plus tinted-fill variants for badge/card backgrounds (e.g. `--warn-fill`, `--neg-fill`) so `SystemEventsCard` and similar badge components can use a token instead of a hardcoded light-mode-only hex. Replace all confirmed offenders above with the new tokens. While making this pass, do the token-existence sweep batch-44's M-1 item calls for (diff every `var(--*)` reference in `frontend/src/` against the actual `THEMES` keys) if it hasn't already been done by whichever batch lands first — don't duplicate the sweep if batch-44 already did it, just confirm no new mismatches were introduced by this batch's own new token names.

**Verification:** toggle dark mode and visually check all four confirmed offender categories, plus spot-check a few other charts/badges/cards not explicitly listed above in case the same hardcoded-hex pattern recurs elsewhere (the four confirmed sites came from a targeted check, not an exhaustive one — the review says as much).

## Process

Full 29-step workflow qualifies for the LOW-tier downgrade (self-review + 1 review agent) — this is a pure visual/theming change with no logic, state, or data-correctness surface. Re-verify claims live first (confirm the listed hex/line combinations still match current code). Tests: `cd frontend && npm test` (should be unaffected, but confirm nothing snapshot-tests exact colour values that this batch intentionally changes). Manually verify in a browser: toggle both themes, check every listed site plus a general visual sweep of each affected tab. Lint via the real pre-commit interpreter. Rebuild `static/dist` in the same commit. Confirm before commit. Full workflow: `memory/feedback_implementation_workflow.md`.
