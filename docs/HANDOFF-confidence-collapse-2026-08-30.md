# HANDOFF: a suspected July regression in model discrimination — direction consistent, significance NOT established

Written 2026-08-30. Condensed from an 833-line working document; the full
version with every retraction and its reasoning is preserved beside this one as
`HANDOFF-confidence-collapse-2026-08-30-FULL.md`. Read that only if you need to
know why a hypothesis was dropped.

**THE FIGURES HERE ARE A SNAPSHOT OF A GROWING CORPUS.** Every number derives
from 341 settled core rows, the state of `data/predictions.db` on 2026-08-30.
`python .unlazy/audit_handoff.py --all` re-derives them. **A failing gate after
new data is EXPECTED and means "re-derive", not "the document is broken".** Do
not edit a number to make a gate pass.

## Bottom line

1. **The model has never beaten the market on Brier in any month.** This is the
   only conclusion that survives every qualification below.
2. Something appears to have changed between **2026-06-30 03:34 and
   2026-07-02 19:07** — a window containing **zero commits**.
3. That change is **downstream of the forecast**: raw forecast error HALVED
   while probabilities got worse.
4. **The regression is NOT established.** Every measurement points the same
   direction and none reaches significance once confounds are handled.

## The measurement

AUC — the probability the model ranks a random YES above a random NO. 0.50 is
no signal. **AUC is invariant under temperature scaling** (a strictly
increasing map fixing 0.5), so it cannot be a calibration artefact. Accuracy at
a fixed 0.5 threshold is equally invariant, for the same reason; Brier and
confidence are NOT. It CAN be an artefact of which markets were scanned — and
it largely is.

| period | who | n | AUC | SE | z vs 0.50 |
|--------|-----|---|-----|----|-----------|
| May-Jun | **model** | 198 | **0.6828** | 0.0377 | **+4.85** |
| May-Jun | market | 198 | 0.6853 | 0.0376 | +4.93 |
| Jul-Aug | **model** | 143 | **0.5321** | 0.0484 | **+0.66** |
| Jul-Aug | market | 143 | 0.7271 | 0.0424 | +5.35 |

- model, MayJun - JulAug = **+0.1507**, SE 0.0613, z = +2.46
  — nominally significant, **BUT CONFOUNDED: see below.**
- market, MayJun - JulAug = -0.0418, SE 0.0567, z = -0.74 — not significant

Monthly: May 0.6215 (n=51) | Jun 0.6973 (147) | Jul 0.5497 (69) | Aug 0.5085 (74).
Pooled model AUC 0.6178 (n=341, z=+3.89); pooled market 0.7049 (z=+7.31).

## Why it is not established: composition

The condition-type mix is almost completely different across the boundary:

| condition | May-Jun share | Jul-Aug share |
|-----------|---------------|---------------|
| `between` | **55.6%** | **2.8%** |
| `above` | 26.3% | 59.4% |
| `below` | 14.1% | 37.8% |

Family drifted too (KXHIGH 65.7% -> 45.5%, KXLOWT 34.3% -> 54.5%). Ladder
width did not: `between` markets are 2.00F wide in both periods.

| condition | period | who | n | AUC | SE | z vs 0.50 |
|-----------|--------|-----|---|-----|----|-----------|
| above | May-Jun | model | 52 | 0.6989 | 0.0723 | +2.75 |
| above | Jul-Aug | model | 85 | 0.5786 | 0.0620 | +1.27 |
| below | May-Jun | model | 28 | **0.5444** | 0.1144 | **+0.39** |
| below | Jul-Aug | model | 54 | 0.4731 | 0.0793 | -0.34 |
| between | May-Jun | model | 110 | 0.6378 | 0.0545 | +2.53 |
| between | Jul-Aug | model | **4** | — | — | too few |

1. The model's May-June skill was concentrated in `between` markets
   (n=110, AUC 0.638) and `above` (n=52, 0.699). On `below` it NEVER
   discriminated — 0.5444 at z=+0.39 in its best period.
2. **`between` all but disappeared**, 110 rows to 4. The pooled May-June figure
   is therefore heavily weighted by a market type that is absent later.
3. **Within `above`, the drop is 0.6989 -> 0.5786** — the difference SE is
   ~0.095, so **z is about 1.27. NOT SIGNIFICANT.**

