# MODULE: kalshi_client.py

## Before You Start
Read `tests/test_kalshi_client.py`, `tests/test_idempotency.py`, and
`tests/test_http.py` before grading.

## TIER 1 Functions
`_request_with_retry()`, `place_order()`, `_find_order_by_client_id()`,
`_check_key_permissions()`, `_sign_headers()`.

## TIER 2 Functions
Read-only API calls: `get_markets()`, `get_market()`, `get_orderbook()`,
`get_positions()`, `get_balance()`, `get_open_orders()`, `get_events()`,
`get_series_list()`, `get_order()`, `cancel_order()`, `place_maker_order()`.
Display helpers and validators.

## Acceptance Criteria
A function CANNOT score above 7 if it fails any of these.

- AC1: `place_order()` generates a `client_order_id` before the API call and calls
  `_find_order_by_client_id()` after a timeout or 5xx response to detect whether the
  order was actually placed. A timeout does not mean the order was not placed — a retry
  without checking would create a duplicate position.
- AC2: `_request_with_retry()` does NOT automatically retry POST requests without the
  duplicate-detection check above. Retry on GET is safe; retry on POST is not without
  idempotency verification.
- AC3: `_check_key_permissions()` verifies the private key file is readable only by
  the current user — a world-readable `kalshi_private_key.pem` is a security issue.
- AC4: `_sign_headers()` includes the correct HMAC components in the correct order. Any
  deviation from Kalshi's signing spec produces 401 errors.
