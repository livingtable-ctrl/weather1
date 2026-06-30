# Grade Audit — execution_log.py

Graded: 2026-06-29
File length: 492 lines
All functions read in full before grading.

Module note per tier2.md: "Check whether a crash between order placement and the log write
would leave the order unlogged. An unlogged order is invisible to the audit trail."

---

## Key Structural Finding

The module-level note is the primary concern. The caller pattern in order_executor.py is:

```
log_id = execution_log.log_order(...)   # pre-logged as 'sent'
# ... call Kalshi API ...
execution_log.log_order_result(log_id, status="filled"/"failed", ...)
```

Because `log_order()` is called with `status='sent'` BEFORE the API call, a crash between
placement and the result update leaves a 'sent' row — not an unlogged order. The
`was_ordered_this_cycle` / `was_ordered_recently` guards treat 'sent' as a live order and
will block re-entry. This is the safe design. No crash-between-write gap.

---

## Function Grades

[execution_log.py] _conn() L:30–35  8/10 — Opens fresh connection each call with WAL+FULL sync; callers use `with _conn() as con:` for auto-commit; no connection pool so each call pays open overhead but avoids stale state. Minor gap: no timeout set so long DB locks can stall the cron thread indefinitely.  [Confidence: Confirmed]

[execution_log.py] init_log() L:38–102  8/10 — Correct double-checked locking (check-lock-check), executescript for CREATE TABLE, then separate connection for migrations with per-statement OperationalError catch (the right idiom for ADD COLUMN idempotency). Gap: the migration loop catches `sqlite3.OperationalError` bare (L100), which is correct for "duplicate column" but would also silently swallow a genuine table-corruption error on first boot.  [Confidence: Confirmed]

[execution_log.py] log_order() L:105–153  7/10 — Inserts all structured fields in one atomic INSERT before the API call is made (correct pre-logging pattern). `cur.lastrowid or 0` is a safe fallback. No red flags. Gap: if `json.dumps(response)` raises (malformed dict with non-JSON-serialisable values), the entire log write fails silently — caller gets 0 and proceeds with no log ID, then passes 0 to `log_order_result()` which would UPDATE WHERE id=0, matching nothing.  [Confidence: Likely]
FAILURE SCENARIO: Caller passes a `response` dict containing a datetime or bytes value (e.g. from a Kalshi API response wrapper). `json.dumps` raises TypeError. The INSERT is not executed. `log_order` returns 0. `log_order_result(0, ...)` silently updates zero rows. The order is unlogged.

[execution_log.py] log_order_result() L:156–184  7/10 — Straightforward UPDATE by primary key. Same `json.dumps` risk as `log_order` if caller passes a non-serialisable response. No guard on `row_id` being 0 — a 0 passed from a failed `log_order` call silently updates nothing, leaving the 'sent' row permanently in the DB (stale ghost that will block future was_ordered* checks).  [Confidence: Confirmed]
FAILURE SCENARIO: `log_order` returns 0 (json.dumps failure or other INSERT error). Caller calls `log_order_result(0, status='filled', ...)`. UPDATE WHERE id=0 matches nothing. Order remains as status='sent' forever, blocking the same ticker indefinitely through `was_ordered_recently`.

[execution_log.py] was_recently_ordered() L:187–209  8/10 — The H-21 comment documents the ISO-T → space normalization correctly; using `replace(replace(placed_at, 'T', ' '), 'Z', ''))` is robust. `status != 'failed'` exclusion is correct. `within_minutes` defaults to 10. No red flags.  [Confidence: Confirmed]

[execution_log.py] was_traded_today() L:212–230  7/10 — SQL injection risk via f-string interpolation of `live_clause` (L223). Although `live` is a bool, the construction `f" AND live = {1 if live else 0}"` inserts a literal int directly into the query string — fine for this type but structurally fragile. The `placed_at LIKE ?` pattern relies on placed_at using the UTC date prefix, which is consistent with `datetime.now(UTC).isoformat()` in `log_order`. Test coverage exists (test_dedup.py, 7 tests). Gap: no test covers the `live=True` isolation path directly against the DB (only integration test through main._auto_place_trades).  [Confidence: Confirmed]

[execution_log.py] was_ordered_this_cycle() L:233–245  7/10 — Simple, correct query. No status='cancelled' exclusion — a cancelled order on this cycle would still block re-placement. This may be intentional (conservatism) but is undocumented and differs from `was_ordered_recently` which explicitly excludes 'cancelled'. No test coverage for the cycle-match path.  [Confidence: Possible]

