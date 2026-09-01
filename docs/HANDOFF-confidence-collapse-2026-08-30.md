# HANDOFF: a suspected July regression in model discrimination — DIRECTION
# CONSISTENT, SIGNIFICANCE NOT ESTABLISHED

Written 2026-08-30. Self-contained on purpose — re-derive every number below
rather than citing this file. Prior handoffs in this project went stale because
figures were carried forward instead of recomputed.

---

## THE HEADLINE — read this before anything else

Everything below this section was written while chasing a *confidence*
collapse. That framing is subordinate to this one and is kept only because the
eliminations in it are still valid work. **The actual finding is a loss of
DISCRIMINATION**, which is a different and much more serious thing.

AUC — the probability the model ranks a random YES above a random NO. 0.50 is
no signal. **AUC is invariant under temperature scaling** (a strictly
increasing map fixing 0.5), so unlike every other metric in this document it
cannot be an artefact of the calibration argument that occupies the rest of it.

| period | who | n | AUC | SE | z vs 0.50 |
|--------|-----|---|-----|----|-----------|
| May-Jun | **model** | 198 | **0.6828** | 0.0377 | **+4.85** |
| May-Jun | market | 198 | 0.6853 | 0.0376 | +4.93 |
| Jul-Aug | **model** | 143 | **0.5321** | 0.0484 | **+0.66** |
| Jul-Aug | market | 143 | 0.7271 | 0.0424 | +5.35 |

- model, MayJun - JulAug = **+0.1507**, SE 0.0613, **z = +2.46 — SIGNIFICANT**
- market, MayJun - JulAug = -0.0418, SE 0.0567, z = -0.74 — not significant

Monthly: May 0.6215 (n=51) | Jun 0.6973 (147) | Jul 0.5497 (69) | Aug 0.5085 (74).
Pooled model AUC 0.6178 (n=341, z=+3.89); pooled market 0.7049 (z=+7.31).

### What that says

1. **In May-June the model discriminated as well as the market did** — 0.6828
   against 0.6853. Not proven equal (the SEs are ~0.038, so the interval is
   wide), but there is no measurable gap. **SEE THE COMPOSITION QUALIFICATION
   BELOW — this pooled figure is weighted by `between` markets that are
   nearly absent from the later period.**
2. **In July-August the model fell to chance** (0.5321, z=+0.66) while the
   market on the SAME markets stayed strong (0.7271, z=+5.35). The later
   markets were not harder on the market's own showing. **CAUTION: an earlier
   draft ended this item with a flat assertion that the model had specifically
   broken. That assertion is withdrawn by the composition qualification below
   and must not be read as a conclusion.**
3. **IF the effect is real it is a REGRESSION rather than a limitation** —
   more data would not fix a regression, it would only average a working model
   together with a broken one, which is what every May-August aggregate in
   this project silently does. **This item is CONDITIONAL.** An earlier draft
   stated it flatly as "This is a REGRESSION, not a limitation"; the
   difference-in-differences bootstrap below returns p about 0.21, so the
   antecedent is not established.
4. **It cannot be calibration.** AUC is calibration-invariant by construction.
   ONE PRECISION CAVEAT, found by gating this claim rather than asserting it:
   the invariance is exact in real arithmetic and exact in float64 at most
   temperatures — delta 0.0 at T=2 and T=10 on this corpus — but NOT at every
   T. At T=4.6, three of the 303 distinct stored probabilities round together
   under the transform, creating ties worth **3.4e-05** of AUC. The argument
   is unaffected at that magnitude; the word "EXACTLY" is not literally true
   in floating point, and the gate for this claim uses a 1e-3 tolerance rather
   than 0 for that reason.
   Any explanation involving T, EMOS, Platt or blend weights is ruled out on
   mathematics, not on evidence.

### The coherent story underneath

In May-June the model matched the market on RANKING (AUC) while losing on
Brier (edge -0.0459 May, -0.0240 Jun). Equal discrimination, worse
calibration — which is the *fixable* combination, and precisely what a
temperature around 5 addresses. On this reading the model was close to parity
in June, and then lost the ranking ability that made that possible.

### What it does to the project's no-edge conclusion

It does not overturn it — the model never beat the market on Brier in ANY
month, including May and June. But it damages the evidence: roughly half the
settled corpus was produced by a model with no discrimination, so every pooled
May-August figure mixes two different systems and the Jul-Aug half is
measuring a bug. **Any re-measurement must split at the July step.**

### MAJOR QUALIFICATION — the drop is substantially a COMPOSITION effect

Added 2026-08-30 by a hardening pass that went looking for the one confound
the earlier version listed as unchecked. It found it. **Read this before
acting on the headline table above.**

The condition-type mix is almost completely different across the boundary:

| condition | May-Jun share | Jul-Aug share |
|-----------|---------------|---------------|
| `between` | **55.6%** | **2.8%** |
| `above` | 26.3% | 59.4% |
| `below` | 14.1% | 37.8% |

Family drifted too (KXHIGH 65.7% -> 45.5%, KXLOWT 34.3% -> 54.5%). Ladder
width did not: `between` markets are 2.00F wide in both periods.

Stratifying AUC by condition type changes the reading:

