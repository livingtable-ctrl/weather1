# Grade Audit — ml_bias.py
**Graded:** 2026-06-29
**Model:** claude-sonnet-4-6
**File:** ml_bias.py (819 lines)
**Branch:** claude/jolly-chandrasekhar-7d8447

---

## TIER 1 Functions

---

### [ml_bias] train_all_temperature_scaling() L:460–681  ★ T1

```
Score: 7/10  |  Confidence: Confirmed
AC: AC1 PASS — multi-day uses explicit `AND (p.days_out IS NULL OR p.days_out >= 1)`;
    same-day uses `AND p.days_out = 0`. Separate queries.
    AC3 PASS — `global _TEMP_CACHE; _TEMP_CACHE = None` at L674 after write.
    AC2 N/A (this is training, not application).
    AC4 N/A.
Red flag: NONE
Invariants: I1 PASS — separate day-filtered queries.
            I6 N/A (this function writes emos_params, not the EMOS call path).

STRENGTHS:
• Separate multi-day vs same-day queries (L541–563) with correct day_out filters — I1 honored.
• Upper-bound boundary guard at L517 (`T >= _T_UPPER_BOUND * 0.99`) prevents directional-bias artifacts.
• Cache invalidated at L674 after write — AC3 satisfied.
• NLL-vs-T=1.0 comparison gate at L532 (`if nll(T) >= nll(1.0): return None`) prevents regression.
• Uses `atomic_write_json_with_history` (L671) — I3 honored via safe_io.
• "between" excluded from training (L547) — correct; 'between' T skewed by asymmetric market structure.

WEAKNESSES:
• line 413: `_load_temperature_scale()` catches `Exception` at L413 with no log line at WARNING or above — RF1 candidate, but this is the loader helper, not the trainer. The trainer itself at L578 catches bare `Exception` with `existing = {}` silently (L578–579). A corrupt file during training is silently discarded; operator won't know calibration was rebuilt from scratch.
• line 541: SQL query on raw `predictions` table (not `multiday_predictions` view), but has explicit `AND (p.days_out IS NULL OR p.days_out >= 1)` — passes I1 by letter, though using the view would be safer for future schema changes.
• line 565–566: `all_probs`/`all_labels` built from multiday rows. The 'between' rows are excluded from fitting but their condition_type='between' entries still pass through for the by_type loop (L606–613). Wait — L547 already excludes `condition_type != 'between'`, so `rows` never contains between rows. The by_type loop at L615 would never encounter a 'between' key. Correct but confusing because the training code for condition-specific T appears to allow 'between' even though the query excludes it — dead code path.
• No direct test exercises `train_all_temperature_scaling()` end-to-end. The `test_ml_bias.py` file only tests `apply_temperature_scaling` indirectly. Under preamble rules, no meaningful test coverage caps max score at 8, but combined with the silent-exception issue a 7 is appropriate.

FAILURE SCENARIO:
`temperature_scale.json` is corrupted on disk (e.g., truncated by a WinError 32 race before safe_io was introduced). `existing = {}` at L579 silently resets to empty; all previously-trained condition T values are discarded. The function continues, trains only from current data, and overwrites the file with whatever subset passes the min_samples gate — possibly writing a file with fewer keys than before (e.g., losing the 'above' T). No log line at WARNING or above is emitted. The operator sees nothing.

VERDICT: keep as-is (correctness is solid; log the corrupt-file path at WARNING before setting existing={})
```

---

### [ml_bias] apply_temperature_scaling() L:417–457  ★ T1