The last surviving argument was that **the market's AUC did not fall in any
stratum** — `above` 0.7358 -> 0.7530, `below` 0.5861 -> 0.6517 — so the two
diverged in OPPOSITE directions on the same rows, which composition alone
cannot produce. Measured as a difference-in-differences, cluster-bootstrapped
by ticker (`.unlazy/did_bootstrap.py`):

    observed DiD  = +0.1373   (positive = model deteriorated vs the market)
    95% CI        = [-0.0794, +0.3446]   2000 resamples
    two-sided p   ~ 0.21

**THE CONFIDENCE INTERVAL INCLUDES ZERO. DO NOT PRESENT "THE MODEL BROKE IN
JULY" AS ESTABLISHED.**

A selection confound was tested and **REFUTED.** The recording regime genuinely
did change: May-June recorded only
markets where a paper trade was placed (51/51 and 147/147), July recorded none
(trading paused), August 63 of 74. Imposing the old regime's own selection on
the new data — does not rescue the model:

| period | who | n | AUC | SE | z vs 0.50 |
|--------|-----|---|-----|----|-----------|
| May-Jun | model | 198 | 0.6828 | 0.0377 | +4.85 |
| Jul-Aug | model | **63** | **0.4849** | 0.0733 | **-0.21** |
| Jul-Aug | market | 63 | 0.7213 | 0.0645 | +3.43 |

July contributes zero traded rows, so that n=63 subset is entirely August and
it cannot speak to July directly.

## Where the defect is: downstream of the forecast

Raw forecast error, `|forecast_temp_f - outcomes.settled_temp_f|`, degrees F:

| month | n | median | mean | p90 |
|-------|---|--------|------|-----|
| 2026-05 | 51 | 2.65 | 2.69 | 5.50 |
| 2026-06 | 50 | 2.68 | 2.80 | 5.20 |
| 2026-07 | 56 | **1.18** | 2.01 | 4.14 |
| 2026-08 | 70 | **1.67** | 2.05 | 4.18 |

**The temperature forecast roughly HALVED its error in July** while
discrimination fell. The model forecasts the weather better than ever and
converts it into worse probabilities, so the defect is in the
temperature-to-probability step.

WHAT THIS RULES OUT: any explanation that degrades the forecast itself —
a model dropping out of the blend, a data source going stale, seasonality.
Corroborating that, `n_members` is **238 on every one of the 56 July rows**,
spanning the collapse window, with `blend_exclusions` empty throughout — so
the ensemble did not lose a member when discrimination died.

THE SIGNATURE TO HUNT: a sigma that is uniformly WRONG compresses
probabilities but PRESERVES their ranking, so it cannot move AUC. Only a
sigma that became noisy ROW-TO-ROW can hold forecast accuracy constant while
destroying discrimination.

## Suspects eliminated — do not re-open without new evidence

- **EMOS (`ae1d5bae`, 2026-06-27).** **EMOS WAS NEVER ACTIVE.**
  `data/emos_params.json` does not exist and activation requires an explicit
  `emos-train --activate`; `cron.py:2202` only ever prints a readiness
  reminder. A method that
  never ran cannot have flattened anything.
- **Pricing fix (`d5a6440f`, 2026-06-30 00:46).** ELIMINATED: the 02:13 and
  03:34
  predictions later that same morning were still extreme (0.038, 0.963).
- **`TRADING_PAUSED` selection.** Trading was paused 2026-07-01 to 07-31.
  August ran `is_shadow = 0` (71 of
  78 rows, trading resumed) and confidence STAYED collapsed at 0.0700, so
  the effect outlived the pause. WEAKENED rather than eliminated: it assumes
  nothing else sustains the August flatness.
- **Loss of the `obs` blend component.** ELIMINATED by the aggregate, which
  points the other way — blends
  CONTAINING obs have LOWER mean confidence (0.1135, n=88) than blends
  without it (0.1425, n=137), and the share of predictions carrying obs
  ROSE across the collapse: May 0%, Jun 43.2%, **Jul 62.5%**, Aug 45.9%.

## A confirmed code defect — real, but NOT the July cause

`backlog.txt` ~L47711 records that `train_all_temperature_scaling` FITS T ON
ITS OWN PRIOR OUTPUT, and that "sameday/hourly were never frozen". Confirmed in
code: the fitter reads `our_prob`, the stored POST-calibration value. Current
`data/temperature_scale.json`: `sameday` **T = 3.8294** (n=102), `global`
T = 4.6013 (n=68), `above` T = 1.2739 (n=44). Most predictions in
this corpus are same-day, and same-day is the key that was never frozen.

