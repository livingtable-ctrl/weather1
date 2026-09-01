# Gates: schedule `cron --sameday-only`, and the June->July window investigation

OWNS: main.py, tests/test_cmd_schedule_sameday.py,
tests/test_cmd_schedule_settlement_monitor.py,
docs/HANDOFF-confidence-collapse-2026-08-30.md, .unlazy/probe_july_window.py,
.unlazy/audit_handoff.py, backlog.txt, BACKLOG_OPEN.md

Scope: (1) make `py main.py schedule` register two daily Windows tasks running
`cron --sameday-only` at **05:10 and 23:10 UTC**; (2) identify what changed
between 2026-06-30 03:34 and 2026-07-02 19:07, or say plainly that it did not
resolve.

The times were 06:10/22:10 through round 1. The operator approved the move to
05:10/23:10 after review showed 06:10 misses Denver outright and 22:10 clears
the Pacific gate by ~17 minutes. NOTHING WAS REGISTERED ON ANY MACHINE in this
session, so no orphaned `_06UTC`/`_22UTC` task can exist anywhere; the operator
will run `py main.py schedule` fresh on a dedicated always-on host.

All figures below are from the run that produced this text.

- [x] G1: The handoff's figures still hold against the current DB.
  CHECK: python .unlazy/audit_handoff.py --all
  EXPECT: HANDOFF_JULY_WINDOW_OK
  EVIDENCE: exit 0. **15** checks now, not 14: the July-window probe was
      ORPHANED when written -- it ran from nowhere, and a corrupted figure
      (`89 of 205`) in the new section passed all fourteen others, including
      `--contradictions`, which never noticed 89/205 is not 44.9%. Registering
      it in `CHECKS` is the fix. The doc's stale "16 checks" prose is corrected
      to 15 and now names the probe.

- [x] G2: `cmd_schedule()` registers exactly two `cron --sameday-only` tasks at
      the host-local wall times for 05:10 and 23:10 UTC.
  CHECK: python -m pytest tests/test_cmd_schedule_sameday.py -q --no-header
  EXPECT: 13 passed
  EVIDENCE: 13 passed. Driven under a frozen clock in New_York (summer AND
      winter), Los_Angeles, Denver and Europe/London. Expected times are
      re-derived via `astimezone()`, an independent route from the
      implementation's `fromtimestamp()`; the UTC targets live in one constant
      used by both the expectation and the task names, so changing one alone
      fails.

- [x] G3: The new tasks do NOT advance `last_full_scan`, so the "last FULL cron
      scan" warning still fires.
  CHECK: python -m pytest "tests/test_cron_integration.py::TestSamedayOnlyFullScanStaleness" tests/test_sameday_only.py -q --no-header
  EXPECT: 19 passed
  EVIDENCE: 19 passed. Verified rather than duplicated: the behaviour was
      already covered, including `test_full_scan_gap_alert_fires_with_distinct_
      cooldown_key` (the cron.py ~2061 alert this task asked about) and its
      positive control. Enforced by `if sameday_only or not _full_scan:`.

- [x] G4: Scoped regression suite over every touched file is green.
  CHECK: python -m pytest tests/test_cmd_schedule_sameday.py tests/test_cmd_schedule_settlement_monitor.py tests/test_cmd_schedule_cycles.py -q --no-header
  EXPECT: 27 passed
  EVIDENCE: 27 passed, counted at the moment of writing this line. The wider
      sweep including the two cron files is 46 passed.

- [x] G5: Lint and types pass via the repo's own pre-commit hooks.
  CHECK: python -m pre_commit run --files main.py tests/test_cmd_schedule_sameday.py tests/test_cmd_schedule_settlement_monitor.py .unlazy/probe_july_window.py .unlazy/audit_handoff.py
  EXPECT: mypy.....................................................................Passed
  EVIDENCE: ruff, ruff-format and mypy all Passed. Run AFTER the final edit,
      not carried forward -- an earlier green run was invalidated twice by
      later edits. mypy caught a real `var-annotated` gap in the probe that
      round 2 could not check (it declined to run pre-commit because its
      hooks rewrite files while another agent was editing the tree).

- [x] G6: The new tests are not vacuous.
  EVIDENCE: NINE mutations, each applied with the Edit tool (which fails loudly
      on a mismatch) and reverted immediately; `grep MUTATION main.py` is clean
      and `git diff --stat` shows only intended changes.
        M1 drop `--sameday-only`                 -> 1 failed
        M2 skip the UTC->local conversion        -> 4 failed
        M3 `continue` -> `return` on decline     -> 1 failed
        M4 nest under settlement_duration        -> 1 failed
        M5 register only one of the two times    -> 7 failed
        M9 minute 10 -> 30                       -> 4 failed
      Plus the four that SURVIVED round 1 and were only killed after round 2
      wrote assertions for them:
        M-K warning threshold `<6` (stale after the time change) -> 2 failed,
            precisely on the Los_Angeles and Denver cases
        M-G drop `.strip().lower()`              -> 1 failed
        M-D failure branch -> `pass` (swallowed) -> 1 failed
        `/mo 2` appended AFTER `/ST`             -> 1 failed
      HONEST LIMIT, unchanged: the four timezone cases prove the conversion is
      host-correct and not hardcoded, but under a frozen clock the winter
      New_York case does not by itself separate "localize the target instant"
      from "snapshot the current offset". That DST-transition property is
      covered for the same helper in test_cmd_schedule_settlement_monitor.py,
      not here.

