# Grade Audit — calibration.py

**Grader:** claude-sonnet-4-6  
**Date:** 2026-06-29  
**File:** calibration.py (475 lines)  
**TIER 1 functions:** `_load_rows`, `calibrate_seasonal_weights`, `calibrate_city_weights`, `calibrate_condition_weights`, `calibrate_and_save`

---

## TIER 1 Functions

---

### `_load_rows()` L:132–148  ★ T1

```
Score: 8/10  |  Confidence: Confirmed
AC: AC1 PASS — uses `FROM multiday_predictions p` (view defined as days_out IS NULL OR days_out >= 1)
Red flag: NONE
Invariants: I1 PASS (multiday_predictions view enforces same-day exclusion)
STRENGTHS:
• Uses the multiday_predictions view — correct by design; same-day METAR trades can never
  contaminate blend-weight calibration through this path.
• Explicitly filters NULL component probs before returning rows, preventing NaN propagation
  downstream in _brier().
• Uses sqlite3.Row factory for named-column access, reducing positional indexing errors.
WEAKNESSES:
• line 133–148: No exception handler. A SQLite error (locked DB, corrupt file, missing table)
  propagates as an unhandled exception to calibrate_seasonal_weights / calibrate_city_weights
  callers. calibrate_and_save documents "Raises on DB read failure" but seasonal/city callers
  do not — they will surface an uncaught exception to the cron log.
• line 146: `AND (p.condition_type IS NULL OR p.condition_type != 'between')` excludes
  between-condition rows from seasonal and city calibration entirely. This is defensible
  since between uses a separate blend, but it is silently undocumented inside the function.
  A reader adding a new condition type could be confused why rows disappear.
FAILURE SCENARIO (score = 8, not ≤7, so required only if score ≤7 — N/A):
VERDICT: keep as-is
```

---

### `calibrate_seasonal_weights()` L:151–211  ★ T1

```
Score: 7/10  |  Confidence: Confirmed
AC: AC1 PASS (delegates to _load_rows which uses multiday_predictions view)
    AC2 N/A (seasonal weights file does not contain T values)
    AC3 PASS — _split_rows cuts at 80th-percentile date; optimization on train, gate on val
Red flag: NONE
Invariants: I1 PASS
STRENGTHS:
• Delegates DB access to _load_rows, keeping SQL filter invariant centralized.
• Always returns all four seasons with neutral defaults + _uncalibrated flag — callers never
  see a KeyError during early accumulation.
• Recency weighting via _compute_recency_weight is passed through to _brier, so older
  trades count less without losing their contribution.
• Test coverage: test_returns_weights_summing_to_one, test_below_threshold_omits_season,
  test_rows_without_source_probs_not_counted — meaningful assertions on output shape and
  threshold behavior.
WEAKNESSES:
• line 177: column order passed to tuple is (date, ensemble_prob, clim_prob, nws_prob, 
  settled_yes, weight). _brier() expects rows (e, c, n, s[, weight]) i.e. (ensemble, clim,
  nws, settled). The _load_rows query returns columns in order: ensemble_prob, nws_prob,
  clim_prob. But then calibrate_seasonal_weights builds the tuple as:
      (date_str, row["ensemble_prob"], row["clim_prob"], row["nws_prob"], ...)
  This is (ensemble, CLIM, NWS) — which matches _brier's (e, c, n) expectation. PASS.
• line 209: _split_rows is called per-season without a guard that train is non-empty.
  If a season has exactly _SEASONAL_MIN rows and they all fall after the cutoff_date, train
  will be empty and _best_weights will do a random search over zero rows, returning equal
  weights (score = inf → equal). Not a crash but produces meaningless output silently.
• No WARNING log when the val-set improvement gate rejects calibrated weights — only when
  _best_weights returns _uncalibrated due to tiny val set. An operator cannot distinguish
  "no improvement found" from "not enough data" without adding logging.
FAILURE SCENARIO:
  Season has exactly 20 rows all dated within the last few weeks. Auto-computed 80th
  percentile cutoff at row 16; val = rows 16–19 (4 rows < _MIN_VAL_ROWS=10 in
  _best_weights). _best_weights logs a WARNING and returns _uncalibrated=True. The
  "_uncalibrated" flag causes calibrate_and_save to preserve existing on-disk weights.
  Correct behavior, but the WARNING from _best_weights says "calibrate_blend_weights"
  (the wrong function name) — confusing to the operator reading logs.
VERDICT: keep as-is (minor log clarity issue, no correctness bug)
```

---

### `calibrate_city_weights()` L:214–255  ★ T1

