# Batch 15: Rain/snow/hurricane market category expansion

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch groups 5 **pre-existing** backlog item(s) (not from the 2026-08-18 audit) sharing **weather_markets.py, cron.py, settlement_monitor.py**. Each item's full existing entry is reproduced verbatim below from `backlog.txt` -- these already have their own Problem/Priority write-ups from earlier sessions; read them in full rather than treating the excerpt here as complete.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. Pre-existing backlog item (`backlog.txt:4`)

```
[OPEN 2026-08-16 -- found by opus review (effort=high) while shipping the
  settlement-lag METAR calibration fix immediately below this entry; not
  fixed in that same change -- see "Why not now" below.] METAR
  SETTLEMENT-LAG CALIBRATION MAKES CRON.PY'S >=0.80 FORCE-CLOSE GATE
  MATHEMATICALLY UNREACHABLE UNDER THE CURRENT FITTED MODEL -- ALSO, THE
  MODEL WAS FIT ON A DIFFERENT POPULATION THAN IT'S APPLIED TO HERE
Priority: Low -- the affected mechanism (settlement_monitor.py's T-ticker
  force-close) has never actually run in production. Confirmed via
  `data/cron.log` (1.8MB of real history, zero "SETTLEMENT LAG signal"
  lines ever) and via `schtasks /Query /TN KalshiWeatherSettlementMonitor`
  (task not registered on this machine -- cron.py's own comment near
  line 1444 already notes the 720min staleness default "predates
  settlement_monitor.py ever actually being scheduled to run"). This is a
  design gap to close before the mechanism goes live, not an active bug.

Problem:
  `metar._dynamic_lock_in_confidence()` is hard-bounded to [0.72, 0.97]
  (its own docstring states this range explicitly). Run through the real
  fitted calibration model (a=b=0.2262, c=0.4001, n=33 as of this
  writing -- re-check `data/metar_lockout_calibration.json`, cron.py's
  D5 weekly block auto-retrains it) across that ENTIRE input range, the
  calibrated output never exceeds ~0.766 for a YES-lock or ~0.595 for a
  NO-lock -- both permanently below cron.py:1471's `_sig_conf >= 0.80`
  force-close gate. Independently verified by hand-computation (not just
  taking the review's word for it): swept clearance x hour x margin_f=1.0
  through both the raw formula and `apply_metar_calibration`, confirmed
  max(calibrated) = 0.7661 (YES) / 0.5954 (NO) < 0.80 with no exceptions.

  Separately: `ml_bias.fit_metar_calibration()` is fit on
  `tracker.get_metar_lockout_calibration_data()` rows, which come from
  `weather_markets._metar_lock_in()` -- called with `margin_f=3.0`
  (default) against the daily running-extreme temperature
  (`fetch_metar_daily_extreme`). `settlement_monitor.py`'s T-ticker path
  calls the same underlying `check_metar_lockout()` with
  `margin_f=_SETTLEMENT_MARGIN_F=1.0` against the INSTANTANEOUS reading
  (`obs["current_temp_f"]`). The settlement path's raw confidence scores
  are drawn from a different population (different margin, different
  temperature basis) than the one the model was fit on -- applying the
  entry-path model here is an extrapolation, not a like-for-like
  correction, even though it still moves scores in the right direction.

What it would look like:
  Two independent pieces of follow-up work, only worth doing once the
  settlement monitor is actually scheduled and producing real signals:
  (1) Decide whether/how to rescale cron.py's 0.80 force-close gate for
  the calibrated scale -- note NO-locks cap at ~0.595 (worse than most
  reasonable confidence thresholds) even in the best case, so a single
  shared threshold for both outcomes may not make sense; a real decision
  needs real settlement-lag outcome data, not this synthetic sweep alone.
  (2) Consider fitting a settlement-path-specific calibration model
  (own margin_f/temperature-basis population) rather than reusing the
  entry-path one, once enough settlement-lag rows with real outcomes
  exist to fit one.

Why not now:
  No real settlement-lag data exists yet to inform either fix -- the
  scheduled task has never run. Rescaling cron.py's gate speculatively,
  before any real data shows what the calibrated distribution actually
  looks like in production, risks tuning to the wrong number. Shipping
  the calibration wiring itself (this file's next entry) with the gate
  left as-is is the conservative choice: it fixes the two-calibration-
  regimes disagreement the original entry reported, and the mechanism
  simply stays dormant (as it already has been) until this is revisited.

When to revisit:
  As soon as someone runs `py main.py schedule` to actually register the
  `KalshiWeatherSettlementMonitor` task (or otherwise starts running
  `settlement-monitor` regularly) and settlement-lag signals start
  accumulating with real outcomes -- pull real confidence distributions
  before picking a new threshold, and reconsider whether a
  settlement-path-specific calibration fit is warranted at that point.
```

### 2. Pre-existing backlog item (`backlog.txt:3469`)

