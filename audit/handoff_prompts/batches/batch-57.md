# Batch 57: Brier-family condition_type filtering (MEDIUM)

## Context

Repo: weather1. Written 2026-08-24 against master `223dedadcfd2` — re-verify current before starting. Source: backlog.txt entries L25014, L25041, L25098 (all three re-verified against live code during batch-48's backlog sweep, 2026-08-24 — each confirmed STILL OPEN with the file:line cites below accurate as of that hash).

Files owned: `tracker.py`, `calibration.py`, `ml_bias.py`, `main.py` (the `cmd_calibrate` Platt query only). Parallel-safe with batches 58-62 (no file overlap).

**Why these three are one batch:** they are the same defect with three different blast radii — Brier/skill statistics computed over prediction rows without excluding shadow-only, non-temperature `condition_type`s. The repo already has the correct exclusion logic (`count_settled_predictions()` applies it, and AUD-0004 fixed `graduation_check()`'s Brier the same way in commit `31e55b1e` — that fix is the precedent to mirror). Splitting these would mean three sessions each re-deriving the same exclusion list.

**This matters because it already caused a real incident:** AUD-0004 found `graduation_check()`'s unfiltered Brier read 0.2169 (passes the 0.23 live-trading gate) vs 0.2397 correctly filtered (fails it). That gate authorizes ALL live trading. The functions below feed dashboards, calibration fits, and analytics rather than that specific gate — but the same contamination is present.

## Items

### 1. `brier_skill_score()` has no `condition_type` filter [L25014]

**Files:** `tracker.py:3914` (`def brier_skill_score(city: str | None = None)`)

The function body (~33 lines) contains zero occurrences of `condition_type`, `_excluded_brier_condition_types`, or `_ALWAYS_EXCLUDED_CONDITION_TYPES` — verified by direct read 2026-08-24.

**Fix:** apply the same exclusion the repo's own `count_settled_predictions()` uses. Do NOT hand-write a new tuple — see item 2, which exists specifically because hand-written copies have already drifted.

**Verify before/after:** this function compares model Brier against a market baseline. There is a separate, already-recorded finding (memory: `project_weather1_no_brier_skill_vs_market`) that the model currently shows **no** skill vs market (0.2596 vs 0.2201, n=214) and that `brier_skill_score()` missed it partly by reading a view that drops D+0 rows (56% of the corpus). Re-run the comparison after this fix and record the corrected number in the backlog resolution — if filtering changes the verdict in either direction, that is a material finding, not a footnote.

### 2. Three modules still carry a hardcoded, drifting exclusion tuple [L25041]

**Files:** `calibration.py:42-49` (`_SHADOW_CONDITION_TYPES`), `ml_bias.py:201`, `ml_bias.py:917`, `ml_bias.py:947` (a literal 6-tuple inlined directly in SQL), `main.py:7854-7858` (inside `cmd_calibrate`'s Platt query)

Five sites, none of which import tracker's shared helper. A new shadow condition type added to the registry updates none of them.

**Fix:** export one canonical exclusion list from `tracker.py` (or wherever `count_settled_predictions()` already sources it) and have all five sites import it. This is the item that makes items 1 and 3 durable rather than a snapshot — do it **first**, then land 1 and 3 on top of it.

**Watch for:** the five sites may not currently agree with each other. Diff them before consolidating; if any site's list is a superset/subset of another, that difference is either a bug or a deliberate scoping decision, and you need to determine which before collapsing them. Do not assume the longest list is correct.

### 3. Four more Brier-family functions with no filter, found via adjacency [L25098]

**Files:** `tracker.py:1855` (`get_brier_by_days_out`), `tracker.py:3820` (`get_brier_by_tier`), `tracker.py:7522` (`get_brier_by_version`), `tracker.py:7551` (`get_pnl_by_signal_source`)

Zero `condition_type` matches in any of the four (verified 2026-08-24).

**Fix:** same shared exclusion from item 2. Note `get_pnl_by_signal_source` is P&L, not Brier — confirm the exclusion is actually correct there before applying it (a shadow signal's P&L may be genuinely interesting to report separately rather than exclude). If it should NOT be filtered, say so explicitly in the resolution note rather than silently skipping it.

## Process

Full 29-step workflow (`memory/feedback_implementation_workflow.md`). **No LOW-tier downgrade** — this spans 4 files, and item 1 touches a statistic that has already been shown to move a gate verdict. Opus review at `effort: high`.

Tests: scope pytest to the files touched — `tests/test_tracker*.py`, `tests/test_calibration*.py`, plus grep `tests/` for the exact function names being changed before finalizing the file list (a relevantly-named file can still miss a caller). **Never run the bare full suite.**

Each fix needs a real mutation test: revert the exclusion, confirm the specific test fails with a numerically different Brier, restore. A test that passes with and without the filter proves nothing.

Lint via the real pre-commit hook (ruff + ruff-format + mypy), not the repo's `.venv` mypy directly.

Update backlog.txt resolutions for L25014/L25041/L25098, then `python backlog_index.py` and confirm the entries left the open list. Confirm with the user before committing.
