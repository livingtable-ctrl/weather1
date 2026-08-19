# Batch 19: Signal graduation convention

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch groups 1 **pre-existing** backlog item(s) (not from the 2026-08-18 audit) sharing **tracker.py, ml_bias.py**. Each item's full existing entry is reproduced verbatim below from `backlog.txt` -- these already have their own Problem/Priority write-ups from earlier sessions; read them in full rather than treating the excerpt here as complete.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. Pre-existing backlog item (`backlog.txt:14624`)

```
[PARTIALLY RESOLVED 2026-07-25 -- parts (a) and (b) shipped; part (c), the
  blend-weights-dict refactor, still open, deliberately scoped out as its
  own separately-reviewed pass given its live-blend blast radius --
  STALE TITLE CORRECTED 2026-08-06, see note near the end: part (b) shipped
  a real mechanism (SIGNAL_REGISTRY + a standing graduation-report command),
  so "IS A CONVENTION, NOT A MECHANISM" no longer describes what's left]
  SIGNAL GRADUATION IS A CONVENTION, NOT A MECHANISM -- SIGNAL #3 REBUILDS RUN-TREND'S PLUMBING
Priority: Medium -- the log-only->trigger->blend pattern is now this
  project's explicit strategy for all new alpha; its marginal cost is
  currently ~6 touch points per signal.

Problem:
  Run-trend established the graduation *pattern* but implemented it as
  bespoke wiring at every layer, so signals #3-#5 (trade-flow, AFD,
  richer-ML features are all queued in this file) each repeat it.
  Storage: one named migration per scalar (tracker.py:221-223, v40-v42)
  plus dedicated columns per signal -- predictions is now at schema v53
  largely from this accretion (was v42 when this entry was written; the
  hourly-directional work added var TEXT, one more accretion of the exact
  same shape this entry describes). API: a new named parameter on
  log_prediction() (tracker.py:610 run_trend: dict | None) -- the
  signature grows one kwarg per signal, forever. Threading: every
  log_prediction call site updated through order_executor's shared helper
  _prediction_kwargs_from_analysis (order_executor.py:1926) -- CORRECTION
  2026-07-20: main.py's two direct call sites no longer re-import
  get_forecast_run_trend_from_analysis locally; that specific duplication
  was fixed by [RESOLVED 2026-07-17] LOG_PREDICTION KWARGS ASSEMBLY
  TRIPLICATED (below) -- both call sites now route through the same shared
  helper. The core thesis (kwarg-growth-per-signal, no generic mechanism)
  is otherwise unaffected by that fix and still fully holds.
  Enablement: run-trend's trigger (sample floor + correlation check)
  exists only as backlog.txt prose that someone must remember to run by
  hand. Meanwhile the codebase already *has* an in-code activation
  mechanism -- sample-gated auto-activation with one-time notification
  (_regime_blend_active() weather_markets.py:3887 +
  _notify_feature_activation 3852, and siblings: PDO/PNA gate at 3912,
  MIN_BIAS_CORRECTION_TRADES) -- but it's re-derived per feature and was
  not used for run-trend. Blend entry (the eventual step): the core
  blend is a *positional 3-tuple* -- _blend_weights() returns
  (w_ensemble, w_climatology, w_nws) (weather_markets.py:3954-3962). Any
  signal graduating to a real blend weight either changes that arity
  everywhere or joins the growing chain of bespoke post-blend
  adjustments, which is how analyze_trade got to 1,660 lines.

What it would look like:
  (a) log_prediction(..., signals: dict[str, float] | None) persisting to
  a signal_values(prediction_id, name, value) table (or one JSON column,
  matching the blend_sources/run_trend_points precedent) -- new signal =
  new dict key, zero migrations, zero signature/call-site changes; (b) a
  small signal registry (name, extract(analysis) -> value(s),
  sample_floor, correlation_target) driving both a standing
  graduation-report command (runs every pending signal's enablement query
  against settled outcomes -- replaces the per-entry prose triggers) and
  the auto-activation notification machinery that already exists for
  regime/PDO; (c) leave blend *wiring* manual -- the deliberate human
  step is the point of the pattern -- but let graduated signals enter as
  named entries in a weights dict rather than tuple-position N+1.

Why not now:
  - Do (a)+(b) when the *next* log-only signal is built (trade-flow is
    queued post-Belgium) -- that's when the second data point proves/
    disproves the shape, and the cost is near-zero incremental to work
    already planned. Not worth a standalone pass while run-trend's own
    trigger hasn't fired.

When to revisit:
  - When PUBLIC TRADE-FLOW SIGNAL (or any other log-only signal above) is
    next picked up -- build the registry then, not before.

RESOLVED 2026-07-24 (part (a) only -- storage mechanism; parts (b)/(c)
  still open, unstarted): picked up out of the literal "when to revisit"
  order -- re-read the entry live before starting and found its own gate is
  "build this when the next log-only signal is picked up, not before," but
  the 3-WAY MODEL_CONSENSUS CHECK entry (shipped earlier the same session,
  see above) had *just* added a 6th hand-wired signal
  (ecmwf_consensus_gap_prob) without this mechanism -- the gate had already
  fired and been missed, with no new signal currently queued to validate a
  design against. Talked this through explicitly with the user rather than
  deferring outright (as two other entries were deferred earlier this same
  session for genuinely still-unmet gates) or silently proceeding with the
  full (a)+(b)+(c) scope: the storage piece (a) is low-blast-radius (one
  new nullable column, nothing existing touched or migrated) and has 6 real
  historical signals' worth of shape to design against, unlike (b)'s
  registry/report-command tier which is more genuinely speculative without
  a concrete next signal driving its requirements. User chose to ship (a)
  only and explicitly skip the registry.
  Shipped: tracker.log_prediction(..., signals: dict[str, float] | None)
  persisting to a single new signal_values TEXT column as JSON (schema
  v58->v59) -- mirrors the existing blend_sources/run_trend_points
  JSON-column precedent exactly, rather than a separate
  signal_values(prediction_id, name, value) table. order_executor.py's
  _prediction_kwargs_from_analysis now unconditionally reads
  a.get("signals") and passes it through -- a FUTURE new log-only signal
  needs zero new migration, zero new log_prediction parameter, and zero new
  order_executor.py wiring; it only needs to create a `signals` dict inside
  analyze_trade()'s result (there is no such dict there yet -- this ships
  the pipe, nothing flows through it today) and, on the read side, its own
  json_extract()-based query (no consumer/registry/report exists yet
  either, deliberately -- that's the still-open (b)).
  The existing 6 named columns (run_trend, ensemble_spread_f,
  model_disagreement_f, precip_sum_in, nbm_quantile_prob,
  ecmwf_consensus_gap_prob) are deliberately NOT retrofitted onto this --
  would need a backfill/consumer-migration pass per column, explicitly out
  of scope.
  New tests: tracker round-trip/absent-null/reupsert-overwrite (mirrors the
  established pattern for every prior log-only column) plus one this
  mechanism specifically needed that scalar columns didn't --
  signals={} (empty dict, falsy but not None) must still serialize to
  non-NULL "{}", distinct from omitting the argument entirely (NULL); and
  order_executor kwargs-passthrough (derived-when-present /
  absent-gives-None-not-KeyError, mirrors nbm_quantile_prob's tests).
  Mutation-tested (stashed tracker.py+order_executor.py -> all 6 new tests
  failed with the exact predicted TypeError/KeyError; restored and
  re-verified green). 519 tests pass across this session's own scoped sweep
  (test_tracker.py/test_prediction_kwargs.py/test_weather_markets.py) plus
  a separate 466-test background pass this session also ran (same
  p9_p10/ml_bias/paper/phase4/retirement_probation/regression/
  pnl_attribution/phase2_batch_h/cron_integration/live_execution/
  confidence_tiers/sameday_reserve sweep as the earlier 3-WAY session);
  ruff/ruff format/mypy clean on all 4 changed files.
  Independent Agent(opus, effort=high) review (its own separate isolated
  verification, not this session's own numbers above): confirmed schema/
  SQL/params counts internally consistent (45 columns = 44 placeholders +
  datetime('now'), new column appended last everywhere so no existing
  column shifted), JSON-encoding pattern matches blend_sources exactly,
  zero live-behavior change (grepped weather_markets.py -- "signals" is set
  nowhere, so every real call site resolves to None today), its own 4
  mutation tests genuinely killed real mutants
  (is_not_None-vs-truthiness, dropped ON-CONFLICT-SET clause, wrong .get()
  key), and its own broader 424-test pass (test_tracker.py/
  test_prediction_kwargs.py plus test_infrastructure/test_phase2_batch_g/
  test_execution_log/test_trading). Findings, all fixed:
  (1) a migration comment spliced two different backlog-entry quotes
  together as if one verbatim quote -- corrected to cite both accurately;
  (2) the same comment's "add one key to analyze_trade()'s signals dict,
  done" overclaimed completeness (no signals dict exists there yet, and
  there is no reader either) -- reworded to say so explicitly; (3) the new
  `signals` param name can be confused with this codebase's unrelated
  existing use of "signal(s)" for a scanned trade candidate (cron.py's
  signals_cache, "no qualifying signals" elsewhere in order_executor.py) --
  added a comment distinguishing them, since `a` is an untyped dict so
  nothing else catches the mix-up; (4) signal_values_json's assignment was
  the only new-value-in-this-diff not appended last among its siblings --
  moved for consistency (cosmetic, zero functional effect). User confirmed
  commit+push explicitly.
  Still open at that point, unstarted: part (b) (the signal registry +
  standing graduation-report command + auto-activation-notification reuse)
  and part (c) (graduated signals joining a named blend-weights dict instead
  of _blend_weights()'s positional tuple) -- same "when to revisit" trigger
  as above.

RESOLVED 2026-07-25 (part (b) -- the signal registry + standing
  graduation-report command; part (c), the blend-weights-dict refactor, is
  deliberately still open, see below): picked up on explicit user request.
  Re-verified this entry's own stated gate before designing anything --
  "build the registry when the next log-only signal is picked up, not
  before." No new log-only signal was queued or in flight at the time this
  was picked up either -- the literal gate still hadn't fired a second time.
  Surfaced this via AskUserQuestion rather than silently building
  speculatively or silently deferring again: since 8 real signals (not just
  run_trend, the only one that existed when this entry was first written)
  now have their own real, already-battle-tested backlog.txt "ENABLEMENT
  TRIGGER" prose, retrofitting all 8 into the registry now was scoped as the
  registry's actual second-and-onward data points, proving/disproving the
  design against real historical cases rather than a hypothetical future
  one. User confirmed: build part (b) only this pass (part (c) deferred as
  its own separately-scoped follow-up given the live-blend blast radius --
  see below), retrofit all 8 signals now rather than shipping an empty
  shell.
  Research before designing (not assumed from this entry's own text, which
  predates several of the 8 signals): grepped every backlog.txt
  "ENABLEMENT TRIGGER" section and found the 8 signals' triggers are NOT
  uniform in rigor or shape -- only run_trend and GEM/UKMO give a literal,
  machine-checkable numeric floor + query; the rest ("richer ML", "market
  implied", "3-way ecmwf", "nbm_quantile_prob", "cross-city pooling") defer
  to prose ("once enough rows accumulate," "same precedent as X") with no
  query ever written out. This meant a registry entry's "correlation check"
  genuinely can't be one generic automated query across all 8 -- a Pearson
  correlation, an MAE-vs-baseline-model comparison, and "let the existing
  `py main.py features` command arbitrate" are three different kinds of
  judgment call. Landed on automating ONLY the sample-floor count (which
  every signal's own trigger text does agree is the real gate, whether
  literal or implied) and keeping each entry's correlation check as a
  documented `correlation_note` string -- a human-readable reminder of what
  to actually check once the floor clears, not something the registry
  itself computes. Matches this entry's own stated philosophy ("leave blend
  *wiring* manual -- the deliberate human step is the point of the
  pattern") extended one step earlier: the graduation *judgment*, not just
  the graduation *wiring*, stays a human call.
  Also found the count sources aren't uniform: 6 of the 9 registry rows
  (run_trend, market_implied, gated_edge, richer_ml_features,
  nbm_quantile_prob, ecmwf_consensus_gap -- the last one switched from an
  ensemble_member_scores model-observation count to its own
  ecmwf_consensus_gap_prob column after the review below, since that
  column IS the entry's own stated "accumulation clock", and the raw
  model-observation count accrues faster and would have cleared the floor
  well before the actual correlation-checkable signal had enough samples)
  check a `predictions` column (or, for any future signal shipped only
  through the generic `signals` JSON column, a `json_extract` key) joined
  to a real settled temperature; both GEM/UKMO graduation entries check
  `ensemble_member_scores` (a tracked *model*, not a per-prediction column)
  instead, correctly -- their own min_n=20 trigger is genuinely about raw
  tracked-model observations, not a logged column; cross-city pooling has
  no persisted per-row signal at all (it's a standalone retrospective-
  validation utility, tracker.get_regional_recent_bias, already run once
  with a real r~=0.35-but-thin-coverage result) and got a purely
  informational entry with `count_fn=None` pointing at that result rather
  than a fabricated query.
  Also found (and fixed) that count_settled_signal_rows joining the full
  `predictions` table rather than the `multiday_predictions` view diverges
  from this file's own established convention (count_settled_predictions'/
  count_emos_ready_predictions' docstrings: the view exists specifically
  "so same-day METAR trades don't inflate ... the graduation threshold")
  -- correct for gated_edge/market_implied/richer_ml_features/
  nbm_quantile_prob/ecmwf_consensus_gap, which are all genuinely computed
  for same-day markets too and would be undercounted by the view, but
  wrong for run_trend specifically, whose own production function
  (get_forecast_run_trend) documents itself as multi-day-only. Added a
  `multiday: bool` param to count_settled_signal_rows and set it only for
  run_trend's registry entry -- makes the exclusion structural (via the
  view) rather than relying solely on run_trend's own writer-side gate to
  never populate a same-day row, matching this file's stated preference
  for a structural guarantee over an implicit one.
  Shipped: tracker.count_settled_signal_rows(column, *, json_key=None,
  multiday=False) -- the generic predictions-column/JSON-key counter,
  matching count_emos_ready_predictions' settled_temp_f-required,
  outcomes_valid-joined filter shape exactly (excludes disputed rows,
  matching every other calibration-adjacent count in the file) but NOT its
  table choice by default (see the multiday note above -- table choice is
  per-entry, not hardcoded to the view) -- and
  tracker.count_model_observations(model) -- a single-model,
  settled-rows-only counter mirroring get_member_accuracy's own filter but
  returning a plain count instead of a full MAE breakdown. weather_markets.
  SIGNAL_REGISTRY (a tuple of 9 frozen _SignalRegistryEntry dataclasses:
  run_trend, market_implied, gated_edge, richer_ml_features,
  nbm_quantile_prob, ecmwf_consensus_gap, gem_graduation, ukmo_graduation,
  cross_city_pooling -- 9 rows for 8 backlog topics, since GEM and UKMO
  graduate independently per their own correlation_notes despite sharing
  one "GRADUATE GEM/UKMO" backlog entry) and
  weather_markets.get_signal_graduation_report() (walks the registry,
  calls each entry's count_fn, compares to sample_floor when both exist,
  calls the existing _notify_feature_activation the first time a floor
  clears -- reusing the exact one-time-alert mechanism
  _regime_blend_active/_pdopna_blend_active already use, so a graduation-
  ready signal surfaces the same way any other auto-activation does, and a
  count_fn exception is caught and reported as an unavailable count rather
  than crashing the whole report for every other signal). Wired into a new
  `py main.py signals` CLI command (cmd_signals(), main.py) -- the "standing
  graduation-report command" this entry's own text asked for, replacing the
  need to remember and hand-run each signal's own scattered prose trigger.
  Read-only throughout -- zero live-trading-behavior change; verified via a
  real (not mocked) end-to-end test against an empty, isolated DB that all
  9 real registry entries resolve cleanly to 0/not-cleared with no
  exceptions.
  21 new tests: 8 for the two new tracker.py counters (column-based
  non-NULL filtering, settled_temp_f-required, disputed-row exclusion, the
  JSON-key path, model-observation counting including the
  actual_temp-NULL-excluded case) in tests/test_tracker.py; 9 for the
  registry/report mechanism (every registered signal appears in the report,
  below-floor vs. floor-cleared vs. no-fixed-floor vs. count_fn=None vs.
  count_fn-raises, idempotent notify-file behavior, plus the real-registry
  end-to-end smoke test) in tests/test_forecasting.py; 4 for the CLI
  command's display logic in tests/test_p1_remaining.py. Mutation-tested
  the auto-notify wiring directly (temporarily disabled the
  `if floor_cleared:` branch in get_signal_graduation_report, confirmed the
  notify-file test failed with the exact predicted FileNotFoundError,
  restored and re-verified green) -- caught a real mistake in my own first
  test-count assertion in the process (asserted "8 registry entries," the
  actual number is 9 for the reason above; corrected before this was ever
  a hidden bug, just a wrong test literal caught by running the tests, not
  by review).
  Independent Agent(opus, effort=high) review before push found no CRITICAL
  scope violations (confirmed SIGNAL_REGISTRY/get_signal_graduation_report
  have exactly one non-test caller -- the CLI command -- and _blend_weights
  is untouched) but 7 real findings, all fixed: (1) MEDIUM --
  count_settled_signal_rows joined raw `predictions` for every signal,
  diverging from this file's own established multiday_predictions-view
  convention for exactly the "don't let same-day noise inflate the
  graduation threshold" reason count_settled_predictions'/
  count_emos_ready_predictions' own docstrings state -- added a
  `multiday: bool` param, set True only for run_trend (the one signal
  whose own production function documents itself as genuinely multi-day-
  only), left False for the others (genuinely computed for same-day
  markets too, so the view would have undercounted real samples, not just
  filtered noise) -- see the multiday paragraph above for the full
  per-signal reasoning. (2) MEDIUM -- a typo'd/renamed model name passed
  to _count_model_obs would fail silently forever (count_model_observations
  returns 0 for an unknown model, indistinguishable from "not yet
  tracked") -- fixed by validating against KNOWN_FORECAST_MODEL_NAMES at
  closure-build time (module-import time), the same guard class
  _validate_forecast_model_keys already provides on the write side; a
  typo'd real registry entry would now fail the whole module's import,
  not just silently pin one signal's floor at 0. (3) MEDIUM-LOW -- the
  richer_ml_features entry's real count_fn was computed then discarded by
  the CLI (only entries with a sample_floor showed their count; the one
  entry with a count but no floor showed nothing) -- fixed cmd_signals to
  show "`N` samples, no fixed floor" when a count exists. (4) LOW -- the
  3-way ECMWF entry counted raw ecmwf_aifs025_ensemble rows in
  ensemble_member_scores, which accrues faster than the actual
  correlation-checkable ecmwf_consensus_gap_prob column (its own stated
  "accumulation clock" per the 2026-07-24 resolution) -- switched to count
  ecmwf_consensus_gap_prob directly, so the floor-cleared notification
  fires when the real signal has enough samples, not when the underlying
  model merely has enough raw tracked observations. (5) LOW -- 3 doc/
  comment off-by-one errors (this entry's own "6 of 9"/wrapper-repeated-
  "6 times"/a test docstring's "8-entry registry", all should have said
  5/5/9) -- corrected. (6) LOW -- `signals` was missing from README.md's
  command table, the only place CLI subcommands are enumerated for
  discoverability (cmd_help's interactive menu doesn't list subcommands
  either) -- added. (7) LOW -- count_settled_signal_rows accepted both
  column= and json_key= with one silently ignored (a test had to pass an
  "unused" dummy column even when only json_key mattered) -- tightened to
  require exactly one, raising ValueError otherwise. 4 more tests added
  addressing these fixes directly (a multiday-exclusion test proving the
  view restriction is structural not incidental, an exactly-one-of
  ValueError test, a model-name-typo-rejection test, a regression test
  proving ecmwf_consensus_gap now reads its own column even when
  ensemble_member_scores has real rows for the model) -- 25 signal-
  graduation tests total across the 3 files (10 tracker.py counters, 11
  registry/report, 4 CLI display). Full regression sweep (647 tests
  passed, 4 pre-existing skips) + ruff/ruff format/mypy re-run clean after
  every fix.
  Deliberately did NOT build part (c) this pass (own separate AskUserQuestion
  decision, see the header tag above): _blend_weights() returns a positional
  3-tuple with 4 real production call sites (weather_markets.py) and ~25
  test call sites unpacking it positionally -- converting to a dict so a
  graduated signal could enter as a named key instead of a new tuple
  position touches the actual live probability-blend code, a different risk
  tier from this pass's pure-reporting mechanism. Scope this as its own
  pass, with its own review, whenever a real graduated signal is ready to
  wire in and the tuple-arity ergonomics actually start to bite -- don't
  build it speculatively ahead of that, matching this project's own
  established "don't build the abstraction before a second real case
  demands it" discipline (see NO MARKET-TYPE SEAM's identical reasoning for
  the MarketType protocol).

STALE TITLE CORRECTED 2026-08-06: this entry's title ("SIGNAL GRADUATION IS
  A CONVENTION, NOT A MECHANISM") was accurate when written (2026-07-16/17),
  but part (b) above shipped a real mechanism 2026-07-25 -- a SIGNAL_REGISTRY
  plus a standing `py main.py signals` graduation-report command that
  replaces the old "prose trigger someone has to remember to run by hand"
  problem this title was originally naming. Only part (c) (the
  _blend_weights() positional-tuple-to-named-dict refactor) remains open,
  a narrower claim than the title implies. Caught during a 2026-08-06
  full backlog.txt read-through (same pattern as the STALE TITLE/COUNT
  corrections on the ForecastCache and main.py-frozen-import entries
  above) -- title/header corrected per this project's standing convention;
  historical resolution text above left unchanged.
```

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

This batch is documentation/test/low-risk-code only. If every item you actually touch turns out to be a small, mechanically-verifiable diff with no live-order/live-money/safety-gate surface and no multi-file span, steps 11-12 may collapse to the LOW tier (a single self-review pass + one Agent check instead of a dedicated opus effort:high spawn). Re-assess per item -- don't downgrade the whole batch by default if one item in it turns out bigger than expected.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
