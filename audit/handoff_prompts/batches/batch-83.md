# Batch 83: test-suite integrity — a guard that doesn't cover its own repro scripts, a vacuous skip, and 85% of wall time

## Context

Repo: weather1. Written 2026-08-26 against master `0c332140` — **re-verify current before starting**. Live trading dormant.

**Files owned: `tests/conftest.py`, `circuit_breaker.py`, `paths.py`, `tests/prod_data_guard.py`, `tests/test_weather_markets.py`, `audit/reproductions/*`.**

Verified anchors, 2026-08-26 against `bc8bcb09` — spot-check, don't inherit: the guard lives at **`tests/prod_data_guard.py`** (not the repo root) and is armed by `tests/conftest.py:60` via `prod_data_guard.install(paths.DATA_DIR)`, with `paths.py:254` referencing its `ProdDataWriteError`. Exactly **one** `pytest.skip` remains in `tests/test_weather_markets.py`, at **`:1206`** (`if result is None`). `isolate_tracker_db` is at `tests/conftest.py:751` and `reset_open_meteo_circuit_breaker` at `:811`.

Three `backlog.txt` entries, cited by title. All three share `tests/conftest.py` or its immediate surface, which is why they are one batch.

### 1. [MEDIUM] `audit/reproductions/` scripts run outside pytest and bypass the prod-data guard

> `audit/reproductions/ SCRIPTS RUN OUTSIDE PYTEST AND SO ...`

**This is the batch's most valuable item and it is not hypothetical.** During the 2026-08-26 session, four separate commands were run against the real `data/predictions.db` — three `python -c` scripts and one `py main.py validate` — and the latter applied schema migrations v77 and v78 to the production database as a side effect of being run at all. The guard in `tests/conftest.py` (`27949ffa`) and the network default-deny (`3cca1e8e`) both exist and both work, and neither was in play, because neither runs outside pytest.

Design question worth deciding rather than assuming: a guard that only protects the test runner protects the least dangerous caller. Decide whether `prod_data_guard` should be importable and armable from a plain script, whether `audit/reproductions/` should get a shared harness that arms it, or both.

### 2. [MEDIUM] One `pytest.skip()` trapdoor left in `test_weather_markets.py`

> `ONE \`if result is None: pytest.skip(...)\` TRAPDOOR LEFT IN test_weather_markets.py (was four; three removed)`

Not flaky-and-occasionally-skipped — permanently skipped, reported by the suite as coverage. Three siblings were already removed, so both the pattern and the fix shape are established; read how those three were done before inventing a fourth approach.

**Its mutation is the deliverable.** A test whose entire defect is that it proves nothing must be shown to fail for the right reason once repaired.

### 3. [MEDIUM] Autouse fixture setup is 85% of test wall time

> `Autouse fixture setup is 85% of test wall time; two fixtures account for 99.6% of it` — `[PARTIALLY RESOLVED]`

Recommendation 1 (the circuit-breaker half, 74% of setup) shipped 2026-08-25. **Recommendations 2 and 3 are still open and `isolate_tracker_db` is the remaining cost.** Read the existing resolution notes before re-deriving anything.

Beware the interaction with item 1: if you change what `isolate_tracker_db` does, re-check that the real-`data/` guard still fires. These two items touch the same fixture from opposite directions, which is exactly why they are in one batch rather than two.


## Process — follow the 29-step implementation workflow

Read `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` and follow it.

(1) Re-verify every claim below against live code first — these were measured 2026-08-26 and the repo moved fast that day. (3) `AskUserQuestion` for any item marked as needing a decision. (7) Mutation-test via the **Edit** tool, never a string-replace script — a scripted revert has left a silent third state in this repo before. Pair every absence-assertion with a positive control. (8) Scoped tests only — **never the bare full suite**. (9) Lint via the real pre-commit hook, not the repo `.venv`'s mypy; the versions disagree. (11) Independent opus review at `effort: high`. (13) Address every finding including LOW. (14) Memory before commit. (15) Explicit user confirmation before commit/push. (16) `git fetch` + rebase immediately before push. (19) `python backlog_index.py`.

**Two standing hazards.** Scripts run outside pytest bypass conftest's real-`data/`-write blocker and its default-deny network guard — redirect `safe_io.project_root()` or the specific `paths.py` constant before running any scratch script. And do not run `git restore .` or `git checkout -- data/`.
