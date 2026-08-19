# Pass 10 — Failure Modes (Section 22)

Reliability-focused pass over execution_log.py, order_executor.py,
settlement_monitor.py, safe_io.py, kalshi_client.py, positions.py, cron.py,
main.py (cmd_watch/cmd_order), paper.py's cross-process lock. Investigated by
direct Read/Grep of current code + `git show` on the relevant recent commits
(cluster D live-fill routing, cluster A engine unification, cluster J
safe_io/atomic-write migration, cluster K EMOS/METAR calibration chain).

NOTE: `audit/evidence/pass22_failure_modes_verification.md` already exists in
this worktree — an independent re-verification of 5 findings from a prior,
separately-run "Pass 10." I independently re-derived and re-verified those
same 5 root causes myself this session (fresh grep/read, not copied), and
additionally found one new HIGH-severity finding (orphaned/untracked live
order on an ambiguous network failure during placement, F1 below) and one new
LOW finding (paper.py's cross-process file lock fails open after 10s
contention, F6 below) that the prior pass's evidence file does not mention.
Findings below are numbered independently of that file's numbering.

## F1 (NEW) — Ambiguous place_order() failure can leave a real live position permanently untracked and re-orderable

- kalshi_client.py:517-534 `place_order()`: on any exception from `self._post(...)`,
  calls `_find_order_by_client_id()` (lines 551-608) to check whether the
  order landed anyway despite the exception, before deciding whether to
  re-raise.
- `_find_order_by_client_id` makes 3 sequential API calls (resting via
  `get_open_orders()`, executed via a GET, canceled via a GET) — each
  wrapped in its own `except Exception as _e: _log.warning(...)` that
  swallows the failure and moves to the next pass (lines 559-567, 571-582,
  589-607). If ALL THREE also fail (plausible during a genuine sustained
  network/API outage — the same condition class that caused the original
  POST to raise), `_find_order_by_client_id` returns `None`, and
  `place_order()` re-raises the ORIGINAL exception (line 534: `raise exc`).
- The caller (order_executor.py `_place_live_order`, ~line 1670-1678, or
  main.py `cmd_order`, ~line 4750) catches this and calls
  `execution_log.log_order_result(log_id, status="failed", error=str(exc))`.
- Every dedup/anti-thrash guard in execution_log.py deliberately EXCLUDES
  `status='failed'` rows, by design, on the assumption "failed" means
  "genuinely never sent":
  - `was_recently_ordered` (execution_log.py:278-297): `status != 'failed'`
  - `was_ordered_this_cycle` (328-340): `status != 'failed'`
  - `was_traded_today` (300-325): `status NOT IN ('failed', 'canceled', 'cancelled')`
  - `was_ordered_recently` (343-380, the 7-day cross-run guard): same exclusion
- `_recover_pending_orders` (order_executor.py:269-355), the ONLY startup
  reconciliation mechanism against the Kalshi API, filters explicitly to
  `o.get("status") == "pending"` (line 280) — it never looks at `status
  == "failed"` rows, so a misclassified row is never automatically
  reconciled, even on the next process restart.
- Net effect: if the order actually reached Kalshi (accepted, resting or
  filled) but the client never received a usable response AND the 3-pass
  reconciliation also failed (a correlated/sustained connectivity problem,
  not a single blip), execution_log records this as a clean failure. The
  real position:
  1. Is invisible to `_get_live_open_positions()` (only reads
     `status='filled'`), so it receives ZERO automated stop-loss/breakeven/
     model-exit protection, indefinitely, until a human notices via
     Kalshi's own UI and manually reconciles.
  2. Is NOT protected against re-entry: every dedup guard above ignores the
     row, so a subsequent scan (same or later forecast cycle) can place a
     genuinely NEW order for the same ticker/side. Kalshi-side idempotency
     (`client_order_id`, derived from
     `ticker:side:action:count:price:cycle`) only protects a retry with the
     IDENTICAL price and cycle string — a retry at a different price
     (likely, since price moves) or in a later forecast cycle (a new
     `cycle` string) produces a different `client_order_id`, so Kalshi will
     NOT dedupe it. This can double real financial exposure on the same
     signal, with neither copy under automated protection.