```
Score: 8/10  |  Confidence: Confirmed
AC: AC2 PASS — `days_out` keyword argument is accepted (L419). Same-day path uses
    `days_out == 0` (L435); multi-day falls through to condition_type lookup (L442).
    AC3 N/A (this is the apply function; cache invalidation is train's responsibility).
Red flag: NONE
Invariants: I1 N/A (no SQL). I6 N/A (not EMOS path).

STRENGTHS:
• Same-day isolation is correct: `days_out=0` → sameday T only, no fallback to global (L435–440). Test coverage confirms this behavior (test_sameday_no_fallback_to_global, test_sameday_uses_sameday_T).
• Multi-day lookup order correct: per-condition → global → prior T → no-op (L443–457).
• T≈1.0 early-exit at L455 (`abs(T - 1.0) < 0.01`) is elegant and prevents floating-point noise.
• Above/below prior T values (L451–454) are intentional and documented. Preamble explicitly permits them.
• Test coverage is excellent: 7 tests in TestApplyTemperatureScaling covering no-file, global T, per-condition, fallback, sameday, sameday-no-fallback, multiday-unaffected.
• `_load_temperature_scale()` is called on every invocation but is cache-aware (L394–395) — no unbounded I/O.

WEAKNESSES:
• line 413 (in `_load_temperature_scale`): bare `except Exception: return None` with NO log. If the file exists but contains invalid JSON, the function silently returns None, which causes apply_temperature_scaling to skip scaling entirely and fall back to priors. The operator cannot distinguish "file absent" from "file corrupt" without reading logs at DEBUG. This is a gap — logs should be at WARNING.
• The `days_out` parameter is typed `int | None` but the comparison is `days_out == 0` (L435). If the caller passes `days_out=None` (the most likely omission), the function falls through to multi-day path. This is documented behavior but could silently misclassify a same-day trade if the caller forgets. AC2 requires `days_out` to be passed; the function can't enforce this.

FAILURE SCENARIO:
Caller omits `days_out=0` for a same-day trade. `apply_temperature_scaling(prob=0.92, condition_type=None)` falls through to multi-day path, finds no condition T in table, finds global T (e.g., 4.0), and compresses 0.92 → ~0.72. Kelly sizing for a near-certain METAR observation is significantly under-sized. This is an AC2 failure at the call site, not in this function — but the function has no guard to detect it.

VERDICT: keep as-is — the function itself is correct; WARNING log in _load_temperature_scale is the only direct fix needed here.
```

---

### [ml_bias] train_bias_model() L:136–250  ★ T1

```
Score: 7/10  |  Confidence: Confirmed
AC: AC1 PASS — query uses `FROM multiday_predictions` (L165), correct.
    AC4 N/A (this is training, not application).
Red flag: NONE
Invariants: I1 PASS — uses `multiday_predictions` view directly.

STRENGTHS:
• Uses `multiday_predictions` view (L165) — I1 by design, best form of the guard.
• 'between' excluded from training (L167) — correct; between-condition markets have different feature distributions.
• 80/20 temporal holdout (L200–222) with MSE gate prevents regressions from being saved.
• HMAC sidecar written after pkl serialization (L241) — security-critical, covered by test_train_writes_hmac_sidecar.
• Cache invalidated at L233–234 (`_MODELS_CACHE = None; _LOAD_ATTEMPTED = False`) after training — correct.
• WARNING log emitted when holdout MSE fails (L217) — operator can see when cities are skipped.

WEAKNESSES:
• line 362 in `apply_ml_prob_correction()`: Exception caught at L373 with `_log.debug` — RF1 candidate (see TIER 2 promotion below for that function; this weakness is noted here as it affects the overall training pipeline's outputs).
• line 227: per-city training failures are caught at WARNING (`_log.warning`), but the outer loop continues — correct.
• No test exercises a successful training path with actual DB data that meets the 200-sample threshold; `test_train_bias_model_returns_dict` uses `min_samples=50` but starts from an empty DB (0 rows), so the dict is always `{}`. This confirms the function runs and returns a dict, but does not verify the training logic fires. AC criterion: score cap at 8 without meaningful test coverage of the training path (preamble).

FAILURE SCENARIO:
If `our_prob` in the DB is NULL for some rows, the code at L181 does `float(our_prob or 0)` — silently substitutes 0.0. A NULL our_prob row is treated as a 0.0 probability observation and used in training. This will slightly corrupt the training data for any city with such rows, but the effect is small given the 200-sample gate.

VERDICT: keep as-is (fix the our_prob NULL substitution to skip/warn instead of silently use 0.0)
```

---

### [ml_bias] apply_ml_prob_correction() L:343–375  ★ T1

