# Grade Audit — output_formatters.py
**File:** `output_formatters.py`
**Lines:** 1–506
**Tier:** TIER 2 (display helpers only)
**Graded:** 2026-06-29

---

## Summary

Four functions total. All are display/CLI helpers with no direct trade placement,
sizing, or balance accounting. None appear on the TIER 1 list. Two red flags are
noted below — both are RF1 (silent exception swallows) — which promote those
functions to full TIER 1 blocks per the preamble.

---

## Function Index

| Function | Lines | Tier |
|---|---|---|
| `cmd_history` | 36–387 | TIER 2 → promoted (RF1) |
| `cmd_balance` | 395–412 | TIER 2 → promoted (RF1) |
| `cmd_positions` | 420–483 | TIER 2 → promoted (RF1) |
| `cmd_pnl_attribution` | 491–505 | TIER 2 |

---

## TIER 1 Promoted Blocks

---

### cmd_history — RF1 promotion

```
[output_formatters.py] cmd_history() L:36–387  ★ T2→T1 (RF1 promotion)
Score: 5/10  |  Confidence: Confirmed
AC: N/A (no formal ACs defined for display helpers)
Red flag: RF1 — bare `except Exception: pass` at L:255–256 silently drops
  get_market_calibration() failures; second bare `except Exception: pass` at
  L:386–387 silently drops the entire Model Analytics block
  (get_confusion_matrix, get_roc_auc, get_edge_decay_curve).
Invariants: None directly applicable (pure display, no trade decisions, no DB writes).
STRENGTHS:
• Defensively guards every optional subsection (city_cal, type_cal, rel, trend)
  with explicit `if` checks rather than try/except, which is cleaner.
• `sync_outcomes(client)` is called first so history reflects latest settlements.
• Brier thresholds for grade labels (0.10/0.18/0.25) are reasonable and the
  display is informative.
• Source leaderboard aggregation (L:286–319) is correct: sums successes/total
  across cities before dividing, avoiding a per-city averaging bias.
WEAKNESSES:
• L:255–256: `except Exception: pass` — if `get_market_calibration()` throws
  (DB schema mismatch, corrupt row, missing column), the operator sees nothing.
  No log line at WARNING or above means a persistent calibration query failure
  is invisible without grepping logs.
• L:386–387: same pattern wraps the entire Model Analytics block — a crash in
  `get_confusion_matrix()`, `get_roc_auc()`, or `get_edge_decay_curve()` is
  silently swallowed. The operator sees the "── Model Analytics ──" header but
  no data and no explanation.
• L:95: `brier_score_rolling_with_n()` is called without a try/except. If it
  raises (rare but possible with empty DB), the function crashes before printing
  profit factor or source reliability — inconsistent with the silent treatment
  elsewhere.
• The function is 352 lines with no sub-function extraction, making it difficult
  to test individual display sections in isolation.
FAILURE SCENARIO:
  DB schema migration runs (e.g., v30–v33) that adds a new column; old query in
  `get_market_calibration()` raises `sqlite3.OperationalError: no such column`.
  The exception is caught at L:255, `pass` executes, operator sees a blank section
  with no error and no log. Same scenario for Model Analytics block: a query
  regression after a schema change causes the entire analytics section to silently
  vanish from the `history` output.
FIX:
  output_formatters.py:255 — replace `except Exception: pass` with:
    `except Exception as exc: import logging; logging.getLogger(__name__).warning("market calibration display failed: %s", exc)`
  output_formatters.py:386 — same pattern:
    `except Exception as exc: import logging; logging.getLogger(__name__).warning("model analytics display failed: %s", exc)`
VERDICT: fix before live (low urgency — display only, but silent failures hide
  diagnostic data from the operator)
```

---

### cmd_balance — RF1 promotion

```
[output_formatters.py] cmd_balance() L:395–412  ★ T2→T1 (RF1 promotion)
Score: 5/10  |  Confidence: Confirmed
AC: N/A
Red flag: RF1 — `except Exception: paper_str = ""` at L:408–409 silently
  drops paper balance failures with no log.
Invariants: None directly applicable (display only; does not gate or scale any trade).
STRENGTHS:
• Calls `validate_api_key(client)` before making any API call — correct guard.
• Handles the Kalshi API returning either an int (cents) or a float by
  branching on `isinstance(balance, int)` at L:404 — defensive conversion.
• Lazy import of `paper_balance` inside function body avoids circular import
  at module load time.
WEAKNESSES:
• L:405–409: `except Exception: paper_str = ""` — if `paper_balance()` raises
  (e.g., corrupt paper_trades.json, lock error), the operator sees only the
  Kalshi balance with no indication that the paper balance failed to load.
  No log at WARNING means this failure mode is invisible.
• The silent fall-through produces output that looks healthy when it is not.
FAILURE SCENARIO:
  `paper_trades.json` is locked by a concurrent write (WinError 32) and
  `paper_balance()` raises. `except Exception` fires, `paper_str = ""`,
  operator runs `balance` and sees only the Kalshi number. Paper ledger is
  potentially corrupt or in mid-write; operator has no indication.
FIX:
  output_formatters.py:408 — replace `except Exception: paper_str = ""` with:
    `except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("paper balance read failed: %s", exc)
        paper_str = dim("  Paper: ERROR (see logs)")`
VERDICT: fix before live (low urgency — display only, but operator deserves
  visibility into ledger read failures)
```

