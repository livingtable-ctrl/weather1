# MODULE: circuit_breaker.py

## Before You Start
Read `tests/test_circuit_breaker.py` and `tests/test_flash_crash_cb.py` before grading.

## TIER 1 Functions
All functions that change or read OPEN/HALF-OPEN/CLOSED state, and the function that
blocks requests when OPEN.

## Acceptance Criteria
A function CANNOT score above 7 if it fails any of these.

- AC1: State OPEN actually blocks all order placement requests — not just logs a
  warning. A circuit breaker that logs but proceeds is not a circuit breaker.
- AC2: HALF-OPEN state allows exactly one probe request through, and transitions back
  to CLOSED only if the probe succeeds. If the probe fails, it must return to OPEN.
- AC3: The burst window correctly absorbs parallel failures as a single event. Rapid
  simultaneous failures from a single API outage should count as 1 failure event, not N.
  Otherwise a burst would permanently trip the breaker.
- AC4: Thresholds (`failure_threshold`, `recovery_timeout`) are read from `.env` or
  config, not hardcoded. If hardcoded: flag INFO and note the operational impact.
