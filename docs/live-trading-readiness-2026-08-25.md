# Live-trading readiness — assessment 2026-08-25

Written against master `bc16f9d0`. Every number here was measured on this
date against the live `data/predictions.db` and `data/paper_trades.json`, not
recalled. Re-derive before acting on any of it; this project's data moves
daily and several figures in here already superseded earlier ones.

---

## 1. The mechanical gate

`paper.graduation_check()` (`paper.py`, grep `def graduation_check`) requires
all three. Current state:

| gate | required | actual | |
|---|---|---|---|
| settled trades | ≥ 30 | **243** | PASS |
| total P&L | ≥ $50 | **−$37.89** | FAIL |
| Brier, last 50 settled | ≤ 0.23 | **0.2436** | FAIL |

`graduation_check()` returns `None`. Win rate is 49.0% (119/243) and is
deliberately **not** a gate — the function's own docstring explains why: a bot
buying NO at $0.03 can win 97% of the time and still lose money on the rare
adverse move.

Mechanically, then: **P&L must swing +$88 and Brier must fall 0.014.**

---

## 2. Why the gate understates the problem

The gate asks whether paper trading was profitable. Four independent
measurements say there is no measured edge to be profitable *with*.

| measurement | result | reading |
|---|---|---|
| model vs market Brier, on the tail actually traded (n=211) | +0.0388 ± 0.0151, **t = +2.56** | model is *significantly worse* than the price |
| realized P&L per contract, at the mean real spread (0.024) | **+0.0032 ± 0.0323, t = +0.10** | indistinguishable from zero |
| conviction → P&L relationship | **rho = −0.0215, p = 0.754** | more conviction buys nothing |
| resolution (information content) vs market | **0.0147 vs 0.0409** | market carries 2.8× |
| AUC | **0.605 vs 0.715** | barely ranks better than chance |

Spread figures are measured from `price_history`, not assumed: median 0.020,
mean 0.047, p90 0.100. At the 0.040 half-spread `utils.py` itself assumes,
per-contract P&L is **−0.0128**.

**Independent corroboration.** Batch-66 reached the same conclusion from a
different angle, run by a separate session: capture ratio 0.378 over 243
settled trades, mean realized return **−0.040 per dollar of cost**, and skill
*worsening* as conviction rises (−0.179 pooled → −0.233 at ≥0.20 → −0.431 at
≥0.30). Two investigations, different methods, same answer.

So −$37.89 is not noise around a positive edge. It is what a zero-edge system
looks like after fees and spread.

---

## 3. Calibration is not the missing piece — this was tested directly

A **perfect in-sample isotonic recalibration** of `our_prob` — the theoretical
ceiling for any calibration layer, cheating by fitting the same data it scores
— reaches **0.2323**. The market's *actual* Brier is **0.2201**. Even the
cheating upper bound loses.

Murphy decomposition on 214 settled rows (uncertainty 0.2482, identical for
both):

| | Brier | reliability ↓ | resolution ↑ | AUC |
|---|---|---|---|---|
| model | 0.2596 | 0.0222 | **0.0147** | 0.605 |
| market | 0.2201 | 0.0146 | **0.0409** | 0.715 |

Reliability is what recalibration fixes, and it is only 0.0222 of the model's
0.2596. The deficit is **resolution**, which recalibration cannot create by
construction.

That is why batch-53's IDR replay failed (−9.30% vs the reference Gaussian
against a +5% bar) and why EMOS also fails the same bar (+3.72%/+4.30%). Not
the wrong calibrators — the wrong lever. Both are CLOSED in `backlog.txt`.

---

## 4. Where the resolution actually is (and isn't)

Every component probability, scored on the same settled rows:

| component | n | Brier | resolution | AUC | 95% CI |
|---|---|---|---|---|---|
| **market_prob** | 214 | 0.2201 | 0.0409 | **0.715** | [0.643, 0.782] |
| our_prob | 214 | 0.2596 | 0.0147 | 0.605 | [0.529, 0.679] |
| raw_prob | 213 | 0.2584 | 0.0158 | 0.609 | [0.533, 0.682] |
| **ensemble_prob** | 167 | 0.3097 | 0.0084 | **0.530** | **[0.441, 0.619]** |
| nws_prob | 164 | 0.3735 | 0.0074 | 0.566 | [0.478, 0.653] |
| clim_prob | 164 | 0.3049 | 0.0141 | 0.572 | [0.484, 0.662] |
| **nbm_quantile_prob** | **26** | **0.2162** | 0.0488 | **0.657** | [0.424, 0.868] |

Three things fall out:

1. **The ensemble carries no ranking signal.** AUC 0.530, CI comfortably
   containing 0.5. Neither does NWS or climatology.
2. **Climatology ranks as well as the entire blend** (0.572 vs our_prob's
   0.568 on the same rows). The weather forecast is contributing ~nothing to
   ranking beyond the climatological base rate.
3. **The blend does not beat its own inputs** — on `raw_prob`'s 213 rows,
   our_prob 0.602 vs raw_prob 0.609. The post-processing stack slightly
   *reduces* ranking ability.

`ensemble_prob`'s reliability table is the clearest single diagnostic:

| bin mean ens_prob | 0.064 | 0.265 | 0.388 | 0.518 | 0.749 |
|---|---|---|---|---|---|
| **observed rate** | 0.412 | 0.636 | 0.471 | 0.563 | 0.529 |

