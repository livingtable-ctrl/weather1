# Pass 6 — Kalshi Semantics: Independent Verification Notes

Verifier pass over the 4 raw findings submitted for Section 17. All 4 independently
re-derived from current source (not trusted from the original write-up).

## Finding 1 — exposure/risk caps blind to live positions (paper.py)
Read paper.py:1299-1301 (get_open_trades -> _load()["trades"] only, i.e. paper_trades.json),
1598-1673 (get_city_date_exposure/get_directional_exposure/get_total_exposure/
get_ticker_exposure/get_correlated_exposure all sum over get_open_trades()),
1676-onward (portfolio_kelly_fraction composes those), 3447-3651 (check_position_limits,
same get_open_trades()/get_total_exposure() calls). Read order_executor.py:2310-2364
(_auto_place_trades seeds _open_trades_list from paper.get_open_trades() only),
2436 (MAX_CONCURRENT_POSITIONS checked against that same list), 2990-3058 (live branch:
opp_placed via _place_live_order, appends only to in-memory _open_trades_list, comment
literally says "F6: mirror the paper branch's _open_trades_list.append(trade)"),
3059-3122 (paper/else branch: place_paper_order() actually called at 3094). No
execution_log merge found anywhere in this function. CONFIRMED as described, no
material inaccuracy found. E1 static, verified directly.

## Finding 2 — _count_open_live_orders only counts 'pending'
order_executor.py:171-174, literal source confirmed:
`return sum(1 for o in orders if o.get("live") and o.get("status") == "pending")`.
Cross-checked _kalshi_status_to_internal (order_executor.py ~224-248): "executed" ->
"filled", "canceled"+fill_count -> "filled" (F9 partial-fill promotion) — confirms
"filled" is the resolved-position status. execution_log.get_filled_unsettled_live_orders
(execution_log.py:535-556) WHERE clause literally `status = 'filled' AND settled_at IS
NULL AND closes_position_id IS NULL` — the codebase's own canonical "real open position"
query, distinct from _count_open_live_orders' 'pending'-only filter. _place_live_order
(order_executor.py:1610-1613) uses config.get("max_open_positions", 10) against
_count_open_live_orders() — default 10 confirmed. GTC placement confirmed
(time_in_force="good_till_canceled") and pending pre-log confirmed at log_order(...,
status="pending", live=True). grep confirmed _poll_pending_orders (the only pending->filled
transition point) has exactly one call site, main.py:3760, inside cmd_watch's `if live:`
block. cron.py:906-908 comment confirms "cron.py itself never places live orders."
git log -S confirmed _kalshi_status_to_internal predates the 53-commit window
(introduced 1f88d9e8); order_executor.py's own recent-commits list (e5331a8d, 105cf4ce,
c6288b9c, fc8e3555, 1659e638...) does not touch _count_open_live_orders. Read
tests/test_prelog.py:109-119 test_placed_order_counts_toward_open_positions — confirmed
it only asserts the freshly-pending case (_run_place then _count_open_live_orders()==1
immediately after placement, no fill-transition step), matching the "gap is untested"
claim. CONFIRMED, no material inaccuracy. E1 static, verified directly.

## Finding 3 — MAX_SAME_DAY_SPEND has no persistent cross-cycle live enforcement
order_executor.py:1602 confirmed: `if execution_log.get_today_live_spend() >=
MAX_DAILY_SPEND:` (persistent counter, but checked only against the larger cap).
order_executor.py:3001 confirmed: `if sameday_spent + _live_cost_estimate >
MAX_SAME_DAY_SPEND:` inside the live branch (lines 2990-3058, same branch as Finding 1).
sameday_spent seeded at order_executor.py:2446 `sameday_spent = _daily_sameday_spend()`,
which is paper_trades.json-only (confirmed by reading _daily_sameday_spend's body,
iterates `_load()["trades"]` filtered on days_out==0). CONFIRMED, no material
inaccuracy. E1 static, verified directly.

## Finding 4 — manual live sell only closes oldest matching position
main.py:4595-4630 read in full. Comment and warning text match the finding's quote
verbatim ("this sell only closes the OLDEST one ... the others are untouched and need
their own sell", literally "Opus review (2026-08-17), NEW-M1"). _live_close_position =
_live_open_matches[0] (oldest by construction of _get_live_open_positions' ordering,
consistent with description). CONFIRMED exactly as described, self-acknowledged
in-code limitation. E1, verified directly.

## Summary
All 4 findings independently reproduced against current source; none disproven, none
downgraded. No attempt to refute succeeded — every code path cited matches the
finding's own description, including exact line-level mechanics (variable names,
default values, comment text).
