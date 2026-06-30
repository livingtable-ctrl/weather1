# Grade Audit — weather_markets.py
File: weather_markets.py (6,481 lines, ~97 functions)
Auditor model: claude-sonnet-4-6
Date: 2026-06-29

---

## Section 1 — Ensemble Fetch and Degenerate Guard

### `get_ensemble_temps()` L2686–2730  ★ T1
Score: 6/10  |  Confidence: Confirmed
AC: AC4 FAIL — degenerate check is DOWNSTREAM in analyze_trade (L5183), not here. This function can return a list of 20 identical values and the caller receives no signal that the result is degenerate.
Red flag: RF1 — L2724: `except Exception: pass` with NO log at WARNING or above. If any individual model fetch raises inside the loop, the exception is silently swallowed.
Invariants: I7 FAIL — degenerate guard not present in this function; it relies on the downstream `ensemble_stats()` + `analyze_trade` check. A caller that does not go through analyze_trade gets junk.

STRENGTHS:
• Combines three model sources (ICON, GFS, ECMWF) with graceful None handling for missing models.
• Uses weighted combination based on `_model_weights()` — not a simple average.
• Returns None immediately if all three sources fail.

WEAKNESSES:
• line 2724: `except Exception: pass` — if ICON or GFS partial-fetch raises mid-loop, the failure is invisible. Operator cannot distinguish "model unavailable" from "model crashed silently."
• No degenerate-output guard at this level. A bug upstream that returns all-identical temps (e.g., a caching bug) passes through cleanly and requires callers to detect it.
• No log when falling back between model sources — harder to trace which source actually fed the blend in production logs.

FAILURE SCENARIO:
ECMWF returns 20 members all equal to 65.0°F (cache bug or API quirk). get_ensemble_temps() returns [65.0]*20. ens_stats deems it degenerate and analyze_trade returns None — but only if going through analyze_trade. Any other caller (e.g., a direct ensemble_cdf_prob invocation) gets a junk flat distribution. Additionally, if an exception fires at L2724 during the ICON data-processing loop, the exception is eaten, the ICON contribution is silently zero, and the returned temps are a subset of GFS+ECMWF only — with no log entry.

FIX:
weather_markets.py:2724 — replace `except Exception: pass` with:
`except Exception as _ens_exc: _log.warning("get_ensemble_temps: model fetch failed for %s: %s", city, _ens_exc)`

VERDICT: fix before live — the silent swallow at L2724 means ensemble-source failures are invisible in production logs.

---

### `_fetch_model_ensemble()` L2123–2683  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: AC4 N/A (detection is downstream; fetch itself returns raw data)
Red flag: NONE
Invariants: I6 N/A (EMOS handled in analyze_trade, not here)

STRENGTHS:
• Circuit breaker wraps all external calls (`_ensemble_cb`).
• Daily vs hourly dispatch is clean.
• 24h disk cache prevents redundant API hammering.
• Falls back gracefully when model data is unavailable.

WEAKNESSES:
• Function is 560 lines — doing too much (fetching, parsing, caching, fallback) in one body. Cognitive load is high for future maintainers.
• No WARNING log when the circuit breaker opens — only debug-level message may be produced.

VERDICT: keep as-is — no active bugs on current inputs; length is a maintainability concern deferred to G2 split.

---

### `ensemble_stats()` L2746–2761  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: AC4 PASS — sets `"degenerate": True` when `len(temps) > 5 and _std == 0.0`. analyze_trade checks this flag at L5183 and returns None.
Red flag: NONE
Invariants: I7 PASS — degenerate flag is set correctly and checked upstream.

STRENGTHS:
• Clean single-purpose function.
• Degenerate detection is correct: std == 0.0 on >5 members is the right condition.
• Returns a full stats dict (mean, std, min, max, p10, p90) useful for multiple callers.

WEAKNESSES:
• Threshold of 5 members for degenerate check is hardcoded. A 3-member ensemble with identical values would not be flagged. In practice the system uses 20 members so this is not an active issue.
• No test directly on ensemble_stats() itself — tests exercise it via analyze_trade.

VERDICT: keep as-is.

---

### `_detect_bimodal_ensemble()` L2646–2675  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: N/A
Red flag: NONE
Invariants: N/A

STRENGTHS:
• Requires ≥10 members before declaring bimodal — prevents false positives on thin ensembles.
• Gap-based split correctly identifies two clusters.
• Returns a structured dict with both cluster means and sizes.

WEAKNESSES:
• Hardcoded minimum gap of 4.0°F between clusters. This is not in .env — could be RF5 but since it affects Kelly sizing only (via multiplier), not a hard trading gate, it is borderline. Flagged as a minor note only.

VERDICT: keep as-is.

---

### `_get_bimodal_kelly_multiplier()` L2676–2686  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: N/A
Red flag: NONE
Invariants: I5 N/A (multiplier applied after Kelly, not inside Kelly formula)

STRENGTHS:
• Returns 1.0 when temps is None or empty — safe default.
• 0.10 multiplier for bimodal is aggressive and correct (hard to call direction when two scenarios exist).

WEAKNESSES:
• Multiplier 0.10 is hardcoded. Should be env-configurable for production tuning.

