# Pass 22b — Independent Re-verification of Pass 10 "Failure Modes" Raw Findings (7 findings)

Skeptical re-verification of the 7-finding raw JSON supplied this session (a superset of
the 5 findings already checked in `pass22_failure_modes_verification.md` — this file adds
independent verification of the 2 new findings, "Ambiguous place_order() failure" and
"paper.py cross-process lock fails open", plus re-confirms the other 5 against current
code, and adds one material correction on finding 5's exact mechanism).

## Finding 1: Ambiguous place_order() failure — CONFIRMED
- kalshi_client.py:517-534 `place_order()`: `except Exception as exc:` block calls
  `_find_order_by_client_id(client_order_id)`; if `existing` is falsy, `raise exc` (line 534)
  — re-raises the original exception.
- kalshi_client.py:551-608 `_find_order_by_client_id`: 3 sequential lookups (open orders
  L560, executed-status GET L572, canceled-status GET L590), each wrapped in its own
  `try/except Exception as _e:` that logs a warning and falls through — a failed lookup is
  indistinguishable from "found nothing". If all 3 raise, function returns `None` at L608.
- order_executor.py `_place_live_order` (L1644-1685): pre-logs `status="pending"` (L1650)
  before calling `client.place_order`; on exception, `execution_log.log_order_result(log_id,
  status="failed", error=str(exc))` (L1679-1683). Same pattern in main.py `cmd_order`
  (L4743-4756: pending pre-log not shown here but the `except Exception as e:` at L4753
  writes `status="failed"` at L4754).
- execution_log.py: grepped all 4 dedup functions — `was_recently_ordered` (L278-297,
  `status != 'failed'`), `was_traded_today` (L300-325, `status NOT IN ('failed','canceled',
  'cancelled')`), `was_ordered_this_cycle` (L328-340, `status != 'failed'`),
  `was_ordered_recently` (L343-380, `status NOT IN ('failed','canceled','cancelled')`) —
  all 4 confirmed to exclude 'failed' rows from their dedup WHERE clauses.
- order_executor.py `_recover_pending_orders` (L269-355): filter is
  `o.get("status") == "pending"` (L280) — confirmed 'failed' rows are never in the `pending`
  list this function reconciles; no other function in the file re-checks 'failed' rows
  against the Kalshi API.
- Full chain independently traced and matches the finding's description exactly.
- Verdict: CONFIRMED, MEDIUM confidence (matches original), E1 (static code read only —
  no live client available in this worktree to reproduce a real correlated-outage scenario).

## Finding 2: cmd_watch --live position-protection unguarded — CONFIRMED
- main.py:3759-3790 `if live:` block (4 calls: `_poll_pending_orders`,
  `_reprice_or_cancel_pending_orders`, `_check_live_position_exits`,
  `_check_live_model_exits`) has zero try/except.
- Immediately below in the same function, paper-side blocks ARE guarded: main.py:3792-3810
  (`except Exception as _alert_exc:`), 3822-3850 (`except Exception as _sl_exc:`),
  3861-3889 (`except Exception as _model_exit_exc:`) — each with an explicit comment about
  "silently and permanently kill[ing]" the check for the rest of the loop.
- Outer loop (main.py:3575-3911) catches only `except KeyboardInterrupt:` at L3911.
- order_executor.py:1376-1446 `_check_live_position_exits`: read in full — zero try/except
  anywhere in the function body; calls `store.save_peak`/`store.exit` per position
  unguarded, so a failure on one position's DB/network op aborts the whole scan.
- cron.py:912-923: the equivalent pair of calls (`_check_live_position_exits`,
  `_check_live_model_exits`) IS wrapped in `try/except Exception as _live_exit_exc:` —
  confirms the gap is cmd_watch-specific, not codebase-wide (direct diff-by-reading).
- Verdict: CONFIRMED, VERY HIGH confidence (matches original), E1.

## Finding 3: cmd_order unmatched-sell settlement fallback — CONFIRMED
- main.py:4806-4835 `elif action == "sell":` unmatched-sell branch: calls
  `record_live_early_exit(row_id, price, "unmatched_sell", 0.0)` (L4823) inside
  `try/except Exception as _settle_err:` (L4820-4829) that only logs a warning — no retry,
  no alternate fail-closed handling. Comment at L4807-4819 explicitly states the row was
  written as `live=True/status='filled'/settled_at=NULL/closes_position_id=None` and must
  not be left in that shape.
- execution_log.py:535-556 `get_filled_unsettled_live_orders()`: WHERE clause is
  `live = 1 AND status = 'filled' AND settled_at IS NULL AND closes_position_id IS NULL` —
  confirmed this is exactly the row shape that would remain if the settle call at L4823
  fails, and confirmed this function's callers would treat such a row as an open position.
- Verdict: CONFIRMED, HIGH confidence (matches original), E1.

## Finding 4: Settlement-lag force-close is paper-only — CONFIRMED
- cron.py:1434-1497: full block read. Imports `paper.close_paper_early`/
  `paper.get_open_trades` (L1455-1456); builds `_open_by_ticker` exclusively from
  `paper.get_open_trades()` (L1458); matches settlement signals only against that dict.
- Grep for `settlement_signal|read_settlement_signals` across the whole repo: only
  cron.py (consumer), settlement_monitor.py (producer), web_app.py (read-only display),
  plus tests/docs/graphify artifacts — zero matches in order_executor.py or positions.py.
- Verdict: CONFIRMED, HIGH confidence (matches original), E1.

## Finding 5: settlement_monitor.py DEBUG-level per-city failure logging — CONFIRMED, with a material correction to the stated mechanism
- settlement_monitor.py:591-592 (`except Exception as exc: _log.debug(...)`) and
  settlement_monitor.py:599-600 (same pattern) confirmed as the only two exception
  handlers in `run_settlement_monitor`'s polling loop (full L515-608 read).
- Commit `64c08693` (2026-08-10, `git show --stat` verified) confirmed to schedule
  settlement_monitor.py as a real unattended daily task (schtasks registration), so the
  DEBUG-only handling is no longer dormant/manual-only.
- **Correction to the finding's own mechanism claim**: the finding states these lines
  "reach bot.log but are invisible during an interactive run" (i.e., a console-vs-file
  visibility gap only). I verified this is not the actual mechanism. main.py:9460-9492
  `_setup_logging()` sets `root.setLevel(logging.INFO)` (L9475) — this determines the
  *effective level* inherited by `settlement_monitor.py`'s `_log = logging.getLogger(__name__)`
  (no explicit level of its own), which is INFO, not DEBUG. Worse: main.py:9556 calls
  `logging.disable(logging.DEBUG)` globally whenever `--debug` is NOT passed (the normal/
  scheduled-task case) — this is a *global* kill-switch that suppresses all DEBUG-and-below
  log calls application-wide, at the logging-record-creation stage, before any handler
  (file or console) is even considered. I reproduced this exact effective-level behavior
  directly:
  ```
  py -c "import logging; root=logging.getLogger(); root.setLevel(logging.INFO); \
         child=logging.getLogger('settlement_monitor'); \
         print(child.getEffectiveLevel(), child.isEnabledFor(logging.DEBUG))"
  # -> 20 False
  ```
  So under normal (non `--debug`) operation these `_log.debug()` calls are full no-ops:
  they never reach bot.log OR the console. The finding's claimed remedy (bump DEBUG→WARNING)
  is still correct and still matches the analogous fix already applied elsewhere
  (cron.py:2053-2058, verbatim comment: "a DEBUG line 6 days apart is effectively
  invisible" — that fix uses `_log.warning`, which is NOT suppressed by
  `logging.disable(logging.DEBUG)` and would additionally surface on console since the
  console handler is INFO-level). Net effect: the underlying operability gap is real and,
  if anything, worse than described (total silence, not just console-invisibility) — this
  strengthens rather than weakens the finding's recommendation, but the finding's own
  stated evidence path ("routes DEBUG to the file handler... console handler is INFO") is
  factually incorrect about where these particular log calls actually go.
- Verdict: CONFIRMED (core problem and fix recommendation both hold), confidence raised to
  VERY HIGH (reproduced the actual mechanism, which is stronger evidence than the
  original's own static-only claim), evidence_level E2 (ran a reproduction of the exact
  logging behavior, not just a static read).

## Finding 6: paper.py cross-process ledger lock fails open after 10s — CONFIRMED
- paper.py:142-221 `_CrossProcessDataLock` class read in full.
- `_acquire_file_lock` (L171-199): win32-only path (L172-173 returns immediately as a
  no-op on non-Windows — this worktree's host is win32, so the guarded path is live here).
  `deadline = time.monotonic() + 10.0` (L180); on `OSError` from `msvcrt.locking` past the
  deadline, logs `_log.warning("...contended >10s — proceeding without it this call")`
  (L188-191), closes the file handle, and `return`s — i.e. proceeds WITHOUT the lock held,
  confirmed no exception is raised and no retry beyond the 10s loop.
- Confirmed `paper.is_paused_drawdown` (L626), `is_streak_paused` (L2436), and
  `get_open_trades` (L1299) exist in paper.py as claimed, all reading the same
  lock-protected ledger that `trading_gates.LiveTradingGate.check()` depends on
  transitively (per recon's already-verified gate-chain trace).
- Verdict: CONFIRMED, HIGH confidence (matches original), E1 — connection to a
  demonstrated live-gate failure remains structural/static only, as the original honestly
  disclosed (no live client available to reproduce >10s contention against a real gate
  check in this worktree).

## Finding 7: execution_log.py/tracker.py never call con.close() — CONFIRMED
- execution_log.py:108-113 `_conn()` returns raw `sqlite3.connect(DB_PATH, timeout=30)`.
  Grep counts: 21 `with _conn() as con:` sites, 0 `con.close()` calls in the whole file
  (independently re-counted this pass, matches finding's numbers exactly).
- tracker.py:413-419 `_conn()` returns raw `sqlite3.connect(DB_PATH)`. Grep counts: 105
  `with _conn() as con:` sites, 0 `con.close()` calls (re-counted, matches exactly).
- `sqlite3.Connection.__exit__` only commits/rolls back the transaction, does not close
  the connection — standard, documented CPython `sqlite3` module behavior.
- Verdict: CONFIRMED, HIGH confidence (matches original), E1.

## Summary
All 7 findings CONFIRMED. No findings disproven. One finding (5) had its confidence
raised and evidence upgraded to E2 after a reproduction revealed the actual suppression
mechanism (`logging.disable(logging.DEBUG)` + INFO-level root logger) is total log-call
suppression, not merely a console-vs-file visibility gap as originally stated — the
underlying operability concern and recommended fix both survive and are, if anything,
strengthened by this correction.
