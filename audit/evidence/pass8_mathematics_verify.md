# Pass 8 (Mathematics) — Independent Verification

Re-examined all 4 findings from Pass 8 against current code in this worktree
(no edits made; read-only verification). Ran the pass's own reproduction
scripts fresh rather than trusting their cited output.

## 1. persistence_prob() symmetric-normal on monotonic running max — CONFIRMED
- Read weather_markets.py `_compute_persistence_prob` (~6108-6144) and
  climatology.py `persistence_prob` (223-259): confirmed `persistence_prob`
  is an unconditional `Normal(current_value, std_dev)` CDF with no
  monotonicity/one-sidedness handling, and `_compute_persistence_prob` does
  feed `metar.fetch_metar_daily_extreme(..., "max")` (a running max) into it
  for var="max"/days_out=0.
- Confirmed hourly path (weather_markets.py ~10207-10218): unconditional
  `blended_prob = 0.85*ens_prob + 0.15*persistence_p` whenever
  `persistence_p is not None`, no obs_override gate.
- Confirmed daily path (~11955-12015): `persistence_p` is only used in the
  weighted blend inside the `else` branch of `if obs_override is not None:`
  — i.e. only when the live-NWS-observation override is unavailable, matching
  the finding's own stated limitation.
- Re-ran `audit/reproductions/pass8_persistence_prob_monotonic_bias.py`
  against the live `climatology.persistence_prob` function this session:
  reproduced the exact cited numbers (0.6554 at +2F margin, 0.5000 exactly
  at threshold==running_max, mirror 0.3446 for 'below', +0.0517/+0.0750
  hourly blend deltas). No discrepancy from the original pass's numbers.
- Verdict: CONFIRMED, E2 (re-executed reproduction this session against real
  code, not just re-reading the original pass's transcript).

## 2. apply_seasonal_tilt() zero-floor wet/dry asymmetry — CONFIRMED
- Read acis_precip.py `apply_seasonal_tilt` (463-497): confirmed additive
  shift computed once, then `shifted = [max(0.0, s + damped_shift_in) for s
  in remaining_sums]` — a floor at 0.0 applied per-sample after an additive
  (not multiplicative) shift, exactly as described.
- Read weather_markets.py ~8836-8901 (`_analyze_monthly_rain_trade`'s far-tail
  block): confirmed the in-code comment already explicitly documents this as
  an "Accepted, documented limitation (opus review, 2026-08-17, L3)" —
  matching the finding's own limitations note verbatim (dry tilt
  under-applied vs wet, shadow-only, out of scope to fix here).
- Confirmed shadow-only claim by reading through line ~8990: the tilted
  `combined_totals`/`forecast_blend_signal`/`rain_forecast_blend_prob` are
  stored in a separate dict and never feed `blended_prob` (which is computed
  independently from `remaining_sums_tilted`, the pre-existing, unrelated
  shipped tilt) — so `rec_side`/`_price_and_size` sizing genuinely do not
  see this far-tail-blend tilt asymmetry.
- Re-ran `audit/reproductions/pass8_seasonal_tilt_floor_asymmetry.py` this
  session against the live `acis_precip.apply_seasonal_tilt`: reproduced
  the exact cited numbers (mean 0.0550->0.0688 wet, 0.0550->0.0527 dry,
  6.00x asymmetry ratio, exceed_frac 0.150->0.200 wet vs 0.150->0.150 dry
  unchanged).
- Verdict: CONFIRMED, E2 (re-executed reproduction this session; also
  independently confirmed the "already self-documented, shadow-only" framing
  by reading the surrounding code, not just trusting the finding's claim).

## 3. METAR-calibrated settlement confidence can't reach cron.py's >=0.80 gate — CONFIRMED
- Read settlement_monitor.py `_calibrate_metar_settlement_confidence`
  (277-345): confirmed it applies `ml_bias.apply_metar_calibration` and that
  its own docstring already states the exact same bounds the finding cites
  (~0.766 YES-lock ceiling, ~0.595 NO-lock ceiling, a=b=0.2262, c=0.4001) and
  explicitly frames this as a known, already-filed-as-backlog dormancy, not
  a live incident.
- Read ml_bias.py `apply_metar_calibration` (494-505): confirmed the actual
  formula is `sigmoid(a*ln(s) - b*ln(1-s) + c)`, which collapses to
  `sigmoid(a*logit(s)+c)` when a==b (confirmed `fit_and_save_metar_calibration`
  always fits params as `(a, a, c)`).
- Independently recomputed (fresh Python, this session, not copying the
  original pass's arithmetic) with a=b=0.2262, c=0.4001:
  - YES-lock raw=0.97 -> calibrated 0.76610 (matches cited ~0.766)
  - NO-lock raw_conf=0.97 (raw_p_yes=0.03) -> calibrated conf 0.59537
    (matches cited ~0.596)
  Both permanently below cron.py's threshold.
- Confirmed cron.py:1471 `if _sig_conf >= 0.80 and _sig_ticker in _open_by_ticker:`
  is the actual gate compared against this calibrated confidence.
- Verdict: CONFIRMED, E2 (independently re-derived the numeric bounds by
  hand-executing the real calibration function this session with fresh
  Python, rather than trusting the cited hand-calculation).

## 4. trade_cycle.py net_edge fallback diverges from order_executor's validate() gate — CONFIRMED (static)
- Read trade_cycle.py ~463-471: confirmed
  `net_edge = analysis.get("net_edge"); if None: net_edge = analysis.get("edge"); if None: net_edge = 0.0`.
- Read order_executor.py ~2011-2013 (`_validate_trade_opportunity`):
  confirmed `edge = opp.get("net_edge"); if edge is None: edge = 0.0` — no
  fallback to `opp.get("edge")`.
- Confirmed trade_cycle.py itself carries an inline comment (line ~670)
  explicitly acknowledging this exact divergence and asserting it "only
  ever makes tier classification MORE permissive than placement's real
  gate, never less" — matches the finding's quote precisely.
- Checked all `_price_and_size` call sites in weather_markets.py (10 call
  sites via grep) confirm `net_edge` is always set as a computed float
  (`net_edge = min(..., 3.0)` at line ~7843, never conditionally omitted)
  in every dict returned to callers — supports the finding's own
  "financial_risk: none currently in the live path" caveat; the gap is only
  theoretically reachable via a future analyzer or hand-built test dict.
- Verdict: CONFIRMED as an accurate, currently-dormant divergence. Evidence
  level stays E1 (static code comparison) — no live trigger exists in
  current code to reproduce at E2, matching the original pass's own
  characterization; I did not find a path that would elevate this beyond E1.

## Summary
All 4 findings independently reproduced/confirmed this session with no
material corrections. Two of the four (seasonal-tilt asymmetry, METAR
settlement-gate dormancy) are self-acknowledged, already-documented,
low-severity/shadow-only issues per the codebase's own in-code comments —
verification did not find them overstated or understated. Findings 1 and 4
retain their original severity/confidence assessment; nothing was
downgraded.