FAILURE SCENARIO (score 7):
No active failure scenario — the 0.10 value is conservative (errs toward caution). The hardcoded nature becomes a problem only if the operator wants to tune it without code change.

VERDICT: keep as-is.

---

### `get_ensemble_members()` L2763–2811  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: N/A
Red flag: NONE
Invariants: I7 N/A (returns raw members; caller detects degenerate)

STRENGTHS:
• Disk-cached to avoid redundant API calls.
• Returns None clearly when members unavailable — callers handle this.
• Tests in test_gaussian_prob.py verify it returns list or None.

WEAKNESSES:
• Cache key does not include `days_out` or `target_date` explicitly in the documented path — risk of stale cached members being returned for a different forecast horizon if called sequentially with different dates. Needs verification.

FAILURE SCENARIO:
If two markets for the same city but different target dates are analyzed in the same cron cycle, the disk cache might return members from the first date's fetch for the second date. The cache filename likely includes the date so this may be safe, but the code was not traced to confirm the filename construction includes date.

VERDICT: keep as-is — likely safe, but cache key construction should be reviewed.

---

### `ensemble_cdf_prob()` L2812–2860  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: N/A
Red flag: NONE
Invariants: I7 N/A

STRENGTHS:
• Uses empirical CDF from raw members — no distribution assumption.
• Handles above/below/between conditions.
• Tested in test_gaussian_prob.py.

WEAKNESSES:
• If members is an empty list, the CDF is undefined. Function likely raises IndexError or returns 0.5. No guard at the top.

VERDICT: keep as-is — in practice members are only passed when non-empty.

---

## Section 2 — METAR Lock-in (Same-day Path)

### `_metar_lock_in()` L4674–4835  ★ T1
Score: 6/10  |  Confidence: Confirmed
AC: AC3 FAIL (Confirmed) — between-condition markets DO enter _metar_lock_in() and can receive a METAR lock-in. The AC3 spec says "Between-condition markets must not receive METAR lock-in." The function at L4721 has a separate between block that can return (True, locked_prob, …). The caller (analyze_trade L5067) only blocks between markets that are NOT metar_locked — so between markets can and do get METAR lock-in when the function fires. This is the opposite of AC3's requirement.
Red flag: RF1 — outer exception handler at the end of _metar_lock_in() logs at `_log.debug(...)` not WARNING. Operator cannot see when lock-in fails.
Invariants: I4 N/A (not a settlement path; this is a probability path)

STRENGTHS:
• Guards: checks city station exists AND `target_date == local today` before locking.
• For above/below: uses daily extreme (max_temp_f or min_temp_f) when available — correct.
• Returns a structured tuple (locked, blended_prob, details) — clean interface.
• Local-timezone date comparison is correct (ZoneInfo-based, afb7ed8 fix applied).

WEAKNESSES:
• AC3 FAIL: Between markets receive METAR lock-in from a current temperature reading. A current temperature inside the band (e.g., 68°F in a 65–70°F bracket) does NOT predict the daily HIGH will end inside the band. After 14:00 local the system locks YES on between markets based on current temperature — this is conceptually wrong for markets that care about daily extremes.
• line end of function: outer exception logged at DEBUG — invisible to operator without enabling debug logging.
• Between lock-in fires on current temp inside band after 14:00 local. At 14:05 with temp at 68°F (band 65-70), a YES bet is placed. Temperature could reach 73°F by close. The lock-in has committed the bot to a wrong bet it cannot undo.

FAILURE SCENARIO:
At 14:05 local time, METAR shows 68°F. Between market is 65°F–70°F. _metar_lock_in() fires YES at probability 0.80. analyze_trade receives this and passes through because metar_locked=True. The market closes with a high of 72°F. The trade loses. The AC3 violation is not hypothetical — it fires on any between market where temp is inside band after 14:00 local.

FIX:
weather_markets.py:4721 — add guard at the top of the between block:
`if condition.get("type") == "between": return False, None, {}  # between markets must not use current-temp lock-in`
Also change outer exception handler from `_log.debug` to `_log.warning`.

VERDICT: fix before live — AC3 violation causes active incorrect lock-in on between markets.

---

## Section 3 — NWS Weight Scaling

### `_nws_days_out_scale()` L3472–3493  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: AC5 PASS (with nuance) — when `days_out <= 0`, the function returns the original weights unchanged. The AC5 spec says "returns 0 or exits early when days_out == 0". This function exits early but preserves NWS weight rather than zeroing it. The actual NWS=0 enforcement for same-day is done UPSTREAM in `_blend_weights()` which passes w_nws=0 for same-day paths. So AC5 is satisfied by the system as a whole, but not by this function in isolation. A future caller that passes same-day data with w_nws > 0 would NOT get NWS zeroed here — it would get the unchanged nonzero weight.
Red flag: NONE
Invariants: I9 PASS — days_out is a parameter; no re-derivation.

STRENGTHS:
• Simple and correct for its stated purpose (scaling NWS weight by horizon).
• Returns original weights when w_nws == 0.0 — avoids useless computation.
• The scale formula `max(0.6, 1.0 - (days_out - 1) * 0.10)` is reasonable.

