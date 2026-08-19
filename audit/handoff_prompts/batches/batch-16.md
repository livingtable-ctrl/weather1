# Batch 16: Forecast/ML alpha signal development

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch groups 6 **pre-existing** backlog item(s) (not from the 2026-08-18 audit) sharing **weather_markets.py, tracker.py, ml_bias.py**. Each item's full existing entry is reproduced verbatim below from `backlog.txt` -- these already have their own Problem/Priority write-ups from earlier sessions; read them in full rather than treating the excerpt here as complete.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. Pre-existing backlog item (`backlog.txt:8326`)

```
[PARTIALLY RESOLVED 2026-07-24 -- track-only plumbing shipped; the actual
  3-way gating decision (item 2 below) still gated on real data, unchanged]
  3-WAY MODEL_CONSENSUS CHECK -- ECMWF_AIFS025_ENSEMBLE'S PROBABILITY ISN'T WIRED IN YET
Priority: Low (the underlying weight-learning field is done; this is a
  trade-quality-gate refinement, not a correctness bug)

Problem:
  analyze_trade()'s model_consensus check (weather_markets.py, the
  "Model consensus check" block) is still the original binary
  abs(icon_p - gfs_p) > 0.12 comparison -- it does not consider
  ecmwf_aifs025_ensemble at all, even though _get_consensus_probs() now
  fetches that model's mean via the same _model_prob_and_mean() helper used
  for icon/gfs (2026-07-23, see the resolved TRACK ECMWF FORECAST ACCURACY
  entry above). _model_prob_and_mean() computes a real member-vote-fraction
  probability for ecmwf_aifs025_ensemble as a side effect of computing its
  mean -- _get_consensus_probs() just doesn't return it yet (deliberately
  scoped out of the 2026-07-23 session, at the user's explicit choice, to
  keep that session to "ship the weight-learning field only").

What the fix looks like:
  1. Extend _get_consensus_probs()'s return tuple with ecmwf_prob (cheap --
     _model_prob_and_mean("ecmwf_aifs025_ensemble") already computes it,
     currently discarded via `_, ecmwf_mean = ...`).
  2. Decide how to fold a 3rd probability into model_consensus. Note this is
     NOT purely mechanical: icon_p/gfs_p are real member-vote-fraction
     probabilities from live multi-member ensembles (same methodology,
     directly comparable). ecmwf_aifs025_ensemble's probability, once wired
     in, WOULD also be a genuine member-vote-fraction probability from the
     same ENSEMBLE_BASE infrastructure -- so unlike the ecmwf_ifs025
     alternative (which has no members at all, only a single deterministic
     point value), a 3-way check here IS apples-to-apples methodologically.
     Still a real design decision: all-pairwise-agreement (max spread across
     all 3 pairs) vs. a simpler max-min-spread check across all 3 probs.

Why not now:
  - Deliberately deferred by explicit user decision on 2026-07-23 to keep
    that session scoped to the weight-learning field alone.
  - Changes live trade-gating behavior (model_consensus feeds
    "near_threshold"/downstream Kelly-adjacent signals) -- deserves its own
    scoping pass, not a rider on an unrelated instrumentation change.

When to revisit:
  - Whenever model_consensus's trade-quality signal is next being tuned, or
    once enough settled ecmwf_aifs025_ensemble observations exist to know
    whether its member-vote probability actually disagrees with icon/gfs in
    a way worth gating on (rather than guessing at the 3-way threshold blind).

RESOLVED 2026-07-24 (item 1 only -- the plumbing; item 2, the actual 3-way
  gating decision, is still open and deliberately unstarted, see below):
  before picking this up, re-verified live that ensemble_member_scores
  (tracker.db) had zero settled ecmwf_aifs025_ensemble rows (vs 67 each for
  icon_seamless/gfs_seamless) -- the tracking only started the day before
  (2026-07-23), so any 3-way threshold chosen today would be exactly the
  "guessing blind" scenario this entry's own "when to revisit" warns
  against. Surfaced this to the user via AskUserQuestion before implementing
  anything; user chose track-only scope explicitly.
  Shipped: a new weather_markets._get_ecmwf_aifs_prob(city, target_date,
  condition, hour, var) helper (kept separate from _get_consensus_probs's
  5-tuple, same reasoning as _get_gem_ukmo_means's docstring -- ~20 existing
  call sites mock/unpack that tuple positionally) that reuses
  _model_prob_and_mean("ecmwf_aifs025_ensemble", ...) -- same cache key as
  _get_consensus_probs's own ecmwf fetch, so it's a cache hit, not a second
  network call, whenever both run in the same analyze_trade pass. analyze_trade
  now calls it under the same ens_prob/temps gate as _get_gem_ukmo_means, and
  computes ecmwf_consensus_gap_prob = max(|icon_p - ecmwf_p|, |gfs_p - ecmwf_p|)
  (None unless all three are non-None) -- log-only, threaded through
  tracker.log_prediction (new nullable column, schema v57->v58) via
  order_executor._prediction_kwargs_from_analysis, mirroring the exact
  established pattern for nbm_quantile_prob/gem_forecast_mean/ukmo_forecast_mean.
  model_consensus itself is UNCHANGED -- still exactly
  abs(icon_p - gfs_p) > 0.12, icon-vs-gfs only; ecmwf_aifs_prob never feeds it,
  directly or indirectly.
  New tests: weather_markets fetch-level (TestGetEcmwfAifsProb, mirrors
  TestGetGemUkmoMeans), analyze_trade-level (gap computed correctly, None when
  ecmwf_prob missing, survives a fetch exception, model_consensus provably
  unaffected -- the gap in the passing test (0.15) exceeds the 0.12 threshold
  on purpose, so a regression that folded it into the gate would flip
  model_consensus and fail the test), order_executor kwargs-passthrough
  (mirrors nbm_quantile_prob's tests), tracker round-trip/null/reupsert
  (mirrors nbm_quantile_prob's tests). New conftest.py autouse fixture
  (default_ecmwf_aifs_prob_none) stubs the new helper to None for every
  other test, same pattern as default_gem_ukmo_means_none, to avoid real
  network calls leaking into unrelated tests.
  Mutation-tested twice: (1) reverted the whole weather_markets.py diff via
  git stash -- collection failed with AttributeError as expected (the new
  tests import _get_ecmwf_aifs_prob at module level); (2) narrower mutation
  changing the max(...) formula to a single term -- the gap-value test failed
  with the exact predicted symptom (0.13 instead of 0.15), then both were
  restored and re-verified green.
  Regression sweep while building this (weather_markets/tracker/
  prediction_kwargs/trading/p1_remaining/debug_fixes plus a broader second
  pass across p9_p10/ml_bias/paper/phase4/retirement_probation/regression/
  pnl_attribution/phase2_batch_h/cron_integration/live_execution/
  confidence_tiers/sameday_reserve): 1071 passed, 6 skipped, 0 failures.
  ruff + ruff format + mypy clean on all 7 changed files.
  Independent Agent(opus, effort=high) review of the diff: confirmed the
  gate is unchanged, the helper/cache-key reasoning is correct, the gap
  formula and None-guards are correct, schema/INSERT/params are internally
  consistent (44 columns = 43 placeholders + datetime('now'), new column
  appended at the end everywhere so no existing column shifted), and zero
  live-trading-behavior change beyond the new log-only column/key. One real
  finding: the field was originally named ecmwf_consensus_gap_f, but the
  `_f` suffix means degrees-Fahrenheit everywhere else in this file
  (ensemble_spread_f, model_disagreement_f, forecast_temp_f) while this
  value is a probability-space gap in [0,1] -- renamed to
  ecmwf_consensus_gap_prob across all 6 touched files (mechanical, caught
  before any data existed under the old name, so no migration/backfill
  concern) and re-verified lint/mypy/tests green after the rename.
  Still open, unstarted: item 2, the actual 3-way gating decision
  (all-pairwise-agreement vs max-min-spread threshold) -- same "when to
  revisit" trigger as above, now with ecmwf_consensus_gap_prob's own
  accumulation clock started to eventually inform that threshold choice
  with real data instead of a guess.
```

