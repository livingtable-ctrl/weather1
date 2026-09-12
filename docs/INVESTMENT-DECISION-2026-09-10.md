<!--
Landed 2026-09-12. Every figure in this report was MEASURED ON 2026-09-10 against
predictions.db, data/paper_trades.json + data/paper_archive/, and live external
sources; the filename carries the measurement date, not the landing date.

The corpus is live and several figures move. RE-DERIVE ANY NUMBER YOU INTEND TO
RELY ON -- do not cite this document as a source. Figures known to move: the
live-era P&L, every count from analysis_attempts/predictions/outcomes, and the
price-recal accrual rate.

The 15 evidence/*.json artifacts behind this report (plus 8 raw intermediates)
were session-scratchpad files and are NOT in the repo. Each section states the
table and query it was measured from, which is what makes it re-derivable.

Four of the author's own measurements were wrong and were corrected before
reaching a conclusion; all are disclosed in the closing appendix. Read it before
trusting any single figure here.
-->

# WEATHER1 — Investment Decision

Research date: **2026-09-10**. Repository at `5707f48a`, unmodified. `data/` read read-only from the main clone.
Every figure below was re-derived from primary source in this session unless explicitly labelled otherwise.

---

## 1. EXECUTIVE DECISION

**FINAL DECISION: SUNSET**

| | |
|---|---|
| **Confidence** | High on the weather-forecasting thesis; Medium on the decision overall |
| **Overall score** | **22.5 / 100** |
| **Core thesis status** | Disproven as to forecasting (P3, P4 PROVEN FAILURE); the one surviving result is not robust (P8 STRONGLY NEGATIVE) |
| **Dominant failure point** | The model is less accurate than the price it trades against, and the headroom to fix that is smaller than the measurement noise floor — **THESIS-CRITICAL** |
| **One-sentence reason** | Weather1's probabilities lose to the market on every population tested, the public forecast it is built on already absorbed the AI-model advantage in May 2026, the maximum remaining forecast improvement (0.1–0.3 °F) is smaller than the irreducible observation error (0.5–1 °F), and the single statistically significant result in the project is a horizon artifact whose sign is *negative* at the horizon the bot actually trades — measured independently on 64.7M Kalshi trades. |

A note on what this decision does **not** rest on: the realised paper loss. At an effective sample of 202 the 95% clustered confidence interval on mean P&L per trade is **[−2.93, +2.83]** — the ledger is statistically uninformative, and treating it as proof of failure would be exactly the error the brief forbids.

---

## 2. BOTTOM LINE

Three things are now established, and a fourth is established as unknowable in time to matter.

**One. The forecast is worse than the price.** On 764 settled markets — every market the scanner analysed, not a favourable subset — the market's Brier score is **0.1079** and weather1's is **0.1702**. The market wins on all four populations tested. On the markets weather1 actually traded, its probabilities are worse than answering 0.5 to every question (0.2624 against 0.2500). And when the model disagrees with the price, it is not merely uninformative but actively wrong: P(yes | model above market) = **0.190** versus P(yes | model below market) = **0.700**, z = **−14.6**. The model says 0.25 where reality is 0.047.

**Two. That gap cannot be closed.** This is the part that converts an implementation failure into an opportunity failure. The baseline is not a raw model — it is the National Blend of Models, a ~30-model statistically post-processed blend that already applies decaying-average and quantile-mapping bias correction, already publishes calibrated percentiles for daily max/min, and **since v5.0 on 2026-05-05 already ingests ECMWF AIFS for temperature**. Measured headroom for further post-processing on an already-post-processed product is 5–12% of MAE — about 0.1–0.3 °F on a 2–3 °F base, and negative at some sites. The observation and climate-day stack alone contributes 0.5–1 °F: ASOS values are rounded to whole °F, and the true daily extreme can occur between METARs and never be transmitted. **The noise floor is larger than the entire prize.**

**Three. The one significant result is a horizon artifact, and the rule is on the wrong side of it.** The project's pivot is a price-recalibration rule that reads no weather data at all: fit `y ~ a + b·logit(price)`, trade where the recalibrated probability disagrees. Frozen at b = 1.33635, z = +3.323. It reproduces — I measure b = **1.3310**, z = **+3.20** clustered, on 690 rows. I tested and **refuted** the leading explanation, that the bot's own gates manufacture it: same price source, same lead, split on whether the bot ever analysed the ticker gives a selection effect of z = −0.15 to −0.61. It is not a ticker-selection artifact, not a price-source artifact, and not carried by one price band.

It is a **horizon** artifact, and this is now settled by published work rather than by my inference. On the independent hourly tape I measure b falling monotonically with lead — 1.284 at 6h, 1.013 at 12h, 0.809 at 24h, 0.442 at 36h — and at a fixed 12-hour horizon the sign **flips between regimes**: b = 1.466 (z = +2.01) in May–June against b = 0.776 (z = −1.99) in July–September. Independently, **Le (2026) fits the identical `a + b·logit(p)` model on 64.7M Kalshi trades split by time-to-resolution, and reports Kalshi *weather* slopes of 0.69, 0.84, 0.74, 0.87, 0.91, 0.97 for every cell inside 48 hours, rising above 1 (1.20, 1.20, 1.37) only beyond two days.** The bot's frozen 1.336 sits squarely in the long-horizon range — and its picks are same-day and next-day, at a median 15.5-hour lead, where the published slope is **below 1**.

That inverts the trade. With b < 1 the market is *over*confident, prices too extreme, and the recalibrated probability for a 25¢ contract is *higher* than 25¢ — a BUY YES. All **14 of 14** logged picks are NO, structurally, because the frozen coefficients make the YES branch unreachable. At its own trading horizon the rule is systematically on the wrong side, and that is measured on a sample roughly 100,000 times larger than the one it was fitted on.

**Four. The test that would settle it takes 2.9 years.** The rule's own sealed pre-registration needs 1,100 settled picks before the first look. It has logged 14 picks, 10 settled, across **four distinct target days**, all on the NO side. At the measured 1.02 settled picks per day that is **1,071 more days**; the 2,200-pick kill point is 5.9 years. The first 10 settled picks returned **−28.9%** per dollar staked.

The fifth thing is the reason this is SUNSET rather than PAUSE: there is no version of the weather thesis left to validate. The cheap decisive experiment — does the bot's selection manufacture the coefficient — has now been run, and the answer did not save it.

---

## 3. WHAT WEATHER1 ACTUALLY IS

A 283,697-line Python system (323 modules, 210 test files, 170,397 lines of test code, 6,965 test functions) that scans Kalshi weather markets, builds a probability, compares it to the market price, and places resting paper orders.

**The pipeline, as implemented:**

1. Fetch the Kalshi catalog — ~770 markets per scan.
2. Family gates: daily/weekend rain is track-only; hourly markets only at their target hour.
3. Market gates: liquidity floor 50 contracts, volume floor 50, spread ≤ 30% of mid, and `extreme_price` (reject the near-certain).
4. Input gates: a `between` bracket requires a METAR lock.
5. Forecast assembly from ensemble members, NWS, climatology and intraday METAR observation.
6. Bias correction and blend weights (condition / seasonal / city, with separate same-day tables).
7. Probability via ensemble empirical CDF or a normal with sigma capped at 3.0 °F.
8. **Market anchor** — blend the model toward the market mid (`_MARKET_ANCHOR_BETWEEN` 0.25, `_ABOVE`/`_BELOW` 0.10).
9. Model gates, including a hardcoded `MAX_MODEL_MKT_GAP = 0.25`.
10. Edge gates and a retired-method gate.
11. Kelly sizing, position limits, circuit breakers.
12. Order: resting midpoint GTC limit — maker — into a **paper ledger only**.
13. Settlement monitor → `outcomes` → calibration refits.

Steps 8 and 9 together are the structural fact the repo names itself (backlog L1155, OPEN): the pipeline pulls the model toward the price and then discards whatever still disagrees. What survives is where the model already agreed — where there is nothing to win.

**Scale of state:** 78 MB `predictions.db` — 632 predictions, 1,014 settled outcomes, 878 analysis attempts, 158,701 Kalshi trades, 32,152 hourly price bars, 21,037 orderbook snapshots. Risk machinery is real and broad: circuit breakers across 19 files, Kelly in 22, drawdown in 16, kill switch in 11, plus black-swan, flash-crash, SPRT and watchdog layers.

**It has never traded real money.** `.env` sets `KALSHI_ENV=prod`, but `LIVE_TRADING_ENABLED` is never set and `trading_gates.py:69` refuses every live order without it. `live_fills`: 0 rows. `daily_live_loss`: 0 rows. `audit_log`: 0 rows. The startup banner claiming "PRODUCTION MODE — LIVE ORDERS ENABLED" is wrong, which the repo knows (L2405, OPEN). This resolves the prior handoff's open safety question: **nothing is armed.**

**Documentation versus implementation — implementation wins, six times.** The six discrepancies found are recorded in `evidence/L1_system.json`. The two that matter:

- **Settlement source.** Kalshi's help centre (updated 2026-07-22) and the bot's own climate-day window both describe the NWS CLI process. `metar.py:369` records that **effective 2026-08-14 the daily temperature ladders settle on The Weather Company**, verified live against two Kalshi endpoints and six series (commit `e853736c`). My external research confirms it independently: `GET /series/KXHIGHNY` returns `settlement_sources: [{"name":"The Weather Company"}]`, and the partnership was announced 2026-08-27. The bot's settlement window is documented against a **superseded regime**, and the code states plainly that its status under TWC is unknown because *nobody has read weather.com/kalshi*.
- **`outcomes.settled_at` is not a settlement time.** It is a recording time: median **54.5h** after the ticker's nominal expiry, p75 361.5h, max 745.5h, only 47.9% within ±48h. Any lead computed from it is wrong — which I discovered by computing one and getting a median 217-hour "lead" for markets settling within a day.

---

## 4. INVESTMENT THESIS

Ten propositions, each tested independently. Full evidence in `evidence/L5_propositions.json`.

| # | Proposition | Status |
|---|---|---|
| P1 | Kalshi weather markets contain exploitable mispricing | **UNCERTAIN** |
| P2 | Public weather information is insufficiently incorporated into prices | **NEGATIVE** |
| P3 | Weather1 can estimate probabilities better than relevant baselines | **PROVEN FAILURE** |
| P4 | The forecasting advantage is large enough to create trading edge | **PROVEN FAILURE** |
| P5 | The edge survives fees and execution costs | **SUPPORTED** as to cost structure; vacuous as to any edge |
| P6 | Enough opportunities exist | **NEGATIVE** |
| P7 | Weather1 can actually execute those opportunities | **UNCERTAIN** |
| P8 | The edge is sufficiently robust | **PROVEN FAILURE** (was STRONGLY NEGATIVE on internal evidence alone; the published horizon decomposition closed it) |
| P9 | The edge is likely to persist | **UNCERTAIN, leaning NEGATIVE** |
| P10 | Continued development has positive expected value | **NEGATIVE** |

P5 deserves its unusual entry. Weather maker fees appear to be **zero** — verified against the live API across **all 390** Climate-and-Weather series (`fee_type=quadratic`, `fee_multiplier=1`, zero maker-fee variants, with `KXNFLGAME` returning `quadratic_with_maker_fees` as a working control), and `/series/fee_changes` empty. The ledger reconciles exactly: `cost == quantity × entry_price` on all 269 settled trades, maximum absolute difference **0.0000**. This is the project's strongest genuine asset.

**One honest caveat, because my two research passes disagreed.** Neither could read Kalshi's official fee PDF (HTTP 429 on every attempt, including with browser headers). The live-API enumeration with a working control is the stronger evidence and is what I rely on. But some secondary trackers quote a maker fee of 0.0175·C·P·(1−P) — roughly 0.22¢ per contract at 85¢ — and one study describes maker-fee-free as the "pre-2025" structure. The ledger's exact reconciliation is the bot's own accounting, not an exchange confirmation, and `live_fills` is empty, so **no real fill has ever confirmed it.** Call this strongly supported, not proven. If it is wrong, roughly a tenth of the documented maker edge disappears and the maker-only thesis weakens further.

And it is not enough regardless: Kalshi makers average about **−10%** across 300k+ contracts against takers' −32%, their above-50¢ advantage is **not replicated once split by days-to-close**, and closing-day maker losses resemble takers' — closing day being the horizon this bot rests into. Maker status reduces the loss rate; it does not create a profit.

---

## 5. BAD VS UNKNOWN

This separation is load-bearing and the decision respects it.

### Proven / strongly supported failures

1. **Weather1's probabilities are worse than the market price.** 764 settled markets, market Brier 0.1079 vs 0.1702; worse on all four populations; worse than constant-0.5 on the traded population; disagreement anti-informative at z = −14.6. The project's own rule retired its ensemble method on 2026-09-01 at Brier 0.2570/0.2711 against its own 0.25 threshold.
2. **The forecast-improvement path is structurally closed.** Headroom 0.1–0.3 °F against an irreducible 0.5–1 °F observation floor, on a baseline that already ingests AIFS.
3. **The project's entire historical profit came from a leak.** All 17 profitable `above`/`metar_lockout` trades (+$282.81, 82.4% win) were entered 2026-06-05 to 2026-06-21 — every one before commit `e395392b` (2026-06-25) added the guard requiring the observation's local date to equal the target date. Post-guard that path has zero trades. Removing the stratum takes the live era from −$13.88 to **−$296.69**.
4. **The one significant result is not robust.** Sign flips between seasons at a fixed horizon; 1 of 6 lead bins significant; 0 of 13 thresholds with a CI excluding zero.
5. **Parameter selection does not generalise.** The bot's own weekly sweep reports 60–64% in-sample win rates at *every* threshold value against a **48.7%** realised rate.

### Important unresolved uncertainties

1. **Whether any exploitable mispricing exists at this venue (P1).** The best-evidenced candidate is not calibration but *underreaction*: a published study of 353M trades finds a one-minute change in a precisely observed benchmark probability moves price only ~**0.64-for-one**, with the residual predicting short-horizon drift, worse in thin books. That is a latency edge, not a forecasting one, and weather1 does not pursue it.
2. **Whether live execution works (P7).** Paper fills are credible — resting fills 96–100% realistic, no detectable adverse selection (permutation p = 0.142), and the bot's decision price agrees with the independent tape to a median 1.25–1.5¢. But the live order path **has never been fired at a real exchange** (L15326, OPEN) and `live_fills` is empty.
3. **Whether the realised P&L means anything.** It does not. Effective n = 202, clustered 95% CI on mean P&L per trade **[−2.93, +2.83]**, total P&L 95% CI **[−788.73, +760.96]**. The smallest per-trade edge this sample could have detected at 80% power is **$4.11 on a $17.17 mean stake — 24% per trade**. This is an UNKNOWN, not a failure, and it is not used as evidence for SUNSET.
4. **The TWC climate-day boundary.** Unread. Every outcome after 2026-08-14 was scored against a definition the bot does not hold.
5. **Whether backfill ordering ever leaked.** Not decidable: `outcomes` carries no write timestamp and `settled_at` is a recording time. An unresolvable lineage gap, reported as such rather than as a clean channel.

---

## 6. CURRENT KALSHI OPPORTUNITY

**Verdict: MARGINAL, and the attractive parts are not the parts weather1 uses.**

Genuinely attractive, verified current:

- **Zero maker fees on weather**, confirmed across all 390 series with a working control and no pre-announced change.
- **`post_only` is a documented order flag** with `PostOnlyCrossCancel` as a clean rejection signal, so maker-only execution is a designed capability.
- **Breadth is real and growing**: 390 Climate-and-Weather series, ~240 new weather markets per day across 38 active series, now including international stations (EGLL, LFPG, RJTT, ZBAA, OMDB, WSSS, YSSY) — not the "20 US cities" every secondary source repeats.
- **Rate limits are ample**: 200 reads/sec at the basic tier.
- **Tight quotes**: median spread 1¢, 73% exactly 1¢.

Structurally unattractive:

- **Depth, not spread, is the binding constraint.** Median depth at best ask **25 contracts**; 51.2% of open markets had no usable two-sided quote when measured on 2026-09-10. Independent capture of 9,554 books across 1,984 daily high-temp markets agrees: median depth 27, ~25% one-sided. Capacity scales by breadth, not size.
- **Tight spreads are subsidised, by two separate programs.** The **Liquidity Provider Program** requires a signed Market Maker Agreement and prices by reverse auction under a confidential appendix — the professional tier, and it does list weather series. A distinct, open **Liquidity Incentive Program** pays ordinary members for resting orders. Current quote quality is a policy choice, not a market property. *(An earlier draft of this report called the CFTC filing a DMM program. It is not — its subject line is "Amendment to August 2025 Liquidity Incentive Program" and it never mentions DMMs. Corrected.)*
- **Half the universe is unanalysable by construction.** Of 740 markets scanned in the last complete cycle, 676 were rejected and only **64 reached analysis (8.6%)** — and **324 of those rejections, 47.9%, were `extreme_price`**. By the time a daily weather market is liquid, the answer is largely known.
- **The market is already well calibrated.** Raw ECE of **0.0162** across 8,494 settled KXHIGHNY markets; a weather-specific academic study finds implied-temperature bias of approximately **zero** in the warm season. The widely repeated "70,000 resolved markets, a 70¢ contract resolves yes ~70%" claim traces to **Kalshi's own research marketing**, is self-reported with no bucket table or standard errors, and the 70k figure is *per horizon*, which the secondary phrasing loses.
- **Specification risk is live.** Two changes in four weeks: the settlement-source switch to The Weather Company effective 2026-08-14, and amendments to seven weather rulebooks on 2026-09-02/03 permitting Kalshi to hold expiration on a materially erroneous reading, await revised data, or **resolve to a last fair price it determines** — prompted partly by suspected tampering at a station now under police investigation. Settlement is no longer purely mechanical.

---

## 7. FORECASTING ADVANTAGE

**Verdict: none exists, and none is available.**

Measured, this session, on the bot's own corpus:

| Population | n | Model Brier | Market Brier | Skill |
|---|---:|---:|---:|---:|
| `predictions`, all settled | 460 | 0.2654 | 0.2205 | −0.0449 |
| `predictions`, non-shadow (actually traded) | 270 | 0.2625 | 0.2265 | −0.0360 |
| `predictions`, core temp methods | 347 | 0.2624 | 0.2235 | −0.0389 |
| `analysis_attempts`, all settled (**unbiased**) | 764 | 0.1702 | 0.1079 | −0.0623 |

Constant-0.5 scores 0.2500. The model scores 0.2624 on the traded population — **worse than refusing to forecast**.

Decile calibration is the discriminating evidence. The market tracks the diagonal across its whole range (0.0–0.1 → 0.029; 0.4–0.5 → 0.434; 0.9–1.0 → 0.919). The model is severely over-dispersed upward at the low end: it says 0.25 where the realised rate is **0.047**. The repo already knows this (L1893, OPEN: "THE CALIBRATED FORECAST IS NOT CALIBRATED — INTERCEPT −0.69, SLOPE +1.50, AND THE MARKET BEATS IT ON BOTH PARAMETERS").

The external picture closes the path rather than merely describing the gap:

- **NBM v5.0 (2026-05-05) already ingests ECMWF AIFS for temperature and dew point.** The "I will use AI models and the public forecast does not" edge expired four months ago.
- **Post-processing headroom on already-post-processed products is 5–12% of MAE.** NOAA Office Note 13-1, decaying-average bias correction on operational GFS-MOS across 1,319 stations and ~574,500 cases: MAE improved **0.25–0.30 °F** at short projections. Han et al. 2024, site-specific XGBoost on top of IMPROVER (the nearest NBM analogue): average 11.35% RMSE reduction, per-site range 0.54%–37.13%, and **6.46% worse** at one site. The often-quoted ~50% CRPS reduction (Bremnes et al. 2023) post-processes *raw* output and does not transfer.
- **The observation floor is the same order as the entire prize.** ~1.5–2.5 °F MAE for daily max at a major US airport at 0–1 day lead. ASOS values are rounded to whole °F before conversion; the daily extreme is the extremum of a rolling 5-minute average and **can occur between METARs and never be transmitted**. That stack contributes **0.5–1 °F** — larger than the 0.1–0.3 °F available from better modelling.
- **AI models are operational and free**: NOAA AIGFS/AIGEFS/HGEFS operational 2026-01-05, free on NOMADS and S3; ECMWF AIFS operational since 2025-02-25 and *leading* for 2-m temperature over Europe; Google WeatherNext 3 with 0.05° station output. Every one is equally available to every competitor.

**The strongest counter-argument, stated fairly.** One week before this audit — 2026-09-03 — Google released **WeatherNext 3**, the first widely available model designed for exactly this problem: trained directly on sparse *station* observations, emitting a station-calibrated 2 m temperature distribution (mean plus p10/p25/p50/p75/p90) at 0.05° with 64 ensemble members, initialised hourly, out to 48 hours, free to an individual with a Google Account. If anything were going to reopen the forecasting question, it is this.

It does not reopen it today, for four measured reasons. Its *published* accuracy gains are for **precipitation**, not temperature, and the launch gives no ECMWF comparison for 2 m temperature. **Daily maximum is not a provided variable** — it must be derived from the hourly series, which re-imports the climate-day and rounding problems that constitute the dominant error term. It is one week old, with no independent verification at day-0/day-1 station Tmax, which is a specification nobody publishes numbers for at all. And critically, **it is free to every competitor too**, so it cannot create a private advantage — the CC-BY text attached to it even reads "not intended, validated, or approved for real world use," and whether the real-time tier permits commercial use could not be determined.

**What a solo developer could genuinely do better** is not meteorology: settlement-definition fidelity, speed of reaction to new public model cycles, and correct tail shape. The first of those is precisely where weather1 is currently blind.

---

## 8. TRADING EDGE

The brief's five definitions, kept separate.

**Forecasting edge — none.** Section 7. Negative on every population.

**Theoretical edge — large, and that is the symptom.** The bot's recorded `net_edge` at entry averages 0.41–0.54 across the parameter sweep, and its current live signal list carries a "STRONG BUY" at **97.3% edge** (model 96.7% against a market at 48.5%) on a hurricane-count market 84 days out. A 97-point disagreement with a liquid market is not an edge; it is a model failure. That the gates let it through to a signal list, with Kelly sizing it at $0, is the machinery half-working.

**Executable edge — unknown, and unvalidated in the only way that counts.** Paper fill assumptions are defensible (96–100% realistic, adverse-selection permutation p = 0.142), and the decision price is real (median 1.25–1.5¢ from the independent tape at the same instant). But the live path has never been fired at a real exchange, and median depth of 25 contracts caps any position at roughly $25 of one side at the touch.

**Net edge — zero or negative at every threshold tested.**

| Min edge | n | P&L | win% | ret/$ | ret/$ w/ taker fee | trades/day | clustered 95% CI on mean P&L |
|---:|---:|---:|---:|---:|---:|---:|:--|
| 0.01–0.15 | 269 | −13.88 | 48.7% | −0.30% | −3.41% | 2.32 | [−2.93, +2.83] |
| 0.20 | 248 | −13.01 | 47.6% | −0.29% | −3.45% | 2.14 | [−3.16, +3.05] |
| 0.25 | 237 | −13.64 | 47.3% | −0.32% | −3.49% | 2.04 | [−3.30, +3.18] |
| 0.30 | 217 | +11.63 | 47.0% | +0.28% | −2.89% | 1.87 | [−3.46, +3.57] |
| 0.35 | 169 | +171.85 | 46.2% | +5.34% | +2.06% | 1.46 | [−2.82, +4.86] |
| 0.40 | 129 | +196.09 | 43.4% | +8.23% | +4.83% | 1.11 | [−3.19, +6.23] |
| 0.50 | 74 | +242.18 | 41.9% | +18.77% | +15.02% | 0.64 | [−2.21, +8.76] |

High thresholds *do* show positive in-sample P&L. That is not an edge: the threshold is chosen after seeing the outcomes, and **not one of 13 rows has a clustered confidence interval that excludes zero**. Note also that the win rate *falls* as the threshold rises (48.7% → 41.9%) while P&L rises — the gain is a handful of large wins, not a better hit rate. Against this, the bot's own sweep reports 60–64% in-sample win rates at every value. The 12–16 point gap between in-sample and realised is the overfitting, measured directly.

**Realised edge — none demonstrated, and none refuted.** Live era: 269 settled, **−$13.88**, 48.7% win, −0.301% on $4,619 deployed, max drawdown −$460.65. Archived era (closed): 25 settled, **−$432.36**, 32.0% win, **−73.9%** on cost. Combined: **294 settled, −$446.25**. Reading `paper_trades.json` alone misses 96.9% of the loss.

The shape matters more than the total. By condition and method:

| condition | method | n | P&L | win% | mean win | mean loss |
|---|---|---:|---:|---:|---:|---:|
| `above` | `metar_lockout` | 17 | **+282.81** | 82.4% | +28.89 | −40.56 |
| `below` | `metar_lockout` | 3 | +21.00 | 66.7% | +27.30 | −33.60 |
| `below` | `ensemble` | 53 | +15.97 | 35.8% | +10.70 | −5.68 |
| `between` | `ensemble` | 40 | −100.75 | 42.5% | +6.39 | −9.11 |
| `above` | `ensemble` | 77 | −101.20 | 39.0% | +6.80 | −6.79 |
| `between` | `metar_lockout` | 69 | **−184.45** | 63.8% | +19.04 | **−40.88** |

The +$282.81 is the leak (§5). The −$184.45 at a **63.8% win rate** with losses 2.1× wins is the signature of buying near-certainty — and it is the same payoff shape the longshot-fade rule would produce, which is why a high win rate in the forward test must not be read as success. A third loss engine sits outside both: the **40 `early_exit` trades lost $292.06 at a 5% win rate**.

---

## 9. DATA AND LEAKAGE AUDIT

**Verdict: the evidence is mostly trustworthy and largely reproducible, with one historical leak that explains the entire recorded profit and two lineage gaps that cannot be closed from the schema.**

**Confirmed leak (historical, fixed).** The METAR lockout read the previous evening's observations: before commit `e395392b` (2026-06-25) there was no guard requiring the observation's local date to equal the target date, and 62 of 88 locks came from 00–02h UTC scans — 20:00–22:00 the *previous* local evening, when the target climate day had not started. All 17 profitable `above`/`metar_lockout` trades fall inside 2026-06-05 to 2026-06-21. The guard was correct and must not be relaxed.

**Channels checked and clean:**

- **Decisions after the climate day ended: 0 of 690.** An earlier pass of this audit reported 8.24%, using `target_date + 1 day 00:00 UTC` as expiry. US markets close at midnight **local standard** time — 5–8h later — so that figure was an artifact of my own proxy and is withdrawn. The corrected bound is conservative: the true close is an hour later still than the DST offsets I used, so a zero count under the earlier boundary remains zero under the true one.
- **No calibration circularity.** `analysis_attempts.forecast_prob` equals `forecast_prob_precal` on all 88 rows carrying both — the final-stage calibrator is an identity transform. Any residual in-sample advantage would favour the model, so the negative skill delta is conservative.
- **No same-day trading on resolved markets.** 0 of 150 non-shadow `days_out=0` settled predictions had a price below 10¢ or above 90¢ at decision; the `extreme_price` gate removes them upstream.
- **The decision price was real.** Agreement with the independent hourly tape at the same instant: median 1.25–1.5¢ across 92–101 paired rows.

**Unresolvable:**

- **Outcome write timing.** `outcomes` has no write timestamp, and `settled_at` is a recording time (median 54.5h after nominal expiry, max 745.5h). A backfill-ordering leak cannot be excluded from the schema alone. It would not affect the forward-looking measurements here, which anchor on `analyzed_at` and the ticker's own target date.
- **Settlement definition.** Every outcome after 2026-08-14 was scored against The Weather Company's climate day, which the bot does not know. Live specification risk, not a backward leak.

---

## 10. EMPIRICAL PERFORMANCE

| | |
|---|---|
| Settled paper trades | **294** (269 live era + 25 archived) |
| Distinct target dates (live era) | **67** |
| Distinct (city, date) cells | 249 |
| **Effective sample size** | **202** (design effect 1.332, clustering on target date) |
| Realised P&L | **−$446.25** combined; −$13.88 live era; −$432.36 archived |
| Return on cost | −0.301% live era; −73.9% archived |
| Max drawdown | **−$460.65** |
| Win rate | 48.7% live era; 32.0% archived |
| Mean P&L per trade | −$0.0516, clustered 95% CI **[−2.93, +2.83]** |
| Total P&L 95% CI | **[−$788.73, +$760.96]** |
| Trade frequency | 2.32/day live era; 0 live trades ever |
| Out-of-sample | Realised 48.7% win rate against the bot's own 60–64% in-sample sweep |
| Robustness | Positive in **1 of 3** entry months; negative under every cost assumption and every fill rate |
| Forward pre-registered rule | 14 picks, 10 settled, 4 distinct days, all NO, **−28.9%** |

Cost sensitivity: bot's actual (resting maker, $0) −$13.88; Kalshi taker fee −$157.35; taker both legs −$300.82; 1¢ adverse slippage −$101.45. Fill-rate sensitivity (200 draws each): 0.75 → −$18.55, 0.50 → −$10.98, 0.25 → −$1.37. A lower fill rate scales the loss down; it never makes the strategy profitable.

---

## 11. STATISTICAL VALIDITY

**The realised ledger cannot settle the question, and the forecast comparison can.**

On the ledger: 269 settled trades in 67 date clusters, design effect 1.332, effective n 202. The cluster-robust estimator was control-tested two ways — assigning one observation per cluster reproduces the iid SE exactly (ratio 1.0000), and duplicating every row *within* its cluster shrinks the iid SE by 29.4% while moving the clustered SE by **0.0%**. The minimum detectable mean P&L per trade at 80% power is **$4.11 on a $17.17 mean stake — a 24% per-trade edge**. Nothing smaller is visible. Under the brief's §52 bands, 294 combined settled outcomes is "preliminary", and the effective independent-event count is lower still.

On the forecast comparison the situation reverses: 764 settled markets with clean data, realistic ($0, verified) costs and a directional z of **−14.6** is far past the 300-observation threshold the brief sets for a large-sample negative. **This is why the SUNSET case rests on the forecast comparison and not on the P&L.**

**Multiple testing.** The surface is wide: 11 methods, 8 condition types, 25 cities, 11 parameter-sweep values, and in this session alone 6 lead bins, 6 price bands and 9 populations for `b` — at least 88 implied comparisons before counting the historical search. The single significant lead bin (14–20h, z = +2.84) is marginal after a Bonferroni correction across the 6 bins tested (p ≈ 0.027) and unremarkable against the full surface. An external caution sharpens this: a study of 353M trades and 429k contracts warns that about **half** of raw calibration-slope variation is estimation noise.

**Selection and survivorship.** Checked and mostly clean, with two findings. The two data tables are nearly **calendar-disjoint** — 198 of 354 `price_history` tickers (56%) are May–June markets for which `analysis_attempts` has **zero** rows — which makes any naive table-versus-table comparison confounded. A prior session made that error twice in successive drafts of its own analysis; I made it once in this session before correcting it. Separately, the bot's gate-passing subsample has a logit-price spread of 0.62 against 1.84 in the scanned population, so its apparently null result on `b` is a power artifact, not evidence.

**Leave-one-out and permutation.** No single price band carries `b > 1` (dropping any one band leaves z ≥ 2.44). A permutation null shuffling outcomes within (series, lead bucket) gives p = 0.0005 against an observed b of 1.331 — but the permuted mean is 0.593, not 1.0, so this confirms the price carries information beyond series base rates and **does not** test b against 1. Stated because it is easy to misread as support.

**Degeneracy.** Fits at 2–12h leads anchored on `settled_at` quasi-separated (b = 16.5, SE = 988, 100% of fitted probabilities at 0 or 1). They are reported as **not identified**, not as b > 1 — without that guard this audit would have reported a spectacular false positive.

---

## 12. COMPETITIVE ENVIRONMENT

**Verdict: no defensible position, and the prize is being competed for by better-resourced participants.**

**Who is on the other side, by name.** Susquehanna describes itself on its own site as the "**flagship market maker on Kalshi**," providing two-sided liquidity across markets explicitly including **weather**. Jump took Kalshi equity for liquidity provision in February 2026; Cantor opened institutional blocks in August 2026 with Susquehanna pricing. Designated market makers are additionally paid through a CFTC-filed Liquidity Incentive Program scored on spread tightness and size.

**And the professionals arrived recently enough to have reversed the sign of the maker edge.** Becker (2026), on 72.1M Kalshi trades, measures makers at +1.12% and takers at −1.12%, with a **weather-specific maker advantage of 2.57pp** — but reports that the relationship **inverted**: makers were at **−2.0% through 2023**, flipping positive only after October 2024 when professional liquidity providers entered. That is a 5.3-point swing in the one quantity the maker-only thesis depends on, inside two years. A second study (Bürgi, Deng & Whelan, 313,972 Kalshi contracts, maker/taker labelled directly by Kalshi's API) finds its +2.6% above-50¢ maker return is **not replicated once split by days-to-close**, and that **maker losses on closing-day prices resemble takers'** — closing day being precisely the horizon a same-day bot rests into. On Betfair, Whelan finds the maker edge on longshots **disappears as the event progresses**.

What weather1 has that a funded competitor cannot easily reproduce: **almost nothing.** Every forecast input is free and public — NWS/NBM, NOAA AIGFS on S3, ECMWF AIFS, open AI-model archives, and as of 2026-09-03 Google's station-trained WeatherNext 3. The external research is explicit that skill-based edge here is a commodity and the defensible edges are operational. Three genuine, narrow exceptions:

1. **Capacity indifference.** Bürgi et al. name thin volume as the *first* limit to arbitrage — an institution cannot deploy size into a 25-contract book, and a solo trader does not need to.
2. **Variance tolerance.** The same authors invoke proper risk aversion to explain why institutions rationally decline: against a 2.6% mean the return standard deviation is **33%**, a per-trade Sharpe of roughly **0.08**.
3. **Eligibility for Kalshi's open Liquidity Incentive Program.** Genuinely real, genuinely open to an individual with no application, no minimum capital and no volume floor, and it genuinely *excludes* Market Maker Agreement holders — so Susquehanna is barred from this tier. **But it does not currently pay on temperature.** As of 2026-09-10 the only weather series with active or upcoming programs are KXRAIN (44), KXRAINWKND (23) and KXLOWCC (9); there are **zero** on any temperature series. Temperature LIP existed and was switched off — KXHIGHNY last paid 2026-02-07, KXTEMPNYCH 2026-08-04. The bot's own markets pay nothing today.

Against those: the one published practitioner postmortem on Kalshi weather trading reports **0 wins / 32 losses**, attributing it to Gaussian tails (actual extremes about 2× predicted frequency), fee drag on cheap contracts, and being exit liquidity for faster bots. Weather1 uses a normal distribution with a 3.0 °F sigma cap — the same tail assumption — in a system whose own out-of-sample sigma refits made Brier *worse* at all four cutoffs.

**Competitive half-life: SHORT — 12 to 24 months**, on three independent bases: Becker's documented sign inversion when professional LPs arrived; Bürgi et al.'s own year-by-year coefficients decaying to 0.021 in 2025 at only p<0.1; and their explicit warning that such anomalies "tend to disappear once they have been publicized" — which has now happened in **three** independent papers, one of which contains the weather-by-horizon breakdown. For anything forecast-based the half-life is not short but **zero**, since the advantage does not currently exist.

---

## 13. ENGINEERING ECONOMICS

**Verdict: the maintenance base is large and growing faster than any measurable value, and the marginal value of the next development unit is negative.**

| | |
|---|---|
| Python | 283,697 lines, 323 modules |
| Tests | 210 files, 170,397 lines, **6,965 test functions** (0.60 test:source ratio) |
| Commits | **1,656** in 5 months (2026-04-09 → 2026-09-09) |
| Of those, "fix" commits | **1,035 — 62.5%** |
| Revert/rollback/abandon | 89 |
| Retire/remove/delete | 228 |
| Stale branches / tags | 218 / **0** |
| Open backlog entries | **98** |
| Module growth | 47 → 323 files, **6.9×**, in 5 months |
| Value over the same span | −$446.25 paper, **0 live trades** |

The test suite is now large enough that the repo forbids running it unscoped. Operating cadence is decaying: 1.79 scans/day observed, **4 of the last 8 scan cycles reached analysis on one market or none**, and the last cron run was 2026-09-08 23:44 — the system had been idle for ~1.9 days when this audit began.

Open defects include several on correctness-critical paths: the hourly path adds a °F temperature to a probability (L4031); the deterministic blend trades on HRRR under a GFS label, and HRRR is the one model the repo declares excluded from every live blend (L4074); `record_live_partial_exit` can write `fill_quantity=0` and resurrect a position at its original size (L8244); and the METAR lock cannot be retired at any score because the retirement check reads a view excluding all 106 of its rows (L162).

**Marginal value of the next development unit:**

| Work | Expected improvement | P(success) | Effort | Expected economic value |
|---|---|---|---|---|
| Accrue the pre-registered sample to its first look | Resolves the only significant result | High eventually, ~0 in a useful horizon | **2.9 years** at 1.02 settled picks/day | **Negative** — arrives too late; first 10 picks returned −28.9% |
| Read weather.com/kalshi, pin the TWC climate day | Removes specification risk on every daily temp market; named externally as the highest-value indie edge | High — it is a reading task | Hours | **Positive but small**; does not itself create an edge |
| More post-processing / calibration | 5–12% of MAE (0.1–0.3 °F), occasionally negative | Moderate for the metric, ~0 for P&L | The last four months were this | **Negative** — below the 0.5–1 °F observation floor |
| Arm live trading | Converts paper results to real ones | Path never fired at a real exchange | Moderate | **Negative** at a measured negative edge |

---

## 14. OPPORTUNITY COST

The realistic alternatives, ranked by expected value:

1. **Stop and reallocate the time — highest.** The measured expected value of continued development on the current thesis is negative, and the information that would change that arrives in 2.9 years.
2. **Keep the data corpus, drop the trading thesis — the main salvageable value.** 32k price bars, 21k orderbook snapshots, 158k trades and 1,014 settled outcomes cost months to collect and would cost months to rebuild.
3. **Apply the same engineering to the documented underreaction effect — plausible, unvalidated, and a different project.** A ~0.64-for-one price response to new public information with residual drift is a plumbing and latency problem, which is where this repo's real competence lies. It is not a weather bot and should not be built inside one.
4. **Continue as-is — lowest.** Negative measured edge, 98 open defects, a 62.5% fix-commit ratio, a 2.9-year resolution horizon.

The sunk 1,656 commits and 283,697 lines affect the cost of *stopping* — almost nothing, since nothing is deployed with real money — and are not evidence for the thesis.

---

## 15. COUNTERFACTUALS

| Path | Expected value | Reasoning |
|---|---|---|
| **A. Do nothing / stop** | **Best available** | Zero further cost; preserves the corpus and the findings; forecloses nothing that has positive expected value |
| **B. Keep current weather1, minimal development** | Slightly negative | Operating cost is real (the cadence is already decaying) and the forward clock runs 2.9 years with no decision point before then |
| **C. Improve weather1, continue major development** | Clearly negative | The dominant improvement path has 0.1–0.3 °F of headroom under a 0.5–1 °F noise floor |
| **D. Simplify — keep only what is demonstrably valuable** | Near zero | Honest answer: what survives the test is the data pipeline and the $0-maker-fee finding. The price-recal rule is ~200 lines that read none of the other 283,000 — "simplifying" to it means deleting the project and keeping a stub whose coefficient reverses sign by season |
| **E. Build a different strategy with the same skills** | Positive, speculative | The underreaction effect is documented and unexploited here; a latency-oriented build plays to this repo's demonstrated strengths |
| **F. Another prediction-market opportunity** | Positive, speculative | The same 353M-trade study locates robust miscalibration in *political* markets, not weather |
| **G. Another project entirely** | Baseline | The fair comparator, and B and C both lose to it |

---

## 16. EVIDENCE LEDGER

| Claim | Evidence | Source | Direction | Strength | Confidence | Decision Impact | Status |
|---|---|---|---|---|---|---|---|
| The market's probability beats weather1's on every population | Brier 0.1079 vs 0.1702 (n=764); market better on all 4 populations | `predictions.db` `analysis_attempts`, `predictions`⋈`outcomes_valid` | STRONGLY NEGATIVE | Very Strong | Very High | Critical | Proven Failure |
| Weather1's probabilities are worse than constant 0.5 on the traded population | 0.2624 vs 0.2500 (n=347) | same | STRONGLY NEGATIVE | Strong | High | Critical | Proven Failure |
| The model's disagreement with the price is anti-informative | P(yes\|model>mkt)=0.190 vs P(yes\|model<mkt)=0.700, z=−14.6 (n=690) | same | STRONGLY NEGATIVE | Very Strong | Very High | Critical | Proven Failure |
| The forecast-improvement path is structurally closed | Headroom 5–12% MAE (0.1–0.3 °F) vs 0.5–1 °F irreducible observation error; NBM v5.0 already ingests AIFS | NOAA ON 13-1 (574,500 cases); Han et al. 2024; NWS PNS25-45 | STRONGLY NEGATIVE | Strong | High | Critical | Strongly Supported (as a closure) |
| All historical profit came from a fixed leak | 17/17 profitable `above`/`metar_lockout` trades entered before guard `e395392b` | `paper_trades.json` ⋈ `predictions`; `git log` | STRONGLY NEGATIVE | Very Strong | Very High | Critical | Proven Failure |
| The `b>1` result reproduces on its own population | b=1.3310, z=+3.20 clustered (n=690) vs frozen 1.33635/+3.323 | `analysis_attempts`; `cron.py:1290` | POSITIVE | Strong | High | Critical | Supported |
| `b>1` is NOT a ticker-selection artifact | Same source, same lead, split on bot selection: z=−0.15 to −0.61 | `price_history` ⋈ `outcomes_valid` | POSITIVE | Moderate | High | High | Supported |
| `b>1` is NOT a price-source artifact | At matched instants (\|dH\|≤1.5h, n=92) bot price 1.706 vs tape 1.693 | prior internal measurement, backlog L1545 | POSITIVE | Moderate | Medium | High | Supported |
| But `b` reverses sign between seasons at a fixed horizon | H=12h: May–Jun 1.466 (z=+2.01) vs Jul–Sep 0.776 (z=−1.99) | `price_history`, LST-anchored | STRONGLY NEGATIVE | Strong | High | Critical | Strongly Negative |
| **And published work fits the same model on 64.7M Kalshi trades and finds `b` BELOW 1 at every weather horizon inside 48h** | weather slopes 0.69, 0.84, 0.74, 0.87, 0.91, 0.97 inside 48h; 1.20, 1.20, 1.37 only beyond 2 days | Le (2026), arXiv:2602.19520 | STRONGLY NEGATIVE | Very Strong | High | Critical | Proven Failure |
| The rule therefore trades the wrong side at its own horizon | 14 of 14 picks are NO; b<1 implies the 25¢ contract is *under*priced, i.e. BUY YES | `price_recal_shadow_log`; `cron.py:1290`; Le (2026) | STRONGLY NEGATIVE | Strong | Medium-High | Critical | Strongly Negative |
| The maker edge reversed sign when professional LPs arrived | makers −2.0% through 2023 → +1.12% after Oct 2024; weather maker gap 2.57pp; a 5.3pp swing | Becker (2026), 72.1M trades | NEGATIVE | Strong | Medium | High | Negative |
| Maker returns vanish at the horizon the bot rests into | +2.6% above-50¢ maker return not replicated when split by days-to-close; closing-day maker losses resemble takers' | Bürgi/Deng/Whelan, 313,972 contracts | NEGATIVE | Strong | Medium | High | Negative |
| Per-trade Sharpe of the maker edge is ~0.08 | 2.6% mean against 33% return SD | Bürgi/Deng/Whelan | NEGATIVE | Moderate | Medium | Medium | Negative |
| Susquehanna is Kalshi's self-described flagship market maker, in weather | own site lists two-sided liquidity incl. weather; Jump took equity Feb 2026; Cantor blocks Aug 2026 | sig.com/predictions | NEGATIVE | Strong | High | Medium | Strongly Negative |
| Kalshi's Liquidity Incentive Program is open to a solo trader and excludes MM-agreement holders | no application, no minimum capital, no volume floor; the exclusion list names Market Maker Agreement holders | CFTC filing rules02112639183; Kalshi help centre | POSITIVE | Strong | High | Medium | Supported |
| **But no temperature series carries a live incentive program** | as of 2026-09-10, active+upcoming weather programs are KXRAIN (44), KXRAINWKND (23), KXLOWCC (9) and **zero** temperature; KXHIGHNY last paid 2026-02-07, KXTEMPNYCH 2026-08-04 | Kalshi public API `/incentive_programs`, 193,924 programs enumerated | **STRONGLY NEGATIVE** | Strong | High | **Critical** | **Proven Failure (of this path)** |
| Pool sizes are small and shared, and the "$1–$1,000" figure was a misread | the filing sets the daily **pool** at $10–$1,000; $1.00 is the minimum *payout to a user*. Live weather pools are $100/market; Kalshi posted ~$23,310 on weather LIP in 7 days ≈ **$3,300/day across all weather**, shared | Kalshi API + CFTC filing | NEGATIVE | Strong | High | High | Negative |
| The two-sided Target Size gate excludes same-day temperature markets outright | 0 of 6 qualified — books pin one-sided at 0.99/1.00 once the outcome is known | live book measurement, 2026-09-10 | NEGATIVE | Moderate | Medium | Medium | Negative |
| The incentive regime itself is under regulatory scrutiny | CFTC Staff Letter 26-23 (2026-08-12) calls event-contract incentive filings "procedurally or substantively deficient" | cftc.gov | NEGATIVE | Moderate | Medium | Medium | Negative |
| A free, station-trained 2 m temperature model shipped one week before this audit | WeatherNext 3, 2026-09-03: trained on station observations, 0.05°, 64 members, hourly init, 48h range, free to individuals | Google DeepMind; arXiv:2609.03582 | NEUTRAL | Moderate | Medium | Medium | Uncertain |
| And `b` is unstable across horizon inside its own population | 0.98–2.94 across 6 lead bins; 1 of 6 significant | `analysis_attempts` | NEGATIVE | Moderate | High | High | Negative |
| The largest band residual rests on 6 events | band 0.10–0.25: residual −0.110, n=98, but 33 distinct days and **6 YES events** | `analysis_attempts` | NEGATIVE | Moderate | High | High | Uncertain |
| The realised ledger cannot detect a realistic edge | effective n=202; CI [−2.93,+2.83]; MDE $4.11 = 24%/trade | `paper_trades.json`, clustered SE (2 controls passed) | UNCERTAIN | Strong | High | High | Uncertain |
| Realised P&L is negative across both eras | −$446.25 over 294 settled; −73.9% on cost in the archived era | `paper_trades.json` + `paper_archive/` | NEGATIVE | Moderate | Very High | High | Negative |
| No edge threshold produces a defensible positive return | 0 of 13 thresholds have a clustered CI excluding zero | `paper_trades.json` | NEGATIVE | Strong | High | High | Negative |
| Parameter selection does not generalise | bot's own sweep 60–64% in-sample vs 48.7% realised | `param_sweep_results.json`; ledger | NEGATIVE | Strong | High | High | Strongly Negative |
| Weather maker fees are zero | All 390 weather series `fee_type=quadratic`, `fee_multiplier=1`; control `KXNFLGAME` returns the maker variant; `/series/fee_changes` empty; ledger reconciles to 0.0000 | Kalshi live API; `paper_trades.json` | STRONGLY POSITIVE | Strong | High | High | Supported (see caveat) |
| …but the fee premise is not confirmed by the official schedule or a real fill | Kalshi's fee PDF returned HTTP 429 on every attempt; some secondary trackers quote a maker fee of 0.0175·C·P·(1−P); one study describes maker-fee-free as the "pre-2025" structure; `live_fills` is empty | two independent research passes disagreeing | UNCERTAIN | Moderate | Medium | High | Uncertain |
| Maker status is still loss-making on average | makers ≈ −10%, takers ≈ −32% over 300k+ contracts | Bürgi/Deng/Whelan | NEGATIVE | Moderate | Medium | High | Negative |
| Only 8.6% of scanned markets are analysable; half are already decided | 64 of 740 reached analysis; 324 of 676 rejections were `extreme_price` | `scan_funnel.json`, `scan_runs` | NEGATIVE | Strong | Very High | High | Negative |
| Depth, not spread, is the binding constraint | median depth at best ask 25–27; 51.2% with no usable two-sided quote | Kalshi API measurement; independent 9,554-book capture | NEGATIVE | Strong | High | Medium | Negative |
| The market is already well calibrated | raw ECE 0.0162 over 8,494 settled KXHIGHNY; warm-season implied-temperature bias ≈ 0 | CalibShi (tier 7); Ziye Luo SSRN 7138562 | NEGATIVE | Moderate | Medium | High | Negative |
| The "70k markets, 70¢→70%" claim is Kalshi's own marketing | self-reported, no bucket table or SEs, and the 70k is *per horizon* | Kalshi Research, "Hedging Climate Risk" | NEUTRAL | Moderate | High | Medium | Uncertain |
| The pre-registered test cannot finish in a useful horizon | 1.02 settled picks/day → 1,071 days to the 1,100 first look; 5.9 yr to kill | `price_recal_shadow_log`; `tracker.PRICE_RECAL_LOOK_1/2` | STRONGLY NEGATIVE | Very Strong | Very High | Critical | Proven Failure (of the test, not the idea) |
| The rule's first settled picks are losing | 10 settled, 5 wins, −28.9% per dollar, across 4 distinct days | `price_recal_shadow_log` | NEGATIVE | Weak | High | Medium | Uncertain |
| Settlement moved off the NWS CLI report and the new boundary is unread | TWC effective 2026-08-14, verified live (`e853736c`); `metar.py:369` states the boundary is unknown | repo + Kalshi API/rules | NEGATIVE | Strong | High | High | Negative |
| Settlement is no longer purely mechanical | 7 weather rulebooks amended 2026-09-02/03 to allow resolving to a Kalshi-determined last fair price | Kalshi rulebook amendments | NEGATIVE | Moderate | High | Medium | Negative |
| Nothing in the system is proprietary | every forecast input is free and public; AI models operational and free | NOAA EPIC; ECMWF; Google | NEGATIVE | Strong | High | High | Strongly Negative |
| Live execution is entirely unvalidated | `live_fills`=0, `daily_live_loss`=0; L15326 OPEN | `predictions.db`, `execution_log.db`, backlog | UNCERTAIN | Strong | Very High | Medium | Uncertain |
| Paper fill assumptions are sound | resting fills 96–100% realistic; adverse-selection permutation p=0.142; decision price within 1.25–1.5¢ of the tape | prior internal work; this session's paired test | POSITIVE | Moderate | Medium | Medium | Supported |
| Complexity has grown far faster than value | 47→323 modules (6.9×) in 5 months; 62.5% fix commits; 98 open entries; 0 live trades | `git log`, `backlog_index.py` | NEGATIVE | Strong | Very High | High | Strongly Negative |
| A documented, unexploited inefficiency exists — but it is a latency effect | price moves ~0.64-for-one to new public information; residual predicts drift | arXiv 2606.07811 (353M trades) | POSITIVE | Moderate | Medium | High | Plausible |
| Published practitioner experience on this exact strategy is 0 for 32 | 0 wins / 32 losses; blamed Gaussian tails, fee drag, faster bots | Northlake Labs postmortem (tier 6) | NEGATIVE | Weak | Medium | Medium | Negative |

---

## 17. DOMINANT FAILURE POINT

> **DOMINANT FAILURE POINT: weather1's probability estimates are less accurate than the market price it trades against, and the headroom available to fix that is smaller than the measurement noise floor.**

**Can weather1 succeed if this weakness remains unresolved?** No. Every downstream component — fair value, edge, sizing, execution — consumes that probability. A system whose probability is worse than the price cannot profit by disagreeing with the price, and the market-anchor plus `MAX_MODEL_MKT_GAP` gates acknowledge this by discarding the disagreements, which leaves only trades with nothing to win.

**Classification: THESIS-CRITICAL.** Secondary strengths cannot compensate. The engineering is genuinely good (6,965 tests, broad risk machinery), the fee structure is genuinely excellent ($0 maker, verified), the data corpus is genuinely valuable — and none of that can make an anti-informative signal profitable. Per the brief's no-compensation rule: better forecasting cannot compensate for an edge eliminated by costs, and great engineering cannot compensate for negative net P&L; here it is starker still, because the forecasting itself is the failure.

What makes this fatal rather than merely current is the second clause. An implementation failure would be fixable. This is bounded by physics and instrumentation: 0.1–0.3 °F of available improvement against 0.5–1 °F of irreducible error in how the settled value is measured and which day it belongs to.

---

## 18. CORE BOTTLENECK

Walking **Data → Forecast → Probability → Fair Value → Market → Edge → Execution → Settlement → Profit**:

| Link | State |
|---|---|
| Data | **Adequate.** Free public inputs, collected reliably; 32k bars, 21k books, 158k trades |
| **Forecast** | **THE BOTTLENECK.** Worse than the market on every population; over-dispersed upward at the low end (says 0.25 where truth is 0.047) |
| Probability | Broken downstream of the forecast; the repo's own L1893 records intercept −0.69, slope +1.50 against the market beating it on both |
| Fair value | Anchored to the market by construction, then disagreements discarded (L1155) |
| Market | Well calibrated (ECE 0.0162); not the weak link |
| Edge | Computed from a worse-than-market probability, so systematically wrong in sign |
| Execution | Unvalidated live, credible on paper, capacity-capped at ~25 contracts |
| Settlement | Definition changed 2026-08-14 and is unread |
| Profit | −$446.25, statistically indistinguishable from zero in the live era |

**Why it matters:** it is the first link that is worse than its freely available alternative, and every later link inherits it.

**Is it fixable?** No, not to a level that creates edge. **Cost to fix:** the last four months were spent trying — EMOS, Platt scaling, temperature scaling, Venn–Abers, per-city and per-season weights, separate same-day tables, sigma refits. **Probability of fixing it:** low, and bounded above by the headroom-versus-noise-floor argument. **Does fixing it change expected value?** Even a full 12% MAE improvement would not, because the market already prices better than the improved forecast would, and the residual error is dominated by settlement measurement rather than meteorology.

---

## 19. SCENARIO ANALYSIS

### BEAR — reasonable adverse assumptions

The TWC climate-day boundary differs from the bot's assumed window, so some fraction of historical outcomes were scored against the wrong definition and the calibration work rests on mislabelled targets. `b` continues below 1 as the autumn regime deepens, making the longshot fade a negative-expectancy trade. Depth stays at ~25 contracts, capping any viable strategy below the cost of maintaining 283,697 lines. The DMM incentive program lapses, spreads widen from 1¢, and the zero maker fee becomes moot. **Outcome: further losses, plus the operating cost of a decaying system. Forecast edge: none. Net edge: negative. Frequency: falling.**

### BASE — most defensible assumptions

Weather1's forecast remains worse than the market; no threshold, method or calibration change reverses it. `b` stays horizon- and season-dependent, averaging near 1 with no stable tradeable sign. The forward test continues accruing at ~1 settled pick/day and reaches its first look in August 2029 (1,071 days from 2026-09-10) having cost three years. Realised P&L continues to hover near zero with occasional large drawdowns. **Outcome: ~$0 to −$500/year of paper losses, 0 live trades, and a 2.9-year wait for a result that the seasonal sign flip has already made uninterpretable. Forecast edge: none. Net edge: ~0. Competition: unchanged and unbeatable on data.**

### BULL — strong but realistic

The bull case can no longer run through `b > 1`: the published horizon decomposition puts every weather cell inside 48 hours between 0.69 and 0.97, and my own tape measurement agrees. The strongest *honest* bull case is therefore a different one, and it is worth stating precisely because it is the only one left.

The bull case as originally drafted ran through the Liquidity Incentive Program: stop forecasting, rest two-sided orders, collect the subsidy. **That was checked and it does not hold.** There is currently **no incentive program on any temperature series** — only KXRAIN, KXRAINWKND and KXLOWCC pay, and those are a different forecasting problem the bot does not solve. Where weather LIP does pay, the pool is **$100 per market**, and Kalshi posted roughly **$3,300 per day across all weather markets combined**, shared among every participant. A static, no-competitive-response simulation of the published formula puts 100 contracts at the touch at **$11–$78 of a $100 pool** — a ceiling, not a forecast. And the two-sided Target Size gate **excludes same-day temperature markets outright** (0 of 6 qualified), pushing a participant toward next-day books, which are the thinnest.

So the honest bull case is now much narrower: the settlement boundary is resolved (done — it is the NWS CLI report), the outcome labels are sound (checked — 98% internally consistent), and the operator waits to see whether temperature LIP returns. If it returns at a pool materially above $100/market, a passive liquidity business becomes arguable — **on top of** a strategy that stands without it, because the subsidy pays for posting while the measured maker return is still **−9.64%**.

**Forecast edge: none, and none sought. Net edge: negative today on temperature, because the subsidy that would carry it does not exist there. Trade frequency: high by design. Execution: the binding unknown — the live path has never been fired. Competition: barred from this tier, which is the one genuinely favourable fact. Expected future value: approximately zero until a temperature program returns.**

Read this carefully, because it is the decisive scenario: **even the bull case is not a vindication of weather1**, and as of this measurement it is not even a business. It would keep the client, the risk layer and the data, throw away the forecasting thesis that is the project's entire reason for existing, and wait on an exchange subsidy that is currently switched off for the relevant markets.

---

## 20. DECISION STABILITY

**Classification: ROBUST.**

I had this at MODERATELY ROBUST until the external evidence landed. The assumption most likely to flip the recommendation — that `b > 1` might prove stable at a short horizon — has now been *measured and closed* by published work on 64.7M Kalshi trades, in agreement with my own independent measurement. With that door shut, the decision no longer has an identified flip condition inside reach.

Reasonable movement in fees, slippage, fill rate, trade frequency, competition, development time, capital or opportunity cost does not change it. The SUNSET case rests on a forecast comparison with z = −14.6 at n = 764, a headroom argument drawn from external measurements on 574,500 cases, and a horizon decomposition on 64.7M trades. Nothing in the sensitivity set touches those.

**What would still flip it**, and how far the world has to move:

1. **A genuine information asymmetry** — a private or materially faster data source. Not a better public model; by construction every competitor gets those too. This is a change in the owner's resources, not in the measurements.
2. **A 10× capacity change.** Median depth at best ask rising from ~25 to above ~250 contracts would make a thin-margin liquidity business worth building. That is a change in the venue, not in weather1.
3. **A settlement methodology that becomes mechanically predictable from public data the market demonstrably ignores.** Current movement is the opposite direction: the 2026-09-02/03 amendments made settlement *less* mechanical.

**What does not flip it:** better forecast models (the baseline already ingests AIFS, and WeatherNext 3 is free to everyone), more compute, more data within this corpus, a lower fee (already ~zero), a higher fill rate (the sensitivity shows the loss scaling, never reversing), or completing the forward test (which now cannot produce an interpretable pooled coefficient).

One residual caveat, stated because it cuts against me: **if the settlement-definition audit revealed that a material share of historical outcomes were mislabelled, every calibration measurement here would need re-deriving.** It would not make the forecast better than the market — the market is scored against the same labels — but it would reopen the probability work, and it is the one thing I could not check.

---

## 21. WEIGHTED SCORECARD

Scores are 0–10 with a plausible range.

### SHARED EVIDENCE — and how double-counting was prevented

Most of the negative weight in this scorecard traces to **one underlying fact**, not to several independent ones. The dependency chain is:

> **Forecast worse than market** → probability worse than market → fair value anchored to market → no genuine edge → no net P&L

That is **one** advantage failing, observed at five points — not five confirmations. It is the evidence behind *Forecasting / data advantage* (1/10), and it is also the dominant evidence behind *Demonstrated trading edge* (1/10) and *Net profitability potential* (2/10). Those three categories carry 45% of the total weight between them, and if their shared root were counted as three independent findings the score would be artificially depressed.

How it was handled: the three categories are scored on **what each adds beyond the shared root**, and the shared root is counted once.

| Category | Shared root contribution | What is *independent* in this score |
|---|---|---|
| Forecasting / data advantage | the root itself | the external headroom measurement (0.1–0.3 °F vs a 0.5–1 °F floor) — a genuinely separate line of evidence, from NOAA ON 13-1 and Han et al., not from this corpus |
| Demonstrated trading edge | inherits the root | the leak date-split (17/17 pre-guard), the threshold sweep (0 of 13 CIs excluding zero), and the absence of any live trade — none derivable from the Brier comparison |
| Net profitability potential | inherits the root | the verified fee structure (**positive**, and the reason this is 2/10 rather than 1/10), and the external maker-return measurements |

Two other pieces of evidence are genuinely independent of that chain and of each other, which is why they carry weight of their own: the **horizon decomposition** of `b` (a result about the *market*, measured on 64.7M external trades plus my own tape, and entirely separate from weather1's forecast quality), and the **engineering-burden measurements** (commit mix, open defects, module growth).

Conversely, one apparent confirmation was explicitly **not** double-counted: my own finding that `b` is horizon-dependent and Le (2026)'s published finding are *not* fully independent — both measure the same market over an overlapping period using the same estimator. Le's sample is vastly larger and its period wider, so it is treated as the primary evidence and mine as a consistency check, rather than as two votes.

### Demonstrated trading edge — **1/10** (range 0–2) — weight **25%** — contribution 2.50
**Confidence: High.** *Evidence:* −$446.25 over 294 settled; the only profitable stratum was a leak (17/17 pre-guard); 0 of 13 thresholds with a CI excluding zero; no live trades ever. *Main uncertainty:* the live-era CI includes zero, so "no demonstrated edge" is correct but "negative edge demonstrated" is not — hence 1 rather than 0. *Would rise to 4/10 if* the forward test showed a positive return over ≥100 independent events.

### Net profitability potential — **2/10** (range 1–4) — weight **20%** — contribution 4.00
**Confidence: Medium-High.** *Evidence:* the cost side is genuinely excellent — $0 maker fees verified across all 390 weather series, ledger reconciling to 0.0000 — but there is no gross edge for it to preserve, and makers average −10% exchange-wide. *Main uncertainty:* the bull case (§19) is real but small and does not need this codebase. *Would rise to 5/10 if* `b>1` survived a multi-season fixed-horizon test.

### Opportunity size / trade frequency — **3/10** (range 2–4) — weight **10%** — contribution 3.00
**Confidence: High.** *Evidence:* 390 series and ~240 new markets/day is real breadth, but only 8.6% of scanned markets reach analysis, 47.9% of rejections are already-decided markets, median depth is 25 contracts, and validation takes 2.9 years. *Main uncertainty:* international stations are new and unmeasured here. *Would rise to 6/10 if* depth grew materially or a path existed to thousands of settled observations quickly.

### Competitive defensibility — **1/10** (range 0–2) — weight **10%** — contribution 1.00
**Confidence: High.** *Evidence:* nothing proprietary; every input free and public; tight spreads exchange-subsidised via a CFTC-filed DMM program; the one published practitioner postmortem is 0-for-32. *Main uncertainty:* the accumulated data corpus has some reproduction cost, though no exclusivity. *Would rise only if* a genuinely private data source or a latency advantage were acquired.

### Forecasting / data advantage — **1/10** (range 0–2) — weight **10%** — contribution 1.00
**Confidence: Very High.** *Evidence:* market Brier better on 4 of 4 populations; model worse than constant 0.5 on the traded set; disagreement anti-informative at z=−14.6; NBM already ingests AIFS; headroom below the observation noise floor. *Main uncertainty:* none material — this is the best-evidenced finding in the report. *Would rise* only on a demonstrated Brier advantage over the market on a held-out period.

### Technical feasibility — **7/10** (range 6–8) — weight **10%** — contribution 7.00
**Confidence: High.** *Evidence:* the system genuinely works as software — it scans, models, sizes, gates, rests orders, monitors settlement and recalibrates, with broad risk machinery and 6,965 tests. *Main uncertainty:* the live order path has never been fired at a real exchange, and 98 open entries include defects on correctness-critical paths. *Would fall to 4/10 if* arming live trading exposed the execution defects already catalogued.

### Remaining development economics — **2/10** (range 1–3) — weight **5%** — contribution 1.00
**Confidence: High.** *Evidence:* 62.5% of 1,656 commits are fixes; 98 open entries; 6.9× module growth in 5 months against zero live trades; every major development path has negative expected value except one reading task. *Main uncertainty:* a deliberate simplification could lower the burden, but what survives is a stub. *Would rise* only if the thesis were validated first.

### Risk — **4/10** (range 3–6) — weight **5%** — contribution 2.00
**Confidence: Medium.** *Evidence:* risk controls are unusually thorough for a solo project (circuit breakers, kill switch, SPRT, drawdown, flash-crash, watchdog), and no real money is at risk today. Against that: the banner misreports live status, the live path is unvalidated, and settlement specification changed twice in four weeks. *Main uncertainty:* the real risk is operational, and untested. *Would fall* sharply on arming live trading before the execution smoke test.

### Opportunity cost — **2/10** (range 1–3) — weight **5%** — contribution 1.00
**Confidence: High.** *Evidence:* a 2.9-year resolution horizon dominates every alternative; the documented underreaction effect is a better use of the same skills and is a different project. *Main uncertainty:* how the owner values the alternatives, which is their call. *Would rise* if no alternative use of the time existed.

**Weights total 100%. Overall Score = Σ(score ÷ 10 × weight) = 2.50 + 4.00 + 3.00 + 1.00 + 1.00 + 7.00 + 1.00 + 2.00 + 1.00 = 22.5 / 100.**

Against the brief's guidance: CONTINUE needs ≥75 with no critical category below ~6; CONTINUE WITH MAJOR CHANGES needs an underlying opportunity ≥8/10 and ≥65 overall; PAUSE needs opportunity ≥7/10; SUNSET is <50. **22.5 sits well inside SUNSET, and three critical categories are at 1/10.**

---

### THRESHOLD PROVENANCE

Every numeric threshold this decision leans on, with its basis. None was moved to make weather1 pass or fail.

| Threshold | Default | Used here | Basis | Confidence |
|---|---|---|---|---|
| Brier ceiling for "has skill" | 0.25 (constant-0.5) | **0.25, unchanged**, plus the market's own Brier as the binding comparator | 0.25 is the score of refusing to forecast; it is a floor, not a pass mark. The *real* threshold is the market price, because that is what the bot must beat to profit. Both are reported | High |
| Net edge bands | <0% negative, 0–1% marginal, 1–3% interesting, 3–5% strong, >5% very strong | **unchanged** | The brief's bands. They are not load-bearing: every measured threshold row has a CI containing zero, so the decision never turns on which band a point estimate falls in | High |
| Statistical significance | \|z\| > 1.96 | **unchanged, but always on cluster-robust SEs** | Naive SEs are wrong here because one weather draw settles every bracket on a city-day. The clustered estimator was control-tested twice (§11) | High |
| "Large-sample negative" floor | ~300 independent decision-relevant observations | **unchanged**; met for the forecast comparison (n=764) and **not** met for the P&L (effective n=202 with a CI spanning ±2.9) | Applying it selectively is the point: it is satisfied where the evidence is decisive and not where it is not | High |
| Sample-size bands | <100 weak, 100–299 preliminary, 300–499 meaningful, 500+ strong | **unchanged**; 294 combined settled = "preliminary" | The brief's bands, with the effective-n caveat stated rather than the raw count used alone | High |
| Opportunity score for PAUSE / MAJOR CHANGES | ≥7/10 and ≥8/10 | **unchanged** | Deliberately not relaxed. Had I lowered the PAUSE bar to ~3/10 the recommendation would flip, which is exactly why it was left alone | High |
| Overall score for SUNSET | <50/100 | **unchanged**; measured 22.5 | Margin is wide enough that the precise cut point is immaterial | High |
| `b` null hypothesis | b = 1 (perfect calibration) | **unchanged** | b = 1 is the no-mispricing null by construction. Testing against 0 (as a naive correlation test would) would be meaningless — the price obviously predicts the outcome | Very High |
| Degeneracy / quasi-separation cut | none standard | **\|b\| > 5, or SE > 2, or >50% of fitted probabilities at 0/1, or mean fitted variance < 0.01** | Authored for this audit because short-lead fits genuinely quasi-separated (b=16.5, SE=988). Any one of the four trips it; the cut is deliberately loose because a false "degenerate" costs a measurement while a false "identified" costs a wrong conclusion | High |
| Capacity floor for a viable build | none standard | **median depth ≥50 contracts to consider, ≥250 to justify** | Derived from the measured median of 25–27 and the observed mean stake of $17.17: at 25 contracts a position is ~$25 of one side, which cannot service a 283,697-line maintenance base | Medium — the 250 figure is a judgement, and it is flagged as such |
| Bounded-effort cap on surviving tasks | none standard | **two weeks total** | Chosen to be short enough that the three residual tasks cannot quietly become a fourth month of analysis, which is this project's recorded pattern | Medium |

One threshold I deliberately did **not** adopt: the brief's suggestion that the favourite–longshot bias is most exploitable in the $0.05–0.15 and $0.75–0.92 bands. My research refuted both halves — no primary source places the bias in a middle band (Snowberg & Wolfers' Figure 1 is monotone to −61% at 100/1), and liquidity does **not** dry up at Kalshi's extremes, where the 1–10¢ and 90–99¢ bands hold two thirds of the book and the highest maker share. Selecting a price band on that basis would have imported a false premise.

---

## 22. FATAL AND CORE GATES

### Layer 1 — fatal / structural gates

| Gate | Result | Basis |
|---|---|---|
| Structurally unattractive opportunity | **MARGINAL — not confirmed fatal** | Zero maker fees, 390 series, 240 markets/day are real; but 8.6% analysable, depth 25, ECE 0.0162 |
| No credible path to positive net economics | **FAILS (fatal)** | No gross edge exists for an excellent cost structure to preserve; the one candidate reverses sign by season |
| No credible forecasting / trading advantage | **FAILS (fatal)** | Market better on 4/4 populations; worse than constant 0.5 on the traded set; z=−14.6 |
| Structural competitive disadvantage | **FAILS (fatal)** | Nothing proprietary; all inputs free; spreads subsidised; practitioner record 0-for-32 |
| Required development disproportionate to opportunity | **FAILS (fatal)** | 2.9 years to the first pre-registered look; 283,697 lines against a few-hundred-dollars-a-month bull case |
| Negative expected value of continued investment | **FAILS (fatal)** | Every major development path measured negative except one reading task |

**Five of six fatal gates fail. Per the brief, a confirmed fatal gate produces SUNSET and the weighted score cannot override it.**

### Layer 2 — core thesis gates

| # | Gate | Result |
|---|---|---|
| 1 | Opportunity exists | **PARTIAL** — at the venue, probably; in weather forecasting, no |
| 2 | Weather1 can capture it | **FAIL** |
| 3 | Forecasting advantage exists | **FAIL** (proven failure) |
| 4 | Trading advantage exists | **FAIL** (none demonstrated) |
| 5 | Net economics are positive | **FAIL** |
| 6 | Evidence is sufficiently robust | **FAIL** (sign flips by season) |
| 7 | Opportunity is sufficiently large | **FAIL** (depth 25; 2.9-year validation) |
| 8 | Advantage has reasonable durability | **FAIL** (nothing to defend) |

### Layer 3 — weighted score

**22.5 / 100.** Computed after Layers 1 and 2, and it does not override them; it agrees with them.

### Conflict resolution, walked in the prescribed order

The categories conflict (technical feasibility scores 7/10 while three critical categories score 1/10), so the tie-break order is applied explicitly rather than by judgement.

| Step | Test | Result here | Implication |
|---:|---|---|---|
| 1 | Is the underlying opportunity attractive? | **No — 2–3/10.** Market ECE 0.0162; 8.6% of markets analysable and 47.9% of rejections already-decided; median depth 25; forecast headroom below the observation floor | **→ SUNSET.** The order terminates here, but the remaining steps are walked anyway to confirm no later step rescues it |
| 2 | Attractive opportunity, inadequate implementation? | Not reached — the opportunity fails step 1. Had it passed, the surviving change removes the weather system entirely, which is a new project, not a major change | Does not yield CONTINUE WITH MAJOR CHANGES |
| 3 | Credible opportunity, insufficient evidence? | No. Evidence is *sufficient* and adverse: n=764 at z=−14.6 internally, 64.7M trades externally | Does not yield PAUSE |
| 4 | Is unknown being confused with failed? | Checked. P1, P7, P9 are held at UNCERTAIN; the realised P&L is excluded from the case because its CI is [−2.93, +2.83] | The SUNSET case rests only on what is decisively measured |
| 5 | Is this implementation failure or thesis failure? | **Thesis failure.** An implementation failure would be fixable; a 0.1–0.3 °F headroom under a 0.5–1 °F instrument floor is not, and the one non-weather thesis is measured with the wrong sign at its own horizon | Confirms SUNSET rather than MAJOR CHANGES |
| 6 | Is the fundamental strategy sound (CONTINUE) or must components change (MAJOR CHANGES)? | Neither. The fundamental strategy is the failure, and the only surviving component reads none of the system | Neither category qualifies |
| 7 | PAUSE vs SUNSET — is there a specific unresolved question that could realistically change the decision? | **No.** The one such question was `b`'s stability; it has been answered externally and internally, adversely | **→ SUNSET** |
| 8 | CONTINUE vs PAUSE — does evidence meet the continuation standard? | No (22.5 vs ≥75). Is there a cheap decisive experiment? No — the decisive one is already run | **→ SUNSET** |
| 9 | MAJOR CHANGES vs PAUSE — is the destination validated? | The destination (a liquidity-provision business) is *not* validated, and it is a different destination from weather1's | Neither |
| 10 | Failure priority: structural > economic > thesis > evidence > implementation | Failures present at the **structural** level (no defensible position, instrument-bounded headroom), the **economic** level (negative marginal development value), and the **thesis** level (P3/P4/P8) | The highest-priority failure class is engaged, so lower-priority strengths cannot override |

Every step that can terminate the order terminates at SUNSET, and no step yields a different category.

---

## 23. ADVERSARIAL RED TEAM

Assuming SUNSET is wrong, the strongest case for CONTINUE:

> **The project just pivoted away from the thing that failed, and the pivot has the only statistically significant result anyone has found — and the two reasons the literature says such an edge cannot be captured both fail to apply here.** `b = 1.33` at z = +3.3 is a real favourite–longshot signature. The classic objection is that the bias is "efficient within transaction costs" — spreads and fees eat it. But weather1 pays **exactly zero** maker fees (verified across all 390 weather series with a working control) and **rests** rather than crosses, removing both cost terms at once. Meanwhile the thing that was refuted — the weather forecast — is being correctly abandoned. Judging weather1 on its forecast Brier is judging the version that is already retired. The measured paper loss cannot distinguish −$13.88 from zero. And the project has repeatedly been wrong in the *pessimistic* direction too: its own audit refuted two successive drafts accusing the coefficient of being an artifact, and this very session withdrew a price-source accusation and a timezone-leak accusation after measuring them properly.

**What survives falsification:**

- The zero-fee and resting-maker facts survive completely. They are verified, current, and genuinely unusual. This is the strongest true element of the bull case.
- The "judge the new thesis, not the retired one" framing survives as a fair criticism of a lazy analysis — and the report answers it: §4 P1/P8, §11 and §19's bull case all evaluate the pivot on its own terms.
- The caution against pessimistic error survives and is the reason three propositions are marked UNCERTAIN rather than NEGATIVE, and the reason the P&L is explicitly excluded from the SUNSET case.

**What does not survive:**

- **The coefficient is negative at the horizon the rule trades, and this is now published rather than inferred.** This is the falsification that holds, and it is decisive. Le (2026) fits the *identical* `a + b·logit(p)` model on **64.7M Kalshi trades** split by time-to-resolution and reports weather slopes of **0.69, 0.84, 0.74, 0.87, 0.91, 0.97 for every cell inside 48 hours**, exceeding 1 only beyond two days (1.20, 1.20, 1.37). My own independent tape measurement agrees: 1.284 at 6h falling to 0.442 at 36h, with July–September at 0.776 (z = −1.99) at 12h. The bot's frozen 1.336 is a long-horizon number applied to same-day and next-day picks at a median 15.5-hour lead. **With b < 1 the correct trade at 25¢ is BUY YES; all 14 of 14 logged picks are NO, structurally, because the frozen coefficients make the YES branch unreachable.** The rule is not merely unproven — it is pointed the wrong way, against a sample 100,000× larger than its own.
- **Zero cost cannot rescue a signal with the wrong sign.** Removing the fee and spread objections matters only if the signal survives. Worse than not surviving, it inverts: paying nothing to be systematically on the wrong side is still a loss.
- **The maker advantage is quantified, horizon-dependent, and recently reversed.** Makers average about −10% across 300k+ contracts; the above-50¢ maker return is **not replicated when split by days-to-close**; closing-day maker losses resemble takers'; and Becker measures the whole maker/taker relationship **inverting** from −2.0% through 2023 to +1.12% after professional LPs arrived in October 2024. Resting beats crossing. It does not beat zero, and it did not always beat crossing.
- **The forward test cannot arbitrate within a decision-relevant horizon.** 2.9 years to the first look, 10 settled picks returning −28.9%, four distinct target days of independent information.
- **An independent check says the measurement itself is fragile.** A 353M-trade study warns that roughly half of raw calibration-slope variation is estimation noise — precisely the quantity the bull case rests on.

**Verdict: the opposing case identifies a real structural advantage (near-zero-cost maker execution, and eligibility for a liquidity-incentive subsidy Susquehanna is excluded from) attached to a signal whose published sign at this bot's own horizon is the opposite of the one it trades. SUNSET survives, and the adversarial pass strengthened it rather than weakening it.**

The honest residue of the red team is not a case for CONTINUE but a pointer elsewhere: the cost structure and the Liquidity Incentive Program are real, and they argue for *market making*, not for forecasting. That is alternative E in §15, and it is a different project.

---

## 24. VALUE OF INFORMATION

Worth resolving:

| Question | Cost | P(changes decision) | Value |
|---|---|---|---|
| ~~How large is the LIP subsidy for a solo resting-order trader?~~ **ANSWERED 2026-09-10** | 1 research pass | — | **Closed.** The program is real and open, but there are **zero** active or upcoming incentive programs on any temperature series; pools where weather does pay are $100/market against ~$3,300/day shared across all weather. No two-week project here |
| **Does temperature LIP ever come back?** | ~50 lines polling `/incentive_programs`, one day | Low now; would reopen the liquidity-provision option if it returns at a materially larger pool | Cheap enough to be worth it *only* if the operator wants a standing watch rather than a project |
| **What is the TWC climate-day boundary?** (read weather.com/kalshi) | Hours | Low for the decision; high for the integrity of every stored outcome | **Worth doing regardless** — the cheapest item in the project, and it validates or invalidates the entire labelled corpus |
| **Is the zero weather maker fee real?** | One real fill, or one successful read of the official schedule | Low — it would weaken, not strengthen, the case for continuing | Worth doing before any real money moves, because the two research passes disagreed |

Not worth resolving:

- **Whether `b > 1` holds at a short horizon.** This was the highest-value question when this audit began, and it is now **answered**: Le (2026) fits the same model on 64.7M Kalshi trades and finds every weather cell inside 48h between 0.69 and 0.97, with my own independent measurement agreeing. Buying more of this information has negative value — it would only re-confirm a published result on a 100,000× smaller sample.
- **Whether more forecast post-processing helps.** Bounded at 0.1–0.3 °F under a 0.5–1 °F floor. The answer cannot matter.
- **Whether the realised paper P&L is truly negative.** At 24%-per-trade detection power, useful precision needs thousands more trades. Unanswerable at this scale, and not load-bearing.
- **Whether live execution works.** Expensive to learn (real money through an unfired path with catalogued defects) and only relevant if an edge existed.
- **Completing the 2.9-year forward accrual.** Negative value: the information arrives long after it could be acted on, and the published horizon decomposition has already made the pooled coefficient uninterpretable.

---

## 25. FINAL CATEGORY COMPARISON

| Decision | Gate Status | Score | Evidence | Expected Value | Pass/Fail |
|---|---|---:|---|---|---|
| CONTINUE | Fails 5 of 6 fatal gates; 7 of 8 core gates | 22.5 | Forecast worse than market on 4/4 populations; no demonstrated edge; 98 open defects | Negative — further loss plus operating cost | **FAIL** |
| CONTINUE WITH MAJOR CHANGES | Requires underlying opportunity ≥8/10; measured 2–3/10 | 22.5 | Market ECE 0.0162; depth 25; `b` reverses sign by season | Slightly positive only for a stub that needs none of this codebase | **FAIL** |
| PAUSE | Requires opportunity ≥7/10 and a bounded decisive experiment; opportunity 2–3/10 and the cheap decisive experiment has already been run | 22.5 | Selection test completed this session and did not rescue the result; the rule's own test needs 2.9 years | Negative — pays operating cost for information that arrives too late | **FAIL** |
| **SUNSET** | Fatal gates confirmed; core thesis disproven as to forecasting | 22.5 | z=−14.6 directional; headroom 0.1–0.3 °F under a 0.5–1 °F floor; all profit traced to a fixed leak | Best available — zero further cost, preserves the corpus and the findings | **PASS** |

---

## WHY THIS CATEGORY WINS

**Why SUNSET beats CONTINUE.** CONTINUE requires the core thesis supported, net economics positive, and no fatal gate. All three fail. Weather1's probabilities lose to the market on every population tested, including the one it actually trades, where they also lose to answering 0.5 to everything. Five of six fatal gates fail. The brief's no-compensation rule is decisive here: the genuinely excellent engineering and the genuinely excellent fee structure cannot compensate for a signal that is anti-informative at z = −14.6.

**Why SUNSET beats CONTINUE WITH MAJOR CHANGES.** This category requires a *strong underlying opportunity* (≥8/10) with an inadequate implementation. The opportunity measures 2–3/10: the market is already calibrated to 1.6 percentage points, only 8.6% of scanned markets are analysable and half of all rejections are markets already decided, median depth is 25 contracts, and the forecast-improvement headroom is smaller than the irreducible observation error. The failure is not in the implementation of a good idea — the idea that a solo developer can out-forecast a blend that already ingests AIFS, at a station where the settled value is rounded to whole degrees and may never be transmitted, is the part that is wrong. The one change that would qualify as "major" — keep the price-recalibration rule and delete the weather system — produces a ~200-line program that uses none of the remaining 283,497 lines, and whose coefficient reverses sign between the only two seasons in which it can be measured. That is not a major change to weather1; it is a different, unvalidated project that happens to live in the same repository.

**Why SUNSET beats PAUSE.** PAUSE requires a credible opportunity (≥7/10), an unresolved decision-critical question, and a **bounded** experiment whose information value exceeds its cost. The opportunity threshold is not met at 2–3/10. But the stronger reason is that **the decision-critical question is no longer unresolved.**

The brief that set up this work named the selection test on `b` as task one, predicting that if `b → 1` unfiltered, the edge was an artifact of the bot's own gates. I ran it, and the answer was neither outcome it anticipated: the gates are *not* the mechanism (selection effect z = −0.15 to −0.61), but the coefficient is a **horizon** artifact. And that is not merely my inference — Le (2026) fits the identical model on 64.7M Kalshi trades and reports every weather slope inside 48 hours between **0.69 and 0.97**, rising above 1 only beyond two days. My own tape measurement agrees independently. The bot's picks sit at a median 15.5-hour lead, in the range where the published slope is below 1 and the rule's fixed NO side is therefore the **wrong** side.

PAUSE buys information. The information has already been bought, on a sample 100,000× larger than the bot's, and it is adverse. What remains is the rule's own forward test, which needs **1,071 more days** — not a bounded experiment by any reading — and whose first 10 settled picks returned −28.9%. Paying operating cost for 2.9 years to re-confirm a published result at lower precision is negative-value research, and PAUSE here would be exactly the vague middle ground the brief forbids.

**Why SUNSET beats SUNSET-as-a-default — i.e. why this is a reasoned SUNSET and not a shrug at incomplete evidence.** The brief forbids choosing SUNSET merely because evidence is incomplete, and forbids treating "not enough evidence" as "evidence it does not work". This decision respects both. Three propositions are marked UNCERTAIN, not negative: whether exploitable mispricing exists at the venue at all (P1), whether live execution works (P7), and whether the advantage could persist (P9). The realised paper loss is explicitly **excluded** from the case, because at an effective n of 202 its confidence interval is [−2.93, +2.83] and it proves nothing. The SUNSET case rests instead on the measurements that *are* decisive at scale: a 764-observation forecast comparison with a directional z of −14.6, external headroom measurements on 574,500 cases showing the available improvement is smaller than the noise floor, and a robustness test in which the project's one significant coefficient changes sign with the season.

---

## IF SUNSET — what this means in practice

### Exact reasons

1. The forecast is worse than the price it trades against, on every population, including worse than refusing to forecast.
2. The gap is not closable: available post-processing headroom (0.1–0.3 °F) is below the irreducible observation and climate-day error (0.5–1 °F), on a public baseline that already ingests the AI models.
3. Every dollar the project ever made came from a look-ahead leak that was correctly fixed.
4. The one statistically significant result reverses sign between the only two seasons in which it can be independently measured.
5. Its own forward test needs 2.9 years, and its first 10 settled picks lost 28.9%.
6. Nothing in the system is defensible; every input is free and public.
7. The expected value of the next unit of development is negative on every major path.

### Which thesis assumptions failed, and which remain unknown

**Failed:** P2 (public information insufficiently incorporated), P3 and P4 (forecasting advantage — proven failure), P6 (enough opportunities to validate), P8 (robustness), P10 (positive development EV).
**Remain unknown, and are not claimed as failures:** P1 (whether any exploitable mispricing exists at the venue), P7 (whether live execution works), P9 (whether any advantage could persist). Also unknown and unresolvable from the schema: whether outcome backfill ordering ever leaked.

### Why further work is not worth its cost

The dominant failure is bounded by instrumentation, not effort. The test that would change the answer takes 2.9 years through the sealed protocol. The maintenance base is 283,697 lines with 98 open entries and a 62.5% fix-commit ratio, growing 6.9× in five months while producing zero live trades.

### What is reusable — and worth keeping

- **The data corpus.** 32,152 hourly price bars, 21,037 orderbook snapshots, 158,701 trades, 1,014 settled outcomes, 878 analysis attempts. Months to collect, months to rebuild. Keep it; it is the single most valuable artifact.
- **The verified fee finding.** Zero maker fees across all 390 weather series, with the `fee_type`/`fee_multiplier` enumeration method and the `KXNFLGAME` control. Reusable for any Kalshi strategy.
- **The Kalshi client, the settlement monitor, and the risk machinery.** Genuinely good, strategy-independent engineering.
- **The methodological record.** The `.unlazy/` oracles, the mutation-testing discipline, and the backlog's habit of recording *refuted* drafts alongside surviving findings. This is why three wrong explanations were caught in this audit rather than published.
- **This report and the 98-entry backlog** as a record of what was measured and what it cost.

### Which ideas should not be pursued

- Further forecast post-processing, bias correction or probability calibration for Kalshi daily temperature markets.
- Un-retiring the ensemble method, or relaxing the METAR date guard.
- Completing the 2.9-year forward accrual of the sealed pre-registration.
- Arming live trading on the current signal.
- Any strategy whose edge depends on out-forecasting NBM at a well-sited major airport at 0–1 day lead.

### Whether any future event could justify reconsideration

Yes — three, each with a measurable trigger. Note that the trigger that existed when this audit began (*"does `b > 1` survive unfiltered?"*) is **no longer on the list**: it has been measured, externally on 64.7M trades and internally on my own tape, and it failed.

1. **A genuine information asymmetry becomes available.** A private or materially faster data source — not a better public model, which by construction every competitor also gets. Measurable trigger: a data source the owner can access and a named competitor cannot.
2. **The venue's capacity changes by an order of magnitude.** Median depth at best ask above **~250 contracts** sustained over a month of sampling, making a thin-margin liquidity business viable at a size worth the maintenance.
3. **Settlement becomes mechanically predictable from public data the market demonstrably ignores.** Measurable trigger: a published settlement algorithm plus a measured market failure to price it. Current movement is the opposite direction — the 2026-09-02/03 amendments made settlement *less* mechanical.

Absent one of those, this file should stay closed.

### Kill-switch / stopping conditions, if any work continues at all

Three cheap tasks survive this decision (§24). If the owner does them, these are the pre-committed stopping conditions, set **before** seeing any result:

| Condition | Measurable basis | Action |
|---|---|---|
| Total effort across all three surviving tasks exceeds **two weeks** | wall clock | Stop. Confirm SUNSET. |
| No temperature series carries an active or upcoming incentive program | `/incentive_programs?status=active,upcoming` filtered to KXHIGH*/KXLOWT*/KXTEMP* returns zero | **Already true as of 2026-09-10.** Stop — there is no subsidy to collect on the bot's markets |
| Temperature LIP returns at a pool materially above $100/market **and** the live execution smoke test (L15326) passes | the same endpoint, plus a successful real fill | Only then consider a **new**, weather-free liquidity-provision project; do not revive the forecasting pipeline |
| Any real money is placed while L15326 is still OPEN | `live_fills` row count > 0 with the smoke test unpassed | **Halt immediately** — the execution path has never been fired at a real exchange and carries catalogued defects (L8244) |
| The TWC boundary audit shows a material share of stored outcomes were mislabelled | recompute settled extremes under both window definitions against `outcomes.settled_temp_f` | Re-derive the calibration measurements before citing any of them again |
| Median depth at best ask stays below **50 contracts** | Kalshi orderbook sampling over a month | Capacity too small to justify any build |
| Anyone proposes re-fitting or re-reading the frozen `b` as grounds to continue | the proposal itself | Refuse — the horizon decomposition has settled it; re-litigating a closed measurement is the failure mode this project has recorded five times |

