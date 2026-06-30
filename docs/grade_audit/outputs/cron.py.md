# Grade Audit — cron.py

**Graded by:** claude-sonnet-4-6  
**Date:** 2026-06-29  
**File:** `cron.py` (2406 lines)  
**Test files read:** test_cron_integration.py, test_cron_lock.py, test_cron_trade_updates.py, test_main_cron_smoke.py

---

## TIER 1 Functions

---

### [cron.py] _cmd_cron_body() L:441–2292  ★ T1

```
Score: 6/10  |  Confidence: Confirmed
AC: FAIL AC1 — no per-order kill switch check inside _auto_place_trades; checked once
    before placement block (L:1676) but not per-signal.
    PASS AC2 — same-day/multi-day caps enforced independently in _auto_place_trades.
    PASS AC3 — strong_opps.sort(key=_kelly_sort_key, reverse=True) at L:1671–1672.
    PASS AC4 — auto_settle_paper_trades delegates to tracker (1h gate) then settle_paper_trade;
    no 24h gate on settlement path (but this is consistent with design intent — 24h gate is
    for early-exit mechanisms, not outcome-based settlement post-finalization).
    PASS AC5 — run_black_swan_check called with client=client; Brier check inside alerts.py
    uses brier_score() with default min_days_out=1. No explicit arg passed but default is correct.
    PASS AC6 — L:806: _err.get("multiday_directional_accuracy") — correct dict key confirmed.
    PASS AC7 — count_settled_predictions() (multi-day view) at L:1752, calibrate_and_save()
    at L:1770, sentinel write at L:1783 — all three steps present.
Red flag: RF1 (partial) — L:1491-1503: outer except TimeoutError block contains dead code.
    The inner TimeoutError handler at L:1475 catches and does NOT re-raise, so the outer
    except TimeoutError at L:1491 never executes. The _log.error() at L:1493 is dead. This
    is not a silent swallow (the inner handler does log), but the dead code is misleading.
    Also L:590: bare `except: pass` on SAME_DAY_RESERVE reminder — trivially Tier-2 path.
Invariants:
  I1 PASS — calibration uses count_settled_predictions() (multiday view L:1752)
  I2 N/A — cron body does not own the data lock; paper.py functions own it
  I3 N/A — cron body delegates atomic writes to safe_io.atomic_write_json
  I4 POSSIBLE — auto_settle_paper_trades has no 24h gate; settles on outcome availability.
    Likely intentional: 1h finalization gate in sync_outcomes ensures stability; the 24h gate
    is for early-exit mechanisms (stop-loss) not outcome-based settlement.
  I5 N/A — Kelly formula lives in order_executor, not cron body
  I8 PASS — drawdown check is in _auto_place_trades (is_paused_drawdown)
  I9 PASS — days_out carried from analyze_trade into signal dict and into _auto_place_trades
STRENGTHS:
• L:1671–1672: signals sorted by Kelly descending before cap consumption — correct AC3.
• L:1676–1681: second kill switch check before placement block — good defense in depth.
• L:1274–1279: kill switch checked per-future in analysis loop — breaks scan on mid-run activation.
• L:1253: _reset_gate_counts() called before parallel analysis pool — gate stats are per-scan.
• L:1236–1250: ticker deduplication before analysis prevents duplicate order attempts.
• L:1747: PYTEST_CURRENT_TEST guard prevents auto-calibration from firing in tests.
• L:536-537: pre-scan settlement failure logged at WARNING — operator can see it.
• L:1878-1882: stop-loss exception logged at ERROR — correctly escalated.
WEAKNESSES:
• L:1491–1503: outer except TimeoutError block contains dead code. After pass on L:1492
  the _log.error() at L:1493 IS reachable (pass is a no-op), BUT the outer except block
  can never fire because the inner handler at L:1475 already consumed the TimeoutError
  without re-raise. The log at L:1493 is unreachable dead code. The comment "already
  handled inside pool block above" confirms the author's intent, but the _log.error call
  creates confusion about double-logging. Verified: inner handler logs at ERROR (L:1476),
  outer handler can never fire — the log at L:1493 is dead.
• L:1676–1681: kill switch check before placement block does NOT fulfill AC1 completely.
  If 5 strong signals are queued and the kill switch is activated after order 1 is placed,
  orders 2–5 still execute because _auto_place_trades has no per-signal kill switch check.
• L:2048: graduation toast message hardcodes Brier threshold "≤ 0.20" but graduation gate
  is ≤ 0.23 (per memory notes 9650708). Stale display string — non-fatal but misleading.
• L:590: bare `except: pass` swallows SAME_DAY_RESERVE reminder errors with no log.
  Low severity (display-only path) but still RF1-adjacent.
• L:624: EMOS reminder `except: pass` similarly bare — again display-only, low severity.
• Function is 1852 lines. Cognitive complexity makes it hard to audit cold.
FAILURE SCENARIO:
  Kill switch activated mid-placement: user has 4 strong signals queued. Signal 1 is placed
  (real money if live). While order_executor._auto_place_trades is processing signal 2, the
  kill switch file is written (manually or by black swan). Signals 2-4 still execute because
  _auto_place_trades loops all opps without checking KILL_SWITCH_PATH between placements.
  This is the exact scenario AC1 describes. Cost: up to 3 unintended live trades.
FIX (required if score ≤6):
  order_executor.py — inside the for-loop in _auto_place_trades, add before placement:
    from cron import KILL_SWITCH_PATH
    if KILL_SWITCH_PATH.exists():
        _log.warning("_auto_place_trades: kill switch activated mid-placement — stopping")
        break
  cron.py L:1492-1503 — remove the dead outer except TimeoutError block:
    Replace:
      except TimeoutError:
          pass  # already handled inside pool block above
          _log.error(...)
    With nothing (delete lines 1491-1503; the comment is already wrong).
VERDICT: fix before live — AC1 gap is a real money risk in live mode; dead-code block
  is a maintenance hazard.
```

