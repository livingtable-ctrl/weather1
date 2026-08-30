# Findings ledger — round 1 (37) + round 2 (28) + round 3 (26), all 91 resolved

Three parallel opus reviewers, non-overlapping scopes: **A** protocol statistics
(15), **B** implementation (6), **C** tests and gate checkers (16).

Workflow step 13: every finding is addressed, all of them, not just HIGH/MEDIUM,
and a deliberate no-op is a legitimate resolution only when it is explicit and
reasoned per finding. Step 18: the only deferral bar is genuinely massively out
of scope, and hitting it must be stated rather than left to disappear.

**Round 1 status: 36 FIXED, 1 NO-OP with reason, 0 deferred, 0 open.**
**Round 2 status: 28 FIXED, 0 no-op, 0 deferred, 0 open — six of them created
by round 1 own fixes.**
**Round 3 status: 26 FIXED, 0 no-op, 0 deferred, 0 open. Verdict on the code:
sound. Verdict on the design: no defect of kind. The findings are in the
checkers, in stale gate evidence, and in one assumption refutable from data
already in this repo.**

---

## The headline

**A-F1 invalidated the pre-registered sample floor.** N_KILL = 1,340 was sized on
`sd = 0.3992` and `fee = 0.01120`, both derived from a mean executable price of
0.8010 — the DISCOVERY pick set's price (0.791 + 1c) at b = 1.4871. The FROZEN
coefficients produce a different pick set: mean mid 0.7387, executable 0.7487,
sd 0.42024, fee 0.01258.

| | superseded | corrected |
| --- | ---: | ---: |
| mean executable entry | 0.8010 | **0.7487** |
| sd | 0.3992 | **0.42024** |
| delta net | +0.03980 | **+0.03842** |
| N_KILL | 1,340 | **1,700** |
| look 1 | 670 | **850** |
| power at 1,340 | 0.800 | **0.705** |

The coefficients were frozen from the 642-row refit and the price distribution
was inherited from the discovery's 135-pick table. Different pick sets — the
failure this project already has a name for.

**THE CLOCK HAD NOT STARTED.** At the moment of correction the live DB was at
`user_version 84`, `price_recal_shadow_log` did not exist, and zero picks had
been logged. Section 6 binds from the first logged pick. Fixing a registration
before it takes effect is not re-cutting a running experiment, and both facts
are checkable rather than asserted.

---

## A — protocol statistics (15/15)

- [x] **A-F1 CRITICAL** — floor sized on the wrong pick set. **FIXED**: sd, fee
      and delta recomputed at the frozen coefficients; N_KILL 1,340 → 1,700,
      look 1 → 850; correction notice added at the head of the entry.
- [x] **A-F2 CRITICAL** — cluster level. **FIXED**: primary moved to
      `target_date` (z +2.8068), `(city, target_date)` demoted to secondary
      (+2.9991). The reviewer's "deff > 1 in 8 of 12 cuts" did **not** reproduce
      on my cut (0.705 / 0.805 / 0.623, all < 1) and is recorded as
      unreproduced; the decisive half — that the pre-committed cluster was the
      *less* conservative of the two — reproduced exactly and drove the change.
      Re-clustering after the fact is now named as the seventh threshold.
- [x] **A-F3 MAJOR** — five numbers for four cuts; "151-185 clusters" wrong for
      the by-date cuts. **FIXED**: replaced with a labelled two-row table,
      cluster counts stated per level, and a wild cluster bootstrap-t
      pre-committed for any look arriving with under 40 date clusters.
- [x] **A-F4 MAJOR** — "excludes delta ≥ +0.0398". **FIXED**: rewritten as a
      power statement with the upper bound at a marginal null. (Round 2 found
      that bound was computed on superseded inputs; corrected to +0.0492.)
- [x] **A-F5 MAJOR** — the 0.74-0.86 band. **FIXED**: the addendum now separates
      the SIDE (reconciles) from the BAND (does not) — 0.560-0.910, median
      0.745, only 33.2% inside.