---

## FINAL DECISION TEST

**1. If weather1 did not exist today, would you build it?** No. Knowing that the public baseline already ingests AIFS, that available post-processing headroom is 0.1–0.3 °F against a 0.5–1 °F observation floor, that the market's raw ECE is 0.0162, that median depth is 25 contracts, and that the one published practitioner attempt went 0-for-32 — no rational allocation of five months builds this.

**2. Given the existing codebase, is continuing rational?** No. The codebase lowers the cost of continuing but does not change the expected value, which is negative on every major path. The sunk 1,656 commits are not evidence.

**3. Is there credible evidence of a repeatable, executable, net-positive edge?** No. There is one statistically significant result; it is not repeatable across seasons, its executability is untested live, and its net sign depends on the regime.

**4. Is the opportunity large enough?** No. Even the bull case is a few hundred dollars a month gross, capacity-capped at ~25 contracts per market, on a strategy that needs none of this system.

**5. Is the advantage defensible?** No. Every input is free and public; tight spreads are exchange-subsidised; there is no private data and no latency advantage.

**6. Is continued development worth the opportunity cost?** No. A 2.9-year resolution horizon dominates every alternative, including simply stopping.

**7. What is the strongest argument for SUNSET?** That the dominant failure is bounded by instrumentation rather than effort: the model is worse than the price at z = −14.6, and the maximum improvement available (0.1–0.3 °F) is smaller than the irreducible error in how the settled value is measured and which day it belongs to. No amount of engineering crosses that gap.

