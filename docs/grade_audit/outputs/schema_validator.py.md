# Grade Audit — schema_validator.py

**File:** `schema_validator.py`
**Lines:** 157
**Tier:** TIER 2 (utility/validation helpers — no direct trade placement, sizing, or settlement)
**Graded:** 2026-06-29

---

## Function Index

| Function | Lines | Tier | Score |
|---|---|---|---|
| `_price_to_decimal()` | 14–20 | T2 | 8/10 |
| `validate_market()` | 23–98 | T2 | 5/10 |
| `validate_forecast()` | 101–131 | T2 | 7/10 |
| `validate_nws_response()` | 134–157 | T2 | 5/10 |

---

## TIER 2 Function Grades

**[schema_validator.py] `_price_to_decimal()` L:14–20  8/10 — Clean normalization with silent None-return on bad input; the `f > 1.0` heuristic correctly handles Kalshi's 0–100 cent scale, but `f == 1.0` (a valid 1¢ bid in cent terms) is misclassified as already-decimal and returned as 0.01 rather than 0.0001 — extremely rare in practice.**  [Confidence: Confirmed]

---

**[schema_validator.py] `validate_market()` L:23–98  5/10 — Price range violations (out-of-range bid/ask) are logged at DEBUG not WARNING, so a corrupted market price entering the trade path produces no operator-visible log; only the inverted-spread check is WARNING-level, meaning silent bad prices can pass through with `ok=False` returned but no alert.**  [Confidence: Confirmed]

FIX: `schema_validator.py:73` — change `_log.debug(` to `_log.warning(` for the bid out-of-range block; `schema_validator.py:81` — same change for the ask out-of-range block.

Details:
- Lines 73–79: `_log.debug("schema_validator[%s]: %s yes_bid %.4f out of range …")` — this is a price integrity failure, not a debug trace. An out-of-range bid means the market data is corrupt or the API format changed. Callers that receive `ok=False` may still pass the data along if they don't treat the return value as a hard block.
- The type-check in `alias_fields` (lines 46–48) is effectively a no-op: the comment says "type check skipped" and the `pass` never validates the actual type. The `expected_type` variable in the alias loop is computed but never used, which is misleading.
- No test coverage found for this function.

FAILURE SCENARIO: Kalshi API returns `yes_bid=0` (market at zero, fully resolved) — `_price_to_decimal(0)` returns `0.0`, fails the `0.0 < bid < 1.0` check, logs at DEBUG (invisible in production), returns `ok=False`. If the caller ignores the return value or treats it as a soft warning, a resolved market with a 0 price enters the signal pipeline. Since the failure is silent at WARNING level, the operator cannot distinguish this from normal operation by watching logs.

---

**[schema_validator.py] `validate_forecast()` L:101–131  7/10 — Correctly checks presence and type of `temperature_2m_max` and `time`; logs at WARNING on violations; minor gap: allows `temperature_2m_max` to be `None` (type union includes `type(None)`) without checking whether the caller handles a None list, and does not check that `time` and `temperature_2m_max` have matching lengths when both are lists.**  [Confidence: Confirmed]

---

**[schema_validator.py] `validate_nws_response()` L:134–157  5/10 — The type-mismatch branch (lines 147–155) logs at WARNING but does NOT set `ok = False`, so a `properties` field with the wrong type silently returns `True` — the function reports valid when the response structure is broken.**  [Confidence: Confirmed]

FIX: `schema_validator.py:155` — add `ok = False` after the `_log.warning(…)` call in the `elif not isinstance(val, expected_type):` block (the line is present in `validate_forecast()` at L:130 but is missing here).

FAILURE SCENARIO: NWS API changes response structure and `properties` arrives as a list instead of a dict. The `elif not isinstance(val, expected_type):` branch fires, logs a warning, but returns `True` (ok was never set to False in that branch). Any caller that gates on `validate_nws_response()` receives `True` and proceeds with a structurally invalid NWS response, potentially causing a KeyError or AttributeError deeper in the NWS parsing path.

---

## File-Level Summary

`schema_validator.py` is a pure utility with no direct trade execution. The three
validators are used as a defensive layer before API response data enters the bot's
logic. No red flags (RF1–RF6) fire. No invariants from the system table apply directly
(no SQL, no locks, no Kelly, no atomic writes).

Two findings require fixes before the next production incident:

1. **`validate_market()` silent price violations** — out-of-range bids/asks log at DEBUG
   instead of WARNING. Operators monitoring logs at INFO/WARNING will never see corrupt
   market prices. Severity: MEDIUM (operator visibility gap, not a trade-placement bug
   unless callers ignore the return value).

2. **`validate_nws_response()` missing `ok = False`** — a type mismatch on `properties`
   returns `True` silently. This is an active bug on a reachable path if the NWS API
   response format changes. Severity: MEDIUM (NWS forecasts feed the multi-day blend;
   a corrupted properties dict causes downstream AttributeError, not a silent bad trade).

The `_price_to_decimal()` edge case with `f == 1.0` (interpreted as already-decimal
rather than 1¢) is theoretical — Kalshi bids are never exactly 1.00 in practice and
the heuristic is correct for all realistic inputs.

No test coverage was found for any function in this file. Given the TIER 2 classification
and the validator-only role, this is acceptable but worth noting.
