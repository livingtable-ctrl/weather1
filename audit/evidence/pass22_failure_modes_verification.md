# Pass 22 — Verification of Pass 10 "Failure Modes" Findings

Independent re-verification of 5 raw findings from Pass 10. All 5 confirmed against
current code (no disproven findings this pass).

## Finding 1: cmd_watch live position-protection calls unguarded — CONFIRMED
- main.py:3759-3790 (`if live:` block) has zero try/except around
  `_poll_pending_orders`, `_reprice_or_cancel_pending_orders`,
  `_check_live_position_exits`, `_check_live_model_exits`.
- Immediately below, paper-side checks at main.py:3822 (`try:`/`except Exception as _sl_exc:`)
  and main.py:3861 (`try:`/`except Exception as _model_exit_exc:`) ARE guarded, with
  comments explicitly describing the "silent pass would silently and permanently kill"
  risk class.
- Outer loop wraps only `except KeyboardInterrupt:` at main.py:3911 (loop starts main.py:3575).
- order_executor.py:1376-1446 `_check_live_position_exits`: confirmed zero try/except
  anywhere in the function body (read in full).
- order_executor.py:1448-1536 `_check_live_model_exits`: try starts at line 1483; lines
  1465 (`_get_live_open_positions()`) and 1469 (`get_weather_markets(client)`) execute
  unguarded before the try.
- order_executor.py:1290-1298 docstring comment (inside `_exit_live_position`) verbatim
  confirms the crash-the-whole-process risk was already known and documented for the
  RuntimeError-race case specifically.
- cron.py:912-923 confirmed to wrap the equivalent `_check_live_position_exits`/
  `_check_live_model_exits` calls in `try/except Exception as _live_exit_exc:` —
  confirms the gap is cmd_watch-specific, not codebase-wide.
- Verdict: CONFIRMED, VERY HIGH confidence, E1 (static read of full call chain).

## Finding 2: cmd_order unmatched-sell/exit-fill bookkeeping broad except, no retry — CONFIRMED
- main.py:4780-4805 (`record_live_exit_fill` call): wrapped in broad `except Exception as
  _live_rec_err:`, logs warning "check execution_log manually", no retry.
- main.py:4806-4837 (`record_live_early_exit` unmatched-sell fallback): wrapped in broad
  `except Exception as _settle_err:` at 4820-4829, same pattern.
- execution_log.py:734 `record_live_exit_fill` confirmed to raise `RuntimeError` at
  lines 787/798 specifically for the concurrent-settlement race — cmd_order's broad
  `except Exception` catches this AND any other exception type identically, unlike
  order_executor.py's own narrower `except RuntimeError as _race_err:` (order_executor.py:1303).
- cmd_order is confirmed one-shot (CLI command, returns after this block) — no
  cron/watch-style next-cycle retry exists for this path.
- Verdict: CONFIRMED, HIGH confidence, E1.

## Finding 3: Settlement-lag force-close is paper-only — CONFIRMED
- cron.py:1434-1497 confirmed: entire block imports `paper.close_paper_early`/
  `paper.get_open_trades`, matches signals only against `_open_by_ticker` built from
  `paper.get_open_trades()` (cron.py:1458).
- Grep for `settlement_signal|read_settlement_signals` across order_executor.py,
  positions.py, main.py: zero matches. Only cron.py (consumer), settlement_monitor.py
  (producer), web_app.py reference it at all.
- Verdict: CONFIRMED, HIGH confidence, E1.

## Finding 4: settlement_monitor.py DEBUG-level exception logging — CONFIRMED
- settlement_monitor.py:591-592 (`except Exception as exc: _log.debug(...)`) and
  settlement_monitor.py:599-600 (same pattern) confirmed as the only two exception
  handlers in the polling loop, both DEBUG level.
- Commit 64c08693 (2026-08-10) confirmed via `git show --stat` to add scheduled daily
  schtasks registration for this task — no longer dormant.
- Analogous WARNING-level fix-pattern confirmed to exist elsewhere in the same window:
  cron.py:2053-2058 ML-retrain block, comment verbatim: "Bumped from debug to warning...
  a DEBUG line 6 days apart is effectively invisible."
- Verdict: CONFIRMED, HIGH confidence, E1.

## Finding 5: execution_log.py/tracker.py never call con.close() — CONFIRMED
- execution_log.py:107-113 `_conn()` returns a raw `sqlite3.connect(...)` object.
  Grep: 21 `with _conn() as con:` call sites, 0 `con.close()` calls in the whole file.
- tracker.py:413 `_conn()` — 105 `with _conn() as con:` call sites, 0 `con.close()`
  calls in the whole file.
- No `atexit` registration or other close mechanism found in either file.
- Python's `sqlite3.Connection.__exit__` only commits/rolls back the transaction; it
  does not close the connection (confirmed against known sqlite3 module semantics —
  this is standard, documented behavior, not a guess).
- Verdict: CONFIRMED as a real (long-standing, low-severity) pattern. Reliance on
  CPython refcounting for prompt close is real but not something the `with` idiom
  itself guarantees.

## Summary
5/5 findings survive verification with no downgrades or disproofs. All evidence
remains E1 (static code reading) — none were executed this pass; execution against
findings 1 and 2 would require a live client this worktree cannot construct (no
credentials), consistent with the original pass's own stated limitations.