- Scope: this is a `kalshi_client.py`/`execution_log.py` interaction that
  predates the 2026-08 commit window but is squarely inside cluster D's
  domain (live-fill/position tracking correctness) which received 3 fix
  commits this window (`bb91374f`, `105cf4ce`, `e5331a8d`) for adjacent bugs
  in the same subsystem — none of those 3 commits touch this specific gap.
- Type: RELIABILITY / DATA_INTEGRITY. Severity: HIGH (real, untracked,
  unprotected live exposure + possible silent double-exposure). Confidence:
  MEDIUM (well-reasoned static trace of a real code path, but the precise
  triggering network-outage shape was not reproduced live — no live
  credentials in this worktree per the audit's own constraints).
  Evidence level: E1.
- Recommendation: `_recover_pending_orders` (or a sibling function) should
  also periodically re-check `status='failed'` live-order rows that have no
  confirmed Kalshi-side outcome (or `place_order` should mark such
  ambiguous failures with a distinct status, e.g. `"unknown"`, rather than
  overloading "failed" for both "never sent" and "sent, outcome unknown" —
  the two need different dedup treatment).

## F2 — cmd_watch `--live` position-protection block has zero exception handling; a single DB/network error kills the entire persistent watch process (re-verified)

- main.py ~3759-3790 (`if live:` block inside `cmd_watch`'s `while True:`
  loop) calls `_poll_pending_orders`, `_reprice_or_cancel_pending_orders`,
  `_check_live_position_exits`, `_check_live_model_exits` with no
  surrounding `try/except` — read directly, confirmed no guard exists.
  Immediately below, the paper-side equivalents at main.py:3822
  (`except Exception as _sl_exc`) and ~3861 (`except Exception as
  _model_exit_exc`) ARE guarded, with comments explicitly warning that a
  silent failure here "could permanently and invisibly stop" checks.
- The outer loop (main.py:3575 `while True:` ... :3911 `except
  KeyboardInterrupt:`) catches nothing but `KeyboardInterrupt`.
- `order_executor.py` `_check_live_position_exits` (1376-1446): confirmed no
  try/except anywhere in the function body. It calls
  `positions.update_peak_profits` → `store.save_peak` →
  `execution_log.update_live_peak_profit` (a bare, unguarded SQL UPDATE,
  execution_log.py:577-598) for every position with an improved peak, and
  `store.exit()` → `_exit_live_position` (which itself only catches
  `RuntimeError` for the settlement-race case, not other exception types)
  for every triggered ticker. A single unhandled exception from ANY of
  these — e.g. a `sqlite3.OperationalError` from a locked/full DB, or a
  `requests` exception from `_get_current_book` — aborts the whole
  function, so positions later in the same `by_ticker` loop (not just the
  one that failed) also get skipped this cycle, and the exception then
  propagates uncaught to cmd_watch's loop, killing the whole process.
- `order_executor.py` `_check_live_model_exits` (1448-1536): `positions =
  _get_live_open_positions()` (1465) and `markets = get_weather_markets(client)`
  (1469) execute before the function's own `try:` (starts 1483) — a DB or
  network failure there is likewise unguarded and propagates the same way.
- Contrast: `cron.py:912-923` wraps the equivalent
  `_check_live_position_exits`/`_check_live_model_exits` pair in `except
  Exception as _live_exit_exc: _log.warning(...)` — confirming the gap is
  cmd_watch-specific. Cron's failure mode is bounded (skip this scheduled
  run, retry on the next scheduled invocation, since cron is a fresh
  process each run); cmd_watch's is not (the process itself dies, and
  because cmd_watch is meant to run indefinitely as the live operator's
  interactive session, nothing automatically restarts it — every open live
  position goes unprotected until a human notices and manually restarts).
- Type: RELIABILITY. Severity: HIGH. Confidence: VERY HIGH. Evidence: E1
  (full read of both call chains).
- What state is the system left in after the failure: cmd_watch's process
  exits (uncaught exception → Python traceback, process terminates); every
  live position that was open at that moment keeps its Kalshi-side
  exposure completely unmanaged (no stop-loss, no breakeven, no model-exit)
  until an operator notices the process died and restarts it.

## F3 — cmd_order manual-sell bookkeeping failure leaves the exact phantom-position shape the fix was designed to prevent