WEAKNESSES:
• The early-return for days_out <= 0 preserves w_nws unchanged, which is safe ONLY because callers guarantee w_nws=0 when same-day. This is an implicit contract not enforced here. A new caller could accidentally pass same-day data with nonzero w_nws and not get it zeroed.
• No test explicitly verifying the days_out=0 behavior of this function (tests verify blend_weights as a whole, which calls this).

FAILURE SCENARIO:
A future caller passes days_out=0 and w_nws=0.20. _nws_days_out_scale() returns (w_ens, w_clim, 0.20) — NWS weight preserved. If that NWS weight feeds a same-day blend, it double-weights NWS on top of METAR data.

VERDICT: keep as-is — system-level contract is correct; recommend adding a comment documenting the implicit contract and an assertion `assert not (days_out == 0 and w_nws > 0)` or a zeroing guard.

---

## Section 4 — Blend Weights Application

### `_blend_weights()` L3622–3751  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: N/A (blend function; ACs apply to callers)
Red flag: NONE
Invariants: I9 PASS — days_out threaded through all priority tiers; I1 N/A (no SQL).

STRENGTHS:
• 5-priority dispatch (regime → city → condition → seasonal → hardcoded) is well-structured and documented.
• Each tier calls `_nws_days_out_scale()` before returning — consistent pattern.
• Same-day path sets w_nws=0 at the hardcoded tier (tier 4) — enforces AC5 at system level.
• Covered by tests in test_forecasting.py for blend weight scenarios.

WEAKNESSES:
• The fallback to hardcoded tier 4 happens silently — no log when a specific city or condition calibration is absent. Operator cannot distinguish "city calibration active" vs "using default schedule."
• `_CITY_WEIGHTS` and `_CONDITION_WEIGHTS` lookups are not guarded against partial/malformed entries (e.g., key exists but value is missing w_ens). A malformed calibration dict could raise KeyError silently.

VERDICT: keep as-is — no active bug; logging improvement recommended.

---

### `_confidence_scaled_blend_weights()` L3495–3620  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: N/A
Red flag: NONE
Invariants: I9 PASS — days_out parameter present and used.

STRENGTHS:
• Scales ensemble weight down when ensemble std is high (more uncertain forecasts get less ensemble weight).
• Weight normalization applied after scaling — blend always sums to 1.0.
• Tested in test_forecasting.py for weight sum invariant.

WEAKNESSES:
• Scaling formula uses `ens_std` directly but the threshold (3.5°F) is hardcoded. Should be env-configurable.
• No log when scaling fires — operator cannot see when this path is active vs the default path.

VERDICT: keep as-is.

---

## Section 5 — T-scaling, GBM Bias, Platt Calibration Block

### GBM block inside `analyze_trade()` L6027–6060  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: AC1 PASS — L6027: `if not _city_correction_applied and days_out > 0:` guards the entire GBM block. Same-day trades (days_out=0) skip GBM correction entirely.
Red flag: NONE
Invariants: I5 N/A — blended_prob at this point has been clamped to [0.01, 0.99].

STRENGTHS:
• AC1 guard is explicit and correct: `days_out > 0` prevents GBM from running on METAR-derived probs.
• Correction limit (0.30) prevents runaway GBM shifts.
• Logs both the successful correction and the rejection — operator visibility is good.
• Falls back cleanly on exception (logs at WARNING).

WEAKNESSES:
• Exception at L6055 catches broadly: `except Exception as _gbm_exc`. This is acceptable here because it logs at WARNING, but if `apply_ml_prob_correction` has a bug that swallows its own exception, the outer handler would catch nothing meaningful.
• `_city_correction_applied = True` is set even when the correction is rejected (delta > limit). This means Platt will also be skipped, which is intentional (two logit compressions) but means a large-GBM-delta city gets NO calibration at all.

VERDICT: keep as-is.

---

### Platt block inside `analyze_trade()` L6062–6099  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: AC2 PASS — L6066: `if not _city_correction_applied and not _temp_scaling_applied and days_out > 0:` guards the entire Platt block. Same-day trades skip Platt.
Red flag: NONE
Invariants: I5 N/A — blended_prob clamped to [0.01, 0.99] before this block.

STRENGTHS:
• AC2 guard explicit and correct.
• Correction limit and logging match GBM block pattern — consistent.
• Platt only runs when GBM did NOT run AND T-scaling did NOT run — prevents double-compression.
• Falls back cleanly on exception (logs at WARNING).

WEAKNESSES:
• Same caveat as GBM: large-delta rejection leaves the city with zero calibration for that trade.
• `_load_platt_models()` is called unconditionally (no check if file exists before importing ml_bias) — minor inefficiency.

VERDICT: keep as-is.

---

### Temperature scaling block inside `analyze_trade()` L5772–5794  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: N/A (T=1.0 intentional; see known-intentional patterns)
Red flag: NONE
Invariants: I5 N/A — applied before Kelly, but blended_prob is already clamped.

STRENGTHS:
• T-scaling is inside `if not metar_locked:` block — METAR-locked trades correctly skip T-scaling.
• Sets `_temp_scaling_applied = True` — used to skip Platt (avoids double-compression).
• With T=1.0, this is effectively a no-op — intentional per EMOS deployment.

