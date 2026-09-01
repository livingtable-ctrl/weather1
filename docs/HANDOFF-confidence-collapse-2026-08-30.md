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

## Still open

- **What changed between 2026-06-30 03:34 and 2026-07-02 19:07?** Zero commits
  in that window, so look at data, config, accumulated state, or an
  auto-activating feature crossing a threshold — not the commit log.
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
  `round(forecast_prob + bias, 6)` — see `tracker.py:1630`. **The medians are
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
