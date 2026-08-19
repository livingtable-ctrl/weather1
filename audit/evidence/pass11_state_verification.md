# Pass 11 (State) — Independent Verification

Re-examined all 4 raw findings against current source (not the original pass's
descriptions of it). Ran `pytest audit/reproductions/pass11_state_repro.py -v -s`
myself (3 passed) rather than trusting the original pass's reported run.

## Finding 1 — `_count_open_live_orders()` counts only status=='pending'
CONFIRMED. order_executor.py:172-175 sums only `status == "pending"`.
`_poll_pending_orders` (order_executor.py:424-524) transitions rows to
`status="filled"` once a fill is observed (line ~510-514), at which point they
drop out of the count entirely, while `execution_log.get_filled_unsettled_live_orders()`
(execution_log.py:535-556, filters `status='filled' AND settled_at IS NULL`)
correctly still reports them open. Gate call site confirmed at
order_executor.py:1610-1613 (`_place_live_order` step 2, `config.get("max_open_positions", 10)`).
Ordering claim confirmed: in main.py's watch loop, `run_trade_cycle()` (which
reaches `_auto_place_trades`→`_place_live_order`→this gate via `ctx.auto_place_trades`,
trade_cycle.py:908/919) runs at main.py:3632, strictly before `_poll_pending_orders`
at main.py:3760 in the same iteration — so a position filled in a prior cycle's
poll step is already `status="filled"` and invisible to this cycle's gate.
Existing test `tests/test_prelog.py::test_placed_order_counts_toward_open_positions`
only exercises the pending state, matching the finding's stated test gap.
Self-ran repro: `test_count_open_live_orders_drops_filled_positions` — PASSED,
observed before=3, after=0, real_open_positions=3.

## Finding 2 — `_auto_place_trades`'s position/VaR gates are paper-ledger-only
CONFIRMED. order_executor.py:2360-2364: `_open_trades_list = get_open_trades()`
(imported from `paper`, order_executor.py:2310-2321 import block) is the sole
feed for `MAX_CONCURRENT_POSITIONS` (order_executor.py:2434-2443) and the VaR
gate `portfolio_var(_open_trades_list + [candidate])` (order_executor.py:2929).
No `execution_log`/`get_filled_unsettled_live_orders`/`_get_live_open_positions`
call exists anywhere in `_auto_place_trades`'s body (grep-confirmed). The
"F6" same-cycle mitigation is real (order_executor.py:3037-3053,
`_open_trades_list.append(...)` after a live placement) but is explicitly
in-memory and per-call — `_open_trades_list` is reseeded from
`paper.get_open_trades()` on every fresh `_auto_place_trades()` invocation, so
positions opened in a prior cycle (the normal case for a long-running
`watch --auto --live`/cron process) are never included. Parallel precedent
(`get_today_live_spend()` fixing the analogous spend-cap blind spot) confirmed
at order_executor.py:1591-1607. Self-ran repro:
`test_auto_place_trades_open_trades_list_is_paper_only` — PASSED (source-inspection
assertions all held).

## Finding 3 — cmd_order's manual partial sell never settles its own execution_log row
CONFIRMED. main.py:4780-4793 (cmd_order's live-sell branch) calls only
`execution_log.record_live_exit_fill(_live_close_position, _record_count, price)`.
Read `record_live_exit_fill` (execution_log.py:734-804): for a partial fill
(`clamped_fill_count < qty`) it calls `record_live_partial_exit(position["id"], ...)`
— operating on the POSITION row (`position["id"]`) — and never touches the
SELL ORDER's own row (the `log_id` created earlier in cmd_order with
`closes_position_id` set). Contrast confirmed at order_executor.py:1279-1332:
`_exit_live_position`'s partial-fill branch makes a required second call,
`execution_log.record_live_early_exit(log_id, exit_price, reason, partial_pnl)`
(line 1320, comment explicitly says "Settle the EXIT ORDER's own row"),
which cmd_order's manual path omits. Verified the "limitations" claim too:
`_exit_live_position`'s own full-close branch (lines 1334-1373) also never
calls `record_live_early_exit(log_id, ...)` — so the divergence is genuinely
partial-fill-only, not a full-fill regression. Self-ran repro:
`test_cmd_order_partial_manual_sell_row_never_settled` — PASSED, observed the
sell order's own row with `settled_at: None, pnl: None, exit_price: None`
permanently, and `get_live_pnl_summary()` returning `total_pnl: 0.0` despite
a real partial fill.

## Finding 4 — sqlite3 connections via `with _conn() as con:` never explicitly closed
CONFIRMED. `execution_log._conn()` (execution_log.py:108-113) and
`tracker._conn()` (tracker.py:413-419) both return a bare `sqlite3.connect(...)`
with no `contextlib.closing` wrapper anywhere. Grep-confirmed counts match
exactly: 21 `with _conn() as con:` sites in execution_log.py, 105 in tracker.py,
zero `.close()`/`contextlib.closing` calls in either file. This is accurately
scoped as LOW/E1 (static-only, no observed failure) — sqlite3's context manager
only manages the transaction, not connection lifetime; CPython refcounting closes
it as soon as `con` goes out of scope in normal single-threaded call patterns, so
this is latent fragility, not a reproduced incident.

## Summary
All 4 findings independently CONFIRMED after direct code reading (order_executor.py,
main.py, execution_log.py, tracker.py, trade_cycle.py) and re-running the pass's
own repro suite myself. No claim was found to overstate or misrepresent the code.
Findings 1 and 2 are the two most consequential live-safety gaps in this pass
(position-count hard-stop silently disabled once GTC orders start filling;
VaR/concentration gates blind to a live-only account's real exposure) and both
reproduce cleanly and deterministically — not edge-case/timing-dependent bugs.