---

### [cron.py] cmd_cron() L:2334–2406  ★ T1

```
Score: 7/10  |  Confidence: Confirmed
AC: PASS AC1 (partially — same gap as _cmd_cron_body; kill switch checked before placement but
    not per-order inside _auto_place_trades)
    N/A for AC2–AC7 (delegated to _cmd_cron_body)
Red flag: NONE
Invariants:
  I2 N/A — no direct data access
  I3 N/A — no JSON writes in this function
STRENGTHS:
• L:2354: lock acquisition fail → return/exit rather than proceed. Correct fail-closed.
• L:2363: KeyboardInterrupt caught separately with user-friendly log. Does not silently swallow.
• L:2367: ctx.clear_cron_running_flag() in finally — always cleans up even on exception.
• L:2404: ctx.release_cron_lock() called at end of finally — lock always released.
• L:2352: watchdog armed before lock acquisition — prevents infinite hang even in lock path.
• L:2383–2393: heartbeat JSON written in finally — survives exceptions.
• L:2400–2403: WAL checkpoint in finally — good maintenance practice.
WEAKNESSES:
• L:2371–2378: .cron_last_run write uses `__import__("datetime")` instead of the already-
  imported datetime at module level. Aesthetic only — functional.
• L:2405: `_sys.exit(0)` called after full scan when not in loop mode. Test code uses
  `try/except SystemExit` to handle this — it's documented behavior but makes unit testing
  awkward. Not a bug but worth noting.
• No test covers the KeyboardInterrupt path being cleaned up via lock release (though
  test_cron_lock_released_on_keyboard_interrupt covers the flag cleanup).
FAILURE SCENARIO:
  If ctx.release_cron_lock() itself raises an exception (rare: e.g., permission error on
  Windows), the exception propagates out of cmd_cron — but it's in the finally block.
  In practice _release_cron_lock has its own exception handler so this is benign.
VERDICT: keep as-is — solid wrapper; the AC1 gap is in _cmd_cron_body/_auto_place_trades.
```

---

### [cron.py] _acquire_cron_lock() L:170–250  ★ T1

```
Score: 9/10  |  Confidence: Confirmed
AC: N/A
Red flag: NONE
Invariants: N/A (lock utility, not a trading function)
STRENGTHS:
• L:197–210: corrupt lock → warning log + attempt unlink + return False. Correct fail-closed.
• L:212–231: PID-aware stale detection when psutil available. Falls back to age-based for
  psutil-unavailable environments. Both paths log at WARNING.
• L:246–250: outer except catches unexpected errors and returns False (fail-closed).
• L:188–190: safe defaults for pid/started_at/heartbeat before inner try — prevents NameError.
• Full test coverage: test_cron_lock.py covers fresh install, live PID, dead PID,
  no psutil, corrupt lock, and I/O error paths.
WEAKNESSES:
• L:243: lock data written without atomic write (plain Path.write_text). A crash between
  directory creation (L:237) and write_text (L:243) leaves a partial/empty lock file.
  On the next run, the empty file will fail JSON parse → fail-closed (safe). Low severity.
• L:238: `lock_data = {"pid": ..., "started_at": ..., "heartbeat": ...}` — heartbeat is
  set at acquisition time but never updated during the run. A long-running cron would show
  a stale heartbeat, making the 1800s psutil-unavailable guard less useful.
VERDICT: keep as-is — excellent fail-closed design with strong test coverage.
```

