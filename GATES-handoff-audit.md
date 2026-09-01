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
