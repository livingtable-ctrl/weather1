# Full System Grade — Kalshi Weather Trading Bot

## Purpose

This prompt produces a **scored report card** for the entire system. Unlike the bug-finding
audit (`full_system_audit_prompt.md`), the goal here is to evaluate *quality, completeness,
and correctness* across 10 categories and assign a letter grade (A–F) to each. Run this
periodically to track whether the system is improving.

---

## Background (read before grading)

This is a live paper-trading bot that bets on Kalshi weather markets (city daily high
temperature). Two fundamentally different trade pipelines exist:

- **Same-day** (`days_out=0`): METAR-locked; probability comes from real-time observed
  temperature vs. the contract threshold using a normal CDF at `ci_scale=1.0`. Predictions
  are sharp (near 0 or 1). Calibrated separately with `T_sameday`.
- **Multi-day** (`days_out≥1`): Ensemble blend of GFS/ECMWF/ICON ensemble, NWS/NBM
  point forecast, and climatology. Smoothed (0.3–0.7). Calibrated with `T_global`,
  `T_between`, `T_above`, `T_below` (in `data/temperature_scale.json`). Bias-corrected
  via GBM then Platt scaling once gates are met.

The system is in **paper-trading mode** throughout. Capital is ~$437. The primary exit
criterion from paper mode is Brier ≤ 0.20 on multi-day trades (currently ~0.28).

---

## Files to Read

Read every file before grading. Do not skip any.

**Core backend:**
- `paper.py` — balance, drawdown tiers, `_drawdown_snapshot()`, `position_correlation_matrix()`
- `tracker.py` — DB schema, `multiday_predictions` view, all SQL queries, `brier_score()`
- `ml_bias.py` — GBM + Platt + temperature scaling (train and apply paths)
- `calibration.py` — condition weight training, `calibrate_and_save()`
- `nws.py` — sigma scoping, `_nws_days_out_scale()`, NWS blend weights
- `weather_markets.py` — `analyze_trade()`, blending, gate logic, Kelly sizing
- `monte_carlo.py` — `simulate_portfolio()`, `portfolio_var()`, correlation
- `cron.py` — settlement loop, calibration gate, anomaly check, ensemble pin auto-renew
- `order_executor.py` — trade placement, `_daily_paper_spend()`, `_same_day_open()`
- `main.py` — entry point, `load_dotenv()` position, `cmd_calibrate()`, admin commands
- `alerts.py` — Brier drift alert, win-rate collapse, black swan
- `safe_io.py` — atomic write implementation
- `circuit_breaker.py` — thresholds and trigger conditions

**Config / data:**
- `.env` (or describe from memory if not readable) — key constants: `MAX_DAILY_SPEND`,
  `MAX_SAME_DAY_POSITIONS`, `MAX_SAME_DAY_SPEND`, `BELOW_GATE_ENABLED`, etc.
- `data/temperature_scale.json` — current T values for above/below/global/between
- `data/learned_weights.json` — current blend weights per condition/city

**Frontend:**
- `web_app.py` — all Flask routes, especially `/api/status`, `/api/calibration-status`,
  `/api/opportunities`, `/api/anomaly-status`
- `weather app site V_3 (3)/src/tabs/` — all 9 tab files
- `weather app site V_3 (3)/src/useData.js` — data fetching and `mapStats()`

**Tests (skim for coverage):**
- All `test_phase2_batch_*.py` files — what is and isn't covered

---

## Grading Rubric

Each category is graded A–F on this scale:

| Grade | Meaning |
|-------|---------|
| A | Correct, complete, well-designed; only minor polish missing |
| B | Mostly correct; 1–2 non-critical gaps or rough edges |
| C | Works but has a meaningful correctness gap or design flaw |
| D | Significant bug or missing safety net that affects results |
| F | Broken or dangerous; would cause wrong trades or data loss |

---

## Category 1: Prediction Pipeline (weight: high)

**What to evaluate:**
- Does `analyze_trade()` correctly route same-day vs. multi-day to separate code paths?
- Does NWS sigma=1 scoping apply only to `between` markets at `days_out=1`?
- Does `_nws_days_out_scale()` return 1.0 at d=1 (neutral point) and decay beyond that?
- Are condition weights (above/below/between/spring) applied correctly and distinctly?
- Does `T_above` / `T_below` from `temperature_scale.json` apply only to the right market type?
- Is the "uncalibrated flag" logic correct — does it prevent neutral weights doubling NWS?
- Does the ensemble blend sum to 1.0 for every condition without silent normalization bugs?