**8. What is the strongest argument for CONTINUE?** That the project has pivoted to a signal with a genuinely significant coefficient, and that the two cost objections the literature raises against capturing such a signal — fees and crossing the spread — verifiably do not apply, because weather maker fees are zero across all 390 weather series and the bot rests rather than crosses. That combination is real and unusual.

**9. What evidence most strongly contradicts the preferred decision?** The `b = 1.3310`, z = +3.20 fit on 690 rows, together with the refutation of its leading alternative explanation — the bot's own gates do **not** manufacture it (selection effect z = −0.15 to −0.61). A genuinely significant, genuinely unexplained-by-selection result sitting in a zero-fee maker-only venue is the best reason to doubt SUNSET.

**10. What single new piece of evidence would most likely change the decision?** A fixed-short-horizon estimate of `b` on ≥3,000 settled Kalshi weather markets spanning three or more seasons, whose clustered 95% confidence interval excludes 1.0 in the same direction in every season. That is obtainable from historical candlesticks in days rather than the sealed protocol's 2.9 years, and it is the only measurement in this report worth buying before accepting SUNSET.

---

## Appendix — provenance and corrections made during this audit

Every figure above was measured on 2026-09-10 and recorded in the session evidence artifacts described in the header comment (not carried into the repo); each section names the table and query it came from. Inherited claims were re-derived; four measurements of my own were wrong and were corrected before they reached a conclusion:

1. **A "b > 1 significant" result at 2–12h leads was quasi-separation**, not a finding (b = 16.5, SE = 988, 100% of fitted probabilities at 0 or 1). A degeneracy guard now reports these as *not identified*.
2. **An "8.24% of decisions made after expiry" leakage finding was an artifact of my own UTC proxy.** US markets close at midnight local standard time, 5–8h later. Corrected figure: **0 of 690**.
3. **A "the bot's recorded price inflates b" accusation was withdrawn** after a prior internal measurement with tighter instant-matching (|dH| ≤ 1.5h, n = 92) showed the two price sources give the same coefficient (1.706 vs 1.693).
4. **A clustered-SE formula was muddled**, producing an effective n of 13. The corrected estimator passes two controls (singleton-cluster reproduces the iid SE exactly; within-cluster duplication shrinks the iid SE 29.4% and moves the clustered SE 0.0%) and gives **effective n = 202**.

A fifth correction is to my own earlier printed output: a line asserting "no threshold produces a positive net return" was contradicted by the same table's 0.40 row (+8.23%). The corrected reading is in §8 — high thresholds do show positive in-sample P&L, and not one of 13 has a confidence interval excluding zero.
