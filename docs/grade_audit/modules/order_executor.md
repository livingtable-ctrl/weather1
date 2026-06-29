# MODULE: order_executor.py

## Before You Start
Read `tests/test_execution_proof.py`, `tests/test_execution_stability.py`, and
`tests/test_dedup.py` before grading.

## TIER 1 Functions
The local `place_order()` wrapper, `record_paper_trade()`, and any function that
writes to `paper_trades.json` or calls the Kalshi client.

## Acceptance Criteria
A function CANNOT score above 7 if it fails any of these.

- AC1: `record_paper_trade()` is called ONLY after the Kalshi API returns a success
  response. A failed API call (non-2xx, timeout, network error) must not create a
  phantom position in `paper_trades.json`.
- AC2: Every paper trade record written includes: `days_out`, `close_time`, `cost`,
  `side`. Missing `days_out` breaks same-day/multi-day separation downstream.
- AC3: The retry path cannot create a duplicate position — either the client_order_id
  is checked (via `_find_order_by_client_id`) or the record is written only after
  confirmed success with no subsequent retry.
- AC4: `_sameday_effective_cap()` is present and dormant (intentional — threshold not
  yet reached at ~99 same-day trades; activates at 150). Do NOT flag as dead code. Do
  NOT flag as missing. Score it as DORMANT.
