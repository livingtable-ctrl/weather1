# Pass 11 — State: Independent Verification

Session: re-examined all 7 raw findings from Pass 11 against current source. Re-ran
existing repro scripts myself (did not trust prior pass's claimed results) and wrote
one new repro (EMOS TOCTOU) to convert an E1 claim to E2.

## Finding 1 — _count_open_live_orders only counts status=='pending'
CONFIRMED. order_executor.py:172-175 reads exactly as described (`get_recent_orders(limit=500)`
filtered to `live and status=='pending'`). get_filled_unsettled_live_orders (execution_log.py:535)
uses `status='filled' AND settled_at IS NULL` — the two definitions genuinely diverge once a
position fills. main.py:3632 (run_trade_cycle call) precedes main.py:3760 (_poll_pending_orders
call) in the watch loop, confirming prior-cycle fills are invisible to the same cycle's gate.
Re-ran `py -m pytest audit/reproductions/pass11_state_repro.py::test_count_open_live_orders_drops_filled_positions`
this session — PASSED.

## Finding 2 — _auto_place_trades gates seeded only from paper ledger
CONFIRMED (static). order_executor.py:2364 `_open_trades_list = get_open_trades()` (paper.py import,
line 2313/1847). No execution_log/get_filled_unsettled_live_orders call anywhere in
_auto_place_trades' body (grep-confirmed). The only live-aware mutation is the same-cycle
append at lines 3037-3053 (labeled "F6" in-code), which does not backfill prior-cycle live
fills. Re-ran `pass11_state_repro.py::test_auto_place_trades_open_trades_list_is_paper_only` —
PASSED.

## Finding 3 — cmd_order partial manual sell never settles its own row
CONFIRMED. main.py:4780-4793 shows exactly one call, `record_live_exit_fill(_live_close_position,
_record_count, price)`, no second call. Read execution_log.py:734-804 (record_live_exit_fill) in
full: both its partial (`record_live_partial_exit`) and full-close (`record_live_early_exit`)
branches operate on `position["id"]` (the POSITION's row) only — never on the caller's own
sell-order row_id. Contrast with order_executor.py:1279-1320 (_exit_live_position's partial-fill
branch), which makes a required SECOND call, `execution_log.record_live_early_exit(log_id, ...)`,
explicitly to settle the exit order's own row ("Settle the EXIT ORDER's own row... so this sold
lot gets its own tax-CSV row"). cmd_order has no equivalent second call. Re-ran
`pass11_state_repro.py::test_cmd_order_partial_manual_sell_row_never_settled` — PASSED.

## Finding 4 — pending-order window eviction (200/500-row LIMIT, no live filter in SQL)
CONFIRMED, upgraded confidence via direct re-run. execution_log.py:937-944 `get_recent_orders`
has no WHERE clause at all (`SELECT * FROM orders ORDER BY placed_at DESC LIMIT ?`). Contrast
get_live_pnl_summary's own `open_count` (execution_log.py:922-928): direct SQL
`WHERE live=1 AND status='pending'`, no LIMIT — proving the fix pattern already exists
elsewhere in the same file, as claimed. order_executor.py:174 (_count_open_live_orders,
limit=500) and :441 (_poll_pending_orders, limit=200) both confirmed via grep.
Independently re-ran `py audit/reproductions/pass11_stale_pending_window_eviction.py` this
session (script, not pytest) — output:
```
live pending order visible to _poll_pending_orders (limit=200)? False
live pending order counted by _count_open_live_orders (limit=500) after 250 interleaved paper orders? True (count = 1 )
live pending order counted by _count_open_live_orders after 520 interleaved paper orders? False (count = 0 )
row still exists in DB with status: pending
```
Matches the finding's claimed numbers exactly (200-row eviction at 250 interleaved orders,
500-row eviction at 520).

## Finding 5 — dedup guards not new-broken by closes_position_id (OBSERVATION)
CONFIRMED as pre-existing, non-regression. Re-ran both
`pass11_dedup_baseline.py` and `pass11_dedup_exit_row.py` this session: entry-only scenario
already returns was_traded_today=True/was_recently_ordered=True with no exit row present;
adding the exit row produces the identical result. execution_log.py:278-380 confirmed none of
the three guard queries filter `closes_position_id`.

## Finding 6 — sqlite `with _conn() as con:` never closed
CONFIRMED. grep counts match exactly: execution_log.py 21 sites, tracker.py 105 sites, 0
`.close()`/`contextlib.closing` in either file. `_conn()` (execution_log.py:108, tracker.py:413)
returns a fresh `sqlite3.connect(...)`; the context-manager protocol used only commits/rolls
back, doesn't close.

## Finding 7 — get_emos_status() TOCTOU mislabels deletion race as corruption
CONFIRMED, upgraded from E1 to E2 this session. ml_bias.py:1207-1222 confirmed as described:
`exists()` check then separate `read_text()`/`json.loads()` inside a broad `except Exception`
that returns `{'active': False, 'corrupt': True, ...}` without distinguishing
FileNotFoundError from a genuine parse failure. Wrote and ran new repro
`audit/reproductions/pass11_emos_toctou_repro.py` this session: monkeypatched `Path.exists` to
delete the file at the exact moment `exists()` is checked (simulating a concurrent
deactivate_emos()), confirming `get_emos_status()` returns `{'active': False, 'corrupt': True,
'error': "[Errno 2] No such file or directory..."}` for what is actually a pure deletion race,
not corruption.

## Summary
All 7 findings CONFIRMED against current source; none disproven. Findings 4 and 7 upgraded
in evidence strength (both now backed by a runtime repro executed this session, not just
inherited from the prior pass's claims).
