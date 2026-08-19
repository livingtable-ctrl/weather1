# Pass 4 Feature Correctness — Independent Re-Verification

Session: re-verify 6 raw findings against current code. All file/line refs re-read directly
this session; two findings independently reproduced with runnable scripts (audit/reproductions/).

## Finding 1 — Between-bucket YES lock decided by instantaneous reading (settlement_monitor.py)
- Read settlement_monitor.py:200-274 (docstring + `_check_between_settlement` body) directly.
  Confirmed `comp_temp = max(current_temp_f, max_temp_f)` and the YES branch
  (`if max_temp_f is not None and lower_f <= comp_temp <= upper_f`) uses `comp_temp`, not
  `max_temp_f` alone — so when `current_temp_f > max_temp_f`, `comp_temp == current_temp_f`
  and the lock is decided by the instantaneous reading despite the docstring's explicit claim
  ("Requires a REAL max_temp_f; never locks YES from the current_temp_f fallback alone").
- Ran `audit/reproductions/pass4v_between_settlement_repro.py`:
  `_check_between_settlement(current_temp_f=67.0, lower_f=66.5, upper_f=68.5, max_temp_f=65.0)`
  → `{'locked': True, 'outcome': 'yes', 'confidence': 0.775, 'comp_temp_f': 67.0}`. max_temp_f
  (65.0) is below the band; the lock fired purely off current_temp_f=67.0. Exit 0, assertions
  passed. E2.
- Confirmed `tests/test_settlement_monitor.py:170-182`
  (`test_yes_requires_real_max_temp_not_current_temp_fallback`) only tests `max_temp_f=None`,
  not the present-but-lower case — the gap the finding describes is real.
- Confirmed cron.py:1434-1497 reads settlement signals via `read_settlement_signals` and closes
  matching open paper trades via `paper.close_paper_early()` when confidence>=0.80, with no
  ticker-family distinction visible in this code block.
- Verdict: CONFIRMED.

## Finding 2 — Exposure caps never read execution_log live positions
- Read paper.py:1299-1301 (`get_open_trades`), 1598-1673 (`get_city_date_exposure`,
  `get_directional_exposure`, `get_total_exposure`, `get_correlated_exposure`) — all key
  exclusively off `get_open_trades()` → `_load()["trades"]` (paper_trades.json). No
  execution_log reference in any of these functions (grep of `execution_log` in paper.py hits
  only comments/docstrings elsewhere, none in the exposure functions).
- Read paper.py:3447-3692 (`check_position_limits`) — `existing_cost` (3629-3633) and all
  cap checks (3645-3685) source from the same paper-ledger-only helpers.
- Read order_executor.py:2364-2368 (`_open_trades_list = get_open_trades()`, feeding
  `portfolio_kelly_fraction`/`corr_kelly_scale` at 2778-2783) — confirmed paper-ledger-only;
  its only execution_log touch nearby is `execution_log.was_ordered_recently()` (2702), a
  narrow 7-day same-ticker dedup guard, not a general exposure computation.
- Read main.py:4520-4576 — confirmed `check_position_limits()` is called for `action=="buy"`
  unconditionally (not gated on `_is_live`, which is computed independently at 4528).
- Verdict: CONFIRMED. This is a genuine, currently-dormant (live trading is gated off in this
  worktree) risk-control gap exactly as described.

## Finding 3 — Startup banner undercounts live-capable commands
- Read main.py:9562-9584 — `_live_orders_possible = cmd == "watch" and "--auto" in args and
  "--live" in args`; banner prints "Live orders are NOT placed by this command — only
  `watch --auto --live` can" whenever this is False, which includes `cmd_order`'s invocation.
- Read main.py:4528-4536 confirming `cmd_order` independently computes `_is_live` and calls
  `pre_live_trade_check` + places a real order when live.
- Correction to the finding's own evidence text: there is no `main.py order <ticker> buy/sell`
  CLI form. The actual routing (main.py:9696-9697) is `elif cmd in ("buy", "sell"):
  cmd_order(client, cmd, args[1:])` — i.e. `main.py buy <ticker> ...` / `main.py sell <ticker>
  ...`. `_live_orders_possible` does not check `cmd in ("buy", "sell")` either, so the
  substantive claim (banner undercounts live-capable commands) still holds; only the finding's
  illustrative invocation syntax was imprecise.
- Verdict: CONFIRMED (with a minor correction to invocation syntax, does not affect the claim).

## Finding 4 — trade_cycle.py net_edge fallback more permissive than order_executor's
- Read trade_cycle.py:459-474 — confirmed two-step fallback
  (`net_edge = analysis.get("net_edge") or analysis.get("edge") or 0.0`).
