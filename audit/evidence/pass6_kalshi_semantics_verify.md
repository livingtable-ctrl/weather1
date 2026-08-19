# Pass 6 — Kalshi Semantics — Independent Verification

All 5 raw findings independently re-derived from current source (not trusted from
the original claim text). All CONFIRMED, none disproven.

## F1: Settlement PnL uses maker fee ($0) for taker (IOC) entries
- order_executor.py:432-433 `from utils import KALSHI_MAKER_FEE_RATE as _fee` used
  unconditionally in `_poll_pending_orders` settlement formula (~L566-580).
- `execution_log.get_filled_unsettled_live_orders()` (execution_log.py:535-556)
  query has no maker/taker distinction — any live/filled/settled_at-NULL/
  closes_position_id-NULL row qualifies, regardless of origin.
- main.py:4702-4711 (post e5331a8d) — cmd_order live buys always
  `time_in_force="immediate_or_cancel"` (taker).
- order_executor.py:989-1015 `_reprice_or_cancel_pending_orders`'s taker-cross
  fallback (`_clears_taker_fee` gate at line 635) independently places entry
  replacements with `time_in_force="immediate_or_cancel"` — pre-existing gap,
  not introduced by e5331a8d.
- Contrast: `execution_log.record_live_exit_fill` (execution_log.py:734-804) DOES
  use real `KALSHI_FEE_RATE` (0.07) for exits, explicitly documented as
  IOC-only reasoning (L742-750) — confirms devs treated IOC=taker correctly on
  the exit side but never revisited the entry-side settlement formula.
- tests/test_live_execution.py:983,1057,1123 assert the $0-fee formula exactly
  as claimed — current intended/tested behavior.
- Verdict: CONFIRMED, E1 (static, multi-site corroborated).

## F2: check_position_limits blind to live positions
- paper.py get_open_trades (1299-1301), get_total_exposure (1620-1623),
  get_ticker_exposure, check_position_limits (~3629-3665) all source only
  `_load()['trades']` (paper.py's JSON ledger). No `execution_log` import
  in paper.py except in comments (grep confirmed).
- main.py:4546-4576 confirms cmd_order's live buy path calls
  `paper.check_position_limits` as its sole exposure gate.
- backlog.txt:1910,1999 confirms a matching pre-filed entry
  ("EXPOSURE CAPS ARE STRUCTURALLY BLIND...").
- Verdict: CONFIRMED, E1.

## F3: No automated reconciliation vs client.get_positions()
- `grep get_positions(` — only two matches outside tests: definition
  (kalshi_client.py:450) and the sole caller (output_formatters.py:426).
- output_formatters.cmd_positions is dispatched only from main.py's manual CLI
  branch (`elif cmd == "positions": cmd_positions(client)`, main.py:9694-9695),
  not from cron.py/trade_cycle.py/order_executor.py.
- Verdict: CONFIRMED, E1.

## F4: cmd_order sell only closes oldest of multiple same-ticker/side positions
- main.py:4609-4630 confirmed verbatim — `_live_open_matches[0]` selected,
  warning printed listing count and untouched positions, matching in-code
  "Opus review (2026-08-17), NEW-M1" comment cited by the finding.
- Verdict: CONFIRMED, E1.

## F5: cmd_order has no local price-range validation
- main.py:4333-4356 (cmd_order) validates count only (whole number >= 1);
  no `0 < price` / `<= 1` check anywhere before place_order() call
  (grep across full cmd_order body confirmed no such check).
- Contrast confirmed: web_app.py:2995-2996 does
  `if not (0.0 < exit_price <= 1.0): return 400`.
- Verdict: CONFIRMED, E1.

## F6: cmd_order writes order_type=action ("buy"/"sell") vs schema's market/limit
- execution_log.py:135 schema comment: `-- "market" or "limit"`.
- order_executor.py 6 call sites (737,836,1241,1649,3088,3258) all pass
  literal "limit"/"market".
- main.py:4658 `order_type=action` confirmed exact.
- `git log -S "order_type=action" -- main.py` → only 1e3faca6 (Apr 2026)
  introduces the string; `git show e5331a8d -- main.py` diff shows the
  log_order() call was rewritten (new kwargs added) but `order_type=action`
  carried through unchanged — confirms "re-touched without fixing" claim.
- No SELECT/read of `order_type` found anywhere (grep across execution_log.py,
  web_app.py, output_formatters.py) — dormant data-quality issue, no active
  consumer, as the finding itself states.
- Verdict: CONFIRMED, E1.

## Summary
6/6 raw findings independently confirmed against current code with no material
discrepancies in line numbers, mechanism, or severity framing. No findings
disproven or downgraded.