- [x] **A-F6 MAJOR** — the 10.3/day, ~130-day case is unreachable. **FIXED**:
      withdrawn; 266 days is the only estimate; deadline moved to 2027-12-31
      with the 1.8x margin derived.
- [x] **A-F7 MODERATE** — noise floor independence and loose wording. **FIXED**:
      tail probabilities added beside E[max] (44% at M=12) and the source's own
      independent-trials caveat quoted.
- [x] **A-F8 MODERATE** — M undercounted. **FIXED**: 10 → 12 (both held-out
      Brier t-tests counted); z_crit 2.8653; the M=12 row shows a **negative**
      net edge.
- [x] **A-F9 MODERATE** — retained power. **FIXED**: recomputed on the bivariate
      normal at rho = 0.7071 → 0.81706 → 0.81687, a cost of **0.00019**, not the
      0.004 the draft got by multiplying marginals. G3 now computes it the same
      correct way, which is the point — the old checker shared the error.
- [x] **A-F10 MODERATE** — the 1c spread frozen into an unamendable number.
      **FIXED**: labelled an assumption, 2c sensitivity stated (round 2
      recomputed it properly as 2,846), and
      a trigger pre-committed at 100 picks if the measured median exceeds 1.5c.
- [x] **A-F11 MINOR** — two fee ratios, neither naming its price. **FIXED**:
      both name it (67% at P=0.79); size-dependence scoped to C=1..4; C=25's 3%
      optimism and unrelated-strategy provenance disclosed.
- [x] **A-F12 MINOR** — one-tailed justification backwards. **FIXED**: the entry
      now says 2.8653 is the two-sided cut used one-tailed as a deliberate
      tightening, not a consequence of direction, and states its cost.
- [x] **A-F13 MINOR** — "independently reproduced" overstated; numbers didn't
      reproduce. **FIXED**: "independently" withdrawn, and the exact split rule
      stated — order by `(target_date, ticker)`, fit first 321, pick last 321.
      Under that rule my figures reproduce exactly; the reviewer had ordered by
      `analyzed_at`, which is a genuinely different split.
- [x] **A-F14 MINOR** — two non-reproducing figures. **FIXED**: the +0.07427
      peak is withdrawn rather than replaced (it reproduces at no intercept in
      the record); the +0.0610 vs +6.06% gap is disclosed as a difference of
      quantities.
- [x] **A-F15 NIT** — "670" ambiguous. **NO-OP, resolved incidentally**: look 1
      moved to 850, so it no longer collides with the 670-row population figure.
      Nothing left to annotate.

## B — implementation (6/6)

- [x] **B-F1 CRITICAL** — raw `outcomes` join, red repo-wide guard. **FIXED**:
      reads `outcomes_valid`; guard green; disputed-settlement test plus its
      positive control added; a mutant covers the EXISTS clause.
- [x] **B-F2 MEDIUM** — a silently-stalled log looks like a quiet day. **FIXED**:
      the INFO line moved out from under `if _prsl_wrote`, and a WARNING fires
      when the skip rate exceeds 90% of a non-trivial scan.
- [x] **B-F3 LOW-MED** — dead `_target_date` fallback. **FIXED**: reads `_date`;
      test and mutant added.
- [x] **B-F4 LOW** — "KXHIGH*/KXLOW*" is a ticker claim. **FIXED**: comment
      corrected; the 30 KXTEMP* hourly rows disclosed in the entry; the
      unresolved question of whether the discovery's 538 rows were
      ticker-filtered recorded as a known imprecision in the inherited effect
      size.
- [x] **B-F5 LOW** — no `init_db()`. **FIXED**.
- [x] **B-F6 INFO** — no production caller; NULL-city collapse. **FIXED**: cron
      logs progress counts (no statistic); `settled_events` COALESCEs NULL
      cities, with a test and two mutants.

## C — tests and gate checkers (16/16)

