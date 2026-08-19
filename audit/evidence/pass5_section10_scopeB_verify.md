# Pass 5 — Section 10 / Scope B: Independent Verification

Verifier pass over 4 raw findings from Pass 5 (Feature Integration). All four
CONFIRMED against current HEAD (`d190d09d`). No disprovals.

## 1. portfolio_var() VaR gate blind to execution_log live positions
- order_executor.py:2364 `_open_trades_list = get_open_trades()` (imported from
  `paper` at line 2313) confirmed feeding directly into `portfolio_var(_open_trades_list
  + [candidate])` at order_executor.py:2930.
- paper.get_open_trades() (paper.py:1299-1301) confirmed to read only
  `_load()["trades"]` (paper_trades.json) — no execution_log reference.
- Confirmed the only other caller of `simulate_portfolio` is `main.py:8592
  cmd_montecarlo`, explicitly paper-only display command ("Run 1000 Monte Carlo
  simulations on the current open paper positions", uses `paper.get_open_trades`
  directly, prints results, no gating effect).
- Status: CONFIRMED. E1 static trace, matches original claim exactly.

## 2. Startup banner misidentifies which commands can place live orders
- main.py:9567 confirmed: `_live_orders_possible = cmd == "watch" and "--auto" in
  args and "--live" in args`, with the false-branch message "Live orders are NOT
  placed by this command — only `watch --auto --live` can" (line ~9578).
- Confirmed two independent `pre_live_trade_check(client)` call sites bypass this
  entirely: main.py:4531 inside `cmd_order` (guarded by `_is_live = getattr(client,
  "base_url", None) != DEMO_BASE` at line 4528), and main.py:2478 inside
  `_quick_paper_buy`'s maker-order branch (guarded identically at line 2477).
  Both reach a real order path independent of `cmd == "watch"`.
- Status: CONFIRMED. E1, exact line/logic match.

## 3. paper.check_position_limits blind to execution_log live positions
- Read full body of check_position_limits (paper.py:3447-3688) and all five
  exposure helpers (get_city_date_exposure, get_directional_exposure,
  get_total_exposure, get_ticker_exposure, get_correlated_exposure,
  paper.py:1598-1660) — confirmed every one sources exclusively from
  `get_open_trades()` → paper_trades.json; zero references to execution_log in
  any of these functions.
- Confirmed backlog.txt already documents this exact gap (lines 1908-2060,
  "EXPOSURE CAPS ARE STRUCTURALLY BLIND", "confirmed EMPIRICALLY MOOT today: zero
  live=1 rows have ever existed").
- Status: CONFIRMED. E1, exact match, correctly flagged as already-tracked not novel.

## 4. settlement_monitor METAR force-close gate structurally dormant
- Read `_calibrate_metar_settlement_confidence` (settlement_monitor.py:277-323)
  and `_dynamic_lock_in_confidence` (metar.py:31-56); confirmed hard [0.72, 0.97]
  bound in code (metar.py:54: `round(min(0.97, max(0.72, conf)), 3)`).
- Confirmed cron.py's force-close gate literally checks `if _sig_conf >= 0.80`
  (cron.py ~line 1470) against paper trades via `close_paper_early` — the >=0.80
  gate is real and present.
- **Independently re-derived the numeric claim** (not just trusted the code
  comment): wrote and ran a standalone Python script applying the exact beta-
  calibration formula (`sigmoid(a*ln(s) - b*ln(1-s) + c)`, a=b=0.2262, c=0.4001,
  as cited in the comment) across the full raw-confidence domain [0.72, 0.97]:
  - max calibrated YES-lock confidence = **0.76610** (comment claims ~0.766)
  - max calibrated NO-lock confidence = **0.59537** (comment claims ~0.595)
  Both independently computed maxima are below the 0.80 gate threshold, matching
  the finding's conclusion exactly. This upgrades evidence level from the
  original's E1 (comment-trust) to **E2** (reproducible, actually executed).
- Limitation: could not verify the on-disk fitted (a,b,c) values themselves match
  a=0.2262/c=0.4001 in this worktree (no metar_calibration.json present, paths.py
  resolves to main clone's data/ which was deliberately not touched). Relied on
  the values as documented in the code comment; the math built on top of them
  checks out exactly.
- Status: CONFIRMED, upgraded to E2.

No files modified outside audit/. No live credentials used or sought.
