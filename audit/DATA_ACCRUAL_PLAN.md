# Data-accrual plan — how to make the live-trading gates reachable

Written 2026-08-25 against master `087af072`. Every figure here was measured
against the live `data/predictions.db` on that date; re-measure before acting,
and treat any number older than a few weeks as a hypothesis.

## The problem in one paragraph

Every live-trading gate in this repo is a sample-count floor. At the rate
samples currently accrue, several of those floors are not reachable on any
realistic timeline — which is the pressure that produced batch-75's bug in the
first place (a METAR running extreme was written into the forecast column,
where it inflated the usable sample at the cost of corrupting it). The
question this document answers is: what can be done about the rate, honestly,
without lowering a floor or faking a sample.

## The single most important reframing

**There are two different questions, and they differ in cost by ~16×.**

| Question | Estimator | sd | n for a meaningful effect |
|---|---|---|---|
| *Is the model calibrated?* | forecast error, °F | **2.889** | **262** (to detect 0.5 °F) |
| *Does the model beat the market?* | realized PnL, $/contract | **0.4698** | **4,331** (to detect 2¢) |

Both use the same convention as the existing backlog table (two-sided 95%,
80% power); the PnL column reproduces that table's 693 / 1,925 / 4,331 /
17,323 exactly, which is how the convention was confirmed.

The consequence is stark, and it is the part nobody has acted on:

- **Calibration is already answerable.** On 208 clean ensemble rows we can
  detect a bias of **0.56 °F**. Detecting 1.0 °F needs only n=66.
- **Edge is not close.** On 321 settled rows the smallest detectable edge is
  **7.3¢/contract** — larger than any plausible real edge. Batch-66's measured
  skill was *negative*, so this is not a near miss.

**Action:** audit every sample-count floor for which question it is actually
gating. A floor that blocks a *calibration* decision (station bias, sigma,
EMOS, per-city offsets) behind a PnL-sized n is costing time for nothing. This
has not been done and is the cheapest item on this list.

## The levers, ranked

### 1. Settle `analysis_attempts` — ~6× the scoring rate

> **CORRECTED 2026-08-26. This is already BUILT and already RUNNING — the task
> is to UNBLOCK it, not to write it.** The first draft of this document
> described it as work to be done. It is not.
> `tracker.settle_pending_attempt_tickers()` exists, is called from
> `sync_outcomes()` under `ATTEMPT_SETTLE_CAP_PER_SYNC` every cron cycle, and
> has a one-time drain command: `py main.py backfill-attempt-outcomes`.
>
> What it produced on the 2026-08-26 00:28 UTC cycle:
> `analysis_attempts sweep settled=0 skipped=0 failed=25` — every attempt
> failed on `Circuit open for source 'kalshi_api_read'`, which had tripped
> after five `401 Unauthorized` responses caused by a 41 s clock skew. So the
> lever has been running and silently returning nothing.
>
> **The action is therefore: fix the clock (done 2026-08-26), then run the
> drain command once.** Everything below still describes the size of the prize
> correctly; only the "cost" line's framing was wrong.

Already filed HIGH in `backlog.txt` as *"the only real lever on the graduation
timeline"*. Re-verified 2026-08-25:

- **697 attempts logged, 84 scored.** 570 tickers have no `predictions` row;
  **501 of them are already past their target date.**
- Cost is a one-time ~501-call settlement backfill plus ~22/day steady state
  (measured: 22.03 distinct tickers analysed per day over 30 days). Settlement
  is once per ticker, not once per cycle — the old "~2,000 calls per cron
  cycle" objection was the wrong shape. **The per-cycle half already runs;
  only the one-time drain is outstanding.**
- Scoring rate moves from **3.21/day** (321 settled rows over 100 days) to
  **~22/day**. A 3¢ edge goes from **1.6 years to 0.2 years**; 2¢ from 3.7
  years to 0.5.

It is also the *unbiased* population, which matters more than the rate.
`predictions` only gets a row after a market clears the placement gates, so its
minimum |our − market| is **0.0984** — there is not one low-conviction row in
it. `analysis_attempts` has a minimum of **0.0011**, with **174 rows (25.0%)
below the 0.08 edge floor**. Every model-vs-market statistic this repo has ever
computed was computed on the high-conviction tail only.

