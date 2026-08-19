# Pass 22c — Independent Re-verification of Pass 10 "Failure Modes" Raw Findings

All 7 raw findings independently re-checked against current source (not against the
finding's own description, and not by reading prior pass22/pass22b verification files
until after forming my own conclusions). Note: audit/evidence/pass22_failure_modes_verification.md
and pass22b_failure_modes_verification.md already exist from earlier verification passes on
what appears to be an overlapping/identical finding set — spot-checked after my own read and
findings converge (same CONFIRMED verdicts for the cmd_watch and cmd_order findings).

## Finding 1 — Ambiguous place_order() failure — CONFIRMED, HIGH, E1
- kalshi_client.py:517-534 `place_order`: except block calls `_find_order_by_client_id`,
  re-raises original exception only if `existing` is None. Confirmed.
- kalshi_client.py:551-608 `_find_order_by_client_id`: 3 sequential lookup passes (open
  orders / executed / canceled), each independently wraps its own `try/except Exception`
  and falls through to "not found" on failure. Confirmed line-for-line.
- execution_log.py: grepped all 4 dedup functions — was_recently_ordered (278-297),
  was_traded_today (300-325), was_ordered_this_cycle (328-340), was_ordered_recently
  (343-380) — all exclude `status != 'failed'` / `status NOT IN ('failed', ...)`. Confirmed.
- order_executor.py:269-355 `_recover_pending_orders`: filters strictly `o.get("status") ==
  "pending"` (line 280); never revisits 'failed' rows. Confirmed.
- order_executor.py:1552-1685 `_place_live_order`: pre-logs status="pending" (line 1650)
  BEFORE calling client.place_order, then on exception sets status="failed" (line 1681) —
  so a row that hits this exact ambiguous-outcome path is explicitly overwritten from
  "pending" to "failed" and therefore never reaches `_recover_pending_orders`'s pending-only
  filter. Confirmed — same pattern independently present in main.py's cmd_order path
  (~4694-4756, log_order_result(..., status="failed", ...) at line 4754).
- Verdict: full call chain confirmed exactly as described. The residual uncertainty is only
  about how often the "original POST failed AND all 3 reconciliation GETs also failed"
  scenario occurs in production — a real but comparatively narrow trigger window. Confidence
  raised from MEDIUM (original) to HIGH given the mechanical chain is fully and precisely
  verified; the narrowness of the trigger is already captured in the original limitations text.

## Finding 2 — cmd_watch --live position-protection block unguarded — CONFIRMED, VERY HIGH, E1
- main.py:3759-3790 `if live:` block (4 calls: _poll_pending_orders,
  _reprice_or_cancel_pending_orders, _check_live_position_exits, _check_live_model_exits) —
  confirmed zero try/except surrounding it.
- Confirmed by contrast: the two blocks immediately following in the same function ARE
  guarded — price alerts (3792-3810, `except Exception as _alert_exc`), paper stop-
  loss/breakeven (3822-3850, `except Exception as _sl_exc`), model-exit/expiring (3861-3889,
  `except Exception as _model_exit_exc`).
- Outer `while True:` loop (3576) has only `except KeyboardInterrupt:` at 3911.
- order_executor.py:1376-1446 `_check_live_position_exits`: read in full, zero try/except in
  the function body.
- cron.py:912-923: confirmed the equivalent pair of calls (`_check_live_position_exits`,
  `_check_live_model_exits`) IS wrapped in `try/except Exception as _live_exit_exc` with a
  warning log — confirms the gap is cmd_watch-specific.
- Verdict: fully confirmed, structural and deterministic (independent of which specific
  exception fires first).

## Finding 3 — cmd_order unmatched-sell settlement fallback — CONFIRMED, HIGH, E1
- main.py:4806-4829 (`elif action == "sell":` unmatched-sell branch): confirmed
  `record_live_early_exit(row_id, price, "unmatched_sell", 0.0)` wrapped only in
  `except Exception as _settle_err: _log.warning(...)` — no retry, no alternate handling.
  The surrounding comment (4807-4819) explicitly documents the exact "would be misread ...
  as a brand-new entry" risk this call exists to prevent.