```
Score: 7/10  |  Confidence: Confirmed
AC: AC1 PASS (delegates to _load_rows → multiday_predictions view)
    AC2 N/A
    AC3 PASS
Red flag: NONE
Invariants: I1 PASS
STRENGTHS:
• Same structural correctness as calibrate_seasonal_weights — delegates to _load_rows,
  uses train/val split, gates on _BRIER_IMPROVEMENT_GATE.
• _CITY_MIN=50 chosen for SE~0.07 statistical reliability (commented).
• Test coverage: test_returns_weights_for_qualifying_city, test_below_threshold_omits_city.
WEAKNESSES:
• line 253: Same empty-train risk as calibrate_seasonal_weights — no guard on train being
  non-empty after _split_rows.
• City weights silently drop cities that do not reach _CITY_MIN. No WARNING logged for
  cities approaching the threshold (e.g., 40/50). An operator cannot tell that a high-
  volume city (e.g., Chicago KMDW) is almost eligible without querying the DB directly.
• No test for a city that exactly meets _CITY_MIN (50 rows) — threshold boundary untested.
FAILURE SCENARIO:
  City with exactly 50 rows all concentrated in a 2-week window. Cutoff at the 80th
  percentile gives ~10 rows in val. _best_weights runs, finds no improvement (all rows
  similar), returns equal weights. Correct outcome. But if someone reduces _SEASONAL_MIN
  and forgets _CITY_MIN is a separate constant, they get different behavior per path with
  no cross-reference comment.
VERDICT: keep as-is
```

---

### `calibrate_condition_weights()` L:289–360  ★ T1

```
Score: 8/10  |  Confidence: Confirmed
AC: AC1 PASS — explicit `AND (p.days_out IS NULL OR p.days_out >= 1)` at line 314
    AC2 PASS — CONDITION_MIN=60 at line 284 (via _CONDITION_MIN), MIN_VAL_ROWS=10 at line
               109 in _best_weights, BRIER_IMPROVEMENT_GATE=0.005 at line 23. All three
               present and correct.
    AC3 PASS — _split_rows provides held-out validation set
Red flag: NONE
Invariants: I1 PASS
STRENGTHS:
• Three-layer defense intact and correct:
    Layer 1: _CONDITION_MIN=60 gates the outer loop (not enough rows → neutral defaults).
    Layer 2: _MIN_VAL_ROWS=10 gates _best_weights (not enough val rows → _uncalibrated).
    Layer 3: _BRIER_IMPROVEMENT_GATE=0.005 gates replacement (no improvement → equal weights).
• Does NOT use the multiday_predictions view — instead uses `FROM predictions` with explicit
  `AND (p.days_out IS NULL OR p.days_out >= 1)`. This is functionally equivalent and
  correct; I1 PASS.
• Returns neutral defaults for all three condition types, protecting callers from KeyError.
• Test coverage: test_calibrate_condition_weights_returns_per_type_dict with 120 rows per
  type — meaningful assertion on structure and sum-to-1.
WEAKNESSES:
• line 300–317: Opens the DB connection directly (not via _load_rows). This is a second
  code path for DB access in the same file — if someone fixes a query bug in _load_rows
  they may not update calibrate_condition_weights. Minor architectural inconsistency.
• line 314: The inline days_out filter uses `(p.days_out IS NULL OR p.days_out >= 1)` which
  matches the multiday_predictions view definition — correct. But unlike _load_rows, it
  queries `FROM predictions` directly, which is fine but less DRY.
• The condition_weights BRIER_IMPROVEMENT_GATE comment at line 23 says "min val-set
  improvement" but the code at _best_weights line 126 computes `val_baseline - val_calibrated
  <= _BRIER_IMPROVEMENT_GATE`. This means val_calibrated must be strictly MORE than
  0.005 better than baseline. Correct, but the comment says "min improvement" which
  could be read as ">= 0.005" — minor documentation ambiguity.
VERDICT: keep as-is
```

---

### `calibrate_and_save()` L:381–438  ★ T1

```
Score: 6/10  |  Confidence: Confirmed
AC: AC1 PASS (delegates to calibrate_*_weights which enforce the filter)
    AC2 PASS — function does NOT touch temperature_scale.json; T values are not written here.
               The three-layer defense in calibrate_condition_weights() is intact.
    AC3 PASS (inherited from callee functions)
Red flag: RF1 — line 423: `except Exception: pass` — exception caught without any log at
               WARNING or above. If json.loads fails on a corrupt condition_weights.json,
               the failure is silently swallowed. Caller sees no indication that the
               preservation logic was skipped and fresh calibrated weights (possibly
               neutral/uncalibrated) were written instead.
               Quote: `except Exception:\n            pass  # corrupt / missing — use freshly-calibrated values as-is`
Invariants: N/A (no trading gate, balance, or Kelly logic here)
STRENGTHS:
• Single canonical implementation for both cmd_calibrate and cron auto-calibration.
• Preservation logic correctly protects manually-tuned condition weights from being
  overwritten when auto-calibration produces _uncalibrated=True (insufficient data).
