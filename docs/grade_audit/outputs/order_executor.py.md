# Grade Audit — order_executor.py
Generated: 2026-06-29

---

## TIER 1 Functions

---

### `place_paper_order()` L:94–96  ★ T1

```
[order_executor.py] place_paper_order() L:94–96  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: AC2 N/A (shim — delegates entirely to paper.place_paper_order which owns field validation)
    AC3 N/A (shim)
Red flag: NONE
Invariants: I3 N/A (write happens inside paper.place_paper_order), I10 N/A (shim — paper guards env)
STRENGTHS:
• Module-level shim pattern is correct — tests can monkeypatch "order_executor.place_paper_order"
  without patching the paper module directly, preventing cross-test contamination.
• No business logic here; all delegation. Any bug is in paper.place_paper_order, not here.
WEAKNESSES:
• line 95: If paper.place_paper_order raises, the exception propagates raw to the caller.
  _auto_place_trades catches this (L1495), so no silent failure in practice.
  Minor: no re-raise wrapper or type annotation on return value — caller must know it returns a dict.
VERDICT: keep as-is
```

---

### `_place_live_order()` L:345–448  ★ T1

```
[order_executor.py] _place_live_order() L:345–448  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: AC1 PASS — record is only written after confirmed API success (step 6 on success path);
       pre-log at step 5 is "pending", updated to "placed" only on success or "failed" on exception.
    AC2 N/A — _place_live_order does not write to paper_trades.json; writes to execution_log only.
    AC3 FAIL AC3 — "if execution_log.was_ordered_this_cycle(ticker, side, cycle):" at L404
       checks for cycle dedup before pre-logging, but there is no check for client_order_id
       after placement. If the API succeeds but log_order_result(status="placed") crashes,
       a subsequent retry attempt finds no "placed" row, passes the was_ordered_this_cycle
       check (still "pending"), and issues a second order. However _recover_pending_orders()
       handles this on the NEXT startup — not within the same cron cycle.
Red flag: NONE
Invariants:
  I5 PASS — price guard: "if price <= 0: return False, 0.0" at L396; market bid/ask presence
     checked at L387-393; quantity guard "if quantity <= 0: return False, 0.0" at L399.
  I8 PASS — _place_live_order does not call get_balance(); gating uses execution_log.get_today_live_loss()
     and _count_open_live_orders() — both from execution_log, not paper balance.
  I10 PASS — function is only reachable from _auto_place_trades when live=True; trading_gates.pre_live_trade_check()
     is called first at L361.
STRENGTHS:
• Pre-log before API call (L411–421) is exactly right: crash between pre-log and API call leaves a
  "pending" row that _recover_pending_orders() can reconcile on startup.
• Guard hierarchy is clean: graduation gate → daily loss → open positions → size → dedup → pre-log → API.
• Exception handler at L441–447 marks the row "failed" AND prints visibly — no silent failure.
• The H-5 guard (L387-393) prevents fabricated 50¢ midpoint when market dict has no bid/ask.
WEAKNESSES:
• line 376: "_count_open_live_orders() >= config['max_open_positions']" — KeyError if
  live_config is passed without 'max_open_positions'. The daily_loss_limit path (L367) uses
  .get() with default; the max_open_positions path does not. One missing key crashes the guard
  path before the trade is logged.
• line 404: Cycle dedup is checked AFTER pre-log at L411, but the was_ordered_this_cycle check
  at L404 is BEFORE pre-log. That's correct. However there is a second was_ordered_this_cycle
  check in _auto_place_trades at L1272 — the redundant check is fine defensively but comments
  would clarify intent.
• AC3 gap: within-cycle double-placement if log_order_result crashes between API success and status update.
  This is a narrow race window (< 1ms), but it exists.
FAILURE SCENARIO:
  live_config supplied without 'max_open_positions' key → KeyError at L376 → function raises
  unhandled → caller (_auto_place_trades) does not catch it (only catches Exception at L1495 for
  the paper path; live path catches return values not exceptions from _place_live_order) →
  entire _auto_place_trades call stack raises, skipping all subsequent signals.
  Actual risk: low because live_config is assembled in cmd_cron with all required fields, but
  not validated at this call site.
VERDICT: fix before live (add .get() for max_open_positions)
```

---

### `_auto_place_trades()` L:849–1619  ★ T1