[execution_log.py] was_ordered_recently() L:248–266  8/10 — H-22 comment explains the NOT IN ('failed', 'cancelled') design clearly. `placed_at >= datetime('now', ?)` with negative interval string is a valid SQLite idiom. Returns False for cancelled orders (correct — cancelled orders should allow re-entry). Well-documented.  [Confidence: Confirmed]

[execution_log.py] get_today_live_loss() L:269–277  8/10 — Single SELECT, returns 0.0 on missing row, clean. Used as a gate in order_executor to check daily loss limit. No exception handling — a DB corruption would propagate as an unhandled exception to the caller (order_executor), which would likely abort the trade cycle. This is the safer failure mode (halt on uncertainty) vs. silently returning 0.0.  [Confidence: Confirmed]

[execution_log.py] add_live_loss() L:280–311  6/10 — RF1 candidate: L306–311 catches broad `Exception exc` and calls `warnings.warn(...)` (not `_log.warning(...)`). `warnings.warn` goes to stderr in production and is NOT captured by the application's logging system, making this silently invisible in log files. The fallback returns `get_today_live_loss()` which could also fail, returning 0.0 — causing the caller to undercount daily loss. This is a safety-relevant function (gates daily trade limits).  [Confidence: Confirmed]

**RF1 PROMOTION — add_live_loss()**

[execution_log.py] add_live_loss() L:280–311  ★ T1 (promoted from T2 via RF1)
Score: 5/10  |  Confidence: Confirmed
AC: N/A (no acceptance criteria defined in module)
Red flag: RF1 — `warnings.warn(f"add_live_loss DB write failed: {exc}")` at L307 — exception caught without a log at WARNING or above; `warnings.warn` is invisible to the application logger.
Invariants: N/A (not a Kelly/balance/settlement path directly)
STRENGTHS:
• INSERT ON CONFLICT pattern is atomic and handles concurrent calls correctly (L296–301).
• Fallback chain (get_today_live_loss → 0.0) prevents a crash from propagating to caller.
• Used correctly: caller (order_executor) checks the returned value immediately.
WEAKNESSES:
• L307: `warnings.warn(...)` is not captured by Python's logging framework. In production (where warnings.simplefilter is not set), this goes to stderr and disappears. The operator has no visibility into DB write failures in this critical accounting function.
• L309–310: The inner except catches any exception from `get_today_live_loss()` and returns 0.0. If the DB is corrupt, daily_loss gates will read 0.0 and allow unlimited trading on that day.
• No type check on `amount` — None or NaN passed from caller would insert NULL/NaN into the DB accumulator, corrupting all future reads from that date's row.
FAILURE SCENARIO: The execution_log.db WAL file is locked briefly by a backup process. The INSERT ON CONFLICT fails with OperationalError("database is locked"). warnings.warn fires — invisible in log files. get_today_live_loss() also fails (same lock). Returns 0.0. order_executor sees daily loss = 0.0, treats daily limit as unmet, and continues placing orders regardless of actual day's losses.
FIX:
execution_log.py:307 — replace `warnings.warn(f"add_live_loss DB write failed: {exc}")` with `_log.warning("add_live_loss DB write failed: %s", exc)`
Also add guard at L289: `if amount is None or (isinstance(amount, float) and (amount != amount)): _log.warning("add_live_loss called with invalid amount=%r; skipping", amount); return get_today_live_loss()`
VERDICT: fix before live — logging failure is high-confidence and the fallback-to-0.0 path is dangerous for a daily loss gate.

---

[execution_log.py] get_filled_unsettled_live_orders() L:314–325  8/10 — Clean SELECT with correct filters (live=1, filled, settled_at IS NULL). Returns list of dicts. Used in order_executor settlement loop. No edge case issues.  [Confidence: Confirmed]

[execution_log.py] record_live_settlement() L:328–343  7/10 — Updates settled_at, outcome_yes, pnl by order_id. `int(outcome_yes)` correctly converts bool to 0/1. No 24h gate check here — but the 24h gate is enforced in the caller (order_executor), not in this write function. This is an acceptable separation of concerns, but means any future caller can bypass the 24h gate by calling this directly.  [Confidence: Confirmed]

