# Batch 58: Live order-path integrity (MEDIUM/HIGH — touches real-money code)

## Context

Repo: weather1. Written 2026-08-24 against master `223dedadcfd2` — re-verify current before starting. Source: backlog.txt L25336, L25371, L24388, L24423, L24457, L24499, L27399, L26637 (all re-verified against live code during batch-48's backlog sweep, 2026-08-24; the file:line cites below were accurate at that hash).

Files owned: `kalshi_client.py`, `kalshi_ws.py`, `order_executor.py`, `execution_log.py`, `main.py` (`cmd_cancel` only). Parallel-safe with 57, 59-62.

**Live-trading state — read before touching anything:** `KALSHI_ENV=prod`, but `LIVE_TRADING_ENABLED` is unset and `ENABLE_MICRO_LIVE` is hardcoded `False`, so no path here places real orders today. That is exactly why these are safe to fix now and dangerous to leave: every item below is dormant-but-real, and flipping either flag arms them all at once. Treat this as live-money code regardless of the current flag state.

## Items

Ordered deliberately: 1-2 are the cheapest and most self-contained, 3-6 are the position-tracking cluster (do them together, they interact), 7-8 stand alone.

### 1. `order_id` flows unvalidated into 4 REST path segments [L25336]

**Files:** `kalshi_client.py:1233` (`get_order`), `:1243` (`cancel_order`), `:1314` (`amend_order`), `:855` (`get_order_queue_position`), plus `main.py`'s `cmd_cancel` (the raw-CLI-input path)

All four interpolate `order_id` into a URL path with no format check, mirroring the pattern AUD-0076 already fixed for `ticker`/`series_ticker`. `py main.py cancel <order_id>` passes argv straight through with zero normalization.

**Fix:** add an `order_id` format check mirroring `_validate_ticker_format` (`kalshi_client.py:369`) but with the correct charset — **verify Kalshi's real order_id format first** (grep live `execution_log.db` or a stored order response); it is a lowercase-hex UUID, not an uppercase ticker, so reusing the ticker regex will reject every real id.

**Also correct as part of this fix:** `get_live_weather_index`'s docstring (`kalshi_client.py:803`) claims it is "the one path-interpolating method in the file that had no equivalent guard." That was true when written and is now false — these four exist. Fix the claim in the same change.

### 2. `kalshi_ws.py` is hardcoded to the PROD WebSocket host [L25371]

**Files:** `kalshi_ws.py:28` (`_WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"`, used at `:354`). Zero `KALSHI_ENV` reads in the entire file.

Consumers are live: `order_executor.py:155-157` (`get_cached_book`) and `:3274-3276` (`get_cached_mid_price`). In demo mode, reprice/chase logic and the flash-crash circuit breaker consume **real production prices** — making demo-mode dry runs quietly misleading rather than unsafe.

**Fix:** read `KALSHI_ENV` and select the host the same way `KalshiClient.__init__` already does for REST. Mirror that existing selection logic rather than writing a second convention.

**Note:** this directly undercuts the DEMO_BASE smoke test (backlog L6585), which is a hard prerequisite before `ENABLE_MICRO_LIVE` is ever flipped on. A demo smoke test that silently reads prod prices does not validate what it claims to. Worth calling out in the resolution.

### 3. `get_live_pnl_summary()`'s `open_count` undercounts [L24388]

**Files:** `execution_log.py:1667-1673` (`SELECT COUNT(*) ... WHERE live = 1 AND status = 'pending'`), docstring `:1625`

This is the identical bug AUD-0009 already fixed for `_count_open_live_orders` — compare against `order_executor.py:2013-2022`, which now unions pending + `get_unknown_live_orders()` + `get_filled_unsettled_live_orders()`. Both gaps the original entry named (filled-unsettled AND unknown) are present here.

**Fix:** mirror `_count_open_live_orders`'s union. Update the docstring, which currently documents the wrong behavior as if intended.

### 4. `_exit_live_position`'s docstring contradicts its actual gate [L24423]

**Files:** `order_executor.py:2272` (calls the FULL `pre_live_trade_check(client)`), docstring `:2220-2224`

The docstring claims it "re-runs only the kill-switch/trading-paused gate" and is "deliberately NOT subject to the daily-loss/spend/max-open-position gates." The code runs the full `LiveTradingGate` (`trading_gates.py:143-150` → `check_or_raise()` → `graduation_check`, `is_accuracy_halted`, `is_daily_loss_halted`, `is_paused_drawdown`, `is_streak_paused`).

**Consequence:** once the daily-loss halt trips, every protective exit is silently disabled — the bot stops being able to close losing positions at exactly the moment it most needs to. Failure surfaces only as `_log.warning("[LiveExit] Gate blocked exit ...")` at `:2274`; no operator alert.

**Fix — this needs a real decision, not a mechanical edit.** Either (a) make the code match the docstring (exit path uses a reduced gate: kill-switch + trading-paused only, since exiting reduces risk), or (b) make the docstring match the code and add an operator alert when an exit is gate-blocked. **(a) is the behaviorally correct answer** — a kill switch exists to stop opening new risk, not to trap existing risk — but it changes live-trading behavior, so surface it via `AskUserQuestion` before implementing. Do not silently pick one.

**Related, same theme, different entry:** backlog L30045 (no operator path to close a position while the kill switch is engaged) is the dashboard/CLI half of this same design question, and is assigned to **batch 63** (the design batch). Coordinate — if 63 lands first, inherit its decision rather than re-deciding.

### 5. `'unknown'`-status live orders have no age cap or alert [L24457]

**Files:** `execution_log.py:893-911` (`get_unknown_live_orders()` — `SELECT * ... WHERE live = 1 AND status = 'unknown' ORDER BY placed_at`, unbounded, no age predicate), recovery loop `order_executor.py:696-790`

An order whose true state genuinely cannot be determined is re-checked forever at 3 authenticated GETs per recovery pass, with no escalation. The no-`client_order_id` dead-end branch only logs a warning and `continue`s. `alerts.py` has no unknown-order alert.

**Fix:** add an age threshold past which an unresolvable row raises an operator alert (mirror the existing alert conventions in `alerts.py`) and stop re-polling it every pass. Decide explicitly what the terminal state is — a row that can never be resolved should not stay `unknown` indefinitely.

### 6. Recovery re-walks full order history once PER unknown row [L24499]

**Files:** `order_executor.py:723` (`client._find_order_by_client_id(...)` inside the `for order in unknown:` loop at `:706`), `kalshi_client.py:1158` (its own 3-status paginated fetch per call)

N unknown rows = N full paginated history walks per recovery pass.

**Fix:** hoist to one fetch per pass, matching against all unknown rows in memory. Do this **together with item 5** — they touch the same loop, and 5's age cap bounds the worst case that makes 6 expensive.

### 7. `_amend_live_order`'s bookkeeping call nulls the old row's fields [L27399]

**Files:** `order_executor.py:1754` (`execution_log.log_order_result(row_id=replaces_order_id, status="amended")`), `execution_log.py:298-316`

`log_order_result` sets `response=?` and `fill_quantity=?` **unconditionally** (only `filled_at`/`market_mid_at_fill` use `COALESCE`). Calling it bare therefore wipes the amended-away order's recorded response and fill quantity. Same bug class the backlog records as "L-10(a)."

**Fix:** either pass the existing values through, or extend `log_order_result` to `COALESCE` these two the way it already does the other two. Prefer the latter — it fixes the class, not the instance. Grep every other bare `log_order_result` call for the same shape before deciding.

### 8. Entry-side taker fee never charged on an early exit [L26637]

**Files:** `execution_log.py:1477` (`pnl = round(gross_pnl - kalshi_taker_fee(clamped_fill_count, exit_price), 4)` — exit leg only), docstring `:1408-1444`

A taker-entered position closed via stop-loss/breakeven/model-exit/manual sell is charged only the exit-side fee. Natural settlement is unaffected. The function's own docstring already carries an explicit "KNOWN GAP … deliberately not fixed in this change" paragraph naming this backlog entry — so this is a deliberate deferral being picked up, not a newly-found bug.

**Fix:** charge the entry-side taker fee when the entry was a taker fill. **Verify the entry fill's maker/taker status is actually recorded** before assuming it can be read back — `get_fills` carries `is_taker`, but confirm the stored row retains it. If it does not, that gap is the real blocker and should be reported rather than worked around with an assumption.

**P&L consequence:** every affected historical row currently overstates realized P&L. Decide explicitly whether to backfill-correct stored rows or only fix forward, and state which in the resolution — a silent forward-only fix leaves the analytics corpus permanently inconsistent across a date boundary that nothing records.

## Process

Full 29-step workflow. **No LOW-tier downgrade** — every item is on a live-order or live-position-tracking path. Opus review at `effort: high`.

Given the size, consider splitting the review by subsystem (2 reviewers: items 1-2 API-surface, items 3-8 position/P&L bookkeeping) rather than one reviewer over all eight — see `memory/feedback_scale_review_to_change_size.md`.

**Items 4 and 8 require `AskUserQuestion` before implementation** (gate semantics; fee backfill scope). Do not default either.

Tests: scope to `tests/test_live_execution.py`, `tests/test_execution_log.py`, `tests/test_kalshi_client*.py`, `tests/test_order_executor*.py` — but grep `tests/` for each changed function name before finalizing. **Never run the bare full suite.**

Mock realism matters here: when mocking a Kalshi API response, use values the real exchange actually returns (`resting`/`canceled`/`executed` — never `"filled"`). A previously-shipped bug passed its first test suite precisely because the mock used a status string the API never emits.

Lint via the real pre-commit hook. Update all 8 backlog resolutions, run `python backlog_index.py`, confirm before committing.