### 2. Pre-existing backlog item (`backlog.txt:10151`)

```
[PARTIALLY RESOLVED 2026-07-24 -- logging side shipped; retraining/feature-
  vector wiring still gated on accumulation, as this entry's own "when to
  revisit" always said] RICHER ML CALIBRATION FEATURES
Priority: Medium (model architecture is fine; the feature vector is the
  bottleneck)

Problem (as originally scoped):
  The GradientBoosting bias model trains on exactly [our_prob, month,
  days_out, 0.0] (ml_bias.py:204) — four features, the fourth literally
  always zero. Ensemble spread, ICON/GFS disagreement, data_quality score,
  condition_type, and sigma-used are all computed at trade time and
  discarded before training.

What shipped (2026-07-24, combined with FORECAST-CONDITION COVARIATES FOR
  SIGMA above in one logging pass):
  ensemble_spread_f and model_disagreement_f (both already computed at
  trade time in analyze_trade()'s result dict, just never persisted)
  threaded through log_prediction()/tracker.predictions (schema v56) and
  the shared _prediction_kwargs_from_analysis() helper, log-only. 6 new
  tests, opus review clean, pushed `9f2ad91`.

Still open (unchanged from original scoping):
  - ml_bias.py:204's training feature vector itself is UNTOUCHED -- still
    exactly [our_prob, month, days_out, 0.0]. This was deliberate: the
    200-samples-per-city training gate means retraining needs weeks of
    newly-logged rows with the new columns before it can use them
    (existing rows lack them, no backfill possible). data_quality/
    condition_type/sigma_used are also still not logged.

When to revisit:
  - Once enough ensemble_spread_f/model_disagreement_f rows accumulate,
    let the existing `features` importance command arbitrate whether they
    actually earn a place in ml_bias.py's training vector.
```