```
[PARTIALLY RESOLVED 2026-07-28 (near-term <=16-day ensemble forecast signal)
  AND 2026-08-17 (>16-day far-tail blend, this update) -- both shadow/log-
  only; see resolution notes at the end of this entry. Still open: the
  actual graduation decision (does this signal correlate with real
  settlements well enough to change forecast_prob) -- data-gated, currently
  6 of the 20 settled predictions required, unaffected by this update]
  RAIN MARKETS -- MONTHLY MODEL HAS NO DAY-SPECIFIC FORECAST SIGNAL
Priority: Medium -- shadow-only today (RAIN_TRADING_ENABLED gate +
  TRADING_PAUSED both mean nothing sizes off this yet), but should be
  looked at before the rain model is ever trusted for real sizing.

Problem:
  Cron's `check_market_anomalies()` flagged the same 2-3 rain tickers as
  "price drifted against model" on 3 consecutive runs on 2026-07-27:
  KXRAINSTPM-26JUL-8 (our 39-43% vs market 68-70%), KXRAINNYCM-26JUL-6
  (our 7-10% vs market 30-44%), KXRAINNYCM-26JUL-7 (our 1-7% vs market
  14-21%), plus one-off KXRAINCHIM-26JUL-4. Investigated live rather than
  assuming a bug: reproduced `_analyze_monthly_rain_trade()`'s bootstrap by
  hand against real ACIS data (month-to-date actual + 30yr remaining-days
  history for NYC/StPetersburg/Chicago) and got raw pre-bias probabilities
  matching cron's "our" values almost exactly (NYC >6in: 6.7% vs cron's 7%;
  NYC >7in: 0.0% [never happened in 30 years] vs cron's 1%; StPetersburg
  >8in: 42.9% vs cron's 39%; Chicago >4in: 7.1% vs cron's 7%) -- the model
  is not malfunctioning, it's doing exactly what Step 2 (`1839d76`) built
  it to do.
  Root cause: the model's only "what's actually going to happen the rest of
  this month" signal beyond the 30yr climatological bootstrap is Open-Meteo
  Seasonal's ECMWF SEAS5 tilt, and that's a *monthly mean* only (already
  flagged as a limitation in this file's own RAIN/SNOW/HURRICANE MARKETS
  entry, Step 2 handoff item 1: "mean-only, no per-member spread ... can
  adjust central tendency but can't itself supply distribution shape") --
  it has no day-level resolution, so it structurally cannot see "a system
  is forecast to bring heavy rain on day 29" the way a trader checking an
  actual short-range forecast (or the market itself) can.
  Pulled Open-Meteo's real 7-day `precipitation_sum` forecast live for the
  divergent cities to check which side of each divergence looks right:
    - NYC: forecast for the remaining accrual days (Jul 27-31) sums to only
      ~0.87in -- nowhere near the 2.31in/3.31in still needed for rungs 6/7.
      The real short-range forecast supports the model's LOW probability,
      not the market's 30%/14% pricing -- on these two rungs the market
      looks like the mispriced side (or reflects something about these
      illiquid deep-OTM brackets this bot doesn't have visibility into),
      not the model.
    - St. Petersburg: forecast shows a building wet pattern right at
      month's end (0/0/0.9/2.7/6.5mm Jul 27-31, continuing into 13.2mm Aug
      1 -- just past this ticker's settlement), consistent with the
      market's higher 68-70% price. This looks like real information the
      climatology-only model can't see, not market noise.

What the fix looks like (not yet designed in detail):
  Blend a real short-range forecast signal for the remaining days of the
  current accrual month into `_analyze_monthly_rain_trade()`, on top of
  (not replacing) the 30yr empirical bootstrap -- Open-Meteo's regular
  forecast API (already used elsewhere in this bot, ~16-day horizon) covers
  "the rest of the month" for any ticker whose remaining days fit inside
  that window, which is most of a typical month once a chunk of it has
  already accrued. Needs its own design pass, not a mechanical wire-up:
  how to combine a per-day deterministic/ensemble forecast total with the
  bootstrap's right-skewed remaining-days resample (add the forecasted
  near days as a fixed increment before resampling history only for the
  tail beyond the forecast horizon?), and whether the existing SEAS5
  monthly-mean tilt becomes redundant for the near-term portion once a
  real day-level forecast is wired in (it would still be the only signal
  for the tail beyond 16 days out, e.g. brackets checked early in a month).

When to revisit:
  Before `RAIN_TRADING_ENABLED`'s shadow gate is ever allowed to size real
  trades. No live cost today (shadow-only + TRADING_PAUSED), but this is
  exactly the class of gap Step 2's own handoff predicted (item 1's
  "mean-only" caveat) and now has 3 days of live confirmation behind it.

RESOLVED (partially) 2026-07-28: shipped the near-term case -- when a
  ticket's entire remaining accrual window fits inside Open-Meteo's 16-day
  forecast horizon (exactly the situation in every 2026-07-27 divergent
  ticket), a real ensemble forecast is now fetched and logged as a
  candidate signal. Deliberately shadow/log-only, matching every other new
  signal's `SIGNAL_REGISTRY` rollout in this codebase (`run_trend`,
  `market_implied_distribution`, etc.): `_analyze_monthly_rain_trade()`'s
  actual returned `forecast_prob`/pricing/CI/sizing is completely
  unchanged -- this only adds a `signals: {"rain_forecast_blend_prob": ...}`
  key to the result dict for future validation, a new `rain_forecast_blend`
  entry in `SIGNAL_REGISTRY` (10th entry as of 2026-07-28, since shifted to
  11th by a 2026-08-01 insertion earlier in the registry; floor=20 settled
  predictions, tracked via `py main.py signals`), and nothing else.
  New `weather_markets._fetch_ensemble_precip_multiday()`: extends
  `_fetch_ensemble_precip`'s existing single-day ensemble fetch (same
  models/weighting/circuit breaker/host) to keep the full 16-day response
  instead of indexing out one date, summing each ensemble member's values
  across the requested date range. Member-index stability across days was
  confirmed live (2026-07-28, direct Open-Meteo API call) before relying on
  it: `precipitation_sum_memberNN` is one continuous simulated trajectory's
  day-by-day values within a single response, not independently-shuffled
  per-day, so summing by member index is a real per-trajectory total.
  Scope deliberately limited to the forecast-covered case only -- when the
  remaining window exceeds 16 days (early-month tickets), the signal is
  simply not computed this cycle. No historical-tail blending, no reuse of
  the SEAS5 tilt machinery for a partial-coverage case. That's the next
  increment, not this one, matching this project's established pattern of
  shipping in size-appropriate steps.
  A plan-review pass (10 rounds, user-requested) before any code was
  written caught 4 real issues: the originally-planned insertion point
  preceded where `threshold` is defined (would have been a `NameError`);
  the planned `count_fn` used a raw lambda instead of this codebase's own
  established closure-factory convention (fixed by adding
  `_count_signal_json_key`, mirroring `_count_signal_column`); the plan
  assumed a `result_dict` variable to mutate that doesn't exist (the
  function returns a dict literal directly, fixed via conditional
  dict-unpacking); and the new fetch call needed an explicit defensive
  try/except (a bug in new code must only ever cost the new signal, never
  the already-working bootstrap-only analysis it sits next to).
  Mutation-testing during first-pass implementation caught a real vacuous
  test (the "remaining window exceeds 16 days" test used a raising mock,
  silently swallowed by the new try/except regardless of whether the real
  scope-boundary check was correct -- fixed by switching to a call-counter)
  and 2 pre-existing test files with a hardcoded registry-size assertion
  needing an update to 10, not just new tests for the new signal
  (`test_forecasting.py`'s `test_registry_has_9_entries...`, renamed not
  just bumped, since its own name encodes the count and this project
  already hit the identical stale-count-name bug once before, SIGNAL
  GRADUATION session 2026-07-25; and
  `test_real_registry_entries_all_resolve_against_a_real_empty_db`).

  Independent `Agent(opus, effort=high)` review of the first-pass
  implementation, before push, found it was NOT safe to ship -- 3 real
  HIGH-severity issues, all fixed:
  (H1) `count_settled_signal_rows(json_key=...)`'s query unconditionally
  required `o.settled_temp_f IS NOT NULL`, but KXRAIN*M rows never populate
  that column (they write `settled_value` instead, confirmed against
  `count_settled_rain_predictions()`'s own join, which has no such filter
  for exactly this reason) -- meaning the new registry entry's count would
  have stayed permanently 0 regardless of how much real settled data
  accumulated, silently defeating the entire point of the shadow rollout.
  Fixed with a new `require_settled_temp: bool = True` parameter on
  `count_settled_signal_rows()` (tracker.py), `False` for this entry only,
  verified live end-to-end (a real settled prediction + signal now counts
  1, not 0, both via the tracker function directly and via the actual
  `SIGNAL_REGISTRY` entry's `count_fn()`).
  (H2) Open-Meteo pads a model's response with a FULL-length `time` array
  past that model's own real forecast horizon, filling the tail with
  nulls rather than truncating the array -- confirmed live (2026-07-28,
  direct API call): for a 16-day Denver request, `icon_seamless`'s real
  horizon was only 7 days and `ecmwf_ifs025`'s only 14. The first-pass
  `is_all_null` guard only caught a fully-null model, not a
  partially-covering one, so short-horizon members' truncated (and
  therefore systematically low) totals were being pooled with full-window
  totals as if equivalent -- for the exact ~2-week windows this feature
  actually runs against, not a rare edge case. Fixed by requiring a member
  to have a non-null value on every single requested day to be counted at
  all; a model whose horizon falls short contributes zero members instead
  of a biased partial one.
  (H3) The flagship end-to-end test's mocked members (1.0-6.0in) never
  exceeded its own 7.0in threshold even before the (also-omitted)
  month-to-date term, so its one probability assertion always landed on
  the 0.01 clamp floor regardless of whether the real formula was even
  used -- mutation-verified vacuous against both a wrong mtd term and the
  entire computation replaced with a hardcoded 0.0. Fixed with members
  straddling the threshold and a real non-zero month-to-date mock, plus an
  explicit self-check that the fixture lands strictly inside the clamp
  range.
  4 more MEDIUM/LOW findings, all addressed: the 16-day boundary itself
  had no dedicated test (mutation-verified 3 different wrong boundary
  values all passed unnoticed) -- added two boundary-exact tests; no test
  pinned the actual date range passed to the fetch (an off-by-one or
  swapped coords would've been invisible) -- added call-argument
  assertions; the reachable-but-untested "ticket checked after month-end"
  branch had its `date()` construction outside the try/except (not a live
  bug today -- the existing guard prevents it -- but fragile against a
  future edit) -- moved inside the try as belt-and-suspenders, added a
  regression test (using a direct `_analyze_monthly_rain_trade()` call
  with an explicit `close_dt`, not `analyze_trade()`'s wall-clock-derived
  close_time, to avoid the same real-vs-frozen-clock race this project's
  own `test_bias_correction_keyed_on_close_dt_month_not_accrual_month`
  already sidesteps); and a circuit-breaker test asserted only the final
  `None` return, not that a failure was actually recorded (a later
  same-cycle success on the unconditional ECMWF call was silently
  resetting the counter before the assertion) -- fixed to make every model
  fail and assert the failure count actually moved. Every fix above was
  itself mutation-tested (reverted, confirmed the corresponding test
  fails, restored) and re-verified live against the real API and a real
  isolated DB, not just against mocks.
  17 new/updated tests total: 14 new in `test_rain_markets.py`, 1 new in
  `test_tracker.py` pinning the `require_settled_temp` fix directly, and 2
  pre-existing `test_forecasting.py` tests updated for the registry-size
  change. Every new test mutation-tested
  against a reverted version of the real fix (kept a backup outside the
  repo and swapped via direct file copy, not `git checkout`, after an
  earlier mishap this same session where `git checkout -- <file>` was used
  mid mutation-test and wiped an entire file's real uncommitted work, not
  just the intended mutation -- see [[feedback_mutation_test_safe_revert]]).
  Full scoped regression (483 tests: `test_rain_markets.py`,
  `test_forecasting.py`, `test_tracker.py`, `test_infrastructure.py`) plus
  a broader sweep (`test_weather_markets.py`, `test_price_and_size.py`,
  `test_city_registry_manifest.py`, 253 more) all pass; ruff + ruff format
  + mypy clean on every touched file (`weather_markets.py`, `tracker.py`,
  `tests/test_rain_markets.py`, `tests/test_forecasting.py`,
  `tests/test_tracker.py`).

RESOLVED (partially) 2026-08-17: shipped the >16-day far-tail-blend case --
  when a ticket's remaining accrual window EXCEEDS Open-Meteo's 16-day
  forecast horizon (the gap this entry's own "when to revisit" section
  called out), `_analyze_monthly_rain_trade()` no longer skips the
  forecast-blend signal for the whole cycle. It now fetches the near-
  forecast-covered PREFIX of the remaining window and blends it with a
  resampled far-tail climatology for the days beyond it, instead of falling
  back to pure climatology (blended_prob/rec_side/sizing) for the entire
  remaining window the moment any part of it exceeds the horizon. Still
  deliberately shadow/log-only, matching the 2026-07-28 near-only case and
  every other new signal's `SIGNAL_REGISTRY` rollout convention in this
  codebase -- `forecast_blend_prob` is untouched, only
  `signals.rain_forecast_blend_prob` (plus 2 new metadata keys, see below)
  changes.

  Re-verified this entry's remaining claims live before starting (2026-08-
  17): `RAIN_TRADING_ENABLED` confirmed unset in the real `.env`;
  `count_settled_signal_rows(json_key="rain_forecast_blend_prob",
  require_settled_temp=False)` returned 6, confirming the graduation
  decision stays data-gated (floor is 20) and is genuinely unaffected by
  this update, per this entry's own explicit scope split.

  Design (2 decisions surfaced via AskUserQuestion before writing code,
  both later revised in part by the opus review below):
  - Combine each near-forecast member with far-tail climatology via a
    per-member `random.choice()` resample draw (matching this entry's own
    "resample climatology... combining into one distribution per simulated
    trajectory" language) -- REVISED post-review to a deterministic cross
    product; see H2 below.
  - Scope the existing SEAS5 monthly-mean tilt to the tail-only historical
    sums (a second `acis_precip.apply_seasonal_tilt()` call with a later
    `remaining_start_day`, mechanically reusing the function as-is) rather
    than reusing the full-remaining-window tilt already computed for
    `blended_prob` -- kept as designed; the near days now have a real
    forecast and don't need SEAS5's mean-only nudge on top of it, while the
    tail beyond the forecast horizon still does.

  Independent `Agent(opus, effort=high)` review (this entry's 3rd such
  review, after 2026-07-28's implementation review and its own earlier
  10-round plan review) found 2 HIGH + 3 MEDIUM + 5 LOW, all addressed:
  (H1) Verified LIVE against Open-Meteo (Denver, `forecast_days=16`): a
  16-day-out request falls entirely outside `icon_seamless`'s (~7-day) and
  `ecmwf_ifs025`'s (~14-day) real per-model horizons, so
  `_fetch_ensemble_precip_multiday`'s own full-coverage-only rule (the H2
  fix from 2026-07-28, correctly protecting against biased-low partial
  members) silently dropped BOTH every time -- the far case's "ensemble"
  was actually always exactly 30 `gfs_seamless` members, zero ECMWF weight,
  vs. the near-only case's ~130-member, ~77%-ECMWF-weighted ensemble, with
  no way to tell from the logged value alone. Fixed by capping the far
  case's own near-fetch to a real 14-day window (`today + 13`, recovering
  ECMWF's horizon at the cost of 2 fewer forecast-covered days folded into
  the tail instead) -- the near-only branch is untouched, still spans up to
  a genuine 16 days, matching the shipped 2026-07-28 values byte-for-byte
  (verified directly by reading the partition logic, not just asserted;
  mutating the near-only case's own boundary still fails its existing
  tests).
  (H2) With H1's real near-member count only ~30, the originally-chosen
  per-member `random.choice()` resample draw injected ~+/-8pp of pure
  sampling noise into the logged signal on every scan cycle (opus's
  60-repeat repro on an identical input: stdev 0.084) -- the same ticker
  would log a different value on consecutive cycles, directly inflating the
  Brier score this signal will eventually be judged on for graduation.
  Fixed by switching to a deterministic cross product (every near member
  paired with every tail-year value) -- the exact noise-free expected value
  of the same "pair each member with a tail draw" design intent, ~30
  members x ~15-30 tail years = a few hundred to ~1000 terms, negligible
  cost. This was a live revision of the AskUserQuestion-answered design
  mid-session -- surfaced transparently before applying rather than
  silently overridden, since cross-product had been on the original 3-
  option menu before a deflected first ask got simplified to 2 options.
  (M1) The per-member resample's `random.choice()` call consumed the
  SHARED global RNG stream before `acis_precip.bootstrap_ci_month_total()`
  ran later in the same function (also global-RNG-based), meaning the far
  case's own new code could shift the PRE-EXISTING bootstrap CI's stream
  position -- not wrong today (that CI is already unseeded in production)
  but it falsified this block's own stated "a bug here must only ever cost
  this new signal" contract, and would have silently changed sizing under
  any seeded/reproducible backtest. Resolved as a side effect of H2's
  cross-product fix, which removes the RNG call entirely from this block.
  (M2) The tilt-scoping test only recorded the spy's first call argument
  and never asserted on the resulting probability -- mutation-verified 3
  real bug shapes survived it (full_month_sums swapped for the tail sums
  themselves; the wrong full-window full_month_sums passed to the tail
  call; seasonal_mean_mm silently dropped to None for the tail call only).
  Fixed: the test now asserts all 3 call args on both the full-window and
  tail-only `apply_seasonal_tilt()` calls, a call-counter proving
  `seasonal_mean_mm` is reused not re-fetched, and pins the resulting
  probability via an INDEPENDENT direct call to the real (unmocked)
  `apply_seasonal_tilt()` with the same known inputs -- not by reading back
  whatever the code-under-test itself produced.
  (M3) The <15-usable-tail-years fallback (`combined_totals = None`) had
  zero test coverage -- mutation-verified that changing it to
  `combined_totals = member_totals` (silently treating the near-only
  members as if they already covered the full remaining window, missing
  every tail day's rain) passed the entire suite. Fixed with a dedicated
  test constructing history where every year is missing exactly 4 days,
  all inside the tail range -- pushes the tail range's own 20%-missing
  threshold over the edge while staying under it for the full remaining-
  window range, the only way to reach this branch without the earlier,
  unrelated `len(remaining_sums) < 15` check firing first. Also added a
  `_log.debug` on this branch (previously silent, unlike the analogous
  warning at the `len(remaining_sums) < 15` gate above it).
  (L1) The stored signal carried no marker of which regime produced it
  (near-only real-forecast vs. far-case forecast+climatology-blend, and per
  H1, materially different model composition) -- pooling both into one
  future Brier/calibration comparison without being able to stratify.
  Fixed by adding `rain_forecast_blend_tail_days` and
  `rain_forecast_blend_n_members` to the signal payload (both branches,
  `tail_days=0` for the near-only case) -- log-only, must ship before rows
  accumulate since it can't be retrofitted onto already-logged predictions.
  (L2) Opus review found this diff newly makes the "before month starts"
  branch reachable for the forecast-blend fetch for the first time (the
  shipped 2026-07-28 near-only guard structurally could never trigger
  there, since `remaining_end_date - today_local` was always >= a full
  month's length in that branch) -- and when `remaining_start_date` is more
  than ~7 days out, `icon_seamless`'s real horizon (live-probed above)
  means the ENTIRE requested range returns all-null for that model, which
  `_fetch_ensemble_precip_multiday`'s `is_all_null` check treats as a dead-
  model FAILURE recorded on the circuit breaker SHARED with every other
  market's ensemble fetch, not a benign empty result. Not reachable today
  given `RAIN_MAX_DAYS_OUT`'s own days_out gate on the caller side (a
  3-day margin from a plausible future env bump), but this diff's own
  restructuring is what newly exposes it, so fixed inline rather than
  filed separately (same-payload test: it's the same `rain_forecast_blend`
  fetch path this change already touches) with a conservative, explicitly-
  documented 6-day gap guard plus a dedicated regression test proving the
  exact previously-open gap (7-13 day gap, where the general fetch_end_date
  check alone would still have let it through) is now closed.
  (L3) `apply_seasonal_tilt()`'s additive-shift-then-floor-at-0.0 design
  assumes a multi-week distribution; a 1-3 day tail (common once a ticket
  is checked mid-month) is mostly exact zeros, so a dry SEAS5 tilt gets
  floor-clipped on most samples and is under-applied relative to a wet one.
  Accepted as a documented no-op: fixing it means changing
  `apply_seasonal_tilt()`'s own clamp behavior, which also feeds the
  ALREADY-SHIPPED full-remaining-window tilt `blended_prob`/`rec_side`/
  sizing depend on -- genuinely separate surgery, out of this change's
  scope. Magnitude is tiny (a fraction of an inch on a 1-3 day tail) and
  this signal is shadow-only regardless.
  (L4) Added a far-case analogue of the near-only case's own "existing
  calc is byte-identical with vs. without the blend" test
  (`test_far_case_signal_does_not_change_forecast_prob_or_ci`) --
  particularly relevant now that H2's cross-product fix removed the shared-
  RNG risk (M1) the original design carried.
  (L5) The original resample test's headline probability assertion landed
  on the clamp ceiling (every forced draw picked a deliberate outlier),
  the same clamp-collapse shape as 2026-07-28's own H3 finding. Superseded
  entirely by the new cross-product test
  (`test_far_case_cross_product_not_random_sampled`), which uses two clean
  value groups on each axis so the resulting fraction (375/600 = 0.625) is
  an exact combinatorial value strictly inside the clamp range that only a
  true cross product produces.

  Every fix (H1, H2, L2, L3-as-no-op-decision) mutation-tested via the Edit
  tool against a live-reverted version of the real code, confirmed the
  corresponding test fails, restored. Also mutation-tested the untouched
  <=16-day near-only branch's own boundary and off-by-one guards to confirm
  this restructuring didn't relocate a bug into them (it didn't).

  9 new/rewritten tests in `TestRainForecastBlendSignal`
  (`tests/test_rain_markets.py`; 68 tests collected in that file total, up
  from 65 after 2026-07-28's own additions): the far-blend/boundary tests
  updated for the 14-day cap; the tilt-scoping test strengthened (M2); the
  obsolete per-member-resample test replaced with the cross-product test
  (H2/L5); new tests for the 6-day gap guard (L2), the thin-tail-years
  fallback (M3), and the far-case byte-identical regression (L4). Full
  scoped regression re-run after all review fixes: `test_rain_markets.py`
  (68 tests) + `test_forecasting.py` + `test_tracker.py` +
  `test_infrastructure.py` = 600 tests, all pass; ruff + ruff-format +
  mypy clean on `weather_markets.py` and `tests/test_rain_markets.py`
  (mypy also re-checks the whole repo's other touched-adjacent files as
  part of its normal run, all clean).

  Still open, unchanged by this update: the graduation decision itself
  (data-gated, 6 of 20 settled predictions).

  Origin/master had moved 2 commits since this branch's start
  (`b0f4cad2` fix(weather_markets): source real daily-high for
  persistence_prob's dead branch; `e5331a8d` fix(main,order_executor,
  execution_log): route cmd_order's live fills through execution_log) --
  file-overlap check found real overlap on `weather_markets.py`,
  `backlog.txt`, and the generated `graphify-out/` files. Fast-forwarded
  (0 local commits, clean ff) then re-applied this session's stashed
  changes; `weather_markets.py`/`backlog.txt`/`tests/test_rain_markets.py`
  auto-merged with zero conflicts (different functions/regions), only the
  generated files (`BACKLOG_OPEN.md`, `graphify-out/graph.json`,
  `GRAPH_REPORT.md`, `cache/stat-index.json`) conflicted -- regenerated
  rather than hand-merged, per this project's standard convention. Re-ran
  lint/mypy (clean) and a widened regression sweep covering the merged
  origin changes' own touched files too (`test_rain_markets.py`,
  `test_forecasting.py`, `test_tracker.py`, `test_infrastructure.py`,
  `test_weather_markets.py`, `test_execution_log.py`,
  `test_live_execution.py`, `test_trading_gates.py`): 1054 passed, 4
  skipped, 0 failed.
```