---

### [cron.py] _check_graduation_gate() L:288–308  ★ T1

```
Score: 7/10  |  Confidence: Confirmed
AC: N/A
Red flag: NONE
Invariants:
  I1 PASS — uses tracker.count_settled_predictions() which queries multiday_predictions view.
STRENGTHS:
• L:296: checks ENABLE_MICRO_LIVE env var — gate is a no-op in paper mode. Correct.
• L:302–308: raises RuntimeError with clear message including current count and threshold.
• Caller (_cmd_cron_body L:498) catches RuntimeError and returns None — correct abort path.
WEAKNESSES:
• L:302: uses tracker.count_settled_predictions() — but this is the total multi-day count,
  not the rolling last-N. The graduation check in paper.graduation_check() uses last_n=50
  Brier. This gate counts total, which may be overly permissive once the bot has many trades.
  Possible — both metrics serve different purposes; count gate is a baseline sanity check.
• Zero direct test coverage. Called through full cron integration tests only (which mock
  ENABLE_MICRO_LIVE as 'false' by default, so the gate logic is never exercised in tests).
FAILURE SCENARIO:
  When ENABLE_MICRO_LIVE='true' and count < MIN_BRIER_SAMPLES, the RuntimeError is raised
  correctly. But the gate is only tested indirectly — no test verifies the RuntimeError path.
VERDICT: keep as-is — logic is simple and correct; add a targeted unit test.
```

---

## Auto-calibration trigger (embedded in _cmd_cron_body L:1744–1797)

The auto-calibration block is assessed as part of _cmd_cron_body above (AC7 PASS). Individual assessment:

- **count_settled_predictions()** → multi-day only (multiday_predictions view) ✓  
- **calibrate_and_save()** called ✓  
- Sentinel written after successful calibration ✓  
- Cache invalidation: immediately pushes new weights into running _wm module ✓  
- PYTEST_CURRENT_TEST guard prevents test contamination ✓  

Score for this sub-block inline with _cmd_cron_body score.

---

### [cron.py] Ensemble pin auto-renewal (embedded in _cmd_cron_body L:856–898)  ★ T1

This block is assessed within _cmd_cron_body. Isolated assessment:

```
AC6 PASS — L:805: _err.get("multiday_directional_accuracy") — correct key.
Logic: pin renewed if < 48h remaining OR pin missing, but ONLY if da >= 0.70.
If da < 0.70: logs WARNING and skips renewal — operator can see the model quality warning.
Gap: L:885 uses Path.write_text (not atomic_write_json) for strategy_pins.json.
A crash mid-write could corrupt the pins file. On restart, corrupt JSON triggers except
at L:866 → _pins = {} → _should_renew = True → tries to renew again. Self-healing.
```

---

### [cron.py] Brier alert check (embedded in _cmd_cron_body L:1884–1916)  ★ T1

```
Score component (within _cmd_cron_body): Good
PASS: uses get_brier_over_time(weeks=3), checks last 2 consecutive weeks > BRIER_THRESH.
PASS: BRIER_ALERT_THRESHOLD from utils (not hardcoded).
PASS: Discord notification in nested try — failure doesn't block the alert log.
PASS: PYTEST_CURRENT_TEST guard prevents test contamination.
GAP: _log.debug on outer exception (L:1916) — if get_brier_over_time raises, failure is
invisible in production logs. Should be WARNING.
RF-adjacent: L:1913 bare `except: pass` on Discord notification swallows Discord errors.
Low severity (notification-only path).
```

---

## TIER 2 Functions

---

