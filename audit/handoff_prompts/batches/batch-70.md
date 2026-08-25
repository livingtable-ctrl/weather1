# Batch 70: A3 forecast provenance + A7 trade post-mortem — BLOCKED on batch 64

## Context

Repo: weather1. Written 2026-08-24 against master `a67a21a6` — **re-verify current before starting** (`git fetch` + `git log origin/master`). Live trading dormant. Both items are read-only analytics.

Source: Weather V3 additions handoff (A3, A7), re-planned in **Backend Build Order** — https://claude.ai/code/artifact/dc35c571-4d3d-4771-b7f1-95518032a010. See [INDEX-PANEL-BACKENDS.md](INDEX-PANEL-BACKENDS.md).

Files owned: `tracker.py` (new query functions), `web_app.py` (new endpoints). Additive-only.

**Blocked on [batch 64](batch-64.md) item 3 (per-cycle forecast history), and partly on item 1 (real model-cycle timestamp).** Do not start by building the writer yourself — that is batch 64's file ownership and duplicating it will conflict. **Before starting, check the writer has actually been producing rows**, and how many: `SELECT COUNT(*), MIN(...), MAX(...)` on whatever batch 64 landed. A panel built against three days of history will render but say nothing.

## Items

### 1. A3 [MEDIUM]: which model run produced this, and which way has it been moving

**Files:** `tracker.py` (new query function over batch 64's forecast-history rows + existing `blend_sources`/`run_trend_points`), `web_app.py`.

**Read what already exists first.** `get_forecast_run_trend()` (`tracker.py:5868`) already compares today's forecast for a target date against the last few runs and returns a points series; `run_trend_points`, `run_trend_delta` and `run_trend_jumpy` are persisted per prediction; `blend_sources` carries the model weights as JSON. The handoff calls A3 "the only genuinely new forecast pipeline in the first thirteen" — that is wrong, and building a parallel history mechanism beside `get_forecast_run_trend()` would be duplication. Scope this to composing what exists plus batch 64's genuine addition.

**Fix direction:** a per-city payload with the input source list (model name, cycle timestamp, age, blend weight, value), the blend summary (EMOS value + ensemble spread), the revision series over recent cycles with the spread band, and the model-vs-market probability gap over the same cycles — that shaded gap being, in the handoff's framing, the edge the scanner has been claiming, cycle by cycle.

**The staleness rule is the part with real value.** A source excluded for age currently surfaces only in logs. Surface it in the payload with the reason and `weight 0`, so an operator can see *why* a blend looks the way it does rather than inferring it.

### 2. A7 [MEDIUM]: were we right, or lucky

**Files:** `tracker.py` (new query function), `web_app.py`.

*Have:* observed high and strike per settled trade — both available at settlement, and both must come from the official source batch 68 verifies, **not** a METAR reading. *Need from batch 64:* the per-cycle rows for the timeline's middle.

The 2×2 is outcome (profit/loss) × forecast correctness (right/wrong), counts per cell, and the honest sentence beneath it: strip the lucky wins and the win rate falls from X% to Y%. That sentence is the panel.

**Fix direction:** the quadrant counts as a group-by; settlement margin in degrees from strike with the ensemble-spread band (a settlement inside the band is thin, flag it); and the event timeline including **the best exit that was available and not taken** — which is reconstructible from `price_history` the same way batch 67's A11 does it. Reuse batch 67's reconstruction rather than writing a second one.

**Dependency note:** this panel scores "was the forecast right", so it inherits batch 68's conclusion about which observed value is authoritative. If batch 68 found a mis-grade and history was regraded, this must be built against the regraded data.

## Process — follow the 29-step implementation workflow (`feedback-implementation-workflow`) exactly, in order

Full 29 steps.

(1) Re-verify twice over here: confirm batch 64's writer is producing rows **and** read `get_forecast_run_trend()` before designing item 1, so this batch composes rather than duplicates. (3) `AskUserQuestion` for item 1's cycle-window length and item 2's "forecast correct" definition — the latter is a genuine judgement call (correct side of the strike? within the spread band? within some degree tolerance?) and it determines every number in the quadrant. Do not decide it in a code comment. (7) Real mutation-tested tests via Edit-revert with hand-computed expected values; pair absence-assertions with positive controls. For item 2, a test that pins the right/wrong classification at the strike boundary specifically — that is where the definition chosen above actually bites. (8) Scoped: `tests/test_tracker.py`, `tests/test_web_app.py`, plus whatever covers the forecast-history writer. **Never the full suite.** (9) Lint via the real pre-commit hook. (11) Independent opus review at `effort: high`. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase immediately before push.

**Sample-size honesty:** the same discipline A14 established applies — withhold statistics below a floor rather than rendering a thin number, and report `n` everywhere. A 2×2 quadrant over a few dozen settled trades has cells with single-digit counts; say so rather than colouring them.

Full step list: `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`.
