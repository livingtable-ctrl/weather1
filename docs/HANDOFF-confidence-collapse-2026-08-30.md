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
   ELIMINATED TWICE. (a) Confidence hit its series MAXIMUM on Jun 28/29/30,
   the three days AFTER the commit. (b) EMOS is gated behind a 40-row
   `ens_var` training set; cumulative `ens_var`-populated rows crossed 40 on
   **2026-07-05**, three days AFTER the collapse had already begun.
2. **`d5a6440f` (2026-06-30 00:46) pricing field fix
   (`yes_bid_dollars`/`yes_ask_dollars`).** ELIMINATED: the 02:13 and 03:34
   predictions later that same morning were still extreme (0.038, 0.963).
3. **`TRADING_PAUSED` / shadow-mode selection.** Trading was paused
   2026-07-01 to 2026-07-31 for travel, which matches the onset almost
   exactly, and the obvious story is that paused mode logs marginal
   predictions that live mode filters out. ELIMINATED: August ran with
   `is_shadow = 0` (71 of 78 rows, trading resumed) and confidence STAYED
   collapsed at 0.0700. The effect outlived the pause.
   Monthly: May `is_shadow=0` conf 0.2333 | Jun `0` 0.1958 |
   Jul `1` 0.0739 | Aug `0` **0.0700**.
4. **Loss of the `obs` component from the blend.** Looked compelling on a
   day-by-day read: high-confidence days carry `{"obs": 0.87, ...}` and flat
   days carry `{"ensemble": .., "gaussian": .., "climatology": ..}`.
   ELIMINATED by the aggregate, which points the other way — blends
   CONTAINING obs have LOWER mean confidence (0.1135, n=88) than blends
   without it (0.1425, n=137), and the share of predictions carrying obs
   ROSE across the collapse: May 0%, Jun 43.2%, **Jul 62.5%**, Aug 45.9%.
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

## What the deeper commit research actually produced

Elimination, not identification. Four leading suspects are dead on dates or
on aggregates, and the window is pinned to a 2-day gap containing no commits
at all. That empty window is the finding: it redirects the search away from
the commit log entirely and toward accumulated state, config, and external
inputs. A new session should start from the "still open" list above and NOT
re-derive the eliminated four.

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