| condition | period | who | n | AUC | SE | z vs 0.50 |
|-----------|--------|-----|---|-----|----|-----------|
| above | May-Jun | model | 52 | 0.6989 | 0.0723 | +2.75 |
| above | Jul-Aug | model | 85 | 0.5786 | 0.0620 | +1.27 |
| below | May-Jun | model | 28 | **0.5444** | 0.1144 | **+0.39** |
| below | Jul-Aug | model | 54 | 0.4731 | 0.0793 | -0.34 |
| between | May-Jun | model | 110 | 0.6378 | 0.0545 | +2.53 |
| between | Jul-Aug | model | **4** | — | — | too few |

WHAT THIS MEANS:
1. **The model's May-June skill was concentrated in `between` markets**
   (n=110, AUC 0.638) and `above` (n=52, 0.699). On `below` it NEVER
   discriminated — 0.5444 at z=+0.39 in its best period.
2. **`between` all but disappeared**, 110 rows to 4. The pooled May-June AUC
   is therefore heavily weighted by a market type that is absent later.
3. **Within `above`, the drop is 0.6989 -> 0.5786** — real in direction, but
   the difference SE is ~0.095, so **z is about 1.27. NOT SIGNIFICANT.**
4. So the pooled drop of -0.1507 at z=+2.46 **overstates the evidence for a
   regression.** A large part of it is the mix moving away from the one
   condition type the model was good at.

THE LAST SURVIVING CLAIM WAS ALSO TESTED, AND IT DOES NOT HOLD EITHER.
The argument for keeping this as a qualification rather than a retraction was
that **the market's AUC did not fall in any stratum** — `above` 0.7358 ->
0.7530, `below` 0.5861 -> 0.6517 — so the model and market diverged in
OPPOSITE directions on the same rows, which composition alone cannot produce.
That is a difference-in-differences, and it was measured properly rather than
eyeballed (`.unlazy/did_bootstrap.py`):

    statistic = (model_MayJun - model_JulAug) - (market_MayJun - market_JulAug)
    averaged over the `above` and `below` strata, cluster-bootstrapped by
    ticker so rows of one settlement are not treated as independent.

    observed DiD  = +0.1373   (positive = model deteriorated vs the market)
    95% CI        = [-0.0794, +0.3446]   2000 resamples
    two-sided p   ~ 0.21

**THE CONFIDENCE INTERVAL INCLUDES ZERO. The divergence is NOT established.**

SO THE HONEST STATE OF THE HEADLINE, after three rounds of testing it:
- Pooled, the drop is large (0.6828 -> 0.5321) and nominally significant
  (z=+2.46), but it is **confounded** by the `between` share collapsing from
  55.6% to 2.8%.
- Within `above`, the drop is 0.6989 -> 0.5786, **z about 1.27 — not
  significant**.
- Within `below`, the model never discriminated in either period.
- The model-versus-market divergence, the last thing standing, is
  **p about 0.21 — not significant**.

**DO NOT PRESENT "THE MODEL BROKE IN JULY" AS ESTABLISHED.** What is true is
that every measurement points the same DIRECTION — model down, market up, in
both strata — and not one of them reaches significance once the confound is
handled and clustering is respected. That is a hypothesis worth testing on
more data, not a finding.

HOW TO SETTLE IT: a within-stratum comparison needs enough `between` rows in
the later period, which this corpus does not have (n=4). Any future
re-measurement must stratify by condition type rather than pool, and must
cluster by ticker.

A GENUINELY NEW AND ACTIONABLE FINDING FROM THIS: the model's discrimination
was always concentrated in `between` markets. That is where it had edge and
where a future effort should look first — not in `below`, where it has never
beaten a coin flip in any period.

### Honest limits on this finding

- n = 198 and 143; SEs 0.038-0.048. The May-June model-vs-market comparison is
  within noise, so "as good as the market" is *not measurably worse*, not
  proven equal.
- Many splits were examined on 2026-08-30 before this one was found. Treat
  z = +2.46 as weaker than it looks.
- **Population drift WAS the obvious confound, and it has been TESTED and
  REFUTED.** The recording regime genuinely did change: May-June recorded only
  markets where a paper trade was placed (51/51 and 147/147 = 100%), July
  recorded predictions with NO trades at all (0/69 — trading was paused
  2026-07-01 to 07-31 for travel), and August is 63/74 = 85%. So the later
  population is not selected the same way, and selection on model-market
  disagreement would inflate the earlier AUC.
  Restricting BOTH halves to rows that have a paper trade — i.e. imposing the
  old regime's own selection on the new data — does not rescue the model:

  | period | who | n | AUC | SE | z vs 0.50 |
  |--------|-----|---|-----|----|-----------|
  | May-Jun | model | 198 | 0.6828 | 0.0377 | +4.85 |
  | Jul-Aug | model | **63** | **0.4849** | 0.0733 | **-0.21** |
  | Jul-Aug | market | 63 | 0.7213 | 0.0645 | +3.43 |

  Under identical selection the model is still at chance, marginally BELOW
  0.50, while the market on those same rows is still strongly discriminating.
  The drop is not a population artefact.
  ONE LIMIT ON THAT TEST: July contributes zero traded rows, so the Jul-Aug
  traded subset (n=63) is entirely AUGUST. The comparison is really May-June
  versus August, and it cannot speak to July directly.