- [x] **C-F1 CRITICAL** — G5 missed 6 of 10 call forms. **FIXED**: fails closed
      on any unresolved call outside an explicit allowlist; resolves import
      aliases (module-level and function-local); handles Call and Attribute
      receivers; follows `order_executor`/`kalshi_client`/`paper`; runs **six**
      positive controls, all previously missed, all now caught.
- [x] **C-F2 CRITICAL** — `settled_events` indistinguishable from `return 1`.
      **FIXED**: fixture seeds 3 cities × 4 dates (12 events of 900 picks);
      three mutants now die.
- [x] **C-F3 CRITICAL** — yes_bid/yes_ask swap invisible. **FIXED**: both
      columns asserted with different values.
- [x] **C-F4 MAJOR** — G1 blind to the converse. **FIXED**: post-protocol
      backlog edits must be declared with a reason; `.split()` filename bug
      fixed via `-z`.
- [x] **C-F5 MAJOR** — the anti-echo gate echoed. **FIXED**: inputs PARSED from
      the parent entry's own discovery table and recomputed from the DB; the
      haircut table matched POSITIONALLY per row; the 1c spread checked to be
      labelled an assumption rather than used silently.
- [x] **C-F6 MAJOR** — blocklist, and two indistinguishable fields. **FIXED**:
      exact key-set equality; the second test runs past look 1 so the two fields
      must differ.
- [x] **C-F7 MAJOR** — day-not-hour asserted only as a DDL string. **FIXED**:
      two behavioural tests across a real UTC boundary, plus a same-day control.
- [x] **C-F8 MAJOR** — datetime target_date. **FIXED**:
      `_price_recal_target_day` normalises six shapes; parametrised test,
      end-to-end dedup control, two mutants.
- [x] **C-F9 MAJOR** — mutation gaps. **FIXED**: 10 mutants added (22 total, all
      killed). The `target_date`/`_target_date` fixture collision is broken by a
      test that omits the analysis key entirely. G8's kill criterion now also
      runs the content gates, so a mutation to a pre-committed constant is
      caught where it is actually asserted.
- [x] **C-F10 MODERATE** — G10 minimum below the true count. **FIXED**: `-k`
      widened, minimum raised to 6.
- [x] **C-F11 MODERATE** — `protocol_version` unbound. **FIXED**: G3 asserts
      cron's string appears in the entry.
- [x] **C-F12 MODERATE** — no upgrade-path test; merge-base comparison. **FIXED**:
      a test winds an existing DB back to v84 and asserts `_run_migrations`
      reaches v86 with table and index present, then writes through it.
- [x] **C-F13 MODERATE** — scoped derivation missed 24 cron modules. **FIXED**:
      `TOUCHED` widened with `outcomes_valid`, `_RAW_OUTCOMES_ALLOWLIST`,
      `cmd_cron`, `sameday_only`, `all_results`: **23 → 57 modules, 2189 → 3766
      tests**. The widening immediately caught the red disputed-row guard *and*
      a pre-existing ordering bug in `test_sameday_only.py`.
- [x] **C-F14 MODERATE** — G9 not read-only. **FIXED**: snapshots, restores on
      rewrite, fails loudly. It fired on the first run; formatting was then
      applied deliberately and re-verified.
- [x] **C-F15 MINOR (8 items)** — **7 FIXED**: network test patches
      `_get`/`_post`/`_delete` with `hasattr` guards; `days_out` stores NULL when
      absent; NULL-city collapse fixed and tested; same-ticker/two-dates tested;
      terminal state tested; look points single-sourced in `tracker`;
      `check_order` uses `-z`; `run_selected` minimums at true counts.
      **1 NO-OP with reason**: no sqlite lock/contention test. The writer's
      connection handling is byte-identical to the sibling `_log_exit_rule_shadow`
      that has run in production for months, so such a test would exercise the
      sibling's already-proven behaviour rather than anything this change
      introduces.
- [x] **C-F16 MODERATE** — GATES.md evidence overstated. **FIXED**: G8's title no
      longer claims "each" guard; the unreproducible "two mutants survived"
      claim is marked disclosure, not measurement; G5's unresolved-call line is
      now a real assertion.

---

