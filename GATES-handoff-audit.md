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


## STATUS 2026-08-30 — honest close

G1-G7 were written as runnable oracles calling `.unlazy/audit_handoff.py`.
**That script was never written.** The verification was performed ad hoc in
the session instead: live SQL against data/predictions.db, `git log -1` per
cited hash, `sed -n` per cited line, and direct inspection of data/ and
data/.history/. The evidence is real but it is NOT reproducible by running
this ledger, which is what a runnable gate is supposed to guarantee.

Therefore, by this ledger's own rule ("a checked box with missing or pending
evidence is unmet"):

- G1 numbers        — UNMET AS DECLARED. Verified ad hoc; every figure in the
                      document was re-derived, and three were wrong (see G9).
- G2 commits        — MET IN SUBSTANCE. All 7 cited hashes exist with matching
                      dates. Not run through the declared oracle.
- G3 citations      — UNMET. 3 of 4 verified (cron.py:2218, backlog L9854,
                      tracker.py ~4930). One claim FAILED: the artefact
                      data/emos_params.json.premature_do_not_use_20260704 does
                      not exist. Fixed in the document.
- G4 contradictions — MET IN SUBSTANCE. Four stale/contradictory passages found
                      and removed; a scan confirms none remain.
- G5 populations    — MET IN SUBSTANCE. June n=48 vs n=44 reconciled and stated.
- G6 EMOS gate      — MET. The 40-row gate is real (cron.py:2218) but counts
                      ens_mean, not ens_var; the elimination was rewritten to
                      rest on EMOS never having been activated instead.
- G7 re-derive      — UNMET. The document's re-derivation instructions were not
                      executed literally by a naive reader. Untested.
- G8 20 passes      — MET. 20 distinct lenses, listed in the session report.
- G9 issues handled — MET. 12 issues found; all fixed in the document or
                      recorded there as an explicit limitation.

HANDOFF REQUIRED: G1, G3 and G7 are unmet as declared. Anyone re-running this
audit should write `.unlazy/audit_handoff.py` so the checks are reproducible
rather than trusting this session's transcript.


## PASS 2 — 2026-08-30, second 20-pass audit

The HANDOFF REQUIRED from pass 1 is DISCHARGED: `.unlazy/audit_handoff.py`
now exists and implements G1-G7 as real oracles. Re-running the ledger
reproduces the checks instead of trusting a transcript.

    python .unlazy/audit_handoff.py --all
    -> HANDOFF_NUMBERS_OK / _COMMITS_OK / _CITATIONS_OK
       / _NO_CONTRADICTIONS / _POPULATIONS_OK / _REDERIVE_OK

- G1 numbers        — MET (runnable). Caught one real defect: the doc claimed
                      n_members "constant 238 from 2026-06-20 through August".
                      False — August carries 208/258/2427/2438. July IS
                      uniformly 238 across all 56 rows, so the conclusion held
                      but the claim was overstated from a truncated view.
- G2 commits        — MET (runnable). All cited hashes exist with matching dates.
- G3 citations      — MET (runnable). One failure was a defect in the CHECKER
                      (regex dropped the `tests/` prefix), not the document.
- G4 contradictions — MET (runnable). Found 2 stale headings surviving prior
                      retractions, then 2 more stale passages by hand; the
                      stale-phrase list now covers all of them.
- G5 populations    — MET (runnable).
- G6 EMOS gate      — MET (carried from pass 1).
- G7 re-derive      — MET (runnable). The document's own recipe reproduces its
                      headline confidence table.
- G8 20 passes      — MET. Lenses: structure, oracle authoring, each of the six
                      runnable checks, n_members depth, four stale-section
                      reads, oracle extension, injection hygiene,
                      self-containment, table validity, duplication,
                      actionability, retraction hygiene.
- G9 issues handled — MET. 9 issues this pass, all fixed in the document.