```
[order_executor.py] _auto_place_trades() L:849–1619  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: AC1 PASS — paper path: pre-log at L1373 with status="pending"; place_paper_order at L1384;
       log_order_result(status="filled") at L1423 only on success. Exception path at L1495
       marks row "failed". Phantom position is impossible.
    AC2 PASS — place_paper_order called at L1384 with: days_out=int(a.get("days_out", 1)) at L1402,
       close_time=m.get("close_time") at L1399, rec_side at L1384, entry_price/cost computed
       at L1350/L1402 (cost derived inside paper.place_paper_order from price×qty).
       All four required fields thread through.
    AC3 PASS — execution_log.was_traded_today() at L1062 and was_ordered_this_cycle() at L1272
       together prevent duplicate placement within a day/cycle. Pre-log status "pending" is
       updated to either "filled" or "failed" — was_traded_today() filters out "failed" rows
       (confirmed in test_dedup.py), so a crash-and-retry scenario allows re-placement of
       truly failed orders without creating duplicates on success.
    AC4 PASS — _sameday_effective_cap() is present (L503) and called at L939; dormant because
       SAME_DAY_DYNAMIC_SLOTS=False and SAME_DAY_RESERVE_SLOTS<=0.
Red flag: NONE
Invariants:
  I2 POSSIBLE — _daily_paper_spend() and _daily_sameday_spend() call paper._load() without
     _DATA_LOCK (the lock lives in paper.py; these helpers are in order_executor.py). These
     are read-only calls used for gating decisions, not RMW cycles. Under Flask threading this
     could theoretically return a stale count if a concurrent write is mid-flight, but the bot
     runs as a single-threaded cron process during trade placement. Intentional design: these
     helpers are in order_executor.py and cannot import the lock without circular dependencies.
     Flagged as Possible — not deducted.
  I5 PASS — entry_price guarded: "if entry_price <= 0 or entry_price >= 1.0: continue" at L1198.
     kelly guard: "if adj_kelly < 0.002: continue" at L1112. qty guard: "if qty < 1: continue" at L1229.
  I8 PASS — drawdown gate uses paper.is_paused_drawdown() (which internally calls _drawdown_snapshot(),
     not raw get_balance()) at L876 and L1284. Spend tracking uses the computed entry_price × qty,
     not a balance read.
  I9 PASS — days_out is read from analysis dict a.get("days_out", 1) at L1089/L1293/L1402 and
     int()-cast. It is NOT re-derived. The default of 1 for missing days_out is conservative
     (treats legacy trades as multi-day).
  I10 PASS — live path only enters when "if live and live_config:" at L1301; _place_live_order
     is only called on that branch.
STRENGTHS:
• Per-iteration drawdown re-check at L1282–1290 is excellent — catches mid-cycle HALT breaches
  rather than only checking once at function entry.
• VaR gate at L1237–1268 adds portfolio-level risk check before each placement.
• L1-B price refresh at L1132–1165: re-fetches live market price, checks edge hasn't reversed
  (L1179–1191), falls back gracefully on client failure. Tested by test_execution_proof.py.
• Separate same-day/multi-day cap accounting is correctly implemented and well-commented.
• MicroLive sub-path at L1511–1609 has its own pre-log + result update pattern, consistent
  with the main live path.
• Dedup pipeline is thorough: open_tickers set → was_ordered_recently(7d) → was_traded_today → was_ordered_this_cycle.
WEAKNESSES:
• line 1301: The live path daily-spend update at L1340 (sameday_spent += cost) uses the value
  returned by _place_live_order as "cost", but _place_live_order returns (placed, dollar_cost)
  where dollar_cost = round(quantity * price, 2) from the live execution price. If the order
  partially fills at a different price, cost is pre-fill-estimate, not actual fill cost. The
  gap is minor (GTC orders fill at limit price) but not documented.
• line 1399: close_time=m.get("close_time") — uses market dict 'm', not analysis dict 'a'.
  In flat-dict mode (item is not a tuple), m=item=a, so this resolves correctly. In tuple mode,
  'm' is the market dict which should have close_time. However, at L1153 the analysis dict 'a'
  is replaced with a fresh market dict merged in: "a = {**a, 'market': _fresh_market, ...}".
  The close_time still comes from original 'm' at L1399, not from the refreshed market in 'a'.
  If the market close_time changed between analysis and execution (unusual but possible on
  Kalshi with rolling markets), the stale close_time is stored. Low severity.
• line 893–898: _open_trade_sides dict is built from paper_trades at function entry and is
  NOT re-read after each placement. The flip-warning at L1032–1048 correctly compares against
  the side stored when the trade was opened. The local update at L1343/1410 keeps it consistent
  for subsequent iterations.
• Function is 770 lines — logic is correct but hard to audit in one pass. No comment explaining
  the overall state machine (pre-trade gates → sizing → placement → post-placement bookkeeping).
FAILURE SCENARIO:
  If is_daily_loss_halted() raises (e.g. file I/O error reading loss_limit_override.json) at
  L879, _auto_place_trades returns early rather than propagating — "is_daily_loss_halted(client)"
  is called without a try/except at L879. The exception would propagate to cmd_cron's caller,
  causing the entire cron cycle to fail with zero trades placed and no log entry. The halted
  check is imported from paper at L879 — paper.is_daily_loss_halted normally catches its own
  I/O errors, but any unhandled exception propagates here.
VERDICT: keep as-is (file size is a maintainability concern, not a correctness bug; see G2/G3)
```