## Found while fixing, outside all three review scopes

**A pre-existing test-isolation bug in `tests/test_sameday_only.py`.** Three
tests in `TestCronSamedayOnlyCliWiring` pass only by ordering luck: the real
`.env` sets `KALSHI_ENV=prod`, conftest imports `main` at collection time so
`load_dotenv()` puts that in `os.environ`, and conftest's own autouse
`_clear_ws_credentials` deletes the credential vars — so `main.main()` hits
`_validate_config()` and raises `SystemExit(1)` before `cmd_cron` is reached.
Run alone the module never triggers that import and `KALSHI_ENV` falls back to
its `"demo"` default.

Verified pre-existing rather than assumed: with **origin/master's own cron.py and
tracker.py** dropped into this worktree, the same three tests fail identically.
(An earlier check in a detached worktree wrongly suggested I had caused it —
that worktree sits at a different path and cannot see the main clone's `.env`,
so the comparison was invalid. Corrected by re-running in place.)

Fixed in the same change per step 18: the fixture now pins `KALSHI_ENV=demo`.

---

## The cross-cutting lesson

Three findings are one defect: **my verification recomputed my own errors rather
than checking them against anything external.** G3 certified retained power of
0.796 (A-F9) because the checker made the same independence mistake the text
did. G3's inputs were retyped from the entry it was checking (C-F5). G7's
derived module set missed a red repo-wide guard because the derivation came from
my own list of what I thought I had touched (B-F1, C-F13).

A self-written oracle inherits its author's blind spots. That is the argument
for the review, and it is why the fixes move the checkers' inputs to sources the
checkers do not control.

---

# ROUND 2 — 28 findings, all resolved

Two parallel opus reviewers on the CORRECTIONS, not the original. The round
exists because a fix reliably introduces new defects in code a prior round just
called clean, and it did: **A2-F1, A2-F3, A2-F4, A2-F5, A2-F6 and B2-F1 were all
created by round 1's own fixes.**

**Measured: 28 fixed, 0 no-op, 0 deferred, 0 open.**

## The headline

**A2-F1 CRITICAL — the floor counted the wrong unit.** The table's unique index
is `(ticker, target_date, date(recorded_at))` — one row per market **per day** —
so a market in the firing band for three days writes three rows carrying the
same settlement. The sizing treated each row as an independent observation. The
decision statistic does not: duplicating every pick k times scales `S` and every
cluster sum by k, so `z` is **exactly invariant** (verified numerically at
k = 1, 2, 3, 5 — all give z = 1.725459). 1,700 rows at multiplicity 2 would have
delivered the power of 850: 0.42 against the committed 0.82.

The floor was right; its **denomination** was wrong. `get_price_recal_progress`
now counts DISTINCT `(ticker, target_date)` picks and reports `settled_rows`
separately so the multiplicity stays visible. Fixed before the first pick, with
a test and a mutant.

## Scope A — statistics (17/17)

- [x] **A2-F1 CRITICAL** — pick unit. **FIXED**, above.
- [x] **A2-F2 MAJOR** — the cluster justification was the z comparison, a
      data-dependent basis for a choice section 6 forbids making from data.
      **FIXED**: section 3 now leads with the mechanism (measured cross-city
      correlation, shared synoptic patterns, an all-NO directional book) and
      demotes the z to a consistency check. The multi-day table (2-day +2.7885,
      3-day +2.4146, week +2.1233) is disclosed **in advance**, so reaching for
      a coarser cluster after seeing the result is visibly the seventh threshold.
- [x] **A2-F3 MAJOR** — the "+0.052 upper bound", *added by round 1's fix*, was
      computed on the superseded z_crit, sd and N. **FIXED**: +0.0492.
- [x] **A2-F4 MODERATE** — the 2c sensitivity, *added by the fix*, held sd and
      fee at their 1c values. **FIXED**: recomputed properly — 2,846 (+73%).
- [x] **A2-F5 MODERATE** — "3% optimistic against 0.01120", *added by the fix*,
      quoted the discovery fee. **FIXED**: 1.4% against 0.012580.
