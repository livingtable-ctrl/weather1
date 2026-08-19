# Batch 6: Brier/calibration condition_type filter family

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch comes from the 2026-08-18 max-depth forensic audit (`audit/AUDIT_REPORT.md` / `.json`). It groups 3 finding(s) that share **tracker.py** -- doing them together means you only load this subsystem's context once, and avoids two different sessions independently editing the same file in parallel. Live trading is currently dormant (`LIVE_TRADING_ENABLED` unset) -- no active financial exposure today for any item below, but treat items tagged HIGH/MEDIUM as touching a real live-order/live-money surface once trading is enabled.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. Pre-existing backlog item (`backlog.txt:20087`)

```
[OPEN 2026-08-18 -- split out of the BRIER_SCORE() CONDITION_TYPE FILTER
  entry above per its own opus review: needs new ticker-prefix-parsing
  logic paper trades have no equivalent of today, not a same-shape mirror
  of that fix] BRIER_SCORE()'S PAPER_TRADES.DB FALLBACK HAS NO
  CONDITION_TYPE FILTER, AND IS NOW MORE REACHABLE THAN BEFORE
Priority: Medium -- not exercised today (83 filtered tracker-DB rows
  exist, so the primary query never returns zero rows for
  graduation_check()'s actual call pattern), but no longer purely
  hypothetical: the sibling fix above means any future DB state where
  every settled multi-day prediction is an excluded condition_type now
  falls through to this completely unfiltered path instead of erroring or
  returning a filtered-but-smaller result.

Problem:
  tracker.brier_score()'s fallback path (paper.get_all_trades(), used when
  the primary tracker-DB query returns 0 rows) has no condition_type
  filter of any kind. Paper trade records carry no condition_type field at
  all -- only ticker and var -- unlike tracker-DB prediction rows, which
  store condition_type explicitly via log_prediction's analysis dict.
  Filtering this fallback correctly would require deriving condition type
  from the ticker string prefix (e.g. distinguishing KXRAIN*/KXBETWEEN*/
  KXDENSNOWM*-style tickers), a parsing mechanism that doesn't exist
  anywhere else for paper trades today. tests/test_tracker.py::
  TestBrierScoreConditionTypeFilter::
  test_when_every_settled_row_is_excluded_falls_through_to_unfiltered_paper_fallback
  pins the current (unfiltered) behavior with a real reproduction: an
  all-excluded tracker DB + one contaminated paper trade (entry_prob=0.9,
  outcome='no', error=0.81) produces brier_score()==0.81 with no filtering
  applied at all.

Why not now: needs its own scoped design decision (which ticker-prefix
  parsing scheme to use, whether to add it as a shared helper other paper-
  trade consumers could also use, whether var-based classification -- see
  paper.py's own KXHIGH*/KXLOW* ticker-prefix disambiguation logic used
  elsewhere -- is the right model to follow) rather than a same-shape
  mirror of the tracker-DB fix.
```

### 2. Pre-existing backlog item (`backlog.txt:20124`)

```
[OPEN 2026-08-18 -- split out of the BRIER_SCORE() CONDITION_TYPE FILTER
  entry above per its own opus review: a design decision about how to
  couple a hardcoded exclusion list to a live feature flag, not a
  same-shape mirror of that fix] BRIER-FAMILY CONDITION_TYPE EXCLUSION
  LIST HAS NO COUPLING TO RAIN/SNOW/HURRICANE GRADUATION GATES
Priority: Medium -- latent today (RAIN_TRADING_ENABLED unset per this
  worktree's env), but production is at 17 settled precip_month_total rows
  against weather_markets._rain_gates_active()'s 20-row graduation
  threshold -- close enough that this should be resolved before that flag
  flips, not discovered after.

Problem:
  count_settled_predictions()'s and (as of the entry above)
  brier_score()'s condition_type exclusion list
  ('between'/'precip_month_total'/'snow_month_total'/'hurricane_count'/
  'hurricane_next_event'/'storm_order') is a hardcoded tuple with no
  coupling to whether those market families are actually shadow-only or
  live. The moment RAIN_TRADING_ENABLED (or the equivalent snow/hurricane
  flag) flips, these functions will permanently exclude the calibration of
  a market family receiving real capital, with nothing to notice the
  mismatch or prompt a review. This is a pre-existing gap inherited from
  count_settled_predictions() (2026-07-30), but the entry above propagates
  it into the Brier VALUE that gates ALL live trading, not just a sample
  count -- a strictly larger blast radius once triggered.

Why not now: needs a real design decision (should the exclusion list read
  from the same flags that gate each market family's live-trading
  activation? should there be a startup/cron-time consistency check that
  alerts if an excluded condition_type's live-trading flag is enabled?) --
  a genuine judgment call for AskUserQuestion when picked up, not
  something to decide silently while fixing an unrelated Brier-score bug.
```

### 3. Pre-existing backlog item (`backlog.txt:20156`)

```
[OPEN 2026-08-18 -- split out of the BRIER_SCORE() CONDITION_TYPE FILTER
  entry above per its own opus review: unifying/extending filtering across
  the whole Brier family is real, separate, larger-scoped work] SEVERAL
  BRIER-FAMILY FUNCTIONS STILL HAVE NO CONDITION_TYPE FILTER --
  brier_score_rolling_with_n AND brier_score_rolling NOW DISAGREE
Priority: Low-Medium -- brier_score_rolling_with_n feeds real display
  paths (main.py, output_formatters.py, pdf_report.py, web_app.py) and
  get_brier_over_time feeds cron.py's operator-facing 2-consecutive-weeks
  Brier alert, but neither gates live-trading authorization the way
  graduation_check()'s brier_score() call does -- lower financial-safety
  stakes than the 2 entries above, still worth closing for calibration
  accuracy.

Problem:
  tracker.py's brier_score_rolling_with_n(), get_brier_over_time(),
  brier_score_by_method(), brier_score_by_method_rolling(), and
  brier_score_probation_rolling() have zero condition_type filtering.
  brier_score_probation_rolling() specifically gates auto-unretirement of
  a retired method. Concrete new inconsistency introduced by the entry
  above: brier_score_rolling(weeks=N) (a thin wrapper around the now-
  filtered brier_score(cutoff_days=N*7), no non-test callers) and
  brier_score_rolling_with_n(weeks=N) (unfiltered, real callers) are
  documented siblings over the identical window and will now return
  different numbers for the same inputs. Also: the exclusion tuple is now
  duplicated 9 times across the codebase (calibration.py x1, ml_bias.py
  x3, tracker.py x7, main.py x1 display-only) -- a pre-existing SNOW
  MARKETS backlog note (~2026-07-30, "STEP 2 HANDOFF NOTE") already
  flagged this as stale at "tracker.py (2 sites)"; it is 7 now.

Why not now: extending the exclusion to every Brier-family function is a
  genuinely larger, separate change (5+ functions, some with real
  operator-facing consumers whose historical values would shift) than the
  single targeted safety-gate fix above; count_settled_predictions()'s own
  docstring already explicitly defers this same unification as separate
  scope. Whoever picks this up should also consider whether the 9-times-
  duplicated exclusion tuple is worth extracting into one shared module-
  level constant at the same time, given the count keeps growing every
  time a new site needs the same list.
```

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

At least one item in this batch touches a live-order/live-money/safety-gate path (or is adjacent enough to warrant it) -- this batch does **not** qualify for the steps 11-12 LOW-tier downgrade. Apply the full ceremony as written, all 29 steps, for the batch as a whole.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