---

## TIER 2 Functions

---

```
[order_executor.py] _in_gfs_update_window() L:53–68  9/10 — Correct guard with env-configurable lockout; handles all four GFS init hours; tested (test_execution_stability.py); minor gap: reloads env var only on module import, so runtime changes to GFS_LOCKOUT_MINS require restart (intentional given the module-level read).  [Confidence: Confirmed]
```

```
[order_executor.py] _current_forecast_cycle() L:77–85  8/10 — Correct NWS cycle computation (00z/12z); no error path; deterministic given UTC clock; no test coverage but logic is trivial (3 lines).  [Confidence: Confirmed]
```

```
[order_executor.py] place_paper_order() (shim) L:94–96  — graded above as TIER 1.
```

```
[order_executor.py] _midpoint_price() L:105–117  7/10 — Correctly computes midpoint for both YES and NO sides; inverted spread guard at L115 prevents bad price from propagating; returns a rounded float. Gap: if both yes_bid=0 and yes_ask=0 (no market data), returns 0.50 (defaults), which could mislead a caller that doesn't check for 0.50 as a sentinel. The H-5 guard in _place_live_order catches this before it reaches order placement. No unit test for the inverted spread guard.  [Confidence: Confirmed]
```

```
[order_executor.py] _count_open_live_orders() L:121–123  7/10 — Simple filter over execution_log; correct. Gap: limit=500 is hardcoded — if more than 500 recent orders exist, the count is silently wrong. RF5 candidate (hardcoded limit) but 500 is a display limit, not a trading threshold; no env var needed here. No unit test.  [Confidence: Confirmed]
```

```
[order_executor.py] _recover_pending_orders() L:132–196  7/10 — Crash recovery logic is correct and well-commented: fetches pending live rows, reconciles each against the Kalshi API, resolves status. Exception handler at L195 logs at WARNING — RF1 PASS. Gap: the "no order_id" path at L164 sets status="sent" with the comment "treated as sent to prevent duplicate" — the log message says "marked failed" but status is "sent". Minor inconsistency between log text and actual status; sent blocks dedup for 7 days which is the intent.  [Confidence: Confirmed]
```

```
[order_executor.py] _poll_pending_orders() L:209–341  6/10 — Settlement P&L math is correct for all four yes/no × win/lose combinations. Pre-close cancel logic is well-designed. Gap (RF1): L266–270 exception handler for pre-close cancel check fires at DEBUG level ("_log.debug"), not WARNING — an operator cannot see when pre-close cancel parsing is silently failing without enabling debug logging. The outer exception handler at L296 prints (not logs) — visible on console but not captured in log files. A print() is not a WARNING log. RF1 is borderline: the _log.debug at L266 swallows a potentially significant error (cannot determine if a trade should have been cancelled before expiry). Not promoting to TIER 1 because the function does not directly affect balance or sizing, only order lifecycle.  [Confidence: Confirmed]
FIX: order_executor.py:267 — change _log.debug to _log.warning for pre-close cancel check exception
FIX: order_executor.py:286 — change print() to _log.warning() for GTC cancel failure  
FIX: order_executor.py:297 — change print() to _log.warning() for poll order failure
FIX: order_executor.py:341 — change print() to _log.warning() for settlement check failure
```

```
[order_executor.py] _daily_paper_spend() L:457–474  7/10 — Correctly excludes same-day trades (days_out==0) from multi-day spend; legacy trades (days_out=None) treated as multi-day via "!= 0" comparison. Reads paper._load() without _DATA_LOCK — acceptable for a read-only gate function in single-threaded cron usage. No unit test.  [Confidence: Confirmed]
```

```
[order_executor.py] _daily_sameday_spend() L:478–494  7/10 — Symmetric to _daily_paper_spend(); uses strict equality "== 0" to exclude legacy (None) trades from same-day count. Correct design, well-commented.  [Confidence: Confirmed]
```