- [x] **A2-F6 MODERATE** — "C=5 to C=25 penalty is 0.4%" false. **FIXED**: table
      added; C=5 carries 8.3% and its derived floor of 1,716 **exceeds** the
      committed 1,700, now named as a dependency rather than glossed.
- [x] **A2-F7 MODERATE** — delta is still a hybrid. **FIXED**: disclosed, with
      all three defensible transfers priced (1,079 / 1,644 / 2,161) and 1,700
      stated as a floor rather than a bound.
- [x] **A2-F8 MODERATE** — "by an independent route" false; Bonferroni is the
      union bound on that same event. **FIXED**, and the double-counted M is now
      priced: with no multiplicity the floor is 939.
- [x] **A2-F9** ten-fork → twelve-fork. **A2-F10** surviving 10.3/day.
      **A2-F11** stale 670/1,340 in two docstrings — which also makes round 1's
      A-F15 no-op false, corrected here. **A2-F12** b = 1.336269 against the
      committed 1.33635, disclosed under the entry's own five-decimal standard.
      **A2-F13** 1,440 → 1,449. **A2-F14** surviving 0.79. **A2-F15** mid and
      executable prices mixed in one block. **A2-F16** the MinBTL denominator is
      SR_target, not E[max], which made the printed form degenerate.
      **A2-F17** the 0.705 was itself a mixed-input figure; both values now
      given. All **FIXED**.
- [x] **Attack 6 — the correction's legitimacy.** Sound in kind, under-bounded.
      **FIXED**: three bounds added — at most ONE pre-clock correction; "zero
      picks" narrowed to "no FORWARD observation", with the in-sample forks
      acknowledged; and the clock's start bound to the first logged row rather
      than to cron's scheduling accident.

## Scope B — code and gates (11/11)

- [x] **B2-F1 HIGH** — the production readout logged the **demoted** cluster,
      and a round-1 mutant *actively enforced* the demotion. 900 picks over
      3 cities × 4 dates read as 12 events where the primary cluster gives 4.
      **FIXED**: both counts returned and named, primary logged first, mutant
      inverted.
- [x] **B2-F2 HIGH** — G3's "parsed from the PARENT entry" was **false**. The
      anchor matched at offset 803, inside the protocol entry's own
      cross-reference; the slice was unbounded and the row it found sat 3.11 MB
      past the anchored entry's end. **FIXED**: located by its own `[OPEN`
      header, bounded to 6,456 chars, exactly-one-match required, and asserted
      to lie outside the entry under test.
- [x] **B2-F3 HIGH/MED** — G5's `get` allowlist and dropped dynamic dispatch let
      four more forms through. **FIXED**: `.get(` allowed only on known
      mappings, dynamic dispatch fails closed, FOLLOW made deterministic, both
      extra production entry points walked. **11 controls, all caught** — it was
      1 originally and 6 after round 1.
- [x] **B2-F4** stale docstrings. **B2-F5** the skip-rate alarm had ~12 points of
      headroom over a routine 78% and measured the wrong thing — replaced with a
      `last_at` staleness alarm, and the INFO line no longer hides while
      unsettled. **B2-F6** `init_db()` initialised `tracker.DB_PATH` while the
      writer wrote its own parameter — now bound to the actual target, with the
      table's own two migrations applied for a foreign path. **B2-F7** the
      normaliser missed the space separator and never validated — now splits
      T/t/space and **canonicalises** through `fromisoformat().isoformat()`, so
      ISO basic form cannot open a second key space. **B2-F8** the vacuous
      `assert second in (0, 1)` deleted. **B2-F9** G9's file list derived from
      the diff (it had omitted `test_sameday_only.py`) with a `try/finally`
      restore. **B2-F10** G1's declaration control documented honestly as
      provable-then-attested. **B2-F11** M disclosed as a second input without
      external authority; "positionally" corrected to whole-row matching.
      All **FIXED**.

## What the round-2 fixes themselves caught

