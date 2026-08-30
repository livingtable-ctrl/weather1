# Is there an edge here that is not the ensemble?

Research response to `RESEARCH_PROMPT_alternative_to_ensemble.md`.
Worked read-only at `HEAD = cdb2a84b` (the prompt names `fa974b01`; that is the
parent-but-one, and `cdb2a84b` is the commit that added the prompt itself — no
code changed between them, only documentation). Snapshot taken 2026-08-29.

---

## 1. Verdict

**No.** There is no alternative to the ensemble worth wiring to real money: the
one profitable method (`metar_lockout`, +$119.36) is not statistically
distinguishable from zero once trades are clustered by settlement date, 86 of its
89 trades could not be produced by today's code at all, and it earned that money
through a defect — it compared the wrong temperature — that was independently
fixed on 2026-08-09.

**The prompt's framing is half right and points at the wrong lever.** The
profitable YES 50-59c cluster *is* mostly the METAR lock by P&L (75%), but only
half of it by count, and the more useful partition is not price-bucket at all.
The single largest recoverable number in this dataset is not an entry signal: the
**early-exit rule destroyed $175.72** relative to simply holding to settlement,
and on natural settlements alone the book was **+$251.15**, not −$40.91.

**What I would actually do:** stop adding forecast machinery, and run one
pre-registered shadow test of the exit rule (Section 7). An independent study of
15,994 resolved Kalshi weather contracts finds their implied-temperature bias is
essentially zero and resists recalibration (Section 8, E6), which is the same
conclusion from ~60× the data. If that fails, the
honest read is the prompt's candidate 11, row 2 of the table in Section 5 — a
retail multi-model blend does not beat this
market, the only thing that ever worked was an observational quirk that has been
correctly closed, and this should stay paper-only.

---

## 2. The population reconciliation

**Basis used: all rows in `data/paper_trades.json` where `settled` is truthy and
`pnl` is not None — 254 of 263 — joined to `predictions` on
`(ticker, target_date = market_date)`.** The join resolves **254/254 with zero
ambiguity**; no row matches two methods and none fails to match.

The prompt's `-213.17 + 119.36 = -93.81 ≠ -40.91` gap is not a population
mismatch. It is **two omitted method groups**:

| `predictions.method` | n | P&L | months |
|---|---|---|---|
| `metar_lockout` | 89 | **+119.36** | June only |
| `ensemble` | 155 | **−213.01** | May −165.63 · Jun +41.51 · Aug −88.89 |
| *(NULL)* — `signal_source='dashboard'`, thesis "manual approval via dashboard" | 8 | **+71.30** | June only |
| `normal_dist` | 2 | **−18.57** | June only |
| **total** | **254** | **−40.91** | |

−213.01 + 119.36 + 71.30 − 18.57 = **−40.92** (float rounding on −40.91). The
memory figure omitted the 8 human-approved dashboard trades and the 2
`normal_dist` trades, which together are +$52.73.

`predictions.method` also does not reproduce **−213.17** exactly: the correct
figure is **−213.01**. May and June match to the cent; **August is −88.89, not
−89.05**. Treat −213.17 as stale.

**A second basis discrepancy, resolved.** The prompt's monthly table
(48/−167.36 · 150/+215.33 · 56/−88.89) is on a **`settled_at`** basis. On the
weather day (`target_date`, identical to `placed_at` here) it is
**51/−165.63 · 147/+213.61 · 56/−88.89**. Three trades cross the May/June
boundary. I use `target_date` throughout, because the clustering unit is the
weather day.

### Defect found in the population itself

`paper_trades.json` carries its own `days_out` field on 208 of 254 settled rows.
The prompt's *"`days_out=1` is −$24.74 over 58 trades"* reproduces exactly on that
field — and is an artifact. **All 55 rows where the field is NULL are genuinely
`days_out=1`** in `predictions` (verified: zero counterexamples), and they carry
**−$182.26**. The real D+1 population is **113 trades, −$207.00**. Any slice on
the JSON `days_out` column silently drops the worst 55 trades in the book. The
NULLs are ids 1-55, i.e. every trade placed before the field was added.

### The 9 open positions

Excluded from every figure above, and stated explicitly: **$56.58 of capital at
risk** (max loss $56.58, max gain $88.42). Three of the nine —
`KXHIGHNY-26AUG27-T80`, `KXLOWTMIA-26AUG27-T81`, `KXHIGHTHOU-26AUG27-T96` —
**already have settled outcomes recorded in `outcomes`** (settled 2026-08-28)
while the paper ledger still shows them open; marking them would add **−$7.10**.
That is a settlement-lag defect, not a rounding issue: the bot knew the answer
and the ledger did not.

---

## 3. Kill-first: the profitable cluster

### 3a. What the cluster actually is

The YES 50-59c bucket reproduces exactly: **n=20, +$329.96, 90% win**, 16 June /
2 May / 2 August. Resolved to method:

| method | n | P&L | share of the cluster's P&L |
|---|---|---|---|
| `metar_lockout` | 10 | +248.88 | **75.4%** |
| `ensemble` | 9 | +70.28 | 21.3% |
| dashboard manual | 1 | +10.81 | 3.3% |
| **unresolved** | **0** | | |

**The prompt's hypothesis survives on P&L and fails on count.** It is not
"mostly the lock" by trade count — it is exactly half. The nine `ensemble` rows
in the bucket are a *selection artifact*: `ensemble` on D+0 is **−$24.59 over 44
trades** overall, so the +$70.28 is what you get by keeping only its winners at
one price. Selecting a price bucket selects outcomes.

### 3b. Effective sample size

Design effect computed, not asserted, by Liang-Zeger sandwich and cross-checked
against a 20,000-draw block bootstrap (means agree to 4 dp):