### THE DEFECT IS IN THE TEMPERATURE->PROBABILITY STEP, NOT THE FORECAST

This narrows the search more than anything else in this document.

Raw forecast error, `|forecast_temp_f - outcomes.settled_temp_f|`, degrees F:

| month | n | median | mean | p90 |
|-------|---|--------|------|-----|
| 2026-05 | 51 | 2.65 | 2.69 | 5.50 |
| 2026-06 | 50 | 2.68 | 2.80 | 5.20 |
| 2026-07 | 56 | **1.18** | 2.01 | 4.14 |
| 2026-08 | 70 | **1.67** | 2.05 | 4.18 |

**The temperature forecast roughly HALVED its error in July** and stayed
better in August — over exactly the span where AUC fell from 0.68 to chance.
The model is forecasting the weather better than ever and converting that into
worse probabilities. So the defect is downstream of the forecast, in the step
that turns a predicted temperature into a probability.

WHAT THIS RULES OUT: any explanation that degrades the forecast itself —
a model dropping out of the blend, a data source going stale, seasonality
making the weather harder. Corroborating that, `n_members` is **238 on every one of the 56 July rows**,
spanning the collapse window, with `blend_exclusions` empty throughout — so
the ensemble did not lose a member when discrimination died.
  PRECISION NOTE, because an earlier draft overstated this as "constant 238
  from 2026-06-20 through August": it is not. June carries both 138 (23 rows)
  and 238 (21) either side of a 06-20 switch, and August carries 238 (54),
  258 (13), 208 (1) and — implausibly for a member count — **2427 (2 rows,
  2026-08-30) and 2438 (8 rows, 2026-08-28/29)**. None of that variation
  touches the June-30-to-July-2 boundary, so the conclusion stands, but the
  late-August values look like a separate defect and are not explained here. That substantially weakens
the ECMWF silent-drop lead (`5a3d80b3`), which was the best remaining
candidate before this measurement.

WHERE TO LOOK NOW: the sigma / distribution-width step. Note the asymmetry
that makes this precise — a sigma that is uniformly WRONG compresses
probabilities but PRESERVES their ranking, so it cannot move AUC. Only a
sigma that became noisy ROW-TO-ROW can hold forecast accuracy constant while
destroying discrimination. That is the specific signature to hunt.

WHAT THE STORED SIGMA FIELDS COULD AND COULD NOT SHOW: `ens_var` is the only
sigma-like column populated on both sides of the boundary, and it is stable
(median 4.39 Jun, 4.90 Jul, 4.07 Aug) with a consistently high row-to-row
CV of 0.77-0.84 throughout — no step. `ensemble_spread_f`, `implied_sigma`
and `model_disagreement_f` are only populated from July onward, so they cannot
be compared across the boundary at all. `implied_sigma` is worth attention on
its own terms: median 3.33 (Jul) and 1.91 (Aug) with CV 1.19-1.33, which is
extremely noisy, and `fit_market_implied_distribution()` already has an open
backlog entry for returning a degenerate fit on ~19% of rows.

A WARNING FOR WHOEVER RUNS THESE QUERIES: an earlier pass of this analysis
reported a dramatic scale change in `model_disagreement_f` (~74 in May-June
versus ~1 in July-August) and nearly filed it as a semantic-change defect. It
was an off-by-one in the analysis script — five column names enumerated
against six selected columns, so the field was reading `forecast_temp_f`, and
"74" was simply the temperature. `model_disagreement_f` is NULL before July.
Check column alignment before believing any cross-boundary jump.

### Therefore the priority question is unchanged but now much more valuable

**What changed between 2026-06-30 03:34 and 2026-07-02 19:07?** That window
still contains zero commits. It now sits between a model with real,
market-matching skill and a model with none.

---

## The question that started it

"It doesn't make sense that a model gets worse AFTER calibration — that goes
against all logic."

The logic is sound. The premise was subtly wrong, and finding out why exposed
something larger.

## RETRACTED: "Finding 1 — the calibration layer is a no-op"

**The reasoning below is unsound and the conclusion is withdrawn.** It is kept
because the numbers are real and the error is instructive.

`raw_prob` IS NOT THE PRE-CALIBRATION PROBABILITY. It is reconstructed as
`raw_prob = round(forecast_prob + bias_correction, 6)` — see
`weather_markets.py:18614` and the comment at `weather_markets.py:15495`
citing `tracker.py:1528`, and `tests/test_tracker.py:1449` which states the
relation outright. So `our_prob ≈ raw_prob` demonstrates only that
**`bias_correction` is approximately zero**. It says NOTHING about whether
temperature scaling, Platt, or blend calibration ran.

Measured magnitude of `|our_prob - raw_prob|`, ensemble, temperature ladders:

| month | n | median | mean | max | rows > 0.01 |
|-------|---|--------|------|-----|-------------|
| 2026-05 | 51 | 2.4e-7 | 0.0049 | 0.1231 | 2 |
| 2026-06 | 48 | 2.0e-7 | 2.1e-7 | 4.9e-7 | 0 |
| 2026-07 | 57 | 2.4e-7 | 2.4e-7 | 5.0e-7 | 0 |
| 2026-08 | 78 | 3.1e-7 | 0.0010 | 0.0776 | 1 |

