# Pass 6 — Kalshi Semantics — Evidence Notes

Read-only audit. No repo files modified outside audit/.

## Finding 1: Risk/exposure caps in paper.py are structurally blind to real live positions

Traced every exposure/sizing function reachable from `order_executor._auto_place_trades`
and the manual order paths in main.py:

- `paper.get_open_trades()` (paper.py:1299-1301) reads exclusively
  `_load()["trades"]` = `paper_trades.json`.
- `paper.get_total_exposure()` (paper.py:1620-1623), `get_city_date_exposure()`
  (1598-1605), `get_directional_exposure()` (1608-1617), `get_correlated_exposure()`
  (1654-1673), `get_ticker_exposure()` (1626-1629), `position_age_kelly_scale()`
  (1632+) — every one sums over `get_open_trades()`, i.e. paper.json only.
- `paper.portfolio_kelly_fraction()` (paper.py:1676+) — the Kelly-sizing gate used by
  `order_executor._auto_place_trades` (order_executor.py:2778) — composes entirely
  from the functions above.
- `paper.check_position_limits()` (paper.py:3447+) — the shared manual-order gate
  used by `cmd_order` (main.py:4548), `cmd_today` [P] Place (main.py:2416,
  main.py:4548 area), `cmd_paper` (main.py:8281), web_app `/api/paper-order`
  (web_app.py:2857) — also sums `get_open_trades()` only (paper.py:3617-3646).
- `order_executor._auto_place_trades`'s own `_open_trades_list = get_open_trades()`
  (order_executor.py:2364, imported from `paper` at line 2313) seeds
  `MAX_CONCURRENT_POSITIONS` (2435-2439), `open_tickers` dup-ticker set (2365),
  same-day/multi-day date-concentration counts (2402-2432) — all from paper.json
  at the START of each cycle.

Live fills placed by `_auto_place_trades`'s live branch (`_place_live_order`,
order_executor.py:1552) are **never** written to paper.json — `place_paper_order`
is called only in the paper (`else`) branch (order_executor.py:3094). The live
branch instead does `_open_trades_list.append(...)` (3042-3053) purely in-memory,
so live orders placed earlier in the *same* cycle are visible to the rest of
*that* cycle's loop (this in-memory append was itself a documented "F6" fix), but
that list is discarded and rebuilt from paper.json alone on the next cycle/process
invocation. `main.cmd_order`'s live path was fixed in `e5331a8d` (2026-08-17) to
stop writing manual live fills into paper.json — which is correct for P&L/exit
tracking, but it also means cmd_order-placed live positions were never counted
by these paper-only exposure functions either, before or after that fix.

Net effect: `MAX_CONCURRENT_POSITIONS`, the global 50% portfolio exposure cap,
the per-city/date cap, the directional-concentration cap, and the correlated-
city-group cap are all computed with **zero knowledge of any live position that
has survived past the cycle it was opened in** — whether opened automatically
via `_auto_place_trades` or manually via `cmd_order`/`cmd_today`'s maker path.

Recon's own Section 6 already flagged the `cmd_order`-specific instance of this
gap as an explicitly deferred, safety-relevant follow-up from `e5331a8d`; this
trace shows the gap is total (every exposure-cap function, every live entry
path), not scoped to `cmd_order`.

## Finding 2: `_count_open_live_orders()` stops counting a live order the moment it fills

`order_executor._count_open_live_orders()` (order_executor.py:172-175):
```python
def _count_open_live_orders() -> int:
    """Count live orders with status 'pending' — enforces max_open_positions limit."""
    orders = execution_log.get_recent_orders(limit=500)
    return sum(1 for o in orders if o.get("live") and o.get("status") == "pending")
```//
used as the `max_open_positions` gate inside `_place_live_order`
(order_executor.py:1610-1613), the ONLY entry-side live position-count cap in
the automated engine.

`execution_log`'s own status vocabulary (order_executor.py:224-248,
`_kalshi_status_to_internal`) treats "pending" as *unresolved* (still resting /
not yet polled) and "filled" as a confirmed fill (`status='filled'`). The
canonical "real open live position" query elsewhere in this same module is
`execution_log.get_filled_unsettled_live_orders()` (execution_log.py:535-556):
`WHERE live=1 AND status='filled' AND settled_at IS NULL AND closes_position_id
IS NULL`.

`_place_live_order` always GTC-places (`time_in_force="good_till_canceled"`,
order_executor.py:1665) and pre-logs `status="pending"` (1644-1655). Only
`main.cmd_watch`'s loop calls `_poll_pending_orders` (main.py:3760, the only
caller in the repo — confirmed via grep across order_executor.py/cron.py/
main.py/trade_cycle.py), which resolves a still-open GTC order's real Kalshi
status via `client.get_order()` and rewrites the row's status to "filled" once
Kalshi reports "executed" (or "canceled" with a nonzero fill). `cron.py`
explicitly documents (cron.py:906-908) that it never places live orders itself,
so `watch --auto --live` is the only source of live entries, and its own loop
is what performs this pending→filled transition on every iteration.

