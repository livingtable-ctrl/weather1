# Gates: option-5 forward-validation protocol + picks-shaped shadow log

OWNS: backlog.txt, tracker.py, cron.py, tests/test_price_recal_shadow_log.py

Scope: pre-commit the forward-validation protocol for the price-recalibration
rule into backlog.txt BEFORE any code, then build the shadow log that starts its
clock — a picks-shaped table written once per cron cycle, placing nothing.

Verified 2026-08-30 on 3563cd31, python 3.14, Git Bash on win32.

- [x] G1: The protocol is committed to backlog.txt in a commit that lands
      strictly before the first commit touching tracker.py or cron.py, so the
      pre-commitment is provable from git history rather than asserted.
  CHECK: python .unlazy/check_order.py
  EXPECT: GATE_G1_PASS
  EVIDENCE: exit 0, matched. protocol commit 425fd7bd, first implementation
      commit 3563cd31, ancestry confirmed; the protocol commit touches neither
      tracker.py nor cron.py.

- [x] G2: The protocol entry states all four things the brief demands — the
      per-pick log contents and decision rule, the multiple-testing haircut with
      all three located papers cited from a primary read, the derived minimum
      independent-observation floor, and the stopping/no-peeking rule.
  CHECK: python .unlazy/check_protocol.py
  EXPECT: GATE_G2_PASS
  EVIDENCE: exit 0, matched. 404-line entry; all 9 per-pick fields, the frozen
      coefficients, all three papers each cited with a formula only a reader
      would have (T(y; phi(y)); p_BON = min(M*p_val,1); Z^-1[1-1/N]), N_KILL and
      its derivation, and all six no-peeking clauses present.

- [x] G3: Every quantitative claim in the protocol re-derives from the live DB
      and from the CFTC-filed fee formula, to the stated precision. The checker
      recomputes each figure from source and compares against the text; it does
      not read a number out of the text and echo it back.
  CHECK: python .unlazy/check_numbers.py
  EXPECT: GATE_G3_PASS
  EVIDENCE: exit 0, matched. Recomputed and matched: the 5-row haircut table,
      5 noise-floor values, both sample floors, the MDE identity at N_KILL, the
      futility power cost, the 60-day cross-reference, three fee figures, and
      the frozen coefficients against a refit of the entry's own population
      definition (drift in b = 0.00008 against a 0.01 tolerance; 670 rows, 642
      core, 442 city-day events, 1.45 rows/city-day).
      It caught two real errors in the entry before it passed — a retained
      power of 0.770 that recomputes to 0.796, and a 60-day MDE of +0.084 that
      recomputes to +0.074. Both were corrected in the text, not in the checker.

- [x] G4: The picks table is added by APPENDING to tracker._MIGRATIONS (never
      inserting mid-list, which would skip forever on every existing DB) and
      _SCHEMA_VERSION matches len(_MIGRATIONS).
  CHECK: python .unlazy/check_migration.py
  EXPECT: GATE_G4_PASS
  EVIDENCE: exit 0, matched. 84 statements on master are a byte-identical AST
      prefix of the 86 now; the 2 appended are the table and its unique index;
      _SCHEMA_VERSION 86 == len(_MIGRATIONS).

- [x] G5: The writer is shadow-only by construction: it performs no network I/O
      and reaches no order-placement path. Verified by call-graph walk from the
      writer over the repo's own AST, not by reading the docstring.
  CHECK: python .unlazy/check_shadow_only.py
  EXPECT: GATE_G5_PASS
  EVIDENCE: exit 0, matched. Call graph walked across cron, weather_markets,
      utils, positions, tracker; 18 unresolved calls, all builtins or sqlite3.
      POSITIVE CONTROL RAN IN THE SAME INVOCATION and tripped: with
      `place_order` planted in the writer the checker reports
      `cron._log_price_recal_picks -> place_order` and exits 1. The control is
      not a separate run whose result is asserted later.
      One earlier version of this checker flagged `dict.get` as an HTTP get;
      the fix narrowed transport detection to specific client methods plus
      attribute calls on known network receivers, and the control still trips.