The medians are rounding noise from that `round(..., 6)`. **So the question
"is calibration degrading the model" is OPEN, not answered.** Two narrower
claims do survive and should not be over-read: `data/analysis_calibration.json`
is an untrained identity map, and `forecast_prob == forecast_prob_precal` to
0.0 on all 40 `analysis_attempts` rows carrying both. Both concern the ml_bias
section-9c stage ONLY. Neither covers temperature scaling.

## A CONFIRMED CODE DEFECT (but NOT the cause): T is fit on its own output

SUPERSEDED AS AN EXPLANATION. An earlier draft called this "the leading
hypothesis" for the July collapse. It cannot be: the headline finding is a
loss of AUC, and AUC is invariant under temperature scaling by construction,
so no value of T can produce it. What follows is still a real, filed defect
worth fixing on its own merits — it is simply not the answer to July.

`backlog.txt` ~L47711:

> train_all_temperature_scaling FITS T ON ITS OWN PRIOR OUTPUT, AND _fit_T's
> LOWER BOUND CANNOT EXPRESS THE CORRECTION THE UNBIASED DATA ASKS FOR

Its own priority note records that batch-87 froze `global/above/below/between`
while a real analysis calibration exists — **"but the freeze lifts the moment
that fit declines, and sameday/hourly were never frozen and are not covered by
either half below."**

Current `data/temperature_scale.json`: `sameday` **T = 3.8294** (n=102),
`global` T = 4.6013 (n=68), `above` T = 1.2739 (n=44). Most predictions in
this corpus are same-day, and same-day is the key that was never frozen.

MECHANISM, which is a genuine positive feedback loop: T divides the logit, so
a large T flattens output toward 0.5. If the next fit trains on that flattened
output, it sees a model that discriminates poorly, and asks for MORE
flattening. T ratchets up, confidence ratchets down, and it never recovers —
which matches the observed series, where confidence fell and stayed fallen.
A T near 4-5 is not a plausible correction for a sane forecaster; it is what a
fitter emits when it is being fed its own damage.

WHY THIS ALSO ANSWERS THE ORIGINAL OBJECTION. "A model cannot get worse from
being calibrated" is correct for calibration fitted on independent data. It is
FALSE for a calibrator fitted on its own prior output — that is not
calibration, it is a feedback loop, and it degrades monotonically. The
objection was right and it correctly identified that something was structurally
wrong.

WHAT MUST BE CHECKED BEFORE ACCEPTING THIS — it is a hypothesis:
1. **Is T actually applied to these rows?** Find where T is applied relative
   to the `forecast_prob` write. If T-scaling sits upstream of the stored
   probability, it is live; if the same-day path never calls it, this dies.
2. **What was `sameday` T during July?** `data/.history/` retains only the
   last 10 snapshots and the oldest is 2026-08-01T20:35 (T=1.0, n=0), so July
   is NOT recoverable there. Look for another source or reconstruct from the
   fit's own inputs.
3. **The Aug-01 snapshot shows T=1.0 with n=0**, meaning T-scaling was inert
   at that instant — which does not fit a July collapse caused by T. Either
   the collapse has a different July cause and T sustains it from August, or
   the July `sameday` key was non-1.0 while `global` was not. RESOLVE THIS.
   It is the strongest evidence AGAINST the hypothesis.
4. There is still **no confidence step at 2026-08-02** when global T went
   1.0 -> 6.41. Explain that before accepting T as the mechanism.

## Superseded: the original Finding 1 numbers

`predictions`, `method='ensemble'`, joined to `outcomes_valid`, temperature
ladders only. `conf` is mean `|p - 0.5|`:

| month | n | conf(our_prob) | conf(raw_prob) | within 10pp of 0.5 |
|-------|---|----------------|----------------|--------------------|
| 2026-05 | 51 | 0.2333 | 0.2378 | 15.7% |
| 2026-06 | 48 | 0.1958 | 0.1958 | 37.5% |
| 2026-07 | 56 | 0.0723 | 0.0723 | 75.0% |
| 2026-08 | 70 | 0.0775 | 0.0775 | 80.0% |

`our_prob` equals `raw_prob` from June onward. Post-calibration IS
pre-calibration. Three confirmations — note (1) and (3) are the same fact
measured on two different tables rather than independent evidence, and (2) is
the mechanism that explains both:

1. The column equality above.
2. `data/analysis_calibration.json` is
   `{"multiday": {"a": 1.0, "b": 0.0, "n": 0, "_uncalibrated": true}}` —
   an untrained identity map.
3. On `analysis_attempts`, `forecast_prob == forecast_prob_precal` with
   max |difference| exactly 0.0 across all 40 rows carrying both.

**[RETRACTED — see the retraction section above. This sentence read "So no
calibration stage is degrading anything. It is a pass-through." It does not
follow: `raw_prob` is `our_prob + bias_correction`, so the comparison it rests
on never measured calibration at all. Kept verbatim only so the error is
legible.]**
Note the trap this creates: `tracker.get_analysis_calibration_data()`
(`tracker.py` ~4930) trains that calibrator FROM `analysis_attempts` with
`days_out >= 1`. The moment cron's weekly block fits it, it stops being a
no-op and any analysis of the multi-day population becomes in-sample.

## Superseded: the confidence collapse (a symptom, not the finding)