**Scoring criteria:**
- A: All routing correct; sigma scoping tight; T values applied per market type; no blending arithmetic bugs
- B: One condition type has a minor weight miscalculation or a scale factor at a boundary that's off-by-one
- C: A gate that's supposed to guard a path is easily bypassed, or the wrong T is applied to a market type
- D: Same-day and multi-day share a calibration path, or NWS weight doubles for uncalibrated cities
- F: Predictions are wrong by construction (e.g., probability always clipped or inverted)

---

## Category 2: Edge & Kelly Sizing (weight: high)

**What to evaluate:**
- Does `net_edge` correctly account for Kalshi's fee structure on both sides?
- Is the Kelly fraction computed from the right probability and payout ratio?
- Does the `BREAKEVEN_TRIGGER_PCT = 0.75` breakeven gate fire correctly?
- Are signals sorted by Kelly descending before date-cap consumption?
- Does the multi-day date cap (`MAX_POSITIONS_PER_DATE=4`) correctly exclude same-day?
- Does the same-day cap (`MAX_SAME_DAY_POSITIONS=8`) use `_is_still_live()` to exclude expired?
- Does `_daily_paper_spend()` exclude same-day trades (own cap: `MAX_SAME_DAY_SPEND=400`)?
- Is the Kelly gate (method Kelly ≥ 50% threshold) applied correctly in `analyze_trade()`?
- Does drawdown scaling (TIER_1=1.0, TIER_2=0.70, TIER_3=0.30) correctly reduce Kelly?

**Scoring criteria:**
- A: Kelly math correct; fee on correct side; caps independent and non-interfering; sort confirmed
- B: Breakeven gate or Kelly gate has a minor threshold off-by-one; otherwise correct
- C: Multi-day cap accidentally eats same-day slots or vice versa; or Kelly computed from wrong prob
- D: Fee rate applied on wrong amount (entry price vs. payout); or caps silently interfere
- F: Kelly sizing produces negative quantity or crashes; or all caps disabled

---

## Category 3: Risk Management (weight: high)

**What to evaluate:**
- Does `_drawdown_snapshot()` add back same-day open costs to effective balance?
- Do `is_paused_drawdown()` and `drawdown_scaling_factor()` use effective balance (not actual)?
- Does `get_max_drawdown_pct()` use actual balance (reporting only — this is intentional)?
- Does the black swan Brier check use multi-day only (`multiday_predictions`)?
- Does the anomaly detection window (`run_anomaly_check`) filter to multi-day only?
- Does the ensemble pin auto-renew in cron when Brier < 0.20 on last 10 multi-day?
- Does the 24h settlement gate prevent premature exits on new trades?
- Are circuit breakers opening and closing correctly with correct thresholds?
- Is the kill switch file checked before every trade placement (not just at cron start)?

**Scoring criteria:**
- A: All checks isolated to correct trade type; snapshot adds back open costs; kill switch per-trade
- B: One secondary gate (ensemble pin, circuit breaker) has a minor logic gap
- C: Anomaly window or black swan includes same-day trades, diluting the signal
- D: `_drawdown_snapshot()` missing the open-cost addback, causing wrong tier calculation
- F: Kill switch file not checked at trade time; or drawdown tier calculation inverts scaling

---

## Category 4: Trade Lifecycle & Settlement (weight: medium)

**What to evaluate:**
- Does settlement correctly use the city's local calendar day (not UTC) for ASOS obs window?
- Does the settlement audit (`audit_settlement()`) use ASOS ICAO matching?
- Does `close_time` get stored on all new paper trades?
- Are trades with missing `close_time` (placed before 2026-05-28) excluded from the 24h gate?
- Does `count_settled_predictions()` query `multiday_predictions` (not `predictions`)?
- Are P&L calculations correct for both YES and NO sides?
- Does the pre-scan settlement run before the scanning loop (so expired slots are freed)?

**Scoring criteria:**
- A: UTC→local conversion correct; close_time stored; settlement uses ASOS correctly
- B: Settlement window is slightly wide/narrow but catches the correct day in practice
- C: Settlement uses UTC day instead of local, causing evening observations to count for the next day
- D: P&L computed incorrectly for NO side, or settlement always produces wrong outcome
- F: Settlement loop crashes or silently skips all trades

---

## Category 5: Data Integrity & Separation (weight: medium)

**What to evaluate:**
- Is `multiday_predictions` view defined correctly in `tracker.py init_db()`?
- Do all analytics queries (Brier, bias, GBM training, Platt training, condition weights,
  T_sameday query) use `multiday_predictions` or a `days_out>0` guard?