### 3. Pre-existing backlog item (`backlog.txt:10540`)

```
[PARTIALLY RESOLVED 2026-07-23 -- item #1 (generalize _model_weights()) shipped; #2/#3/#4 (the actual graduation decision) still gated on real data, unchanged] GRADUATE GEM/UKMO (AND FUTURE TRACKING-ONLY MODELS) FROM TRACK-ONLY INTO THE LIVE BLEND
Priority: Medium -- read together with GENERALIZED PER-MODEL ACCURACY
  TRACKING above (Pass 3, conceptually: that entry generalized the
  tracking mechanism, this one generalizes the weighting mechanism the
  same way).

RESOLVED 2026-07-23 (item #1 only -- _model_weights() generalized, zero live
  behavior change today, pushed pending commit): tiers 1 (MAE-derived) and 2
  (learned_weights.json) of _model_weights() now admit any model beyond the
  fixed 3-key baseline that is a genuine candidate for the ensemble blend --
  i.e. in `baseline` or in TRACKING_ONLY_MODEL_NAMES -- instead of only ever
  iterating the hardcoded 3 keys. Tier 3 (pure seasonal, no data at all)
  deliberately stays baseline-only, since a non-baseline model has no coded
  seasonal/climatological prior and consumers' own `weights.get(model, 1.0)`
  fallback already produces the identical neutral value either way.
  A real, non-obvious bug was caught by an opus review before this could ship
  as originally scoped: a naive "admit any model with tracked data" version
  (the first attempt) would have let `ecmwf_ifs025` leak into this function's
  output -- it's real, currently-tracked data (feeds
  _forecast_model_weights()'s SEPARATE daily deterministic blend, has no
  ensemble members, was never a candidate for THIS blend) that, unlike
  gem_global/ukmo_global_ensemble_20km, is NOT blocked by
  TRACKING_ONLY_MODEL_NAMES from reaching mae_weights/learned_weights.json.
  The reviewer's own suggested fix (add ecmwf_ifs025 to
  TRACKING_ONLY_MODEL_NAMES) was rejected as semantically wrong -- that
  constant means "excluded from EVERY live blend," and ecmwf_ifs025 genuinely
  has real live weight elsewhere. Fixed instead by restricting admission to
  `ensemble_candidate_models = set(baseline) | TRACKING_ONLY_MODEL_NAMES`
  specifically (both tiers), which correctly excludes ecmwf_ifs025 without
  mislabeling it. A second opus review confirmed this correction is sound and
  complete (enumerated every model that can ever reach
  get_member_accuracy()'s output -- only ecmwf_ifs025 needed excluding, and
  is now the only one that was) and caught one more real gap: this entry's
  own item #2 text below (and this function's docstring) claimed graduation
  is a clean "one-line change: remove it from TRACKING_ONLY_MODEL_NAMES, no
  other code change needed" -- that is WRONG given the fix above. Removing a
  model from TRACKING_ONLY_MODEL_NAMES alone would also remove it from
  `ensemble_candidate_models` unless it's separately added to `baseline` too
  -- skipping that second step would silently re-exclude it, reproducing the
  exact bug this generalization exists to fix, just one step later.
  **Corrected graduation recipe (supersedes item #2 below): (1) remove from
  TRACKING_ONLY_MODEL_NAMES, (2) add to `baseline` in _model_weights() (a
  plain 1.0 if no seasonal prior is warranted), (3) add to the live-blend
  fetch lists in get_ensemble_temps()/batch_prewarm_ensemble().** Item #3's
  MAE pre-check and item #4's per-city/global-floor reasoning below are
  otherwise unaffected and still the real remaining gate.
  Also documented (not fixed, correctly left as-is): `ensemble_candidate_models`
  treats "in TRACKING_ONLY_MODEL_NAMES" as synonymous with "ensemble-blend
  candidate" -- true today (both current members are real ensemble products)
  but not a structural guarantee; flagged directly in the function's own
  docstring so a future addition to TRACKING_ONLY_MODEL_NAMES for a
  non-ensemble reason doesn't silently get swept into this blend too.
  Both generalizations are confirmed INERT in production today (verified by
  both review passes): TRACKING_ONLY_MODEL_NAMES models are skipped inside
  _weights_from_mae() itself before ever reaching mae_weights, so nothing
  currently exercises the new admission branches outside tests that inject a
  value directly via mock. 3 new regression tests added
  (tests/test_weather_markets.py: tier-1 admits a non-baseline model, tier-2
  admits one, a real-model-that-must-NOT-leak-in test using ecmwf_ifs025
  specifically -- not the untestable-in-practice gem_global/ukmo shape),
  each mutation-tested against a reverted version of the fix. 665 tests pass
  (up from the pre-existing 661) across the full scoped sweep
  (test_tracker.py/test_weather_markets.py/test_signal_quality.py/
  test_forecasting.py/test_phase4.py/test_weather.py); ruff/ruff-format/mypy
  clean.
  Item #1 (generalize _forecast_model_weights() too) from the original plan
  below was found NOT NEEDED after tracing the actual code: gem_global/
  ukmo_global_ensemble_20km only ever appear via the ensemble-side
  _get_gem_ukmo_means() (ENSEMBLE_BASE), never anywhere near
  _forecast_model_weights() or get_weather_forecast()'s deterministic daily
  fetch loop -- they are exclusively ensemble-shaped models. Touching that
  second live-trading-critical function would have been unnecessary surface
  area for zero benefit.

Problem:
  As of Pass 2, gem_global/ukmo_global_ensemble_20km are tracked for
  accuracy (model_forecast_means, ensemble_member_scores) but structurally
  barred from the live blend via TRACKING_ONLY_MODEL_NAMES
  (weather_markets.py). The reason they're barred isn't a policy choice
  about GEM/UKMO specifically -- it's that _model_weights() (the ensemble
  blend, feeds batch_prewarm_ensemble) and _forecast_model_weights() (the
  daily point-forecast blend, feeds get_weather_forecast()) each hardcode
  a fixed 3-key baseline dict (`for model, default in baseline.items()`)
  and normalise/softmax over it -- there is no code path today by which
  ANY model outside that dict could ever earn live weight, no matter how
  much tracked accuracy it accumulates. Hardcoding GEM/UKMO in as a 4th
  and 5th baseline key would work, but repeats the exact "one more model,
  one more hand-edit in N places" pattern GENERALIZED PER-MODEL ACCURACY
  TRACKING was built to end -- and would need doing AGAIN for the next
  source (a future WeatherNext, or whatever comes after).

What the fix looks like:
  1. Generalize _model_weights() and _forecast_model_weights() to iterate
     whatever models clear their EXISTING accuracy floor (the same min_n
     that already gates _weights_from_mae's tier-1 / get_model_weights's
     MIN_OBSERVATIONS=10 softmax inclusion) minus TRACKING_ONLY_MODEL_NAMES,
     instead of a fixed baseline dict -- mirroring exactly how Pass 1
     turned 4 named scalar fields into one generic dict. A model with no
     seasonal/meteorological-skill prior (unlike ECMWF's reasoned ecmwf_w)
     gets a neutral 1.0 default, same as icon/gfs today, until its own
     learned weight overrides it.
  2. Once that mechanism exists, "graduating" a specific model is a
     ONE-LINE change: remove it from TRACKING_ONLY_MODEL_NAMES. No other
     code change needed -- same design promise as Pass 1's "add a source
     needs one line in analyze_trade()."
  3. Do NOT gate this one-line removal on a new, elevated sample floor.
     Re-derived from source (first pass here wrongly proposed a new 50-obs
     floor "because graduation is a bigger decision") and corrected: once
     the mechanism in #1 exists, the EXISTING per-model floor (min_n=20,
     matching ACCURACY_MIN_SAMPLE/SPRT_MIN_TRADES precedent, already used
     to decide whether ANY model's learned weight is trusted) is what
     already answers "is there enough data on this specific model" --
     inventing a separate, higher, GEM/UKMO-specific bar would be exactly
     the kind of new-signal special-casing the RUN-TO-RUN TREND entry's own
     ENABLEMENT TRIGGER text warns against ("don't invent a new... bar just
     because this signal is new").
  4. DO add a concrete, written pre-check before #2 (revised after user
     pushback on the first-pass "no formal bar, just eyeball it" proposal
     -- correctly: the inverse-MAE formula's self-regulation has a lag.
     weight = 1/mae is normalised over a ROLLING window (60 days in
     _weights_from_mae, 30 in get_model_weights), so a genuinely bad model
     only gets down-weighted gradually as its window-average MAE catches
     up -- meaning it could measurably drag on real trade probability for
     weeks after graduation before the formula discounts it. A pre-check
     run BEFORE the code change ships, not an after-the-fact hope the
     formula self-corrects, is the actual fix for that lag). The concrete
     check: at graduation time, query get_member_accuracy()/
     get_model_weights() for the SAME city and rolling window the live
     blend itself uses, and require:
       gem_or_ukmo_mae <= worst-performing current baseline model's mae
     (i.e. icon_seamless/gfs_seamless/ecmwf_aifs025_ensemble/ecmwf_ifs025's
     own MAE over that identical window/city, whichever is highest/worst
     today) -- not "must beat the average," just "must not be worse than
     the worst model already blended," so graduating GEM/UKMO can't make
     the blend's own worst-case per-model error picture worse than what's
     already live. Compute this per-city (accuracy can vary a lot by
     region -- a model competitive in NYC could be bad in Phoenix), but
     since TRACKING_ONLY_MODEL_NAMES is a single global flag per model
     (see the mechanical note under "When to revisit" below), the actual
     go/no-go is the WORST city's result across all cities with enough
     data, not any single city's -- don't flip the global switch on a
     good NYC number while some other city is quietly bad. If a model
     fails this check, leave it in TRACKING_ONLY_MODEL_NAMES and re-check
     again after more data accumulates, rather than graduating it anyway
     on the theory the formula will fix it. This is a documented, defined
     criterion to apply at the time -- not vague "eyeball it" -- while
     still keeping the actual code change (#1/#2) itself a deliberate,
     reviewed, separately-confirmed merge, matching this file's own
     stated philosophy for this shape of decision (see the SIGNAL
     GRADUATION entry: "leave blend wiring manual -- the deliberate human
     step is the point of the pattern").

Why not now:
  - #1/#2 are real, live-trading-critical code changes (both blend weight
    functions) that deserve their own dedicated pass, review, and test
    coverage -- not a rider on Pass 2.
  - There is no real tracked data yet: gem_global/ukmo_global_ensemble_20km
    were only wired into model_forecast_means as of Pass 2 (2026-07-23),
    so ensemble_member_scores has zero rows for either. The floor in #3
    (min_n=20, per-city or global matching _weights_from_mae's own
    fallback logic) hasn't remotely been reached and needs real elapsed
    paper-trading time, not more engineering effort right now.

When to revisit:
  - Check settled-observation counts for gem_global/ukmo_global_ensemble_20km
    in ensemble_member_scores periodically (e.g. whenever this file is next
    open for other reasons, same cadence as the RUN-TO-RUN TREND and
    DATA-DRIVEN SIGMA FROM SETTLED HISTORY entries' own settled-count
    checks -- all three are gated on the same kind of settled-trade volume
    growing over time).
  - Once min_n=20 is cleared (per-city preferred, global fallback,
    mirroring _weights_from_mae's existing tier-1 logic exactly): build #1
    (generalize both weight functions), then run #4's concrete MAE
    pre-check per-city against icon/gfs/ecmwf_aifs025_ensemble/
    ecmwf_ifs025's own numbers over the same window. Important mechanical
    note (caught while writing this up): TRACKING_ONLY_MODEL_NAMES is a
    single global on/off per model, not per-city -- there is no way to
    graduate a model in NYC but leave it track-only in Phoenix without a
    bigger change (e.g. turning the set into a city-scoped structure,
    itself a separate design decision, not assumed here). So #4's
    per-city results feed one aggregate go/no-go per model: look at the
    WORST city's result across all cities with enough data, not just any
    single city's -- don't flip the global switch on the strength of a
    good NYC number while some other city is quietly bad. (Per-city
    weight variation still happens correctly AFTER graduation, via the
    existing city-preferred-else-global MAE logic already in
    _weights_from_mae -- what the pre-check gates is only the one-time
    global on/off decision, not ongoing per-city weighting.) Then do #2
    (remove from TRACKING_ONLY_MODEL_NAMES) as an explicit, reviewed,
    separately-confirmed change -- not an automatic flip the moment the
    floor is crossed.
  - GEM and UKMO should graduate independently, not as a pair -- no reason
    to hold one back for the other, and UKMO's shorter real forecast
    horizon (~9-10 of 16 days, see Pass 2's resolution above) may mean it
    never earns a competitive learned weight even with plenty of data,
    which is fine -- that's exactly what the inverse-MAE weighting is
    supposed to discover on its own.
```

