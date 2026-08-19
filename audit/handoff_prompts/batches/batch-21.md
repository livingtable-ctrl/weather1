# Batch 21: Calibration go-live decisions

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch groups 2 **pre-existing** backlog item(s) (not from the 2026-08-18 audit) sharing **ml_bias.py, tracker.py, main.py**. Each item's full existing entry is reproduced verbatim below from `backlog.txt` -- these already have their own Problem/Priority write-ups from earlier sessions; read them in full rather than treating the excerpt here as complete.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. Pre-existing backlog item (`backlog.txt:2720`)

**Staleness note (added during this session's batching pass, 2026-08-18):** this entry's own header already says the data floor cleared 2026-08-16 -- do NOT treat this as 'still waiting on data' the way the entry's original 40-row bar reads. **User-directed update (2026-08-18, this session):** the user raised the real bar for considering EMOS go-live to **~80 settled trades** in the ens_var-populated training set, not the original 40 -- their own risk-tolerance call, not re-derived from any precedent in this file. Re-verify the current settled count against that 80 figure yourself before treating this as ready; do not silently fall back to the stale 40 either from the original entry or as a lower substitute.

```
[PARTIALLY RESOLVED 2026-08-16 -- confirmation gate built and the data floor
  has cleared; actual go-live is still a deliberate follow-up decision, not
  done as part of this change -- see Resolution below.]
  EMOS CALIBRATION STAYS DISABLED UNTIL THE ens_var-POPULATED TRAINING SET CLEARS 40 ROWS
Priority: Medium -- directly explains a real, already-observed Brier
  degradation (two consecutive weeks over the P10.3 alert threshold,
  0.2329 and 0.2804, found 2026-07-31), but no code is broken and no
  action is needed beyond waiting and re-checking.

UPDATE 2026-08-18 (user's explicit call, raised during the max-depth audit's
  backlog-triage session -- their own risk-tolerance decision, not
  re-derived from anything in this entry): the real go-live bar for EMOS is
  ~80 settled trades in the ens_var-populated training set, not the 40
  originally cited above. The 40-row floor clearing 2026-08-16 does NOT by
  itself mean this is ready -- re-check the current settled count against
  80, not 40, before treating this as a live go/no-go decision.

Problem:
  EMOS (ml_bias.py's fit_emos/emos_exceedance_prob/emos_interval_prob) was
  deployed 2026-06-27 (`ae1d5ba`) as the intended replacement for
  temperature-scaling calibration on multi-day (`above`/`below`/`global`)
  predictions, and that same commit reset temperature_scale.json's T to
  1.0 (identity/no-op, see ml_bias.py:485) across the board as a "handoff"
  to EMOS. EMOS itself was caught and deliberately reverted the same
  session (data/emos_params.json.premature_do_not_use_20260704) because
  `py main.py emos-train` flips a live probability method the instant
  data/emos_params.json exists, with no separate confirmation step -- a
  process/safety concern, not a fit-quality judgment (re-verified
  2026-07-31 after initially guessing "deemed unfit" without checking; the
  actual recorded reason is the missing confirmation gate). With EMOS
  never actually live and T-scaling parked at the 1.0 no-op, multi-day
  predictions ran with ZERO calibration correction of any kind for the
  full ~33 days until temperature_scale.json was finally retrained
  2026-07-30 (delayed that long because the F3 auto-calibration sentinel
  was undercounting settlements due to the condition_type-contamination
  bug fixed the same day, `ee7288b`). get_brier_over_time() shows the
  damage precisely: W24=0.1997, W25=0.1937 (pre-gap) -> W26=0.2678,
  W27=0.2687, W29=0.2329, W30=0.2804 (inside the gap; W30's predictions
  all predate the 07-30 retrain).

  Separately, re-verified whether EMOS itself is ready to activate now
  that the process-gate concern could be addressed with a real
  confirmation step: count_emos_ready_predictions() = 103 (ens_mean +
  settled_temp_f), well past the 40-row reminder gate in cron.py -- but
  only rows placed since Jun 21 2026 (forward-fill) carry a real ens_var;
  backfilled Previous-Runs-API rows don't. get_emos_training_data()'s own
  population (days_out IS NULL OR >=1, matching EMOS's actual multi-day
  scope) currently has only 31 rows with real ens_var populated -- short
  of the 40-row floor cron.py's own comment cites (Gneiting 2005: 10
  forecast cases per parameter x 4 EMOS parameters a/b/c/d). Confirmed the
  forward-fill pipeline itself is healthy (every recent method='ensemble'
  multi-day/same-day prediction has ens_var populated correctly -- this is
  a volume gap, not a broken pipeline). Recent accrual rate: ~5-8
  ens_var-populated multi-day rows/week (W24-W29), so ~40 should clear in
  roughly 2 more weeks at the current pace.

What it would look like:
  Once count_emos_ready_predictions()-equivalent-for-ens_var-only clears
  40 (no dedicated live counter exists for this exact subset today --
  `get_emos_training_data()` returns the rows, count with
  `sum(1 for r in rows if r["ens_var"] is not None)`), deliberately run
  `py main.py emos-train` as an explicit, separate decision (not a side
  effect of anything else), and reset temperature_scale.json's affected
  keys at the same time per the original 2026-06-27 revert note's own
  caveat ("needs a coupled temperature_scale.json reset when it does").
  Verify the resulting calibration curve (`py main.py validate`) actually
  improves on the current T-scaling-only baseline before trusting it live
  -- EMOS replacing a currently-working T-scaling fit is a real regression
  risk if the EMOS fit turns out worse, not just a formality.

Why not now:
  User decision 2026-07-31: explicitly wait for more ens_var-populated
  settled data (31/40) rather than activate on today's thinner sample.
  T-scaling is live and freshly retrained (2026-07-30) in the meantime, so
  multi-day predictions are not running uncalibrated right now -- this is
  a "wait for a better version," not "the current gap is unaddressed."

When to revisit:
  Check the ens_var-populated multi-day row count (see query above) in
  ~2 weeks (~mid-August 2026); activate deliberately once it clears 40,
  following the "what it would look like" steps above.

Resolution (2026-08-16):
  The ens_var-populated count cleared 40 as predicted (48 rows as of this
  session, up from 31 on 2026-07-31 -- matches the cited ~5-8/week accrual
  rate). Added a dedicated live counter for it,
  tracker.count_emos_variance_ready_predictions(), since none existed
  before (cron.py's own EMOS-ready banner was using
  count_emos_ready_predictions() -- ens_mean-only, no ens_var filter --
  which clears 40 earlier than the real variance-fit population does
  whenever backfilled Previous-Runs-API rows, which never carry ens_var,
  make up part of the total; fixed the banner to use the stricter count and
  stopped it suggesting `backfill-emos` at that stage, since backfill rows
  can't move this count).

  Built the actual confirmation gate the "process/safety concern" above was
  about: `py main.py emos-train` is now a dry run by default -- it fits and
  prints a/b/c/d but does NOT write emos_params.json (the file whose mere
  existence is the only switch weather_markets.py checks). A new
  `--activate` flag is required to go live, and even with the flag it still
  prompts a typed 'yes' confirmation (mirrors the accuracy-override CLI
  pattern in main.py's cmd_admin) before writing anything. Confirmed
  activation also resets T_above/T_below/T_global to 1.0 in
  temperature_scale.json in the same step (ml_bias.reset_temperature_scale_
  for_emos()) -- the coupled reset this entry's own "what it would look
  like" section called for, now atomic with activation instead of a
  separate manual step nobody remembered to do last time. Added
  `emos-status` (shows whether EMOS is live and its fitted values) and
  `emos-deactivate` (reverts to the ensemble/climatology blend + T-scaling,
  also confirm-gated) for symmetry with accuracy-override/-clear/-status --
  deactivation previously meant manually deleting a file with no tooling.

  Deliberately did NOT run `emos-train --activate` as part of this session
  -- this entry's own "What it would look like" text requires verifying the
  resulting calibration curve (`py main.py validate`) beats the current
  T-scaling baseline before trusting EMOS live, which is a separate,
  substantive decision the confirmation gate exists to make possible, not
  something to shortcut through while building the gate itself.

  Independent opus review (effort=high) of the first-pass gate found 5
  HIGH + 9 MEDIUM + 11 LOW -- every finding was in the coupled T-scaling
  half or the revert path, not the confirm-prompt mechanism itself, which
  it confirmed was solid. All addressed, none deferred:

  HIGH -- (1) the T=1.0 reset didn't persist: cron.py's own weekly
  train_all_temperature_scaling() retrain would silently refit and
  overwrite it within ~7 days while EMOS stayed live, recreating exactly
  the double-calibration the reset exists to prevent -- fixed by gating
  that function on `EMOS_PARAMS_PATH.exists()`, skipping global/above/
  below/between whenever EMOS is active. (2) emos-deactivate cleared the
  in-process EMOS cache only in the CLI process that ran it, so a
  concurrently-running `loop`/`watch` process kept using cached EMOS
  params indefinitely -- the emergency revert didn't revert. (3) the
  matching problem on activation's T-scaling half (a running loop's
  temperature-scale cache stayed stale after a separate process reset it).
  Both (2)/(3) fixed by making _load_emos_params()/_load_temperature_scale()
  check the file's mtime on every call (cheap stat, reload only on real
  change) instead of caching permanently after first load. (4) 'between' IS
  an EMOS-covered condition type (weather_markets.py calls
  emos_interval_prob for it) but the reset's docstring and key-list both
  claimed otherwise and left it untouched -- the strongest T in the file
  (~6.8, "between markets have a much larger calibration gap") was landing
  on top of EMOS's own fit undetected. Fixed: 'between' now resets
  alongside global/above/below. (5) deactivation didn't restore T -- it
  stayed at the 1.0 placeholder for up to a week (weekly, not daily as the
  original text claimed) AND permanently disabled the
  _T_ABOVE_PRIOR/_T_BELOW_PRIOR fallback (which only fires when a key is
  fully ABSENT, never once a placeholder key exists), reproducing this
  entry's own documented zero-calibration incident as deactivate's *normal*
  outcome. Fixed: reset_temperature_scale_for_emos() now snapshots the
  pre-reset values to temperature_scale_pre_emos.json, and deactivate_emos()
  restores them immediately (not waiting for the next retrain) via a new
  restore_temperature_scale_from_emos_snapshot().

  MEDIUM -- the two-file activation write (emos_params.json then
  temperature_scale.json) had no rollback: a failure between them left EMOS
  live with stale T -- wrapped in try/except with an explicit rollback via
  deactivate_emos() and a clear FAILED/Rollback-complete message.
  --activate had no data-quality floor of its own (only cron.py's banner
  suggested 40 rows, enforcing nothing) -- added a hard refusal below 40
  ens_var rows, with a --force override (mirrors backfill-emos's existing
  flag) and n/n_var now restated in the confirm prompt itself. A corrupt
  emos_params.json was unrecoverable via any CLI command (status/deactivate
  both silently reported "not active") -- get_emos_status() now returns a
  distinct corrupt:true, and both commands offer to remove it.
  cron.py's banner regression: the ens_var-strictness fix (see above)
  accidentally also stopped suggesting `backfill-emos` once ens_mean alone
  cleared 40, even though backfill-emos legitimately still helps the a/b
  fit below that -- restored as its own 4th branch. emos-status/
  emos-deactivate were gated behind full Kalshi credential validation even
  though neither touches the API -- the emergency revert must not be
  blockable by an unrelated broken API key, so both now bypass validate_env()
  the same way `calibrate` already does (emos-train left as-is: a rarer,
  more deliberate action). Neither activate nor deactivate checked for a
  cron cycle in flight -- added a cron._is_cron_running() guard to both (one
  scan could otherwise price some markets pre-switch, some post-switch).
  Added reset_for_emos/reset_at provenance fields so a pinned 1.0 isn't
  mistaken for a real fit on inspection. web_app.py's /api/emos-status
  duplicated get_emos_status() with a stale "Run: py main.py emos-train"
  message (no longer true post-dry-run-by-default) -- corrected. First-ever
  activation's exact fitted params were unrecoverable after a deactivate
  (atomic_write_json_with_history only snapshots on overwrite, nothing to
  overwrite on a first write) -- deactivate_emos() now archives to
  data/.history/ via a raw text copy before unlinking, working even on a
  corrupt file.

  LOW -- fixed the old-format T-scale migration's key name (n_samples, not
  n -- matches train_all_temperature_scaling's own migration), a docstring
  typo (ml_bias._cmd_emos_train -> main._cmd_emos_train, it's in main.py),
  and "daily calibration" -> "weekly" in both the deactivate message and
  code comments (this entry's own earlier resolution text repeated the same
  daily/weekly error, also fixed). Added tests for the previously-uncovered
  old-format migration branch and cron.py's banner 4-way branch logic.

  40 new/updated tests total across tests/test_ml_bias.py's TestEmos +
  TestTrainAllTemperatureScalingSkipLogging classes and
  tests/test_main_cron_smoke.py's TestEmosActivationGate/
  TestEmosStatusAndDeactivate classes (84 collected in the scoped suite, up
  from 63 pre-review). Mutation-tested via the Edit tool (not string-replace
  scripts) on every HIGH/MEDIUM fix's own test: the retrain skip-guard, the
  between-key inclusion, the deactivate-restores-T behavior, the >=40
  variance-floor refusal, the cron-lock guard (both activate and deactivate
  call sites), and the activation rollback -- each confirmed to actually
  fail when its fix was reverted, not just pass by construction. 84 pass in
  the scoped suite; a wider sweep (test_cron_integration.py +
  test_tracker.py + test_p9_p10.py) surfaced one unrelated pre-existing
  failure (log_prediction's known UTC-vs-local days_out bug, already
  tracked separately) -- confirmed identical on unmodified master via git
  stash, not a regression from this change. Ruff + mypy clean on all
  changed files (main.py, ml_bias.py, tracker.py, cron.py, web_app.py,
  paths.py).
```

### 2. Pre-existing backlog item (`backlog.txt:10000`)

**Staleness note (added during this session's batching pass, 2026-08-18):** this entry's own text is dated 2026-07-16 and says zero settled trades have a non-NULL `run_trend_delta`. Independently re-queried the real production DB this session: **22 rows** now qualify (`predictions JOIN outcomes WHERE run_trend_delta IS NOT NULL AND settled_temp_f IS NOT NULL`) -- already stale in the other direction from the entry's own zero. **User-directed update (2026-08-18, this session):** the user set the real bar for this specific signal at **~60 rows** (higher than the entry's own cited 20-50 precedent range), their own call, not re-derived from anything in this file. Re-run the exact query above yourself (the count will have moved again) and compare against 60, not the entry's original 20/50 figures; the entry's own accuracy-check requirement (step 2 in the reproduced text below) still needs to be run regardless of sample count.

```
[PARTIALLY RESOLVED 2026-07-16] FORECAST RUN-TO-RUN TREND SIGNAL
Priority: was Medium (new alpha source, mostly existing plumbing) -- now Low
  until the enablement trigger below fires; this is a data-collection phase,
  not an active development item.

UPDATE 2026-08-18 (re-verified live during the max-depth audit's backlog-
  triage session, plus the user's own explicit call): this entry's sample-
  floor count is stale -- re-queried the real production DB and found 22
  rows now have a non-NULL run_trend_delta + settled_temp_f (up from 0 on
  2026-07-16), via the exact query this entry's own ENABLEMENT TRIGGER
  section specifies below. The user's real bar for THIS signal specifically
  is ~60 rows (higher than the 20-50 precedent range this entry originally
  cited from other signals) -- their own risk-tolerance call, not re-derived
  from this file. Re-run the query yourself before treating this as ready;
  the entry's own accuracy-check requirement (step 2 below) still needs to
  run regardless of sample count, and 22 does not yet clear 60 either way.

PARTIALLY RESOLVED 2026-07-16: the LOGGING half is shipped; the BLEND half
  (directional lean and/or sigma-widening) is deliberately not built yet --
  scoped via AskUserQuestion before coding (data-source symmetry, series
  length, blend usage) and the user chose log-only for this pass, matching
  every other new-signal entry in this file's own precedent (candlestick
  capture, trade-flow signal, this entry's own original wording).
  Live-verified against the real Previous Runs API (2026-07-16) before
  writing code: a future target_date returns real non-null data when queried
  with forecast_days instead of past_days (the pre-existing
  _fetch_previous_run_daily, built only for backfilling PAST dates, returns
  None for a future one); the existing lead clamp of 1-7 is correct (lead=8
  confirmed all-null live); Open-Meteo accepts multiple previous_dayN
  hourly variables in one request, so a 4-point lookback costs the same 3
  HTTP calls (one per model) as a 2-point one would -- this is why 4 points
  were shipped instead of 2, at no extra API cost, so jumpiness (needed for
  the sigma-widening half, when it's built) doesn't require a second schema
  migration later.
  Shipped: tracker.get_forecast_run_trend(city, target_date, days_out, var) --
  weights the same 3 models as backfill_emos_data's EMOS ens_mean
  (_PREVIOUS_RUN_MODEL_MAP, via _model_weights) across leads N..N+3 (clamped
  to 1-7), so every point in the series uses identical apples-to-apples
  methodology, not a mismatch between a live ensemble mean and a single
  deterministic control run. Returns {"points": [...], "delta": ...,
  "jumpy": ...} or None (days_out<1 -- same-day markets use the METAR
  pipeline instead; unknown city; fewer than 2 usable leads). Cached
  (ForecastCache, 4h TTL, 30min TTL on a negative/failed result so a
  transient API hiccup doesn't blank the signal out for a full 4h) keyed on
  (city, target_date, days_out, var) -- var included because a HIGH and LOW
  market on the same city/date need independently cached series. Wired into
  tracker.log_prediction() as a new run_trend param (3 new columns:
  run_trend_points JSON, run_trend_delta/run_trend_jumpy scalars, schema
  v39->v42). 18 new tests (tests/test_tracker.py) -- fetch parsing/omission/
  failure modes, weighted-delta/jumpy computed from known per-model values
  with intentionally UNEQUAL weights (proves real weighting, not an average
  disguised as one), cache-hit-avoids-second-network-call, log_prediction
  round-trip, and the extraction-helper's field-mapping/malformed-input
  cases (see below). Mutation-tested the weighted-mean line (swapped to a
  plain average on a scratch edit, confirmed the delta/jumpy test fails with
  the exact expected wrong numbers, reverted) -- confirmed the test genuinely
  checks weighting rather than passing spuriously.

  Independently reviewed (Agent, opus) -- found the log-only guarantee held
  and the schema migration was safe, but ONE real MEDIUM issue: the initial
  design called get_forecast_run_trend() directly inside
  weather_markets.analyze_trade(), which put up to 3 sequential HTTP calls
  (up to ~60s worst case on a cache miss) on the live order-placement
  critical path -- analyze_trade's caller only places the order after it
  returns, so a slow fetch would delay an already-fully-decided trade's
  submission even though the fetch itself never touched blended_prob/kelly/
  edge. Fixed by moving the call entirely out of analyze_trade: new
  tracker.get_forecast_run_trend_from_analysis(analysis) extracts city/
  target_date/days_out/var from an analyze_trade()-shaped dict and is now
  the ONLY caller of get_forecast_run_trend, invoked from
  order_executor._prediction_kwargs_from_analysis and main.py's two direct
  log_prediction call sites (cmd_market, cmd_order) -- all of which run at
  LOG time, which for real trades already happens AFTER order placement
  (order_executor._auto_place_trades' own docstring), fully decoupling the
  fetch from fill timing. Side benefit: markets that get analyzed but never
  traded or shadow-logged now skip the fetch entirely, where the original
  design would have fetched for every scanned market regardless of outcome.
  Also fixed 2 LOW robustness gaps the same review surfaced:
  _fetch_previous_run_leads now checks the `hourly` field is actually a
  dict before indexing into it (a malformed API response could otherwise
  raise AttributeError outside the function's own try/except), and
  get_forecast_run_trend's model-weighting/statistics section is now
  wrapped in its own try/except so the function's "never raises" docstring
  claim is actually enforced by the function itself, not just inherited
  from whatever happened to call it. A second finding -- the real
  data/predictions.db had drifted to PRAGMA user_version=40 while already
  having all 3 new columns (caused by this session's own now-fixed
  _SCHEMA_VERSION=40 typo briefly existing while all 3 migration entries
  were already in _MIGRATIONS, and something triggering init_db() against
  the real DB during that window) -- confirmed harmless and self-healing
  (duplicate-column guard), but corrected immediately anyway by calling
  tracker._run_migrations() once by hand rather than leaving it for the
  bot's next natural run.

ENABLEMENT TRIGGER (the actual ask: when to turn this from log-only into a
  real blend input) -- do NOT wire it into blended_prob/sigma/kelly until:
  1. A meaningful number of settled trades have a non-NULL run_trend_delta/
     run_trend_jumpy (check: predictions JOIN outcomes WHERE
     run_trend_delta IS NOT NULL AND settled_temp_f IS NOT NULL). Apply the
     same sample-floor precedent already used elsewhere in this file before
     trusting a per-signal statistic (ACCURACY_MIN_SAMPLE=20,
     SPRT_MIN_TRADES=20, MIN_BIAS_CORRECTION_TRADES=50) -- don't invent a
     new, lower bar just because this signal is new.
  2. A real accuracy check has been run against that data: does a positive
     run_trend_delta (forecast trending warmer) actually correlate with the
     forecast being LOW (i.e. the true value came in even higher), the
     directional-persistence hypothesis this entry is built on? Does high
     run_trend_jumpy actually correlate with larger forecast error (the
     sigma-widening hypothesis)? Both are testable directly against
     settled_temp_f once #1 is satisfied -- don't wire in blend/sigma
     changes on the strength of the mechanism sounding plausible alone.
  3. Only then: revisit the original "What the fix looks like" below for
     the actual blend/sigma wiring, gated behind tracked accuracy like every
     other signal source in this file (see the ENSEMBLE spread bias, NWS
     weight decay, and dynamic bias-correction gates already live in
     weather_markets.py for the established pattern to match).
  This same trigger shape (accumulate -> check correlation against real
  settlement data -> only then wire into the blend) applies to every other
  log-only-shipped signal in this file -- see RICHER ML CALIBRATION
  FEATURES and GENERALIZED PER-MODEL ACCURACY TRACKING below, and the
  candlestick capture / public trade-flow signal entries, all of which have
  the same "ship the logging, evaluate later" shape and the same risk of
  being logged forever and never actually revisited without an explicit
  check-back condition like this one.

Problem (original framing, still accurate for the blend/sigma half):
  The Open-Meteo Previous Runs API is already integrated — but only in
  tracker.py (~2231) / backtest.py for EMOS backfill. The live path never
  compares the current model run against the previous run. Run-to-run
  revision carries signal: a forecast trending warmer across consecutive
  runs tends to keep trending while markets anchor to the older number, and
  high run-to-run jumpiness is a principled reason to widen sigma.

What the fix looks like (still open -- logging half only is done above):
  Feed the now-logged delta/jumpy series as (a) a small directional lean in
  the blend and/or (b) a sigma-widening term when jumpiness is high, once
  the ENABLEMENT TRIGGER above is satisfied.

Why not now:
  - The enablement trigger above hasn't fired yet -- zero settled trades
    have a run_trend_delta value as of 2026-07-16 (the column didn't exist
    until today). Needs real elapsed time + trading activity, not more
    engineering effort.

When to revisit:
  - Check the ENABLEMENT TRIGGER's sample-floor query periodically (e.g.
    whenever this file is next open for other reasons, or paired with the
    DATA-DRIVEN SIGMA FROM SETTLED HISTORY entry's own settled-count check
    below, since both are gated on the same kind of settled-trade volume
    growing over time).
```

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

At least one item in this batch touches a live-order/live-money/safety-gate path (or is adjacent enough to warrant it) -- this batch does **not** qualify for the steps 11-12 LOW-tier downgrade. Apply the full ceremony as written, all 29 steps, for the batch as a whole.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