- Are same-day trades correctly excluded from `train_bias_model()`, `calibrate_condition_weights()`,
  `count_settled_predictions()`, GBM/Platt apply paths?
- Is `T_sameday` trained only on `days_out=0` above/below (not between)?
- Does `data/temperature_scale.json` hold the correct keys (`above`, `below`, `global`, `between`)?
- Is `count_settled_below_predictions()` correct for the `BELOW_GATE_ENABLED` guard?

**Scoring criteria:**
- A: Every query correctly partitioned; view definition correct; T_sameday scoped right
- B: One peripheral query (e.g., walk-forward validation) accidentally includes same-day
- C: Calibration training pulls from `predictions` instead of `multiday_predictions`, mixing types
- D: GBM or Platt applies to same-day trades, introducing wrong bias correction
- F: View definition wrong or missing; all "multi-day" queries return everything

---

## Category 6: Operational Safety (weight: medium)

**What to evaluate:**
- Does `safe_io.py` use atomic temp-file-then-rename for all writes to JSON config?
- Are all writes to `temperature_scale.json`, `learned_weights.json`, `signals_cache.json`
  going through `safe_io` (not raw `open()` + `write()`)?
- Is cron crash-safe — does a mid-run exception leave data consistent?
- Does the peak reset (`admin reset-peak`) require explicit confirmation?
- Is the backup system running and is the backup age shown in the dashboard?
- Is `load_dotenv()` called before all local imports in `main.py`?
- Does the `same_day_cap` fix (`_is_still_live()`) correctly handle expired close_time?
- Are all cron-scheduled retrain actions idempotent (safe to re-run)?

**Scoring criteria:**
- A: All writes atomic; cron crash-safe; dotenv position correct; peak reset requires confirm
- B: One minor file written with raw `open()` that's low-risk (read-only config)
- C: `temperature_scale.json` written without atomic temp-file, risking corruption mid-write
- D: `load_dotenv()` after local imports — module-level constants read wrong `.env` values
- F: No atomic writes anywhere; a crash mid-calibration could corrupt the DB

---

## Category 7: Frontend Dashboard (weight: medium)

**What to evaluate:**
- Do all 9 tabs load without errors? (Overview, Positions, Signals, Forecast, Analytics,
  Activity, Risk, Trades, Settings)
- Does `/api/status` correctly populate `M.stats` in `useData.js mapStats()`?
- Does the calibration card show `T_above`, `T_below`, `T_global`, `T_between`?
- Does the equity curve "Since peak" toggle work correctly?
- Does Trade History show breakeven count separately from wins/losses?
- Does the backup staleness warning fire after 24h?
- Does the Positions tab show `—` instead of blank for missing model field?
- Does the VaR 95%/99% row appear in the Risk tab when data is available?
- Does the Settings cron-age banner correctly interpret UTC timestamps?
- Are drawdown halt %, balance, P&L all formatted correctly (not off by 100x)?

**Scoring criteria:**
- A: All tabs correct; calibration T values shown; VaR shown; no formatting bugs
- B: One tab has a stale field or a label that's slightly wrong
- C: A key number is wrong by 100x (e.g., drawdown % shown as decimal instead of %)
- D: A tab crashes or shows completely wrong data in a way that misleads the operator
- F: Dashboard won't build or is unloadable

---

## Category 8: Test Coverage (weight: low)

**What to evaluate:**
- Which critical paths have batch tests? (Kelly sizing, cap logic, settlement, VaR, anomaly)
- Are the same-day reserve tests in place (5 tests in `test_phase2_batch_n.py`)?
- Are the daily-spend split tests in place (`test_phase2_batch_o.py`)?
- Are there tests for `_drawdown_snapshot()` same-day addback?
- Are there tests for directional accuracy guard in `directional_accuracy()`?
- Are there any tests for the calibration pipeline (condition weight training)?
- Are there tests for the settlement UTC→local window?

**Scoring criteria:**
- A: All critical paths tested; edge cases covered; tests actually exercise live code
- B: Most critical paths covered; calibration pipeline untested (acceptable given data dependency)
- C: No tests for drawdown snapshot or cap logic — core financial safety untested
- D: Tests exist but use mocked DB or wrong field names and don't catch real regressions
- F: No test suite; `py -m pytest` produces zero tests or all failures

---

## Category 9: Code Architecture (weight: low)