**Open question flagged in the entry, unresolved:** does `audit_settlement`
work for a ticker with no `predictions` row? Check before assuming.

### 2. One-off historical backfill — calibration answered immediately

`backtest.py` already talks to `previous-runs-api.open-meteo.com`, which
returns archived forecasts for past dates. A single backfill over the
available window would yield, for 21 cities × 2 vars:

| window | pairs | smallest detectable bias |
|---|---|---|
| today | 208 | 0.561 °F |
| `past_days=41` | ~1,722 | **0.195 °F** |
| `past_days=92` | ~3,864 | **0.130 °F** |

A **4× improvement in calibration resolution, available with no waiting at
all.** Ground truth is already reachable (ACIS/METAR, both already used here).

**Three real constraints, all documented in the repo:**
- `temperature_2m_previous_day0` is **not a real field** and is silently
  ignored — the minimum reconstructable lead is `previous_day1` (~24 h).
- The API exposes whole-day run offsets only, not intraday run selection, so
  this cannot reconstruct a same-day 15Z decision.
- It measures the **deterministic 3-model blend**, which is a *different
  estimator* from the live ensemble mean. Fine for station bias (largely
  estimator-independent) and for sigma; **not** a substitute for measuring the
  live blend. Same caveat as batch-75's `model_forecast_temp_f` column.

**Verify the actual `past_days` ceiling before planning around 92** — the
existing call site passes `max(41, days_out + 2)`, which is not evidence of
the API's limit.

### 3. Harvest the archive daily from now on

The window above is bounded, so history beyond it **cannot be bought
retroactively**. Storing `previous_day1` daily costs almost nothing and, in a
year, yields an archive that no amount of money or API access can reconstruct
later. Low urgency, zero regret, and the cost of *not* doing it compounds.

## Ruled out — checked, so nobody re-checks

- **Ladder-rung double counting.** The obvious suspicion, and a documented
  trap elsewhere in this repo. Measured: **321 settled rows vs 313 distinct
  (city, market_date, var) events — 2.5%.** The counts are honest; there is
  nothing to recover here.
- **`backfill-ensemble-var` on the 25 NULL-var blended rows.** Run live
  2026-08-25: recovers **0 of 25**, permanently (no matching prediction, or a
  city-day that traded both a high and a low market, which
  `ensemble_member_scores` cannot disambiguate without a ticker). They are also
  harmless — `get_dynamic_station_bias` filters `var = ?`, which a NULL never
  matches.

## Not recommended

- **Adding cities/families to raise the rate.** It works linearly, but each new
  family arrives unvalidated and inherits pooled gates the moment the aggregate
  count opens — the documented batch-52 Miami trap. It buys rate at the expense
  of the thing the rate is *for*.
- **Lowering any floor.** The floors are the only thing standing between a
  model with measured negative skill and live money.

## The caveat that governs all of the above

Accelerating measurement is not the same as accelerating go-live.

- Batch-66 measured skill at **−0.179 pooled**, and *worse* the more the model
  disagrees with the price (−0.431 at ≥0.30 disagreement).
- Batch-65 found pooled Brier's one-sided 95% lower bound at **0.2348**, above
  the bot's own **0.22** halt threshold — by its own halt rule the model is
  currently failing.

So a 6× faster clock most likely delivers a definitive **no** sooner rather
than a go-live sooner. That is still worth a great deal: it is the difference
between three months and three years of ambiguity, and a fast no frees the
effort for a different model. But it should be the expectation going in.

## The precondition that costs nothing

**No scan has run since batch-64 landed** (2026-08-25 08:46 UTC; newest
`predictions` row is 06:36 UTC the same day). All four of batch-64's
forward-only writers are still empty — `forecast_run_inits`,
`blend_exclusions`, `orderbook_depth_snapshots` at zero, and
`ensemble_member_values` holding only synthetic test rows. None of the levers
above accrue while the scanner is idle, and batches 70/71 are blocked on
exactly this data.

Start the scanner before doing anything else on this list.

> **Superseded for `orderbook_depth_snapshots`, 2026-08-28.** That table was
> not waiting on the scanner. The WebSocket had never started in production —
> `cron.py` read two env var names that exist nowhere else in the repo, so the
> listener was never constructed and the start path returned with no log at
> any level. Fixed; the first cron run after the fix wrote 726 rows across 526
> distinct tickers. Do not quote the zero above as current state.
