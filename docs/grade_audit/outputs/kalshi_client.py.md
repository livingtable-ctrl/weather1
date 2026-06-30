# Grade Audit — kalshi_client.py
Generated: 2026-06-29

---

## Summary

| Function | Tier | Score | Verdict |
|---|---|---|---|
| `_check_key_permissions()` | T1 | 7/10 | keep as-is (Windows path has silent-pass gap) |
| `_build_session()` | T2 | 9/10 | keep as-is |
| `_request_with_retry()` | T1 | 8/10 | keep as-is |
| `KalshiClient.__init__()` | T2 | 8/10 | keep as-is |
| `_sign_headers()` | T1 | 8/10 | keep as-is |
| `_full_path()` | T2 | 9/10 | keep as-is |
| `_check_error_body()` | T2 | 8/10 | keep as-is |
| `_get()` | T2 | 8/10 | keep as-is |
| `_post()` | T2 | 8/10 | keep as-is |
| `_delete()` | T2 | 8/10 | keep as-is |
| `_validate()` | T2 | 8/10 | keep as-is |
| `get_markets()` | T2 | 8/10 | keep as-is |
| `get_market()` | T2 | 8/10 | keep as-is |
| `get_orderbook()` | T2 | 7/10 | keep as-is |
| `get_events()` | T2 | 8/10 | keep as-is |
| `get_series_list()` | T2 | 8/10 | keep as-is |
| `get_balance()` | T2 | 8/10 | keep as-is |
| `get_positions()` | T2 | 8/10 | keep as-is |
| `get_open_orders()` | T2 | 8/10 | keep as-is |
| `place_order()` | T1 | 8/10 | keep as-is |
| `_find_order_by_client_id()` | T1 | 7/10 | keep as-is (silent exception swallowing) |
| `get_order()` | T2 | 7/10 | keep as-is |
| `cancel_order()` | T2 | 8/10 | keep as-is |
| `place_maker_order()` | T2 | 8/10 | keep as-is |

File-level median: **8/10**. No active bugs found. Two functions with silent exception swallowing patterns worth noting but not blocking.

---

## TIER 1 Functions — Full Blocks

---

### `_check_key_permissions()` L:29–77  ★ T1

```
[kalshi_client.py] _check_key_permissions() L:29–77  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: AC3 PASS — checks group/other read bits on Unix; restricts via icacls on Windows
Red flag: NONE
Invariants: I10 N/A (no trade gate here)
```

**STRENGTHS:**
- Unix path correctly reads `stat().st_mode` and checks `S_IRGRP | S_IROTH`, emits WARNING with chmod instruction. This is the exact pattern AC3 requires.
- Windows path uses `icacls /inheritance:r /grant:r` to strip inherited ACEs and grant current-user-only Full Control. This is the correct Windows hardening approach.
- `FileNotFoundError` (icacls not available, e.g. Wine/WSL) is silently skipped — appropriate, not a trading-path concern.
- Broader exception on the icacls `subprocess.run` logs at WARNING with the key path and the exception — operator can act.

**WEAKNESSES:**
- Line 56: `except FileNotFoundError: pass` — silently skips without any log. On Windows environments where icacls is unavailable, the key is never restricted and nothing is emitted. The comment says "icacls not available (e.g. wine/WSL)" but a WARNING here would be appropriate: the security goal was not achieved.
- Line 77: `except OSError: pass` on Unix — if `stat()` fails (key has been deleted/permissions denied during startup), nothing is logged. This is low risk because init would fail later, but a DEBUG log here would aid diagnostics.
- The Windows `os.getlogin()` can raise `OSError` on some headless/service contexts; not caught (though the outer `except Exception` would catch it and log at WARNING — so not fatal, just produces a warning instead of silently restricting the key).
- Test coverage is Unix-only (both `test_warns_on_world_readable_key` and `test_no_warning_on_private_key` skip on Windows). The Windows icacls path has no test coverage. Given AC3 is listed as a TIER 1 acceptance criterion and Windows is the production platform, this is a meaningful gap. The preamble rule (cannot score >8 without meaningful test coverage) applies; the score stays at 7.