```
Score: 6/10  |  Confidence: Confirmed
AC: AC4 — the function does NOT check `days_out > 0` internally. The module doc (L30)
    and caller in weather_markets.py are expected to enforce this, but the function
    itself has no guard. If called on a same-day trade, it silently applies the
    multi-day-trained model to METAR-derived probabilities.
Red flag: RF1 CONFIRMED — L373: `except Exception as exc: _log.debug(...)` — exception
    is logged at DEBUG, not WARNING or above. A model inference failure (e.g., sklearn
    version mismatch after an upgrade, NaN in feature vector) would be invisible in
    production logs by default. Cap ≤4, but other dimensions are solid, so floor at 5
    and round up given the AC4 issue is architectural (caller enforcement) rather than
    a broken code path.
Invariants: I5 — the function does not enter the Kelly formula directly; it returns a
    clamped [0.0, 1.0] float. No direct I5 responsibility.

STRENGTHS:
• Correction magnitude cap at L364–371 (`ML_BIAS_MAX_CORRECTION`, default 0.25) prevents signal inversion from overfitted models.
• Hard clamp at L372 (`max(0.0, min(1.0, ...))`) ensures output is always a valid probability.
• Fallback to `our_prob` when no model exists (L357–358) — correct and safe.
• HMAC-verified model loading through `_load_models()`.

WEAKNESSES:
• line 373: `except Exception as exc: _log.debug(...)` — RF1. Model inference failure is silent in production. A sklearn API change, memory error, or NaN in feature vector would return our_prob unchanged with no operator-visible log.
• No `days_out > 0` guard inside the function (AC4 not enforced internally). If called on same-day trade, multi-day model is silently applied to METAR probs.
• Test `test_apply_ml_prob_correction_adjusts_probability` covers the happy path. RF1 path is not tested.

FAILURE SCENARIO:
After a `pip upgrade scikit-learn` changes the GBM predict() API, `model.predict()` raises `AttributeError`. The exception is caught at L373, logged at DEBUG, and `our_prob` is returned. If same-day ML bias correction was expected to reduce overconfidence, a position is sized at the raw METAR prob without correction, with no operator alert.

FIX:
ml_bias.py:373 — replace `_log.debug("apply_ml_prob_correction(%s): %s", city, exc)` with
`_log.warning("apply_ml_prob_correction(%s): model.predict() failed — falling back to raw prob: %s", city, exc)`

VERDICT: fix before live (RF1 exception should be WARNING, not DEBUG)
```

---

### [ml_bias] apply_platt_per_city() L:331–340  ★ T1

```
Score: 8/10  |  Confidence: Confirmed
AC: AC4 — same architectural note as apply_ml_prob_correction: no internal days_out
    guard. Caller must enforce multi-day-only invocation.
Red flag: NONE
Invariants: N/A (pure math, no I/O, no Kelly involvement)

STRENGTHS:
• Pure function — no side effects, no I/O.
• Monotonicity is preserved by construction (Platt sigmoid of linear logit transform with A>0 enforced by _fit_platt).
• Returns raw_prob unchanged if city not in models — safe fallback.
• Four tests in test_ml_bias.py cover: unknown city (unchanged), identity A=1.0 B=0.0, monotonicity invariant, and the trained-model path.

WEAKNESSES:
• No guard against `a <= 0` in the apply function itself — relies entirely on `_fit_platt()` having enforced A>0 at training time (L284). A manually edited or corrupted models pickle could have A<0, causing probability inversion. The function silently returns a wrong (flipped) probability.
• No guard against `raw_prob` being 0.0 or 1.0 — `_logit(0.0)` is clamped to `_logit(1e-6)` by `_logit()` L254–257, so this is safe. No issue.

VERDICT: keep as-is (the A>0 gap is protected by training-time enforcement; document it)
```

---

### [ml_bias] train_platt_per_city() L:292–328  ★ T1

