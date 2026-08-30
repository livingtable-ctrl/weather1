# Gates: option-5 forward-validation protocol + picks-shaped shadow log

OWNS: backlog.txt, tracker.py, cron.py, tests/test_price_recal_shadow_log.py

Scope: pre-commit the forward-validation protocol for the price-recalibration
rule into backlog.txt BEFORE any code, then build the shadow log that starts its
clock — a picks-shaped table written once per cron cycle, placing nothing.

- [ ] G1: The protocol is committed to backlog.txt in a commit that lands
      strictly before the first commit touching tracker.py or cron.py, so the
      pre-commitment is provable from git history rather than asserted.
  CHECK: python .unlazy/check_order.py
  EXPECT: GATE_G1_PASS
  EVIDENCE: pending

- [ ] G2: The protocol entry states all four things the brief demands — the
      per-pick log contents and decision rule, the multiple-testing haircut with
      all three located papers cited from a primary read, the derived minimum
      independent-observation floor, and the stopping/no-peeking rule.
  CHECK: python .unlazy/check_protocol.py
  EXPECT: GATE_G2_PASS
  EVIDENCE: pending

- [ ] G3: Every quantitative claim in the protocol re-derives from the live DB
      and from the CFTC-filed fee formula, to the stated precision. The checker
      recomputes each figure from source and compares against the text; it does
      not read a number out of the text and echo it back.
  CHECK: python .unlazy/check_numbers.py
  EXPECT: GATE_G3_PASS
  EVIDENCE: pending

- [ ] G4: The picks table is added by APPENDING to tracker._MIGRATIONS (never
      inserting mid-list, which would skip forever on every existing DB) and
      _SCHEMA_VERSION matches len(_MIGRATIONS).
  CHECK: python .unlazy/check_migration.py
  EXPECT: GATE_G4_PASS
  EVIDENCE: pending

- [ ] G5: The writer is shadow-only by construction: it performs no network I/O
      and reaches no order-placement path. Verified by call-graph walk from the
      writer over the repo's own AST, not by reading the docstring.
  CHECK: python .unlazy/check_shadow_only.py
  EXPECT: GATE_G5_PASS
  EVIDENCE: pending

- [ ] G6: The writer records the executable prices (yes_bid AND yes_ask) and the
      immutable pick-time snapshot, so the protocol's executable-price statistic
      is computable later. A mid-only row would silently re-run the discovery's
      own mid-price assumption.
  CHECK: python .unlazy/run_selected.py "executable or snapshot or book" 7 GATE_G6_PASS
  EXPECT: GATE_G6_PASS
  EVIDENCE: pending

- [ ] G7: The scoped test module passes end to end.
  CHECK: python .unlazy/run_scoped_tests.py
  EXPECT: GATE_G7_PASS
  EVIDENCE: pending

- [ ] G8: The tests are not vacuous: mutating each of the decision rule's guards
      and the shadow-only guard, one at a time, makes the scoped suite fail.
      A surviving mutant means the gate above certifies nothing.
  CHECK: python .unlazy/check_mutations.py
  EXPECT: GATE_G8_PASS
  EVIDENCE: pending

- [ ] G9: The repo's own pre-commit hook passes on the changed files (ruff +
      mypy as the repo configures them, not a bare local mypy).
  CHECK: python .unlazy/check_lint.py
  EXPECT: GATE_G9_PASS
  EVIDENCE: pending

- [ ] G10: The cron path actually writes rows: a driven cron cycle against a
      temporary DB produces picks-table rows, and a second identical cycle adds
      none (the dedup index holds).
  CHECK: python .unlazy/run_selected.py "cron or dedup or migration_runner" 4 GATE_G10_PASS
  EXPECT: GATE_G10_PASS
  EVIDENCE: pending

<!--
Runnable gates are repo-owned Python (portable; stock Windows has no grep/tail).
Every checker prints its own GATE_Gn_PASS token only after all its assertions
pass, and exits non-zero otherwise.

G3 is the anti-echo gate: it recomputes each figure from data/predictions.db and
the fee formula and asserts the text matches. It must never parse a number out
of backlog.txt and compare it to itself.

G5 is a negative/absence assertion. Its positive control is recorded in the
manual review: the checker is run against a deliberately-planted call to the
order-placement path and must FAIL before it is trusted to pass.
-->