### 4. Pre-existing backlog item (`backlog.txt:11100`)

```
[DATA-DRIVEN SIGMA FROM SETTLED HISTORY + CLI-REPORT SETTLEMENT FETCH]
Priority: Medium (sharpens every probability the bot emits; unblocks a
  recorded deferral)

Problem:
  _HISTORICAL_SIGMA is a static city table; sigma feeds gaussian_probability()
  on every trade. outcomes.settled_temp_f now exists with real history but
  its only consumer is EMOS training. Separately, a CLI-report-based
  settlement fetch (IEM afos API, city->WFO/pil table) was designed and
  proven feasible 2026-07-05 but deferred pending "a consumer for
  settled_temp_f accuracy" — this is that consumer. sigma_audit.py is
  diagnostic-only (its own docstring: "no behavior changes").
  CORRECTION 2026-07-20: the original LasVegas/NewOrleans framing above is
  stale — that gap is [RESOLVED 2026-07-12] separately, and
  get_historical_sigma() (weather_markets.py:2294-2313) now tries a dynamic
  per-city/per-month sigma from the 30yr climatology archive before falling
  back to the static table, so LV/NOLA already get real values that way.
  Doesn't invalidate this entry's actual ask (climatology-derived sigma
  reflects climate variability, not actual forecast error vs. settled_temp_f
  — a genuinely different quantity), just the specific example used to
  motivate it.

What the fix looks like:
  Compute per-city (and per-season, matching the existing table's shape)
  forecast-error sigma from settled_temp_f vs forecast_temp history; fall
  back to the static table below a sample-size floor. Build the CLI-report
  fetch (or the cheaper reactive variant: only on ASOS MISMATCH) so the
  training data uses Kalshi's real settlement source. Fixes the LV/NOLA
  sigma gap as a side effect.

Why not now:
  - Needs enough settled history per city/season to beat the static values
    (check counts before starting); CLI fetch carries the known per-city
    hardcoded-table risk documented in the 2026-07-05 deferral.
  - RE-VERIFIED 2026-07-20: queried predictions.db directly (join
    predictions/outcomes on settled_temp_f IS NOT NULL, grouped by
    city/season) — max per-city-per-season count is 21 (Seattle, summer),
    every other cell lower, 234 settled_temp_f rows total across all
    cities/seasons. Still below this entry's own ~30/season floor. For
    context: tracker.count_settled_predictions() = 130,
    count_emos_ready_predictions() = 94. Not ready yet.

When to revisit:
  - Check settled_temp_f row counts per city; start when the biggest cities
    clear a reasonable floor (~30+ per season) — as of 2026-07-20, still not
    crossed (21 max).

UPDATE 2026-08-10 (CLI-report settlement fetch shipped, a cheaper angle than
  this entry's original "What the fix looks like" envisioned; the sample
  floor is NOT yet cleared and the sigma computation itself is STILL NOT
  BUILT, entry remains open -- CORRECTED same day, see note below, after an
  opus review caught the first version of this update overclaiming): per
  docs/feature-scan-2026-08-09.md finding F1, audit_settlement()'s daily
  HIGH/LOW branch (tracker.py) now reads Kalshi's own settled
  expiration_value directly instead of deriving settled_temp_f from the IEM
  ASOS raw-METAR proxy — no city->WFO/pil table needed at all, since Kalshi
  already returns the literal CLI-report figure on every settled market.
  This removes the "CLI fetch carries the known per-city hardcoded-table
  risk" blocker named above outright.
  What this does NOT do: settled_temp_f has exactly one production writer
  (this same daily branch), so the new one-off backfill
  (tracker.backfill_daily_temp_settlement(), `py main.py
  backfill-daily-temp-settlement`) can only CORRECT existing rows' values
  against Kalshi's real settlement -- it cannot create new ones. Read-only
  production probe 2026-08-10 (opus review): 279 rows currently have
  settled_temp_f (all KXHIGH*/KXLOW*, 259 distinct city/date pairs, max 16
  for one city) -- essentially the 234-row 2026-07-20 count plus 6 weeks of
  organic accumulation, not a step change. The ~30/season floor this entry
  is gated on is NOT cleared by shipping the fetch or running the backfill
  alone. Clearing it for real needs a separate bulk-harvest pass (fetch
  every finalized market per tracked series via
  client.get_markets(series_ticker=..., status="settled") -- the pattern
  already used at weather_markets.py:9022-9024 -- and log_prediction/
  log_outcome rows for ones this bot never itself predicted), which is NOT
  built by this change and is real, separately-scoped follow-up work.
  Whoever picks this up next should re-run the 2026-07-20 per-city/per-
  season count query against settled_temp_f first (not assume it's cleared)
  before deciding whether the sigma computation itself -- unchanged,
  unstarted -- is ready to start, or whether the bulk-harvest pass above
  needs to happen first.
```