This section was the original headline. It is demoted: confidence compression
is a real observation but it is downstream of the discrimination loss above.
Raw model confidence collapsed between June and July: **0.1958 -> 0.0723**,
and the share of predictions sitting within 10 points of a coin flip went
**37.5% -> 75%**. It has not recovered (0.0775 in August).

**CORRECTION — an earlier draft said "that explains the accuracy drop". It
does not, and the error is worth stating because it is the same one the
headline finding corrects.** Compressing probabilities toward 0.5 is a
monotone transform: it cannot move a prediction across the 0.5 threshold, so
it leaves accuracy EXACTLY unchanged. An accuracy drop therefore requires
genuine loss of discrimination, which is what the AUC section measures.
Confidence and accuracy fell together because both are downstream of that
loss — not because one caused the other. The table below is kept as the
original observation:

| month | n | Brier(model) | Brier(market) | edge | accuracy |
|-------|---|--------------|---------------|------|----------|
| 2026-05 | 51 | 0.2709 | 0.2250 | -0.0459 | 58.8% |
| 2026-06 | 48 | 0.2666 | 0.2426 | -0.0240 | 60.4% |
| 2026-07 | 56 | 0.2480 | 0.2181 | -0.0300 | 50.0% |
| 2026-08 | 70 | 0.2462 | 0.1978 | -0.0484 | 52.9% |

Accuracy fell ~60% -> ~51%: a model emitting 0.48 and 0.52 is a coin flip by
construction. Brier *improved* over the same span — **for the ensemble population
specifically** (0.2688 -> 0.2470); pooled across ALL methods it slightly
worsens (0.2653 -> 0.2670), a scope distinction surfaced by gating this
sentence rather than asserting it. Ensemble is the right population here
because the table beside it is ensemble-only. That improvement is not a
contradiction — hedging toward 0.5 caps the penalty on every wrong answer.
**Brier improving while accuracy collapses is the signature of a model losing
discrimination, not gaining skill.** The market's Brier improved faster
(0.2250 -> 0.1978), so the gap widened throughout.

## The window, pinned to two days

Daily confidence, ensemble only, temperature ladders. `our_prob` values are
shown because the step is more obvious in the raw numbers than in the mean:

| date | n | conf | our_prob values |
|------|---|------|-----------------|
| 2026-06-28 | 3 | 0.3483 | 0.898, 0.946, 0.701 |
| 2026-06-29 | 2 | 0.3674 | 0.031, 0.234 |
| 2026-06-30 | 2 | **0.4623** | 0.038, **0.963** |
| 2026-07-02 | 6 | **0.0742** | 0.336, 0.578, 0.367, 0.523, ... |
| 2026-07-03 | 1 | 0.1610 | 0.339 |
| 2026-07-05 | 6 | 0.0722 | 0.558, 0.492, 0.798, 0.554, ... |

Last extreme prediction: **2026-06-30 03:34:15** (`our_prob` 0.963).
First flat prediction: **2026-07-02 19:07:45** (`our_prob` 0.336).
It never recovers. This is a step change, not a drift.

**There are ZERO commits between those two timestamps.** `git log --since
'2026-06-30 03:34' --until '2026-07-02 20:00'` is empty. That is the single
most useful fact here: whatever changed was **data, configuration, external
input, or accumulated state — not code**.

## Suspects ELIMINATED, with the evidence

Each of these was a leading hypothesis and each is dead. Do not re-open one
without new evidence; the reasoning is recorded so the work is not repeated.

1. **`ae1d5bae` (2026-06-27) EMOS deployment — "fixes ensemble
   under-dispersion".** Was the prime suspect: right era, and widening a
   distribution is exactly the mechanism that flattens probabilities.
   ELIMINATED, but read the correction below before trusting the reason.
   (a) Confidence hit its series MAXIMUM on Jun 28/29/30, the three days
   AFTER the commit. NOTE this rests on **7 rows total** (3+2+2) — it is
   suggestive, not decisive on its own.
   (b) **EMOS WAS NEVER ACTIVE.** `data/emos_params.json` does not exist —
   verified 2026-08-30, there is no `emos`-named file in `data/` at all.
   Activation requires an explicit `py main.py emos-train --activate`; it
   does not auto-enable, and `cron.py:2202` only ever prints a readiness
   REMINDER "until emos_params.json exists (training done)". A method that
   never ran cannot have flattened anything. **This is the load-bearing
   reason; (a) is corroboration.**
   ONE CAVEAT ON THE SOURCE: the backlog entry describes EMOS as "caught
   and deliberately reverted the same session" and names an artefact
   `data/emos_params.json.premature_do_not_use_20260704`. That FILE DOES
   NOT EXIST on disk today. An earlier version of this paragraph cited it
   as present, having copied it out of the backlog without checking. The
   absence of `emos_params.json` is verified and sufficient; the reverted-
   artefact story is backlog testimony and is not independently confirmed.
   CORRECTION TO AN EARLIER DRAFT OF THIS FILE: it eliminated EMOS by
   claiming the 40-row gate crossed on 2026-07-05, after the collapse. That
   used the wrong column. `_EMOS_TRAIN_GATE = 40` at `cron.py:2218` counts
   **`ens_mean`** rows, not `ens_var`; cumulative `ens_mean` rows crossed 40
   on **2026-06-28**, i.e. BEFORE the collapse. Had EMOS been active, that
   timing would have made it MORE plausible, not less. The elimination
   survives only because EMOS never activated.
