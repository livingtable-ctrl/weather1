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

The system is in **paper-trading mode** throughout. Capital is ~$1,048 (peak ~$1,095).
The primary exit criterion from paper mode is Brier ≤ 0.20 on multi-day trades
(currently ~0.24 overall last-50; the `ensemble` method's lifetime Brier is 0.2681 but
its rolling last-20 is 0.2129 — see Category 3 and Category 10 for why both numbers
matter now).

**Trading is currently paused** (`TRADING_PAUSED=true` in `.env`, since 2026-06-30,
expected through ~2026-07-30 — the operator is traveling to a Kalshi-restricted
jurisdiction). Cron still scans, analyzes, and logs "shadow" predictions
(`is_shadow=1` in `predictions`) for signals that would have traded, so Brier/
calibration scoring stays current — but zero real or paper orders are placed while
this flag is set. Grade the system as if trading were live (the pause is an
operator-level switch, not a bug), but Category 10 should reflect that the pause
is active and when it's due to lift.

---

## Files to Read

Read every file before grading. Do not skip any.

**Core backend:**
- `paper.py` — balance, drawdown tiers, `_drawdown_snapshot()`, `position_correlation_matrix()`
- `tracker.py` — DB schema, `multiday_predictions` view, all SQL queries, `brier_score()`,
  `brier_score_by_method()` vs `brier_score_by_method_rolling()` (lifetime vs rolling-N
  Brier — check their `WHERE` clauses stay in sync), `auto_retire_strategies()`'s three
  escape-hatch guards (pin, `dir_accuracy_guard`, rolling-Brier), `is_shadow` column
- `ml_bias.py` — GBM + Platt + temperature scaling (train and apply paths)
- `calibration.py` — condition weight training, `calibrate_and_save()`
- `nws.py` — sigma scoping, `_nws_days_out_scale()`, NWS blend weights
- `weather_markets.py` — `analyze_trade()`, blending, gate logic, Kelly sizing
- `monte_carlo.py` — `simulate_portfolio()`, `portfolio_var()`, correlation
- `cron.py` — settlement loop, calibration gate, anomaly check, ensemble pin auto-renew
- `order_executor.py` — trade placement, `_daily_paper_spend()`, `_same_day_open()`,
  `_log_shadow_predictions()` (applies the same validation/dedup gates as real
  placement before logging — check it doesn't diverge from `_auto_place_trades`'s gates)
- `main.py` — entry point, `load_dotenv()` position, `cmd_calibrate()`, admin commands
- `alerts.py` — Brier drift alert, win-rate collapse, black swan
- `safe_io.py` — atomic write implementation
- `circuit_breaker.py` — thresholds and trigger conditions

**Config / data:**
- `.env` (or describe from memory if not readable) — key constants: `MAX_DAILY_SPEND`,
  `MAX_SAME_DAY_POSITIONS`, `MAX_SAME_DAY_SPEND`, `BELOW_GATE_ENABLED`,
  `SAME_DAY_RESERVE_SLOTS`/`SAME_DAY_DYNAMIC_SLOTS`, `TRADING_PAUSED`, etc.
- `data/temperature_scale.json` — current T values for above/below/global/sameday
  (`between` is a valid key too, populated once ≥15 between-market samples accumulate —
  currently absent, which is dormancy, not a bug)
- `data/condition_weights.json` — ensemble/climatology/nws blend weights per condition
- `data/learned_weights.json` — current blend weights per condition/city
- `data/retired_strategies.json`, `data/strategy_pins.json` — retirement/pin state
- `data/predictions.db` — via `tracker.py` helpers; check `is_shadow` rows too

**Frontend:**
- `web_app.py` — all Flask routes, especially `/api/status`, `/api/calibration-status`,
  `/api/opportunities`, `/api/anomaly-status`
- `weather app site V_3 (3)/src/tabs/` — all 9 tab files
- `weather app site V_3 (3)/src/useData.js` — data fetching and `mapStats()`

**Tests (skim for coverage):**
- All `test_phase2_batch_*.py` files — what is and isn't covered
- `test_p9_p10.py::TestStrategyRetirement` — retirement/pin/rolling-Brier guard coverage
- `test_shadow_predictions.py` — shadow-prediction logging/dedup coverage

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
- Does `analyze_trade()` (`weather_markets.py:4910`) correctly branch same-day vs.
  multi-day behavior via `metar_locked` (computed at line ~5124, checked in ~8 separate
  conditionals through the function — it's not a single clean fork near the top, so
  check each branch point individually rather than assuming one dispatch point)?
