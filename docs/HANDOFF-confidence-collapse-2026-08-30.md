# HANDOFF: the model's confidence collapsed in July, and calibration is not the cause

Written 2026-08-30. Self-contained on purpose — re-derive every number below
rather than citing this file. Prior handoffs in this project went stale because
figures were carried forward instead of recomputed.

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

## THE LEADING HYPOTHESIS: temperature scaling fits T on its own output

This is a filed, known code defect, not a new conjecture. `backlog.txt` ~L47711:

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

**So no calibration stage is degrading anything. It is a pass-through.**
Note the trap this creates: `tracker.get_analysis_calibration_data()`
(`tracker.py` ~4930) trains that calibrator FROM `analysis_attempts` with
`days_out >= 1`. The moment cron's weekly block fits it, it stops being a
no-op and any analysis of the multi-day population becomes in-sample.

## Finding 2 — what actually happened

Raw model confidence collapsed between June and July: **0.1958 -> 0.0723**,
and the share of predictions sitting within 10 points of a coin flip went
**37.5% -> 75%**. It has not recovered (0.0775 in August).

That explains the accuracy drop, which is the symptom originally noticed:

| month | n | Brier(model) | Brier(market) | edge | accuracy |
|-------|---|--------------|---------------|------|----------|
| 2026-05 | 51 | 0.2709 | 0.2250 | -0.0459 | 58.8% |
| 2026-06 | 48 | 0.2666 | 0.2426 | -0.0240 | 60.4% |
| 2026-07 | 56 | 0.2480 | 0.2181 | -0.0300 | 50.0% |
| 2026-08 | 70 | 0.2462 | 0.1978 | -0.0484 | 52.9% |

Accuracy fell ~60% -> ~51%: a model emitting 0.48 and 0.52 is a coin flip by
construction. Brier *improved* over the same span, which is not a
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

## CONFIRMED LIVE DEFECT: the temperature ratchet, visible in the snapshots

Separate from the July question. This one is measured, not hypothesised, and
it is degrading the model right now.

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

1. **The ratchet is real and observable.** sameday T climbs 3.423 -> 5.265 in
   under three weeks. This is the mechanism `backlog.txt` ~L47711 describes
   ("FITS T ON ITS OWN PRIOR OUTPUT"), on the `sameday` key that the same
   entry says was never frozen. A larger T flattens output; the next fit reads
   the flattened output and asks for a larger T still.
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
   conclusion — it did so in this session.

WHAT THIS DOES AND DOES NOT EXPLAIN. It does NOT explain July: on 2026-08-01
the sameday key was ABSENT and global T was 1.0 with n=0, so temperature
scaling was inert through July. That is now the second independent
confirmation that T-scaling is not the July cause. It DOES give August an
active degradation mechanism of its own, and it explains the absence of a step
at 2026-08-02: July was already flat from an unknown cause, so switching on a
compressor produced no visible discontinuity — it merely held it there.

SO THERE ARE TWO PROBLEMS, NOT ONE:
- **July onset (2026-06-30 -> 2026-07-02): cause still unknown.**
- **August onward: a live, ratcheting T-scaling defect, already filed as
  L47711, now confirmed with data.** This one is actionable immediately and
  does not depend on solving July.

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
