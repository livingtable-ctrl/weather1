# Round 1 findings ledger — 37 findings, 37 resolved

Three parallel opus reviewers, non-overlapping scopes: **A** protocol statistics
(15), **B** implementation (6), **C** tests and gate checkers (16).

Workflow step 13: every finding is addressed, all of them, not just HIGH/MEDIUM,
and a deliberate no-op is a legitimate resolution only when it is explicit and
reasoned per finding. Step 18: the only deferral bar is genuinely massively out
of scope, and hitting it must be stated rather than left to disappear.

**Measured status: 36 FIXED, 1 NO-OP with reason, 0 deferred, 0 open.**

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
      power statement with the ~+0.052 upper bound at a marginal null.
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
      **FIXED**: labelled an assumption, 2c sensitivity stated (3,004 picks), and
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