- [x] G7: Independent opus review at effort:high, every finding resolved or
      explicitly dispositioned.
  EVIDENCE: THREE reviews ran (two scopes in round 1, one on the fixes in
      round 2), after an initial attempt was blocked by a rate-limited
      classifier and retried rather than skipped.
      Round 1 / code: 5 MEDIUM + 7 LOW + 4 INFO. All fixed except the two time
      recommendations, which were escalated to the operator and approved.
      Round 1 / analysis: 27 findings. See G8.
      Round 2 / fixes: 1 HIGH + 4 MEDIUM + 3 LOW. All fixed. It found a bug the
      round-1 fix INTRODUCED -- the overnight-warning threshold `< 6` was
      calibrated for 06:10 UTC and silently stopped firing for Mountain and
      Pacific hosts once the task moved to 05:10, i.e. exactly the hosts that
      task exists to serve. That is the case for the rule that a fix needs its
      own review.
      Round 2 disclosed it could NOT run mypy (it declined to let pre-commit
      rewrite files mid-session). Treated as unverified and run here -- it
      failed, and the failure was real. See G5.

- [x] G8: TASK 2 resolves to a named mechanism with a discriminating
      measurement, stratified, without pooling May-August.
  CHECK: python .unlazy/probe_july_window.py
  EXPECT: JULY_WINDOW_PROBE_OK
  EVIDENCE: exit 0. THE ANSWER CHANGED SHAPE UNDER REVIEW AND THE DOCUMENT NOW
      SAYS SO. What is established: the window is an artefact of the population
      its endpoints were drawn from, and the corpus change has a commit --
      `e395392b` (2026-06-25), a local-date guard that killed the METAR lock's
      `between` branch. Its last fire is 2026-06-25; above/below keep firing to
      07-31. What is NOT established: that this explains the AUC gap. A
      size-matched random-removal null gives one-sided **p = 0.062** (20,000
      draws, my own derivation; the reviewer independently got 0.065), a
      discrimination-matched null gives **p = 0.361**, and METAR rows are not
      significantly better than the rows they were pooled with (z = +1.16).
      Three of my own claims were FALSE and are retracted in the document: "no
      commit is involved"; "reads an already-observed extreme off a thermometer
      and is not a forecast at all" (median |observed_extreme - settled| is
      8.94F over 106 rows, with ZERO exact matches); and the
      `get_historical_sigma` month-key mechanism (`_load_dynamic_sigma` did not
      exist during the window).
      The probe gates 5 things and mutation-tests clean: editing `+0.0920` to
      `+0.1300` in the doc yields `FAIL: gap without METAR`, exit 1, and the doc
      is restored byte-identically. Both absence checks carry positive controls.

- [x] G9: The four already-eliminated suspects were not re-derived, and any
      claim contradicting one is stated as a contradiction.
  EVIDENCE: None of EMOS, `d5a6440f`, TRADING_PAUSED selection, or the
      obs-blend loss was re-measured. Relationships stated rather than glossed:
      distinct from TRADING_PAUSED in May-June (where every row is traded, so
      the METAR contrast is orthogonal to trading selection) but NOT
      independent of it in July-August (all 17 July-August METAR rows are
      untraded shadow rows); and corroborating on obs, whose rising share
      9.6% -> 46.2% is the consequence of METAR leaving, not a cause.

## Handoffs — open, not silently dropped

- **The residual is unresolved and the document says so.** A +0.0920 gap
  (z=+1.25) survives removing the METAR rows; every cluster bootstrap CI
  includes zero. The corpus must grow before this is answerable.
- **UNEXAMINED CONFOUND surfaced and recorded, not chased:** `4ccbeb28`
  (2026-07-12) switched sigma from the static seasonal table to dynamic
  per-month values, several floored at 1.5F -- a commit-driven sigma change
  landing INSIDE the July-August period the document treats as homogeneous.
- **Why the above/below lock-in branches thinned is UNMEASURED.** `e395392b`
  does not explain it. The unscheduled-sameday mechanism this change fixes is
  plausible but was not demonstrated, and cannot be from this corpus: all 106
  lock-in rows carry `local_hour` NULL, and `predicted_at` is pinned to the
  day's FIRST scan by the `ON CONFLICT(ticker, predicted_date)` upsert while
  `method` is overwritten by the last, so hour-of-day attribution is unsafe.
  Day- and month-level attribution ARE safe (0 of 618 rows disagree).
- **The backlog entry's "20-22h UTC window: 5 scans -> 4 locks" is unsafe to
  cite** for that reason; the resolution note says so in place.
- Not committed. Awaiting the operator's go-ahead.
