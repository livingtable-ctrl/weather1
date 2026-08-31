# GATES — 20-pass audit of docs/HANDOFF-confidence-collapse-2026-08-30.md

The artifact under audit is a PROMPT: it will be pasted into a fresh session
with no access to this conversation. Its only value is that a stranger acting
on it reaches correct conclusions. Every gate below tests that property, not
whether the file reads well.

Scope: the handoff document only. No changes to backlog.txt, cron.py,
tracker.py, or the pre-registration.

- [ ] G1 — Every numeric claim in the document re-derives from the live DB.
      CHECK: python .unlazy/audit_handoff.py --numbers
      EXPECT: HANDOFF_NUMBERS_OK

- [ ] G2 — Every commit hash cited exists, and its date matches the claim.
      CHECK: python .unlazy/audit_handoff.py --commits
      EXPECT: HANDOFF_COMMITS_OK

- [ ] G3 — Every file/line/path citation resolves.
      CHECK: python .unlazy/audit_handoff.py --citations
      EXPECT: HANDOFF_CITATIONS_OK

- [ ] G4 — No internal contradictions: no section asserts something another
      section refutes (the known case: a stale "EMOS has the best mechanism
      story" surviving in NOT-established after EMOS was eliminated).
      CHECK: python .unlazy/audit_handoff.py --contradictions
      EXPECT: HANDOFF_NO_CONTRADICTIONS

- [ ] G5 — Every population/filter behind a quoted n is stated, and identical
      n values are not reused across different filters without saying so.
      CHECK: python .unlazy/audit_handoff.py --populations
      EXPECT: HANDOFF_POPULATIONS_OK

- [ ] G6 — The EMOS elimination does not rest on an unverified claim about
      the gate's threshold. Either the 40-row ens_var gate is confirmed in
      source, or the elimination is restated to not depend on it.
      CHECK: python .unlazy/audit_handoff.py --emos-gate
      EXPECT: HANDOFF_EMOS_GATE_OK

- [ ] G7 — The re-derivation instructions, executed literally as written by
      someone with no other context, reproduce the headline table.
      CHECK: python .unlazy/audit_handoff.py --rederive
      EXPECT: HANDOFF_REDERIVE_OK

- [ ] G8 — Manual: 20 distinct review passes completed, each with a stated
      lens and a recorded finding or explicit "nothing found". A pass that
      merely re-reads without a lens does not count.

- [ ] G9 — Manual: every issue found across the 20 passes is either fixed in
      the document or listed in the document as a known limitation. None is
      silently dropped.
