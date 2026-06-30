# Grade Audit — paths.py
_Graded 2026-06-29 | Auditor: claude-sonnet-4-6_

---

## File Summary

`paths.py` is a **pure constants module** — 35 lines, zero functions.

It defines module-level `Path` constants for every data and state file the bot
touches, rooted through `safe_io.project_root()` so that git-worktree runs
resolve to the main project's `data/` directory rather than the worktree copy.

There are no functions, no logic, no branches, and no side effects beyond the
two module-level computations on import:

```python
_ROOT = _project_root()
_DATA = _ROOT / "data"
```

Because there are no functions, the TIER 2 per-function grading format does not
apply. The module is evaluated as a whole below.

---

## Module-Level Evaluation

### What it does
- Calls `safe_io.project_root()` once at import time, stores the result in
  `_ROOT`.
- Derives `_DATA = _ROOT / "data"`.
- Exposes 14 named path constants covering: DB, paper ledger, all model
  artifacts, and all system-state sentinel files.

### Strengths
- Single source of truth design is correct and well-executed. Prior to this
  module (G1 work), each file constructed its own `Path(__file__).parent /
  "data" / ...` — any worktree or deployment layout change would require
  patching every file individually.
- `safe_io.project_root()` delegation is the right choice: worktree support
  requires the root to come from the main project, not `__file__`, and
  centralising that call here means only one place needs updating if the
  resolution logic changes.
- Names are unambiguous (`KILL_SWITCH_PATH`, `LOCK_PATH`,
  `RUNNING_FLAG_PATH`, etc.) — a reader calling `paths.KILL_SWITCH_PATH` can
  understand what file they are touching without digging through other modules.
- The comment on line 28 (`# System state — these live in data/ (verified
  against cron.py and watchdog.py)`) is exactly the right kind of annotation:
  it explains _why_ the choice was made and names the files that were checked.

### Weaknesses / Observations

**Missing: `execution_log` path.** There is no `EXECUTION_LOG_PATH` constant.
If `execution_log.py` constructs its own path, that module is not covered by
this single source of truth.  Confidence: Possible — execution_log.py may
derive its path internally or may not use a persistent file.

**Missing: `emos_train` output path.** `EMOS_PARAMS_PATH` is present; there is
no corresponding `EMOS_TRAIN_RESULTS_PATH` or similar. If training writes an
intermediate file before promoting to `emos_params.json`, that path is not
centralised here. Low severity; only matters when `emos-train` is run.

**No validation on `_project_root()` result.** If `safe_io.project_root()`
returns a path where `data/` does not exist (e.g. a fresh clone with no data
directory), every consumer silently holds a non-existent path and fails at first
`open()` — with no early error at import time. A startup check like
`assert _DATA.is_dir(), f"data/ directory not found at {_DATA}"` would catch
this earlier in the process lifecycle. Severity: LOW — the bot would fail loudly
when it first tries to open any file, so this is a DX/diagnostics gap rather
than a silent failure.

**No `__all__` export list.** Minor: a `__all__` would make the public surface
explicit and prevent consumers from accidentally importing `_ROOT` or `_DATA`
directly. No functional impact.

### Red Flags
NONE — no functions, no exception handling, no trading logic.

### Invariants
No applicable invariants (no functions, no DB queries, no lock usage, no Kelly
calls, no probability handling, no balance reads).

---

## Overall Module Score: 8/10

The module does exactly one thing and does it correctly. The worktree-aware
root delegation is non-obvious and correctly explained in the docstring and
inline comment. The only deductions are:

- −1: No `_DATA.is_dir()` guard at import time; first-open errors are
  misleading when the data directory is missing (non-obvious invariant, no
  comment explaining the assumption that `data/` exists).
- −1 cap reached: `execution_log` path may not be centralised here (Possible
  confidence — not confirmed without reading execution_log.py).

Median would be 7; the extra point is justified because the module is a
genuine quality-of-life improvement over the prior per-file path construction
pattern, and the worktree rationale is clearly documented.

**VERDICT: keep as-is.** Optional improvements: add `_DATA.is_dir()` assertion,
add `execution_log` path if that module uses a persistent file, add `__all__`.
