# Batch 65: A12 scanner funnel + A2 calibration — the two cheapest panels

## Context

Repo: weather1. Written 2026-08-24 against master `a67a21a6` — **re-verify current before starting** (`git fetch` + `git log origin/master`). Live trading dormant. Both items are read-only analytics over data already persisted; neither changes a trading decision.

Source: Weather V3 additions handoff (A12, A2), re-planned in **Backend Build Order** — https://claude.ai/code/artifact/dc35c571-4d3d-4771-b7f1-95518032a010. See [INDEX-PANEL-BACKENDS.md](INDEX-PANEL-BACKENDS.md).

Files owned: `tracker.py` (**new query functions only**), `web_app.py` (**new endpoints only**), `weather_markets.py` (gate-count region only, item 1).

**Coordination:** batches 64-67 and 70-71 all append to `tracker.py` and `web_app.py`. Work is purely additive — append new functions beside their subject-matter siblings — so conflicts should be zero and whichever lands second rebases. The one shared literal is `web_app.py`'s `/api/analytics` reflection tuple: rebase, don't hand-merge. Do **not** add migrations here; that is batch 64's and 72's territory.

**Pattern to copy:** A14 shipped in `7f0acc7a` and is the reference implementation for this whole set — `tracker.get_model_vs_market_brier()` + `_brier_series_stats()`, served through the `/api/analytics` reflection tuple rather than a route of its own. Read it before starting. In particular reuse its conventions: join `outcomes_valid` (never raw `outcomes`), apply `_condition_type_not_in_sql(_excluded_brier_condition_types())`, withhold every statistic below a sample floor rather than letting a caller render a thin number, and keep any advisory label display-only.

## Items

### 1. A12 [MEDIUM]: "why are there no signals today" cannot be answered

**Files:** `weather_markets.py` (`get_gate_counts`, and wherever candidates are rejected), `cron.py:2451` (`gate_counts` in the scan summary), `web_app.py`, `frontend/src/useData.js:441` for the existing normalisation shape (read only — no frontend work in this batch).

**This is the cheapest panel in the eighteen and it is cheaper than the handoff says.** `gate_counts` already flows end to end: `weather_markets.get_gate_counts()` → `cron.py:2451` writes it into the scan summary → `useData.js:441` normalises it → `RiskTab.jsx:383` already renders it. Nothing new needs plumbing.

Two things are missing. The counts are an **unordered dict**, so the funnel cannot be drawn — a funnel is meaningless without knowing which gate ran before which, and the useful sentence ("both survivors were rejected by the per-settlement-date cap, not by the model") requires knowing which gate was *last*. And rejected candidates are discarded, so the closest-misses table has no source.

**Fix direction:** give the gates an explicit declared order and human labels at the point they are defined, so the ordering is a property of the gate list rather than something the consumer reconstructs. Retain the top few rejected candidates per scan with their rejecting gate and the margin by which they missed. Add scanner-health fields the panel needs: last completed scan, forecast sources live, and days-with-zero-signals in the last 30 so a quiet day can be compared against its own baseline.

Keep the retention bounded — this runs every scan; a few candidates, not every rejection.

### 2. A2 [MEDIUM]: the weekly Brier halt rule fires on a blend that can hide a bad city

**Files:** `tracker.py` (new query function), `web_app.py`.

`entry_prob` (YES-space), the binary outcome, and `days_out` are all already persisted per settled prediction — the handoff is right that this needs no new data. What is missing is the decomposition and the per-city × per-horizon breakout.

The acceptance criterion is the point of the panel: the existing weekly-Brier halt rule evaluates a **blended** number, so a single city or horizon already past 0.22 can be masked by the rest. This panel must make that visible. Check what `brier_alertTier`/`detect_brier_drift` currently threshold on before designing the payload, so the panel's numbers and the halt rule's numbers are reconcilable rather than two different blends.

**Fix direction:** one `/api/calibration`-shaped payload, bucketed **server-side** (the handoff is explicit that A2, A14 and A15 should not be computed client-side). It needs: reliability-diagram bins with a sample count per bin; the Murphy decomposition (reliability, resolution, uncertainty — the three terms whose combination is the Brier already reported); and a per-city × per-horizon table with a 6-week trend series.

**Small-sample handling is not optional and not a UI concern.** Follow A14's structural approach: below the floor, return `None` for every statistic and a label — a caller cannot render a number it was never given. The handoff's `n<10` is the floor for *display*; if any cell drives a degradation flag, that flag needs its own, higher floor, and A14's `_paired_advantage` shows the pattern for gating on significance rather than a raw count.

## Process — follow the 29-step implementation workflow (`feedback-implementation-workflow`) exactly, in order

Full 29 steps. Item 1 touches the scan path, which runs every cron cycle; item 2's output feeds the operator's read on whether the model is degrading.

(1) Re-verify first: confirm `gate_counts` still flows as described and check whether any gate ordering already exists implicitly. (3) Item 1's retention shape (how many rejected candidates, where stored, how bounded) and item 2's floor-vs-flag threshold split are both genuine `AskUserQuestion` decisions — give them equal visibility. (7) Real, mutation-tested tests via Edit-revert. For item 2, hand-compute every expected Brier and decomposition value in the test's own comment from the rows that test inserts — never copy them from a run of the function; A14's `tests/test_model_vs_market_brier.py` is the pattern, including pairing every absence-assertion with a positive control. (8) Scoped: `tests/test_tracker.py`, `tests/test_calibration.py`, `tests/test_web_app.py`, `tests/test_weather_markets.py` (or whichever covers the gate path). **Never the full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high`, and review the fixes to its findings too. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push.

**One trap specific to item 2:** a per-city Brier computed on a handful of settled rows will look alarming or reassuring at random. Before shipping any degradation flag, check the live per-city row counts — if most cities are below the floor, the honest panel says so rather than colouring cells. A14's live data had exactly this shape: only two lead-time buckets had usable n.

Full step list: `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`.