2. **`d5a6440f` (2026-06-30 00:46) pricing field fix
   (`yes_bid_dollars`/`yes_ask_dollars`).** ELIMINATED: the 02:13 and 03:34
   predictions later that same morning were still extreme (0.038, 0.963).
3. **`TRADING_PAUSED` / shadow-mode selection.** Trading was paused
   2026-07-01 to 2026-07-31 for travel, which matches the onset almost
   exactly, and the obvious story is that paused mode logs marginal
   predictions that live mode filters out. **WEAKENED, NOT ELIMINATED** —
   an earlier draft of this file called it eliminated and the argument does
   not hold as stated. The evidence: August ran with `is_shadow = 0` (71 of
   78 rows, trading resumed) and confidence STAYED collapsed at 0.0700, so
   the effect outlived the pause.
   Monthly: May `is_shadow=0` conf 0.2333 | Jun `0` 0.1958 |
   Jul `1` 0.0739 | Aug `0` **0.0700**.
   WHY THAT IS NOT CONCLUSIVE: it assumes nothing else sustains the
   flatness in August. Something else plausibly does — see the temperature
   scaling section below — and a pause can also strand persistent state
   rather than reverting cleanly when the flag clears. Treat this as the
   best-supported remaining hypothesis for the JULY onset, not as dead.
4. **Loss of the `obs` component from the blend.** Looked compelling on a
   day-by-day read: high-confidence days carry `{"obs": 0.87, ...}` and flat
   days carry `{"ensemble": .., "gaussian": .., "climatology": ..}`.
   ELIMINATED by the aggregate, which points the other way — blends
   CONTAINING obs have LOWER mean confidence (0.1135, n=88) than blends
   without it (0.1425, n=137), and the share of predictions carrying obs
   ROSE across the collapse: May 0%, Jun 43.2%, **Jul 62.5%**, Aug 45.9%.
   POPULATION NOTE: this analysis requires `blend_sources IS NOT NULL`, so
   its June n is **44**, not the 48 in the headline table above. Same month,
   different filter. Verified: June ensemble rows are 48 both unjoined and
   joined to settled outcomes, and 44 with `blend_sources` populated.
   A warning attached to this one: it was called a confirmed finding on the
   strength of a hand-read of ~15 days at n=1-6 per day, before the aggregate
   was computed. That is the same error that produced two other retractions
   in this project on the same day.

## Still open, none examined

- **`5a3d80b3` (2026-07-07) "Fix ECMWF silently dropped from daily
  forecast".** This is a FIX, so the defect it repairs predates it. If ECMWF
  was silently dropping out from around Jul 1, the blend lost a member — a
  plausible flattening mechanism with no commit at the onset, which fits the
  empty-window constraint. **Best remaining lead.** Find when the bug was
  introduced, not when it was fixed.
- **`38c64aef` (2026-06-28) regime blend weights, auto-activation at 30
  settled trades**, and **`2356f77e` PDO/PNA auto-activation at 20 west-coast
  settled trades.** Auto-activating features change behaviour with no commit
  at the moment of change, which is exactly the signature here. Find the
  settled-trade counts as a function of date and see whether either crossed
  on Jul 1-2. Note this is the SAME reasoning that made EMOS attractive, and
  EMOS died on its dates — so check the dates FIRST.
- **`learned_weights.json`** may have been refit during the pause and stuck.
  It has file history (`4c9a51fa` added `atomic_write_json_with_history`
  keeping the last 10 states) — read the history and look for a Jul 1-2 write.
- **External data change.** No commit is required for Open-Meteo to change a
  model, or for a source to start returning wider spreads. Unfalsifiable from
  the repo alone, but `ensemble_spread_f` and `ens_var` are stored per row and
  can be trended across the boundary.
- **Population / market-composition drift.** Whether Jul/Aug scanned the same
  cities and ladder widths as May/Jun is unchecked. Wider brackets alone
  flatten probabilities.

## What is NOT established

- **n is small.** 48 rows in June against 56 in July. A confidence shift this
  large is unlikely to be noise, but the monthly Brier differences are not
  individually significant.
- **No cause has been identified.** Four hypotheses were tested and none
  survived as the explanation. The window contains no commits. This document
  narrows the search; it does not answer it.
- **The eliminations rest on small n.** The EMOS timing argument uses 7 rows.
  The daily table runs n=1-6 per day. Only the monthly aggregates and the
  step itself are on firmer ground.
- Seasonality and population drift are unexamined; both are listed under
  "still open" above rather than repeated here.

## How to re-derive

The confidence table: `predictions` JOIN `outcomes_valid` on ticker,
`settled_yes IN (0,1)`, tickers `LIKE 'KXHIGH%' OR 'KXLOWT%'`,
`method='ensemble'`, grouped by `strftime('%Y-%m', predicted_at)`, computing
mean `|our_prob - 0.5|` and mean `|raw_prob - 0.5|`.

Known traps in this database, each of which has cost a run:
- `analysis_attempts` has **zero rows before July**. Any "since May" question
  must use `predictions`. This is why the first attempt at this analysis
  returned only two months.