• Delegates all writes to atomic_write_json_with_history — safe atomic write path used.
• INFO log at completion includes counts for all three weight files.
WEAKNESSES:
• line 423: RF1 — bare `except Exception: pass` in the condition weight preservation
  block. If the existing condition_weights.json is corrupt or has unexpected structure,
  the failure is completely silent. The comment says "corrupt / missing — use freshly-
  calibrated values as-is" but this is wrong behavior: if the file is corrupt, freshly-
  calibrated neutral/uncalibrated values silently overwrite whatever the operator had
  manually configured. The operator has no indication this happened.
• No validation that _dir is writeable before attempting the three atomic writes. If
  the data/ directory has a permissions problem, atomic_write_json_with_history will
  raise, but the first write (seasonal) may have already succeeded — partial update
  with no rollback.
• The `from tracker import DB_PATH` and `from safe_io import atomic_write_json_with_history`
  are deferred imports inside the function body. This is unusual and makes the dependency
  graph harder to trace, though it does avoid a circular import at module load time.
FAILURE SCENARIO:
  data/condition_weights.json becomes corrupt (truncated mid-write by a crash).
  calibrate_and_save() runs on next cron tick. json.loads raises JSONDecodeError at line 413.
  The except-pass swallows the error. All three condition types have _uncalibrated=True
  from this run (below=16 settled trades < _CONDITION_MIN=60). The preservation logic was
  skipped silently. atomic_write_json_with_history writes fresh neutral defaults over the
  existing hand-tuned below/above weights. No log at WARNING or above. Operator has no idea
  the weights changed until they notice degraded P&L.
FIX:
  calibration.py:423 — replace `except Exception:\n            pass` with:
    except Exception as _exc:
        _log.warning(
            "calibrate_and_save: could not read existing condition_weights for preservation — "
            "using freshly-calibrated values: %s",
            _exc,
        )
VERDICT: fix before live (RF1 — silent exception in weight preservation logic)
```

---

## TIER 2 Functions

---

```
[calibration.py] _compute_recency_weight() L:27–35  8/10 — Correct exponential decay
  with clamp on negative days_ago; bare `except Exception: return 1.0` is RF1-adjacent
  but impact is benign (fallback to equal weight, not a trading decision).
  [Confidence: Confirmed]
```

```
[calibration.py] _brier() L:54–65  9/10 — Correct weighted Brier; skips None components;
  guards against zero sum_w; clean and readable.  [Confidence: Confirmed]
```

```
[calibration.py] _split_rows() L:68–83  7/10 — Correct 80/20 temporal split with explicit
  cutoff support; one gap: if all rows are identical dates, cutoff_date equals the last
  date and train may be empty — no guard or log.  [Confidence: Confirmed]
```

```
[calibration.py] _best_weights() L:86–129  8/10 — Random-search simplex with held-out val
  gate and _MIN_VAL_ROWS guard; WARNING log when val too small; fixed seed (42) ensures
  reproducibility; one gap: log message says "calibrate_blend_weights" (wrong function name
  for the context, as this is a private helper).  [Confidence: Confirmed]
```

```
[calibration.py] load_seasonal_weights() L:258–269  8/10 — Correct: missing file returns {},
  exception at WARNING with return {}; no silent failure.  [Confidence: Confirmed]
```

```
[calibration.py] load_city_weights() L:272–281  8/10 — Same pattern as load_seasonal_weights;
  correct.  [Confidence: Confirmed]
```

```
[calibration.py] load_condition_weights() L:363–378  8/10 — Same pattern; correct.
  [Confidence: Confirmed]
```

```
[calibration.py] validate_weight_files() L:441–473  7/10 — Checks sum-to-1 (with _-prefix
  key exclusion), checks negative values, logs ERROR for bad weights; gap: does not check
  city weights for the same invariants (only seasonal and condition), so a corrupt
  city_weights.json with weights summing to 0.8 would be silently accepted.
  [Confidence: Confirmed]
```

---

## Summary

| Function | Tier | Score | Verdict |
|---|---|---|---|
| `_compute_recency_weight` | T2 | 8 | keep |
| `_brier` | T2 | 9 | keep |
| `_split_rows` | T2 | 7 | keep |
| `_best_weights` | T2 | 8 | keep |
| `_load_rows` | **T1** | 8 | keep |
| `calibrate_seasonal_weights` | **T1** | 7 | keep |
| `calibrate_city_weights` | **T1** | 7 | keep |
| `load_seasonal_weights` | T2 | 8 | keep |
| `load_city_weights` | T2 | 8 | keep |
| `calibrate_condition_weights` | **T1** | 8 | keep |
| `load_condition_weights` | T2 | 8 | keep |
| `calibrate_and_save` | **T1** | 6 | **fix before live** |
| `validate_weight_files` | T2 | 7 | keep |

**File median: 8.** One function requires a fix before next live cron run: `calibrate_and_save` (RF1 silent exception in condition weight preservation).
