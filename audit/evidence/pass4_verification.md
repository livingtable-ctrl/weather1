# Pass 4 — Feature Correctness: Independent Verification

All 4 findings independently re-checked against current code (read-only, no execution).

## 1. Exposure caps blind to execution_log live positions — CONFIRMED
- `order_executor._auto_place_trades`: `_open_trades_list = get_open_trades()` (order_executor.py:2364) sources
  `open_tickers`, `_open_trade_sides`, `_multiday_date_counts`, and feeds `portfolio_kelly_fraction`/`corr_kelly_scale`
  (order_executor.py:2774-2779) — all paper-ledger only. `execution_log.was_ordered_recently(ticker, days=7)`
  (order_executor.py:2699) is the only execution_log touch in this whole function, and it's a narrow 7-day
  same-ticker dedup, not a general exposure/concentration check.
- `paper.check_position_limits` (paper.py:3447-3489): `existing_cost = sum(... for t in get_open_trades() ...)`,
  city/date/directional/correlated caps (paper.py:3653-3682) all keyed off the same paper-only `get_open_trades()`.
  No `execution_log` import/reference anywhere in the function body.
- `paper.get_open_trades()` (paper.py:1299-1301) reads only `_load()["trades"]` (paper_trades.json). No merge.
- `main.cmd_order` (main.py:4544-4572) calls `check_position_limits` for `action == "buy"` regardless of
  `_is_live` (determined earlier at main.py:4528 via `client.base_url != DEMO_BASE`) — i.e. this same blind
  gate is the one applied to real live buys via cmd_order.
- Verdict: claim fully accurate as described. CONFIRMED, E1 (static, this-session verified).

## 2. KALSHI_ENV=prod banner still wrong about which commands can place live orders — CONFIRMED
- main.py:9567: `_live_orders_possible = cmd == "watch" and "--auto" in args and "--live" in args`.
- main.py:4528: `_is_live = getattr(client, "base_url", None) != DEMO_BASE`, computed unconditionally inside
  `cmd_order`, reachable via plain `main.py order <ticker> buy/sell ...`.
- main.py:4530-4536: when `_is_live`, `pre_live_trade_check(client)` is called; on success execution continues to
  a real `client.place_order(..., time_in_force="immediate_or_cancel")` further down (confirmed present later
  in cmd_order body).
- So the banner's "only watch --auto --live can place live orders" is demonstrably false for cmd_order.
- Verdict: CONFIRMED, E1.

## 3. trade_cycle.py net_edge fallback diverges from validate()'s edge default — CONFIRMED
- trade_cycle.py:466-469: `net_edge = analysis.get("net_edge"); if None: net_edge = analysis.get("edge"); if None: net_edge = 0.0`.
- order_executor.py:2011-2013: `edge = opp.get("net_edge"); if edge is None: edge = 0.0` — no fallback to raw `edge`.
- trade_cycle.py:658-671 contains an in-code comment explicitly acknowledging this exact divergence and arguing
  it's permissive-only (verified verbatim, matches finding's description closely).
- Verdict: CONFIRMED as described; genuinely a residual, self-documented, LOW-severity display/placement drift.
  Did not additionally verify reachability (whether analyze_trade() ever actually omits net_edge while setting
  edge) — same limitation the original finding disclosed.

## 4. Far-tail rain blend tilt under-applied for short tails — CONFIRMED
- acis_precip.py:499: `shifted = [max(0.0, s + damped_shift_in) for s in remaining_sums]` — floor-at-0.0 additive
  shift, asymmetric for a mostly-zero distribution.
- weather_markets.py:8858-8878 (far-case block, tail_sums path) calls this on `tail_sums`, with an in-code
  comment (8859-8873) that verbatim matches the finding's characterization ("mostly exact zeros... dry SEAS5
  tilt gets clipped... Not fixed here... shadow-only").
- Confirmed log-only / shadow-only: `combined_totals` (far-case tilted tail) only feeds
  `forecast_blend_signal["rain_forecast_blend_prob"]` (weather_markets.py:8912-8933), a separate, clearly
  metadata/logging dict. `blended_prob` (weather_markets.py:8941-8943, the value that actually drives
  rec_side/sizing) is computed from `remaining_sums_tilted` from a different, earlier call (line 8737) — not
  from the far-case `combined_totals`/`tail_sums_tilted` at all.
- Verdict: CONFIRMED, E1, INFO severity as originally stated is appropriate.

## Summary
All 4 findings from the raw pass survive independent re-verification unchanged in substance. No downgrades,
no disproven claims. Only refinement: confidence/evidence levels affirmed rather than changed, since I
independently re-read every cited line rather than trusting the original description.