Deriving G9's file list from the diff pulled the `.unlazy/` checkers into lint
for the first time, which immediately found a real mypy type error and a ruff
violation in `check_shadow_only.py`. The gate that was widened to stop lying
about its scope found bugs the moment its scope became honest.

---

# ROUND 3 — 26 findings, all resolved. FINAL ROUND.

Two parallel opus reviewers on round 2's corrections. Scope B's verdict on the
code was **"the round-2 code fixes are sound"**; scope A's on the design was
**"I could not find a defect of kind in the inferential design."** The findings
are concentrated in the checkers, in stale gate evidence, and in one assumption
that turned out to be refutable from data already in this repo.

**Measured: 26 fixed, 0 no-op, 0 deferred, 0 open.**

## The headline

**R3-A1 HIGH — the 1c half-spread was not unverified; it was refuted.** The entry
listed the real bid/ask distribution under NOT VERIFIED and said the log would
start measuring it on day one. Both were wrong: `orderbook_depth_snapshots`
already holds 10,140 prod snapshots, **1,769 of them inside the 0.09–0.44 firing
band across 324 tickers**. Measured:

| | half-spread |
|---|---|
| median | **0.0150** |
| mean | 0.0209 |
| per-ticker median | **0.0200** |
| share above 1.5c | 49.9% of snapshots, 54.3% of tickers |

The decision statistic uses the **real** executable price while the sizing used
mid + 1c, so the forward test would have measured the worse delta and been
judged at a floor sized for the better one:

| half-spread | sd | delta | floor | power at 1,700 |
|---|---|---|---|---|
| 0.010 (assumed) | 0.42024 | +0.03842 | 1,644 | 0.817 |
| **0.015 (measured)** | **0.41724** | **+0.03360** | **2,118** | **0.676** |
| 0.020 | 0.41416 | +0.02878 | 2,846 | 0.500 |

**RESIZED: N_KILL 1,700 → 2,200, look 1 850 → 1,100, ~344 days.** This is the
third and final pre-clock pass; the entry's own cap said the second was the
last, and doing it anyway is recorded as a deliberate override rather than
rationalised — shipping a floor sized on an assumption already contradicted by
data in hand is the worse error.

**Depth is the other half.** From the same snapshots, C = 25 is available at the
best bid only **51.0%** of the time and under 5 is available 19.1% — and section
3's table puts the derived floor *above* the commitment at C = 5. Adding
`yes_bid_size` columns was considered and **rejected**: the scan carries no
depth, so they would have been two permanently-NULL columns, which is the exact
defect `exit_rule_shadow_log`'s schema comment warns about. The depth trigger
reads `orderbook_depth_snapshots` instead.

## Scope A — statistics (15/15)

- [x] **R3-A1 HIGH** — the spread. **FIXED**, above.
- [x] **R3-A2 HIGH** — round 2 redefined a pick as a distinct
      `(ticker, target_date)` but left the statistic reading `entry_price_exec`,
      a **per-row** column. Which row supplies a pick's price was undefined, and
      entry prices span 0.560–0.910. **FIXED**: pre-committed to the FIRST row
      at which the pick fired — the price a live implementation would have
      transacted at. Left open it would have been the eighth threshold.
- [x] **R3-A3 HIGH** — "EXACTLY invariant" is exact only for identical rows; real
      duplicates share `y_i` but differ in `a_i` and `f_i`. **FIXED**: the claim
      is narrowed to what it is (uninformative about the extra rows), and the
      collapse rule in A2 is what actually makes it moot.
- [x] **R3-A4 HIGH** — the "design effect" column was never defined, and under
      the CONVENTIONAL definition the primary cluster is **1.1015, above 1**.
      **FIXED**: column defined, both definitions given, and the finding that
      matters recorded — the ANOVA ICC within `target_date` is **−0.0068**, so
      the in-sample data show **no positive within-date dependence at all**,
      which is the opposite of the synoptic mechanism round 2 promoted to
      justify the cluster. It is retained as a prior, explicitly labelled as
      one, and the sizing does not lean on it.