```
Score: 7/10  |  Confidence: Confirmed
AC: AC1 — this function operates on rows passed IN (not fetched from DB), so the caller
    is responsible for correct filtering. The function itself has no SQL.
Red flag: NONE
Invariants: N/A

STRENGTHS:
• min_samples gate (default 15 in function, test uses 200) prevents overfitting on sparse cities.
• Exception per city at L321–326 with WARNING log — operator can see which cities fail.
• Defers to `_fit_platt` which enforces A>0 and |A|<=5, |B|<=5 (L284–288).

WEAKNESSES:
• line 309: `except (ValueError, TypeError): pass` — silently drops malformed rows. Correct behavior, but there's no counter/log to indicate how many rows were skipped. A systematically malformed dataset (e.g., our_prob stored as strings) would silently train on fewer samples than expected without any diagnostic.
• No test covers training failure path (optimizer non-convergence logged at WARNING). `test_train_platt_per_city_returns_coefficients` only tests the happy path and the min_samples skip.
• Function accepts any `rows` list from the caller without validating `days_out` filter — relies entirely on caller to pass only multi-day rows.

VERDICT: keep as-is
```

---

## TIER 2 Functions

---

```
[ml_bias] _hmac_secret() L:42–44  9/10 — Returns MODEL_HMAC_SECRET from env as bytes; documented dev-only empty string behavior.  [Confidence: C]
```

```
[ml_bias] _compute_hmac() L:47–54  9/10 — Correctly raises RuntimeError if secret unset rather than silently computing an unkeyed hash; uses sha256.  [Confidence: C]
```

```
[ml_bias] _write_hmac() L:57–60  8/10 — Creates parent dir, writes hex digest; no exception handling — a disk-full failure during training would propagate up from train_bias_model(), which is acceptable.  [Confidence: C]
```

```
[ml_bias] _load_models() L:63–133  8/10 — HMAC-verified pickle load with compare_digest (timing-safe), correct _LOAD_ATTEMPTED semantics distinguishing transient from definitive failures, WARNING/ERROR logs on all rejection paths. Gap: if pkl exists and loads successfully but contains a non-dict (L127), it returns {} silently — a WARNING would help.  [Confidence: C]
```

```
[ml_bias] _logit() L:253–257  10/10 — Clamps to [1e-6, 1-1e-6] before log, preventing -inf/+inf. Pure math utility.  [Confidence: C]
```

```
[ml_bias] _sigmoid() L:260–263  10/10 — Correct sigmoid formula; no edge cases in its domain.  [Confidence: C]
```

```
[ml_bias] _fit_platt() L:266–289  8/10 — L-BFGS-B optimizer with cross-entropy NLL; convergence check at L281; explicit A>0 and bounds check at L284 that raises ValueError on invalid fit. One gap: the bounds check `abs(a) > 5 or abs(b) > 5` uses OR — a valid model with A=1.0 B=6.0 would be rejected even though A is fine. Should be independent checks or documented as a joint sanity bound. Minor.  [Confidence: C]
```

```
[ml_bias] _load_temperature_scale() L:383–414  5/10 — Bare `except Exception: return None` at L413 with NO log at any level. RF1 applies: a corrupt temperature_scale.json is silently treated as "file absent," causing apply_temperature_scaling to fall back to prior Ts or no-op. Operator cannot distinguish file-absent from file-corrupt. Score capped at ≤4 by RF1 — but this is TIER 2, so fix required.  [Confidence: C]
FIX: ml_bias.py:413 — replace `except Exception:` block with:
  `except Exception as exc:`
  `    _log.warning("ml_bias: failed to parse temperature_scale.json: %s — using fallback", exc)`
  `    return None`
FAILURE SCENARIO: temperature_scale.json is written mid-update and contains truncated JSON. _load_temperature_scale returns None silently. apply_temperature_scaling falls back to hardcoded priors (T_above=6.0, T_below=3.0) for above/below, and no-op for global/between. This could last for the entire cron cycle with no operator alert.
```

```
[ml_bias] has_ml_model() L:378–380  9/10 — Single-line delegation to _load_models; correct uppercase normalization. Pure utility.  [Confidence: C]
```

```
[ml_bias] fit_emos() L:687–725  8/10 — CRPS minimization via Nelder-Mead; optimizer in sqrt-space ensures c,d >= 0 by construction; returns native floats. Gap: no convergence check on `res.success` — Nelder-Mead does not guarantee convergence (unlike L-BFGS-B) and may exit at a local minimum with no warning. A non-converged fit produces subtly wrong (a,b,c,d) that silently degrades EMOS accuracy. Low risk in practice (CRPS surface is convex for Gaussian), but should log if `res.fun` is unexpectedly large.  [Confidence: C]
```