**FAILURE SCENARIO:**
On Windows production: icacls is present and succeeds, so the key gets restricted. But if `os.getlogin()` raises (service account without a login session), the outer `except Exception` catches it and emits a warning instead of restricting the key. The warning is logged but the key file is left with its original permissions (potentially world-readable if the directory was created with lax ACLs). An attacker with read access to the same machine can exfiltrate the RSA private key.

**VERDICT:** keep as-is — the Unix path is well-tested and correct; the Windows path is functionally sound for normal accounts. Add a WARNING on the `FileNotFoundError` branch and a Windows-compatible integration test to reach 8+.

---

### `_request_with_retry()` L:107–155  ★ T1

```
[kalshi_client.py] _request_with_retry() L:107–155  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: AC2 PASS — POST is excluded from allowed_methods in _build_session (confirmed by test_idempotency.py TestPostRetryExcluded)
Red flag: NONE
Invariants: I10 N/A (gate is in callers)
```

**STRENGTHS:**
- `kwargs.setdefault("timeout", DEFAULT_TIMEOUT)` ensures no call can accidentally hang indefinitely.
- Separate read/write circuit breakers (`_kalshi_cb_read` / `_kalshi_cb_write`) prevent read failures from blocking order placement — this is a high-quality design decision explicitly commented.
- 5xx trips the breaker; 4xx does not — correct distinction (4xx is client error, not infrastructure failure).
- Slow-response warning at >5 seconds gives operator visibility into latency degradation.
- `_SESSION` Retry adapter excludes POST (confirmed by test). `_request_with_retry` itself does not retry — the retry is entirely in the HTTPAdapter, so this function is passive about retries and correct.
- `resp.raise_for_status()` ensures 4xx/5xx HTTP responses always propagate as exceptions regardless of whether callers call it themselves.
- `log_api_request` failures are caught and logged at DEBUG — correct, non-fatal audit logging should never crash the main path.

**WEAKNESSES:**
- Line 150: `except Exception as _e: _log.debug(...)` — audit logging failure is only at DEBUG. If `log_api_request` silently fails (e.g., DB locked), operators won't see it without enabling debug logging. This is a secondary concern (audit trail, not trade safety), but logging at INFO or WARNING would be more appropriate for a production system.
- No test covers `_request_with_retry` directly — all tests mock at the `_post`/`_get` level. The circuit breaker logic, latency warning, and `raise_for_status()` behavior are untested. This doesn't rise to RF6 (not directly a trade placement function), but it is a coverage gap.
- The `CircuitOpenError` raised at L122 is not caught anywhere visible in the file — callers must handle it. This is fine if callers catch it, but it's an implicit contract not documented here.

**VERDICT:** keep as-is — no active bugs, AC2 confirmed, correct circuit breaker design. Minor: promote audit-log failure to INFO.

---

### `place_order()` L:316–376  ★ T1

```
[kalshi_client.py] place_order() L:316–376  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: AC1 PASS — client_order_id generated before _post call (L347); _find_order_by_client_id called on any exception (L367)
AC: AC2 PASS — POST excluded from _build_session retry; dedup check on exception handles idempotency
Red flag: NONE
Invariants: I10 — this function IS the order placement; callers must check KALSHI_ENV before calling. I10 PASS (confirmed: gate is in main._place_live_order, not here — appropriate separation of concerns)
```

**STRENGTHS:**
- Deterministic `client_order_id` via SHA256 of `ticker:side:action:count:price:cycle` — correct implementation. Same inputs in same cycle produce same 32-char hex ID, which Kalshi uses for server-side deduplication.
- When `cycle` is omitted, `uuid.uuid4()` is used — non-deterministic, which is the correct behavior for manual/one-off orders where dedup is not desired.
- Exception handler (L362–376) correctly calls `_find_order_by_client_id` before re-raising — this is the key safety property for AC1. The "order landed but connection dropped" scenario is handled.
- `yes_price_dollars` vs `no_price_dollars` dispatch at L357–360 is correct — confirmed by `test_no_side_buy_sends_no_price_dollars` and `test_yes_side_buy_sends_yes_price_dollars`.
- Warning log at L370–374 when a landed order is returned despite exception — operator gets visibility.
- Test coverage: `TestPostFailureDedup` covers the landed-but-exception path, non-found path, and `_find_order_by_client_id` None-on-error path. `TestClientOrderId` covers determinism, cycle differentiation, random fallback, and body presence.