Non-monotone, and wildly over-confident — it says 6%, the thing happens 41%
of the time. Classic under-dispersed ensemble. A cleanly recomputed Gaussian
on the same forecast mean actually ranks *better* (0.589 vs 0.530), so the
member-exceedance count is discarding information a smooth CDF keeps.

**NBM is the one bright spot** and the only component resembling the market —
but n=26 gives **27% power**, so it is a lead, not a result. See §6.

**Caveat that applies to every AUC above:** the population is selected for
|our_prob − market_prob| ≥ 0.098 (see §5), which mechanically compresses all
of them. The *comparisons* hold — the market is measured on identical rows —
but the absolute levels are not general-population AUCs.

---

## 5. The measurement itself is compromised — fix this first

**`predictions` is selection-biased.** `log_prediction()` only fires for
opportunities that cleared the full placement gate chain. Measured: the
minimum |our_prob − market_prob| across all 563 rows is **0.0984**. There is
not one low-conviction row. Every model-vs-market statistic in this repo is
computed on the high-conviction tail.

(This also makes `get_model_vs_market_brier`'s own docstring caveat backwards
— it warns about dilution from markets where we agreed with the mid. There
are none.)

**The unbiased sample exists and was never scored.** `analysis_attempts` holds
697 rows, min |edge| **0.0011**, 25% below the 0.08 floor `predictions` never
sees — but only 84 had an outcome. Fixed and merged 2026-08-25
(`settle_pending_attempt_tickers`, `backfill-attempt-outcomes`, dry-run by
default). **The backfill has not been run yet.**

**A live bias path is contaminated.** The METAR lock's *running daily extreme*
is persisted as `forecast_temp_f` and reaches `get_dynamic_station_bias` via
`ensemble_member_scores`' `model='blended'` rows, which adjusts live
forecasts. 46% of blended rows carry ±8–10 °F error with opposite signs by
var. Across batch-68's repair, OklahomaCity/max — the only city over the
10-sample floor — swung from **+7.27 °F to −7.06 °F**, a 14.33 °F change in a
correction that is *subtracted* from the raw forecast. Filed as **batch 75**,
Priority HIGH, not yet started.

Any edge number computed before batch 75 lands is suspect.

---

## 6. What would actually change the picture, in order

1. **Land batch 75.** The bias path feeding live forecasts is wrong. Cheapest
   correctness win and a prerequisite for trusting anything else.
2. **Run `py main.py backfill-attempt-outcomes --run`.** ~494 tickers,
   one-time, re-runnable, idempotent. Takes evaluation from 3.5 → ~22
   settled rows/day *and* moves it off the self-selected tail. The weekly
   prune that would have deleted this corpus on a 30-day rolling window is
   already fixed.
3. **Then hunt resolution, not calibration.** Concretely: why is
   `ensemble_prob` at AUC 0.530? And grow the NBM sample — it is the only
   component that looks like the market, its registry `sample_floor=20` gives
   only **27% power** (needs ~150–200; filed in `backlog.txt`), and it is
   currently skipped entirely on the METAR-locked path.

Items 1 and 2 do not create an edge. They make one *measurable*.

---

## 7. Timeline

Per-contract P&L has an irreducible sd of **0.4698** (binary outcomes near
47¢). At n=214 the **minimum detectable edge is 9.0¢/contract** — larger than
any plausible real edge, i.e. the current sample can only detect an edge so
big it would be implausible.

| edge to prove | rows needed | at 3.5/day (now) | at ~22/day (post-backfill) |
|---|---|---|---|
| +5¢ | 693 | 0.5 yr | 0.09 yr |
| +3¢ | 1,923 | 1.5 yr | 0.24 yr |
| +2¢ | 4,327 | **3.4 yr** | **0.54 yr** |
| +1¢ | 17,306 | 13.5 yr | 2.2 yr |

This is the timeline to **know**, not the timeline to **have** an edge. It
only pays off if there is one to find.

---

## 8. Bottom line

The bot does not meet its own graduation gate (2 of 3 failing), and
independent measurements agree it has no edge distinguishable from zero on
the population it currently trades. The shortfall is **resolution** — the
forecast's information content relative to the price — not calibration, not
sample size, and not anything a post-processing layer can supply.

The honest sequence is: fix the contaminated bias path, unlock the unbiased
evaluation corpus, re-measure on clean data for a few months, and only then
ask the graduation question again with numbers worth trusting.

Whether to put real money behind it is an owner decision and nothing in this
document should be read as a recommendation either way.

---

## Provenance

Findings from batch-53's replay, its opus review, batch-66, and batch-68's
settlement-source repair. Related `backlog.txt` entries, cited by title:

- *IDR/EasyUQ AS A CALIBRATION CHALLENGER TO EMOS/TEMPERATURE-SCALING — GATE FAILED, IDEA CLOSED*
- *SILENTLY CORRUPTS ANY ANALYSIS KEYED ON THAT COLUMN* (batch 75 — that
  fragment is the grep-able one; the entry's full title wraps across lines in
  `backlog.txt` and grepping it whole returns nothing)
- *SETTLE analysis_attempts.outcome — THE UNBIASED EVALUATION POPULATION IS ALREADY BEING LOGGED AND NEVER SCORED*
- *THE SIGNAL REGISTRY'S sample_floor=20 CLEARS AT ~27% STATISTICAL POWER*
- *fit_market_implied_distribution() RETURNS A DEGENERATE FIT ON ~19% OF ROWS*
- *MEASURE BRIER SKILL CONDITIONED ON THE SIZE OF OUR DISAGREEMENT WITH THE PRICE* (batch 66)
