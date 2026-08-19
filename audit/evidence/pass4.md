# Pass 4 — Feature Correctness — Evidence Notes

This session re-ran Pass 4 (Feature Correctness). `audit/evidence/pass4_verification.md`
already existed from a prior run of this same pass and had independently re-confirmed 4
findings; those are re-confirmed again here (still accurate, no code changes since) and
carried into this session's final output. This file documents the ONE NEW finding this
session added, plus a couple of areas checked and ruled out.

## NEW Finding: between-bucket settlement lock can lock YES off the instantaneous
## METAR reading when the authoritative running daily high is present but lower

- Code: `settlement_monitor.py::_check_between_settlement()` (~L242-274), called from
  `check_city_settlement()` (~L410-419).
- The YES branch is guarded by `if max_temp_f is not None and lower_f <= comp_temp <=
  upper_f`, where `comp_temp = max(current_temp_f, max_temp_f)`. When
  `current_temp_f > max_temp_f` (a realistic case — `fetch_metar()`'s cache and
  `fetch_metar_daily_extreme()`'s cache are independently TTL'd, per the function's own
  docstring, and confirmed by reading `metar.py`'s `_METAR_CACHE` / `_DAILY_OBS_CACHE`
  usage in `fetch_metar()` and `_fetch_daily_temps_f()`), `comp_temp` reduces to
  `current_temp_f` and the "requires a REAL max_temp_f" guard is bypassed in substance:
  the decision is driven entirely by the instantaneous reading, exactly the AC3 bug
  class `bded3d6a`/`39b1ba54` were written to eliminate.
- This directly contradicts the function's own docstring ("YES only from a real
  max_temp_f; never locks YES from the current_temp_fallback alone") and the test
  named for that exact invariant, `test_yes_requires_real_max_temp_not_current_temp_fallback`
  (tests/test_settlement_monitor.py:170) — that test only covers `max_temp_f=None`
  (fully unavailable), not `max_temp_f` being present but lower than `current_temp_f`.
  No test in the file covers the present-but-lower case.
- Reproduction (E2, actually run this session):
  `audit/reproductions/pass4_between_settlement_yes_lock_repro.py` — calls
  `_check_between_settlement(current_temp_f=67.0, lower_f=66.5, upper_f=68.5,
  max_temp_f=65.0)` directly (max_temp_f below the band, current_temp_f just now
  risen into it — i.e. the true running high has NOT been confirmed to reach the band,
  only the latest instantaneous reading has). Result:
  `{'locked': True, 'outcome': 'yes', 'confidence': 0.775, 'comp_temp_f': 67.0}`.
  `comp_temp_f == current_temp_f`, confirming the lock was decided by the
  instantaneous reading, not `max_temp_f`.
- Downstream consumer (verified this session, `cron.py` ~L1437-1491): 
  `read_settlement_signals()` → any signal (T-ticker or between-bucket alike, no
  ticker-family distinction in this code) with `confidence >= 0.80` and a matching
  open paper trade is auto-closed via `paper.close_paper_early()` with **no human
  review**. The `between` path does NOT go through `_calibrate_metar_settlement_confidence`
  (that calibration wiring, `d320142d`, is explicitly T-ticker-only) — so, unlike the
  T-ticker force-close path (dormant today because calibration caps its output
  below 0.80), the between-bucket path's raw, uncalibrated confidence (up to 0.95) is
  used directly against the 0.80 gate. A wider band than this repro's 2°F (common for
  KXHIGH*-B## markets) reaches >=0.80 confidence easily (confidence = min(0.95, 0.70 +
  risk_clearance*0.05); risk_clearance>=2.0 alone clears it) — so this is not merely a
  theoretical low-confidence edge case.
- Practical effect: a temperature that has JUST risen into a between-bucket band (and
  may still be climbing, since the authoritative running high hasn't confirmed it's
  peaked there) can be locked YES and used to force-close an open paper position,
  when the true daily high could still exceed the band later the same day (the actual
  settlement outcome would then be NO). This corrupts paper P&L and — because paper
  P&L from these forced closes feeds `paper.is_accuracy_halted()`'s rolling win-rate,
  which is one of `trading_gates.LiveTradingGate`'s live-order gates (per `d320142d`'s
  own commit message) — could distort the statistic that gates real capital.
- Whether this has fired in production is unverified from this worktree (same
  scheduling caveat Pass 7's sibling T-ticker finding documents: `cmd_schedule()`'s
  daily settlement-monitor task registration state on the real trading machine can't
  be checked from here).
- Distinct from Pass 7's Finding 1 (T-ticker branch uses the instantaneous reading
  outright, no max_temp_f involved at all) — this is a narrower residual gap in the
  code that specifically claims to have fixed exactly this bug class for the
  between-bucket branch.

## Re-confirmed from `pass4_verification.md` (no changes since, all still accurate)

1. Exposure caps (`paper.check_position_limits`, `order_executor._auto_place_trades`)
   are blind to `execution_log`'s live positions — sourced only from
   `paper.get_open_trades()` (paper_trades.json). Re-verified: `paper.py` L3626-3682
   (existing_cost/city-date/directional/correlated caps all via `get_open_trades()`),
   no `execution_log` reference in `check_position_limits`'s body.
