# HANDOFF: the model's confidence collapsed in July, and calibration is not the cause

Written 2026-08-30. Self-contained on purpose — re-derive every number below
rather than citing this file. Prior handoffs in this project went stale because
figures were carried forward instead of recomputed.

## The question that started it

"It doesn't make sense that a model gets worse AFTER calibration — that goes
against all logic."

The logic is sound. The premise was subtly wrong, and finding out why exposed
something larger.

## Finding 1 — the calibration layer is a no-op, so it cannot be the cause

`predictions`, `method='ensemble'`, joined to `outcomes_valid`, temperature
ladders only. `conf` is mean `|p - 0.5|`:

| month | n | conf(our_prob) | conf(raw_prob) | within 10pp of 0.5 |
|-------|---|----------------|----------------|--------------------|
| 2026-05 | 51 | 0.2333 | 0.2378 | 15.7% |
| 2026-06 | 48 | 0.1958 | 0.1958 | 37.5% |
| 2026-07 | 56 | 0.0723 | 0.0723 | 75.0% |
| 2026-08 | 70 | 0.0775 | 0.0775 | 80.0% |

`our_prob` equals `raw_prob` from June onward. Post-calibration IS
pre-calibration. Three independent confirmations of the same fact:

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

## The prime suspect, NOT established

`ae1d5bae`, 2026-06-27:
`feat(emos): deploy EMOS calibration, disable T-scaling — fixes ensemble
under-dispersion (REL=0.046)`

It lands exactly in the June -> July gap. Fixing under-dispersion widens the
predictive distribution, and a wider distribution pushes probabilities toward
0.5. Mechanism and timing both match. The irony to keep in view: correcting
under-dispersion is a legitimate fix for a real defect, and it may have
destroyed the model's usefulness by over-correcting — better reliability,
no discrimination.

**Check this before building on it:** the backlog carries
`[PARTIALLY RESOLVED] EMOS CALIBRATION STAYS DISABLED UNTIL THE
ens_var-POPULATED TRAINING SET CLEARS 40 ROWS`. If EMOS is gated off, it
CANNOT be the cause and this whole hypothesis dies. Verify whether EMOS is
actually live on the path that produced these rows before spending time on it.

Other commits in the window, none yet examined:
- `4ccbeb28` 2026-07-12 Restore climate-derived sigma
- `5a3d80b3` 2026-07-07 Fix ECMWF silently dropped from daily forecast
- `38c64aef` 2026-06-28 regime-specific blend weights, auto-activation at 30
- `8337b87f` 2026-06-27 exclude ensemble from blend when circuit breaker OPEN
- `da935c62` 2026-06-24 prevent condition weight overfitting

`8337b87f` deserves attention alongside EMOS: if the circuit breaker is open,
the ensemble is excluded from the blend, which would also flatten output.

## What is NOT established

- **n is small.** 48 rows in June against 56 in July. A confidence shift this
  large is unlikely to be noise, but the monthly Brier differences are not
  individually significant.
- **Timing is not causation.** Five commits land in that window. The EMOS one
  merely has the best mechanism story.
- **Seasonality is unexamined.** July/August temperature spreads differ from
  May/June. A widening ensemble spread could be physical rather than a code
  change. Rule this out before blaming a commit.
- **Population drift is unexamined.** Whether July/August scanned the same
  cities and ladder types as May/June has not been checked. It should be — a
  shift toward wider brackets alone would flatten probabilities.

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

## Why this matters more than it looks

The stated no-edge conclusion for this project rests on the model having been
fairly evaluated. If the July collapse is a **bug or an over-correction rather
than the model's true skill**, then roughly half the settled corpus was
generated by a crippled model, and every aggregate spanning May-August mixes
two different systems. That does not resurrect the forecasting thesis on its
own — the model never beat the market in ANY month, including May and June
when it was confident — but it does mean the *magnitude* of the deficit is
not trustworthy, and any future re-measurement must split at 2026-06-27.

The one conclusion that survives regardless: **`edge` is negative in every
month, before and after the collapse.** The model has never beaten the market
on this corpus.
