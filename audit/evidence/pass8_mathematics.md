# Pass 8 — Mathematics — Evidence Notes

Scope: independent re-derivation of calculations touched by 2026-08-02→08-17
commits, focused on: far-tail climatology blend (d190d09d), persistence_prob
fix (b0f4cad2), var-split bias-correction (756d8596), EMOS gate (4557a77b +
ml_bias.py fit_emos/emos_exceedance_prob/emos_interval_prob), METAR
calibration weighting (d320142d), Kelly/confidence-tier gates (c9b0fc02,
4d198e1f, 55918ede), plus spot checks on positions.py (fc8e3558), realizable
bid/ask pricing (c6288b9c), between-bucket METAR lock-in math (bded3d6a), and
consistency.py's rain arbitrage edge formula (6845b62c).

## Methodology
Built independent reproduction scripts under audit/reproductions/ that
re-derive formulas from first principles / re-implement the formula
verbatim from source and run it on synthetic inputs, rather than trusting
the implementation's own self-checks.

## Verified CORRECT (no issues found)
- weather_markets.py `_price_and_size`: net_edge/edge/entry_side_edge/Kelly
  formulas — net_edge always co-populated with edge from a single source
  (never independently None), Kelly formula f*=(bp-q)/b standard and
  correctly fee-adjusted.
- climatology.persistence_prob: normal_cdf usage for above/below/between —
  correct P(X>t)=1-Phi, P(X<t)=Phi, P(lo<X<hi)=Phi(hi)-Phi(lo).
- b0f4cad2 persistence_prob dead-branch fix: now correctly resolves METAR
  daily-high via fetch_metar_daily_extreme instead of dead
  max_temp_f/high_f fields; sign/branch structure verified against source.
- ml_bias.fit_emos/emos_exceedance_prob/emos_interval_prob: Gaussian model
  mu=a+b*ens_mean, sigma=sqrt(max(c+d*ens_var,1e-6)); exceedance/interval
  probabilities use ndtr correctly (1-Phi and Phi(hi)-Phi(lo)); "below"
  call site correctly inverts via 1-emos_exceedance_prob. CRPS-minimizing
  fit is standard.
- 756d8596 var-split bias-correction: tracker.get_member_bias's sign
  convention (bias = mean(predicted-actual)) correctly SUBTRACTED from raw
  member temps in both get_ensemble_temps and batch_prewarm_ensemble; no
  double-counting; hourly path correctly excluded (bias={} when hour is
  set); city->global->0.0 fallback logic matches docstring exactly.
- reset_temperature_scale_for_emos / EMOS_COVERED_CONDITION_KEYS: confirmed
  ("global","above","below","between") all four included, matching the
  commit's claimed fix of the "'between' wrongly excluded" bug.
- utils.py MED_EDGE(0.15) vs _EDGE_TIERS max(0.15 LOW/live): confirmed the
  "provably subsumed" claim in c9b0fc02's docstring holds exactly at the
  boundary (>= vs strict < are complementary, no gap) using current live
  values — re-derived algebraically, not just read.
- metar.py C→F conversion fix (bded3d6a): val_f = val_c*9/5+32, standard
  and correctly applied only after the raw *f field is tried first.
- metar._dynamic_lock_in_confidence: recomputed all 4 docstring examples
  by hand from the formula (0.72+0.18*c_factor+0.07*h_factor, clamped to
  [0.72,0.97]) — all 4 matched exactly (0.720, 0.790, 0.881, 0.970).
- Between-bucket YES-lock two-layer margin (_metar_lock_in's
  _yes_inband_margin = half band width, then analyze_trade's
  _between_edge_margin = band_width/8): worked through the composed
  reachable region on a 2°F band — non-empty ([X+0.25, X+1] out of
  [X,X+2]), i.e. NOT the same "mathematically unreachable" dead-code bug
  the commit itself found and fixed for the old hardcoded 1.5°F constant.
- consistency.py find_violations' rain/temperature arbitrage edge formula
  (edge = bid_hi - ask_lo for the "above" ladder case): independently
  re-derived the synthetic-short payoff (buy YES_lo at ask_lo + buy NO_hi
  at 1-bid_hi) across all 3 outcome regions (X<=t_lo, t_lo<X<=t_hi,
  X>t_hi) — minimum guaranteed profit across all three is exactly
  bid_hi-ask_lo, confirming the formula's correctness from first
  principles, not just reading it.
- d190d09d far-tail climatology blend: no day-overlap/day-gap between the
  near-forecast prefix and the historical tail (tail_start_day =
  fetch_end_date.day+1, always resolves within the correct target month
  given the (remaining_start_date - today).days<=6 guard — walked the
  "before month starts" branch's date arithmetic by hand and confirmed
  fetch_end_date never crosses into an adjacent month). Cross-product
  combined_totals correctly avoids double-counting month_to_date_actual
  and correctly computes the exact expected value of the "pair each near
  member with a tail year" idea (matches the commit's own claim).

## Findings logged (see StructuredOutput)
1. METAR settlement-lag force-close gate (d320142d) — independently
   reproduced the claim that calibrated confidence can never reach the
   0.80 gate under the current fit (max ≈0.7661 YES-lock, ≈0.5954
   NO-lock) via audit/reproductions/metar_calibration_bound_check.py.
   Matches the commit's own disclosed numbers exactly. LOW severity: this
   is already known, filed as its own backlog entry by the team, and
   confirmed dormant (never scheduled/run in production).
2. trade_cycle.py's placement-gate net_edge fallback (mirrors
   order_executor._validate_trade_opportunity's edge checks, added in
   c9b0fc02/55918ede) falls back None→raw `edge`→0.0, while validate()'s
   real check falls back None→0.0 directly (no raw-edge fallback).
   Reproduced the divergence in isolation
   (audit/reproductions/net_edge_fallback_mismatch.py): a synthetic
   analysis dict with net_edge=None, edge=+0.30 clears trade_cycle's
   mirror gate but is unconditionally rejected by the real validate().
   Traced to _price_and_size (the sole source of both fields in every
   real analyze_trade path) always setting both together — so this
   specific gap is not reachable via current production code. Also found
   (after building the reproduction independently) that trade_cycle.py's
   own comments (lines 658-671) already document this exact asymmetry
   and its "only ever more permissive, never less" safety argument, which
   I independently verified holds (validate()'s unconditional-reject on
   missing net_edge is the strictest possible outcome, so trade_cycle can
   only ever match or exceed it in permissiveness in this branch). INFO
   severity: real, but already known/documented and provably harmless via
   validate() remaining the final placement gate.
3. Far-tail rain blend's logged `rain_forecast_blend_n_members` metadata
   (explicitly intended per its own comment to let "a future graduation
   analysis stratify by regime") reports only the near-forecast ensemble
   member count, not min(n_members, n_tail_years) — the real effective
   sample size of the deterministic cross-product combined_totals (whose
   raw length, n_members*n_tail_years, is hundreds-to-~1000 but is NOT an
   independent-sample count). A future analyst computing per-signal
   calibration/CI width from this logged n could overstate precision.
   Shadow/log-only, LOW/INFO severity, static reasoning only (E1).

## Reproductions
- audit/reproductions/metar_calibration_bound_check.py
- audit/reproductions/net_edge_fallback_mismatch.py