```
[order_executor.py] _sameday_effective_cap() L:503–584  — DORMANT (intentional)
Both SAME_DAY_DYNAMIC_SLOTS and SAME_DAY_RESERVE_SLOTS <=0 cause the fast-path return at L519.
Per preamble: activates at 150 same-day settled trades (~99 currently). Do not remove. Dynamic-mode
Bayesian blending logic is present and correct when activated. Fail-open pattern on all exceptions
is correct for a cap function.
```

```
[order_executor.py] _check_early_exits() L:593–706  7/10 — 24h settlement gate at L668–680 is correctly implemented (I4 PASS): hard-skips trades with missing close_time with a WARNING log (L663), parses close_time defensively (L674 handles ValueError/TypeError). 12h minimum hold time at L637–652 prevents GFS-intraday whipsawing. Exit price guard at L686–691 prevents recording max loss on missing market data. Gap: the outer exception handler at L699 logs at WARNING with traceback — correct for RF1 compliance. Minor: shift threshold 0.25 is hardcoded (L682) but this is a portfolio management threshold, not a trading edge threshold, so RF5 does not apply. No unit test covering the 24h gate or the 12h hold time.  [Confidence: Confirmed]
```

```
[order_executor.py] _validate_trade_opportunity() L:716–840  8/10 — Comprehensive pre-execution gate covering: system health, flash crash, edge direction, edge magnitude (with confidence tiering and A/B test), Kelly minimum, ticker presence, data freshness. All exception handlers log at WARNING or DEBUG with reasons. A/B variant failure at L809 is caught and logged at DEBUG — RF1 borderline but DEBUG is acceptable for an optimization feature, not a safety gate. Gap: WebSocket cache lookup failure at L741 logs at DEBUG — correct (WS is optional enrichment). Confidence tiering (L786–793) catches exception and falls back to PAPER_MIN_EDGE — correct.  [Confidence: Confirmed]
```

```
[order_executor.py] _is_still_live() (nested in _auto_place_trades) L:925–931  8/10 — Defensive datetime parse; returns True (safe default) on any parse failure; correctly handles missing close_time by returning True (live). No test for this nested function directly, but covered implicitly by _auto_place_trades tests.  [Confidence: Confirmed]
```

---

## Summary Table

| Function | Tier | Score | Verdict |
|---|---|---|---|
| `place_paper_order()` | T1 | 8/10 | keep as-is |
| `_place_live_order()` | T1 | 7/10 | fix before live |
| `_auto_place_trades()` | T1 | 7/10 | keep as-is |
| `_in_gfs_update_window()` | T2 | 9/10 | keep as-is |
| `_current_forecast_cycle()` | T2 | 8/10 | keep as-is |
| `_midpoint_price()` | T2 | 7/10 | keep as-is |
| `_count_open_live_orders()` | T2 | 7/10 | keep as-is |
| `_recover_pending_orders()` | T2 | 7/10 | keep as-is |
| `_poll_pending_orders()` | T2 | 6/10 | fix (log level) |
| `_daily_paper_spend()` | T2 | 7/10 | keep as-is |
| `_daily_sameday_spend()` | T2 | 7/10 | keep as-is |
| `_sameday_effective_cap()` | — | DORMANT | intentional |
| `_check_early_exits()` | T2 | 7/10 | keep as-is |
| `_validate_trade_opportunity()` | T2 | 8/10 | keep as-is |
| `_is_still_live()` (nested) | T2 | 8/10 | keep as-is |

**File median: 7/10** — consistent with a production trading bot at this maturity level.

---

## Top Findings

1. **`_place_live_order()` L:376** — KeyError risk on missing `max_open_positions` key in `live_config`. Fix: `config.get("max_open_positions", 1)` to match the `.get()` pattern used for `daily_loss_limit` on L367. Severity: LOW in practice (live_config assembled in cmd_cron with all fields) but a code hygiene issue with production risk if live_config ever comes from a partial source.

2. **`_poll_pending_orders()` L:266–341** — Four exception paths log/print at DEBUG or via print() instead of WARNING-level logging. Operator cannot see pre-close cancel failures or settlement failures in log monitoring. Fix: raise all four to `_log.warning()`.

3. **`_auto_place_trades()` close_time stale path** — L:1399 reads `close_time` from the original market dict `m`, not from the fresh market fetched at L:1134. In normal operation these are the same. Risk is cosmetic (wrong close_time stored in paper trade record), not a safety issue.

4. **No direct test for `_place_live_order()`** — `test_dedup.py` tests the live dedup guard by patching `_place_live_order`, not by exercising it. The function has no unit test verifying the pre-log → API → result-update flow. This prevents it from scoring above 7 per the rubric.
