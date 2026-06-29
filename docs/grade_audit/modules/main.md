# MODULE: main.py

## CRITICAL — File Size Warning
This file is 7,394 lines. You MUST read it in 2,000-line chunks before grading.
Read(offset=0, limit=2000) → Read(offset=2000, limit=2000) → keep going until EOF.
Do not begin grading any function until you have finished reading every line.

## Before You Start
Read `tests/test_main_cron_smoke.py`, `tests/test_graduation_gate.py`, and
`tests/test_infrastructure.py` before grading.

## TIER 1 Functions
Only these specific functions get full TIER 1 treatment:
`cmd_cron()`, `cmd_settle()`, `validate_env()`, `_build_cron_context()`,
`build_client()`.

Also grade the `load_dotenv()` call as a file-level finding (it is not a function but
it has a correctness requirement — see AC1).

## TIER 2 Functions
All others — display helpers (`_header()`, `_kv()`, `_brier_sparkline()`,
`_ascii_chart()`, `_format_expiry()`), all menu-display functions, all admin commands
that only display or reset state, all internal CLI wrappers.

With 89 functions in this file, most are TIER 2. Do not apply full TIER 1 analysis to
display helpers.

## Acceptance Criteria
A TIER 1 function CANNOT score above 7 if it fails any of these.

- AC1 (file-level): `load_dotenv()` is called BEFORE any local module import.
  Module-level constants like `paper.MAX_DRAWDOWN_FRACTION` are set at import time —
  if `load_dotenv()` runs after the import, `.env` overrides have no effect.
  Verify the exact line order in the file header.
- AC2: `pyproject.toml` (or `ruff.toml`) has `E402` suppressed for `main.py` to avoid
  lint violations from the intentional import ordering.
- AC3: Any display code showing `< 0.20` as the graduation Brier threshold is stale —
  the actual gate is `≤ 0.23`. Flag stale display code as LOW/INFO. Do not flag the
  gate itself (which lives in `paper.graduation_check()`).
- AC4: `validate_env()` checks all required `.env` keys and fails fast with a clear
  error before any trade-path code runs.
- AC5: `cmd_cron()` does not catch broad `Exception` at the top level in a way that
  would suppress a crash and leave the bot appearing to run when it is not.