- Does NWS sigma=1 scoping apply only to `between` markets at `days_out=1`?
- Does `_nws_days_out_scale()` return 1.0 at d=1 (neutral point) and decay beyond that?
- Are condition weights (`data/condition_weights.json`: above/below/between) applied
  correctly and distinctly? (This is a separate axis from seasonal weights —
  `data/seasonal_weights.json`'s spring/summer/fall/winter split — don't conflate the
  two; as of this grade, seasonal weights are still uncalibrated, all at neutral
  0.333/0.333/0.333.)
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
- Does drawdown scaling correctly reduce Kelly? Real structure (`paper.py:134-137,450-458`):
  recovery ratio ≤`_DRAWDOWN_TIER_1=0.80`→halt (0.0 Kelly), ≤`_DRAWDOWN_TIER_2=0.85`→0.10,
  ≤`_DRAWDOWN_TIER_3=0.90`→0.30, <`_DRAWDOWN_TIER_4=0.95`→0.70, else→1.0 (full sizing).
  Note the naming is easy to invert: `_DRAWDOWN_TIER_1` is the *worst* state (halt), not
  full sizing — don't assume "TIER_1" means "healthy" without checking the actual
  threshold direction.

**Scoring criteria:**
- A: Kelly math correct; fee on correct side; caps independent and non-interfering; sort confirmed
- B: Breakeven gate or Kelly gate has a minor threshold off-by-one; otherwise correct
- C: Multi-day cap accidentally eats same-day slots or vice versa; or Kelly computed from wrong prob
- D: Fee rate applied on wrong amount (entry price vs. payout); or caps silently interfere
- F: Kelly sizing produces negative quantity or crashes; or all caps disabled; or drawdown
  scaling is inverted (increases Kelly as drawdown worsens)

---

## Category 3: Risk Management (weight: high)

**Note before evaluating**: this category and Category 10 both discuss "Brier scores under
~0.25" for different purposes — the retirement guard's per-method Brier here (lifetime
`ensemble`=0.2681 / rolling-20=0.2129, threshold 0.25) is unrelated to the graduation
gate's overall-last-50 Brier (0.2408, threshold 0.20) that Category 10 tracks separately.
Don't conflate them when grading.