**What to evaluate:**
- Are module boundaries clean? (paper.py = state; tracker.py = DB; weather_markets.py = analysis)
- Are there circular imports or `from X import *` patterns?
- Is error handling defensive at system boundaries (Kalshi API, weather APIs) vs. internal?
- Is logging consistent (no bare `print()` in production paths)?
- Are constants defined once (no magic numbers duplicated across files)?
- Are comments explaining *why*, not *what*?
- Is `load_dotenv()` the only place where env is loaded?

**Scoring criteria:**
- A: Clean boundaries; no circular imports; error handling appropriate at boundaries only
- B: One or two print() statements remaining; minor constant duplication
- C: Constants like fee rate duplicated in 3+ files with diverging values
- D: Circular imports that survive only by import-inside-function workarounds everywhere
- F: Global state mutation across modules makes order of import affect behavior

---

## Category 10: Current System Health (weight: high — reflects live state)

**What to evaluate** (read `data/` files and recent DB state if possible):

- **Brier score**: Current multi-day all = 0.2798. Is it trending down (W22=0.3592→W23=0.1954)?
- **Balance**: ~$437 with HALT floor ~$352. Is the system in TIER_1?
- **Graduation gate**: Brier ≤ 0.20 is the primary blocker. How far away is it?
- **Temperature calibration**: `T_above=6.0`, `T_below=3.0` in `temperature_scale.json`. Reasonable?
- **Condition weights**: above=ens0.60/clim0.05/nws0.35; below=ens0.05/clim0.75/nws0.20. Locked correctly?
- **Below gate**: `BELOW_GATE_ENABLED` not set — dormant gates correct given N_below~15?
- **Same-day reserve**: 57 settled; dormant until 80–100. Correct to be dormant?
- **Ensemble pin**: Expired (Brier not < 0.70 threshold). Is auto-renew logic sound?
- **Kill switch**: NOT active. Last known clean.
- **Pending tasks from backlog**: Are any of the 21 verified missing features now critical?

**Scoring criteria:**
- A: Brier trending down; system in TIER_1; calibration values empirically grounded; all guards in correct state
- B: One guard (e.g., below gate) arguably should have been enabled already
- C: Brier stalled or slightly rising; calibration values stale relative to recent data
- D: System in TIER_2 or lower; a guard that should be active is off (or vice versa)
- F: System halted, Brier > 0.35, or graduation is regression not progress

---

## Output Format

Produce your report in exactly this structure:

```
# System Grade Report — [date]

## Scorecard

| # | Category                    | Grade | One-line verdict |
|---|-----------------------------|-------|-----------------|
| 1 | Prediction Pipeline         |       |                 |
| 2 | Edge & Kelly Sizing         |       |                 |
| 3 | Risk Management             |       |                 |
| 4 | Trade Lifecycle & Settlement|       |                 |
| 5 | Data Integrity & Separation |       |                 |
| 6 | Operational Safety          |       |                 |
| 7 | Frontend Dashboard          |       |                 |
| 8 | Test Coverage               |       |                 |
| 9 | Code Architecture           |       |                 |
|10 | Current System Health       |       |                 |

**Overall grade: [X] — [one sentence summary]**
```

Then for each category, write:

```
### Category N: [Name] — [Grade]

**Strengths:**
- [bullet per strength]

**Gaps / concerns:**
- [bullet per gap, with file:line citation if applicable]

**What would move this to an A:**
- [specific, actionable]
```

End with:

```
## Top 3 Priorities

The three changes that would most improve the overall grade, in order:
1. [action] — moves Category X from Y to Z
2. ...
3. ...

## What NOT to touch

Changes that look tempting but would be premature or harmful:
- [item] — reason
```

---

## Grading Rules

1. **Do not invent findings.** Every gap cited must be traceable to a specific file and line.
2. **Distinguish "not yet" from "wrong."** A dormant gate (e.g., `BELOW_GATE_ENABLED`) that
   is intentionally off is not a bug — grade it based on whether the threshold logic is correct
   for when it does activate, and whether the current dormancy is justified by sample count.
3. **Calibration grades require sample-count context.** A T value of 6.0 is not
   "suspicious" — it reflects low-confidence shrinkage toward the prior with N=14. Only flag
   calibration values if the update rule itself is wrong, not if the values look unusual.
4. **Don't double-count.** If a bug appears in both Category 2 and Category 5, cite it in
   the most relevant category and note it in the other as "see Category X."
5. **Weight your overall grade.** High-weight categories (1, 2, 3, 10) should influence
   the overall grade more than low-weight ones (8, 9).
