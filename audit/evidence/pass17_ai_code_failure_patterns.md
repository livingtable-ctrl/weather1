# Pass 17 — AI-Code Failure Patterns — Evidence Notes

## Finding 1: VaR pre-trade gate (`portfolio_var`/MAX_VAR_DOLLARS) is structurally blind to real live positions from prior cycles
- order_executor.py:2364 `_open_trades_list = get_open_trades()` (paper.py:1299, paper_trades.json only)
- order_executor.py:2920-2930 candidate dict built and passed to `portfolio_var(_open_trades_list + [candidate])`
- order_executor.py:3037-3057 "F6" comment: live orders placed *within the same cycle* are appended to `_open_trades_list` in-memory, but the list is never seeded from `order_executor._get_live_open_positions()` / `execution_log.get_filled_unsettled_live_orders()` at the top of the function.
- backlog.txt lines 555-690 (resolution note for 6364b38b) explicitly frames Site 2 (monte_carlo.py) as reaching "a real live-trade-gating decision" via this exact call chain, without flagging that the gate's own input list excludes all live positions opened in earlier cycles.
- `_get_live_open_positions()` exists (order_executor.py:1077) and is the established adapter for live positions elsewhere (LivePositionStore, _check_live_position_exits) but is never merged into `_open_trades_list` here.
- utils.py:300 `MAX_VAR_DOLLARS = float(os.getenv("MAX_VAR_DOLLARS", "200.0"))` — gate active by default.

## Finding 2: Stale docstring in kalshi_client.py after e5331a8d added a live IOC caller
- kalshi_client.py line ~583 (_find_order_by_client_id): "no live caller uses IOC/FOK today (all pass good_till_canceled)" — added 2026-07-09, never updated.
- e5331a8d (2026-08-17) added `time_in_force="immediate_or_cancel"` for live orders in main.py's cmd_order (and order_executor._exit_live_position already used IOC before that). Comment now false.

## Finding 3: metar.py fetch_metar_daily_extreme docstring stale after b0f4cad2 added a third caller
- metar.py line ~402-404: "Both current callers (settlement_monitor.py, weather_markets.py's _metar_lock_in)"
- b0f4cad2 (2026-08-17) added a third caller in weather_markets.py's `_compute_persistence_prob` (weather_markets.py:6137), not reflected in the docstring.

## Finding 4: cmd_order's "unmatched live sell" placeholder pnl=0.0 lands in tax/P&L exports as if it were a real (zero) P&L
- main.py (e5331a8d): `record_live_early_exit(row_id, price, "unmatched_sell", 0.0)` — documented as "pnl unknown ... 0.0 is a neutral placeholder, not a real P&L claim"
- execution_log.export_live_tax_csv / get_live_pnl_summary filter on settled_at IS NOT NULL, pnl IS NOT NULL with no way to distinguish a "real $0 outcome" from "unknown, placeholder $0" — narrow edge case (manual live sell against an untracked position), documented but consumer-facing distortion not addressed.