[execution_log.py] export_live_tax_csv() L:346–409  7/10 — Correct dual-branch (tax_year/no-tax_year) SQL. `outcome_yes=None` rows would produce `"no"` in the CSV (L406: `"yes" if row["outcome_yes"] else "no"`), which is misleading for unsettled records — but the WHERE clause requires `settled_at IS NOT NULL AND pnl IS NOT NULL`, so outcome_yes=None rows are excluded. Minor gap: `open(path, ...)` can raise FileNotFoundError if parent directory doesn't exist; no error handling or directory creation.  [Confidence: Confirmed]

[execution_log.py] get_live_pnl_summary() L:412–452  8/10 — Three SELECTs in a single `with _conn()` block (correct, same connection). COALESCE handles NULL SUM. `round(..., 4)` avoids floating-point noise in dashboard display. Gap: `today_pnl` query does not filter `pnl IS NOT NULL`, so if settled_at is set but pnl is NULL, the COALESCE SUM returns 0.0 anyway — not a bug but slightly inconsistent with totals_row query which does filter `pnl IS NOT NULL`.  [Confidence: Confirmed]

[execution_log.py] get_recent_orders() L:455–462  8/10 — Simple, correct. `placed_at DESC` ordering is appropriate for "most recent". No OFFSET support — fine for current use (dashboard display).  [Confidence: Confirmed]

[execution_log.py] get_order_by_id() L:465–478  6/10 — RF1 candidate: broad `except Exception as exc` caught at L476 and logged at DEBUG (`_log.debug`). Per rubric: "exception caught without a log at WARNING or above" fires RF1.  [Confidence: Confirmed]

**RF1 PROMOTION — get_order_by_id()**

[execution_log.py] get_order_by_id() L:465–478  ★ T1 (promoted from T2 via RF1)
Score: 6/10  |  Confidence: Confirmed
AC: N/A
Red flag: RF1 — `_log.debug("get_order_by_id: %s", exc)` at L477 — exception caught and logged at DEBUG instead of WARNING or above. A DB corruption or schema mismatch would silently return None to the caller.
Invariants: N/A (read-only display path)
STRENGTHS:
• Returns None on not-found, safe for callers to handle.
• try/except prevents crashes from propagating to the dashboard.
WEAKNESSES:
• L477: DEBUG logging means DB errors are invisible in production log levels. A caller (main.py L6886) expecting a dict will get None and should handle it, but the silent failure makes diagnosis difficult.
FAILURE SCENARIO: Schema migration partially fails (new column not yet added). A SELECT * raises OperationalError. Caller gets None. Dashboard shows no order detail. No log line at WARNING. Operator cannot distinguish "order not found" from "DB error".
FIX:
execution_log.py:477 — replace `_log.debug(...)` with `_log.warning("get_order_by_id(%r) DB error: %s", order_id, exc)`
VERDICT: fix before live — low-effort change, improves debuggability.

---

[execution_log.py] append_entry() L:481–491  7/10 — Imports json inside function (harmless but inconsistent with top-level import). Uses `_append_lock` (WA-9) for concurrent JSONL append safety. `target.parent.mkdir(parents=True, exist_ok=True)` handles missing dirs. No exception handling — a disk-full or permission error will propagate. This is the safer failure mode for an audit trail function (fail loudly vs. silently drop entries).  [Confidence: Confirmed]

---

## Summary

| Function | Score | Tier | Red Flag |
|---|---|---|---|
| _conn | 8 | T2 | None |
| init_log | 8 | T2 | None |
| log_order | 7 | T2 | None |
| log_order_result | 7 | T2 | None |
| was_recently_ordered | 8 | T2 | None |
| was_traded_today | 7 | T2 | None |
| was_ordered_this_cycle | 7 | T2 | None |
| was_ordered_recently | 8 | T2 | None |
| get_today_live_loss | 8 | T2 | None |
| **add_live_loss** | **5** | **T1 (RF1)** | **RF1** |
| get_filled_unsettled_live_orders | 8 | T2 | None |
| record_live_settlement | 7 | T2 | None |
| export_live_tax_csv | 7 | T2 | None |
| get_live_pnl_summary | 8 | T2 | None |
| get_recent_orders | 8 | T2 | None |
| **get_order_by_id** | **6** | **T1 (RF1)** | **RF1** |
| append_entry | 7 | T2 | None |

**File median: 7–8.** Two RF1 promotions. No RF2–RF6. No crash-between-order-and-log gap (design is pre-log before API call). The most material issue is `add_live_loss` using `warnings.warn` instead of `_log.warning` for a daily loss gate — a DB lock could cause it to silently return 0.0 and allow uncapped intraday trading.