### 5. Pre-existing backlog item (`backlog.txt:12742`)

```
[PARTIALLY RESOLVED 2026-07-24 -- precip_sum_in logging + the wind_gust/
  _hourly_window_high_f wire-up-or-delete call both shipped; sky/cloud
  covariate still needs the not-yet-built NBS sky/gst/p12 fields] FORECAST-CONDITION COVARIATES FOR SIGMA -- INCLUDING FIELDS ALREADY FETCHED AND NEVER READ
Priority: Low-Medium -- sigma today conditions on city/month/horizon/spread
  but never on what kind of weather day it is; several inputs are already
  being paid for.

Problem (as originally scoped):
  The daily forecast fetch requests only
  temperature_2m_max,temperature_2m_min,precipitation_sum
  (weather_markets.py:983); the temperature sigma path
  (weather_markets.py:5620-5660) uses climate sigma x horizon x spread,
  and regime.py conditions only on ensemble mean/std. No weather-type
  conditioning exists anywhere -- yet precip/frontal days have
  systematically larger high-temp errors and cloud-cover busts are the
  classic daily-high miss. Concretely unused today: precipitation_sum is
  fetched with every forecast and never consumed in the temperature path
  (grep of analyze_trade's temp section: precip only routes precip-market
  types at :5340-5350); Pirate Weather's wind_gust/_wind_gust_time_unix/
  _hourly_window_high_f are fetched and stored into the forecast dict
  (weather_markets.py:1097-1100, 2114-2119) with zero readers anywhere
  (repo-wide grep). The NBS bulletins from the REAL NBM entry above would
  add sky/gst/p12 in the same call.

What shipped (2026-07-24, same pass as RICHER ML CALIBRATION FEATURES
  below -- one combined logging pass, per this entry's own "additional
  candidate features for the same GBM" note):
  analyze_trade()'s result dict now surfaces precip_sum_in (forecast.get
  ("precip_in")), threaded through log_prediction()/tracker.predictions
  (schema v56) log-only, same discipline as ensemble_spread_f/
  model_disagreement_f below.
  The wind_gust/_wind_gust_time_unix/_hourly_window_high_f wire-up-or-
  delete call was resolved as DELETE, not wire-up: live-traced that these
  fields are only ever populated via fetch_temperature_pirate_weather()'s
  RARE last-resort fallback path (Open-Meteo AND NBM AND WeatherAPI all
  unavailable) -- wiring them up would have logged mostly NULLs given
  Open-Meteo is the dominant path and doesn't carry them at all. Deleted
  the dead computation blocks and dict keys entirely (confirmed zero test
  coverage existed for them, confirmed high_f's own derivation is fully
  independent of the deleted hourly-window computation). Pushed `9f2ad91`.

Still open:
  - Sky/cloud-cover covariate: NOT built -- would need the REAL NBM
    entry's NBS sky/gst/p12 fields, which this pass didn't touch. Gust is
    now moot (the only real gust field was the just-deleted dead one).

When to revisit:
  - If the REAL NBM entry's NBS sky/gst/p12 fields ever get pulled in for
    another reason, log them alongside precip_sum_in the same way.
```