- [x] **R3-A5 MEDIUM** — C = 25 load-bearing and unmeasurable from the row.
      **FIXED**, above.
- [x] **R3-A6 MEDIUM** — the sizing corpus (`analysis_attempts`, last-price
      upsert) and the forward corpus (fires on ANY day in band) are selected
      differently. **FIXED**: disclosed in section 5 as a known imprecision.
- [x] **R3-A7 MEDIUM** — "EXACTLY TWO LOOKS" vs the 100-pick trigger. **FIXED**:
      the trigger reads prices and sizes, never `y_i`, and section 6 now says so
      rather than leaving a reader to reconcile the two claims.
- [x] **R3-A8 MEDIUM** — the correction notice described one review round.
      **FIXED**: all three, and round 2's own critical is named in the notice.
- [x] **R3-A9..A15 MINOR** — the surviving 0.79 (FINDINGS had wrongly marked
      A2-F14 fixed); the 2,161 floor that recomputes to 2,160; the 10.3/day
      provenance sentence whose own numbers refuted it; the two cluster-count
      pairs stated 15 lines apart with different values; the unstated multi-day
      block alignment; the "roughly a third" cross-reference that is a sixth;
      and the accrual denominator using pick-bearing dates rather than calendar
      days (6.03/day, not 6.39). All **FIXED**.

## Scope B — code and gates (11/11)

- [x] **R3-B1 HIGH** — **G9 passed vacuously on an empty file list**, and the
      list goes empty in the ordinary case: once this branch merges,
      `merge-base(HEAD, master) == HEAD`. Verified — `pre-commit run --files`
      with nothing skips every hook and exits 0. **FIXED**: empty is now a
      failure, both git calls check their return code, and untracked files are
      included.
- [x] **R3-B2 HIGH** — G3's parent-entry back-bound searched only `[OPEN `,
      while backlog.txt already holds **17 `[CLOSED ` headers**. The moment the
      parent entry is groomed to CLOSED the search walks backwards past it and
      the slice spans two entries again — the exact unboundedness round 2 closed.
      **FIXED**: all three header kinds.
- [x] **R3-B3 HIGH** — wrong fallback when the parent is the last entry
      (`else 0` truncated the slice to its header). **FIXED**.
- [x] **R3-B4..B6 MEDIUM** — the schema-bootstrap branch had no test on either
      side and no mutant (two tests and two mutants added); the migration
      substring filter could sweep in a future unrelated `ALTER` (narrowed to
      CREATE TABLE / CREATE UNIQUE INDEX); the `days_out` mutant was killed by a
      `KeyError` rather than by the `or 0` regression it names (widened to the
      whole expression).
- [x] **R3-B7 MEDIUM** — **GATES.md was stale on nine counts** after round 2
      changed six checkers. **FIXED**: the evidence is now rewritten wholesale
      from the run that produces it, and the ledger says so.
- [x] **R3-B8 MEDIUM** — G5 still missed assignment-rebinding
      (`log = requests.get; log(url)`). **PARTIALLY FIXED**: single-letter names
      dropped from `DICT_GET_RECEIVERS`, the cron glue added to the walk, and
      the residual limit STATED in GATES.md rather than papered over — closing
      it needs local dataflow, and exploiting it needs adversarial code.
- [x] **R3-B9..B11 LOW** — the object path was canonicalised like the string
      path (a `date` subclass overriding `isoformat`, or a `datetime.time`,
      would have been stored verbatim); `settled_rows` is now printed, since its
      comment claimed the multiplicity was visible; the vacuous
      `assert tracker_db is not None` removed.

## Found while fixing, and worth its own line

`check_mutations.py` reads bytes and decodes without newline translation, so
**every multi-line anchor silently failed on a CRLF-checked-out file** — and the
failure reads exactly like a missing anchor, i.e. like a real coverage gap. Two
mutants were being reported as untested when the tooling simply could not find
them. Now line-ending aware.

Mutants 25 → **28, all killed**. Tests 69 in the module, **3,780 across 57
modules**.