- [x] G6: The writer records the executable prices (yes_bid AND yes_ask) and the
      immutable pick-time snapshot, so the protocol's executable-price statistic
      is computable later. A mid-only row would silently re-run the discovery's
      own mid-price assumption.
  CHECK: python .unlazy/run_selected.py "executable or snapshot or book" 7 GATE_G6_PASS
  EXPECT: GATE_G6_PASS
  EVIDENCE: exit 0, matched. 7 tests selected and passed, 29 deselected; the
      runner asserts the selection count so a -k expression that stops matching
      fails rather than passing on nothing.

- [x] G7: The scoped test set passes — the new module plus every existing module
      naming a symbol this change touches.
  CHECK: python .unlazy/run_scoped_tests.py
  EXPECT: GATE_G7_PASS
  EVIDENCE: exit 0, matched. 23 modules derived (not hand-listed) out of 202 in
      the suite; 2189 passed, 10 subtests passed, 154s. The runner fails if the
      derived set exceeds half the suite, so "scoped" cannot quietly become the
      full run.

- [x] G8: The tests are not vacuous: mutating each of the decision rule's guards
      and the settlement invariants, one at a time, makes the scoped suite fail.
      A surviving mutant means the gate above certifies nothing.
  CHECK: python .unlazy/check_mutations.py
  EXPECT: GATE_G8_PASS
  EVIDENCE: exit 0, matched. 12/12 mutants killed; baseline verified before and
      the revert verified after. Reverts are from in-memory original bytes in a
      finally block, never `git checkout --`, which would have destroyed the
      uncommitted work in this worktree.
      TWO MUTANTS SURVIVED ON THE FIRST RUN AND BOTH WERE CODE DEFECTS, not test
      gaps to paper over: a `has_quote` check strictly implied by the mid-range
      gate (removed), and `outcome IS NULL` duplicated across a SELECT and a
      per-row UPDATE (rewritten as one statement). A third surviving mutant —
      settlement admitting a non-binary settled_yes — was a genuine test gap and
      is now covered by seeding settled_yes = 2.

- [x] G9: The repo's own pre-commit hooks pass on the changed files (ruff,
      ruff-format, mypy as the repo configures them, not a bare local mypy).
  CHECK: python .unlazy/check_lint.py
  EXPECT: GATE_G9_PASS
  EVIDENCE: exit 0, matched. pre-commit 4.5.1 via `python -m pre_commit`;
      ruff Passed, ruff-format Passed, mypy Passed on cron.py, tracker.py and
      the new test module. The checker fails rather than falling back to a bare
      ruff/mypy if pre-commit is unavailable.

- [x] G10: The cron path actually writes rows: a driven cycle against a DB built
      by the real migration runner produces picks-table rows, and a second
      identical cycle adds none (the dedup index holds).
  CHECK: python .unlazy/run_selected.py "cron or dedup or migration_runner" 4 GATE_G10_PASS
  EXPECT: GATE_G10_PASS
  EVIDENCE: exit 0, matched. 6 tests selected and passed, 30 deselected,
      including a cycle driven against a DB built by tracker.init_db() rather
      than by the hand-picked DDL subset the other tests use.

<!--
Runnable gates are repo-owned Python (portable; stock Windows has no grep/tail).
Every checker prints its own GATE_Gn_PASS token only after all its assertions
pass, and exits non-zero otherwise.

G3 is the anti-echo gate: it recomputes each figure from data/predictions.db and
the fee formula and asserts the text matches. It never parses a number out of
backlog.txt to compare against itself. Its one tolerance (0.01 on the frozen
slope) is against a live table the cron appends to daily; drift past it is a
real finding, not flakiness, and the observed drift prints either way.

G5 is a negative assertion and carries its positive control inside the same
invocation that passes the gate, rather than as a separate --self-test whose
result is asserted by hand.

NOT COVERED BY ANY GATE, recorded so it is not mistaken for verified:
  * No cron cycle has run in production yet, so the first real row count and the
    real forward pick rate are unmeasured. The protocol's 6.39 picks/day is an
    in-sample projection; the log exists to replace it.
  * The bid/ask distribution on these books is unmeasured. That is the point of
    storing both sides, not a claim about them.
-->