ISSUES FOUND, PASS 2:
 1. n_members "constant 238" — false outside July.
 2. Stale heading "CONFIRMED LIVE DEFECT: the temperature ratchet, visible in
    the snapshots" — the ratchet had been retracted.
 3. Stale heading "THE LEADING HYPOTHESIS: temperature scaling" — ruled out on
    mathematics once the headline became AUC.
 4. Retracted conclusion still asserted flatly ("So no calibration stage is
    degrading anything") inside the superseded block.
 5. Stale "a live, ratcheting T-scaling defect ... now confirmed with data".
 6. Stale heading "Finding 2 — what actually happened".
 7. **LOGICAL ERROR**: "that explains the accuracy drop". Compression toward
    0.5 is monotone and cannot move a prediction across the threshold, so it
    leaves accuracy EXACTLY unchanged. Corrected in place.
 8. Two "in this session" references, unresolvable for a stranger.
 9. Checker regex dropped directory prefixes (my defect, not the doc's).

STANDING LIMITATION, not a gate failure: the oracle's expected values are
taken FROM the document, so it proves doc-versus-database consistency and
arithmetic, not that a premise is true. It cannot catch a wrong idea that is
internally consistent. Only the manual passes can, and they are not
reproducible.


## PASS 3 — hardening, 2026-08-30

The question was whether the prompt could be hardened further. It could, and
the answer was found by attacking my own gates rather than the document.

MUTATION TESTING THE ORACLE (`.unlazy/mutate_handoff_oracle.py`). Nine
mutations injected into the handoff in memory, restored from an in-memory
snapshot (never `git checkout --`, which would discard unrelated work).

FIRST RUN: **5 of 9 mutants SURVIVED.** `--numbers` and `--rederive` were
VACUOUS with respect to the document. They held their own hardcoded copies of
every figure and compared those to the database, so the gate proved "the DB
says X" and never "the document says what the DB says". Four figures in the
text could be changed to anything and the ledger still reported green. Pass 2
reported G1 and G7 as "MET (runnable)"; that claim was misleading and is
corrected here.

FIX: every expectation is now PARSED OUT OF THE DOCUMENT and compared against
a freshly derived value, so editing a figure in the text fails the gate.

A SECOND DEFECT SURFACED WHILE FIXING THE FIRST: the initial doc-parsing
regexes were unscoped and matched the HEADLINE AUC table when looking for the
traded-subset and forecast-error tables — comparing real derivations against
the wrong quoted numbers. Added `_section()` so every pattern is scoped to its
own block.

SECOND RUN: **all 9 mutants killed.** The gates can now fail honestly.

- G1 numbers        — MET, and now non-vacuous (proven by mutation).
- G7 re-derive      — MET, and now non-vacuous (proven by mutation).
- G3 citations      — MET; both a bogus line number and a bogus filename are
                      caught.
- G4 contradictions — MET; re-injecting two retracted phrases is caught.
- G9 lint           — GATE_G9_PASS after fixing 4 mypy findings and running
                      ruff format. NOTE pass 2 pushed this file lint-failing
                      because `check_lint.py` was piped through `tail`, so the
                      shell chain continued on tail's exit status.

REMAINING, NOT DONE — the honest ceiling on this ledger:
 1. The oracle proves internal consistency and arithmetic. It cannot catch an
    internally consistent WRONG IDEA. Only the manual passes can, and those
    are not reproducible.
 2. The headline AUC finding rests on a parametric Hanley-McNeil SE. A
    bootstrap or permutation test of the May-Jun minus Jul-Aug difference
    would be stronger and has NOT been run.
 3. Population drift by city and ladder width across the July boundary is
    still unchecked. The traded-subset test refutes the SELECTION confound but
    not a change in the market MIX.


## PASS 4 — hardening round 2, 2026-08-30

Attacked the two gaps pass 3 recorded as NOT DONE. Both closed, and the
headline finding did not survive either one.

### G10 — population drift by condition type and family  [MET, and it FIRED]
    CHECK: python .unlazy/audit_handoff.py --numbers   (strata table gated)
The confound pass 3 listed as unchecked is REAL and large. `between` markets
are 55.6% of May-June and 2.8% of July-August. Family drifted too (KXHIGH
65.7% -> 45.5%). Ladder width did not (2.00F both periods).
Stratified AUC shows the model's May-June skill lived in `between` (n=110,
0.6378) and `above` (n=52, 0.6989), and that it NEVER discriminated on
`below` (0.5444, z=+0.39) even at its best. Within `above` the drop is
0.6989 -> 0.5786 at z about 1.27 — NOT significant. The pooled z=+2.46 is
therefore substantially a mix effect.

### G11 — bootstrap the surviving claim  [MET, and it FIRED]
    CHECK: python .unlazy/did_bootstrap.py
    EXPECT: a 95% CI on the difference-in-differences
The one claim that survived G10 was that the market rose within the same
strata where the model fell, which composition cannot produce. Measured as a
difference-in-differences, cluster-bootstrapped by ticker, 2000 resamples:
observed +0.1373, 95% CI [-0.0794, +0.3446], p about 0.21. **CI includes
zero.** Not established.

### Consequence
The document's headline was rewritten for the third time. It now reads
"DIRECTION CONSISTENT, SIGNIFICANCE NOT ESTABLISHED" and explicitly says not
to present "the model broke in July" as a finding. Every measurement points
the same way and none reaches significance once the confound is handled and
clustering respected.

### What hardening actually bought
Pass 3 hardened the ORACLE and found my gates were vacuous. Pass 4 hardened
the FINDING and found it was not established. In both cases the hardening
attacked my own work rather than the document's prose, and in both cases that
is where the defect was.

### REMAINING, NOT DONE
 1. The oracle still cannot catch an internally consistent wrong idea. Two
    passes of manual review are what caught the composition confound, and
    manual review is not reproducible.
 2. `between` has n=4 in the later period, so the stratum where the model
    actually had skill CANNOT be compared across the boundary with this
    corpus. No amount of analysis fixes that; it needs more data.
 3. Claim coverage is unmeasured: nobody has counted what fraction of the
    document's assertions have any gate at all. The gated set was chosen by
    me, which is the same selection problem the document itself is about.


## PASS 5 — claim coverage, measured by mutation, 2026-08-30

Pass 4 recorded that claim coverage was unmeasured and that the gated set had
been chosen by the same person who wrote the document. That is the selection
problem the document itself is about, so it was measured rather than argued.

METHOD (`.unlazy/coverage_handoff.py`): coverage is defined by MUTATION, not
inspection. Perturb one number in the document, run the full oracle, and see
whether anything fails. If nothing fails, that claim is ungated — the ledger
would certify the document with that figure wrong. The doc is restored from an
in-memory snapshot after every mutation and asserted byte-identical at the end.

    FIRST MEASUREMENT:  43 / 310 gated  =  13.9%
    AFTER THIS PASS:    90 / 310 gated  =  29.0%

WHAT THE FIRST MEASUREMENT EXPOSED: the two findings added by the PREVIOUS
hardening pass — the composition-drift table and the stratified AUC table —
were entirely ungated, as was every z-value in the document including the
+2.46 that the headline rested on. A finding added without a gate is a finding
the ledger will certify wrong.

GATES ADDED:
- `--strata` (HANDOFF_STRATA_OK): the composition table, the stratified AUC
  table including its z column, and the pooled-AUC sentence with its z.
- headline z column and the model difference-in-differences sentence, folded
  into `--numbers`.
- `--restatements` (HANDOFF_RESTATEMENTS_OK): prose that repeats a gated
  figure must agree with a freshly derived value, plus the family-drift
  percentages. This closes a failure mode the sweep revealed — editing only
  the prose copy of a number left the ledger green while the document
  contradicted itself.

All 8 checks pass, all 9 mutants still die, G9 lint passes.

### WHY 29% IS NOT A FAILING GRADE, AND WHY IT IS NOT A GOOD ONE EITHER
Of the 220 still-ungated tokens, a large share are not claims: the constant
`0.5` used to define the null, `0.50` in table headers, and figures that
merely restate a gated table value in prose. The gates now cover every number
the headline argument depends on. But the exact split between "prose" and
"genuine ungated claim" HAS NOT BEEN COUNTED, so 29% is a floor on coverage
and not a characterisation of what remains.

### REMAINING, NOT DONE
 1. The prose/claim split in the 220 ungated tokens is uncounted (above).
 2. NON-numeric claims are entirely ungated. Every causal and eliminative
    sentence — "the bug lost money", "EMOS was never active", "the defect is
    downstream of the forecast" — has no oracle at all. Mutation coverage
    measures arithmetic, not reasoning.
 3. The `between` stratum still has n=4 in the later period, so the one place
    the model had skill cannot be compared across the boundary at all.


## PASS 6 — the prose/claim split, counted, 2026-08-30

Pass 5 said 29% coverage was "a floor, not a grade" and speculated that much
of the remainder was prose. **That speculation was wrong and is retracted.**

Classified mechanically. The only judgement is the PROSE rule, stated so it
can be argued with: a token counts as prose ONLY if it is the literal 0.5/0.50
null reference or a table header cell — it asserts nothing about this corpus.
RESTATED means the identical value is gated elsewhere. GENUINE means a factual
claim about this corpus that no gate reacts to.

    FIRST COUNT (at 29.0% coverage, 220 ungated):
      PROSE      4   (1.8%)
      RESTATED  51  (23.2%)
      GENUINE  165  (75.0%)

So three quarters of the ungated set were real assertions, not prose. Coverage
of GENUINE claims specifically was 90 / (90+165) = **35.3%**, not 29% of a
mostly-decorative remainder. Among the ungated were the document's own
bootstrap CI, the market's per-stratum AUCs carrying the "what survives
composition" argument, the live temperature_scale values carrying the
self-training section, the ens_var medians, and the raw_prob difference table.

GATE ADDED: `--market-strata` (HANDOFF_MARKET_STRATA_OK) covers the market's
per-stratum AUCs and the live `data/temperature_scale.json` T and n values.

    AFTER (9 checks):
      PROSE      4   (1.9%)
      RESTATED  56  (26.7%)
      GENUINE  150  (71.4%)

All 9 checks pass, all 9 mutants die, lint passes.

### THE HONEST STATE
150 genuine numeric claims still have no oracle. The largest clusters are the
forecast-error mean/p90 columns, the n_members detail, the sigma-field
medians, and the bootstrap CI. None is load-bearing for the headline, which is
now fully gated — but "not load-bearing" is my judgement, not a measurement,
and it is exactly the kind of judgement this pass just caught me getting wrong.

### REMAINING, NOT DONE
 1. 150 genuine ungated numeric claims (above).
 2. The bootstrap CI is deterministic under its fixed seed and COULD be gated;
    it is not, because the check would take ~30s inside `--all`.
 3. NON-numeric claims remain entirely ungated. Every causal and eliminative
    sentence has no oracle. This is the largest hole and mutation coverage
    cannot reach it.


## PASS 7 — the three remaining items, discharged, 2026-08-30

All three of pass 6's NOT DONE entries are closed. New module
`.unlazy/audit_handoff_ext.py`; the oracle now has 12 checks and runs in 0.94s.

### (1) The 150 genuine ungated numeric claims -> `--tables`
Gating figures one at a time does not scale; `check_tables` derives WHOLE
tables instead — the forecast-error mean/p90 columns, the our_prob-vs-raw_prob
magnitude table, the n_members August detail, and the temperature_scale
history snapshots read back off disk.

### (2) The bootstrap CI -> `--bootstrap`
Was gateable but "too slow at ~30s". That was an implementation problem, not a
fact: the O(n^2) AUC was replaced with a rank-based Mann-Whitney form, so 2000
cluster resamples now run inside a 0.94s full-suite pass. The gate reproduces
the observed DiD, the CI bounds, AND asserts the CI still includes zero — so
if the data ever moves enough to make the divergence significant, the gate
fails and forces the document to be rewritten rather than quietly going stale.

### (3) Non-numeric claims -> `--assertions`  ** the interesting one **
Pass 6 called this unreachable by mutation coverage. It is unreachable by
MUTATION, but not ungateable: every causal and eliminative sentence has a truth
condition, and writing it down makes it testable. Ten claims are now gated,
each requiring BOTH that the document still makes the claim AND that the data
supports it — a claim silently deleted fails the gate just as a refuted one
does. Covered: EMOS was never active; the forecast halved its error; AUC is
calibration-invariant; compression leaves accuracy unchanged; the market did
not fall in any stratum; the model never discriminated on `below`; the
raw_prob deltas are rounding noise; July n_members is single-valued; `between`
is unmeasurably small later; the fitter reads `our_prob`.

### THE GATE IMMEDIATELY EARNED ITSELF
Writing the AUC-invariance claim as an executable assertion REFUTED the
document's wording. The invariance is exact in real arithmetic and exact in
float64 at most temperatures (delta 0.0 at T=2 and T=10) but NOT all: at
T=4.6 three of 303 distinct stored probabilities round together, creating ties
worth 3.4e-05 of AUC. The claim survives at that magnitude; the word "EXACTLY"
does not. Recorded in the document as a precision caveat. **A qualitative
claim that had been asserted three times in this session, and stated as
"by construction", was wrong in its literal form the first time it was
executed.**

### MEASURED
    coverage    121 / 314 gated = 38.5%   (was 100/310 = 32.3%)
    ungated     PROSE 4 (2.1%) | RESTATED 60 (31.1%) | GENUINE 129 (66.8%)
    genuine-claim coverage = 121 / 250 = 48.4%   (was 35.3%)
All 12 checks pass, all 9 mutants still die, G9 lint passes.

### REMAINING, NOT DONE
 1. 129 genuine ungated numeric claims remain. The count is falling
    (165 -> 150 -> 129) but table-level gating has taken the cheap wins.
 2. `--tables` skips rows whose formatting does not match its patterns
    (scientific-notation cells, untabulated snapshots) via `continue`. Those
    silent skips are not counted or reported, so the gate's own coverage of
    the tables it claims is unmeasured.
 3. The assertion list was written by me from my own document. A claim I never
    thought to gate is still ungated, and nothing measures that omission — the
    same selection problem, one level up.


## PASS 8 — the last three, 2026-08-30

### (2) `--tables` silent skips  [CLOSED]
Every `continue` is now an accounted skip, reported in the failure text, plus
a VACUITY FLOOR: fewer than 8 rows actually checked is itself a failure. On
the current document skips = 0 and checked > 8, so `--tables` was NOT vacuous
— but it could have become so silently, which is how `--numbers` failed
before.

### (3) "the assertion list was written by me"  [MEASURED, not closed]
New tool `.unlazy/prose_coverage.py`. Mutation cannot measure prose — changing
a sentence with no number in it moves nothing an oracle reads — so this
extracts sentences carrying an assertive marker and reports which have no
matching `--assertions` entry. Extraction over-collects on purpose: a claim
wrongly listed as ungated costs a moment, one wrongly omitted is the failure
being measured.

    PROSE CLAIMS DETECTED  93
      matched by a gate     4  (4.3%)
      UNGATED              89  (95.7%)

**THE TOOL WAS ITSELF VACUOUS ON FIRST RUN** and reported 0.0%. Its extractor
required the literal `(r"` sequence, which stopped matching the moment ruff
format split the CLAIMS tuples across lines. A measurement instrument can be
vacuous exactly like a gate. It now refuses to print a coverage number at all
if it extracts zero patterns, rather than reporting a confident 0%.

**AND IT IMMEDIATELY FOUND WHAT IT WAS BUILT TO FIND.** Two conclusions in the
headline's own summary list still read "The model specifically broke." and
"**This is a REGRESSION, not a limitation.**" — flatly contradicting the
corrected headline, which says not to present that as established. The
`--contradictions` gate missed them because that gate only knows the stale
phrases I thought to write down. Both are now withdrawn in the document,
rewritten as conditional, and added to the stale list.

### (1) 129 genuine ungated numeric claims  [PARTIAL]
Numeric coverage is 121/315 = 38.4%, genuine-claim coverage 48.2%. The count
moved 165 -> 150 -> 129 -> 130 across passes; it is no longer falling, because
table-level gating has taken every cheap win and what remains is
one-off figures scattered through prose.

All 12 checks pass, all 9 mutants die, G9 lint passes.

### THE STANDING RESULT, stated plainly
    numeric claims : 38.4% gated
    prose claims   : 4.3% gated
The document's ARITHMETIC is now well guarded. Its REASONING is almost
entirely unguarded, and the gap between those two numbers is the honest
summary of what this ledger can and cannot promise.

### REMAINING, NOT DONE
 1. 89 ungated prose claims. Each needs a hand-written truth condition; there
    is no mechanical route.
 2. 130 genuine ungated numeric claims, now mostly one-off figures in prose.
 3. `prose_coverage.py`'s ASSERTIVE/NON_CLAIM regexes were written by me and
    decide what counts as a claim at all. A claim phrased outside those
    markers is invisible to the measurement. This is the same selection
    problem displaced one further level, and it is not resolvable by adding
    another tool written by the same author.


## PASS 9 — prose claims given truth conditions, 2026-08-30

Pass 8 measured prose coverage at 4.3% and said closing it had no mechanical
route: each sentence needs a truth condition written by hand. Written.

New module `.unlazy/audit_handoff_prose.py`, gate `--prose`
(HANDOFF_PROSE_OK), 15 claims, each requiring BOTH that the document still
makes the claim AND that the evidence supports it. Grouped by what settles
them: the database (9), files on disk (2), repository source (2), and a
mathematical property demonstrated on this corpus (1).

    prose coverage  4.3%  ->  15.1%   (14 of 93 sentences matched)

### TWO FAILURES ON FIRST RUN, both real

1. **"Brier improved over the same span" is TRUE ONLY FOR THE ENSEMBLE.**
   Scoped to `method='ensemble'` it holds (0.2688 -> 0.2470). Pooled across
   ALL methods it is FALSE — Brier slightly WORSENS (0.2653 -> 0.2670).
   The sentence sits beside an ensemble-only table so ensemble is the right
   population, but the unscoped reading a stranger would take is wrong. The
   scope is now stated in the document.
2. **The backlog quote could not be found.** "sameday/hourly were never
   frozen" is presented as verbatim and a literal search failed, because
   backlog.txt hard-wraps and the phrase spans a line break. The gate now
   collapses whitespace before comparing. The quote IS faithful; the check
   was naive.

### AND THE MEASUREMENT TOOL WAS WRONG AGAIN
`prose_coverage.py` read claims from ONE module. After 15 gates were added in
a second module it still reported 4.3%, crediting no improvement. Fixed to
scan every registered gate module, with the module list documented as
load-bearing. This is the SECOND time this tool has silently under-reported —
it previously returned a confident 0.0% because ruff format moved a bracket.
A measurement instrument needs the same suspicion as a gate.

13 checks pass, all 9 mutants die, G9 lint passes.

### THE STANDING RESULT
    numeric claims : 38.4% gated
    prose claims   : 15.1% gated

### REMAINING, NOT DONE
 1. 79 ungated prose sentences. Roughly half are meta-commentary about the
    document's own revision history ("an earlier draft said X"), which is
    checkable only against the document, not against evidence — gating those
    would test nothing. The remainder are genuine and would each need a
    hand-written condition.
 2. 130 genuine ungated numeric claims.
 3. `prose_coverage.py`'s ASSERTIVE/NON_CLAIM regexes still decide what counts
    as a claim, and were written by me. A claim phrased outside those markers
    is invisible to the count. Unresolved and probably unresolvable from
    inside.


## PASS 10 — the rest of the prose claims, 2026-08-30

    prose coverage  15.1%  ->  33.3%   (31 of 93 sentences)
    ungated split   META 14 | EVIDENTIAL 48   (was 63 evidential)

### Two measurement defects fixed BEFORE adding gates
1. **Span matching.** `prose_coverage.py` matched gate regexes against one
   extracted sentence at a time, but several gates deliberately span a line
   break because the document hard-wraps. Those could never match and their
   claims were counted ungated. Patterns are now matched against the whole
   document and mapped back to line numbers. This alone moved 15.1% -> 17.2%
   with no new gates: the tool had been under-reporting.
2. **META vs EVIDENTIAL split, MEASURED.** Pass 9 guessed "roughly half" of
   the ungated set was meta-commentary. Wrong again: it is **14 of 77 (18%)**.
   A META sentence describes this document's own revision history and is
   checkable only against the document, so gating it would test nothing.
   Everything else is evidential and can carry a truth condition.

### 15 new conditions, `--prose2` (HANDOFF_PROSE2_OK)
Composition (3), the eliminations (7), T-scaling (4), and one mathematical
property. Notable ones are exact-equality checks that cannot be trivially
true: `between` JulAug n is exactly 4; the EMOS timing argument rests on
exactly 7 rows; the `blend_sources` filter yields exactly 44 June rows.

### MUTATION-TESTED, and the harness had a defect first
New `.unlazy/mutate_prose_gates.py` deletes the sentence each gate anchors to
and asserts the gate FAILS. First run: 29 of 30 killed, one SURVIVOR. The
survivor was NOT a vacuous gate — the phrase "an untrained identity map"
occurs more than once and the harness removed only the first occurrence, so
the anchor still matched. Harness now removes every occurrence.
**Second run: all 30 anchors killed.** Every prose gate notices its claim
disappearing.

Note what mutation can and cannot reach here: it tests the DOCUMENT half of
each gate. The EVIDENCE half cannot be mutation-tested without writing to the
database, which stays read-only. That half rests on the checks being written
correctly, and several are exact-equality precisely so they cannot pass by
accident.

14 checks pass, 9 numeric mutants die, 30 prose anchors die, G9 lint passes.

### REMAINING, NOT DONE
 1. 48 ungated evidential prose sentences. Many are conditionals ("if the
    same-day path never calls it, this dies") whose truth condition is a
    future observation, not a present fact — those are not gateable now.
    The count has NOT been split further and I am not guessing at it again.
 2. 130 genuine ungated numeric claims.
 3. The evidence half of every prose gate is untested by mutation (above).
 4. `prose_coverage.py`'s claim-detection regexes remain mine. Unchanged and
    unresolvable from inside.


## PASS 11 — third 20-pass audit, 2026-08-30

Lenses: 14 gates; numeric mutants; prose anchors; both coverage tools;
document size; reading order; flat-assertion scan; severity language;
dependent sections; citation EXISTENCE; citation CONTENT; duplication;
markdown validity; self-containment; backlog cross-check; still-open
currency; tooling references; mutation revalidation; final coverage;
final re-run.

10 ISSUES FOUND. The automated suite was green throughout — every one of
these was found by reading, which is the honest measure of what the gates
still do not cover.

### THE WORST ONE: reading order
The headline table's summary line read "**z = +2.46 — SIGNIFICANT**" in bold,
and the qualification that withdraws it sat **54 lines below**. A stranger
skimming the lead would take away the exact opposite of the title. Fixed with
a blockquote warning ABOVE the table and an inline qualification on the bullet
itself. **A document whose title contradicts its own headline table is worse
than one with no title.**

### Sections still written as if the finding held
- "The actual finding is a loss of DISCRIMINATION" -> "suspected".
- The AUC framing said the metric cannot be a calibration artefact but never
  said it CAN be a composition artefact — which it largely is.
- "then lost the ranking ability that made that possible" -> marked as a
  STORY, not a finding.
- "roughly half the settled corpus was produced by a model with no
  discrimination" and "the Jul-Aug half is measuring a bug" -> both assert the
  unestablished finding; rewritten to the defensible version.
- "Still open" called the ECMWF lead **"Best remaining lead"** while a later
  section refuted it with n_members and forecast error. Downgraded, with the
  contradiction named.

### A CITATION WAS SIMPLY WRONG, AND THE GATE COULD NOT SEE IT
The document cited `tracker.py:1528` for the `raw_prob` assignment. That line
concerns an unrelated MECHANISM column; the assignment is at **1630**. The
`--citations` gate passed because it only checked that the line EXISTS.
Upgraded to check CONTENT for named citations — and the upgrade immediately
caught a second error, my own expectation of `ml_bias.py:906` (real line 907).

The stale number propagates through THREE places: the backlog entry "THE
HOURLY PATH PUBLISHES A degF TEMPERATURE INTO bias_correction"
(`backlog.txt` ~L2175), the comment at `weather_markets.py:15495`, and this
document. Nothing checked any of them. Recorded in the document so a fix
covers all three.

### MEASURED AFTER
    14 gates pass | 9 numeric mutants die | 30 prose anchors die | lint clean
    numeric coverage 128/331 = 38.7%
    prose coverage    31/100 = 31.0%   (was 33.3%)

Note the prose percentage FELL while the document improved. Fixing a claim
adds prose, and new prose is ungated by construction. **Coverage percentage is
not a quality score** — it moves whenever the denominator does, and chasing it
would penalise exactly the corrections this pass made.

### REMAINING, NOT DONE
 1. 55 evidential prose sentences and 203 numeric tokens ungated.
 2. Citation CONTENT is checked for 5 named citations only; the rest are
    existence-only and could be as wrong as tracker.py:1528 was.
 3. The stale citation in backlog.txt and weather_markets.py is recorded but
    NOT fixed — it is outside this document's scope and needs its own change.


## PASS 12 — fourth 20-pass audit, 2026-08-30

The 14 gates are saturated: they were green at the start and never moved. So
this pass used lenses NOT tried before — the skimmer's view, absolutes,
orphaned cross-references, time-dependence, live data drift, the
headings-only outline, singleton figures, and the re-derive recipe.
**8 issues, none of which any gate could have caught.**

### THE BEST FIND: the document contradicted its own proof
The lead said AUC is invariant under temperature scaling "so unlike **every
other metric in this document** it cannot be an artefact of the calibration
argument". False on the document's own showing: it proves further down that
**accuracy at a fixed threshold is equally invariant**, for the identical
reason. Corrected to name the real split — invariant {AUC, accuracy},
calibration-sensitive {Brier, confidence} — which also strengthens the
argument, because it makes the accuracy drop evidence of the same thing rather
than an independent symptom. Found by scanning ABSOLUTES ("every", "never",
"only"), which is where overclaiming hides.

### Structural defects an outline read exposed
- **The title was TWO H1 headings.** Written as two `#` lines, it renders as
  two titles. Now one.
- **Two near-identical section names** both beginning "Temperature scaling:".
  Renamed to part 1 / part 2 with distinct subjects.
- The closing section required re-measurement to "split at the July step" but
  never mentioned STRATIFYING by condition type, which the composition
  qualification makes mandatory. Splitting without stratifying reproduces the
  exact confound an earlier pass uncovered.

### A TIME BOMB, now defused in writing
Every figure is a snapshot of 341 settled rows. Verified the DB still matches
today. The moment cron settles more markets the gates FAIL — correctly — but a
reader could mistake that for a broken document. Added an explicit contract:
a failing gate after new data means "re-derive", NOT "edit the number until it
passes".

### The re-derive section under-delivered
It described ONE table while the document now holds seven, and predated the
oracle entirely. Rewritten to lead with `audit_handoff.py --all` and the five
supporting harnesses, and to state plainly that coverage is partial so a green
run does not verify an ungated figure.

### AND IT IMMEDIATELY PRODUCED A SELF-STALE CLAIM
The rewrite quoted "about 39% / 31%" coverage. By the time it was written the
real figures were 37.1% / 29.1% — my own edits had added ungated prose and
moved the denominator. Replaced with an instruction to RUN the tools. A
document must not hardcode a number its own tool prints.

### A RENAME SILENTLY DISARMED A MUTATION CONTROL
Renaming the "Temperature scaling" heading invalidated a mutant anchor in
`mutate_handoff_oracle.py`. The harness reported "ANCHOR NOT FOUND — mutation
never applied" rather than passing, which is the behaviour it was built for.
Anchor realigned. **Editing a document can disarm the controls that guard it,
and only an explicit not-applied report makes that visible.**

Measured after: 14 gates pass, 9 numeric mutants die, 30 prose anchors die,
lint clean, 833 lines.

### REMAINING, NOT DONE
 1. 81 of 108 four-decimal figures appear exactly ONCE in the document, so
    they cannot be cross-checked against a restatement — they are guarded only
    if individually gated, and most are not.
 2. Coverage percentages fall as the document improves. Not a defect, but it
    means the metric cannot be used as a completion target.
 3. Repo-wide line citations remain unchecked by anything.


## PASS 13 — the singleton figures, 2026-08-30

Pass 12 recorded that 81 of 108 four-decimal figures appear exactly ONCE, so
they cannot be cross-checked against a restatement and are guarded only if
individually derived.

### First: measure, do not assume
`.unlazy/singleton_report.py` intersects singleton-ness with mutation
coverage, because neither alone identifies the unguarded set. Of the 81, **34
were already gated and 47 were not.** Gating all 81 would have been wasted
work on 34 of them.

### Gated by CLUSTER, not one figure at a time
Two new checks, `--singletons` and `--singletons2`, derive whole table columns:
the market difference-in-differences line, the stratified-AUC prose
restatement, the within-`above` pooled SE, the traded-subset SE/z columns, the
Brier/edge/accuracy table, the Brier scope sentence, the obs-split confidence,
the daily `our_prob` table (20 figures, including a check that every listed
probability is actually one of that day's rows), the raw_prob mean column, the
conf(raw_prob) column, and the Brier-alert values quoted from backlog.txt.

    singletons gated  34 -> 76 of 81   (5 remain)
    numeric coverage  37.1% -> 48.4%

### THE GATE CAUGHT ITS OWN AUTHOR, TWICE
1. The Brier table derivation initially ran over ALL methods and failed 15
   assertions. The document was RIGHT: that table is ensemble-only, and its n
   column (51/48/56/70) proves it. **The gate was wrong, not the document** —
   which is the outcome a gate exists to distinguish.
2. A regex captured a trailing sentence period into a number ("1.27.") and
   raised ValueError. The runner reports a raised exception as a FAILURE
   rather than swallowing it, so this surfaced immediately.

### Refactor forced by the work
Appending the second batch into `check_singletons` reused local names across
unrelated blocks and produced 16 mypy shadowing errors. Split into two
functions with independent scopes; each carries its own vacuity floor.
Regex literals were also rawified — they worked, but emitted deprecation
warnings that would eventually become errors.

16 checks pass, 9 numeric mutants die, 30 prose anchors die, lint clean.

### REMAINING, NOT DONE
 1. **5 singleton figures still ungated**, all in the temperature_scale
    history table and the `r(n, T) = +0.406` correlation.
 2. Numeric coverage is 48.4%; the majority of remaining ungated tokens are
    not singletons and are cross-checkable, but only by inspection.
 3. `--singletons2`'s daily-table check verifies that each listed probability
    is one of that day's rows, but NOT that the list is complete — a row could
    be omitted from the document without failing.


## PASS 14 — condensed to 212 lines, 2026-08-30

The 833-line document was cut to **212**. The full version is preserved as
`docs/HANDOFF-confidence-collapse-2026-08-30-FULL.md`; nothing was destroyed.

WHAT WAS CUT: the retraction archaeology. Roughly 620 lines of "an earlier
draft said X, that was wrong because Y". Honest, but it served the author
showing work more than a reader wanting the current position.

WHAT WAS KEPT: the bottom line, the AUC measurement, the composition
qualification and the bootstrap that withdraws it, the forecast-error
localisation, the four eliminations, the confirmed T self-training defect, the
open questions, and the trap list.

### RETIRING GATES IS NOT SILENCING THEM
Cutting content broke 40+ gate assertions. Every one was triaged as RETARGET
(content survived, wording moved) or RETIRE (content deliberately deleted), and
every retirement is named in the source comment where the check used to live:

  RETIRED  --rederive (confidence table cut) | --singletons2 (all four of its
           tables cut) | tables: rawprob, ts-history, n_members-August |
           singletons: Brier table, Brier scope, obs-split | 5 prose
           restatements | 4 prose claims | 8 prose2 claims
  RETARGET headline/traded/strata section anchors, temperature_scale sentence,
           AUC + accuracy invariance, market-did-not-fall, rounding-noise,
           never-beat-Brier, skill-in-between, below-never-discriminated,
           between-n=4, 11 further prose anchors

Vacuity floors were LOWERED to match what each gate now actually derives, not
raised to make it pass: batch 1 derives 15 and floors at 12, so deleting a
whole cluster still fails.

### THE HARNESSES CAUGHT THE CUT
Three numeric mutants and several prose anchors pointed at deleted sections.
Both harnesses reported **ANCHOR NOT FOUND -- mutation never applied** rather
than passing. The mutant list was retargeted; it now covers the composition
table, the stratified table and the bootstrap CI, which it did not before.

### MEASURED AFTER
    14 gates pass | 11 numeric mutants die | 18 prose anchors die | lint clean
    numeric coverage 48.4% -> **75.2%**  (115 of 153)
    prose coverage   31.0% -> **44.4%**  (16 of 36); META now 0
    document 833 -> 212 lines

Coverage rose sharply because the denominator fell: cutting ungated prose
raises the percentage without gating anything new. **That is the same
denominator effect noted in pass 12, running the other way — do not read 75.2%
as three passes' worth of new verification.**

### REMAINING, NOT DONE
 1. 20 evidential prose sentences and 38 numeric tokens ungated.
 2. The FULL document is now unguarded — no gate reads it, so it can rot.
 3. `--singletons2` remains in the file but unregistered; if its tables ever
    return, it must be re-registered rather than rewritten.