### 6. Pre-existing backlog item (`backlog.txt:12792`)

```
[PARTIALLY RESOLVED 2026-07-23 -- tracker.get_regional_recent_bias() shipped
  log-only; wiring into an actual forecast lean still gated on more data]
  CROSS-CITY RECENT-ERROR POOLING -- SYNOPTIC-REGIME BIAS SHARE
Priority: Low-Medium -- the spatial correlation structure is already
  learned and stored; it's only ever used to *penalize risk*, never to
  *improve the forecast*.

Problem (as originally scoped):
  Bias correction is strictly per-city and slow: _get_combined_station_bias
  (weather_markets.py:303-337) blends a static table with
  tracker.get_dynamic_station_bias (min 10 samples, weeks of
  accumulation, 4h cache). Nothing used the last 24-48h of realized
  errors in *other* cities to nudge today's forecast -- even though
  forecast errors are spatially correlated under a shared synoptic
  regime, and the bot already quantifies exactly those correlations
  (_CITY_PAIR_CORR paper.py:313-332; tracker.get_recent_city_correlations
  refreshed into monte_carlo.simulate_portfolio) -- but solely for
  portfolio VaR.

RE-VERIFIED 2026-07-23 before picking this up: the "3-14 per-city" count
  cited above was stale (2026-07-12 audit) -- live counts were actually
  1-28 per city, and the settlement-latency question was resolved
  affirmatively (median lag ~1 day across 237 recent settlements, so
  yesterday's correlated-city errors ARE typically available by today's
  scan).

What shipped:
  tracker.get_regional_recent_bias(city, var, hours=48, as_of=None) --
  correlation-weighted mean of correlated cities' settled errors, using
  the exact _CORRELATED_CITY_GROUPS/_CITY_PAIR_CORR tables named above,
  with a ROW_NUMBER dedup to each ticker's latest logged prediction and
  outcomes_valid's disputed-row exclusion. `as_of` (SQLite datetime()
  string) lets a caller reconstruct a specific historical point in time
  without lookahead -- used to retrospectively validate against real
  settled data: Pearson r ~= 0.35 between pooled regional bias and same-
  city same-day error, but thin per-estimate coverage (85/229 candidate
  rows had any signal, averaging 1.67 correlated-city samples each). 9
  new tests, opus review clean (one defense-in-depth hardening applied:
  bound predicted_at by as_of too). Pushed `fd94bf7`.

Still open:
  - NOT wired into any live forecast lean or blend weight -- the r~0.35
    result is real but too sparse to trust yet, correctly shipped as a
    log-only/ad-hoc utility per this entry's own sequencing.

When to revisit:
  - Re-run the retrospective validation once more settled data has
    accumulated; if correlation holds up with denser per-estimate
    coverage, size a bounded lean capped well below
    _get_combined_station_bias's magnitude.
```

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

This batch is documentation/test/low-risk-code only. If every item you actually touch turns out to be a small, mechanically-verifiable diff with no live-order/live-money/safety-gate surface and no multi-file span, steps 11-12 may collapse to the LOW tier (a single self-review pass + one Agent check instead of a dedicated opus effort:high spawn). Re-assess per item -- don't downgrade the whole batch by default if one item in it turns out bigger than expected.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
