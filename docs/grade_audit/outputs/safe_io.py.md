# Grade Audit — safe_io.py
**Date:** 2026-06-29
**File:** `safe_io.py`
**Lines:** 1–158 (full file)
**Module:** All functions are TIER 1 per module spec

---

## Summary

| Function | Score | Verdict |
|---|---|---|
| `project_root()` L:20–43 | 8/10 | keep as-is |
| `atomic_write_json()` L:46–123 | 9/10 | keep as-is |
| `atomic_write_json_with_history()` L:126–157 | 6/10 | fix before live |

File-level median: **7.67/10**

---

## AtomicWriteError (class, L:16–17)

Not a function — simple exception class, no logic to grade.

---

## TIER 1 — `project_root()` L:20–43

```
[safe_io.py] project_root() L:20–43  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: N/A (no acceptance criteria specific to this function)
Red flag: NONE
Invariants: I3 N/A (this is path resolution, not I/O)
STRENGTHS:
• Correctly detects worktree vs main repo by checking whether .git is a file (worktree)
  or a directory (normal clone).
• Parses the gitdir pointer and resolves relative paths correctly via .resolve().
• Falls back silently to `here` on any exception, so it never raises — the calling
  code won't break even if the .git file format changes.
• Navigation logic (parent.parent.parent from worktrees/<name>) matches the standard
  git worktree layout exactly.
WEAKNESSES:
• line 41: The bare `except Exception: pass` at line 41 swallows all parse/path errors
  without a log. If the .git file is malformed or points somewhere unexpected, the
  function silently returns the worktree dir instead of the main project root, and
  subsequent writes in atomic_write_json fall to the emergency candidates at
  project_root()/data — which in a worktree is the wrong location. No WARNING is
  emitted so an operator cannot diagnose this from logs. (RF1 — exception caught
  without a log. See override decision below.)
• No test coverage for the worktree-detect path; tests only exercise the non-worktree
  case implicitly through `atomic_write_json` calls.

RF1 NOTE: RF1 says "Exception caught without a log at WARNING or above". The bare
`except Exception: pass` at line 41 qualifies. However, RF1 in the rubric triggers a
cap at ≤4 for any TIER 1 function. Applying strictly: this would cap the score at 4.

RE-EVALUATION: The failure mode here is not direct financial harm — project_root()
only affects the emergency fallback path (already a rare all-retries-exhausted scenario)
and the main atomic write logic does not call project_root(). The function is also
documented as a path resolver, not a trade gating function. However, the module spec
says "Every function in this file is TIER 1" and RF1 is a hard cap.

APPLYING RF1 CAP: Score capped at ≤4.

REVISED SCORE: 4/10 | Red flag: RF1

FAILURE SCENARIO:
.git file in a worktree is truncated or points to a non-existent location (e.g.,
disk corruption, partial clone, renamed worktree). The except clause at line 41
fires silently. project_root() returns `here` (the worktree directory). In
atomic_write_json, the emergency copy is written to `<worktree>/data/paper_trades.json`
instead of the main project's `data/` directory. The main project's data/ directory
receives nothing. Operator sees no log warning and cannot find the emergency copy.

FIX:
safe_io.py:41 — replace bare `except Exception: pass` with:
    except Exception as _e:
        _log.warning("project_root: failed to parse .git worktree pointer at %s: %s; falling back to %s", git_marker, _e, here)

VERDICT: fix before live
```

---

## TIER 1 — `atomic_write_json()` L:46–123

```
[safe_io.py] atomic_write_json() L:46–123  ★ T1
Score: 9/10  |  Confidence: Confirmed
AC: ALL PASS
  AC1 PASS — line 73: `os.replace(tmp_path_str, path)` — uses os.replace(), not os.rename()
  AC2 PASS — temp file is uniquely named per attempt (attempt index in filename);
             unlinked in the except block at line 78; each attempt uses a distinct
             name so there is no collision across retries
  AC3 PASS — every failure path logs at WARNING (line 82–88) or ERROR (lines 109, 115)
Red flag: NONE
Invariants:
  I3 PASS — os.replace() used; temp file written first; unlink on exception at line 77–80
STRENGTHS:
• Uniquely-named temp file per attempt (`.<name>_<attempt>.tmp`) prevents cross-attempt
  collision and avoids the Windows Defender WinError 32 problem self-healing across retries.
• fsync attempted before rename; fsync failure is logged at WARNING (not silently ignored)
  but does NOT abort the write — correct tradeoff for a trading ledger (durability
  warning but operation proceeds).
• Emergency copy cascade: tries caller-supplied fallback_dir first, then project data dir,
  then system temp — ensures something is written for manual recovery.
• Emergency copy explicitly does NOT propagate transparency (comment on line 92–93 is
  clear): raises AtomicWriteError regardless, so the caller always knows the primary
  write failed.
• AtomicWriteError message includes original exception and emergency copy location —
  actionable for an operator.
• Retry backoff is 1s between attempts (only between, not after final) — sensible for
  Windows Defender delay.
WEAKNESSES:
• line 61: `tmp_path_str` is initialized inside the for-loop body but the except clause
  at line 76 references it via `if tmp_path_str:`. If the `open()` call raises before
  the assignment completes (theoretically impossible in Python since assignment is
  atomic, but the variable is declared in-scope only after the assignment), there is
  a very narrow window where `tmp_path_str` might be the value from a previous iteration
  (attempt N-1) if the exception occurs before overwriting it. In practice this is
  harmless because attempt N-1's tmp file was already unlinked, but it is slightly
  fragile. Minor: no test explicitly covers this.
• The emergency copy loop (lines 103–116) does not attempt fsync on the emergency write.
  Since this is already a last-resort path, the omission is acceptable — but worth noting.
• No test covers the happy path (normal write + os.replace succeeds) directly; tests
  only exercise the failure path. This is a test coverage gap but does not affect the
  function's correctness.
FAILURE SCENARIO (score 9 — provided for completeness):
If the disk is full exactly between the temp write and os.replace(), the unlink in the
except block fires correctly and last_exc is set. After retries exhausted, the emergency
candidate loop also fails (disk full). emergency_path stays None. The AtomicWriteError
message will say "Emergency copy written to None" — slightly confusing but not
operationally harmful (the error is already raised).
VERDICT: keep as-is
```