```
[cron.py] CronContext L:56–91  9/10 — Clean dataclass for dependency injection; all callables typed.  [Confidence: C]

[cron.py] _write_cron_running_flag() L:98–118  8/10 — Warns on fresh flag (double-execution detection); exception logged at WARNING; age check uses st_mtime which is reliable.  [Confidence: C]

[cron.py] _clear_cron_running_flag() L:122–127  8/10 — Simple unlink with exception swallow logged at WARNING.  [Confidence: C]

[cron.py] _check_startup_orders() L:130–158  7/10 — Scans last 50 orders for 5-min double-execution; exception logged at WARNING. Gap: timezone handling falls back to UTC-replace on naive datetimes, which may be wrong if execution_log stores local time.  [Confidence: P]

[cron.py] _release_cron_lock() L:254–258  9/10 — Simple unlink with exception logged at WARNING; missing_ok avoids FileNotFoundError on double-release.  [Confidence: C]

[cron.py] _is_cron_running() L:262–284  7/10 — Read-only PID-aware check; returns False on any error (safe default for callers). Gap: no log on corrupt lock — differs from _acquire_cron_lock behavior.  [Confidence: C]

[cron.py] _check_spend_cap_vs_balance() L:312–327  7/10 — Warns if MAX_DAILY_SPEND > balance; uses get_balance() directly (acceptable — this is a display warning, not a trade gate).  [Confidence: C]

[cron.py] _check_manual_override() L:330–355  7/10 — Returns True if valid override active; auto-clears expired files; exception caught at DEBUG only — expired-override failures are silent in production. Low severity.  [Confidence: C]

[cron.py] _check_prod_reminder() L:387–409  7/10 — Fires once per day after reminder date in prod mode; uses marker file to prevent repeat. Exception at debug level — a broken PROD_REMINDER_PATH would silently skip reminders. Acceptable for a notification-only path.  [Confidence: C]

[cron.py] check_market_anomalies() L:413–419  8/10 — Pure function; safe defaults (0.5) on missing keys; threshold defined as module constant. Has unit test in test_cron_integration.py.  [Confidence: C]

[cron.py] report_anomalies() L:423–437  8/10 — No-op on empty list; WARNING log at end. Has unit test. Minor: float formatting for raw_temp uses :.1f with no None guard (guarded by `if raw_temp is not None` — correct).  [Confidence: C]

[cron.py] _install_cron_watchdog() L:2300–2331  8/10 — Daemon thread hard-kills with os._exit after timeout_secs; CRON_WATCHDOG_SECS env var override; logs at CRITICAL before kill. Minor gap: no test coverage. The 720s default is configurable.  [Confidence: C]
```

---

## Dead Code / Dormant Notes

```
[cron.py] L:1491–1503 — outer except TimeoutError block: DEAD CODE (suspected dead code)
The inner except TimeoutError at L:1475 consumes the exception without re-raise; outer
handler can never fire. The _log.error() at L:1493 is unreachable. Comment "already
handled inside pool block above" confirms intent. Safe to delete L:1491–1503.

[cron.py] L:2048 — graduation toast message: STALE DISPLAY STRING
"Brier ≤ 0.20" is displayed but graduation gate is ≤ 0.23 (per commit 9650708).
Does not affect gate logic — display only. Should be updated for operator clarity.
```

---

## Summary Table

| Function | Tier | Score | Key Issue |
|---|---|---|---|
| `_cmd_cron_body()` | T1 | 6/10 | AC1 gap — no per-order kill switch in `_auto_place_trades` |
| `cmd_cron()` | T1 | 7/10 | Solid wrapper; inherits AC1 gap from body |
| `_acquire_cron_lock()` | T1 | 9/10 | Excellent fail-closed with full test coverage |
| `_check_graduation_gate()` | T1 | 7/10 | Logic correct; no direct unit test |
| `CronContext` | T2 | 9/10 | Clean DI dataclass |
| `_write_cron_running_flag()` | T2 | 8/10 | Good double-execution detection |
| `_clear_cron_running_flag()` | T2 | 8/10 | Correct |
| `_check_startup_orders()` | T2 | 7/10 | Timezone edge case possible |
| `_release_cron_lock()` | T2 | 9/10 | Correct |
| `_is_cron_running()` | T2 | 7/10 | No log on corrupt lock |
| `_check_spend_cap_vs_balance()` | T2 | 7/10 | Correct for reporting |
| `_check_manual_override()` | T2 | 7/10 | Exception at DEBUG |
| `_check_prod_reminder()` | T2 | 7/10 | Notification path |
| `check_market_anomalies()` | T2 | 8/10 | Has test; pure function |
| `report_anomalies()` | T2 | 8/10 | Has test; WARNING log |
| `_install_cron_watchdog()` | T2 | 8/10 | Correct watchdog pattern |

**File median: 7.5/10. The cron infrastructure (locks, watchdog, DI) is solid. The main trading path has one confirmed AC1 gap requiring a fix before live money.**