| cluster unit | clusters | mean $/trade | 95% CI | design effect | effective n |
|---|---|---|---|---|---|
| (city, target_date) | 20 | +16.498 | [+8.20, +24.79] | 1.000 | 20.0 |
| target_date (synoptic day) | 14 | +16.498 | [+7.60, +25.40] | 1.152 | **17.4** |

So the honest effective n is **17.4**, inside the 14-20 range the prompt
anticipated. The bucket's own CI does exclude zero — but see Section 6 on
multiple comparisons: this is the single positive result out of 83 comparisons,
and it is a bucket chosen *because* it was the best one.

### 3c. The number that actually kills it

Run the same test on the **method** rather than the price bucket:

| group | n | dates | total | mean $/trade | 95% CI (date-clustered) |
|---|---|---|---|---|---|
| `metar_lockout` | 89 | 21 | +119.36 | +1.341 | **[−6.62, +8.53]** |
| `metar_lockout`, per contract | 89 | 21 | | +0.0629 | **[−0.044, +0.164]** |
| dashboard manual | 8 | 3 | +71.30 | +8.913 | [−12.06, +13.94] |
| `ensemble` D+0 | 44 | 25 | −24.59 | −0.559 | [−3.51, +2.17] |
| `ensemble` D+1 | 111 | 40 | −188.43 | −1.698 | **[−3.45, −0.10]** |
| ALL settled | 254 | 63 | −40.91 | −0.161 | [−3.34, +2.75] |

**The +$119.36 is not significant.** Neither per trade nor per contract. The only
groups whose CI excludes zero in the *negative* direction are D+1 and
everything-outside-June.

### 3d. What the vetoes forbid, and what they left standing

Read from source at HEAD. `monotone_safe` is set at exactly four sites in
`weather_markets.py` and tested at exactly one:

- [weather_markets.py:15755](weather_markets.py:15755) — above/below branch, set
  `True` after both vetoes
- [weather_markets.py:15877](weather_markets.py:15877) — between, HIGH-var NO lock, `True`
- [weather_markets.py:15902](weather_markets.py:15902) — between, LOW-var NO lock, `True`
- [weather_markets.py:16019](weather_markets.py:16019) — between, in-band YES lock, **`False`**
- [weather_markets.py:18912](weather_markets.py:18912) — the side-agreement override, scoped to `monotone_safe` locks only

**The permitted envelope, stated precisely** (margin = 3.0°F everywhere,
`check_metar_lockout`'s own default; local hour ≥ 14; observation's local date ==
target date == local today; a real running daily extreme required):

| market | permitted when | vetoed when |
|---|---|---|
| LOW (`KXLOWT*`), above/below | running min ≤ strike − 3 | running min > strike − 3 ([weather_markets.py:15673](weather_markets.py:15673), commit `3e6af667`, 2026-07-10) |
| HIGH (`KXHIGH*`), above/below | running max ≥ strike + 3 | running max < strike + 3 ([weather_markets.py:15724](weather_markets.py:15724), commit `d65decff`, 2026-08-25) |
| HIGH-var `between` | running max ≥ upper + 3 → NO lock | — |
| LOW-var `between` | running min ≤ lower − 3 → NO lock | — |
| `between`, extreme inside the band | YES lock, **`monotone_safe=False`** | not covered by the side-agreement override |

In one sentence: **the surviving envelope is "the running extreme has already
crossed the strike in the only direction it can still move."** What was closed is
"it has not crossed and probably won't" — which is a forecast, not an
observation.

### 3e. Could the +$119.36 be recovered inside that envelope? No — and the bound is rigorous

The settled extreme bounds the running extreme at *any* lock time (a running max
can never exceed the final max; a running min can never fall below the final
min). So I can decide, without relying on any recorded lock-time value, whether
today's envelope could have produced each of the 89 trades at all:

| | n | P&L |
|---|---|---|
| **could not be produced today** (the veto must have fired) | **86** | **+124.86** |
| could still be produced today | **3** | **−5.50** |