### 3. Pre-existing backlog item (`backlog.txt:4524`)

```
[OPEN 2026-08-07 -- new, split out of "HURRICANE MARKETS -- TIME-TO-NEXT-EVENT MODEL SHIPPED SHADOW-ONLY" above per its own "user's explicit decision: defer as its own follow-up entry" note] HURRICANE NEXT-EVENT MODEL'S OCCURRED_THIS_SEASON SIGNAL IS SEASON-SCOPED, NOT ISSUANCE-SCOPED (KALSHI CONFIRMS ROLLOVER)
Priority: Low -- shadow-only, zero live-money risk regardless (see below);
  only affects the accuracy of a shadow-logged signal, not any real order.

Problem:
  Confirmed via the official Kalshi contract terms PDF (assets.kalshi.com/
  contract_terms/STORMDATE.pdf, fetched and read live this session -- not
  speculation): KXNEXTHURDATE/KXNEXTCAT5HURDATE's real Payout Criterion is
  "any Atlantic tropical storm has been classified... reaching <storm
  category> intensity... at any point after Issuance and before <date>" --
  anchored to THIS SPECIFIC CONTRACT's Issuance (its own open_time), not
  season start. And: "After the initial Contract, Contract iterations will
  be listed on an as-needed basis at the discretion of the Exchange" --
  Kalshi confirms it rolls this ticker over to a fresh "next hurricane"
  question (a new Issuance point) after each qualifying storm settles the
  current one early (the PDF's own Expiration Date rule: "If an event
  described in the Payout Criterion occurs, expiration will be moved to an
  earlier date").

  The shipped model (weather_markets._analyze_hurricane_next_event_trade)
  has no concept of "since this event's Issuance" -- occurred_this_season
  (event_type="hurricane") is keyed off `_get_cached_hurricane_count_to_date`,
  a SEASON-WIDE cumulative count, and the unconditional-mode fallback's
  first_occurrence_day() climatology measures "day of the season's FIRST
  qualifying storm" from historical Januarys/Mays, not "days elapsed since
  a specific mid-season Issuance date." Both are season-start-anchored
  proxies for what should be an Issuance-anchored question.

  Confirmed live this session: the currently open event's own open_time is
  2026-08-06 (mid-season, not season start -- itself circumstantial
  evidence this event may already be layered on prior seasons' pattern of
  waiting until real hurricane-season activity picks up before listing, not
  necessarily evidence of a rollover). client.get_events(series_ticker=
  "KXNEXTHURDATE") shows exactly ONE real event today ("KXNEXTHURDATE-
  26DEC01"); a second event ("KXNEXTHURDATE-0", sub_title "In 2025") exists
  but has ZERO markets ever created under it in any status (open/settled/
  closed) -- this product never actually launched with real markets before
  2026, so there is no historical rollover instance to directly observe and
  verify the exact mechanics against (e.g. whether ALL 8 "before <date>"
  siblings in an event settle simultaneously on rollover, or something more
  granular).

  Practical impact today: "since season start" and "since this event's
  Issuance" currently coincide -- the Atlantic hurricane count-to-date is
  genuinely 0 so far this season (confirmed live via the existing
  hurricane_count_to_date.json cache), and this event's own open_time
  predates that. The gap is real but latent -- it activates the first time
  a hurricane forms this season AND Kalshi lists a rollover event, at which
  point occurred_this_season=True would misprice a genuinely-still-open
  post-rollover question as already resolved (prob=0.99), and the
  unconditional-mode fallback's season-wide climatology would still be
  answering "day of season's first hurricane" instead of "days since this
  new Issuance."

Why not now:
  - Correctly fixing occurred_this_season requires a genuinely new live
    signal: WHEN each settled KXHURRICANENAMES storm actually crossed
    hurricane strength (a date), not just a cumulative season count, so it
    can be compared against a specific event's open_time. Real new data/
    cache design work, closer in size to the original count-to-date cache
    itself than to a quick fix.
  - User's explicit decision (asked via AskUserQuestion after this research
    was presented): defer as its own follow-up entry rather than build the
    full signal now or ship a partial mechanical fix (e.g. swapping the
    conditional-mode "as_of" reference from today's date to the market's
    own open_time -- a cheaper, strictly-more-correct change that was also
    on the table and also NOT taken this pass).
  - Entirely shadow-only in the meantime (HURRICANE_NEXT_EVENT_TRADING_
    ENABLED defaults off) -- the mispricing this entry describes can only
    ever affect a logged shadow prediction's accuracy, never a real order.

When to revisit:
  - The moment either (a) hurricane_count_to_date.json's ATL count first
    goes from 0 to 1 this season, or (b) client.get_events(series_ticker=
    "KXNEXTHURDATE") first returns more than the one current event --
    whichever comes first. At that point, check live whether the existing
    open "before <date>" markets settled/closed (confirming the rollover
    actually happened) before assuming the gap has activated.
  - If ever prioritized: build the per-storm-became-hurricane-date signal
    (mirrors refresh_hurricane_count_to_date's shape, sourced from settled
    KXHURRICANENAMES markets' own settlement timestamps rather than just
    their yes/no result), then key occurred_this_season off "any qualifying
    storm since this event's own open_time" instead of season-wide count.
```