- Read trade_cycle.py:645-680 — confirmed in-code comment explicitly documents the divergence
  and asserts it is permissive-only (over-classify, not under-classify).
- Read order_executor.py:2007-2015 (`_validate_trade_opportunity`) — confirmed
  `edge = opp.get("net_edge"); if None: edge = 0.0` — no fallback to raw `edge`.
- Verdict: CONFIRMED. Self-documented in-code; low real-world impact as described (worst case
  a displayed tier that then fails placement, already surfaced by cron's own banner fix).

## Finding 5 — Far-tail floor-clipped additive shift under-applies dry-tilt correction
- Read acis_precip.py:463-500 (`apply_seasonal_tilt`) — confirmed line 499:
  `shifted = [max(0.0, s + damped_shift_in) for s in remaining_sums]`. Note: the finding's
  listed symbol `_far_tail_blend` does not exist in acis_precip.py — the actual function name
  is `apply_seasonal_tilt`, and `forecast_blend_signal` is a local dict variable, not a
  function. Substance of the claim (the floor-clip mechanics) is correct regardless.
- Read weather_markets.py:8840-8943 — confirmed the far-tail path (`combined_totals`, built
  from `tail_sums_tilted` via the SAME `apply_seasonal_tilt` call) feeds only
  `forecast_blend_signal["rain_forecast_blend_prob"]`/`..._tail_days`/`..._n_members`, a
  metadata dict; the in-code comment at 8858-8873 self-documents this exact limitation as
  "Not fixed here... this signal is shadow-only." Confirmed `blended_prob` (line 8943, the
  value that actually drives `recommended_side`/sizing) is built from `remaining_sums_tilted`,
  computed earlier and independently at line 8737 via the same `apply_seasonal_tilt` (so the
  near-term/already-shipped path has the identical floor-clip mechanic, but that's explicitly
  out of this finding's stated scope).
- Ran `audit/reproductions/pass4v_far_tail_clip_repro.py`: on a zero-heavy sample list with a
  ±0.8 shift, the negative (dry) shift was under-applied to −0.16 actual mean delta (vs −0.8
  intended) while the positive (wet) shift applied in full (+0.8 exact, no zeros clipped on the
  positive side since floor only clips values pushed below 0). Confirms the asymmetric
  under-application mechanically. E2.
- Verdict: CONFIRMED (INFO severity as originally assessed — shadow-only, no live-trading
  impact); minor symbol-name inaccuracy noted above does not affect the substance.

## Finding 6 — METAR force-close "dormant" claim is a coefficient snapshot, not a durable bound
- Read settlement_monitor.py:277-330 (`_calibrate_metar_settlement_confidence` docstring) —
  confirmed the "never exceeds ~0.766/~0.595" claim is attributed to the specific fitted
  coefficients (a=b=0.2262, c=0.4001) as of 2026-08-16, and that this is presented as current
  fact, not a durable invariant.
- Read ml_bias.py:396-505 (`fit_metar_calibration`/`apply_metar_calibration`) — confirmed
  weekly refit reuses `_fit_platt`'s bounds (ml_bias.py:299-322): `a<=0` rejected, `|a|<=5`,
  `|b|<=5` (the returned "c" is `_fit_platt`'s `b`) — no bound tied to the 0.80 force-close
  threshold anywhere in this path.
- Read metar.py:31-57 (`_dynamic_lock_in_confidence`) — confirmed the raw pre-calibration input
  is hard-bounded to [0.72, 0.97] as claimed.
- Numerically reproduced (`py -c`, this session) `apply_metar_calibration` using the exact
  coefficients cited in the docstring (a=b=0.2262, c=0.4001): YES-lock raw=0.97 → calibrated
  0.7661 (matches "~0.766" claim); NO-lock raw=0.97 → calibrated P(NO)=0.5954 (matches
  "~0.595" claim). Confirms the coefficient-snapshot ceiling claim is currently accurate. E2.
- Also numerically tested the bound EXTREMES the weekly refit is actually constrained to
  (a=b=5, c=±5): calibrated output reaches ~0.99999998 — i.e. the |a|<=5/|b|<=5 magnitude
  bounds do NOT prevent a future retrain from pushing the calibrated confidence above 0.80.
  This directly substantiates the finding's central claim that no bound ties the "dormant"
  property to future retrains. E2.
- Verdict: CONFIRMED, and the "no bound ties output range to 0.80 threshold" mechanism
  independently demonstrated (upgrades finding's evidence level from E1 to E2 for that specific
  sub-claim).