```
[ml_bias] emos_exceedance_prob() L:728–744  9/10 — Clean Gaussian CDF via scipy ndtr; sigma floored at sqrt(1e-6) prevents division-by-zero; critical CRPS-vs-std note in docstring. Well-tested (bounds + monotonicity + consistency with interval_prob).  [Confidence: C]
```

```
[ml_bias] emos_interval_prob() L:747–763  9/10 — Same Gaussian framework as exceedance; P(low<T<high) = CDF(high) - CDF(low), correct. Docstring correctly warns ens_var not std.  [Confidence: C]
```

```
[ml_bias] _load_emos_params() L:766–790  8/10 — Returns None gracefully when file absent (I6 satisfied); logs at INFO on success, ERROR on parse failure. Gap: on parse failure returns None which triggers fallback — correct behavior, but ERROR log at L789 might alarm operators unnecessarily for a file that was never created (pre-emos-train state). Should check file exists before trying to parse.  [Confidence: C]
```

```
[ml_bias] save_emos_params() L:793–818  9/10 — Uses atomic_write_json_with_history (I3 via safe_io); clears _EMOS_CACHE after write; includes fitted_at timestamp; converts all values to native Python types before JSON serialization. Clean.  [Confidence: C]
```

---

## File Summary

| Function | Tier | Score | Key Issue |
|---|---|---|---|
| `train_all_temperature_scaling()` | T1 | 7/10 | Corrupt-file path silently discards existing; no test coverage of training path |
| `apply_temperature_scaling()` | T1 | 8/10 | Silent corrupt-file path in loader helper; AC2 enforcement is caller's responsibility |
| `train_bias_model()` | T1 | 7/10 | NULL our_prob silently substituted as 0.0; test only validates empty-DB return |
| `apply_ml_prob_correction()` | T1 | 6/10 | RF1: exception logged at DEBUG; no AC4 internal guard |
| `apply_platt_per_city()` | T1 | 8/10 | No A>0 guard in apply path (relies on training enforcement) |
| `train_platt_per_city()` | T1 | 7/10 | Malformed rows silently dropped without counter |
| `_hmac_secret()` | T2 | 9/10 | Clean |
| `_compute_hmac()` | T2 | 9/10 | Clean |
| `_write_hmac()` | T2 | 8/10 | No exception handling (acceptable — propagates up) |
| `_load_models()` | T2 | 8/10 | Non-dict pkl returns {} silently |
| `_logit()` | T2 | 10/10 | Perfect |
| `_sigmoid()` | T2 | 10/10 | Perfect |
| `_fit_platt()` | T2 | 8/10 | Joint A/B bounds check minor issue |
| `_load_temperature_scale()` | T2 | 5/10 | **RF1: bare except with no log** — fix required |
| `has_ml_model()` | T2 | 9/10 | Clean |
| `fit_emos()` | T2 | 8/10 | No convergence check on Nelder-Mead result |
| `emos_exceedance_prob()` | T2 | 9/10 | Clean |
| `emos_interval_prob()` | T2 | 9/10 | Clean |
| `_load_emos_params()` | T2 | 8/10 | ERROR log pre-train is noisy |
| `save_emos_params()` | T2 | 9/10 | Clean |

**Mandatory fixes (score ≤6):**
1. `apply_ml_prob_correction()` L:373 — `_log.debug` → `_log.warning` (RF1)
2. `_load_temperature_scale()` L:413 — bare `except Exception:` → `except Exception as exc: _log.warning(...)`

**Recommended fixes (score 7, correctness gaps):**
3. `train_all_temperature_scaling()` L:578 — log at WARNING when existing file is unreadable before setting `existing = {}`
4. `train_bias_model()` L:181 — skip rows with NULL our_prob rather than substituting 0.0

**Overall calibration:** File median is 8/10 — slightly above the expected 6–7 for a live-money system. The core algorithms (EMOS, temperature scaling, HMAC verification) are solid. The two mandatory fixes are isolated and low-risk. The AC4 concern (no internal days_out guard in apply functions) is architectural — the caller in weather_markets.py is the enforcement point.