Once that transition happens, the position is real, open, and unsettled — but
`_count_open_live_orders()`'s `status == "pending"` filter no longer counts it,
because it is no longer "pending"; it is "filled". A `watch --auto --live`
session that has been running for any length of time, with any positions that
have already filled (which is the common case — most limit orders near the
book midpoint do eventually fill), will therefore under-count the true number
of concurrently open live positions passed to gate #2 of `_place_live_order`.
`max_open_positions` (config default 10, main.py) is consequently only a cap on
"orders currently in flight/unresolved," not a cap on "positions currently
held" — the latter is what the setting's name and every other place in the
codebase (docstrings, comments) imply it should be.

This function/pattern pre-dates the 53-commit audit window (`git log -S
"_kalshi_status_to_internal"` shows the oldest hit is `1f88d9e8`, before the
window's earliest commit; `_count_open_live_orders` is unchanged in the
window). It is flagged here because it sits squarely in this pass's risk-
semantics scope (max position / concentration) and interacts directly with
the exact live-position/status-vocabulary subsystem the window's commits
(`e5331a8d`, `bb91374f`, `105cf4ce`) hardened elsewhere — those commits fixed
`get_filled_unsettled_live_orders()`'s matching filter and cmd_order's status
translation, but did not touch this sibling function, which has the same
"status vocabulary" dependency and remains wrong.

## Finding 3 (related, smaller): MAX_SAME_DAY_SPEND has no persistent live-specific enforcement

`_place_live_order` checks `execution_log.get_today_live_spend() >=
MAX_DAILY_SPEND` (order_executor.py:1602) as a persistent, cross-cycle brake —
but only against `MAX_DAILY_SPEND` (the multi-day cap), never against the
tighter `MAX_SAME_DAY_SPEND` sub-budget. The only code that checks live cost
against `MAX_SAME_DAY_SPEND` is the outer loop's `sameday_spent` variable
(order_executor.py:3001), which is seeded exclusively from
`_daily_paper_spend()`/`_daily_sameday_spend()` (paper.json, order_executor.py:
2445-2446) and reset every cycle — the same cross-cycle blindness as Finding 1.
The code's own comment at order_executor.py:1591-1601 acknowledges the general
shape of this gap and states `get_today_live_spend()` was added to address it,
but that only bounds *total* live spend, not same-day-specific spend
specifically, so same-day live positions can still exceed MAX_SAME_DAY_SPEND
across multiple cycles as long as cumulative live spend of all kinds stays
under MAX_DAILY_SPEND.

## Finding 4 (self-documented, informational): multiple live positions per ticker+side

main.py:4609-4630 (`cmd_order`, added 2026-08-17 per its own "opus review
NEW-M1" comment): when more than one tracked live position exists for the same
ticker+side, a manual sell only closes the oldest one; the rest are left open
and the operator is warned in the CLI output. This is an explicitly
acknowledged, non-silent limitation (not a newly-discovered bug) — logged here
per pass instructions to log all findings, including already-known ones, since
it is squarely a risk-semantics (duplicate exposure) item this pass covers.

## Areas checked with no issue found
- `kalshi_client._to_v2_side_price` yes/no + buy/sell → bid/ask + price mapping:
  internally consistent, covered by tests/test_kalshi_client.py, matches its own
  docstring in both directions.
- `kalshi_client.place_order`/`amend_order`/`cancel_order` idempotency-key
  construction and the crash-recovery `_find_order_by_client_id` three-pass
  lookup (resting → executed → canceled-with-fill) — logic is internally
  consistent and exercised by tests.
- `execution_log.record_live_exit_fill`/`record_live_partial_exit`/
  `record_live_early_exit` — P&L math is side-consistent (uses
  `positions.liquidation_price`, which already expresses NO-side prices in
  NO terms), compare-and-set race guards look sound for the scenarios their
  own docstrings describe.
- `trading_gates.LiveTradingGate.check()` — gate ordering, prod-base check via
  the actual client instance (not a separately re-read env var), and
  LIVE_TRADING_ENABLED secondary interlock are all correctly implemented; this
  gate does not itself include a position-count/exposure check (that is a
  separate, and per Findings 1/2, incomplete, layer).
- `tracker.audit_settlement()`'s daily HIGH/LOW branch (commit `e0fd1cc0`):
  reads Kalshi's own `expiration_value` directly, cond_type guard restored,
  between-market handling present — no correctness issue found; this is a
  calibration/audit path, not a live-trading gate.