---

### cmd_positions — RF1 promotion

```
[output_formatters.py] cmd_positions() L:420–483  ★ T2→T1 (RF1 promotion)
Score: 5/10  |  Confidence: Confirmed
AC: N/A
Red flag: RF1 — `except Exception: cur_prob_str = dim("—")` at L:462–463
  silently swallows any failure in the `analyze_trade` / `enrich_with_forecast`
  path for each position, with no log.
Invariants: None directly applicable (display only; does not place, modify, or
  size any order).
STRENGTHS:
• Correctly distinguishes YES vs NO side from the sign of `position` (L:437–439).
• Exit signal thresholds (−0.05, +0.05, ±0.02) are reasonable trigger points
  for operator attention.
• Uses `analysis.get("net_edge", analysis["edge"])` fallback at L:449 — robust
  to the dict not having `net_edge`.
WEAKNESSES:
• L:462–463: bare `except Exception` swallows forecast failures per position.
  If `analyze_trade` raises (e.g., degenerate ensemble returning None propagates
  to an unguarded path, NWS timeout, OperationalError), the operator sees "—"
  in the Cur P column with no indication of what failed or why. Across 8
  positions, all 8 could silently fail.
• The function calls `analyze_trade(enriched)` for every open position — this
  is the full ML inference path (GFS/ECMWF/ICON ensemble fetch, NWS call, bias
  correction). For a position table with 8 positions this triggers 8 full
  pipeline runs serially with no timeout. Not a bug per se, but the silent
  failure makes a hung NWS call invisible.
• No filtering on `exit_signal` before printing: a position where analysis
  failed is shown as holding without exit guidance, which looks like "no exit
  needed" to the operator.
FAILURE SCENARIO:
  NWS API is down (common during maintenance windows). `enrich_with_forecast`
  hangs or raises. Each of the 8 positions in the table silently shows "—" for
  Cur P and no exit signal. Operator believes model sees all positions as
  "no guidance available" rather than "NWS fetch failed" — could miss an exit
  signal on a position whose model probability has flipped.
FIX:
  output_formatters.py:462 — replace `except Exception: cur_prob_str = dim("—")` with:
    `except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("position analysis failed for %s: %s", ticker, exc)
        cur_prob_str = dim("ERR")`
  Also set `exit_signal = dim("analysis failed")` in the except branch so the
  column clearly flags the failure rather than showing blank.
VERDICT: fix before live (operator visibility gap for exit signals — medium urgency)
```

---

## TIER 2 Functions

```
[output_formatters.py] cmd_pnl_attribution() L:491–505  8/10 — Correct single-responsibility display function; sorts by Brier, applies color thresholds, guards on min_samples=5; no silent failures, no trade decisions.  [Confidence: Confirmed]
```

**Notes on cmd_pnl_attribution:**
- Clean function. `get_pnl_by_signal_source(min_samples=5)` result is guarded with early return on falsy.
- Color thresholds (0.20/0.25) are reasonable display heuristics; no invariant applies since this is display-only.
- The only minor gap: if `get_pnl_by_signal_source` raises (rather than returning None/empty), it propagates uncaught to the caller. Given the function is display-only and the pattern across the file is to catch silently (which we are flagging), the correct fix here would be to let it propagate so the operator sees a traceback — this is actually the better behavior. No deduction.
- Score stays 8. Anti-inflation check: a senior engineer can trust this function with the codebase's $815 balance without reading it — it touches no trade logic.

---

## File-Level Observations

1. **Module docstring** claims "no side-effects beyond I/O" — this is accurate.
   `cmd_positions()` calls `analyze_trade()` (full ML inference pipeline) which has
   network side-effects (NWS, ensemble API calls), but these are read-only and do not
   place orders. The claim holds.

2. **Consistent RF1 pattern across three of four functions.** The bare
   `except Exception: pass` / `except Exception: <fallback>` pattern with no log
   was likely copied from an early defensive coding pass. It should be replaced
   file-wide with `except Exception as exc: logger.warning(...)`.

3. **No TIER 1 invariants apply** (I1–I10): this file has no SQL queries, no
   `_DATA_LOCK` usage, no atomic writes, no Kelly formula, no settlement logic,
   no KALSHI_ENV gate (it reads positions but does not place orders), and no
   days_out thread-through. All four invariants that could conceivably apply (I8
   for balance display in `cmd_balance`) are intentionally exempt per the preamble's
   "Reporting vs trading balance" note.

4. **Test coverage:** No test file discovered for `output_formatters.py`. These are
   display helpers and RF6 does not apply (TIER 2 functions). However, the
   `cmd_positions` function invokes `analyze_trade` and `enrich_with_forecast`,
   meaning a regression in those functions could produce unexpected output here
   with no test to catch it.

---

## Score Summary

| Function | Score | Verdict |
|---|---|---|
| `cmd_history` | 5/10 | Fix before live |
| `cmd_balance` | 5/10 | Fix before live |
| `cmd_positions` | 5/10 | Fix before live |
| `cmd_pnl_attribution` | 8/10 | Keep as-is |

**File median: 5/10** — all three promoted functions share the same RF1 pattern;
one targeted fix pass resolves all three.
