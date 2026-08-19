# Pass 11 -- State (Section 23) evidence

Repro harness: `audit/reproductions/pass11_state_repro.py` (3 tests, all pass,
all isolate execution_log.DB_PATH to tmp_path -- never touches the real
main-clone execution_log.db). Run:

    pytest audit/reproductions/pass11_state_repro.py -v -s

## Finding 1 -- `_count_open_live_orders()` only counts 'pending' orders, not open positions

order_executor.py:172-175, consumed at order_executor.py:1611 inside
`_place_live_order`'s step-2 `max_open_positions` gate.

```python
def _count_open_live_orders() -> int:
    """Count live orders with status 'pending' — enforces max_open_positions limit."""
    orders = execution_log.get_recent_orders(limit=500)
    return sum(1 for o in orders if o.get("live") and o.get("status") == "pending")
```

Repro `test_count_open_live_orders_drops_filled_positions`: 3 live buy orders
placed (status='pending') -> gate reports 3. `_poll_pending_orders` observes
fills (status -> 'filled', matching every real GTC fill in production) -> gate
reports **0**, while `execution_log.get_filled_unsettled_live_orders()` (the
function the rest of the codebase treats as "the real open live positions",
per its own docstring and every other consumer in order_executor.py) still
correctly reports 3 open positions.

Within one `watch --auto --live` cycle, order placement (`_place_live_order`,
gated by `_count_open_live_orders()`) runs, then later in the SAME cycle
`_poll_pending_orders` transitions any newly-matched fills from pending to
filled (main.py:3760, after the placement step at cycle top) -- confirmed via
`grep`/read of main.py's cmd_watch loop ordering. So every live position that
fills is invisible to this gate as of the very next cycle's placement check.

## Finding 2 -- `_auto_place_trades`'s position-count/VaR/concentration gates read only the paper ledger

order_executor.py:2310-2321 (imports `get_open_trades` from `paper`),
line 2364 (`_open_trades_list = get_open_trades()`), consumed by:
- MAX_CONCURRENT_POSITIONS, line ~2436
- per-date concentration cap (`_multiday_date_counts`), lines ~2402-2431
- same-day cap (`_same_day_open`), lines ~2402-2404
- VaR gate `portfolio_var(_open_trades_list + [candidate])`, lines 2916-2941
- `corr_kelly_scale`, downstream of the same list

This is unconditional on the `live` parameter -- the same paper-ledger-sourced
list feeds every one of these gates whether `_auto_place_trades(live=True,
...)` or not. Repro `test_auto_place_trades_open_trades_list_is_paper_only`
confirms via source inspection that no `execution_log`/`_get_live_open_positions`
call feeds this list anywhere in the function.

A same-cycle partial mitigation exists (`F6`, order_executor.py:3037-3053):
live orders placed THIS cycle are appended in-memory to `_open_trades_list`
so later candidates in the same cycle see them. This does not address prior
cycles' already-open, already-filled live positions -- those never entered
`_open_trades_list` at all (it's seeded fresh from the paper ledger every
call), so cross-cycle real live exposure is invisible to every gate above,
including the VaR gate that commit `6364b38b`'s own re-verification (per the
recon report) confirmed is "a real live-trade-gating path."

Contrast with the **dollar-spend** dimension of this exact same blind spot,
which WAS given a proper fix: `_place_live_order`'s step 1b (order_executor.py
~1591-1607) explicitly reads `execution_log.get_today_live_spend()` (a
persistent, execution_log-sourced counter) specifically because
`_daily_paper_spend()`/`_daily_sameday_spend()` "only ever read
paper_trades.json and are blind to live orders." No equivalent
execution_log-sourced counter exists for position COUNT or VaR.

## Finding 3 -- cmd_order's manual partial-sell never settles its own execution_log row

main.py:4780-4793 (commit `e5331a8d`, 2026-08-17) vs. the correct pattern in
`order_executor._exit_live_position`'s partial-fill branch (order_executor.py
1279-1332, specifically the follow-up call at line 1320:
`execution_log.record_live_early_exit(log_id, exit_price, reason, partial_pnl)`).

cmd_order calls only `execution_log.record_live_exit_fill(_live_close_position,
_record_count, price)`, which (per its own docstring) settles only the
referenced POSITION row (`position["id"]`) -- for a partial fill it reduces
`fill_quantity` via `record_live_partial_exit` and leaves `settled_at` NULL
(correct -- the position is still open). It never touches the SELL order's
own row (`row_id`, created earlier in cmd_order with `closes_position_id`
set), unlike `_exit_live_position`'s second explicit call.