### 4. Pre-existing backlog item (`backlog.txt:6855`)

```
[PARTIALLY RESOLVED 2026-07-30 — Rain Step 1+2+St. Petersburg onboarding and SNOW Step 1+2 all shipped; hurricane split out to its own entry, see "HURRICANE MARKETS — EXPLICIT GUARD ADDED AFTER A CONFIRMED LIVE GAP" near the top of this file. UPDATE 2026-08-07: that bracket's own "only hurricane's own probability model remains fully open" was stale — it predated 2 real hurricane sub-models that shipped shadow-only since (season-count 2026-08-03, time-to-next-event 2026-08-07, see that entry's own dated resolution blocks). Per-storm category (KXHURCAT), first-hurricane-by-name (KXFIRSTHURRICANE), and per-city landfall remain genuinely open — confirmed live 2026-08-07. STALE CORRECTED 2026-08-08: the "first-hurricane-by-name (KXFIRSTHURRICANE)... remain genuinely open" clause above was already wrong by the time it was written -- a 3rd hurricane sub-model (storm-order, KXFIRSTHURRICANE) shipped shadow-only the SAME DAY, in a later session (`9a7583a`, merged to master `a92956b` -- both confirmed live in master's history 2026-08-08). Re-verified live: KXHURCAT and per-city landfall genuinely still have no model (only appear in code as "still has no model" comments in weather_markets.py/paper.py) -- those two clauses hold; only the KXFIRSTHURRICANE one was stale.] RAIN / SNOW / HURRICANE MARKETS — UNTOUCHED CATEGORY SURFACE
Priority: was Low -- rain and snow are now Medium (both have real,
  shadow-gated probability models); hurricane's own model remains Low,
  unchanged.

Problem:
  "Climate and Weather" has 287 series total; this bot only ever looks at
  ~45 of them (KXHIGH*/KXLOW*, 20 tracked cities). Live-checked 2026-07-08:
  16 KXRAIN* city series exist, 2 currently with real open volume
  (KXRAINDENM -- Denver rain, 7 open markets; KXRAINSTPM, 7 open markets);
  ~23 snow series and ~40 hurricane series (path/category/landfall by city)
  exist but were all dormant/closed at check time. Separately, a handful of
  real weather markets (RAINNYC, KXRAINMIA, KXRAINNOSB) live entirely
  outside the "Climate and Weather" category (filed under "World"), so even
  widening check_series_drift's prefix filter within that one category
  wouldn't catch those.

What the fix looks like:
  Not a ticker-coverage fix -- each market type needs its own forecasting
  model with no shared architecture with the temperature-ensemble blend
  this bot runs today: precipitation-probability modeling for rain,
  snowfall-total modeling for snow, storm-track/intensity modeling for
  hurricanes. Treat as three separate potential product lines, not one
  task. If ever prioritized, rain is the most promising starting point --
  it already has real live volume (Denver/St. Paul) and precip-probability
  modeling is a smaller lift than storm-tracking.

Why not now:
  - No existing model architecture for any of the three.
  - Effort scales per market type, not incrementally with the current bot.
  - check_series_drift()'s KXHIGH*/KXLOW*-only filter is a deliberate
    simplification of an already-noisy check; widening it without picking
    a market type to actually act on would just add more unactionable noise.

When to revisit:
  - If there's real appetite to add a new market type (not just "cover more
    tickers") -- start with rain given current live volume.

  STEP 2 HANDOFF (separate future session, own plan + review -- do not
  build speculatively without re-checking these first):
  1. Real monthly-accumulation probability model in analyze_trade(),
     replacing today's unconditional None-return guard for KXRAIN*M
     tickers. No data provider gives monthly exceedance probability
     directly (confirmed this session against every provider this bot
     already uses) -- the model is a synthesis job, not a fetch. Recommended
     combo, researched and partly live-verified this session: NOAA ACIS
     StnData (`http://data.rcc-acis.org/StnData`, POST JSON, `elems:
     [{"name":"pcpn","interval":"dly"/"mly","duration":"dly"/"mly",
     "reduce":"sum"}]`, unauthenticated public API, this bot has never
     touched it) for (a) real month-to-date actual precip and (b) 30yr daily
     history to build an empirical per-city-month distribution of
     "remaining-days-of-month total" (bootstrap from historical years' D-to-
     month-end sums, not a parametric fit -- precip totals are right-skewed
     and bounded at 0), combined with the known actual-to-date value.
     Optionally tilt with Open-Meteo's Seasonal API (`seasonal-api.
     open-meteo.com/v1/seasonal`, `monthly=precipitation_mean`, ECMWF SEAS5,
     live-tested this session and confirmed working) as a directional nudge
     -- mean-only, no per-member spread, so it can adjust central tendency
     but can't itself supply distribution shape. NOAA CPC's monthly precip
     outlook (`mapservices.weather.noaa.gov/.../cpc_mthly_precip_outlk`) is
     categorical/tercile only, not a numeric CDF -- secondary signal at most,
     don't plan around it as a primary source. `_fetch_ensemble_precip`
     (existing single-day fetcher) is only practical for the final ~2 weeks
     of a month (16-day forecast cap) -- not a monthly solution on its own.
  2. Fix `_parse_market_condition()`'s real, currently-deferred bug: for
     KXRAIN*M tickers it silently collapses all 7 (or 4, NYC) ladder rungs
     into one identical `{"type": "precip_any"}`, discarding the real
     per-bracket threshold -- which lives in Kalshi's own `floor_strike`/
     `yes_sub_title`/`strike_type` market fields (confirmed via live raw
     JSON dump this session), NOT in a `-P<n>` ticker suffix or "inch" text
     in the title (real title is just "Rain in Denver in Jul 2026?"). Must
     be fixed before or alongside item 1 -- the model needs the real
     threshold to compare against.
  3. MANDATORY before any monthly-rain prediction/trade is ever logged: the
     position-sizing fail-open gap found this session. `MAX_CITY_DATE_
     EXPOSURE`/correlated-city penalties (paper.portfolio_kelly_fraction,
     order_executor.py's per-date cap) both key off `target_date_str` being
     a single-day string and silently skip when it's None -- which it
     always is for these tickers (no day component to parse). Once Step 2
     gives these tickers a real (non-None) grouping key, decide deliberately
     how monthly rain positions should be capped (extend the exposure system
     to accept a month-string key, treat the bracket's month as a synthetic
     date, or something else) -- don't let this silently start bypassing the
     caps just because target_date_str stops being None.
  4. Ladder/sibling grouping: `compute_market_implied_distributions()`'s
     current blanket exclusion needs to become real (city, month) grouping.
     `fit_market_implied_distribution()`'s weighted-least-squares machinery
     was confirmed this session to be structurally reusable (works off
     generic (lo, hi, mid_price, weight) tuples) but needs new sigma sanity
     bounds for an inches scale -- current bounds (0.1-50.0) are tuned for
     °F. NYC's ladder has only 4 brackets (not 7, a Kalshi listing choice,
     confirmed via settled history) -- handle variable ladder sizes.
  5. Settlement: `outcomes.settled_value` (float) is reusable for the
     monthly cumulative total, but `settled_var`'s existing semantic (a
     max/min-hour discriminator, from the hourly work) doesn't map cleanly
     onto "this is a monthly total" -- needs a new sentinel value or its own
     column, a real design decision, not a free reuse. `tracker.
     audit_settlement()` currently bails via `_parse_city_date()` returning
     None before reaching any settlement logic -- monthly rain needs its own
     settlement path triggered at month-end, not the "call once near a known
     instant" shape used for daily/hourly (a month's total is only final
     after the month ends, not observable at one point in time the way a
     daily high or an hourly reading is).
  6. Consensus-bonus precedent to follow, not rediscover: hourly Step 2's
     independent review caught that `_analyze_hourly_trade()`'s `consensus`
     flag was near-tautological (its two inputs weren't independent enough
     to justify `_price_and_size()`'s Kelly bonus) and had to be hardcoded
     `False` with a documented reason. A monthly-rain model will face the
     identical question the moment it has more than one signal (e.g. the
     ACIS-empirical estimate vs. the Seasonal-API-tilted one) -- verify real
     independence before wiring any consensus bonus, don't assume it.
  7. Shadow-only rollout: same `_gates_active()` pattern as every other new
     signal in this file (env var + sample-count floor via a new tracker
     count function) -- do not enable real sizing until enough settled
     monthly-rain predictions exist to validate real edge.
  8. Open question, not yet resolved: which NWS station does each city's
     rain market actually settle against. The pattern observed this session
     (Seattle=CLISEA, Denver implied CLIDEN, St. Petersburg=CLISPG) looks
     like the same per-city station this bot's temperature markets already
     use, but verify against each market's real `rules_secondary` text
     before assuming `metar.MARKET_STATION_MAP` transfers as-is -- don't
     guess.
  9. Snow and hurricane are separate, still fully open items (see this
     entry's own "Why not now" above) -- re-scout snow Nov-Mar, hurricane's
     per-city landfall markets Aug-Oct, before assuming either is ready.

RESOLVED 2026-07-20 (Rain Step 1 -- discovery/schema/safety only, no
  probability model; snow, hurricane, and rain's own Step 2 all still
  fully open, see below): re-verified this entry's own volume claim live
  before starting and found it badly stale, same pattern as the
  hourly-directional session's own re-verification catch. The 2026-07-08
  snapshot said "16 KXRAIN* series, 2 with real volume." Live query found
  17 real KXRAIN* series in "Climate and Weather" (not 16), and -- far more
  consequentially -- discovered `_analyze_precip_trade()`/
  `_analyze_snow_trade()` already exist, fully built, wired into
  analyze_trade() (this entry's "no existing model architecture for any of
  the three" claim was wrong) -- they've essentially never run against a
  real market, because KNOWN_WEATHER_SERIES listed the literal dead
  placeholder "KXRAIN", while `client.get_markets(series_ticker=...)` is an
  exact-match filter and the real per-city series live under different
  literal names (KXRAINSEAM, KXRAINDENM, etc.) that were simply never
  fetched.
  Live-verified 10 of those series are currently liquid, comparable
  monthly rain-TOTAL ladder brackets (Seattle highest at 203K volume down
  to Austin ~32K -- NOT "2 with real volume"; St. Petersburg/KXRAINSTPM is
  an 11th, real and live, but a genuinely new city and deliberately
  excluded, see below) -- a structurally different product from daily
  HIGH/LOW: one city-month event has 7 sibling ">N inches" brackets (NYC
  only 4, a Kalshi listing choice), all sharing one month-end close, the
  underlying quantity accruing over ~30 days rather than being a single
  point-in-time value. Snow: real series exist (33, all in "Climate and
  Weather") but 0 open markets anywhere as of 2026-07-20 -- pure July
  seasonality, not abandonment; re-scout Nov-Mar. Hurricane: per-city
  landfall markets (closest analog to HIGH/LOW) are dormant now, historically
  waking up mid-August through October; named-storm/category/count markets
  already have real pre-season volume but are a different product shape
  entirely.
  Confirmed the real monthly-accumulation probability model (Step 2) is
  genuinely new, unvalidated work, not a wiring fix: no data provider gives
  monthly exceedance probability directly (live-checked all of this bot's
  existing providers -- Open-Meteo forecast/ensemble, NWS, IEM/MOS,
  WeatherAPI, Pirate Weather -- none monthly-shaped). The real approach
  would blend NOAA ACIS StnData (month-to-date actual + 30yr daily history,
  a brand-new unauthenticated public API this bot has never touched) with
  Open-Meteo's Seasonal API (`seasonal-api.open-meteo.com`, ECMWF SEAS5
  monthly-mean forecast, mean-only, no per-member spread) -- a genuine
  synthesis job. Deliberately out of scope for this pass, same Step 1/Step 2
  split as HOURLY-DIRECTIONAL TEMPERATURE MARKETS above (commits
  `1acb308`/`06269b4`).
  St. Petersburg (KXRAINSTPM) deliberately excluded from Step 1: confirmed
  live it's a genuinely new city (none of CITY_COORDS's 20 keys), needing
  coordinated edits across ~8 separate scattered registries (CITY_COORDS,
  `_parse_city_from_ticker`, KNOWN_WEATHER_SERIES, metar.MARKET_STATION_MAP,
  `_STATION_BIAS_HIGH`/`_STATION_BIAS_LOW`, `_HISTORICAL_SIGMA`,
  climate_indices.py's AO/NAO/ENSO tables, `paper._CORRELATED_CITY_GROUPS`)
  -- the per-city registry consolidation this backlog already flagged
  (PER-CITY KNOWLEDGE IS SCATTERED, resolved 2026-07-19 as an auditor only,
  not a fix) is still not done, confirmed live (`data/cities.json` still
  doesn't exist). St. Petersburg is also the lowest-volume of the 11 rain
  series anyway.
  Shipped (weather_markets.py, consistency.py, paper.py, order_executor.py):
  `KNOWN_WEATHER_SERIES` now lists the 10 real per-city monthly rain series
  instead of the dead "KXRAIN" placeholder; new `_KXRAIN_MONTHLY_CITY`
  single-source-of-truth dict wired into `_parse_city_from_ticker()` (hand-
  verified against the substring fallback chain: 5 of 10 cities resolve by
  luck today, 5 -- Seattle, LA, Houston, SF, Dallas -- genuinely fail without
  the explicit fix, same "some pass by luck" shape as the hourly-directional
  LA/DC finding); a new unconditional `analyze_trade()` guard returns `None`
  for every monthly-rain ticker before any other gate (unlike the hourly
  guard, Step 1 has zero model for rain at all, so no target-hour-style
  partial pass-through); `compute_market_implied_distributions()` and
  `consistency._group_markets()` both get the same explicit exclusion
  (redundant for their final outcomes -- day-based date-parsing already
  fails these tickers -- but real for `_group_markets()`'s own L-8 warning,
  which would otherwise log a spurious "could not extract date from ticker"
  WARNING for all 10 rain markets on every single scan without it, caught
  and mutation-tested via `self.assertNoLogs`).
  Real, reachable safety gap found and closed, not just defense-in-depth:
  `paper.check_position_limits()` now blocks any qty/price for a monthly-
  rain ticker outright. Traced live: `main.py`'s manual "place order with
  explicit ticker+qty" command resolves city/target_date_str via a
  forecast-free enrichment *before and independently of* `analyze_trade()`,
  and when qty is given explicitly, `analyze_trade()` is never called at
  all -- it calls `check_position_limits()` directly with a real qty. Since
  `target_date_str` stays `None` for rain tickers, the existing city/date/
  directional/correlated-group caps were already silently skipped there --
  only the flat $250 per-market and 50% portfolio caps would still apply.
  Nothing could trade these tickers before this session (they weren't even
  fetched), so blocking manual orders too isn't a regression from any prior
  working state. `portfolio_kelly_fraction()` (paper.py) and
  `_auto_place_trades()`'s per-date cap (order_executor.py) got comment-only
  documentation of why they're provably unreachable instead of redundant
  code guards -- both are hot, general-purpose paths used by every market
  type; touching them for a provably-unreachable case would add regression
  risk without closing a real gap (explicit user decision, asked via
  `AskUserQuestion`).
  `check_series_drift()` extended to watch `KXRAIN*` alongside `KXHIGH*`/
  `KXLOW*` (explicit user decision, not a generalization to "any
  KNOWN_WEATHER_SERIES prefix" -- KXTEMPxxxH stays deliberately excluded,
  matching this same session's earlier standing decision for that market
  family). Real subtlety found during a mandatory 10-pass plan review (user
  asked for it explicitly, matching the hourly-directional precedent): once
  `live_weather` includes `KXRAIN*`, `get_series_list()` returns ALL 17 real
  rain series, including ~7 this bot deliberately doesn't track (dormant
  daily/one-off variants, and KXRAINSTPM) -- without accounting for those,
  the drift-check would warn about them as "missing" every single day
  forever, recreating one level down the exact permanent-noise problem the
  function's own docstring already warns against. Fixed with a new
  `KNOWN_UNTRACKED_RAIN_SERIES` set (deliberately not reusing
  `KNOWN_DEAD_WEATHER_SERIES` -- these are real/live series, not retired
  tickers), built from a fresh live query at implementation time (not
  copied from the session's own research-summary text, which had some
  noisy substring false-positives), each entry commented with why
  (dormant/0-open-markets vs. deferred-real-city). Verified both directions
  with dedicated tests, not just the flagging case.
  `_parse_market_condition()`'s real bug (would silently collapse all 7
  ladder rungs into one identical `{"type": "precip_any"}`, discarding the
  real `floor_strike` threshold, since Kalshi carries the threshold as a
  first-class field/`yes_sub_title` rather than title text or a `-P<n>`
  ticker suffix) is documented in-code but deliberately NOT fixed --
  confirmed unreachable today via all 3 real call paths (analyze_trade's
  new guard, compute_market_implied_distributions's exclusion,
  backtest.py's target_date-is-None skip); real fix is Step 2 work.
  37 new tests (tests/test_rain_markets.py new; additions to
  test_weather_markets.py, test_consistency.py, test_series_drift.py),
  every guard/exclusion/gate mutation-tested via `git stash` -- one weak
  test caught and fixed during mutation-testing itself: the first version
  of the `_group_markets()` exclusion test only asserted `find_violations()
  == []`, which stayed green even with the exclusion reverted (the outcome
  doesn't change, only log noise does) -- strengthened to assert log
  absence directly (`self.assertNoLogs`), confirmed THAT assertion fails
  with the exact predicted warning when reverted. 376 tests pass across the
  full regression sweep (test_weather_markets.py, test_consistency.py,
  test_series_drift.py, test_rain_markets.py, test_dead_code_scan.py,
  test_market_implied_distribution.py, test_hourly_markets.py,
  test_phase2_batch_i.py, test_paper_metrics.py, test_trading.py,
  test_cron_integration.py); ruff + ruff format + mypy clean.
  Followed the same process as HOURLY-DIRECTIONAL TEMPERATURE MARKETS: 3
  parallel Explore-agent research passes feeding a Plan-agent-drafted plan,
  `EnterPlanMode`, and a mandatory 10-pass (this session went further, ~20)
  self-review before presenting -- which caught the `KNOWN_UNTRACKED_RAIN_
  SERIES` noise problem and a real scoping-creep risk (a first draft said
  "generalize check_series_drift to any KNOWN_WEATHER_SERIES prefix," which
  would have silently pulled KXTEMPxxxH back into drift-checking against
  this session's own earlier decision) before any code was written.
  Given the size, independently reviewed with 3 parallel `Agent(opus,
  effort=high)` passes scoped by subsystem (discovery/parsing/analyze_trade
  guard; grouping/drift-check noise-prevention; the safety-critical
  check_position_limits guard), matching this session's own earlier
  precedent for large multi-subsystem changes. All 3 came back clean on
  correctness (no live-money-relevant bug in any of the 4 source files),
  but 2 caught real test weaknesses -- fixed before push, not just noted:
  (1) `test_rain_only_list_produces_no_distributions` was vacuous --
  `parse_city_date()` already returns `None` for rain tickers regardless of
  the new explicit exclusion, so the test stayed green even with the
  exclusion deleted (confirmed by mutation-testing it). Added
  `test_exclusion_holds_even_if_a_date_were_parseable`, which patches
  `parse_city_date()` to return a real (city, date) for a rain ticker --
  simulating the exact forward-guard scenario the exclusion's own docstring
  describes -- and confirmed THAT test fails correctly when the exclusion is
  removed. (2) `check_position_limits()`'s guard test suite never covered
  the case where `city`/`target_date_str` are both non-None (they always
  are None today, but the review flagged this as the one behaviorally
  meaningful untested case, since it would lock in the guard's
  before-everything ordering against a future refactor). Added
  `test_blocks_even_when_city_and_date_are_present`, mutation-tested by
  temporarily weakening the guard to skip when city/date are present and
  confirming the new test catches it.
  39 tests total (up from 37), full regression sweep re-run after the
  fixes (262 tests across test_weather_markets.py/test_consistency.py/
  test_series_drift.py/test_rain_markets.py/test_phase2_batch_i.py/
  test_paper_metrics.py); ruff/mypy clean.
  Still fully open: snow (re-scout Nov-Mar), hurricane (re-scout Aug-Oct for
  per-city landfall markets), St. Petersburg onboarding, and rain's own Step
  2 (the real ACIS+Seasonal-API monthly-accumulation probability model,
  shadow-gated per the established `_gates_active()` pattern before ever
  live-trading).

RESOLVED 2026-07-21 (Rain Step 2 -- the real monthly-accumulation
  probability model, own settlement, shadow-only rollout; all 9 handoff
  items above closed; snow, hurricane, and St. Petersburg onboarding still
  fully open): pushed `1839d76`.
  Re-verified every handoff claim against live state before writing code,
  rather than trusting the Step 1 snapshot. Two claims turned out
  substantially simpler/more-resolved than scoped: (5) settlement --
  Kalshi's own market data carries the literal settled monthly total
  (`expiration_value`) once `status="finalized"`, confirmed live across
  Denver (7 brackets, 2 months) and NYC (4 brackets) -- no independent ACIS
  re-derivation needed for settlement itself, only for the forecast model's
  own inputs. (8) which station -- fully resolved, not just re-verified: all
  10 cities settle at `"CLI" + metar.MARKET_STATION_MAP[city]` minus the
  leading `K`, zero exceptions including NYC (whose `KNYC` already meant
  Central Park for daily temperature, and ACIS `sid="NYC"` independently
  resolves to "NY CITY CENTRAL PARK" -- consistent, not a coincidence).
  Two genuine design decisions (item 3's exposure-cap keying, item 5's
  settlement schema) surfaced via `AskUserQuestion` and resolved only after
  two rounds of user pushback ("are you sure") that each caught something
  real the first pass missed -- see [[project_weather1_kalshi_bot]]'s dated
  session entry for the full re-derivation trail. Landed: settlement schema
  leaves `outcomes.settled_var` NULL for rain rows (ticker prefix already
  disambiguates everywhere else in this codebase, `settled_var` had zero
  production readers); exposure-cap keying uses the market's real
  `close_time` date -- the same field every other market type already uses
  for `target_date`, not a parallel bookkeeping system or a synthetic
  accrual-month value -- so item 3's MANDATORY position-sizing fail-open
  gap closes for free via the existing `portfolio_kelly_fraction()`/
  per-date-cap machinery once these tickers carry a real value, with
  `parse_city_date()` itself deliberately left untouched (still returns
  `None` for KXRAIN*M, walling off `analyze_trade()`'s ~1500 lines of daily-
  only date arithmetic from a monthly-accrual product).
  Tracing every consumer of `target_date` (40+ call sites, not a sample)
  before committing to the exposure-cap design surfaced 3 real, previously-
  dormant bugs that had to be fixed alongside the feature, since they'd
  start firing silently the moment `target_date` carried a real value for
  this ticker family: a string-prefix date comparison mistaken for a parsed-
  date comparison (`monte_carlo.py`, `main.py` x2 -- new shared
  `main._target_date_due()` helper); silent exception-swallowing on an
  unparseable grouping key (`order_executor.py`, 3 sites -- now logs a
  warning, fallback behavior unchanged); and a literal `"None"` string
  written to the DB instead of real SQL `NULL` (`tracker.py`, 3 sites, plus
  a related `column IS NULL` vs `column=?` SQL-semantics fix in
  `settle_analysis_attempt` -- SQL `= NULL` never matches, even a NULL
  column).
  Shipped: new `acis_precip.py` module (NOAA ACIS StnData month-to-date
  actual + ~30yr historical daily precip, handling `"T"`/`"M"`/`"S"` ACIS
  sentinels; Open-Meteo Seasonal `monthly=precipitation_mean` -- NOT
  `precipitation_sum`, confirmed live that 400s -- as an optional
  directional tilt) feeding a bootstrap resample of "remaining-days-of-month
  total" against the market's `floor_strike` threshold, wired into new
  `_analyze_monthly_rain_trade()`; `_parse_market_condition()` fixed at its
  root (item 2 -- reads `floor_strike`/`strike_type` directly, no longer
  falls through to the `precip_any` collapse); `tracker.audit_settlement()`
  new branch (checked before the generic city/date early-return, since that
  always fires first for these tickers); shadow-only rollout
  (`RAIN_TRADING_ENABLED` + `>=20` settled predictions) mirroring
  `_hourly_gates_active()` exactly, including `check_position_limits()`'s
  "shadow-only means no paper order either" stance (not just no live
  order). Item 6's consensus-bonus caution followed exactly as flagged:
  ACIS-empirical and Open-Meteo-tilted are not independent sources (the tilt
  is a nudge on the same physical baseline, not a second estimate) --
  `consensus=False` is hardcoded, never computed, matching hourly Step 2's
  own caught bug. Item 4 (real (city, month) ladder grouping for
  `compute_market_implied_distributions()`/`consistency._group_markets()`)
  deliberately deferred -- confirmed log-only, never gates a trading
  decision for any market type today, user-approved scope cut.
  Given the size, used `EnterPlanMode` and a mandatory multi-pass self-
  review (same pattern as every prior Step-2-scale change) -- caught a real
  mypy-narrowing hazard before it shipped (the gate restructuring's
  conditional guards break mypy's ability to prove `target_date`/`forecast`
  non-`None` for the rest of `analyze_trade()`; fixed with targeted
  `assert`s at points where the narrowing is structurally guaranteed, not
  blanket suppressions -- caught mid-implementation via an isolated `git
  worktree` diff after an earlier same-directory-copy baseline comparison
  gave a false "pre-existing" read, itself only caught by re-verifying after
  a direct user request to fix lint findings too).
  Independent review scaled to 3 parallel `Agent(opus, effort=high)` passes
  by subsystem (model/gating/condition-parsing; settlement/shadow-gate/
  exposure-cap; the 3 pre-existing date-bugs + calibration-pool leak +
  an unrelated live `schema_validator.py` bug found via a real cron-run
  report mid-session). No HIGH findings, but real MEDIUM ones fixed: a
  month-to-date ACIS fetch failure was silently coerced to 0.0 (could badly
  underestimate real accrued rain if the fresh fetch fails mid-month while
  cached history stays available -- now fails closed, no trade); the
  calibration-pool leak-prevention fix was incomplete, covering only 2 of 6
  live mechanisms reading the same predictions data -- extended to
  `train_bias_model`, `train_platt_per_city`, both `get_*_calibration_cli`
  functions, and `calibration.py`'s `calibrate_seasonal_weights`.
  Per two new standing-process rules the user set this session (now in
  [[feedback_implementation_workflow]] steps 15/16: real bugs found via
  adjacency must be fixed in-scope unless massively out of scope, and every
  reviewer finding must be explicitly addressed regardless of how soft its
  wording sounds), every remaining LOW/informational finding was closed
  too, not left as "the reviewer said it wasn't a bug": manual CLI paths
  (`cmd_market`/`cmd_order`) now fall back to the model's close-derived date
  instead of logging NULL; `backfill_emos_data()` no longer re-fetches every
  historical rain ticker from Kalshi on every non-force run forever; the
  settlement client cache now rebuilds on a `KALSHI_ENV` runtime flip; two
  stale comments fixed (a city-grouping count that said "8 of 10" but was
  actually 9 -- only Seattle is ungrouped -- and a misleading `elif`-vs-
  fallthrough comment in `monte_carlo.py`).
  Separately, the same session's cron-run report surfaced (not caused by
  this change) a genuinely unrelated pre-existing bug: `schema_validator.py`
  was flagging `bid=0.00/ask=0.00` (a market with no resting quotes at all)
  as an "inverted spread," contradicting its own stated intent -- fixed to
  match `parse_market_price()`'s existing `has_quote = mid > 0` convention.
  Also cleaned up a real self-inflicted incident from this session's own
  debugging (not a code bug): an ad-hoc `python -c` script tracing one of
  the date-bug fixes called `_auto_place_trades()` directly against the
  live production databases without sandboxing `execution_log`'s/
  `tracker`'s DB paths, leaving one contaminated ticker (`KXBADDATE3`,
  paper not live) across 3 rows in 2 DB files -- traced exhaustively (every
  table in both files) and deleted by exact primary key, verified via
  before/after row counts.
  Three tests were caught as vacuous only by mutation-testing after they
  first passed for reasons unrelated to the fix under test -- an unrelated
  ML-fit holdout-MSE gate (`train_bias_model`'s test rewritten to inspect
  the actual `fit()` call's training-set size), an unrelated validation-row
  floor (`calibrate_seasonal_weights`'s test rewritten with a correctly-
  sized row count), and a deterministic alternating-probability pattern that
  made the underlying Platt fit itself reject regardless of the exclusion
  (`train_platt_per_city`'s test rewritten with a randomized pattern
  matching this file's own existing passing-test convention). All three now
  genuinely mutation-proof. 984 tests pass across the full scoped regression
  sweep; ruff/mypy clean (0 errors, not "pre-existing" as first miscounted
  -- see above).
  `RAIN_TRADING_ENABLED` stays unset until real shadow data accumulates --
  expect the 20-settled-prediction floor to take roughly 2 months given
  monthly settlement cadence (~10 cities x 1 settlement/city/month), much
  slower than hourly's.

RESOLVED 2026-07-26 (St. Petersburg onboarding -- the 11th rain city; snow
  and hurricane remain the only fully open items in this entry): picked up
  as the "smallest/most contained" of 3 ready candidates surfaced at session
  start, after re-verifying live that the other two (SIGNAL GRADUATION part
  (c) -- no signal has cleared its sample floor yet, best still 6/20; snow/
  hurricane onboarding -- both still seasonally dormant, confirmed live via
  a fresh Kalshi API check) were genuinely not ready, per this project's own
  "don't build ahead of a real need" discipline.
  Re-verified live before writing code: KXRAINSTPM has 10 real open brackets
  (1-10in, closing 2026-08-01), settlement station confirmed via the
  market's own `rules_secondary` text as CLISPG/"Albert Whitted" (not
  assumed from the old backlog snapshot), lifetime volume ~14,880 (smaller
  than the other 10 but genuinely live, not a placeholder). KSPG coordinates
  (27.7651, -82.6269) confirmed via live web search against the airport's
  own published position.
  Research pass (Explore agent) found the "~8 registries" framing in this
  entry's old text was imprecise: only 4 of the 8 (CITY_COORDS,
  `_KXRAIN_MONTHLY_CITY`, `KNOWN_WEATHER_SERIES`, `metar.MARKET_STATION_MAP`)
  are actually reachable by `_analyze_monthly_rain_trade()` (the function
  that runs for rain tickers) -- `_STATION_BIAS_HIGH`/`_STATION_BIAS_LOW`,
  `_HISTORICAL_SIGMA`, and `climate_indices.py`'s AO/NAO/ENSO tables are all
  temperature-analysis-path-only and functionally inert for a rain-only
  city; `paper._CORRELATED_CITY_GROUPS` is reachable (rain tickers carry a
  real `target_date_str` since Step 2) but safe to leave unset, matching the
  existing Seattle-standalone precedent.
  One real design decision, resolved via `AskUserQuestion`:
  `city_registry_report()`'s `series_ticker` check hardcoded "at least one
  KXHIGH* ticker" -- would have permanently reported StPetersburg as missing
  regardless of how correctly KXRAINSTPM was wired, since it never checked
  rain tickers at all. User chose to generalize the check (any
  KNOWN_WEATHER_SERIES ticker, any prefix) over allowlisting the gap,
  verified safe against `settlement_monitor.py`'s own separate, stricter
  per-temperature-city assert (keyed off its own fixed 20-city short-code
  map, unaffected).
  Shipped: `CITY_COORDS`, `_KXRAIN_MONTHLY_CITY`, `KNOWN_WEATHER_SERIES`
  (moved off `KNOWN_UNTRACKED_RAIN_SERIES`), and `metar.MARKET_STATION_MAP`
  all gained a real `StPetersburg`/`KSPG` entry; `_STATION_BIAS_HIGH`/
  `_STATION_BIAS_LOW` got an explicit `0.0` placeholder (functionally inert,
  present only to satisfy `test_station_bias_fully_covered()`);
  `_HISTORICAL_SIGMA`/`climate_indices`/`_CORRELATED_CITY_GROUPS` left
  genuinely unset, each with a documented `_KNOWN_GAPS` entry in
  `tests/test_city_registry_manifest.py` (historical_sigma: dynamic
  climatology sigma covers it via CITY_COORDS anyway, matching the existing
  LasVegas/NewOrleans precedent; climate_indices: no temperature record to
  regress against; correlation_group: no correlation study done against
  Tampa Bay, standalone like Seattle rather than guessing a fold-in).
  Verified end-to-end against live data, not just unit tests: with a
  market's volume/open_interest patched up to clear the generic liquidity
  gate, a real `analyze_trade()` call against a real KXRAINSTPM-26JUL-10
  market produced a real result (`method="monthly_rain_bootstrap_tilted"`,
  `forecast_prob=0.107` vs `market_prob=0.145`) -- confirming the full
  ACIS-fetch + bootstrap + Seasonal-API-tilt chain works for this city, not
  just that city detection resolves. Every new registry entry was mutation-
  tested (temporarily removed, confirmed the corresponding test fails,
  restored).
  Opus review (single agent, scoped to this contained change) caught one
  CRITICAL bug this session's own scoped test run missed: `backtest.py` had
  a second copy of settlement_monitor.py's "exactly one KXHIGH* ticker per
  city" import-time assert, but keyed off iterating `CITY_COORDS` directly
  rather than its own fixed city set -- crashed `import backtest` the
  moment a rain-only city landed in CITY_COORDS (silent at bot startup
  since all importers are lazy, but broke the `backtest` CLI command, the
  live-trading-readiness check, and would have made the weekly walk-forward
  cron job fail every single run, freezing `PAPER_MIN_EDGE`'s highest-
  priority override at a stale value). Fixed by introducing
  `weather_markets.TEMPERATURE_MARKET_CITIES` (derived from
  KNOWN_WEATHER_SERIES, not hand-typed) as the correct set for this class of
  per-city temperature-ticker invariant, and repointing backtest.py's assert
  at it. Also caught one HIGH: an existing test
  (`test_phase2_batch_j.py::test_settlement_monitor_stations_match_metar_module`)
  asserted every `metar.MARKET_STATION_MAP` city is reachable through
  settlement_monitor's 20-city short-code map, which is now false by design
  for a rain-only city -- narrowed the test to only require this for
  `TEMPERATURE_MARKET_CITIES` members. Both findings are exactly this
  project's recurring "trace all call sites" failure mode: the initial
  verification pass ran the test suite for the two files actually touched,
  which was too narrow for a change mutating `CITY_COORDS`/
  `MARKET_STATION_MAP` -- two of the most widely-derived-from registries in
  the repo. A regression test
  (`test_temperature_market_cities_excludes_rain_only_cities`) now pins the
  CITY_COORDS/TEMPERATURE_MARKET_CITIES relationship and directly imports
  both `backtest` and `settlement_monitor` so this class of bug fails loudly
  in the manifest test file itself next time, not just incidentally via
  whichever test files happen to get run. Remaining review findings (stale
  "10"/"20"-city counts in several comments now off-by-one, a docstring that
  under-enumerated which ticker prefixes the generalized series_ticker check
  covers) all fixed; two were left as-is with reasoning (a historical
  "confirmed live this session" comment describing the original 2026-07-20/
  07-21 sessions, left untouched as accurate history rather than rewritten;
  a `_KNOWN_GAPS` wording nuance the reviewer itself called "moot in
  practice," left consistent with the existing LasVegas/NewOrleans phrasing).
  Full regression sweep (368+ tests across every touched file) passes
  except one confirmed pre-existing, unrelated, date-dependent failure
  (`TestAnalyzeMonthlyRainTradeEndToEnd::test_full_pipeline_produces_real_result`
  -- fails today because the model bootstraps only *remaining* days of the
  month and today's date leaves too few days for the test's fixture to
  clear its own assertion; reproduced identically on a clean stash of this
  session's diff, so not caused by this change); ruff/mypy clean.
  St. Petersburg is shadow-only like the other 10 rain cities (same
  `RAIN_TRADING_ENABLED` + 20-settled-prediction gate) -- not expected to
  affect live trading behavior until that gate clears.

RESOLVED 2026-07-26 (SNOW Step 1 -- discovery/schema/safety only, no
  probability model, mirrors rain's own original Step 1; hurricane split
  out to its own entry instead of getting the same treatment, see below):
  a backlog/memory review the same day picked up snow and hurricane
  together, then live-verified both far more thoroughly than this entry's
  own text (last updated 2026-07-20) before writing any code -- both
  original assumptions turned out wrong.
  Snow: of 33 real Kalshi series containing "SNOW", only `KXDENSNOWM`
  (Denver) has ever had a real market among this bot's 21 tracked cities (7
  markets, Dec 2025, now closed -- pure seasonality, re-check before next
  winter). Every other tracked city's snow series (NYC, Chicago, Boston,
  Houston, SF, Austin, Dallas, Philly, LA, DC, Seattle) is a registered-
  but-never-launched shell, 0 markets ever. One ticker, `KXMIASNOWM`, is a
  Kalshi registration error (series title reads "Chicago Snowfall Monthly"
  despite the MIA prefix, `frequency: "one_off"` unlike every real
  `"monthly"` ladder -- confirmed not a usable Miami product). Scope
  narrowed from an originally-assumed ~15-city build to Denver only,
  structured so adding a city later (if/when its series actually lists a
  market) is a one-line dict addition, not a redesign. Shipped:
  `_KXSNOW_MONTHLY_CITY = {"KXDENSNOWM": "Denver"}` (mirrors
  `_KXRAIN_MONTHLY_CITY`), wired into `_parse_city_from_ticker()`;
  `KNOWN_UNTRACKED_SNOW_SERIES` (32 entries, each commented with why --
  duplicate re-registrations, Christmas-window variants, untracked cities,
  the broken KXMIASNOWM registration); `check_series_drift()` extended to
  watch snow via substring match (`"SNOW" in ticker`, since unlike KXRAIN
  these tickers share no common prefix); a dedicated `snow_month_total`
  condition branch in `_parse_market_condition()` reading `floor_strike`/
  `strike_type` directly (checked before the existing generic
  SNOW_SERIES/is_snow_ticker branch, same misclassification trap rain's
  Step 2 already had to fix for itself); an unconditional `analyze_trade()`
  guard (`monthly_snow_not_yet_supported`, true Step 1 shape -- rain's
  current code is Step-2-shaped and no longer a direct copy source for
  this); unconditional blocks in `paper.check_position_limits()` (a call
  path reachable without `analyze_trade()` first) and `cmd_order` directly
  (added after opus review -- see the CORRECTION in the sibling
  HURRICANE MARKETS entry for why relying on `check_position_limits`
  alone isn't enough), and a documentation-only comment (not a runtime
  guard) in `order_executor.py`'s
  `_auto_place_trades()`, since re-checking rain's actual Step-1-era commit
  (`b2171ba`) found that function never needed a real code guard --
  `analyze_trade()`'s own guard already makes this loop unreachable for
  the ticker family, and a runtime check there would have been genuinely
  dead code; exclusions in `compute_market_implied_distributions()` and
  `consistency._group_markets()`, including the same mutation-style
  "exclusion holds even if a date were parseable" test rain added. 20 new
  tests (`tests/test_snow_markets.py`, one added after opus review --
  the original city-resolution test passed even with the new dict
  deleted, since the pre-existing generic "DEN" substring fallback
  coincidentally agrees; fixed with a mutation-style test pointing the
  dict at a fake city), full scoped regression sweep (504 tests total
  across this and the sibling hurricane change) passing, ruff/mypy/
  ruff-format clean.
  STEP 2 HANDOFF NOTE (opus review, not fixed this pass -- unreachable
  today since analyze_trade()'s guard means no prediction row can ever
  carry this condition type): `"snow_month_total"` is absent from
  `_CONDITION_CONFIDENCE` (weather_markets.py) and from the
  `condition_type NOT IN (...)` exclusion lists in `calibration.py`,
  `ml_bias.py` (3 sites), `tracker.py` (2 sites), and `main.py` -- the
  identical landmine `"precip_month_total"` was for rain before its own
  Step 2 had to wire it in everywhere. If snow ever gets a real
  probability model, audit every one of those sites the same way rain's
  Step 2 did, don't assume the new type is automatically covered.

RESOLVED 2026-07-30 (SNOW Step 2 -- the real monthly-accumulation
  probability model, own settlement, shadow-only rollout, mirroring Rain
  Step 2's shape exactly; hurricane's own model remains the only fully
  open item in this whole entry): re-verified every Step 1 claim live
  before writing code. Two findings were more consequential than the Step
  1 snapshot implied: Denver's only-ever snow market (Dec 2025, 7
  brackets) had ZERO trading volume/open-interest on every single bracket
  and never reached Kalshi's "finalized" settlement status -- not just
  seasonal dormancy, but a market that has literally never traded once, a
  materially harder starting point than rain had when its own Step 2
  shipped. Still zero open snow markets anywhere across all 33 real
  "SNOW" series as of ship time. Confirmed live that the finalized/
  expiration_value settlement mechanism does work on this platform (14
  real finalized Denver rain brackets), but it cannot be independently
  confirmed against a single real snow data point, since none exists.
  Three real design decisions surfaced via `AskUserQuestion` before
  writing code: (1) full build now vs. landmine-only-this-session --
  user chose full build, matching Rain Step 2's own precedent of shipping
  shadow-gated infra well ahead of settled data existing; (2) module
  architecture for acis_snow.py -- reuse acis_precip.py's bootstrap/tilt
  math via import (confirmed substance-agnostic: no precip-specific logic
  in `historical_remaining_and_full_month_sums`/`bootstrap_ci_month_total`/
  `apply_seasonal_tilt`) rather than duplicating it, while keeping the
  ACIS/Open-Meteo fetch layer in a separate module so a snow-specific bug
  can never touch rain's live shadow-trading path; (3) main.py's cmd_order
  guard shape -- keep the extra defense-in-depth refuse-outright check
  (added for snow in Step 1 after an opus review found relying on
  check_position_limits() alone fails open on an unhandled exception),
  now conditional on `_snow_gates_active()` instead of unconditional.
  Shipped: new `acis_snow.py` module (NOAA ACIS StnData `elem="snow"`
  month-to-date + ~30yr historical daily snowfall, handling the same "T"
  trace sentinel; Open-Meteo Seasonal `monthly=snowfall_mean` -- in
  CENTIMETERS, not millimeters like rain's `precipitation_mean`, confirmed
  live and validated at runtime against the API's own `monthly_units`
  field rather than assumed -- as an optional directional tilt, requiring
  a x10 cm-to-mm conversion at the call site since the reused
  `apply_seasonal_tilt()` expects mm) feeding a bootstrap resample of
  "remaining-days-of-month total" against the market's `floor_strike`
  threshold, wired into new `_analyze_monthly_snow_trade()`; the Step 1
  unconditional `monthly_snow_not_yet_supported` guard in `analyze_trade()`
  replaced with real close_time/days_out gating (`SNOW_MAX_DAYS_OUT`, its
  own env var rather than reusing `RAIN_MAX_DAYS_OUT`) and a
  `snow_month_total` dispatch, mirroring rain's `_is_monthly_rain`/
  `_is_monthly_snow` gate structure exactly; `tracker.audit_settlement()`
  new snow branch (checked before the generic city/date early-return, same
  reasoning as rain's); shadow-only rollout (`SNOW_TRADING_ENABLED` +
  `_snow_gates_active()`) mirroring `_rain_gates_active()`'s shape, but
  with a real fix opus review round 1 caught: `count_settled_snow_
  predictions()` counts DISTINCT (ticker-prefix, year, month) accrual
  events, not raw prediction rows -- Denver's 7-bracket ladder means a
  raw-row floor could have cleared the 20-sample threshold with as few as
  ~3 real months of data. Given the zero-live-market starting point,
  expect this floor to take years to clear, not rain's ~2-month estimate
  (`count_settled_rain_predictions()` deliberately left as row-counting
  and unchanged -- it's already live and accumulating real settled
  predictions today; changing its semantics now would shift an
  already-in-progress gate out from under it, a separate decision if ever
  revisited). Consensus-bonus caution followed exactly as it was for rain:
  ACIS-empirical and Open-Meteo-tilted are not independent, `consensus`
  hardcoded False. `_CONDITION_CONFIDENCE["snow_month_total"] = 0.65`
  (below rain's 0.70 -- zero real settled snow history exists anywhere to
  validate against, a stronger discount than rain's own judgment call).
  Deliberately did NOT port rain's later day-specific forecast-blend
  shadow signal (a separate backlog item shipped 2026-07-28, after rain's
  own Step 2 ship) -- out of scope for Step 2 parity, natural follow-up
  once real snow shadow data exists. All 7 exclusion-list landmine sites
  from the Step 1 handoff note above closed and mutation-tested:
  `_CONDITION_CONFIDENCE`, `calibration.py`, `ml_bias.py` (3 sites,
  including the "sameday" pool site opus review round 2 found had zero
  test coverage despite being fixed correctly), `tracker.py` (2 sites),
  `main.py`'s Platt-scaling query -- one opus-caught vacuous test
  (`calibration.py`'s own `calibrate_seasonal_weights` exclusion had NO
  dedicated test at all; the existing "Platt" test only exercised a
  different query) fixed by adding a real, mutation-confirmed test.
  `backfill_emos_data()`'s rain-only exclusion (a pre-existing gap found
  via adjacency, not part of the original 7-site list) extended to cover
  snow too, since KXDENSNOWM* rows have the identical settled_value-not-
  settled_temp_f shape that would otherwise re-fetch from Kalshi forever.
  Given the size, followed the full 16-step implementation workflow
  including two full sequential `Agent(opus, effort=high)` review rounds
  (round 1: three parallel reviewers scoped by subsystem -- model/gating,
  settlement/shadow-gate, exclusion-list audit; round 2: one reviewer
  verifying every round-1 fix plus its own fresh sweep), with every
  finding from both rounds addressed and personally mutation-tested
  (temporarily reverting each fix, confirming the relevant test fails,
  restoring the exact original bytes -- never via `git checkout`, to
  avoid disturbing other uncommitted work).
  Round 1 found one real HIGH-severity gap: the month-to-date ACIS fetch
  captured `n_missing` (count of "M"/missing sentinel days in the
  response) and silently discarded it -- a fetch that came back present
  but partially missing could understate the accrued total with zero
  guard, for both rain (already live) and snow. Fixed in both
  `_analyze_monthly_rain_trade()` and `_analyze_monthly_snow_trade()`.
  Round 2 caught that round 1's own fix used the WRONG statistic: a
  fractional missing-day threshold (20%, borrowed from the historical
  path's `max_missing_frac`, where one bad year's error is diluted across
  30 analog years) does not transfer to a month-to-date value that gets
  added 1:1 into every single bootstrap sample with no dilution at all.
  Reproduced live against real cached Denver history: the entire month's
  snow was concentrated in 2 of 31 days (6.5% missing -- comfortably
  under a 20% threshold), which is the exact scenario the guard was
  written for and would NOT have caught. Fixed by switching to
  zero-tolerance (`_n_missing > 0`) in all four sites (rain + snow,
  mid-month + after-month-end branches) -- the fetch is cheap and re-runs
  every scan cycle, so failing closed costs nothing but a skipped cycle.
  Round 2 also caught: an empty ACIS response (`HTTP 200` with `data: []`,
  confirmed live for an unresolvable station id) was silently reported as
  `n_missing=0` by both `fetch_month_to_date_actual`/`_snow` (bypassing
  the new guard entirely) and separately poisoned `fetch_historical_daily`/
  `_snow`'s 30-day disk cache with an empty result instead of falling back
  to a stale cache -- both fixed in both rain's and snow's fetch modules.
  Round 2 also found `_quick_paper_buy()` and `cmd_paper()` (two manual
  order-placement paths in main.py) had NO hurricane/snow/rain guard at
  all, unlike `cmd_order()` -- and `_quick_paper_buy()` specifically can
  place a REAL LIVE maker order, with its own `check_position_limits()`
  call deliberately fail-open on exception (pre-existing, unrelated
  behavior). Fixed by adding the same guards to both functions -- and,
  since round 2 correctly pointed out the fail-open reasoning applies with
  equal or greater force to rain (whose shadow gate is live and
  accumulating today, unlike hurricane/snow), extended to rain too rather
  than leaving that asymmetry undefended. Rain's own equivalent seasonal-
  unit assumption (Open-Meteo's `precipitation_mean` in mm) got the same
  runtime validation snow's cm claim did, for consistency and because it's
  the live path. Every fix above has a real, mutation-tested regression
  test; full scoped sweep (1000+ tests across test_snow_markets.py,
  test_rain_markets.py, test_acis_precip.py, test_calibration.py,
  test_ml_bias.py, test_tracker.py, test_shadow_predictions.py,
  test_signal_quality.py, test_hurricane_gating.py, test_trading_gates.py)
  passes; ruff/ruff-format/mypy clean.
  `SNOW_TRADING_ENABLED` stays unset until real shadow data accumulates --
  given zero live snow markets exist anywhere today and Denver's ladder is
  the only city that has EVER listed one, expect the 20-distinct-event
  floor to take years, not months, to clear.
```