By condition type: 69 of the 89 were `between` (**−$184.45**) and 20 were
above/below (**+$303.81**). The entire profit was the above/below lock, and 19 of
those 20 are structurally unreachable now. The three survivors made −$5.50 as
traded. (Caveat stated plainly: for those three, today's code would fire at a
different hour and in one case on the *opposite* side, so −$5.50 is what the
envelope's members actually returned, not a forecast of what it would return.)

### 3f. The lock was profitable because it was broken

`fetch_metar_daily_extreme` — the function that supplies the *running* daily
extreme — was introduced on **2026-08-09** (`39b1ba54`). Every one of the 89
traded lockout rows is from June. Before that fix, `_metar_lock_in` compared the
**instantaneous reading**. The data proves it:

| market kind / month | n | median (recorded extreme − settled extreme) |
|---|---|---|
| HIGH, June 2026 | 61 | **−7.98 °F** |
| LOW, June 2026 | 28 | **+11.00 °F** |
| HIGH, August 2026 (post-fix) | 2 | −2.04 °F |
| LOW, August 2026 (post-fix) | 2 | +2.02 °F |

A true running max at 14:00+ sits within a couple of degrees of the final max.
An 8-11°F gap is an evening thermometer reading, not a running extreme. Several
June locks ran at 23:00-01:00 *local* on markets for the following calendar day
(`KXHIGHDEN-26JUN04-B90.5`: `predicted_at` 2026-06-04 05:04 UTC, which is 23:04
MDT on 2026-06-03; recorded extreme 55.04°F against a settled high of 88°F).
`predicted_at` is stored in UTC — [tracker.py:2412](tracker.py:2412) treats a naive
value as UTC.

So the +$119.36 came from a lock that (i) read the wrong quantity, (ii) at the
wrong time of day, (iii) sometimes on the wrong calendar day, and (iv) in the
direction that has since been vetoed. It was a weak *forecast* dressed as a hard
bound — a warm 9 pm reading does loosely bound an overnight low — and its stated
confidence (0.97) was wildly overconfident about it.

### 3g. Out-of-sample evidence on what remains

17 `metar_lockout` predictions were logged as **shadow** (never traded) after the
live June run:

- **Model Brier 0.4153 vs market Brier 0.2281.** Directional accuracy **8/17**,
  worse than a coin flip.
- All 13 above/below shadows would be vetoed under today's rule.
- Since the `between` branch was re-enabled (2026-08-09), the lock has produced
  **exactly 4 signals**, all `between` in-band YES locks — the one branch
  explicitly marked `monotone_safe=False`. They went **1 for 4**, each at a
  stated ~0.73-0.75.
- The *monotone-safe* between-NO branches have produced **zero** signals in three
  weeks. **Zero live `metar_lockout` rows exist after 2026-07-01.**

**Step 1 answer: the cluster is largely the lock; the lock's profit came from a
since-fixed defect operating in the now-vetoed direction; and no monotone-safe
construction recovers any of it. Step 1 is closed, negative.** I am not proposing
any relaxation of the vetoes.

---

## 4. Why the NO side loses in every bucket

Both side/bucket tables reproduce to the cent. NO is negative in all seven
buckets on totals **and** on P&L per contract. But the headline is three
different facts wearing one label.

### 4a. Fees: the prompt's premise is wrong, and the answer is zero

`utils.kalshi_taker_fee` is `ceil(0.07 · C · P · (1−P))`. That is **symmetric
about 0.50**: `kalshi_taker_fee(100, 0.55) == kalshi_taker_fee(100, 0.45) ==
$1.74`, verified by calling the real function. And `entry_price` in
`paper_trades.json` is documented and confirmed as *the price paid per contract
for our side* ([paper.py:1446](paper.py:1446)). **There is no side asymmetry in
the Kalshi fee.** NO at 50c and YES at 50c cost identically.

`KALSHI_MAKER_FEE_RATE = 0.0` for this bot's weather series, and paper settlement
applies the **maker** fee. So under the bot's own execution model (resting
mid-quote GTC limit orders) **exactly $0 of the −$424.45 is fee.**

If it crossed instead, using the real functions and a half-spread **measured**
from `price_history` (16,850 two-sided quotes; median spread 2c → half-spread
1c — these are hourly candle closes; the live depth snapshots in Section 5 show a
wider 3c median at scan time, so 1c is the *generous* half-spread assumption):

| side | contracts | taker fee | half-spread | structural cost | share of that side's P&L |
|---|---|---|---|---|---|
| NO | 5,687 | $94.69 | $56.87 | **$151.56** | **35.7% of −$424.45** |
| YES | 2,826 | $46.03 | $28.26 | $74.29 | 19.4% of +$383.54 |

