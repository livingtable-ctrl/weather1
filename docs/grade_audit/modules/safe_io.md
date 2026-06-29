# MODULE: safe_io.py

## Before You Start
Read `tests/test_safe_io.py` in full before grading any function.

## TIER 1 Functions
Every function in this file is TIER 1.

## Acceptance Criteria
A function CANNOT score above 7 if it fails any of these.

- AC1: `atomic_write_json` uses `os.replace()` not `os.rename()`. On Windows,
  `os.rename()` raises `FileExistsError` when the destination exists and is NOT atomic.
- AC2: Temp file is written to a uniquely-named path and is always cleaned up — even
  if an exception occurs between the write and the rename. The WinError 32 retry
  (Windows Defender scan delay) is intentional and self-healing; do NOT flag it.
- AC3: Every failure path logs at WARNING or above before returning or re-raising.

## Special Notes
The file is small. Grade every function at full TIER 1 depth regardless of size.