### 5. Pre-existing backlog item (`backlog.txt:7915`)

```
[OPEN 2026-08-06 -- new, split out of the entry above per its own "not part
  of this pass" framing]
  RAIN ARBITRAGE-CHECK SHADOW SIGNAL HAS NO GRADUATION DECISION YET
Priority: Low -- shadow-only, doesn't block or corrupt anything live; just
  means real rain arbitrage (if it exists) never gets auto-corrected.

Problem:
  The entry above shipped rain arbitrage DETECTION (grouping + monotonicity
  check + logging), but every rain-sourced Violation is permanently
  is_shadow=True with no mechanism to ever flip that -- unlike this
  project's other shadow-then-graduate signals (SIGNAL_REGISTRY's sample-
  floor + correlation-check pattern), there is no sample floor, no
  correlation check, and no standing report command tracking how often real
  rain arbitrage actually appears or what it would have been worth.

What it would look like:
  Either wire rain arb violations into the existing SIGNAL_REGISTRY
  graduation-report pattern (a count of shadow violations observed, maybe a
  simple "what would have been captured" retrospective once enough have
  accumulated), or -- since this is a deterministic monotonicity check, not
  a probabilistic forecast signal -- a simpler manual review path (an
  operator periodically runs `py main.py consistency` and eyeballs the
  shadow rows the Type column now marks) followed by a one-line code change
  flipping is_shadow's default once satisfied. The right shape is itself an
  open question -- SIGNAL_REGISTRY's sample-floor/correlation machinery was
  built for probabilistic signals with a settlement outcome to correlate
  against; a monotonicity violation doesn't have an obvious equivalent
  (there's no "was this violation right or wrong" outcome the way a
  temperature forecast has one), so this may need its own simpler mechanism
  rather than reusing that pattern wholesale.

Why not now:
  Deliberately scoped out of the detection-only pass above (AskUserQuestion
  decision) -- shipping detection and observing real shadow output for a
  while is a prerequisite for designing a sensible graduation mechanism, not
  something to guess at upfront.

When to revisit:
  Whenever rain's shadow arb output has accumulated enough real observations
  (via `py main.py consistency`'s Type column, or a future dedicated report)
  to judge whether real violations occur often enough / at enough edge to be
  worth auto-correcting -- not gated on a specific count, purely an
  operator judgment call once real data exists.
```

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

This batch is documentation/test/low-risk-code only. If every item you actually touch turns out to be a small, mechanically-verifiable diff with no live-order/live-money/safety-gate surface and no multi-file span, steps 11-12 may collapse to the LOW tier (a single self-review pass + one Agent check instead of a dedicated opus effort:high spawn). Re-assess per item -- don't downgrade the whole batch by default if one item in it turns out bigger than expected.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