Repro `test_cmd_order_partial_manual_sell_row_never_settled`: after
replicating cmd_order's exact bookkeeping sequence for a 4-of-10-contract
partial manual sell, the sell order's own row has `settled_at=None,
pnl=None` permanently, and `execution_log.get_live_pnl_summary()` returns
`total_pnl=0.0` despite a real, non-zero, correctly-fee-adjusted P&L having
been added to the daily aggregate (`add_live_loss` inside `record_live_exit_fill`
did run). `export_live_tax_csv` filters on `settled_at IS NOT NULL AND pnl IS
NOT NULL`, so this row -- and this lot's realized P&L -- never appears in the
tax export either.

This reproduces, on the new cmd_order path added the same day, exactly the
"aggregate-only P&L" bug commit `105cf4ce` (earlier the same day) fixed for
the automated `_exit_live_position` path.

## Finding 4 -- sqlite3 connections opened via `with _conn() as con:` are never explicitly closed

execution_log.py (21 call sites) and tracker.py (105 call sites) both use
`with _conn() as con:` where `_conn()` returns a fresh `sqlite3.connect(...)`
each call. Python's `sqlite3.Connection.__enter__/__exit__` only manages the
transaction (commit/rollback on exit) -- it does not call `.close()`. Every
one of these ~126 call sites therefore relies on CPython reference counting
to close the connection (and release its WAL/SHM file handles) promptly when
`con` goes out of scope. This is usually fine under CPython's refcounting GC,
but is a latent fragility given this same codebase has independently
documented (commit `94d36402`) that Windows file-sharing violates
(`PermissionError`/WinError 5) fire whenever *any* handle -- reader or not --
is open against a target file during `os.replace()`. execution_log.db and
predictions.db are not currently written via `atomic_write_json`, so this
specific interaction is not confirmed to cause a real incident, but the
pattern is pre-existing and codebase-wide, not introduced by the 53-commit
window. Recorded as INFO/LOW.

## Finding 5 (added in a later Pass 11 re-run, 2026-08-17 session) -- `_poll_pending_orders`/`_count_open_live_orders` can silently lose track of a genuinely still-open live order once enough OTHER orders (mostly paper trades, which share the same `orders` table) get logged afterward

`execution_log.get_recent_orders(limit=N)` (execution_log.py:937-944) is
`SELECT * FROM orders ORDER BY placed_at DESC LIMIT ?` -- no `WHERE live=1`
in the SQL at all. Both safety-relevant consumers fetch a fixed-size window
of the N *most recent orders of any kind* (paper AND live mixed in one
table -- order_executor.py:3083-3092 confirms `_auto_place_trades` pre-logs
every PAPER order into this same table too, specifically so
`was_traded_today()` also works for paper dedup) and only filter for
`live`/`status` in Python *after* truncating to that window:

- `order_executor._poll_pending_orders` (order_executor.py:424-443):
  `pending = [o for o in execution_log.get_recent_orders(limit=200) if
  o.get("live") and o.get("status")=="pending" and o.get("response")]` --
  this is the ONLY place a live GTC order's fill/GTC-cancel-timer status
  ever gets checked and written back to the DB.
- `order_executor._count_open_live_orders` (order_executor.py:172-175):
  `sum(1 for o in execution_log.get_recent_orders(limit=500) if
  o.get("live") and o.get("status")=="pending")` -- feeds the
  `max_open_positions` gate at `_place_live_order` step 2
  (order_executor.py:1610-1613).

Repro `audit/reproductions/pass11_stale_pending_window_eviction.py`: logged
one live GTC order (status='pending'), then 250 more orders into the same
table (mirroring `_auto_place_trades`'s paper pre-log pattern) --
`_poll_pending_orders`'s own exact selection logic no longer includes the
live order (result: `False`). After 520 total interleaved orders,
`_count_open_live_orders`'s own exact selection logic also drops to 0 even
though the row is confirmed still present in the DB with `status='pending'`
(`get_order_by_id` still returns it). `watch --auto`'s loop runs every
`REFRESH_SECS=300` (main.py:211) seconds and can log multiple paper orders
per cycle across every tracked city/market combination
(`_auto_place_trades`), so exceeding 200-500 interleaved rows over a few
hours of active paper+live trading is plausible, not a contrived edge case.

Once evicted from `_poll_pending_orders`'s window, the row's `status` can
never again transition away from `'pending'` -- even if the order actually
filled on Kalshi or expired via the exchange's own GTC timer -- because
nothing else in the codebase updates it. Consequences compound:
`execution_log.get_filled_unsettled_live_orders()` (the function every
other consumer treats as "the real open live positions," requires
`status='filled'`) never picks it up, so `positions.check_stop_losses`/
`check_breakeven_stops` never protect it even if it is a real, live,
filled position sitting on the exchange; and once it also falls out of the
500-row `_count_open_live_orders` window, the `max_open_positions` cap
silently under-counts, permitting MORE live exposure than configured. The
pre-close/GTC-timer cancel logic inside the same `_poll_pending_orders` loop
(order_executor.py:458-470) is also never reached for an evicted row, so a
resting order that should have been canceled ahead of market close stays
resting past that point.

Contrast: `execution_log.get_live_pnl_summary()`'s own `open_count`
(execution_log.py:922-928) queries `WHERE live = 1 AND status = 'pending'`
directly with no LIMIT at all -- proving the codebase already has the
correct pattern for this exact same "how many live orders are pending"
question elsewhere, just not applied to either of the two safety-relevant
consumers above. `execution_log.get_filled_unsettled_live_orders()`
(no LIMIT) and `was_recently_ordered`/`was_traded_today`/
`was_ordered_recently` (bounded existence checks with `LIMIT 1`, not a
truncated-then-filtered window) are all unaffected by this specific bug
class.

Recorded as a new finding this session (not present in the original Pass 11
pass or its independent verification above) -- HIGH severity, E2 (self-built
reproducible test against a real execution_log.py/order_executor.py code
path), MEDIUM confidence on real-world trigger frequency (depends on actual
production paper-order volume between polls, which this worktree cannot
observe directly since no live credentials/real data exist here) but HIGH
confidence in the mechanism itself.