**What to evaluate:**
- Does `_drawdown_snapshot()` add back same-day open costs to effective balance?
- Do `is_paused_drawdown()` and `drawdown_scaling_factor()` use effective balance (not actual)?
- Does `get_max_drawdown_pct()` use actual balance (reporting only — this is intentional)?
- Does the black swan Brier check use multi-day only (`multiday_predictions`)? Separately,
  is the live `.env` black-swan threshold (`BLACK_SWAN_BRIER_THRESHOLD=0.35`, overriding
  `alerts.py`'s in-code default of 0.30) still the intended value — see Category 10.
- Does the anomaly detection window (`run_anomaly_check`) filter to multi-day only?
- Does the ensemble pin auto-renew in cron when directional accuracy ≥ 0.70 and the
  pin is within 48h of expiry (`cron.py`'s pin-renewal block)? (Not Brier-based — the
  renewal condition is directional accuracy, a different signal from the retirement
  gate's own Brier check.)
- Does `auto_retire_strategies()`'s rolling-Brier guard (last-20 settled per method)
  correctly prevent retiring a method whose *lifetime* Brier is stale-bad but whose
  *recent* performance has recovered — without masking a method that's still
  genuinely bad (verify both directions have test coverage, not just one)?
- Are the pin-renewal mechanism and the rolling-Brier guard correctly understood as
  covering *different* failure modes (chronic stop-loss-driven Brier vs. stale lifetime
  average) rather than one being redundant with the other? Removing either without
  the other in place reintroduces a real retirement-safety gap (this happened once
  already this cycle — the pin-renewal block was briefly deleted on the false
  assumption the rolling guard made it redundant, then restored).
- Does the 24h-before-close stop-loss protection (`paper.py::check_stop_losses`,
  ~lines 1106-1122 and the breakeven-stop block ~1203-1209) correctly protect *existing*
  open trades nearing settlement from being stopped out on convergence-noise price
  swings? (This is not a gate on placing new trades — don't confuse it with entry caps.)
- Are circuit breakers (`circuit_breaker.py`'s generic `CircuitBreaker` and the separate
  `FlashCrashCB`) opening/closing correctly per their own configured thresholds? There's
  no single canonical threshold value to check against here (each caller supplies its
  own `failure_threshold`/`threshold_pct`/etc.) — grade the open/close *logic* for
  correctness, not specific numbers, unless a call site's chosen value looks obviously
  unreasonable.
- Is the kill switch file checked before every trade placement (not just at cron start)?

**Scoring criteria:**
- A: All checks isolated to correct trade type; snapshot adds back open costs; kill switch per-trade;
  retirement guards (pin, dir-accuracy, rolling-Brier) are each independently correct and none is
  redundant with or silently overridden by another
- B: One secondary gate (ensemble pin, circuit breaker) has a minor logic gap
- C: Anomaly window or black swan includes same-day trades, diluting the signal; or the rolling-Brier
  guard and lifetime Brier check use subtly different `WHERE` clauses that could silently diverge
- D: `_drawdown_snapshot()` missing the open-cost addback, causing wrong tier calculation
- F: Kill switch file not checked at trade time; or drawdown tier calculation inverts scaling; or a
  retirement guard was removed without verifying it didn't cover a failure mode the others don't

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
  T_sameday query) use `multiday_predictions` or a `days_out≥1` guard?
- Are same-day trades correctly excluded from `train_bias_model()`, `calibrate_condition_weights()`,
  `count_settled_predictions()`, GBM/Platt apply paths?
- Is `T_sameday` trained only on `days_out=0` above/below (not between)?
- Does `data/temperature_scale.json` hold the correct keys (`above`, `below`, `global`, `between`)?
- Is `count_settled_below_predictions()` correct for the `BELOW_GATE_ENABLED` guard?
- Is `is_shadow` separation from P&L structural, not filter-based? `_log_shadow_predictions()`
  only ever calls `tracker.log_prediction(is_shadow=True)` — it never writes to
  `paper_trades.json` (the actual P&L/dashboard data source), so shadow rows can't leak
  into P&L by construction. Confirm no code path exists that writes an `is_shadow=1` row
  AND a paper-trade record for the same signal (that would be the actual failure mode to
  check for, not a missing `WHERE is_shadow=0` filter — there shouldn't need to be one).
  Separately confirm shadow rows ARE included in Brier/calibration scoring (they're real
  forecasts and should keep those scores current — verify this is deliberate, not an
  oversight).
- Do `brier_score_by_method()` (lifetime, no date filter) and
  `brier_score_by_method_rolling()` (count-windowed) share the exact same `WHERE`
  clause / join semantics? If one is ever filtered differently (e.g. excluding
  same-day trades) without mirroring the change into the other, the retirement
  guard's "recent vs. lifetime" comparison silently becomes apples-to-oranges.

**Scoring criteria:**
- A: Every query correctly partitioned; view definition correct; T_sameday scoped right;
  is_shadow correctly included in scoring and excluded from P&L, with no test gap
- B: One peripheral query (e.g., walk-forward validation) accidentally includes same-day
- C: Calibration training pulls from `predictions` instead of `multiday_predictions`, mixing types;
  or the lifetime and rolling Brier queries have already drifted to different WHERE clauses
- D: GBM or Platt applies to same-day trades, introducing wrong bias correction; or is_shadow rows
  are counted in a P&L total somewhere
- F: View definition wrong or missing; all "multi-day" queries return everything

---

## Category 6: Operational Safety (weight: medium)

**What to evaluate:**
- Does `safe_io.py` use atomic temp-file-then-rename for all writes to JSON config?
- Are all writes to `temperature_scale.json`, `learned_weights.json`, `signals_cache.json`
  going through `safe_io` (not raw `open()` + `write()`)? Note: `temperature_scale.json`
  does (`ml_bias.py`/`calibration.py` via `safe_io.atomic_write_json_with_history`), but
  `learned_weights.json` does NOT — `weather_markets.py::save_learned_weights()`
  (~lines 2336-2374) does its own manual `tempfile.mkstemp` + `os.replace`, atomic in
  effect but bypassing the shared helper entirely. Confirm this is low-risk (same
  technique, just not centralized) rather than treating it as already-covered.
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
- Does `tests/test_p9_p10.py::TestStrategyRetirement` cover the rolling-Brier guard in
  *both* directions (blocks retirement when recent recovered; still retires when recent
  is also bad), not just the "happy path" that motivated adding it?
- Does `tests/test_shadow_predictions.py` exercise `_log_shadow_predictions()`'s dedup/
  validation gates (already-open, was-ordered-recently, was-traded-today,
  `_validate_trade_opportunity`), not just the happy-path "logs a row" case?

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
- Is logging consistent (no bare `print()` in production paths)? As of this grade,
  `cron.py` has ~48 bare `print()` calls and `order_executor.py` has ~17 — most appear to
  be intentional CLI/console output (via `dim()`/`green()`/`yellow()` color helpers)
  rather than accidental debug prints, but confirm that distinction holds and that none
  are actually swallowing something that should go through `_log` instead.
- Are constants defined once (no magic numbers duplicated across files)? Confirmed
  instance to check: `BREAKEVEN_TRIGGER_PCT` and `MAX_SAME_DAY_SPEND` are each defined
  twice with DIFFERENT hardcoded defaults — `utils.py:202` defaults `BREAKEVEN_TRIGGER_PCT`
  to `"0.30"` while `config.py:199` defaults it to `"0.75"`; `utils.py:148-149` defaults
  `MAX_SAME_DAY_SPEND` to `"500.0"` while `config.py:187` defaults it to `"400.0"`
  (and `config.py`'s `max_same_day_spend` field has zero call sites — it's dead code).
  Both currently resolve to the same live value only because `.env` explicitly sets
  `BREAKEVEN_TRIGGER_PCT=0.75` and `MAX_SAME_DAY_SPEND=400` — masking the divergence.
  If either line were ever removed from `.env`, whichever code path reads `utils.py`
  (confirmed: `paper.py` imports `BREAKEVEN_TRIGGER_PCT` from `utils`, not `config`)
  would silently start enforcing a different value than `config.py` claims. This is a
  live landmine, not just a style nit — flag it accordingly.
- Are comments explaining *why*, not *what*?
- Is `load_dotenv()` the only place where env is loaded?

**Scoring criteria:**
- A: Clean boundaries; no circular imports; error handling appropriate at boundaries only
- B: A handful of print() statements remaining that are genuinely accidental debug output
  (not the ~65 intentional CLI-output prints already known to exist in cron.py/
  order_executor.py); minor constant duplication with values that agree
- C: Constants duplicated across files with values that only agree because of an
  external override (e.g. `.env`) masking a real default divergence — see
  `BREAKEVEN_TRIGGER_PCT`/`MAX_SAME_DAY_SPEND` above
- D: Circular imports that survive only by import-inside-function workarounds everywhere
- F: Global state mutation across modules makes order of import affect behavior

---

## Category 10: Current System Health (weight: high — reflects live state)

**What to evaluate** (read `data/` files and recent DB state if possible — numbers below
are current as of 2026-07-03; re-pull them fresh each grading run, don't reuse these):

- **Brier score**: `ensemble` lifetime = 0.2681 (above the 0.25 retirement threshold);
  `ensemble` rolling last-20 = 0.2129 (recovered, below threshold — this gap is *why*
  the rolling-Brier guard exists); overall last-50 across all methods = 0.2408. Is the
  rolling number trending further down run over run, or is 0.2129 a temporary dip?
- **Balance**: $1,047.98 (peak $1,095.46, ~4.3% off peak). `drawdown_scaling_factor()` =
  1.0 → confirm the system is at full Kelly sizing, above `_DRAWDOWN_TIER_4=0.95` (i.e.
  recovery ratio > 95%). Careful with naming: `_DRAWDOWN_TIER_1` in the code is the worst
  state (halt at ≤80% recovery), not the best — "TIER_1" does not mean "healthy" here.
- **Graduation gate**: Brier ≤ 0.20 is the primary blocker; overall last-50 (0.2408) is
  the relevant number to track toward that, not the per-method lifetime figure.
- **TRADING_PAUSED**: `true` since 2026-06-30, expected to lift ~2026-07-30 (operator
  traveling to a Kalshi-restricted jurisdiction). Confirm cron still scans/logs shadow
  predictions but places zero real orders while this is set, and confirm nothing else
  in the codebase silently bypasses this flag (trace every caller of the trade-placement
  path, not just `cron.py`'s).
- **Shadow predictions**: 6 logged since the pause began (`is_shadow=1` in
  `predictions`), feeding Brier/calibration scoring with zero P&L impact. One has
  settled so far (`KXHIGHTDAL-26JUL02-T96`, settled YES, model had said 58%).
- **Black swan threshold**: live `.env` sets `BLACK_SWAN_BRIER_THRESHOLD=0.35` and
  `BLACK_SWAN_BRIER_MIN_SAMPLES=30`, overriding `alerts.py`'s in-code defaults
  (`"0.30"`/`"10"`). This is 0.10 above the 0.25 auto-retirement threshold and hasn't
  been cross-checked against the current Brier numbers above — confirm 0.35 is still
  the intended black-swan trigger level, not a stale override from an earlier tuning pass.
- **Ensemble retirement state**: not retired (`get_retired_strategies()` = `{}`).
  Protected by a manual pin expiring **2026-07-10T14:09 UTC** — confirm the pin-renewal
  block (directional-accuracy-gated) and the rolling-Brier guard are both still present
  and neither was removed as "redundant" with the other (see Category 3).
- **Temperature calibration**: `T_above=1.30 (n=23)`, `T_below=1.00 (n=14)`,
  `T_global=4.87 (n=41)`, `T_sameday=2.53 (n=45)` in `temperature_scale.json`. Reasonable
  given sample counts, or has a value moved sharply since the last grade? (These `n`
  values are calibration-fit sample sizes — don't conflate with the below-gate
  eligibility count below, which is a different query.)
- **Condition weights** (`data/condition_weights.json`): above = ensemble 0.60 /
  climatology 0.05 / nws 0.35; below = ensemble 0.05 / climatology 0.75 / nws 0.20.
  Locked/reasonable given the above/below sample sizes, or drifting oddly?
- **Below gate**: `BELOW_GATE_ENABLED` not set in `.env` → dormant by default (requires
  `=1` AND ≥30 settled below predictions per `weather_markets.py`). Current
  `count_settled_below_predictions()` = 18 — still short of 30 even if the flag were
  set, so dormancy is correct either way right now.
- **Same-day reserve**: `SAME_DAY_RESERVE_SLOTS` / `SAME_DAY_DYNAMIC_SLOTS` unset in
  `.env` → mechanism fully disabled regardless of sample count (not merely
  under-threshold). If dynamic slots were ever enabled, `SAME_DAY_RESERVE_MIN_SAMPLES`
  defaults to 150; current same-day settled count is 118, so it would still be dormant
  today even with the flag on. Confirm dormancy is a deliberate operator choice, not a
  forgotten flag.
- **Kill switch**: NOT active (`data/.kill_switch` absent).
- **Pending tasks from backlog**: Are any of the previously-verified missing features
  now critical? Has anything shipped since the last grade that should be checked off?

**Scoring criteria:**
- A: Overall Brier trending down; drawdown scaling at full 1.0 (above `_DRAWDOWN_TIER_4`);
  calibration values empirically grounded; all retirement/pin guards in correct,
  mutually-understood state; TRADING_PAUSED correctly gating every placement path
- B: One guard (e.g., below gate) arguably should have been enabled already
- C: Brier stalled or slightly rising; calibration values stale relative to recent data
- D: Drawdown scaling below 1.0 (any of `_DRAWDOWN_TIER_2/3/4` active); a guard that should
  be active is off (or vice versa); or a trade-placement call site exists that
  TRADING_PAUSED doesn't reach
- F: System halted, overall Brier > 0.35, or graduation is regression not progress; or trades were
  placed while TRADING_PAUSED was set

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
| 10| Current System Health       |       |                 |

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
3. **Calibration grades require sample-count context.** A T value that looks high or low in
   isolation is not "suspicious" on its own — it may reflect low-confidence shrinkage toward
   the prior at a small N (e.g. `T_below=1.00` at `n=14`). Only flag calibration values if the
   update rule itself is wrong, not if the values look unusual for their sample count.
4. **Don't double-count.** If a bug appears in both Category 2 and Category 5, cite it in
   the most relevant category and note it in the other as "see Category X."
5. **Weight your overall grade.** High-weight categories (1, 2, 3, 10) should influence
   the overall grade more than low-weight ones (8, 9).