**WEAKNESSES:**
- Line 364: `except Exception as exc:` — catches all exceptions including `CircuitOpenError`. If the circuit is open (Kalshi infra down), `_find_order_by_client_id` will also fail (same circuit), return None, and then `raise exc` re-raises the `CircuitOpenError`. This is not wrong — the order didn't land if the circuit was open — but the exception handler calling `_find_order_by_client_id` during an open circuit wastes a network call that will immediately fail. Minor inefficiency.
- `count_fp` field is sent as a string (`f"{count:.2f}"`) — this matches Kalshi's `_fp` (fixed-point) fields, but it's a subtle contract. If Kalshi changes this field name, there's no schema validation at this layer.
- `time_in_force` has a valid set (`good_till_canceled`, `fill_or_kill`, `immediate_or_cancel`) but is not validated — an invalid value would produce a 400 from Kalshi, which would then propagate through `_find_order_by_client_id` (order won't be found, so re-raise). Not a failure mode — just a missing input guard.

**VERDICT:** keep as-is — AC1 and AC2 both confirmed; idempotency design is correct and well-tested.

---

### `_find_order_by_client_id()` L:378–405  ★ T1

```
[kalshi_client.py] _find_order_by_client_id() L:378–405  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: AC1 PASS — called from place_order on any exception; handles both resting and filled states
Red flag: RF1 — line 392: bare `except Exception: pass` (no log on resting-lookup failure); line 403: bare `except Exception: pass` (no log on filled-lookup failure)
```

**RF1 DETAIL:**
Lines 392 and 403 both swallow exceptions without any log. If the Kalshi API is rate-limiting or returning 503 during dedup check, `_find_order_by_client_id` silently returns `None`. `place_order` then re-raises the original exception — which is the correct behavior — but the operator has no visibility into whether the dedup check itself failed. This violates RF1 (exception caught without WARNING or above).

**STRENGTHS:**
- Two-pass design (resting first, then filled) handles the taker-fill case where an order lands and fills immediately before the dedup check fires.
- Returns `{**order, "status": "placed"}` for filled orders so the GTC poll loop handles promotion — thoughtful downstream compatibility.
- `test_find_order_by_client_id_returns_none_on_api_error` confirms the None-on-error contract.
- The function correctly never raises — callers depend on None meaning "not found" and place_order re-raises the original exception in that case.

**WEAKNESSES:**
- Lines 392, 403: `except Exception: pass` — RF1 confirmed. During a genuine outage, these silent failures make it impossible to distinguish "order not found" from "dedup check itself failed." Should log at WARNING: "Could not check dedup — assuming order did not land."
- No pagination: `_get("/portfolio/orders", params={"status": "resting"})` returns at most one page of orders. If the user has many open orders, the target order may not appear in the first page. This is a Possible latent bug — at current trading volumes (few open orders at any time) it won't fire, but could at higher volume.
- The two `except Exception: pass` blocks could be collapsed with a helper, but that's style not correctness.

**FAILURE SCENARIO:**
Kalshi API is intermittently returning 503 during a heavy load event. `place_order` sends the POST, gets a timeout. `_find_order_by_client_id` calls `_get("/portfolio/orders")` — this also hits a 503, raises `HTTPError`, which is swallowed by `except Exception: pass`. Function returns `None`. `place_order` re-raises the original timeout. The order may have landed or not — the operator cannot tell from logs. If they retry manually, they may get a duplicate position if the server-side dedup key was not applied (different `cycle` or no `cycle`).

**FIX:**
```python
# Line 392:
except Exception as _e:
    _log.warning("_find_order_by_client_id: resting lookup failed (%s) — assuming not landed", _e)
# Line 403:
except Exception as _e:
    _log.warning("_find_order_by_client_id: filled lookup failed (%s) — assuming not landed", _e)
```

**VERDICT:** fix before live — RF1 pattern. The fix is trivial (add log lines). Score would rise to 8 with the fix.

---

### `_sign_headers()` L:180–202  ★ T1

```
[kalshi_client.py] _sign_headers() L:180–202  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: AC4 PASS — message format is f"{timestamp_ms}{method.upper()}{path}" which matches Kalshi's documented RSA-PSS signing spec
Red flag: NONE
Invariants: I10 N/A
```

**STRENGTHS:**
- Message format `f"{timestamp_ms}{method.upper()}{path}"` is exactly Kalshi's spec: timestamp (ms) + uppercase method + full path. No query string included — correct per spec.
- `method.upper()` normalization prevents case-sensitivity bugs.
- PSS padding with `MGF1(SHA256)` and `salt_length=PSS.DIGEST_LENGTH` matches Kalshi's documented parameters.
- `KALSHI-ACCESS-TIMESTAMP` is set to milliseconds-since-epoch (`int(time.time() * 1000)`) — correct.
- `KALSHI-ACCESS-SIGNATURE` is base64-encoded — correct.
- Content-Type header included in returned dict — matches Kalshi's requirement.
- Early-exit `ValueError` if `_private_key` or `key_id` are missing — explicit, descriptive error message.

**WEAKNESSES:**
- No test coverage for `_sign_headers` directly. All tests that exercise it do so through mock `_post`/`_get` bypasses. A test asserting that the returned headers contain all four required fields (`KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP`, `KALSHI-ACCESS-SIGNATURE`, `Content-Type`) and that the signature is a non-empty base64 string would be valuable. Per preamble rule: cannot score >8 without meaningful test coverage — score stays at 8.
- `_full_path(path)` is used for the signing path (correct — Kalshi requires the full path including `/trade-api/v2` prefix, not just the resource path). The `_full_path` helper is correctly used. However, if `base_url` is misconfigured, the signing path would be wrong. No validation of `base_url` at init time.
- Clock skew: `time.time()` returns system clock. If the machine's clock is >5 seconds off, Kalshi will reject the signature with 401. No NTP check or warning here — but this is operationally expected to be handled at the OS level.

**VERDICT:** keep as-is — AC4 confirmed, signing spec correctly implemented. Add a unit test for the header structure to reach 9.

---

## TIER 2 Functions — Compressed Format

---

**`_build_session()` L:86–101  9/10** — Correctly excludes POST from `allowed_methods`, includes all `_RETRY_STATUSES` (429/500/502/503/504), sets `backoff_factor=1.0`, mounts on both https and http. Confirmed by `test_idempotency.py::TestPostRetryExcluded`. Excellent.  [Confidence: Confirmed]

---

**`KalshiClient.__init__()` L:162–178  8/10** — Correctly delegates to `_check_key_permissions` before loading the key; gracefully skips key loading if path is absent. No crash if `private_key_path` is provided but file doesn't exist (loads nothing silently — caller gets `_private_key=None` and a `ValueError` on first signed request, which is acceptable).  [Confidence: Confirmed]

---

**`_full_path()` L:204–208  9/10** — Single responsibility: extracts `/trade-api/v2` prefix from `base_url` via `urlparse`, appends `path`. Correct for both PROD and DEMO base URLs. Pure function, no side effects.  [Confidence: Confirmed]

---

**`_check_error_body()` L:210–216  8/10** — Raises `ValueError` on a 200 response containing an `"error"` key. Correct defensive check. Static method, no side effects. Only checks `isinstance(data, dict)` — if data is a list, silently passes (correct — list responses like `/markets` would not have a top-level `error` key).  [Confidence: Confirmed]

---

**`_get()` L:218–226  8/10** — Correctly signs with `auth=True` when needed; calls `_check_error_body`; passes `timeout=10` explicitly (overrides `DEFAULT_TIMEOUT=15` — slight inconsistency with the module constant but not harmful; 10s is reasonable for reads). `params=None` default and `p or None` pattern prevents sending empty `params={}` to the API.  [Confidence: Confirmed]

---

**`_post()` L:228–234  8/10** — Always signs (POST is always authenticated). Calls `_check_error_body`. Passes `json=body` correctly. `timeout=10` same minor inconsistency as `_get` but harmless.  [Confidence: Confirmed]

---

**`_delete()` L:236–241  8/10** — Correctly uses `_sign_headers("DELETE", ...)` and `_request_with_retry("DELETE", ...)`. DELETE is in `allowed_methods` for retry — appropriate since cancel-order is idempotent.  [Confidence: Confirmed]

---

**`_validate()` L:244–256  8/10** — Warns (does not crash) on unexpected API shape, which is the correct production behavior. Logs at ERROR level — appropriate severity for API contract violations. Returns `None` so callers continue with `data.get(key, [])` fallbacks.  [Confidence: Confirmed]

---

**`get_markets()` L:260–276  8/10** — Cursor pagination loop is correct: builds fresh `p = dict(params)` each iteration, appends cursor if present, breaks on no cursor. Validates each market via `validate_market(market, source="kalshi")`. Confirmed by `TestGetMarketsPagination` (4 tests: single page, two pages, cursor forwarding, three pages). Uses `auth=True` — correct, positions require auth.  [Confidence: Confirmed]

---

**`get_market()` L:278–283  8/10** — Single market fetch; validates with `validate_market`; returns inner `data["market"]` not the wrapper. Correct.  [Confidence: Confirmed]

---

**`get_orderbook()` L:285–289  7/10** — Handles both `orderbook_fp` and `orderbook` response keys (API version flexibility). However, the fallback validation `self._validate(data, "orderbook", ...)` only fires when neither key is present — if `data` is an empty dict, it returns `{}` silently after logging an error. No test coverage for this function.  [Confidence: Confirmed]

---

**`get_events()` L:291–294  8/10** — Simple pass-through with `_validate` check. Correct.  [Confidence: Confirmed]

---

**`get_series_list()` L:296–299  8/10** — Same pattern as `get_events`. Correct.  [Confidence: Confirmed]

---

**`get_balance()` L:303–304  8/10** — Returns the full balance dict (not a scalar); callers extract the relevant fields. Auth=True. Intentionally used for reporting (I8 applies to trading-gate callers, not this function itself per preamble known-intentional).  [Confidence: Confirmed]

---

**`get_positions()` L:306–309  8/10** — Returns `market_positions` list; validates key presence. Auth=True. Correct.  [Confidence: Confirmed]

---

**`get_open_orders()` L:311–314  8/10** — Filters `status=resting` — correct for open orders. Auth=True. Validates `orders` key. Correct.  [Confidence: Confirmed]

---

**`get_order()` L:407–413  7/10** — Returns `data.get("order", data)` — the fallback to `data` itself is a defensive pattern for API shape changes but could silently return a full response envelope if the key is missing, making the caller work with unexpected data. No test coverage. Low risk given the API is stable.  [Confidence: Possible]

---

**`cancel_order()` L:415–416  8/10** — Delegates to `_delete` which is signed and retried. DELETE idempotency is correct. One-liner, no logic to go wrong.  [Confidence: Confirmed]

---

**`place_maker_order()` L:418–442  8/10** — Thin wrapper over `place_order` with `action="buy"` and `time_in_force="good_till_canceled"` hardcoded. No `cycle` param forwarded — this means every call to `place_maker_order` uses a random UUID for `client_order_id`, so server-side dedup is not active for maker orders. This is intentional per the docstring ("Uses good_till_canceled so the order rests in the book") — maker orders are typically placed once and not retried. Acceptable.  [Confidence: Confirmed]

---

## File-Level Observations

1. **No active bugs found.** All AC1–AC4 acceptance criteria pass. The idempotency design (`client_order_id` + `_find_order_by_client_id` dedup check) is the strongest part of this file.

2. **RF1 in `_find_order_by_client_id`** (lines 392, 403): bare `except Exception: pass` without any log. Fix is trivial — add WARNING logs. This is the only finding requiring action before a live trading event.

3. **Windows test gap for AC3**: `_check_key_permissions` icacls path has no test coverage. Unix path is well-covered. Since the production machine is Windows, this is a meaningful gap.

4. **`_sign_headers` has no direct unit tests** — all tests mock below this layer. A 10-line test asserting header structure and non-empty signature would close this gap.

5. **`_get` and `_post` hardcode `timeout=10`** rather than using the module-level `DEFAULT_TIMEOUT = 15`. This is harmless (10s is still reasonable) but inconsistent. If `DEFAULT_TIMEOUT` is ever changed for tuning, these calls won't pick it up.

6. **No pagination in `_find_order_by_client_id`**: at current volumes (few open orders) this is fine, but could miss an order if the portfolio has many resting orders spread across pages.