2. `KALSHI_ENV=prod` startup banner (`main.py` ~L9567) still claims only
   `watch --auto --live` can place live orders; `cmd_order` reaches the same
   `_is_live`/`pre_live_trade_check`/`place_order(..., time_in_force=
   "immediate_or_cancel")` path via plain `main.py order <ticker> buy/sell`.
3. `trade_cycle.py` (~L466-471) falls back `net_edge = analysis.get("net_edge") or
   analysis.get("edge") or 0.0` for STRONG/MED tier classification, while
   `order_executor._validate_trade_opportunity` (~L2010-2012) only falls back
   `edge = opp.get("net_edge") or 0.0` — no fallback to raw `edge`. Self-documented
   in trade_cycle.py's own comment (~L658-671) as a deliberate, permissive-only
   divergence. LOW severity, re-confirmed present.
4. Far-tail rain blend's `acis_precip.py:499` floor-at-0.0 additive shift under-applies
   the dry-tilt correction for near-zero precip distributions; confirmed still
   shadow-only/log-only (feeds only `rain_forecast_blend_prob` metadata, not the
   `blended_prob` that drives `rec_side`/sizing). INFO severity, re-confirmed.

## Areas checked this session and NOT found to be bugs

- `monte_carlo.py`/`main.py._feature_importance_days_out` (`6364b38b`) — city-local
  ZoneInfo fix correctly implemented, single call site, UTC fallback on ZoneInfo
  failure logged.
- `weather_markets.py` `analyze_trade`/`_analyze_hourly_trade`/`fetch_temperature_pirate_weather`
  city-local date fixes (`0100bffe`) — verified every `datetime.now(UTC).date()` site
  remaining in the file after the fix; the ones still present (`_days_out_from_close_time`,
  persistence-prob ZoneInfo-failure fallbacks, activation timestamps, cache-key dates,
  etc.) are internally UTC-vs-UTC consistent or genuine best-effort fallbacks, not the
  city-local-vs-UTC mismatch class this commit targeted.
- `positions.py` (`fc8e3555`) shared Position read-model — `check_stop_losses`/
  `check_breakeven_stops`/`update_peak_profits`/`liquidation_price`/`_passes_exit_gates`
  read cleanly; no inverted conditions or off-by-ones found. The commit's own disclosed
  scope-out (`check_model_exits`/`_check_live_model_exits`/`_check_early_exits` still
  read raw dicts, `_liquidation_price` vs `_midpoint_price` divergence) was separately
  fixed by `c6288b9c` for the automated/manual paper exit paths (verified: `main.py`'s
  menu-4 close path now uses `_liquidation_price`, not `_midpoint_price`).
- `251e838e` accuracy-halt admin override — CLI-only (`grep` confirms no `web_app.py`
  route references it), `_parse_accuracy_override_args` positional parsing correct,
  `minutes<=0` guarded both in the parser's caller and inside `override_accuracy_halt`
  itself (raises `ValueError`, caught by `cmd_admin`).
- `1659e638` same-day dynamic slot scaling gate fix — `_sameday_effective_cap` and
  cron's nudge message now both key off `paper.get_sameday_band_stats()`'s own
  baseline total, consistently; no residual use of the broader/mismatched
  `count_settled_sameday_predictions()` in the dynamic-mode branch.
- `d37a3e04` STRONG/MED placement-count banner fix — `_placement_outcome_phrase`
  logic reads correctly for placed<found, placed==0, and placed>=found.
- `c9b0fc02`/`55918ede` trade_cycle STRONG/MED placement-gate mirroring — Kelly floor
  (0.002) and confidence-tiered min_edge mirroring in `trade_cycle.py` (~L664-706) now
  match `order_executor._validate_trade_opportunity`'s corresponding checks
  (`ci_adjusted_kelly`→`fee_adjusted_kelly`→0.0 fallback chain, `get_min_edge_for_confidence`
  call signature) exactly, closing the gap `c9b0fc02`'s own commit message had
  originally deferred.
- `8701f49d` GFS lockout gate removal — no residual references to the removed gate
  anywhere outside git history (grepped repo-wide).

## LOW/INFO observation (already self-documented by the team, logged per pass
## instructions for completeness)

- `d320142d`'s METAR-calibrated T-ticker settlement-lag force-close gate is provably
  dormant under the fitted coefficients as of 2026-08-16 (calibrated confidence caps
  at ~0.766 for YES / ~0.595 for NO, both below cron.py's 0.80 threshold) — the
  commit message and code docstring already disclose this and file it as a follow-up.
  Noted here only because the underlying METAR calibration model is auto-retrained
  weekly (`5d9b6c56`) with no re-verification step tying the "stays below 0.80" claim
  to future retrains — a future retrain's coefficients could silently un-dormant this
  path with no test or alert to catch the transition. DESIGN_CONCERN, LOW severity,
  no reproduction attempted (would require simulating a future retrain).