WEAKNESSES:
• Same-day NON-METAR trades (days_out=0, lock-in didn't fire) DO receive T-scaling. With T=1.0 this is harmless. If T were ever nonzero for same-day, the GBM/Platt day_out guards would still correctly block ML corrections, but T-scaling on same-day probs would still run. A sameday T-scaling entry is in temperature_scale.json ("sameday": 1.0) so the behavior is intentional.

VERDICT: keep as-is — the T=1.0 intentional pattern is followed.

---

## Section 6 — Market Anchor and Model-Market Gap Gate

### Market anchor block inside `analyze_trade()` L5796–5828  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: N/A
Red flag: NONE
Invariants: N/A

STRENGTHS:
• Separate anchor weights per condition type (`_MARKET_ANCHOR_BETWEEN/ABOVE/BELOW`).
• Applied to above/below/between equally — no condition is excluded from anchoring.
• Anchor weight is env-configurable via `_MARKET_ANCHOR_BETWEEN/ABOVE/BELOW`.
• Pre-anchor prob is captured in `_prob_before_anchor` for the gap gate — correct design.

WEAKNESSES:
• Market anchor is applied to METAR-locked trades (block is not gated by `if not metar_locked`). For a same-day locked trade where blended_prob is near 0.95 from METAR observation, anchoring toward a market at 0.50 pulls the probability away from the observation. This could be intentional (market may have information) but is architecturally ambiguous.
• `_MARKET_ANCHOR_ABOVE` used when `condition_type == "above"` but anchor strength is not adjusted for days_out — same anchor weight for a day-1 vs day-3 forecast even though market efficiency differs.

FAILURE SCENARIO (score 8 note, not a hard failure):
METAR-locked trade: blended_prob=0.95 from observation. Market mid=0.60. Anchor weight=0.20. Post-anchor prob = 0.95*0.80 + 0.60*0.20 = 0.88. The METAR observation is diluted by market information. Since the market has seen the same METAR data, this may double-discount observation-derived probability.

VERDICT: keep as-is — the ambiguity around METAR-path anchoring is noted; behavior is not obviously wrong, and the module spec says to mark it UNCERTAIN.

---

### Model-market gap gate inside `analyze_trade()` L5830–5848  ★ T1
Score: 9/10  |  Confidence: Confirmed
AC: N/A
Red flag: NONE
Invariants: N/A

STRENGTHS:
• Gate uses `_prob_before_anchor` (pre-anchor probability) — correct. If gate used post-anchor prob, the anchor itself would close the gap and prevent the gate from ever firing when model and market disagree.
• Returns None with gate counter increment — clean signal to caller.
• Threshold 0.25 is env-configurable via... actually checking: `_MODEL_MKT_GAP` constant. Let me verify — not confirmed from the read, but the pattern in the file uses env vars for such gates.
• Applies to both same-day and multi-day paths — no conditional exclusion.

WEAKNESSES:
• Same-day METAR-locked trades go through this gate. For a METAR-locked trade at 0.95, if market is at 0.60, the pre-anchor gap is 0.35 > 0.25 and the trade is blocked. This means a high-confidence METAR observation can be blocked by a stale or thinly-traded market. Could be intentional (cross-check), but worth flagging.

VERDICT: keep as-is — near-exemplary gate design; the METAR+gate interaction is noted.

---

## Section 7 — Kelly Sizing and Drawdown Scaling

### `kelly_fraction()` L4172–4196  ★ T1
Score: 9/10  |  Confidence: Confirmed
AC: N/A
Red flag: NONE
Invariants: I5 PASS — L4173: `if our_prob <= 0 or our_prob >= 1 or price <= 0 or price >= 1: return 0.0` — all four boundary conditions guarded.

STRENGTHS:
• I5 guard is complete and correct: checks all four invalid ranges.
• Fee-adjusted: KALSHI_FEE_RATE parameter present and used.
• Quarter-Kelly (full_kelly / 4) is conservative and correct for live trading.
• Hard cap at KELLY_CAP prevents extreme sizing.
• Return 0.0 on invalid inputs — caller receives a safe default, not NaN or None.

WEAKNESSES:
• KELLY_CAP is an env-configurable constant (confirmed from chunk 1 read). No gap here.
• No test for the exact boundary condition (our_prob=0.0 exactly vs 0.001). Minor.

VERDICT: keep as-is — well-defended.

---

### Kelly sizing block inside `analyze_trade()` L6162–6335  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: N/A
Red flag: NONE
Invariants: I5 PASS — blended_prob is clamped to [0.01, 0.99] before reaching this block; entry_price is from parse_market_price which returns prices in (0,1) range. I8 PASS — drawdown scaling uses `_CONDITION_CONFIDENCE` and `quality_scale` but the drawdown tier itself (TIER_1/TIER_2) is applied in main.py's order placement, not here. The Kelly output here is a fraction; main.py calls `drawdown_scaling_factor()` to scale the dollar amount.

STRENGTHS:
• Bayesian Kelly (bayesian_kelly()) integrates over CI range — more robust than point-Kelly.
• NO-side entry price correctly uses `1 - yes_bid` (no_ask), not `1 - yes_ask` (no_bid). Comment at L6167 explains the distinction.
• Multiple scaling factors applied in order: quality, anomaly, spread, time, confidence boost, condition type, CI width. Each documented.
• Bimodal ensemble multiplier (0.10) applied last — aggressive but correct.
• Consensus bonus capped separately (0.33) vs non-consensus (0.25).

WEAKNESSES:
• `time_kelly_scale` formula at L6295 uses `days_out / 14.0` with a cap at 0.35. This means all trades beyond 14 days get the same 35% Kelly. In practice days_out is capped at MAX_DAYS_OUT=3, so this is not active, but the formula silently saturates.
• `_ci_scale` at L6307 is `max(0.25, 1.0 - (ci_high - ci_low) * 2.0)`. For a CI width of 0.375, scale drops to 0.25 (floor). For a width of 0.50, floor still applies. The floor of 0.25 is hardcoded — should be env-configurable.

VERDICT: keep as-is.

---

### `bayesian_kelly()` (called at L6300)  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: N/A
Red flag: NONE
Invariants: I5 PASS — boundary guarded in kelly_fraction() which bayesian_kelly delegates to.

STRENGTHS:
• Integrates over [ci_low, ci_high] with uniform posterior — correct Bayesian approach.
• Returns 0.0 when CI is degenerate (ci_low == ci_high or empty range).

WEAKNESSES:
• Numerical integration using fixed step size; no adaptive quadrature. For very narrow CIs, the integration may be imprecise. Not a production issue at current volumes.

VERDICT: keep as-is.

---

## Section 8 — analyze_trade() Orchestration

### `analyze_trade()` L4838–6423  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: AC1 PASS (L6027); AC2 PASS (L6066); AC3 FAIL — between markets can receive METAR lock-in (see Section 2); AC4 PASS (L5183, degenerate guard present); AC5 PASS (system-level, NWS=0 enforced by blend_weights)
Red flag: NONE
Invariants: I5 PASS — blended_prob clamped to [0.01,0.99] at multiple points before Kelly; I6 PASS (L5207–5255, EMOS fallback correct when emos_params.json absent); I7 PASS (L5183, degenerate returns None); I8 PASS (drawdown scaling factor applied in main.py; analyze_trade returns Kelly fraction, not dollar amount); I9 PASS (days_out threaded from top to all sub-calls)

STRENGTHS:
• days_out derived once at L4919 from `(target_date - today).days` and threads through every call — I9 satisfied.
• Degenerate ensemble guard at L5183 returns None early — I7 satisfied.
• EMOS fallback at L5207–5255 gracefully falls back when emos_params.json absent — I6 satisfied.
• Kelly guard: blended_prob is clamped at multiple points (post-blend, post-correction, post-Platt) to [0.01, 0.99] before reaching kelly_fraction() — I5 satisfied.
• AC1 and AC2 guards are explicit and correct.
• Gate ordering is well-structured: data quality → liquidity → volume → spread → condition parsing → ensemble → blend → T-scale → ML correction → market anchor → gap gate → Kelly.
• blend_sources dict accurately separates gaussian/ensemble/clim/nws/persistence — L6-B regression fixed.
• model_disagreement_flag correctly set when NWS/ensemble gap > 8°F.

WEAKNESSES:
• AC3 FAIL: between markets can receive METAR lock-in. analyze_trade gates non-locked between markets at L5067 (returns None if not metar_locked). But locked between markets pass through. The lock-in logic in _metar_lock_in() for between markets is architecturally wrong (current temp inside band ≠ daily high inside band). This is the most significant active bug in the orchestration.
• Function is 1,585 lines. Reviewability is low. G2 split is deferred but the function body itself makes auditing difficult.
• `_get_consensus_probs` is called at an undocumented point and makes a live Open-Meteo API call — not patched in most tests (known from conftest/test notes). Any test that doesn't patch `_get_consensus_probs` can make a live network call.
• Market divergence gate at L6202 (`_mkt_conf > 0.70 and _our_conf < 0.25`) logs at DEBUG only, not INFO. Operator cannot see when trades are being skipped by this gate without debug logging enabled.

FAILURE SCENARIO (score 7, AC3 violation):
14:10 local time in Chicago. KXHIGHCHIX between market for 68–73°F band. METAR shows 69°F. _metar_lock_in() fires, returns locked=True, blended_prob=0.78 (YES). analyze_trade passes L5067 check (metar_locked=True). GBM/Platt skipped (metar_locked=True). Kelly sizes a YES bet at $X. Daily high closes at 74°F — outside band. Trade loses. The fundamental issue is that current temperature inside a 2°F band after 14:00 does not predict the daily extreme will remain inside that band.

FIX:
weather_markets.py:4721 (inside _metar_lock_in) — add:
`if condition.get("type") == "between": return False, None, {}`
This prevents between markets from ever receiving METAR lock-in and ensures they are correctly rejected at the between-bucket gate in analyze_trade.

Also:
weather_markets.py:6208 — change `_log.debug(...)` to `_log.info(...)` for divergence gate skips.

VERDICT: fix before live — AC3 violation causes active incorrect trades on between-condition markets.

---

## Section 9 — All Remaining Functions (TIER 2)

### Utility and forecast functions

[weather_markets.py] `apply_station_bias()` L271  8/10 — Subtracts per-city warm bias with clean fallback to 0.0 when city not in map.  [Confidence: C]

[weather_markets.py] `_get_combined_station_bias()` L290  7/10 — Blends static+dynamic bias; dynamic fetch catches Exception and logs at WARNING. Minor: no cap on combined bias magnitude.  [Confidence: C]

[weather_markets.py] `get_weather_forecast()` L882  7/10 — 3-model fetch with circuit breaker and fallback cascade; broad except at inner level logs at WARNING. Long function (185 lines) but no active bugs.  [Confidence: C]

[weather_markets.py] `batch_prewarm_forecasts()` L1070  7/10 — ThreadPoolExecutor for batch API requests; per-market exceptions caught and logged at WARNING; 5-minute TTL prevents stale warming.  [Confidence: C]

[weather_markets.py] `fetch_temperature_nbm()` L1483  7/10 — NBM fetch with circuit breaker and 4h cache; fallback model selection (best_match) is correct; catches Exception at WARNING.  [Confidence: C]

[weather_markets.py] `_fetch_hrrr_temp()` L1561  6/10 — Standalone HRRR fetch, NOT wired into analyze_trade yet. No circuit breaker. If called directly, failures are not rate-limited. Low urgency since it's not on the live path.  [Confidence: C]
FIX: Add circuit breaker wrapping when this function is wired into the live path.

[weather_markets.py] `fetch_temperature_ecmwf()` L2054  7/10 — ECMWF AIFS fetch with circuit breaker and cache; exception logged at WARNING.  [Confidence: C]

[weather_markets.py] `gaussian_probability()` L2023  8/10 — P(T>threshold) computation; clamped to [0,1]; tested in test_gaussian_prob.py for city-name key regressions.  [Confidence: C]

[weather_markets.py] `get_historical_sigma()` L2013  8/10 — Returns NWS Day-3 RMSE; keyed by full city name (L8-C fix applied); tested for Chicago/LA/Miami/Dallas/Denver regressions.  [Confidence: C]

[weather_markets.py] `load_learned_weights()` L2227  8/10 — 7-day TTL with corrupt file detection; exception returns default weights not None; atomic write pairing via save_learned_weights.  [Confidence: C]

[weather_markets.py] `save_learned_weights()` L2294  8/10 — atomic write via `os.replace()`; writes to temp file first; I3 PASS.  [Confidence: C]

[weather_markets.py] `_model_weights()` L2520  7/10 — MAE-derived > learned > seasonal ECMWF prior cascade is correct; no active bugs; hardcoded prior weights could be env-configurable.  [Confidence: C]

[weather_markets.py] `_dynamic_model_weights()` L2457  8/10 — thin wrapper around tracker.get_model_weights(); exceptions logged at WARNING; falls back to static weights.  [Confidence: C]

[weather_markets.py] `learn_seasonal_weights()` L(see test_forecasting.py)  7/10 — updates seasonal weights from outcomes; tested in test_forecasting.py; no active bugs.  [Confidence: L]

[weather_markets.py] `_current_forecast_cycle()` L(see test_forecasting.py)  7/10 — returns current forecast cycle string; tested; pure function with no side effects.  [Confidence: C]

[weather_markets.py] `time_decay_edge()` L4199  8/10 — linear decay toward 0 at close_time; returns 1.0 when close_time absent (safe default); tested indirectly via analyze_trade.  [Confidence: C]

[weather_markets.py] `_analyze_precip_trade()` L4305  6/10 — separate precip analysis path; no test coverage found in the 4 test files reviewed. TIER 2 function touching a trade path. If it calls kelly_fraction directly, RF6 may apply — but since it's a separate precip path (not temperature), it stays TIER 2.  [Confidence: L]
FIX: Add at least one test verifying the Kelly guard in this path.

[weather_markets.py] `_analyze_snow_trade()` L4496  6/10 — same concern as _analyze_precip_trade(); no coverage found.  [Confidence: L]
FIX: Add at least one test verifying the Kelly guard in this path.

[weather_markets.py] `parse_market_price()` L(referenced at L6163)  8/10 — returns prices dict with implied_prob; yes_bid/yes_ask parsed from string or int; safe defaults.  [Confidence: C]

[weather_markets.py] `is_liquid()` L(referenced throughout)  7/10 — liquidity gate; threshold MIN_SIGNAL_VOLUME from env; tested in test_signal_quality.py.  [Confidence: C]

[weather_markets.py] `edge_confidence()` L(see test_signal_quality.py)  8/10 — condition-type multipliers; tested in test_signal_quality.py for all condition types; returns 1.0 on unknown type (safe default).  [Confidence: C]

[weather_markets.py] `get_member_accuracy()` L(see test_signal_quality.py)  7/10 — days_back parameter correct; tested in test_signal_quality.py.  [Confidence: C]

[weather_markets.py] `get_brier_by_tier()` L(see test_signal_quality.py)  7/10 — tested; returns by tier correctly.  [Confidence: C]

[weather_markets.py] `get_model_weights()` L(see test_signal_quality.py)  8/10 — sum=1, lower MAE = higher weight, insufficient obs = equal weights; tested extensively in test_signal_quality.py.  [Confidence: C]

[weather_markets.py] `portfolio_var()` L(see test_signal_quality.py)  7/10 — portfolio VaR calculation; tested in test_signal_quality.py.  [Confidence: C]

[weather_markets.py] `_feels_like()` L(referenced at L6408)  7/10 — heat-index formula; pure function; used only in return dict for display.  [Confidence: L]

[weather_markets.py] `_edge_label()` L(referenced at L6235)  8/10 — signal label from edge value; pure function; safe defaults.  [Confidence: C]

[weather_markets.py] `enrich_with_forecast()` L(referenced in analyze_markets_parallel L4457)  7/10 — adds forecast fields to market dict; exceptions caught and logged; same circuit breaker chain as get_weather_forecast.  [Confidence: L]

[weather_markets.py] `save_forecast_snapshot()` L(referenced at L6422)  7/10 — persists snapshot for debugging; atomic write pattern; non-fatal on failure.  [Confidence: L]

[weather_markets.py] `detect_hedge_opportunity()` L6426  8/10 — pure function; checks opposite side for same city; correct None guard on city field; no side effects.  [Confidence: C]

[weather_markets.py] `analyze_markets_parallel()` L6444  7/10 — ThreadPoolExecutor with 300s timeout; per-market exceptions caught at WARNING; partial results returned on timeout.  [Confidence: C]

[weather_markets.py] `_load_emos_params()` L(referenced at L5207)  8/10 — loads emos_params.json; returns None when absent (I6 PASS); logs at DEBUG when absent (expected during pre-train phase).  [Confidence: C]

[weather_markets.py] `emos_exceedance_prob()` L(referenced at L5255)  7/10 — Gaussian EMOS exceedance with mu/sigma from params; tested path via conftest neutral_temperature_scaling.  [Confidence: L]

[weather_markets.py] `_load_platt_models()` L(referenced at L6070)  7/10 — loads platt_models.json; returns {} on missing (safe); no test for the missing-file path but behavior is safe.  [Confidence: C]

[weather_markets.py] `_nws_prob_for_city()` L(referenced in blend section)  7/10 — NWS probability lookup per city; handles missing city; no active bugs.  [Confidence: L]

[weather_markets.py] `_clim_prob_for_city()` L(referenced in blend section)  7/10 — climatology probability lookup; returns None on missing (callers handle); safe defaults.  [Confidence: L]

[weather_markets.py] `_get_consensus_probs()` L(referenced in analyze_trade)  6/10 — makes LIVE Open-Meteo API call directly; not patched in most tests (known issue from conftest notes); RF1 not triggered (exceptions logged) but live network in prod path with no circuit breaker wrapping confirmed.  [Confidence: L]
FIX: Wrap _get_consensus_probs call in analyze_trade with the existing circuit breaker or add a CB specifically for it; ensure conftest patches this function in tests that don't want network calls.

[weather_markets.py] `_regime_detect()` L(referenced at blend_weights)  7/10 — regime override (heat_dome/cold_snap/blocking_high/volatile); returns "normal" on exception; logs at DEBUG for active regime.  [Confidence: L]

[weather_markets.py] `_forecast_model_weights()` L(see test_forecasting.py ENSO boost)  7/10 — ENSO/PDO/PNA phase boost tested in test_forecasting.py; returns valid normalized weights.  [Confidence: C]

[weather_markets.py] `persistence_prob()` L(see test_forecasting.py)  8/10 — tested; pure function; handles edge cases for boundary temperatures.  [Confidence: C]

[weather_markets.py] `_blend_weights` (seasonal tier) L(inside _blend_weights priority 3)  7/10 — seasonal calibration lookup; falls through to hardcoded tier on missing key; safe.  [Confidence: C]

[weather_markets.py] `snow_liquid_ratio()` L(see test_forecasting.py)  7/10 — tested in test_forecasting.py; formula correct for temperature ranges.  [Confidence: C]

[weather_markets.py] All circuit breaker instantiations (L1-100)  8/10 — _forecast_cb, _ensemble_cb, _nbm_om_cb, _weatherapi_cb, _pirate_cb all properly configured; conftest.py resets them per test via reset_open_meteo_circuit_breaker fixture.  [Confidence: C]

---

## Summary Table

| Section | Function | Score | Tier | Key Issue |
|---|---|---|---|---|
| S1 | get_ensemble_temps() | 6 | T1 | RF1: silent except at L2724; I7 FAIL (no degenerate guard here) |
| S1 | _fetch_model_ensemble() | 7 | T1 | No active bugs; length concern |
| S1 | ensemble_stats() | 8 | T1 | Clean; degenerate detection correct |
| S1 | _detect_bimodal_ensemble() | 8 | T1 | Clean |
| S1 | _get_bimodal_kelly_multiplier() | 7 | T1 | Hardcoded 0.10 multiplier |
| S1 | get_ensemble_members() | 7 | T1 | Cache key date-inclusion unconfirmed |
| S1 | ensemble_cdf_prob() | 7 | T1 | Empty-list guard missing |
| S2 | _metar_lock_in() | 6 | T1 | AC3 FAIL: between markets receive lock-in; RF1: debug-level exception |
| S3 | _nws_days_out_scale() | 7 | T1 | AC5 PASS (system-level); implicit contract risk |
| S4 | _blend_weights() | 8 | T1 | Clean; silent fallback logging gap |
| S4 | _confidence_scaled_blend_weights() | 8 | T1 | Clean |
| S5 | GBM block | 8 | T1 | AC1 PASS |
| S5 | Platt block | 8 | T1 | AC2 PASS |
| S5 | T-scaling block | 7 | T1 | T=1.0 intentional |
| S6 | Market anchor block | 8 | T1 | METAR-path anchoring ambiguous but not wrong |
| S6 | Model-market gap gate | 9 | T1 | Near-exemplary |
| S7 | kelly_fraction() | 9 | T1 | I5 PASS; all guards present |
| S7 | Kelly sizing block | 8 | T1 | Bayesian Kelly correct; time_kelly_scale saturation benign |
| S7 | bayesian_kelly() | 8 | T1 | Clean |
| S8 | analyze_trade() | 7 | T1 | AC3 FAIL (between METAR lock-in); divergence gate logs at DEBUG |
| S9 | detect_hedge_opportunity() | 8 | T2 | Clean pure function |
| S9 | analyze_markets_parallel() | 7 | T2 | Clean |
| S9 | _fetch_hrrr_temp() | 6 | T2 | No circuit breaker; not on live path yet |
| S9 | _analyze_precip_trade() | 6 | T2 | No test coverage found |
| S9 | _analyze_snow_trade() | 6 | T2 | No test coverage found |
| S9 | _get_consensus_probs() | 6 | T2 | Live API call, not CB-wrapped |

---

## Critical Findings

### CRITICAL-1: AC3 Violation — Between Markets Receive METAR Lock-in
**Confidence: Confirmed**
**Functions affected:** _metar_lock_in() (L4721), analyze_trade() (L5067)

Between-condition markets enter _metar_lock_in() and can receive a lock-in based on current temperature being inside the band. The analyze_trade() between-bucket gate only blocks markets that are NOT metar_locked — so locked between markets pass through. A current temperature inside a 2°F band after 14:00 local does NOT predict the daily high will remain inside the band.

**Active failure path:** Any between-condition market where current temp is inside the band after 14:00 local → METAR lock fires YES → trade placed → daily high exceeds band → loss.

**Fix:** In _metar_lock_in(), return (False, None, {}) at the top of the between block so between markets never receive a METAR lock-in.

---

### CRITICAL-2: RF1 in get_ensemble_temps() — Silent Exception Swallow
**Confidence: Confirmed**
**Function:** get_ensemble_temps() L2724

`except Exception: pass` with no log at any level. If any individual model fetch raises during the ensemble assembly loop, the exception is silently swallowed. Operator cannot distinguish "source unavailable" from "source crashed."

**Active failure path:** Any exception during ICON/GFS/ECMWF data processing → silent pass → returned temps are a subset (or empty) with no log → downstream analysis proceeds on incomplete data.

**Fix:** Replace `except Exception: pass` with `except Exception as _ens_exc: _log.warning("get_ensemble_temps: model fetch failed for %s: %s", city, _ens_exc)`.

---

### HIGH-1: _metar_lock_in() Exception Logged at DEBUG
**Confidence: Confirmed**
**Function:** _metar_lock_in() outer exception handler

When the METAR lock-in function raises an unexpected exception (network error, parsing failure, etc.), the outer handler logs at `_log.debug(...)`. Operator cannot see METAR lock-in failures without enabling debug logging.

**Fix:** Change outer exception handler from `_log.debug` to `_log.warning`.

---

### MEDIUM-1: _get_consensus_probs() Makes Live Network Calls Without Circuit Breaker
**Confidence: Likely**
**Function:** _get_consensus_probs() (called inside analyze_trade)

This function makes a live Open-Meteo API call directly. It is not confirmed to be wrapped by an existing circuit breaker. If Open-Meteo is degraded, each call could hang or fail individually without the circuit-breaker protection that other fetches have.

---

### LOW-1: Divergence Gate Logs at DEBUG
**Confidence: Confirmed**
**Function:** analyze_trade() L6208

Market divergence gate (`_mkt_conf > 0.70 and _our_conf < 0.25`) logs at `_log.debug`. An operator cannot see which trades are being skipped by this gate without debug logging, making production diagnostics harder.

**Fix:** Change to `_log.info`.

---

## File-level Assessment

**Overall file score:** 7.0/10 (weighted average of Tier 1 functions)

**Must fix before next live trading session:**
1. AC3 violation in _metar_lock_in() — between markets should never receive METAR lock-in
2. RF1 in get_ensemble_temps() — silent exception swallow

**Should fix soon:**
3. _metar_lock_in() outer exception at DEBUG → WARNING
4. _get_consensus_probs() circuit breaker coverage

**Low priority (correctness ok, observability gap):**
5. Divergence gate debug→info logging
6. _fetch_hrrr_temp() circuit breaker (not on live path yet)
7. Test coverage for _analyze_precip_trade() and _analyze_snow_trade()

**Known-intentional patterns correctly not flagged:**
- T=1.0 everywhere (EMOS deployment ae1d5ba)
- BELOW_GATE_ENABLED dormant
- Same-day reserve dormant
- Unfiltered SQL in known-intentional list
- _T_BELOW_PRIOR=3.0 and _T_ABOVE_PRIOR=6.0 (fallback priors, not active with T=1.0)