- `outcomes.settled_at` is stored **naive** while `analyzed_at`/`created_time`
  carry a `Z`. Subtracting raises TypeError, and a bare `except` silently
  drops every row and looks like a filter bug.
- `settled_at` lags real resolution by a median ~73h. Derive resolution time
  from the ticker's own date, at **midnight LOCAL STANDARD** (05:00Z eastern,
  06:00Z central, 07:00Z mountain, 08:00Z pacific) — not 00:00 UTC. See the
  close_time entry at the top of `backlog.txt`.
- Open the DB read-only: `sqlite3.connect("file:...?mode=ro", uri=True)`.

## What the deeper commit research actually produced

Elimination, not identification. Four leading suspects are dead on dates or
on aggregates, and the window is pinned to a 2-day gap containing no commits
at all. That empty window is the finding: it redirects the search away from
the commit log entirely and toward accumulated state, config, and external
inputs. A new session should start from the "still open" list above and NOT
re-derive the eliminated four.

## Temperature scaling: a second, separate mechanism — and a trap

This was missed entirely by the first two drafts and it changes how the
May-August series should be read.

`ae1d5bae` did not only deploy EMOS. Per the backlog entry "EMOS CALIBRATION
STAYS DISABLED...", that same commit **reset `temperature_scale.json`'s T to
1.0 (identity) across the board** as a handoff to EMOS — and EMOS was then
reverted. So from 2026-06-27 there was NO temperature scaling and NO EMOS:
that is the mechanical explanation for Finding 1's `our_prob == raw_prob`.

Then temperature scaling came back, hard, and NOT during July:

| snapshot | global T | n | sameday T |
|----------|----------|---|-----------|
| 2026-08-01T20:35 | **1.0** | 0 | 1.0 |
| 2026-08-02T02:56 | **6.4136** | 53 | — |
| 2026-08-03T16:02 | 5.3570 | 62 | — |
| current (`data/temperature_scale.json`) | **4.6013** | 68 | 3.8294 |

A T near 5 divides logits by 5 and crushes probabilities toward 0.5. So there
are potentially **two different regimes**, not one phenomenon:
- **July**: T = 1.0, EMOS never active, no calibration at all — yet
  probabilities are flat. Cause UNKNOWN.
- **August**: T = 4.6-6.4 is live and is a sufficient mechanism for flatness
  on its own.

TWO CONSTRAINTS THAT COMPLICATE THIS, both measured, both to be respected:
1. **There is no confidence step at 2026-08-02.** Daily confidence is already
   ~0.03-0.10 in late July and stays ~0.04-0.14 through August. If T-scaling
   were newly crushing the output, a step should be visible and is not.
2. **`our_prob` still equals `raw_prob` through August**, so whatever
   T-scaling does, it is NOT applied between those two stored columns. Either
   it is upstream of where `raw_prob` is captured, or it is not reaching this
   path. **Resolve this before building on the T-scaling story** — find where
   T is applied relative to the `raw_prob` write.

THE TRAP FOR THE NEXT SESSION: because August has its own candidate
mechanism, "the flatness persisted into August" is NOT by itself proof that a
July-specific cause (such as the trading pause) is innocent. An earlier draft
of this file made exactly that inference and it has been downgraded above.

WHAT CANNOT BE RECOVERED: `data/.history/` keeps only the last 10 snapshots
per file, and the oldest surviving `temperature_scale_*` is
**2026-08-01T20:35**. July's values have rotated out. Do not spend time
hunting for them there.

## Temperature scaling: a self-training loop, and what the snapshots do NOT show

Separate from the July question, and NOT a cause of it — AUC is
calibration-invariant, so nothing in this section can explain the
discrimination loss in the headline. The self-training loop here is confirmed
in code; the runaway it would predict is NOT confirmed in the data.

`data/.history/temperature_scale_*.json`, every surviving snapshot:

| snapshot | sameday T | n | global T | n |
|----------|-----------|---|----------|---|
| 2026-08-01T20:35 | **absent** | — | 1.000 | 0 |
| 2026-08-02T02:56 | 3.423 | 71 | 6.414 | 53 |
| 2026-08-03T16:02 | 3.258 | 88 | 5.357 | 62 |
| 2026-08-08T13:05 | 3.258 | 88 | 5.357 | 62 |
| 2026-08-10T05:30 | 3.320 | 93 | 4.185 | 65 |
| 2026-08-14T17:28 | 3.829 | 102 | 4.601 | 68 |
| 2026-08-16T01:27 | 3.849 | 111 | 5.558 | 78 |
| 2026-08-16T16:12 | 3.849 | 111 | 5.200 | **40** |
| 2026-08-20T21:53 | **5.265** | **78** | 4.755 | 79 |

THREE THINGS ARE WRONG HERE:

1. **The self-training loop is confirmed IN CODE. The ratchet is NOT confirmed
   in the data, and an earlier version of this section wrongly claimed it was.**
   CONFIRMED: `train_all_temperature_scaling`'s sameday query is
   `SELECT p.our_prob, o.settled_yes FROM predictions p JOIN outcomes_valid o
   ... WHERE p.days_out = 0 AND (p.method IS NULL OR p.method !=
   'metar_lockout')`. `our_prob` is the STORED POST-CALIBRATION value — the
   output `apply_temperature_scaling` produced. So T is fit on data that T
   itself shaped. That is exactly the mechanism `backlog.txt` ~L47711
   describes ("FITS T ON ITS OWN PRIOR OUTPUT"), on the `sameday` key that the
   same entry says was never frozen. The loop exists.
   NOT CONFIRMED: that it produces a runaway ratchet. The claim "sameday T
   climbs 3.423 -> 5.265" is true only as endpoints and is misleading. The
   actual series is 3.423, 3.258, 3.258, 3.320, 3.829, 3.849, 3.849, 5.265 —
   broadly flat with one late jump that coincides with n falling 111 -> 78.
   And `global` moves the OTHER WAY over the same span, 6.414 -> 4.755. A
   genuine runaway would show on every key; it shows on none.
   ALSO NOT SUPPORTED, and briefly asserted during the 2026-08-30 analysis
   before being checked: "T spikes when n drops". Pooled across all 39 fits, Pearson
   r(n, T) = **+0.406** — the opposite sign — though that pooled figure is
   itself confounded by key (`above` runs T~1.2-1.7, `global` T~4-6), so it
   is Simpson's paradox and should not be cited in either direction.
   WHAT IS SAFE TO SAY: the loop is real in code; T values on `global` and
   `sameday` are large enough (3-6) to compress probabilities materially; and
   T is unstable across refits. Whether the loop is DRIVING that instability
   is unproven on 9 snapshots spanning 19 days. **Do not present the ratchet
   as established.** The way to settle it is to refit T on a
   pre-calibration probability column and compare against the live series.
2. **The training n moves BACKWARDS between fits** — sameday 111 -> 78, global
   78 -> 40 on the same day. A calibration set that shrinks while the corpus
   grows means the population is being re-selected between runs, not
   accumulated. Nothing in this document explains that and it is not
   accounted for anywhere in the backlog. **Treat it as an independent
   defect.**
3. **The docstring contradicts the trainer.** `apply_temperature_scaling`
   (ml_bias.py:848) justifies the separate sameday pool by saying it is
   "fitted only on METAR-derived probabilities" whose distribution is "sharp,
   near 0/1", and warns that "applying multi-day T=3+ would wrongly compress
   METAR probs toward 0.5 and under-size same-day bets". But
   `train_all_temperature_scaling` **explicitly EXCLUDES `metar_lockout`
   rows** from that pool, with its own stated rationale (the METAR-locked
   branch bypasses section 7b, so it would be training on data the transform
   never touches). Both pieces of reasoning are individually defensible; the
   docstring is simply describing a population the trainer does not use, and
   sameday T is now 3.8-5.3, i.e. exactly the "T=3+" the docstring warns is
   wrong to apply. Anyone reasoning from that docstring will reach a false
   conclusion — it did so during the 2026-08-30 analysis.

WHAT THIS DOES AND DOES NOT EXPLAIN. It does NOT explain July: on 2026-08-01
the sameday key was ABSENT and global T was 1.0 with n=0, so temperature
scaling was inert through July. That is now the second independent
confirmation that T-scaling is not the July cause. It DOES give August an
active degradation mechanism of its own, and it explains the absence of a step
at 2026-08-02: July was already flat from an unknown cause, so switching on a
compressor produced no visible discontinuity — it merely held it there.

SO THERE ARE TWO PROBLEMS, NOT ONE:
- **July onset (2026-06-30 -> 2026-07-02): cause still unknown.**
- **August onward: T-scaling is live and its self-training loop is confirmed
  IN CODE (the fitter reads `our_prob`), filed as L47711. The RUNAWAY that
  loop would predict is NOT confirmed in the data** — sameday is broadly flat
  with one late jump and `global` moves the other way. Worth fixing on its own
  merits, and it cannot be the July cause because AUC is calibration-invariant.

## Already-filed related work — read before starting

The backlog entry "EMOS CALIBRATION STAYS DISABLED UNTIL THE ens_var-POPULATED
TRAINING SET CLEARS 40 ROWS" (`backlog.txt` ~L9854) documents a Brier
degradation found 2026-07-31 — two consecutive weeks over the P10.3 alert
threshold at **0.2329 and 0.2804**. That is very likely the same event this
document is chasing, observed from the alerting side seven weeks earlier. Its
2026-08-18 and 2026-08-22 updates also record that the real EMOS go-live bar
was raised to ~80 rows (not 40), and that a live re-check on 2026-08-22 found
56. Start there rather than re-deriving it.

## Why this matters more than it looks

The stated no-edge conclusion for this project rests on the model having been
fairly evaluated. If the July collapse is a **bug or an over-correction rather
than the model's true skill**, then roughly half the settled corpus was
generated by a crippled model, and every aggregate spanning May-August mixes
two different systems. That does not resurrect the forecasting thesis on its
own — the model never beat the market in ANY month, including May and June
when it was confident — but it does mean the *magnitude* of the deficit is
not trustworthy, and any future re-measurement must split at the step itself,
between 2026-06-30 and 2026-07-02 — NOT at the 2026-06-27 EMOS commit, which
an earlier draft of this file wrongly named as the boundary.

The one conclusion that survives regardless: **`edge` is negative in every
month, before and after the collapse.** The model has never beaten the market
on this corpus.