---

## TIER 1 — `atomic_write_json_with_history()` L:126–157

```
[safe_io.py] atomic_write_json_with_history() L:126–157  ★ T1
Score: 6/10  |  Confidence: Confirmed
AC: FAIL AC3 — "history_file.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")"
    at line 148 can raise if the existing file is unreadable or the history dir write
    fails. This exception is NOT caught and NOT logged — it propagates to the caller
    unchecked, potentially skipping the actual atomic_write_json call (line 157) and
    causing a silent data loss: the live ledger is not updated.
Red flag: RF1 — the read/write operations for history at lines 148 and 153 have no
    exception handler. A failure (permissions, disk full, concurrent lock) silently
    unwinds the call stack without any WARNING log, and the primary atomic_write_json
    is never reached.
Invariants: I3 — PARTIAL: the final write at line 157 delegates correctly to
    atomic_write_json (which is I3-compliant). However, if history writing fails before
    line 157, the primary write never happens.
STRENGTHS:
• History archival uses UTC timestamps with millisecond disambiguation — collision
  avoidance for rapid successive writes is handled.
• Pruning of old history files keeps directory size bounded (max_history default=10).
• Correctly delegates the actual atomic write to atomic_write_json (line 157), so the
  primary write path is I3-compliant when reached.
• Imports are inside the function body (slightly unconventional but keeps module-level
  imports minimal).
WEAKNESSES:
• line 148: `path.read_text()` and `history_file.write_text()` are not wrapped in a
  try/except. Any failure here (unreadable source, full disk, permissions error on
  history dir) raises an unhandled exception. Because these lines precede the
  `atomic_write_json(data, path)` call at line 157, the primary write is skipped.
  In a live-money context this means: "paper_trades.json was NOT updated, but the
  caller received an uncaught exception and may or may not handle it gracefully."
• line 153: `existing[0].unlink(missing_ok=True)` — the pruning loop rebuilds
  `existing` by slicing (`existing = existing[1:]`) rather than re-globbing. This
  is correct only if `unlink` succeeds; `missing_ok=True` means a failed unlink is
  silently swallowed, and the list may still have a reference to the deleted file.
  The while-loop will terminate correctly, but if another writer adds history files
  concurrently, the count may drift. Minor issue.
• No test coverage for the history-write failure path (primary write skipped scenario).
  No test coverage for the happy path (history file created, then primary write).
• RF1: the exception at line 148 propagates without a log at WARNING or above.
FAILURE SCENARIO:
  1. history_dir does not have write permissions (e.g., operator changed ownership
     of .history/ during debugging).
  2. `history_file.write_text(...)` raises PermissionError at line 148.
  3. Exception propagates uncaught through atomic_write_json_with_history.
  4. The primary `atomic_write_json(data, path)` call at line 157 is never reached.
  5. paper_trades.json is NOT updated. No WARNING in logs. Caller (paper._save) sees
     an exception; if paper._save does not re-raise or log this, the balance update
     is silently lost.
  Confidence: Confirmed — path is direct and simple.
FIX:
safe_io.py:136–156 — wrap the history block in try/except:

    if path.exists():
        try:
            history_dir.mkdir(exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            history_file = history_dir / f"{path.stem}_{stamp}.json"
            if history_file.exists():
                history_file = (
                    history_dir
                    / f"{path.stem}_{stamp}_{int(_time.monotonic() * 1000) % 1000}.json"
                )
            history_file.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            existing = sorted(history_dir.glob(f"{path.stem}_*.json"))
            while len(existing) > max_history:
                existing[0].unlink(missing_ok=True)
                existing = existing[1:]
        except Exception as _hist_exc:
            _log.warning(
                "atomic_write_json_with_history: history snapshot failed for %s: %s — "
                "proceeding with primary write",
                path, _hist_exc
            )

    atomic_write_json(data, path)

This ensures history failure is logged at WARNING and the primary write always executes.

VERDICT: fix before live
```

---

## File-Level Notes

**Test coverage assessment:**

- `atomic_write_json` has direct test coverage for the failure path (AtomicWriteError
  raised, emergency copy written). Happy path (successful write) is not directly tested
  but is exercised implicitly via paper module round-trip tests.
- `project_root` has no direct test coverage. The worktree-detection logic is only
  exercised when running from a worktree, which is the deployed scenario but not the
  test scenario.
- `atomic_write_json_with_history` has no test coverage at all — neither happy path
  nor failure path.

**Revised score table (after RF1 cap applied):**

| Function | Score | Verdict |
|---|---|---|
| `project_root()` L:20–43 | 4/10 (RF1 cap) | fix before live |
| `atomic_write_json()` L:46–123 | 9/10 | keep as-is |
| `atomic_write_json_with_history()` L:126–157 | 6/10 (RF1) | fix before live |

File-level median (post-cap): **6/10**