It CANNOT be the July cause — AUC is calibration-invariant. And T-scaling was
inert through July: **The Aug-01 snapshot shows T=1.0 with n=0** and carried no
sameday key at all. The runaway such a loop predicts is also NOT visible in the
data: sameday is broadly flat with one late jump, and `global` moves the other
way entirely.

`data/.history/` keeps only the
last 10 snapshots, so July's T values are unrecoverable there.

## PARTLY ANSWERED 2026-08-31: the window is mis-anchored, and the corpus change has a commit

Read this whole section before quoting any of it. The mechanism is
established; the explanation is NOT.

### What IS established

**The window is an artefact of the population it was drawn from.** Its two
endpoints are ensemble predictions. The regime change was in a different
method entirely, five days earlier, and it has a commit: `e395392b`
(2026-06-25), "fix(metar): add local-date guard to prevent prior-day obs from
locking between markets". It rejects a lock when the METAR observation's local
date is not the target date. The cron scanned at 00-02 UTC, which is
20:00-22:00 the PREVIOUS local day, so the guard rejects exactly that traffic.

**The `between` BRANCH of the METAR lock is what stopped, not the lock.** Its
last fire is **2026-06-25**, the day `e395392b` landed; it does not fire again
for 48 days (next: 08-13, then 08-24). The `above`/`below` branches, which the
guard does not touch, keep firing through 07-31. The earlier claim that the
lock "ran every day 06-03..06-26 then stopped" was wrong twice: it is
branch-specific, and June has 21 lock days out of 31, not 24 (06-17, 06-22 and
06-24 have none).

**The composition shift is large and real.** METAR lock-ins were **89 of 198**
May-June core rows (**44.9%**) and 17 of 143 (11.9%) in July-August, and
**69 of the 110 May-June `between` rows (63%)** are lock-ins, as are all 4 of
the July-August survivors. `ens+obs` went 9.6% -> 46.2% as they left.

### What is NOT established: that any of this EXPLAINS the AUC gap

Removing the METAR rows shrinks the May-June minus July-August gap from
**+0.1507** to **+0.0920**. That looked decisive. It is not:

- **Size-matched null.** Remove a RANDOM subset with the same per-period
  counts (89 May-June, 17 July-August), 20,000 draws: mean shrink -0.0000,
  sd 0.0382, and a shrink at least as large as the observed +0.0587 occurs
  with **one-sided p = 0.062**.
- **Discrimination-matched null.** Restrict those draws to subsets scoring at
  least METAR's own 0.7248: **p = 0.361**. The shrink is fully accounted for
  by "an 89-row subset scoring 0.7248 was removed"; the METAR label does no
  work. A random 89-row May-June subset reaches 0.7248 **15.4%** of the time.
- **The premise itself is unestablished.** METAR rows are not significantly
  more discriminating than the rows they were pooled with:
  May-June 0.7248 (n=89) vs 0.6369 (n=109), difference +0.0879, SE 0.0759,
  **z = +1.16**. July-August: +0.5106, SE 0.1520, z = +0.07.

So the honest statement is: **composition changed identifiably and for a known
reason, and it is the largest single contributor anyone has named — but at
this n it cannot be shown to explain the gap rather than to be one more thing
that moved.** Do not present "the METAR rows explain it" as established.

It also does NOT subsume the document's strongest evidence. On the
selection-controlled traded subset above, which already contains zero
July-August METAR rows, removing them accounts for only 23% of the gap and
leaves z at +1.68, not +1.25.

### Corrections to earlier drafts of this section

- **"No commit is involved" was FALSE.** It was an absence claim made without
  a repo-wide search. See `e395392b` above.
