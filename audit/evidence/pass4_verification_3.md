# Pass 4 (Feature Correctness) — Independent Re-verification (session 3)

All 6 raw findings independently re-checked against current code this session (not trusting prior pass4_verification*.md files, though results are consistent with them).

## Finding 1 — Between-bucket settlement lock-in YES from instantaneous reading
CONFIRMED, E2 (reproduced this session).
- settlement_monitor.py:242-274 `_check_between_settlement` read verbatim; `comp_temp = max(current_temp_f, max_temp_f) if max_temp_f is not None else current_temp_f` at L243-245 confirmed.
- Reproduced live: `_check_between_settlement(current_temp_f=67.0, lower_f=66.5, upper_f=68.5, max_temp_f=65.0)` → `{'locked': True, 'outcome': 'yes', 'confidence': 0.7749999999999999, 'comp_temp_f': 67.0}`. max_temp_f (65.0) is below the band; the lock fired purely off current_temp_f.
- tests/test_settlement_monitor.py L126-272 read in full: `test_yes_requires_real_max_temp_not_current_temp_fallback` (L170-182) only covers `max_temp_f=None`. No test anywhere in the class uses `max_temp_f` present-but-lower-than-`current_temp_f` — the exact gap the finding identifies is real.
- cron.py L1434-1497 confirmed: reads `read_settlement_signals(max_age_minutes=720)`, gates purely on `_sig_conf >= 0.80`, calls `paper.close_paper_early()` with no ticker-family (T vs B) distinction and no human review.
- Confirmed the between-bucket branch (settlement_monitor.py L401-453) never calls `_calibrate_metar_settlement_confidence` — only the T-ticker branch (L455-478) does (call site at L469). So the between-bucket confidence is used raw, uncalibrated, up to 0.95.

## Finding 2 — Exposure caps never read execution_log live positions
CONFIRMED, E1 (static, exact match).
- paper.py `get_open_trades()` (L1299-1301), `get_city_date_exposure`/`get_directional_exposure`/`get_total_exposure`/`get_correlated_exposure` (L1598-1673), and `check_position_limits()` (L3447-3686) all read exclusively from `get_open_trades()` → `_load()["trades"]` (paper_trades.json). `grep execution_log paper.py` returns zero calls to any execution_log read function — only unrelated comments.
- order_executor.py L2364 (`_open_trades_list = get_open_trades()`, from paper) and L2778-2783 (`portfolio_kelly_fraction`/`corr_kelly_scale` fed from the same paper-only list) confirmed. execution_log's only touch in this file is `was_ordered_recently()` (L2702), a narrow dedup, not an exposure check.
- main.py L4528-4576: `_is_live` computed independently at L4528; `check_position_limits()` called at L4546-4575 for `action=='buy'` unconditionally (no `_is_live` gate on whether the check runs) — confirms a live buy is checked against a cap that itself only counts paper exposure.

## Finding 3 — Startup banner undercounts live-capable commands
CONFIRMED, E1, with one minor phrasing correction.
- main.py L9567: `_live_orders_possible = cmd == "watch" and "--auto" in args and "--live" in args` confirmed verbatim.
- main.py L4528 (`_is_live = getattr(client, "base_url", None) != DEMO_BASE`) and the real `client.place_order(..., time_in_force="immediate_or_cancel")` call at L4703-4713 inside `cmd_order` confirmed — `cmd_order` independently computes live-ness and places real orders regardless of the banner's narrower check.
- Correction: the finding's phrasing "`main.py order <ticker> buy/sell`" is not the actual CLI syntax — dispatch is `elif cmd in ("buy", "sell"): cmd_order(client, cmd, args[1:])` (main.py L9696-9697), i.e. invoked as `main.py buy <ticker> ...` / `main.py sell <ticker> ...`. This is a cosmetic naming slip in the original finding, not a substantive error — the underlying claim (a plain buy/sell command is live-capable and undercounted by the banner) holds.

## Finding 4 — trade_cycle.py net_edge fallback more permissive than validate()
CONFIRMED, E1, exact match.
- trade_cycle.py L467-471: `net_edge = analysis.get("net_edge"); if None: net_edge = analysis.get("edge"); if None: net_edge = 0.0` confirmed verbatim (two-step fallback).
- trade_cycle.py's own comment at L658-679 explicitly documents the exact divergence from validate(), self-describing it as permissive-only.
- order_executor.py L2011-2013 (`_validate_trade_opportunity`): `edge = opp.get("net_edge"); if edge is None: edge = 0.0` — confirmed no fallback to raw `edge` field. Matches the finding exactly.

## Finding 5 — Far-tail dry-tilt floor-clip asymmetry
CONFIRMED, E1, matches description and is explicitly self-documented in-code as shadow-only.
- acis_precip.py L499: `shifted = [max(0.0, s + damped_shift_in) for s in remaining_sums]` confirmed.
- weather_markets.py L8858-8873 comment matches the finding's characterization near-verbatim (explicitly calls out the floor-clip asymmetry, "Not fixed here", "this signal is shadow-only").
- Traced data flow: `combined_totals` (built from the far-tail-tilted values) only feeds `forecast_blend_signal` (L8912-8933), which is merged only into a `"signals"` metadata/logging dict (L9051-9052). The value that actually drives `blended_prob`/`recommended_side`/sizing is `totals`/`ens_prob` (L8941-8943), built from `remaining_sums_tilted`, a separate, earlier computation not sharing this floor-clip codepath. Confirmed shadow-only claim.

## Finding 6 — METAR force-close dormancy is a coefficient-snapshot fact, not a durable invariant
CONFIRMED (as a design-concern characterization; not a demonstrated present-day bug), E1-E2 (numerically re-derived + live coefficient file read).
- Confirmed the *actual currently-saved* coefficients via `paths.METAR_CALIBRATION_PATH` (resolves to the main clone's `data/metar_lockout_calibration.json` per the worktree-data-dir gotcha): `a=b=0.22619580826228397, c=0.4000758536385143` — matches the commit-message figures the finding cites (a=b=0.2262, c=0.4001) exactly.
- Independently recomputed (not just taken on faith) `apply_metar_calibration`'s output at the extremes of metar.py's fixed `_dynamic_lock_in_confidence` range [0.72, 0.97]: YES-lock ceiling ≈ 0.766 at s=0.97 (sigmoid(0.2262·logit(0.97)+0.4001)); NO-lock ceiling (in confidence-space) ≈ 0.595. Both reproduce the docstring's claimed ~0.766 / ~0.595 figures.
- Confirmed `_fit_platt` (ml_bias.py L299-322) bounds are only `a>0, |a|<=5, |b|<=5` — no bound at all ties the fit to cron.py's 0.80 force-close threshold. A future fit with e.g. a=5,b=5 would push sigmoid(5·logit(0.97)+5) ≈ 1.0, clearly reactivating the gate.
- Confirmed cron.py's weekly retrain block (L2032-2052, `fit_and_save_metar_calibration()`) only fits/saves/logs the new coefficients — no comparison against the 0.80 threshold, no alert on crossing into "active" territory. This is a genuine, currently-unmitigated monitoring gap, exactly as described.
- This finding is explicitly a process/monitoring gap, not a present-day incorrect behavior — status reflects that (see per-finding verdict below).

## Summary
All 6 findings survive independent re-verification with no material changes to the original claims. One finding (#3) has a small factual slip in its own phrasing (CLI invocation syntax) that does not affect the substance. No finding was disproven.