- execution_log.py:535-556 `get_filled_unsettled_live_orders`: confirmed WHERE clause
  `live = 1 AND status = 'filled' AND settled_at IS NULL AND closes_position_id IS NULL` —
  exactly the row shape a failed settle-call leaves behind.
- Verdict: fully confirmed as described.

## Finding 4 — Settlement-lag force-close wired to paper only — CONFIRMED, VERY HIGH, E1
- cron.py:1434-1497: confirmed the block's only data source is `paper.get_open_trades()` /
  `paper.close_paper_early`.
- Grepped `settlement_signal|read_settlement_signals` across order_executor.py, positions.py,
  main.py — zero matches (confirmed empty). web_app.py and settlement_monitor.py are the
  producer/display side only, cron.py is the sole consumer.
- settlement_monitor.py:277-359 `_calibrate_metar_settlement_confidence` docstring
  (verified verbatim, lines 304-318): "the calibrated output across that ENTIRE input range
  never exceeds ~0.766 for a YES-lock or ~0.595 for a NO-lock — both permanently below
  cron.py's >=0.80 force-close gate ... Confirmed via cron.log (no 'SETTLEMENT LAG signal'
  entries ever recorded) and via schtasks (the daily ... task was never registered on this
  machine)." This independently and more precisely corroborates the finding's own
  "financial_risk" dormancy claim — raising confidence to VERY HIGH.
- Verdict: confirmed exactly as described, with stronger evidence than the finding cited.

## Finding 5 — settlement_monitor.py DEBUG-only per-city failure logs — CONFIRMED, HIGH, E1
- settlement_monitor.py:591-592 (`except Exception as exc: _log.debug(...)` market-fetch)
  and :599-600 (`except Exception as exc: _log.debug(...)` per-city) — confirmed exact line
  numbers and DEBUG level, and confirmed these are the only two exception handlers in the
  polling loop (read 510-608 in full).
- main.py:9475-9490 logging setup: confirmed root at INFO (9475), file handler (RotatingFileHandler)
  at DEBUG (9481), console StreamHandler at INFO (9485) — DEBUG lines reach bot.log only.
- cron.py:2053-2058: confirmed the analogous ML-retrain block was deliberately bumped from
  debug to warning with an explicit "DEBUG line 6 days apart is effectively invisible" comment.
- Verdict: confirmed exactly as described, line numbers match precisely.

## Finding 6 — paper.py cross-process lock fails open after 10s — CONFIRMED (documented tradeoff), HIGH, E1
- paper.py:171-199 `_acquire_file_lock`: confirmed 10.0s deadline (line 180), fail-open
  warning-and-return on timeout (188-193, "proceeding without it this call"), and the
  explicit "Never let the locking mechanism itself take down trading" comment (197-198) on
  the broader except-and-continue fallback.
- Verdict: confirmed exactly as described; correctly framed by the original finding as a
  documented/intentional design tradeoff rather than a bug, flagged for completeness only.

## Finding 7 — execution_log.py / tracker.py never close SQLite connections — CONFIRMED, HIGH, E1
- Grepped both files: execution_log.py has exactly 21 `with _conn() as con:` blocks and 0
  `con.close()` calls; tracker.py has exactly 105 and 0, respectively — both counts match
  the finding exactly.
- execution_log.py:108-113 `_conn()`: confirmed `sqlite3.connect(DB_PATH, timeout=30)`, a
  raw connection object with no pooling/wrapper.
- Verdict: confirmed exactly as described. Standard, correctly-characterized sqlite3
  semantics (the `with` context manager only manages the transaction, not the connection
  lifetime) — low practical impact under CPython refcounting as the finding itself notes.

## Summary
7/7 findings CONFIRMED against current source. No findings disproven or downgraded;
finding 1 confidence raised MEDIUM→HIGH and finding 4 raised HIGH→VERY HIGH based on
additional/stronger evidence found during this pass (finding 4's docstring corroboration
in particular is more precise than the original finding's own citation).