- **"reads an already-observed daily extreme off a thermometer and is not a
  forecast at all" was FALSE.** On all 106 lock-in rows,
  `|observed_extreme_f - outcomes.settled_temp_f|` has median **8.94F**, mean
  9.51F, and **zero** exact matches. The lock is a margin-gated extrapolation
  from a partial-day reading, with realized accuracy ~70% on YES-locks
  (`metar.py`'s own docstring), and July-August lock-ins score accuracy 0.471
  / Brier 0.4153. It is a model path with its own beta calibration, not an
  oracle. "The stratum that carried May-June's skill was mostly not the model"
  over-reached.
- **The `get_historical_sigma()` elimination had the right verdict for the
  wrong reason.** `_load_dynamic_sigma` DID NOT EXIST during the collapse: it
  was removed by `24559a75` (2026-05-26) and restored by `4ccbeb28`
  (2026-07-12). Through the whole window the code took the STATIC
  season-keyed fallback, which June and July share (both season 3), so it
  could not change at the July boundary at all. The month-keyed ratios
  (median 0.875 max / 0.794 min) were measured off a cache written 2026-08-29
  and describe a dormant branch.
- **UNEXAMINED CONFOUND that this surfaced:** `4ccbeb28` (2026-07-12) switched
  sigma from the static seasonal table to dynamic per-month values, several
  floored at 1.5F. That is a real, commit-driven sigma change landing INSIDE
  the July-August period this document treats as homogeneous.
- **The sigma-noise result is too fragile to carry weight.** Within
  `ens+gaussian`/`above`, MAD(log effective sigma) is directionally lower in
  July-August, but the cells are n=16-17 vs 28, the May-June value moves
  0.766 -> 0.920 on the exclusion of any one of four rows, and a permutation
  test gives one-sided p = 0.093 at n=17. The aggregate sigma move (median
  3.554 -> 6.976 June to July, CV 1.185 -> 4.314 by August) is real; the
  claim that stratifying REVERSES it is not established.
- Removing the METAR rows leaves `between` with **n=0** in July-August, not
  n=4, so that stratum becomes uncomparable rather than merely thin.

`python .unlazy/probe_july_window.py` gates the four load-bearing figures
(the METAR shares, the May-June METAR AUC, and both gaps) plus the null. It
does NOT gate the per-stratum figures or the sigma paragraph; treat those as
ungated. Run `python .unlazy/coverage_handoff.py` for the current list.

## Still open

- **Whether composition explains the gap at all.** The nulls above say the
  corpus needs to be materially larger before this is answerable. The
  direction is consistent in every stratum and significant in none.
- Why the `above`/`below` lock-in branches also thinned after July, which
  `e395392b` does not explain. A same-day market must be scanned late in its
  city's own local day (`metar._LOCK_IN_HOUR = 14`) and nothing ever
  scheduled `cron --sameday-only` (`scan_runs` holds no `mode='cron-sameday'`
  row), which is a plausible but UNMEASURED mechanism. All 106 lock-in rows
  carry `local_hour` NULL, so that check cannot be run on this corpus, and
  `predicted_at` is pinned to the day's FIRST scan by the
  `ON CONFLICT(ticker, predicted_date)` upsert while `method` is overwritten
  by the last, so hour-of-day attribution is unsafe here in general. Day-level
  and month-level attribution ARE safe: 0 of 618 rows have
  `substr(predicted_at,1,10) != predicted_date`.
- `5a3d80b3` (2026-07-07) "Fix ECMWF silently dropped from daily forecast" — a
  FIX, so the defect predates it. DOWNGRADED: `n_members` and the
  forecast-error result both cut against a lost-member mechanism.
- `between` has n=4 in the later period, so the one stratum where the model had
  skill cannot be compared across the boundary with this corpus at all.

## How to re-derive

    python .unlazy/audit_handoff.py --all        # 16 checks, ~1s
    python .unlazy/mutate_handoff_oracle.py      # proves numeric gates can fail
    python .unlazy/mutate_prose_gates.py         # proves prose gates can fail
    python .unlazy/coverage_handoff.py           # which numeric claims are ungated
    python .unlazy/prose_coverage.py             # which prose claims are ungated

COVERAGE IS PARTIAL — run the coverage tools for current figures rather than
trusting a number written here. **An ungated figure is NOT verified by a green
run.**

Known traps, each of which has cost a run:
- `analysis_attempts` has **zero rows before July**. Any "since May" question
  must use `predictions`.
- `raw_prob` IS NOT THE PRE-CALIBRATION PROBABILITY. It is
  `round(forecast_prob + bias, 6)` — see `tracker.py:1808`. **The medians are
  rounding noise**, which shows only that `bias_correction` is ~0, NOT that
  calibration is inert.
- `outcomes.settled_at` is stored **naive** while `analyzed_at` carries a `Z`.
  Subtracting raises TypeError; a bare `except` drops every row silently.
- `settled_at` lags real resolution by ~73h. Derive resolution time from the
  ticker's own date at **midnight LOCAL STANDARD** (05:00Z eastern, 06:00Z
  central, 07:00Z mountain, 08:00Z pacific), not 00:00 UTC.
- Line citations across this repo are unchecked and drift on every edit above
  them; six were found stale on 2026-08-30.
- Open the DB read-only: `sqlite3.connect("file:...?mode=ro", uri=True)`.

**Any re-measurement must BOTH split at the July step AND stratify by condition
type.** Splitting without stratifying reproduces the confound above.