- main.py ~4806-4829 (`elif action == "sell":` branch, the "unmatched sell"
  case added by `e5331a8d`): when a live sell has no matching tracked
  position, the code immediately calls `record_live_early_exit(row_id,
  price, "unmatched_sell", 0.0)` specifically so the just-logged row
  (`live=True, status='filled', settled_at=NULL, closes_position_id=None`)
  is not misread as a new open position by the next protective-exit scan —
  the comment states this explicitly ("worse than the original bug this
  fix resolves, not just a repeat of it").
- That call is wrapped in `except Exception as _settle_err:
  _log.warning(...)` with NO retry and no alternate fail-closed mechanism
  (main.py ~4820-4829). If the DB write fails (lock contention, disk
  issue), the row is left in EXACTLY the dangerous shape the fix
  documents: `get_filled_unsettled_live_orders()` will surface it as an
  open long position on the very next cycle, and the automated exit
  scanner will attempt a REAL protective sell against a position that was
  already manually closed on the exchange — repeating indefinitely every
  cron/watch cycle (a low-grade "retry storm" of one spurious exit attempt
  per cycle) until an operator manually settles the row.
- The sibling `record_live_exit_fill` call (~4780-4805, the matched-close
  path) has the same broad-except/no-retry shape, but is lower risk since a
  failure there just leaves an already-tracked position looking "still
  open" (the pre-existing, already-understood failure mode) rather than
  fabricating a new phantom one.
- Type: RELIABILITY / DATA_INTEGRITY. Severity: MEDIUM (requires both a
  manual `cmd_order` sell of an untracked ticker AND a DB write failure at
  that exact moment — narrow window, but the consequence is a real
  recurring spurious live order attempt, not just a logging gap).
  Confidence: HIGH. Evidence: E1.

## F4 — Settlement-lag force-close signal only ever wired to paper positions

- cron.py 1434-1497: the entire settlement-lag force-close block imports
  `paper.close_paper_early`/`paper.get_open_trades` and matches signals
  only against `_open_by_ticker` built from `paper.get_open_trades()`
  (cron.py:1458).
- Grep for `settlement_signal|read_settlement_signals` across
  order_executor.py, positions.py, main.py: zero matches outside cron.py
  (consumer), settlement_monitor.py (producer), web_app.py (read-only
  display).
- A live position sitting through the same between-bucket/METAR-lag window
  gets no equivalent automated force-close, even though the underlying
  METAR signal is exactly as applicable to a live position as a paper one.
- Also (settlement_monitor.py:277-359 docstring, self-documented and
  verified against `cron.log`/`schtasks` per the file's own comment): the
  calibrated confidence for this signal is currently bounded below cron's
  own >=0.80 force-close gate under the real fitted METAR model, so the
  mechanism is presently dormant for paper too — not a live behavior
  regression today, but the live-position gap would persist even once the
  gate/calibration mismatch above is fixed.
- Type: FEATURE_DEPENDENCY / DESIGN_CONCERN. Severity: MEDIUM (currently
  dormant in practice per the confidence-bound finding, but is a real gap
  that would activate silently for paper only, never live, the moment
  METAR calibration coefficients drift). Confidence: HIGH. Evidence: E1.

## F5 — settlement_monitor.py per-city polling errors logged at DEBUG only

- settlement_monitor.py:591-592 (market-fetch failure) and 599-600
  (general per-city error) are the only two exception handlers in
  `run_settlement_monitor`'s polling loop, both `_log.debug(...)`.
- main.py's logging setup (~9475-9490) sets the root logger and file
  handler to `INFO`/`DEBUG` respectively but the CONSOLE handler to `INFO`
  (~9485) — so these lines DO reach bot.log (file handler is DEBUG), but
  are invisible on an operator's console during an interactive run, and
  easy to miss in a log file without deliberately grepping for them. A
  sustained per-city failure (e.g. a bad METAR station code, or a
  persistent network issue affecting one city) would silently disable
  settlement monitoring for that city for the whole 2-hour window with no
  console-visible trace.
- Commit `64c08693` (2026-08-10) scheduled this as a real daily cron task
  (`schtasks`), so this is no longer dormant/manual-only code — it now runs
  unattended daily, making silent per-city failures more consequential
  than when the module was manual-invocation-only.
- An analogous fix pattern exists elsewhere in the same commit window:
  cron.py:2053-2058 (ML-retrain block) was deliberately "bumped from debug
  to warning" with the comment "a DEBUG line 6 days apart is effectively
  invisible" — the same reasoning applies here but was not applied to
  settlement_monitor.py.
- Type: OBSERVABILITY / RELIABILITY. Severity: LOW-MEDIUM (file-logged, not
  fully silent, but easy to miss for an unattended daily task). Confidence:
  HIGH. Evidence: E1.

## F6 (NEW) — paper.py's cross-process ledger lock fails OPEN after 10s of contention, not closed

- paper.py:171-197 `_CrossProcessDataLock._acquire_file_lock`: on Windows,
  attempts `msvcrt.locking(..., LK_NBLCK, 1)` in a loop with a hard 10s
  deadline (`deadline = time.monotonic() + 10.0`, line 176). If contention
  persists past 10s, it logs a WARNING ("proceeding without it this call",
  line 187-190) and returns WITHOUT the lock held — the caller's
  read-modify-write on `paper_trades.json` then proceeds completely
  unprotected against a concurrent writer (e.g. cron and a simultaneously
  running `watch --auto`), the exact race this lock exists to prevent.
  Comment at line 195-197 states this is intentional ("Never let the
  locking mechanism itself take down trading").
- This is a documented, deliberate design tradeoff, not an oversight — but
  it means sustained lock contention (>10s) silently degrades to the
  pre-lock behavior: a lost update to the paper ledger (e.g. one process's
  trade write or peak-profit update overwritten by another's stale read).
  Since `paper.is_paused_drawdown()`/`is_streak_paused()` (both read from
  this same ledger) feed directly into `trading_gates.LiveTradingGate.check()`,
  a corrupted/lost paper-ledger update could — in the degraded window only
  — cause the live-trading gate to evaluate against a stale or incomplete
  paper P&L/streak state. This worktree cannot construct a live client to
  observe the gate's live behavior, so this is a static, structural
  observation about the dependency, not a demonstrated live-gate failure.
- Type: RELIABILITY / DESIGN_CONCERN. Severity: LOW (documented, bounded to
  a 10s contention window, and paper.py's own docstring shows the tradeoff
  was consciously made). Confidence: HIGH (static read). Evidence: E1.

## F7 — execution_log.py / tracker.py never explicitly close SQLite connections

- execution_log.py:108-113 `_conn()` returns a raw `sqlite3.connect(...)`.
  21 `with _conn() as con:` call sites in the file, 0 `con.close()` calls.
  tracker.py's own `_conn()` (line 413) shows the same pattern (105 call
  sites, 0 closes). `sqlite3.Connection.__exit__` only commits/rolls back
  the transaction — it does not close the connection (standard, documented
  sqlite3 module behavior).
- In CPython, the connection object is typically finalized promptly via
  refcounting once the local `con` goes out of scope at function return, so
  this is a long-standing, low-practical-impact pattern rather than an
  active leak under normal CPython execution — but it is not guaranteed by
  the `with` idiom itself, and would matter more under a non-refcounting
  Python implementation or if a caller ever captured `con` beyond the
  `with` block's own scope.
- Type: RELIABILITY / IMPROVEMENT. Severity: LOW. Confidence: HIGH.
  Evidence: E1.

## Summary

7 findings total (2 new to this session's independent pass: F1 HIGH, F6
LOW; the remaining 5 independently re-derived and corroborated against a
prior pass's already-verified findings, with additional trigger/root-cause
detail added for F2 and F3 beyond what the prior verification file
captured). No swallowed-exception issue was found in the safe_io.py
atomic-write path itself (retry/emergency-copy/fsync logic is unusually
well-hardened, with explicit prior opus-review fix history for the
mutation-tested edge cases I checked — tmp-file naming collisions,
caller-name attribution, worst-case latency budgeting). kalshi_client.py's
retry/circuit-breaker/timeout layer is similarly well-designed (POST
deliberately excluded from auto-retry, deterministic idempotency keys,
pagination cursor-repeat guards) — F1 is the one gap found in that layer,
specifically in the failure-reconciliation path's own failure mode.

All findings are E1 (static code reading); none were exercised at runtime
this pass (no live Kalshi credentials in this worktree, consistent with the
audit's stated constraints). No findings required or received any repo
mutation — read-only investigation throughout.