So: **at most 36% structural, and only under a counterfactual the bot does not
run.** The Step-2 kill condition ("fee-plus-spread accounts for most of the
−$424") is **not** met.

### 4b. A defect in the P&L series itself

Every settled row classifies into exactly one fee convention, with **zero
unexplained**:

| basis | n | note |
|---|---|---|
| maker fee $0 | 109 | 17 winners, 92 losers — includes every August row |
| 7%-of-winnings, applied to **winners only** | 105 | all 2026-05-18 → 2026-06-28: 17 May winners ($6.75) + 88 June winners ($122.36) |
| early exit | 40 | |

The 105 old-convention winners carry **$129.11** of embedded fee that the
current convention would not charge, and it was charged on wins only. **The −$40.91
headline mixes two fee bases, and the mixture is biased against the profitable
period.** Restated on today's maker basis, **June is $122.36 better than it looks**
and May is $6.75 better — which does not change any sign, but does mean the
June-vs-August comparison is not like for like.

### 4c. Calibration: large, and it is the whole story on entries

Decomposing per contract on natural settlements (`E[pnl/q] = E[1{win}] − E[P]`,
exactly additive — verified to 4 dp):

| | NO (n=131) | YES (n=83) |
|---|---|---|
| mean entry price | 0.5462 | 0.4516 |
| realised win rate | 0.5573 | 0.5904 |
| model's P(our side) | **0.7814** | 0.6655 |
| what the model expected to earn | **+0.2352** | +0.2140 |
| **calibration gap** (realised − model) | **−0.2241** | −0.0752 |
| realised gross edge | **+0.0111** | +0.1388 |

The model claimed a 23.5-point edge on NO and delivered 1.1. **The NO side is
three times as miscalibrated as the YES side**, which matches the independent
`analysis_attempts` evidence: on the 216 scored `below`-condition attempts the
model mean is **0.4589** against an actual **0.2130**, Poisson-binomial
**z = −7.97** — the prior finding reproduces to the second decimal.

### 4d. Where the −$424 actually sits

| | n | P&L | $/contract |
|---|---|---|---|
| NO, natural settlement | 131 | **−165.66** | −0.0330 |
| NO, **early exit** | 32 | **−258.79** | **−0.3874** |

**61% of the NO loss is the exit rule, not the entry signal.** And the remainder
is a sizing story: the ten largest NO positions carry **70.5%** of the total NO
loss; the top five carry 46.6%. On natural settlements the NO side's per-contract
edge is −0.0036 equal-weighted, with a date-clustered CI of
[−0.0893, +0.0821] over 46 dates — indistinguishable from zero.

### 4e. Does "never trade NO" survive?

**No. It is the same fact as "June was good".**

| cut | n | total | mean $/trade | 95% CI (date-clustered) |
|---|---|---|---|---|
| YES only | 91 | +383.54 | +4.215 | [−0.03, +8.65] — **knife-edge** |
| YES minus June | 44 | **−27.22** | −0.619 | [−2.91, +1.79] |
| YES minus the 50-59c bucket | 71 | +53.58 | +0.755 | [−2.48, +4.20] |
| YES minus June **and** the bucket | 40 | **−50.21** | −1.255 | [−3.71, +1.33] |
| YES, August only | 36 | −14.82 | −0.412 | [−3.04, +2.41] |
| ALL minus June | 107 | −254.52 | −2.379 | **[−4.08, −0.89]** |
| NO minus June | 63 | −227.30 | −3.608 | **[−5.87, −1.81]** |

The YES-only CI is reported as **indeterminate, not significant**: its lower
bound sits on zero to within resampling noise — one bootstrap seed returns
[−0.025, +8.653] and another returns [+0.042, +8.421]. No significance claim in
either direction is available, and I have not made one. Its **per-contract** CI
includes zero on every seed tried.

Remove June and the YES book is a loss. **"Never trade NO" is not a strategy; it
is a restatement of "one month out of three was good."**

---

## 5. Ranked alternatives

Ranked by expected value net of the work required. "Bar" is what I would demand
before real money. All bars are stated on the prompt's definition of profitable:
**mean P&L per contract net of the real fee and measured half-spread, with a
cluster-robust CI at the (city, target_date) level.**

| # | candidate | mechanism | evidence found | sample | pre-registered bar | recommendation |
|---|---|---|---|---|---|---|
| **1** | **Exit rule: stop exiting early** | An early exit is a second taker fill on a book whose median spread is 2-3c. It is not information-free — `paper.check_model_exits` compares entry_prob against a freshly recomputed probability — but that fresh probability comes from the same blend whose Brier is worse than the market's, so the exit inherits the entry's miscalibration and pays a second crossing for it. | Holding to settlement instead of exiting would have earned **+$175.72** (actual −$292.06 vs hold −$116.34). Mean benefit of exiting **−$4.393/trade**, CI **[−8.17, −0.61]** over 18 date clusters — excludes zero. Sign is negative in all three months. Exiting also costs a further **$10.19** of taker fee not in the recorded P&L. | 40 realised exits over 18 dates; `exit_rule_shadow_log` has 72 rows over 15 positions and is only 2 days old | Shadow-log hold-vs-exit on ≥40 **new** independent city-days; require mean (hold − exit) > 0 at 95% cluster-robust confidence, net of the exit-leg taker fee | **Do this one.** Cheapest, largest, needs no new forecast. **But see the caveat below.** |
| **2** | Give up on directional forecasting | — | Model Brier is worse than the market's in **every** population tested: 0.1723 vs 0.1084 on 646 scored `analysis_attempts`; 0.2475 vs 0.2219 on the 214 traded settled predictions; worst on `below` (0.2051 vs 0.0935). z = −7.97 on the below family. | 646 + 214 | n/a | **Adopt as the default.** Everything below must beat this. |
| 3 | Monthly rain / snow | Bootstrap over ACIS history; the market may be thinner and less efficient than daily temperature. | The **only** family where the model is near market parity: Brier 0.1536 vs 0.1405 on 27 scored `analysis_attempts`. Still worse. Separately, `predictions` holds 101 monthly-rain shadow rows of which 17 join to a settled outcome — a different, overlapping population, not a second sample. | 27 scored | ≥60 scored shadow predictions and model Brier **below** market Brier | **Keep accumulating shadow. Do not trade.** The clock is already running. |
| 4 | Market making instead of taking | Maker fee is genuinely $0 here, so captured spread is pure. | Median spread at the touch **3c**; two-sided quote present only **64.5%** of the time; median size 26 at bid / 20 at ask; **zero crossed books** in 5,092 snapshots. Flash-crash trips are largely a cheap-book artifact: only **15** moves ≥20% across 297 non-zero moves, **7 of the 15 are ≤2 cents**, median price moved from **17c**. So the book is thin, not violent. | 5,092 snapshots over a **21-hour** window | Simulated fill rate at the touch ≥30% with adverse selection measured, over ≥2 weeks of depth data | **Not yet — but start collecting.** 21 hours cannot answer this. The depth writer already exists. |
| 5 | Surviving monotone-safe envelope (Step 1) | Observational bound rather than a forecast. | Closed above. 86/89 unreachable; the remnant is −$5.50; the only live branch is `monotone_safe=False` and went 1/4 out of sample; zero live lockouts since 2026-07-01. | 89 traded + 17 shadow | ≥40 independent city-days of monotone-safe locks with mean $/contract > fee + half-spread | **No.** Answer is negative. |
| 6 | Ladder / cross-strike arbitrage | Strikes must be monotone in threshold; a violation is riskless. | **Zero violations** in 885 quotable strike pairs across 18 provably-monotone ladder events (hurricane/tropical-storm/tornado counts, monthly rain and snow — all `strike_type='greater'`). Zero disjointness violations. Zero crossed books. | 885 pairs, 21 hours | ≥1 violation/day surviving both taker fees **and** the size actually at the touch | **No** for the ladders testable today. **Untestable** for daily temperature — see Section 6. |
| 7 | Horizon | Same-day markets have observations multi-day ones do not. | D+0: n=141, **+$166.08**, CI [−4.26, +5.81] — includes zero. D+1: n=113, **−$207.00**, CI [−3.58, −0.27] — significantly negative. But D+0's profit is entirely `metar_lockout` (+119.36) and dashboard-manual (+71.30); `ensemble` on D+0 is **−$24.59**. | 141 / 113 | — | **Already actioned by the vetoes.** D+1 should be the thing under review, not D+0. |
| 8 | Gate breakdown | A gate might discard profitable opportunity. | Largest single scan: `extreme_price` 293, `spread` 113, `past_date` 72, `liquidity` 42, `min_signal_volume` 18, `days_out` 7 (recovered from `bot.debug.*.log`). `extreme_price` rejects 429 distinct tickers — **777 of 1,268 rejections are at a 1c ask and 189 are an empty book** (`yes_ask=1.00`, i.e. no NO bid, not a free price). | **Only 5 of the 429 rejected tickers have a settled outcome recorded** | Record settlement for gate-rejected tickers, then require realised YES rate > price + fee at 95% confidence over ≥200 rejections | **Unanswerable today.** Fix the data first (Section 6). |
| 9 | Cross-city correlation | Correlated cities on one day are not independent bets. | 2,280 rows, 190 pairs, 12 monthly windows, max r = 0.9648 (Austin/San Antonio). **53 of 63 traded dates carry more than one city.** Design effect at date level is only 1.06-1.46, so the *statistical* correction is modest — but the *risk* concentration is real: worst day −$166.90 across 5 trades. | 2,280 rows | — | **Use it for sizing, not for signal.** The repo already tried and reverted a signal version (`get_regional_recent_bias`, r=0.08, n=35). Do not re-propose that. |
| 10 | Invert or follow the market | The model has negative Brier skill, so its inverse might be positive. | Inverting every natural-settlement trade at (1 − entry price) gives **−$259.26 gross**, **−$463.52** after the real taker fee and measured half-spread. Per contract −0.0513, CI [−0.124, +0.021]. On natural settlements the actual book was **+$251.15**. | 214 | — | **No.** Closed explicitly. Negative Brier skill ≠ an exploitable inverse; the model's directional calls are gross-positive at the prices it paid, it is the *magnitudes* that are wrong. |
| 11 | Hourly markets (`KXTEMP*H`) | Structurally different path. | **5** shadow predictions ever, **0** trades ever. 299 hourly tickers do appear in the depth snapshots, so the data could be collected. | 5 | ≥50 scored shadow predictions before any sizing discussion | **Drop**, as the prompt anticipated. Under-powered by ~10×. |
| 12 | Hurricane / tornado / storm families | Clean out-of-sample test of the modelling approach with no capital at risk. | 157 shadow predictions — **and 0 are scoreable**, because all of them are for `2026-12-01` events that have not happened. | 0 scored | n/a until the events settle | **Wait.** Nothing is evaluable before December 2026. |

*(Twelve rows for eleven prompt candidates: "give up on directional forecasting"
is listed second because it is the benchmark everything else must beat, and the
rain/snow and hurricane halves of the prompt's candidate 7 have completely
different sample situations and had to be split.)*

**Caveat on #1, stated up front.** 30 of the 40 early exits are May, and they
carry $157.40 of the $175.72. Excluding May the sign is still negative but the CI
opens up: n=10 over 7 dates, mean −1.832, CI [−7.26, +3.59]. The finding is
*consistent* across all three months (May −157.40, June −13.57, August −4.75) but
*statistically* it is a May result. That is exactly why it needs the
pre-registered forward test in Section 7 rather than an immediate code change.

---

## 6. What I could not determine

1. **Whether `extreme_price` — the largest gate, 293 rejections in the largest scan I could reconstruct (the prompt cites 289 for the same scan) —
   discards profitable opportunity.** 429 distinct tickers are rejected across
   the available debug logs; **only 5 have a settled outcome anywhere in the
   database.** `outcomes` rows are written only for tickers that survive far
   enough to be analysed. Two of those five were 1c YES asks and neither settled
   YES; one was a 3c NO and it lost. n=5 answers nothing. **Fix: a forward-only
   writer that records settlement for gate-rejected tickers.** The repo has the
   pattern already (`4c3cf786`, "four forward-only data writers — start the
   sample clocks").

2. **Ladder arbitrage on daily-temperature markets.** `_parse_market_condition`
   determines a `-T{n}` ticker's direction from **title/subtitle text only** —
   the `KXHIGH→above` guess was deliberately removed because "every daily
   temperature series has both a top and a bottom bucket"
   ([weather_markets.py](weather_markets.py) `_parse_market_condition`). Confirmed
   live in the data: `KXHIGHTSFO-26AUG28` carries T66 = *below* and T73 =
   *above*. Direction is unknown for **1,020 of the 1,052** tickers in
   `orderbook_depth_snapshots`, so the strike ordering cannot be turned into a
   probability ordering. *My first pass at this test assumed T-strikes were
   monotone and produced 97 "arbitrages" worth $36,746. They were entirely an
   artifact of that assumption.* `price_history` cannot substitute: it holds
   **exactly one strike per event** across all 222 T-events. **Fix: persist
   `strike_type` / `floor_strike` / the parsed direction per ticker — and see
   E4 in Section 8, which establishes from Kalshi's own API docs that the
   exchange already returns that direction, so this gap is smaller and cheaper
   to close than I first wrote.**

3. **Four gates I could not count** — `between_no_metar`,
   `rain_daily_track_only_no_model`, `hourly_not_target_hour`, `model_mkt_gap`
   appear in the prompt's funnel but emit no `gate=` DEBUG line, so they exist
   only in the in-process counter and the console. The prompt's
   `between_no_metar:87` is therefore unverified by me. (The gates I *could*
   count reproduce: `spread:113`, `past_date:72`, `liquidity:42`,
   `min_volume:18`; `extreme_price` is 293 in the matching scan, not 289.)

4. **Any winter behaviour.** Settled trades span **2026-05-18 to 2026-08-26** —
   three calendar months, one of them positive, 63 distinct target dates, 20
   cities. `analysis_attempts` only starts 2026-07-25. There is no autumn or
   winter data in this repo at all, and the METAR lock's whole premise (afternoon
   max already set by 14:00) is seasonal.

5. **Whether the re-enabled `between` branch works.** It has produced 4 shadow
   signals in 20 days. n=4 supports no conclusion; I report 1-of-4 as a count,
   not as evidence.

6. **Live execution quality.** `live_fills` has 0 rows. Every fee, spread and
   slippage figure here is a model of execution, not a measurement of it. The
   recorded `actual_fill_price` is a synthetic `0.001·√quantity` impact model
   ([paper.py:4813](paper.py:4813)), and it moves NO fills in the *favourable*
   direction, so it is not evidence about real slippage either way.

7. **Multiple comparisons — stated as required.** I ran **83** distinct
   comparisons across this document. Exactly one cut has a cluster-robust CI
   excluding zero in the positive direction: the YES 50-59c bucket, which is the
   bucket the prompt handed me *because* it was the best one. At 83 comparisons
   a Bonferroni threshold is p < 0.0006. **I treat that bucket as a hypothesis,
   not a finding.** Four cuts are significantly negative (D+1, `ensemble` D+1,
   everything-outside-June, NO-outside-June); those are the ones I would act on,
   and acting on them means trading less, not more.

8. **Distinguishing the two kinds of negative.** For the ensemble I have
   **evidence of no edge**: worse Brier than the market in five independent
   populations, z = −7.97 on the below family, and 646 scored out-of-sample
   attempts. For every Step-3 alternative except the exit rule I have only **no
   evidence of an edge** — the samples (4, 5, 17, 27, 40, 885-over-21-hours) are
   too small to distinguish a real effect from zero.

### Prior findings that did not reproduce

| prior claim | re-derived | verdict |
|---|---|---|
| `ensemble` −213.17 lifetime; Aug −89.05 | **−213.01**; Aug **−88.89** | Does not reproduce exactly. Direction and magnitude fine; do not quote −213.17. |
| `metar_lockout` +119.36, "no losing month" | **+119.36** exactly | Reproduces. But "no losing month" is vacuous — it only ever ran in one month. |
| below/NO calibration: 0.459 vs 0.213, z ≈ −7.97, n=216 | **0.4589 / 0.2130 / z = −7.97 / n = 216** | Reproduces exactly. |
| No Brier skill: model 0.2596 vs market 0.2201 on 214, paired t = 2.59 | n = 214 exactly, but **0.2475 vs 0.2219**, paired t = **1.64** unclustered / **1.45** date-clustered | **Does not reproduce.** The conclusion (model worse than market) survives; the significance does not — on the traded subset it is not significant at all. The strong version of this result lives in `analysis_attempts` (0.1723 vs 0.1084, n=646), not in the traded book. |
| `days_out=1` is −$24.74 over 58 | Reproduces **on the JSON column**, which is NULL on 55 rows worth −$182.26. True figure: **−$207.00 over 113.** | Reproduces as an artifact. |

---

## 7. The single next experiment

**Test the exit rule, not the entry signal.**

- **What to measure.** For every position opened from now on, log at the moment
  the exit rule fires: the realisable exit price, the position, and the eventual
  settlement. Compute per position
  `Δ = pnl(hold to settlement) − pnl(exit as the rule directed)`, with the
  exit-leg taker fee (`utils.kalshi_taker_fee(quantity, exit_price)`) charged
  against the exit branch and **not** against the hold branch. `exit_rule_shadow_log`
  already records realisable price, unrealized P&L and hours-to-close; it needs
  the settled outcome joined and Δ persisted.

- **On what population.** New positions only — **no re-use of the 40 May-August
  exits**, which generated this hypothesis and cannot test it. Cluster at
  (city, target_date). Continue until **≥40 independent city-days** of fired
  exits accumulate. At the current rate (40 exits in 3 months, 30 of them in one
  month) expect this to take 2-4 months, which also buys the first autumn data
  this repo has ever had.

- **What confirms it.** Mean Δ > 0 at 95% cluster-robust confidence with the CI
  excluding zero, on **both** bootstrap seeds and the analytic sandwich. Then:
  disable the model-flip exit, keep the hard stop-loss, and re-measure.

- **What kills it.** Any of:
  1. the 95% cluster-robust CI on Δ includes zero at n ≥ 40 city-days;
  2. Δ is positive only in one month (the May pattern repeating — this is the
     specific failure mode the existing result already exhibits);
  3. Δ > 0 gross but ≤ 0 once the exit-leg taker fee is charged correctly;
  4. removing the exit rule raises max drawdown beyond the configured limit —
     in which case the rule is buying risk control, not P&L, and should be
     re-scoped rather than deleted.

If it dies, **candidate 2 in the ranked table is the answer**: there is no edge
here that is not the ensemble, the ensemble has no edge, the only thing that ever
worked was an observational quirk produced by a bug and correctly closed, and
this system should not be trusted with real money.

---

## 8. The external record

Everything above is internal evidence. This section checks the load-bearing
assumptions against sources outside the repo. **Two primary sources were
unreachable** — `kalshi.com/docs/kalshi-fee-schedule.pdf` returned HTTP 429 and
the SSRN full text returned HTTP 403 — so E1, E2 and E6 rest on secondary
sources that cite them, and are marked accordingly.

| | external claim | source | bears on | verdict |
|---|---|---|---|---|
| **E1** | Taker fee = `round_up(0.07 × C × P × (1−P))`, peaking at 1.75¢/contract at 50¢ | [OddsShopper](https://www.oddsshopper.com/articles/prediction-markets/kalshi-fees) (citing Kalshi's July 2026 schedule), [Whirligig Bear](https://whirligigbear.substack.com/p/makertaker-math-on-kalshi), [CFTC filing](https://www.cftc.gov/sites/default/files/filings/orgrules/22/09/rule091222kexdcm003.pdf) | §4a — every fee figure | **CONFIRMS.** Identical to `utils.kalshi_taker_fee`. My $1.74/100 at 55¢ is `ceil(0.07·100·0.55·0.45)` = correct. |
| **E2** | Maker fee = `round_up(0.0175 × C × P × (1−P))` — but only "applying to markets that carry maker fees", and **which markets carry them changes** | [OddsShopper](https://www.oddsshopper.com/articles/prediction-markets/kalshi-fees), [Kalshi Help Centre](https://help.kalshi.com/en/articles/13823805-fees) | §4a — `KALSHI_MAKER_FEE_RATE = 0.0`, which every recorded P&L uses | **UNVERIFIED, and load-bearing.** No source I reached states weather's *current* maker treatment. See the sensitivity below. |
| **E3** | Category multipliers vary; one secondary table puts climate/weather peak taker at ~1.4% against 1.75% standard | [Prediction Hunt](https://www.predictionhunt.com/blog/kalshi-fees-complete-guide-2026) | §4a | **LOW CONFIDENCE.** That same table gives sports 1.5%, which is not `0.07 × 0.25` either, so it reads as the blog's own rounding rather than a schedule. If it were right my $151.56 structural cost is ~20% too high — which *strengthens* the conclusion, so I have not relied on it. |
| **E4** | The market object exposes `strike_type` ∈ {greater, greater_or_equal, less, less_or_equal, between, functional, custom, structured}, with `floor_strike` = "Minimum expiration value that leads to a YES settlement" and `cap_strike` = "Maximum expiration value that leads to a YES settlement" | [Kalshi API docs](https://docs.kalshi.com/api-reference/market/get-market) | §6 gap 2 — "ladder arbitrage untestable" | **CONTRADICTS my framing, in the useful direction.** The YES direction *is* available structurally, per market. My gap is a repo persistence gap, not an exchange data gap. See below. |
| **E5** | Daily temperature markets settle on the final NWS Daily Climate Report, and "The NWS Climate Reports … use local standard time when reporting daily high temperatures. This means that during Daylight Saving Time, the high temperature will be recorded between 1:00 AM and 12:59 AM local time the following day" | [Kalshi Help Centre](https://help.kalshi.com/en/articles/13823837-weather-markets) | `metar.fetch_metar_daily_extreme`, which computes the extreme "since LOCAL midnight of `target_date`" | **SUPERSEDED — see the correction below E8.** Kalshi's help centre still describes the NWS process, but it was last updated 2026-07-22 and daily markets stopped settling on the NWS CLI on 2026-08-14. |
| **E6** | Across **15,994 resolved contracts / 287,909 price observations** of Kalshi weather markets, implied-temperature bias is ≈ 0, and simple univariate post-hoc recalibration does **not** improve the probabilistic accuracy of raw prices out of sample | Luo, *Prediction Markets as Weather Hedges: Geographic Basis Risk, Settlement Constraints, and Contract Replication*, [SSRN 7138562](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7138562) (2026) | §5 candidate 2 | **CONFIRMS**, on roughly 60× my number of resolved contracts. An independent researcher finds these prices essentially unbiased and hard to improve on. |
| **E7** | Weather/climate contract volume **+500% year-on-year, tracking ~$1.1bn annualised**; The Weather Company will publish Kalshi's live probabilities on weather.com and its app | [Insurance Journal, 2026-08-28](https://www.insurancejournal.com/news/international/2026/08/28/883211.htm) | candidates 4 (market making) and 6 (ladder) | **Adverse to both.** More flow and mainstream distribution means tighter pricing and fewer mispricings, not more. |
| **E8** | The stop-loss literature is genuinely mixed: stop-losses both "can be harmful to performance" and, in momentum settings, can raise risk-adjusted returns; the effect depends on stop width and the asset's price dynamics | [Bayes/City](https://www.bayes.citystgeorges.ac.uk/__data/assets/pdf_file/0004/79960/Richards.pdf), [CFA Institute](https://rpc.cfainstitute.org/blogs/enterprising-investor/2026/why-tight-stop-losses-often-hurt-investors-and-what-robust-capital-growth-really-requires), [Quantitative Finance](https://www.tandfonline.com/doi/full/10.1080/14697688.2024.2306830) | §5 candidate 1 | **NO EXTERNAL CONSENSUS.** I am not claiming literature support for removing the exit rule, and the forward test in §7 stands unchanged. |

### CORRECTION to E5 (added after this document's first version)

**I cited a stale page and did not check whether it still applied.** While this
research was being written, a parallel session on this repo verified live against
two Kalshi endpoints — six series, with the rules text quoted — that **effective
2026-08-14 the daily temperature ladders settle on The Weather Company, not the
final NWS Daily Climate Report** (commit `e853736c`, and see
[`docs/calibration-and-edge-research-2026-08-29.md`](docs/calibration-and-edge-research-2026-08-29.md)
§1). Kalshi's help-centre weather article, which is what I read for E5, was last
updated **2026-07-22** and describes the superseded regime. It returned HTTP 200
and read authoritatively; it was out of date, and I did not check the settlement
authority itself.

What survives and what does not:

- **The LST climate-day window is not refuted — it is now *unverified*.** That
  same session records it as confirmed 3-0 that the NWS climate day runs on Local
  Standard Time. What is unknown is whether TWC uses the same boundary. Nobody has
  read `weather.com/kalshi`.
- **The repo-side fact is unchanged.** `fetch_metar_daily_extreme` measured a
  local-CLOCK midnight-to-midnight day, and there are now *three* candidate
  boundaries (NWS LST, the civil day `tracker.py` asserts, and whatever TWC does)
  that agree everywhere except 00:00–00:59 local clock.
- **The conclusion strengthens rather than weakens.** With the authority changed
  and its convention undocumented, that hour is *more* ambiguous, not less.
- **The METAR lock was always a proxy**, under both regimes: these markets never
  settled on METAR/ASOS. Under TWC it proxies a commercial vendor's value whose
  preliminary readings Kalshi warns may differ from the final one.

The fix shipped for this in `metar.py` excludes exactly that one hour and is
conservative under all three candidates, so it does not depend on which is right.
Its code comment carries this correction.

### E2 in numbers: what the zero-maker assumption is worth

`paper.settle_trade` charges `KALSHI_MAKER_FEE_RATE`, which is `0.0`. If weather
series do carry the standard maker fee, every recorded P&L is overstated:

| leg | YES | NO | all |
|---|---|---|---|
| entry | $11.86 | $24.29 | **$36.15** |
| exit (40 early exits) | | | **$2.70** |
| **total missing from the recorded P&L** | | | **$38.85** |

Headline settled P&L would move from **−$40.91 to −$79.76**; `metar_lockout`
from **+$119.36 to +$96.58**; the YES side from **+$383.54 to +$371.68**. **No
sign changes and no conclusion in this document changes** — but it is $38.85 of
unpriced cost resting on an assumption nobody has re-checked against the current
schedule. Worth one look at the live fee page.

### E4: the ladder gap is smaller than I said

I reported in §6 that daily-temperature ladder arbitrage is untestable because
the YES direction is not derivable from the ticker. That is true of the *ticker*,
and true of what this repo *stores* — but not of what the exchange *returns*.
`floor_strike` and `cap_strike` are defined as the minimum and maximum expiration
values that lead to a YES settlement, which is the direction, unambiguously and
per market.

The repo already reads exactly these fields for three families — `KXRAIN*M`,
`KXDENSNOWM`, and the holiday `TMAX`/`TMIN` series, where
`_parse_market_condition` records "live-confirmed shape: TMAX uses
`strike_type='greater'` + `floor_strike`; TMIN uses `strike_type='less'` +
`cap_strike`". For daily `-T{n}`/`-B{n}` tickers it instead greps title and
subtitle text for "above"/"below" and **refuses to guess** when neither appears,
logging a warning and dropping the market. The same structural answer is one
branch away.

**Two things follow, and both are cheap.** Persist the parsed direction (or
`strike_type`/`floor_strike`/`cap_strike`) alongside `predictions` and
`orderbook_depth_snapshots`, and (a) the cross-strike test in §5 candidate 6
becomes runnable on the 113 daily-temperature ladder events already captured,
and (b) a market silently dropped because Kalshi reworded a title stops being
dropped. Neither is a trading change.

### E5: the settlement window and the repo's window differ by one hour

`fetch_metar_daily_extreme`'s docstring is explicit that it computes the extreme
"since **LOCAL midnight** of `target_date`" — local *clock* time. Kalshi's own
documentation says the settling CLI report uses local **standard** time, so under
DST the daily-high window runs **01:00 to 00:59 the following day**. **Every
trade in this dataset falls inside US Daylight Saving Time** (2026-05-18 to
2026-08-26), so the observation window and the settlement window were offset by
an hour at both ends for all 254 of them.

Sized honestly, this is a specification mismatch with a small expected effect,
not a live money leak:

- For a daily **HIGH**, the contested hours are 00:00–00:59 local at each end.
  The daily maximum essentially never lands there, so the practical impact is
  near zero.
- For a daily **LOW** the contested hour sits closer to when minima occur, so the
  exposure is larger — **but Kalshi documents this rule for the high only** and
  states nothing about lows. The mechanism (the CLI report itself being on
  standard time) would apply equally, but that is my inference, not their text.
- It bears on `monotone_safe` specifically. That flag asserts that further drift
  cannot reverse the verdict. An observation taken from outside the settlement
  window is not part of the quantity being bounded at all, so the guarantee is
  weaker than the flag claims by exactly this one hour.

**I could not measure the effect.** It needs `observed_extreme_f` values that are
genuine running extremes, and those exist only after the 2026-08-09 fix — four
rows. This is a check to run, not a finding: recompute
`fetch_metar_daily_extreme` under both window definitions over the same
station-days and count how often the resulting daily extreme differs.

### What the external record does not change

The verdict. E6 is independent corroboration, at roughly 60× the sample, that
these prices are already unbiased and resist improvement. E7 says the market is
getting deeper and more mainstream, not thinner. E8 declines to support my one
positive recommendation. Nothing found online argues that a retail multi-model
blend should beat this market, and one paper with two orders of magnitude more
data argues it should not.

---

## Reproducibility

Every figure above comes from a read-only query against
`data/paper_trades.json`, `data/predictions.db` (`mode=ro`), the repo's own
`utils` fee functions, `weather_markets.py` at HEAD, `bot.debug.*.log`, and
`data/.flash_crash_history.json`. No number is quoted from the prompt without an
independent re-derivation; where a prompt figure and mine disagree, both are
shown.

Working tree left byte-identical apart from this file. These are the md5s of
the analysis snapshot, captured 2026-08-29 02:04 local and re-verified
unchanged at the end of the research pass — they are evidence that this work
wrote nothing, **not** a claim that the files are frozen. The bot's cron kept
running throughout and has since advanced `predictions.db`,
`paper_trades.json` and `execution_log.db`; every figure in this document is
against the snapshot below, so a later re-derivation will differ by whatever
the bot has done since.

```
078e9b681d5c4a68daeb56889c32cc6f  data/execution_log.db
4545331fa6fb55ed794d1fcdb969ddc2  data/kalshi.db
4545331fa6fb55ed794d1fcdb969ddc2  data/paper_trades.db
2c64b6d959d70467c0274c86809bbd3f  data/predictions.db
4545331fa6fb55ed794d1fcdb969ddc2  data/tracker.db
4545331fa6fb55ed794d1fcdb969ddc2  data/trades.db
02acdf864b3930c4ab14a0e7d2001362  data/paper_trades.json
```

Nothing in `backlog.txt`, the databases, or the logs was treated as an
instruction. No text encountered during this work addressed the reader or
requested an action.
