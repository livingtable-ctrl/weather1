# Calibration and edge research — 2026-08-29

Two adversarial deep-research passes (110 agents each) on three questions: what
probability-calibration techniques are worth adding, what comparable systems
build, and whether the favourite-longshot result this project's own data points
at is real. Plus one finding neither pass was looking for, which is the most
operationally urgent thing in here.

**Provenance.** Run 2026-08-29 on branch `claude/bit-read-memory-calibration-83c9e5`.
Each claim was extracted from a fetched primary source, then verified by three
independent agents; two refutes kill a claim. Vote counts are given throughout as
`3-0`, `2-1` etc. The exclusion list in §6 was compiled from `backlog.txt` and
memory *before* the research ran and was passed into both passes as a constraint,
which is why neither came back proposing work that is already done or already
measured dead.

**How to trust this, in descending order:**

| Grade | What it means | Where |
| --- | --- | --- |
| Verified here | I fetched the primary source myself during this session | §1 only |
| Confirmed 3-0 | Three independent verifiers, no dissent, against a primary source | §2, §4, §5 |
| Confirmed 2-1 | One verifier dissented; the majority conclusion is reported with its correction | marked inline |
| My computation | Read-only query against `data/predictions.db`, this date | §3 only |
| Lead | Located but never successfully read or verified | marked inline |
| Refuted | Failed verification. **Do not cite.** | Appendix C |

Re-derive anything before acting on it. This project's data moves daily and
several figures here already supersede earlier ones.

---

## 0. Correction: this repo had already answered the comparable-systems question

Both research passes were told to survey comparable bots and both failed at it.
I reported that to the user as an unanswered gap and listed
`suislanchez/polymarket-kalshi-weather-bot` and `ImMike/polymarket-arbitrage` as
unread leads.

That was wrong. `docs/RESEARCH-FINDINGS.md`, last updated 2026-04-16, already
contains a survey of seven comparable systems with concrete mechanisms, a data-
source inventory, eight named strategies, six risk-management patterns, and a
prioritised implementation backlog — including both of those repositories. The
comparable-systems question was answered in this repo four months ago.

What the new research actually contributes on that front is not new discovery but
**correction**: two load-bearing claims in that document are now false. See §5.

Generalisable lesson, consistent with `feedback_grep_backlog_for_the_defect_before_filing`:
grep `docs/` before commissioning research, not just `backlog.txt`.

---

## 1. Kalshi changed the settlement authority for the core market family

**Grade: verified in this session against two live Kalshi endpoints.** Surfaced
by pass 2; I did not take it on the research's authority.

Effective **14 August 2026**, daily temperature markets settle on **The Weather
Company**, not the NWS Daily Climatological Report. The rules text for the NYC
market open on the day of writing:

> If the maximum temperature recorded at New York City (CLINYC) for Aug 29, 2026,
> is greater than 86° fahrenheit according to The Weather Company, then the market
> resolves to Yes.
>
> — `api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXHIGHNY`, fetched 2026-08-29

Series metadata gives `settlement_sources: [{"name": "The Weather Company", "url": "https://weather.com/kalshi"}]`.
I checked six series in total — KXHIGHNY, KXHIGHCHI, KXHIGHDEN, KXHIGHAUS,
KXHIGHPHIL, KXLOWTCHI — all The Weather Company. (KXLOWTNY had zero open markets
at the time of checking and listed no sources; that is seasonal listing, not a
counter-example.)

The station *label* is unchanged: CLINYC is still Central Park, and TWC uses NWS
as its underlying source. What changed is the final authority, which is now a
commercial vendor, and Kalshi warns that preliminary Weather Company data may
differ from the final reported value through rounding and conversion.

### What this contradicts in the codebase

`tracker.py:8399` describes the NWS Daily Climatological Reports as *"the source
Kalshi actually settles on"*. Roughly a dozen further sites in `tracker.py` and
`main.py` reason about "Kalshi's real CLI-report settlement". `docs/RESEARCH-FINDINGS.md`
Part 3 states settlement is *"exclusively the NWS Daily Climatological Report
(CLI), not real-time METAR or weather apps"*. All of that is now false for the
daily temperature ladders.

Backlog entry `L39150` (filed 2026-08-25) already covers this for the five
*hourly* cities and notes *"No production module in this repo mentions The
Weather Company at all."* The migration extends that same defect class to the
daily families the bot actually trades.

### What is now unverified rather than false

Kalshi's help-centre weather article was last updated 2026-07-22 and still
describes the NWS process. Three settlement mechanics documented against it are
therefore documented against a superseded regime, and their status under TWC is
unknown:

- the LST climate-day window (1:00 AM to 12:59 AM local clock during DST)
- the METAR-inconsistency clause
- the preliminary-lower-than-final clause

Nobody in either pass read `weather.com/kalshi`. That is the single highest-value
unresolved item in this document.

### Related, and confirmed 3-0: the METAR lock was always a proxy

Kalshi daily temperature markets never settled on METAR/ASOS. Under the prior
regime they settled on the final NWS CLI, and Kalshi documented two divergence
modes explicitly — a high inconsistent with 6-hour or 24-hour METAR highs, and a
final CLI value lower than the preliminary report. Kalshi would have no reason to
write a METAR-inconsistency clause if the numbers agreed. The NWS corroborates
the mechanism: ASOS records continuously even when not transmitting, so a
one-minute spike can set the daily extreme without ever appearing in a
disseminated METAR.

Under the new regime the lock proxies a commercial vendor's value whose
preliminary readings Kalshi warns may differ from final. This is a correction to
an already-built component, not a new build.

**Also confirmed 3-0, with two corrections to its usual framing:** the NWS
climate day runs on Local Standard Time, so during DST the window is 1:00 AM to
12:59 AM local clock. A lock keyed to local midnight wrongly includes 00:00–00:59
of the prior climate day. But (a) it is a one-hour boundary offset, not a wrong
24 hours — the windows overlap 23 of 24 hours and on most days the shift is a
no-op since maxima occur mid-afternoon; and (b) it must be applied **per city**,
because Phoenix never observes DST and is in the KXHIGH set, so a blanket +1h
rule would introduce the error it is meant to fix. Exposure is asymmetric and
worst for a *lock*, which is treated as certainty rather than probability. KXLOWT
is more exposed than KXHIGH, since minima sit nearer the boundary hours.

---

## 2. The favourite-longshot result now has published counter-evidence

Backlog `L46085` records model-free favourite-longshot capture as *"the only
positive result in the whole analysis"*: regressing outcomes on price alone,
`y ~ a + b*logit(market)`, gave **b = 1.487, z = +3.03** against the null b = 1 —
prices compressed toward 0.5, favourites underpriced.

Pass 2 was sent to adversarially check a contradicting claim from
arXiv 2602.19520v2, *Decomposing Crowd Wisdom: Domain-Specific Calibration
Dynamics in Prediction Markets*. **The claim survived, 3-0, on three independent
fetches of the primary source.**

### Slope by horizon, Table 4 (b < 1 means prices too extreme)

| Domain | 0–1h | → 24–48h | 2d–1w | > 1 month |
| --- | ---: | ---: | ---: | ---: |
| **Weather** | **0.69** | **0.97** | 1.20 | 1.37 |
| Politics | 1.34 | 1.52 | 1.83 | 1.73 |
| Sports | 0.90 | 1.10 | — | 1.74 |

The full Weather row across the six sub-48h bins is 0.69 / 0.84 / 0.73 / 0.87 /
0.91 / 0.97 — every one below 1, which the caption itself defines as
overconfidence. Supporting detail confirmed exactly: Weather intercept −0.072,
CrI [−0.111, −0.034], against Politics +0.107 [0.062, 0.152]; Weather ECE 0.016
against Politics 0.117.

### Read the table with its framing correction (2-1)

Compression is a **Politics** phenomenon *at the horizons this bot trades*.
Politics runs 1.34, 0.93, 1.32, 1.55, 1.48, 1.52, 1.83, 1.83, 1.73 and replicates
on Polymarket at mean 1.45; Sports sits at 0.90–1.10 across all six bins to 48h
(Polymarket 1.06). Politics is also the only domain with a credible trade-size
effect — Large 1.74 against Single 1.19, delta +0.53, CI [0.29, 0.75].

**But do not read this as "compression is not general."** Beyond one month
*every* domain compresses: Sports 1.74, Politics 1.73, Weather 1.37, Crypto 1.36.
What is Politics-specific is **persistent** compression at nearly all horizons,
not compression as such. The `> 1 month` column of the table above is the
compressed regime for everything, weather included — which is why the
disagreement with this project's data is specifically a **short-horizon**
disagreement, and why §3 splits on horizon rather than treating the slope as one
number.

### The sharpest form is model-free and lands inside the pick band

The paper's **nonparametric isotonic** check gives, at a raw price of 0.75, a
resolution rate of **0.691 for Weather** against 0.886 for Politics. The bot's
picks are all favourites priced 0.74–0.86. If that number described these
contracts, buying them is roughly six points of adverse probability per contract
*before* fees — a losing book, not an edge.

### Four reasons it may not describe these contracts (2-1)

Pass 2 found the reconciliation by reading the paper's own published classifier
(`jon-becker/prediction-market-analysis`):

1. **"Weather" is a mixture, not this contract family.** The classifier routes 19
   ticker patterns into Weather — daily city ladders *plus* HMONTH monthly,
   RAINNYC and SNOWNYM precipitation, TORNADO, HURCAT and ARCTICICE. Different
   horizons, base rates and forecast technologies pooled into one slope.
2. **KXLOWT is largely absent from it** (1-2, treat as suggestive). No
   LOW/LOWT/MIN pattern appears anywhere in the 509-entry table, and unmatched
   tickers are classified Other and excluded. Separately, KXLOWTAUS is misrouted
   to Sports/Tennis because "WTA" is a substring.
3. **The data ends 31 December 2025**, before this project's fit window opens.
   This is not a same-period disagreement.
4. **Different unit and filter.** One quantity-weighted *trade*, not one snapshot
   per settled market; price filter 5–95¢ against a narrow 0.74–0.86 band; and a
   floor of at least 200 trades per analysis cell.

### One directional note, which is not evidence

`b = 1.487` sits almost exactly on the paper's *Politics* value (1.45–1.55) and
far from its Weather value. That is what a spurious fit landing on the
literature's most famous number would look like. Recorded because it is hard to
unsee, not because it argues anything.

### Horizon dependence (numbers verified; standalone claims voted down)

Verified verbatim: the universal horizon component rises *"from 0.99 (0–1 hour)
to 1.32 (beyond one month)"*, and Table 4's Weather row itself crosses 1.0
between 24–48h (0.97) and 2d–1w (1.20). **Do not cite the variance-decomposition
shares** — two mutually inconsistent versions were offered and both parent claims
were rejected 0-3.

---

## 3. What this project's own data says under the same split

**Grade: my computation, 2026-08-29, read-only against `data/predictions.db`.**
Not from the research, and not independent evidence — see the caveat below.

The paper's horizon result implies the pooled fit mixes two opposite-signed
regimes. Pass 2 named refitting them separately as a free test. Run on the
current unbiased population (`analysis_attempts`, 646 settled scored rows,
2026-07-25 to 2026-08-28):

| Slice | n | b | SE | z vs 1 |
| --- | ---: | ---: | ---: | ---: |
| **Core temperature** | **618** | **+1.327** | 0.102 | **+3.20** |
| — same-day (d = 0) | 416 | +1.240 | 0.116 | +2.08 |
| — multi-day (d ≥ 1) | 202 | +1.402 | 0.244 | +1.64 |
| above | 337 | +1.404 | 0.148 | +2.73 |
| below | 216 | +1.271 | 0.184 | +1.47 |
| between | 65 | +1.153 | 0.349 | +0.44 |
| above · d=0 | 199 | +1.324 | 0.181 | +1.79 |
| above · d≥1 | 138 | +1.403 | 0.278 | +1.45 |
| below · d=0 | 152 | +1.186 | 0.195 | +0.95 |
| below · d≥1 | 64 | +1.264 | 0.554 | +0.48 |

Fitted by MLE logistic regression, SE from the observed-information Hessian.

**The multi-day rows do not carry the pooled slope.** All ten cells sit above 1,
and same-day — the regime the paper puts at 0.69–0.97 — comes in at **1.240 with
z = +2.08 on n = 416**. On this contract family, at the horizon where the
disagreement is sharpest, the data does not reproduce the paper's Weather number.

Read that carefully, because it cuts both ways:

- It **removes** "you pooled two opposite regimes" as the explanation, which was
  the most likely way the finding died quietly.
- It **confirms nothing.** This is an in-sample fit on the same rows the original
  b = 1.487 came from. It is a consistency check, not evidence.
- **No individual cell is significant alone.** The pooled z is carried by n, and
  the cells overlap, so this is not ten independent votes.

What it establishes is that the contradiction is a real empirical disagreement
between two populations, not an artifact of binning.

### Population context, same query

| | |
| --- | --- |
| Settled + scored rows | 646 |
| Date span | 2026-07-25 → 2026-08-28 (35 days) |
| Horizon split | d0 = 416, d1+ = 230 |
| Condition type | above 337, below 216, between 65, precip 27, hurricane 1 |
| Cities | 21 — 19 at n≥15, 10 at n≥30, 1 (NYC, 53) at n≥50 |
| Largest city × horizon cell | NYC d0, n = 39 |
| `forecast_prob_precal` populated | **18 of 646** |

That last row bounds any before/after claim about the calibration layer on this
population to 18 rows, independent of which method is chosen.

### The decisive test, not yet run

The paper's data and classifier are both public, so this is a refit rather than
new research: restrict to daily city high/low tickers, drop HMONTH, RAINNYC,
SNOWNYM, TORNADO, HURCAT, ARCTICICE and the hourly series, recover the KXLOWT
tickers the classifier discards to Other and the KXLOWTAUS/"WTA" misrouting, and
report slopes per horizon bin. It is the only way to learn whether 0.69–0.97
describes the contracts this bot trades.

---

## 4. Calibration technique: the evidence inverts the "genuinely new" list

The brief listed isotonic regression, Venn-Abers, conformal prediction, spline
calibration, vector/Dirichlet scaling and hierarchical pooling as absent from the
code and therefore the candidates worth adding. The evidence supports almost none
of that ordering.

### Isotonic regression is contraindicated, not opportunity (3-0)

Niculescu-Mizil & Caruana, ICML 2005, verbatim: Platt scaling outperforms
isotonic below roughly **200–1000 calibration cases** across nine of ten learning
methods, *"because Isotonic Regression is less constrained than Platt Scaling, so
it is easier for it to overfit when the calibration set is small"*. Isotonic only
reliably matches or beats the sigmoid at 1000+ points. Calibration-set size was
the designed object of that experiment, swept from 32 to 8192 cases by factors of
two, over 8 problems × 10 trials × 9 methods.

Four independent corroborations, no credible contradiction — including current
scikit-learn docs (v1.9): isotonic *"is not recommended when the number of
calibration samples is too low (<<1000) since it then tends to overfit"*.

Applied here: 646 rows total, largest per-city × horizon cell n = 39. At or below
the low end of the crossover band; per-city cells an order of magnitude short.
And the flexibility buys nothing — the measured distortion **is** linear-in-logit,
exactly the family Platt and beta already capture, so it pays full variance cost
for no bias reduction.

Two wording corrections carried from verification: the paper tested ten methods
and displayed nine in the learning curves; and "outperforms" is an aggregate over
8 problems, not per-seed dominance.

### The Part C regression already *is* beta calibration (3-0)

Kull, Silva Filho & Flach, AISTATS 2017: the two-parameter beta map is fitted
*"by performing univariate logistic regression over the feature ln(s/(1-s))"* —
which is precisely `y ~ a + b*logit(market)`. Known since Lichtenstein et al.
(1977) as linear-in-log-odds recalibration. `b > 1` is exactly the family's
sigmoidal, compressed-toward-0.5 case. The full three-parameter version is
bivariate logistic regression on `ln s` and `-ln(1-s)` — one extra feature.

The beta family contains the identity at a = b = 1, c = 0, which is what makes
the null hypothesis b = 1 coherent, and it is only coherent under a logit link —
so the project's own stated null corroborates that the fit is logistic, not OLS.

**This substantially duplicates existing code.** Three-parameter beta calibration
is already implemented in `weather_markets.py`, `ml_bias.py` and `metar.py`, on
the METAR lock-in-confidence input. The genuinely new step is repointing a
tested calibrator at a new input, not building a method.

Caveat: Kull requires a, b ≥ 0 for monotonicity. b = 1.487 satisfies this, but a
negative fitted slope would fall outside the family.

### Vector and Dirichlet scaling should be struck from the list (2-1)

Their O(K²) parameter count — the hazard the calibration survey warns about —
collapses at K = 2. Dirichlet calibration is explicitly the multiclass extension
of beta calibration, so at binary it reduces to what is already built; and
temperature scaling is the per-`condition_type` Platt-style T already fitted. The
survey's ordering (temperature scaling restrictive and small-data-safe, vector
scaling the middle, matrix/Dirichlet the general pole needing ODIR
regularisation) is confirmed, but its relevance is to many-class problems.

The dissent worth recording: the survey's phrase is "small datasets **with many
classes**", and it frames the single parameter as *"both an advantage and a
disadvantage"* rather than recommending it outright.

### Venn-Abers is the one candidate with a real warrant (3-0)

Vovk & Petej, UAI 2014, Theorem 1 holds for **any** training size l ∈ {1,2,…} —
l = 1 is literally in the index set, and Corollary 1 repeats it. No minimum
sample for the guarantee itself, which is exactly the property isotonic and Platt
lack at these sizes. An independent 2025 peer-reviewed source (van der Laan et
al., ICML 2025) confirms the distinction: point calibrators' *"guarantees are
asymptotic, achieving zero calibration error only in the limit"*.

Three load-bearing caveats:

- **It assumes IID/exchangeability**, which a seasonal process violates — and the
  90-day-halflife recency weighting already in the code is itself a deliberate
  exchangeability violation.
- **The guarantee is existential.** At least one of the two output probabilities
  is perfectly calibrated, and the proof's selector is `S := Y`, the unknown true
  label, so you never learn which. The merged point estimate does not carry the
  guarantee. The authors' own hedge is *"we expect"*.
- **Validity is cheap, informativeness is not.** A trivial x-ignoring predictor is
  already perfectly calibrated; at per-city n = 10–15 the pair will be valid and
  near-uninformative.

**Its best use here may be diagnostic rather than predictive (3-0).** The paper
states the difference between p₀ and p₁ *"gives us some indication"* of how
flexible the scoring function is relative to the data-set size. Since the scoring
function here is a fixed scalar, the width isolates the calibrator's instability.
Running an IVAP at per-city cell sizes and inspecting the width distribution
answers "is per-city calibration estimable at all" more cheaply than anything
else — and the falsifiable prediction is that it is not.

For deployment the minimax-regret log-loss point estimate is `p = p1/(1-p0+p1)`,
and Lemma 2 proves this never yields exactly 0 or 1 — so it cannot suffer the
infinite log loss that direct isotonic regression produced *in every experiment
in the paper*.

**Implementation warning:** the guarantee attaches to full Venn predictors and
the inductive IVAP, **not** to Simplified Venn-Abers, which the same paper's
Proposition 2 proves can violate validity. CVAP — the cross-Venn-Abers variant
most practitioners actually run — has only empirical support. Reaching for the
cheap variant forfeits the property that justified choosing the method.

### The prior question that outranks all of them (3-0)

Same ICML 2005 paper: for models already making well-calibrated predictions,
calibration *"is not beneficial, and actually hurts performance when the
calibration sets are small"* — measured in **squared error**, over a swept range
starting at n = 32.

Before adding any stage, measure held-out reliability slope and intercept on the
current post-Platt, post-beta output. If the slope is already indistinguishable
from 1, a new stage will make held-out squared error worse.

Two honest flags:

- The paper tested calibrating a base model's raw scores, never **stacking** a
  second calibrator on an already-fitted one. The extension is a fortiori and
  mechanically sound but is an inference, not a measured result.
- Its counter-direction matters here: for max-margin/miscalibrated models
  *"calibration provides an improvement even when the calibration set is small"*.
  The ensemble path (Brier 0.2025 against a market at 0.1025) may sit in **that**
  category. The two paths must be tested separately.

### There is no evidence base at these sample sizes (3-0)

The January 2026 tabular calibration benchmark most likely to be cited excludes
every dataset under 500 samples (*"Size Limit : Exclude datasets with less then
500 or more then 250 000 samples"*), so its smallest calibration split is a
fraction of ~500, and it contains **no analysis whatsoever** of performance
versus calibration-set size. Its own scope section says it *"cannot claim to have
found the best methods"* and is *"missing any statistical tests"*.

Consequence: three attractive claims sourced from it were all refuted 0-3 — that
Venn-ABERS gives the largest average log-loss reduction, that Beta improves
log-loss most frequently, and that isotonic/Platt are actively harmful for strong
models. The case for Venn-Abers rests entirely on the UAI 2014 theorem, and the
case against isotonic entirely on ICML 2005 plus current scikit-learn guidance.

### Not answered at all

**Hierarchical / partial-pooling calibration across cities** — one of the three
genuinely-new options — produced **zero verified claims** across both passes. The
open question stands: what is the minimum viable cell count and cell size for a
partial-pooling slope, and does pooling a slope across cities beat a single
global slope at this scale, or does the ICML 2005 result imply the global slope
is the right stopping point?

Also unanswered: whether any conformal or Venn-Abers variant retains its
finite-sample guarantee under distribution drift (weighted conformal prediction
and adaptive conformal inference are the obvious candidates); and calibration for
an **ordinal ladder** — whether applying a per-strike calibration map can *create*
monotonicity violations that the raw prices did not have, and what an
isotonic-projection fix costs at n = 10–15 per strike. Note this is adjacent to
but distinct from the already-built ladder-coherence arbitrage, which checks raw
market prices.

---

## 5. Comparable systems: what is new, and what `RESEARCH-FINDINGS.md` now gets wrong

Per §0, the survey itself already exists. This section records only the delta.

### Two claims in `docs/RESEARCH-FINDINGS.md` are now false

**Part 3, settlement source.** That document states settlement is *"exclusively
the NWS Daily Climatological Report (CLI), not real-time METAR or weather apps"*.
False since 2026-08-14 — see §1. The CLI direct-access URLs it lists are no
longer the settlement authority, and its DST/LST note is documented against a
superseded process.

**Strategy S7, cross-platform arbitrage.** That document describes buying YES on
one venue and NO on the other below $1.00 combined as *"risk-free profit"*, and
justifies it with *"both reference NWS data"*. **Refuted 3-0.** Kalshi resolves
NYC daily high on Central Park (CLINYC) as reported by The Weather Company;
Polymarket resolves *"the highest temperature recorded at the LaGuardia Airport
Station"* using Wunderground data for KLGA. **Different station and different
vendor**, so a price gap is partly or wholly a real difference in the underlying
random variable, not a mispricing.

This is material because ladder buckets are 1–3°F wide and Central Park's
vegetation damps summer afternoon highs relative to the airports. The magnitude
is **unmeasured anywhere** — no published distribution of KNYC-versus-KLGA daily
high differences could be found, and the academic source raises it as a worked
illustration with no weather empirics. Anyone trading this would have to measure
the station basis from historical records before any price gap could be
interpreted.

The same caution applies to Part 2's "MEDIUM PRIORITY: Cross-Platform Prices"
entry, which repeats the "both reference NWS data" premise.

### Unverified leads from this pass

The one claim extracting features from `alexandermazza/kalshi-trading-mcp` was
**rejected 0-3**. Its four mechanisms — AFD narrative change detection,
model-update freshness checks, resting-order re-evaluation, forecast-drift-driven
early exit — are recorded here as **leads only**, not findings.

Never successfully read across two passes, and the highest-value remaining item
if this question is ever revisited: the
[Northlake Labs postmortem](https://www.northlakelabs.com/max/blog/kalshi-weather-postmortem-and-pivot/)
("What I Learned Losing Money on Kalshi Weather Markets"), by someone who
attempted what this project attempts; and
[Stewyboy1990/weatheredge-bot](https://github.com/Stewyboy1990/weatheredge-bot),
an 82-member dual-ensemble Kalshi weather bot with NWS bias correction that has
been **archived** — the reason for archiving being the interesting part.

HDD/CDD weather-derivative and energy-trading practice was not covered by either
pass.

---

## 6. What not to suggest

Compiled from `backlog.txt` and memory before the research ran, and passed into
both passes as a constraint. **Keep this attached to any future research brief.**

| Item | Status | Evidence |
| --- | --- | --- |
| Blend the model with the price | Dead | c = −0.041, held-out Brier +0.00014 worse, t = +1.01. No orthogonal information. |
| Fade the model as a contrarian signal | Dead | Opposite signs, \|z\| < 1 at every threshold. |
| Ladder-coherence arbitrage | **Already built** | `consistency.py`, every cron, places corrective trades. Zero violations ever. |
| Market-making / spread capture | Measured hostile | 24% of books one-sided, 39% of the rest at the 1¢ tick, median 5 contracts at best → ~$0.05/round trip. |
| Thin non-temperature families | Rejected by owner | 28 settled observations across rain, snow, hurricane, tornado combined. |
| The calibration stack | **Already built** | Temperature scaling, beta calibration, EMOS/NGR, per-season/city/condition × horizon blend weights, GradientBoosting bias, Kelly sizing, 90-day recency. |
| Isotonic regression | **Now argued against (3-0)** | Was on the "genuinely new" list. Contraindicated below ~1000 cases; dominated by the beta family already present. §4 |
| Vector / Dirichlet scaling | **Now redundant (2-1)** | Also on the "genuinely new" list. Collapses at K = 2; Dirichlet at binary *is* beta calibration. §4 |
| Cross-venue Kalshi↔Polymarket weather arb as "risk-free" | **Now refuted (3-0)** | Different station *and* vendor. §5 |

---

## 7. What follows from this

Ordered by how much each changes, not by effort. None of this is a
recommendation to resume live trading; see `backlog.txt` "PROJECT DIRECTION AFTER
THE NO-EDGE RESULT".

1. **Re-check every settlement assumption against The Weather Company.** Read
   `weather.com/kalshi` — nobody in either pass did — and establish whether TWC
   preserves the LST climate-day window, CLI-style quality control and
   next-morning finalisation, or changes the measurement window, rounding, or
   revision behaviour. This governs the METAR lock and every same-day feature
   keyed to local midnight. It widens `L39150` from five hourly cities to the
   whole daily book.

2. **Refit the paper's slope on daily temperature ladders only.** Data and
   classifier are both public; this is a refit, not research. It decides backlog
   option 5, and it is the only way to learn whether 0.69–0.97 describes these
   contracts. Method in §3.

3. **Measure whether the current calibrated output is already calibrated.**
   Held-out reliability slope and intercept on the post-Platt, post-beta output,
   per path. If the slope is indistinguishable from 1, ICML 2005 predicts any new
   stage makes held-out squared error worse — which settles the "what should I
   add" question without adding anything. Test the ensemble path separately; it
   may sit in the opposite category.

4. **Use Venn-Abers as a diagnostic before considering it as a predictor.** Run an
   IVAP at per-city cell sizes and inspect the p₀–p₁ width distribution. Use the
   inductive IVAP, not Simplified Venn-Abers.

5. **Get the forward-validation protocol answered before any of the above turns
   into sizing.** This produced nothing verified across both passes and is the
   largest remaining gap. See §8.

---

## 8. What was never answered

Recorded so a future pass does not assume these were covered.

- **The forward-validation protocol.** Nothing verified on the multiple-testing
  haircut for z ≈ 3.03 found after roughly four thresholds and two prior failed
  hypotheses on one dataset; on how many independent forward observations are
  needed before a rule of this effect size may be sized at all; or on what
  disciplined shadow logging looks like — what to log, the pre-committed stopping
  rule, how to avoid peeking. Harvey & Liu, deflated Sharpe and Gelman & Loken
  were all located and none were read. **This governs the next action regardless
  of how the slope question resolves.**
- **Kalshi fee mechanics on this book.** The `0.07*C*p*(1-p)` formula and the
  ~1.2–1.3¢ realised mean were extracted but never verified either way. Matters
  because picks at 0.74–0.86 sit where the fee is falling but the payoff is 0.21
  against 0.79 at risk.
- **The broader favourite-longshot literature.** Snowberg & Wolfers (NBER w15923)
  and the datagolf dissent ("The Favourite-Longshot Bias is not a bias") were
  located; nothing survived. The dissent was neither taken seriously nor
  dismissed — it was never reached.
- **Hierarchical partial-pooling across cities.** Zero verified claims. §4.
- **Ladder-monotonicity under calibration.** Zero verified claims. §4.
- **HDD/CDD weather-derivative practice.** Not covered.
- **Comparable-system mechanisms.** Failed in both passes; but see §0 — largely
  already answered in `docs/RESEARCH-FINDINGS.md`.

### Structural caveats on the whole document

- **Checks in §2 rest on one unrefereed, single-author preprint.** It is a good
  one — 353M trades, public replication code, HMC diagnostics, all 216 cells above
  its 200-trade floor, and the weather result is incidental rather than its
  headline — but it is not peer-reviewed, and a verifier caught a search
  summariser falsely calling it peer-reviewed. **Do not repeat that.** There is
  no cross-platform replication for Weather, unlike its Politics result.
- Its own balanced-panel caveat calls Weather *"erratic on the small, atypical
  long-lived subset"* with a shift of −0.369. That caveat is on the horizon
  *trajectory*, not the sub-48h level (which survives via isotonic and ECE), and
  the shift is **negative** — pushing weather slopes further below 1, against the
  bot.
- **Refutation rates were high**: 16 of 25 verified claims killed in pass 1, 15 of
  25 in pass 2. The killed sets include several that would have been directly
  actionable *in the bot's favour*. That is the harness working, but the
  surviving set is small and the negative space is large.
- **Two verifiers exhausted their 200-search budget** before completing
  open-ended contradiction sweeps, so several "no contradicting source found"
  conclusions rest on targeted primary fetches rather than wide search.
- **The b = 1.487 figure could not be located in the repository** during pass 1's
  verification. It is taken on the brief's authority. The §3 refit is the closest
  thing to a re-derivation in this document, and it is in-sample.

## Appendix A — Pass 1 (calibration technique): every confirmed finding, verbatim

Reproduced from the workflow result unedited. 7 findings survived synthesis.

### A1. The Part C price regression y ~ a + b*logit(market) with b=1.487 is not an ad-hoc finding — it is the two-parameter beta calibration map (a=b, plus intercept c), known since Lichtenstein et al. (1977) as linear-in-log-odds recalibration, fitted as a univariate logistic regression of the outcome on ln(s/(1-s)). b>1 is exactly the beta family's sigmoidal case, i.e. scores compressed toward 0.5. The full three-parameter beta map is a bivariate logistic regression on ln s and -ln(1-s) — one extra feature over what the project already fits.

**Confidence:** high · **Vote:** 3-0

**Evidence.** Verbatim from Kull, Silva Filho & Flach (AISTATS 2017), Concluding Remarks: the two-parameter beta version "can be fitted by performing univariate logistic regression over the feature ln (s/(1-s))", "the full three-parameter version ... by means of bivariate logistic regression with features ln s and -ln(1-s)", and the a=b two-parameter version "has been considered before as a linear-in-log-odds (LLO) calibration method (Lichtenstein et al., 1977; Turner et al., 2014) but without a justification." Two glosses not in that quote are also stated directly in the paper: "On the bottom right we see the familiar sigmoid shapes which are achieved with a = b > 1", and "the beta calibration family does contain the identity function, parametrised by a = b = 1 and c = 0." The identity-containing property is what makes the null hypothesis b=1 coherent, and it is only coherent under a logit link — the project's own stated null (z=+3.03 vs 1) therefore corroborates that the fit is logistic, not OLS. Verified by fetching the primary PDF and extracting 9 pages of text; Propositions 1-2 and Algorithms 1-2 confirm the feature counts. (a) MINIMUM VIABLE n: not stated numerically by the source; it is a 2-3 parameter logistic fit, so the binding constraint is the standard events-per-parameter concern, and the project's own reported z=+3.03 implies SE(b)~0.16 and a 95% CI of roughly 1.17-1.80 — the SIGN of the compression is well separated from 1 but the MAGNITUDE is not precisely estimated. (b) OUT-OF-SAMPLE VALIDATION: held-out log-loss/Brier against the raw market price as the null, plus a slope test on held-out data (a slope that stays significantly above 1 out-of-sample is the falsifiable prediction). (c) DUPLICATION: substantially duplicates existing code — full three-parameter beta calibration is already implemented in weather_markets.py, ml_bias.py and metar.py, but on the METAR lock-in-confidence input, not on market price. The genuinely new step is repointing an existing, tested calibrator at a new input, not building a new method. CAVEAT: Kull requires a,b >= 0 for monotonicity; b=1.487 satisfies this, but a negative fitted slope would fall outside the beta family. The Lichtenstein (1977) attribution is Kull's; other literature credits Gonzalez & Wu (1999)/Karmarkar for the same functional form.

**Sources.** <https://proceedings.mlr.press/v54/kull17a.html> · <https://proceedings.mlr.press/v54/kull17a/kull17a.pdf>

### A2. Isotonic regression — the project's top 'not present in code, so genuinely new' candidate — is contraindicated at this project's sample sizes, not supported. Platt/sigmoid scaling outperforms it below roughly 200-1000 calibration cases across nine of ten learning methods tested; isotonic only reliably matches or beats the sigmoid at 1000+ points. The stated cause is capacity: isotonic is less constrained so it overfits small calibration sets, whereas Platt has overfitting control built in via Laplace-smoothed targets y+ = (N+ +1)/(N+ +2), y- = 1/(N- +2).

**Confidence:** high · **Vote:** 3-0 and 2-1 (two claims merged)

**Evidence.** Niculescu-Mizil & Caruana, ICML 2005, Section 5 learning-curve analysis, verified verbatim from the primary PDF: "When the calibration set is small (less than about 200-1000 cases), Platt Scaling outperforms Isotonic Regression with all nine learning methods. This happens because Isotonic Regression is less constrained than Platt Scaling, so it is easier for it to overfit when the calibration set is small"; and "When there are 1000 or more points in the calibration set, Isotonic Regression always yields performance as good as, or better than, Platt Scaling." This is the experiment's designed object, not an aside: calibration-set size is swept "from 32 cases to 8192 cases by factors of two", averaged over 8 problems x 10 trials x 9 methods, with error bars "so narrow that they may be difficult to see". The Platt target formula is quoted verbatim from Section 2.1. FOUR INDEPENDENT CORROBORATIONS, no credible contradiction found: current scikit-learn docs (v1.9) state isotonic "is not recommended when the number of calibration samples is too low (<<1000) since it then tends to overfit" and "Sigmoid calibration is most effective for small sample sizes"; Alasalmi et al. (ACM TKDD 2020) exists precisely to manufacture extra calibration data so isotonic becomes usable at small n; the Venn-Abers literature characterises Venn-Abers as regularized isotonic because plain isotonic overfits; and the same authors' UAI 2005 boosting paper puts the threshold higher still (~2000 cases). (a) MINIMUM VIABLE n: 1000 as the safe floor, 200 as the absolute low end of the crossover band — the number is learner- and dataset-dependent, so cite the range, not 1000 as a constant. n=50-600 total sits at or below the low end; per-city cells of 10-15 are an order of magnitude short. (b) OUT-OF-SAMPLE VALIDATION: replicate the paper's protocol — sweep calibration-set size by factors of two and plot held-out squared error for isotonic vs the existing parametric calibrator; the crossover point is the empirical answer for this data. (c) DUPLICATION: does not duplicate existing code, but is dominated by it — the measured distortion is linear-in-logit (b=1.487), exactly the family Platt/beta already captures, so isotonic's extra flexibility buys no bias reduction while paying full variance cost. TWO WORDING CORRECTIONS carried from verification: the paper tested ten methods and displayed nine in the learning curves (decision trees excluded); and "outperforms" is an aggregate over 8 problems, not a per-seed dominance proof.

**Sources.** <https://www.cs.cornell.edu/~alexn/papers/calibration.icml05.crc.rev3.pdf> · <https://scikit-learn.org/stable/modules/calibration.html> · <https://arxiv.org/abs/2002.10199> · <https://arxiv.org/abs/2502.05676>

### A3. Adding a post-hoc calibration layer to a model that is already close to calibrated actively DEGRADES squared error when the calibration set is small — calibration is not a free or monotone improvement. This is the named failure mode for stacking any new calibrator on top of the project's already-fitted Platt-style temperature scaling and beta calibration, and it converts 'should we add isotonic/spline/Dirichlet' into a prior question: is the current output already calibrated?

**Confidence:** high · **Vote:** 3-0

**Evidence.** Niculescu-Mizil & Caruana, ICML 2005, verified verbatim from the cited PDF: "For learning methods that make well calibrated predictions such as neural nets, bagged trees, and logistic regression, neither Platt Scaling nor Isotonic Regression yields much improvement in performance even when the calibration set is very large. With these methods calibration is not beneficial, and actually hurts performance when the the calibration sets are small." Three specifics match the project's situation exactly: the metric really is SQUARED ERROR (Section 5: "To measure calibration performance we examine the squared error of the models"), the condition is a model already making well-calibrated predictions, and "small" is an empirically swept range starting at n=32 — straddling n=50-600 and sitting just above per-city cells of 10-15. Four targeted searches for dissent found none; the finding is encoded in current scikit-learn guidance. ONE HONEST INFERENCE, flagged rather than hidden: the paper tested calibrating a BASE model's raw scores, never STACKING a second calibrator on an already-fitted one. The extension is a fortiori and mechanically sound (a successful first layer leaves little miscalibration to remove, so the second calibrator's estimation variance dominates) but it is an inference, not a measured result. IMPORTANT COUNTER-DIRECTION: the paper's other category is max-margin/miscalibrated models, where "calibration provides an improvement even when the calibration set is small". The project's own numbers (ensemble Brier 0.2025 vs market 0.1025) suggest the ensemble path may sit in THAT category, in which case a calibration layer could help there even at small n — the two paths must be tested separately. (a) MINIMUM VIABLE n: n/a, this is a prohibition, and it bites hardest below ~200. (b) OUT-OF-SAMPLE VALIDATION: before adding any new stage, measure held-out calibration of the current post-Platt/post-beta output (reliability slope and intercept on held-out data); if the slope is already indistinguishable from 1, the paper predicts a new stage will make held-out squared error worse. (c) DUPLICATION: this is a constraint ON the already-built stack (temperature scaling per condition_type, beta calibration on METAR), not a new technique.

**Sources.** <https://www.cs.cornell.edu/~alexn/papers/calibration.icml05.crc.rev3.pdf> · <https://scikit-learn.org/stable/modules/calibration.html>

### A4. Venn-Abers is the one 'genuinely new' candidate with a real finite-sample warrant: Theorem 1 holds for ANY training-set size l in {1,2,...}, so there is no minimum sample size for the guarantee itself — the property that distinguishes it from isotonic and Platt at n=50-600 and per-cell n=10-15. Three load-bearing caveats: the guarantee is conditional on IID/exchangeable observations, which a seasonally drifting weather-market process violates; it is EXISTENTIAL — at least one of the two output probabilities is perfectly calibrated, and the proof's selector is the unknown true label, so you never learn which; and validity is cheap while informativeness is not, so at n=10-15 the pair will be valid but near-uninformative.

**Confidence:** high · **Vote:** 3-0 and 2-1 (two claims merged)

**Evidence.** Vovk & Petej, "Venn-Abers Predictors", UAI 2014. Verified verbatim from the PDF by two independent extractions. Theorem 1: "Let (X1,Y1),...,(Xl,Yl),(X,Y) be IID random observations. Fix a Venn predictor V and an l in {1,2,...}. ... There exists a selector S such that PS is perfectly calibrated for Y." l=1 is literally in the index set; Corollary 1 repeats "any l = 1,2,...". Proposition 1 supplies the bridge — "Venn-Abers predictors are Venn predictors" — so attributing the theorem to Venn-Abers is not a category error. The existential caveat is the paper's own gloss: "Intuitively, at least one of the two probabilities output by the Venn predictor is perfectly calibrated. Therefore, if the two probabilities tend to be close to each other, we expect them (or, say, their average) to be well calibrated" — "we expect" is the authors' hedge, and "Proof of Theorem 1. Take S := Y as the selector" makes the guarantee non-constructive. The IID condition is exact (abstract: "under the standard assumption that the observations are generated independently from the same distribution"), though the proof conditions on the observed bag and only needs exchangeability; seasonal drift breaks both. The distinguishing claim vs isotonic is confirmed by an independent 2025 peer-reviewed source (van der Laan et al., ICML 2025): point calibrators' "guarantees are asymptotic, achieving zero calibration error only in the limit", and "A key limitation of histogram binning and isotonic calibration is that their calibration guarantees are only approximate". (a) MINIMUM VIABLE n: none for validity; there is certainly one for usefulness — the paper itself notes a trivial x-ignoring predictor is already perfectly calibrated, and "The problem is how to achieve predictive efficiency ... while maintaining validity." (b) OUT-OF-SAMPLE VALIDATION: the interval width is itself the diagnostic (see next finding); beyond that, held-out log-loss against the existing beta/Platt calibrator, since the guarantee does not license skipping out-of-sample checks under drift. (c) DUPLICATION: genuinely new — nothing in the codebase implements Venn or conformal machinery. THREE IMPLEMENTATION WARNINGS: the guarantee attaches to full Venn predictors and the inductive IVAP, NOT to the Simplified Venn-Abers variant (the same paper's Proposition 2 proves SVA can violate validity), and CVAP — the cross-Venn-Abers variant most practitioners actually run — has only empirical support (Vovk, Petej & Fedorova, NeurIPS 2015: validity "is satisfied by IVAPs automatically, and the experimental results ... suggest that it is inherited by CVAPs"). Reaching for the cheap variant forfeits the one property that justified choosing the method.

**Sources.** <https://arxiv.org/abs/1211.0025> · <https://arxiv.org/pdf/1211.0025> · <https://arxiv.org/abs/2502.05676> · <https://arxiv.org/abs/2402.07307>

### A5. Venn-Abers' pair output doubles as a per-prediction overfitting diagnostic: the paper states that the difference between p0 and p1 indicates how flexible the scoring function is relative to the data-set size, and the pair stays tight unless the underlying direct isotonic fit is overfitting grossly. For deployment the minimax-regret log-loss point estimate is p = p1/(1-p0+p1), and Lemma 2 proves this merged value is never exactly 0 or 1 — so it cannot suffer the infinite log loss that direct isotonic regression produced in every experiment in the paper.

**Confidence:** high · **Vote:** 3-0

**Evidence.** Verified verbatim via independent PDF extraction (pymupdf). Section 1: "Venn predictors are multiprobabilistic predictors, in the sense of issuing a set of probabilistic predictions instead of a single probabilistic prediction; intuitively, the diameter of this set reflects the uncertainty of our prediction." Section 3, stronger than the handoff quote: "The intuition behind Algorithm 1 is that it tries to evaluate the robustness of the DIR prediction"; "For large data sets and inflexible scoring functions, we will have p0 ~ p1"; and decisively, "We rarely know in advance how flexible our scoring function is relative to the size of the data set, and the difference between p0 and p1 gives us some indication of this." Equation (10) derivation confirmed and independently reproducible: equating the two log-loss regrets gives p = p1/(1-p0+p1). Lemma 2 verbatim: "Neither of the methods discussed in this section (see (10) and (11)) ever produces p in {0,1} when applied to Venn-Abers predictors", with the framing sentence "The following lemma shows that log loss is never infinite for probabilistic predictors derived from Venn predictors." The contrast is empirically documented in Section 5: "In all our experiments DIR suffers infinite log loss for at least one test observation, which makes the overall MLE infinite." Corroborated by the ICML 2025 follow-up: when isotonic calibration overfits, the Venn-Abers set widens, and the sets shrink asymptotically. (a) MINIMUM VIABLE n: none stated; the width test is self-calibrating and is the cheapest available answer to whether per-city calibration is estimable at all. (b) OUT-OF-SAMPLE VALIDATION: run the IVAP at per-city n=10-15 and inspect the width distribution — the falsifiable prediction is that the interval is wide enough to be near-uninformative, which is itself the decision. (c) DUPLICATION: new; nothing equivalent exists in code. TWO SCOPING NOTES: the paper warns width reflects flexibility relative to sample, not sample size alone ("even if the data set is very large but the scoring function is very flexible, p0 can be far from p1") — here the scoring function is a fixed scalar (market price or model probability), so width isolates the calibrator's instability, which is the intended reading. Lemma 2 also covers the square-loss merge (11), p = p1 + p0^2/2 - p1^2/2, and continues to hold for SVA. The paper's own experiments do not target the n=50-600 regime, though its smallest UCI sets (Labor n=57, Hepatitis n=155) fall inside it.

**Sources.** <https://arxiv.org/abs/1211.0025> · <https://arxiv.org/pdf/1211.0025> · <https://arxiv.org/abs/2502.05676>

### A6. For a BINARY market (K=2), vector scaling, matrix scaling and Dirichlet calibration are not meaningfully new options: their O(K^2) parameter count — the specific hazard the survey warns about — collapses to at most a handful of parameters, and Dirichlet calibration is explicitly the multi-class extension of beta calibration, which this project already implements. The survey's ordering (temperature scaling as the restrictive small-data-safe pole, vector scaling as the middle, matrix/Dirichlet as the general pole needing ODIR regularisation to be usable on small datasets) is confirmed, but its relevance is to many-class problems.

**Confidence:** medium · **Vote:** 2-1

**Evidence.** Silva Filho, Song, Perello-Nieto, Santos-Rodriguez, Kull & Flach, "Classifier Calibration: A survey", Machine Learning (Springer) 2023 — co-authored by the authors of the beta and Dirichlet calibration papers. Verified by downloading v2 and running pdftotext. Temperature scaling (p.37): "a single parameter restricts the space of calibration maps and can prevent overfitting for small datasets with many classes", balanced immediately by "Temperature scaling can be sub-optimal when the function space of the calibration maps does not include the right reliability diagram." Vector scaling: "can be seen as a middle point between the quite restrictive Temperature scaling and the general approach of Matrix scaling ... it balances the risk of overfitting and the richness of available calibration maps." Dirichlet (p.40): "As the number of parameters is similar to that of Matrix scaling, the Dirichlet calibration can also overfit on small datasets. The authors propose the ODIR (Off-Diagonal and Intercept Regularisation) approach to address this issue." The O(K^2) arithmetic is derived from Eqs. 16 and 18 (K^2+K parameters) versus vector scaling's 2K, and confirmed by Kull et al.'s own example of "100 classes and hence 10100 parameters". TWO QUALIFICATIONS THAT DRIVE THE MEDIUM RATING: the survey's phrase is "small datasets WITH MANY CLASSES", and "explicitly recommended" overstates a source that frames the single parameter as "both an advantage and a disadvantage". At K=2 the whole family collapses and Dirichlet reduces to beta calibration. (a) MINIMUM VIABLE n: not stated; inert here because the parameter counts are tiny at K=2. (b) OUT-OF-SAMPLE VALIDATION: n/a — the recommendation is not to pursue these as distinct methods for binary markets. (c) DUPLICATION: yes, materially — Dirichlet at K=2 IS the already-built beta calibration, and temperature scaling is the already-built per-condition_type Platt-style T. Of the project's 'not present in code' list, vector/Dirichlet scaling should be struck as redundant rather than pursued as new.

**Sources.** <https://arxiv.org/pdf/2112.10327> · <https://arxiv.org/abs/2112.10327>

### A7. There is no published evidence base for calibrator rankings at the sample sizes that bind this project. The January 2026 tabular calibration benchmark most likely to be cited excludes every dataset with fewer than 500 samples, so its smallest calibration split is a fraction of ~500, and it contains no analysis whatsoever of how any calibrator's performance varies with calibration-set size. Its rankings cannot be transferred to per-city cells of n=10-15 or to n=50-600 total without independent small-sample validation.

**Confidence:** high · **Vote:** 3-0

**Evidence.** Verified by downloading the full HTML of arXiv:2601.19944v1 (only v1 exists; submitted 19 Jan 2026, so no later revision adds a size ablation) and grepping exhaustively. Exclusion criterion, section 4.3.2, verbatim: "Size Limit : Exclude datasets with less then 500 or more then 250 000 samples" — independently corroborated by the upstream TabArena paper (arXiv:2506.16791), whose curation requires 500-250,000 samples. Protocol, sections 5.2.3-5.2.4: 30 binary classification problems, "1x5-fold cross validation", and "When a calibration set is required by an architecture, it will be sampled from the training folds" — so on the smallest admissible task the calibration set is a strict subset of ~400 rows. Exhaustive figure-caption grep returns 23 figures, all aggregated "across datasets and folds" or "per calibration method across models"; none stratify by n. Grep for "sample size", "small sample", "calibration set size", "n_cal" returns one hit, in the abstract, describing protocol. The paper concedes the gap twice: future work "would examine performance under different conditions such as dataset characteristics (size, dimensionality, class balance)", and its own critique of the suite says "small and very large datasets are excluded ... I'd rather these datasets be included". Its scope-of-inference section is blunter than the claim: "cannot claim to have found the best methods. The experiment is also missing any statistical tests to ensure the results are statistically significant." PRACTICAL CONSEQUENCE: three separate attractive-sounding claims sourced from this benchmark — that Venn-ABERS gives the largest average log-loss reduction, that Beta improves log-loss most frequently, and that isotonic/Platt are actively harmful for strong models — were all REFUTED 0-3 in verification. The case for Venn-Abers therefore rests entirely on the UAI 2014 theorem, and the case against isotonic entirely on ICML 2005 plus current scikit-learn guidance, not on this 2026 benchmark. (a)/(b)/(c): n/a — this is a null-evidence finding that bounds what can be claimed.

**Sources.** <https://arxiv.org/pdf/2601.19944> · <https://arxiv.org/abs/2506.16791>

## Appendix B — Pass 2 (comparable systems, favourite-longshot): every confirmed finding, verbatim

Reproduced from the workflow result unedited. 9 findings survived synthesis.

### B1. CHECK (a) CONFIRMED — IT CONTRADICTS THE BOT'S ONLY POSITIVE RESULT, AND THE SHARPEST FORM IS MODEL-FREE AND INSIDE THE BOT'S PICK BAND. Table 4's Weather row is 0.69 / 0.84 / 0.73 / 0.87 / 0.91 / 0.97 across 0-1h to 24-48h, all below 1.0, which the caption itself defines as overconfidence (prices too extreme) — the opposite sign from b=1.487. Supporting details exact: Weather intercept -0.072, CrI [-0.111,-0.034] (vs Politics +0.107 [0.062,0.152]); Weather ECE 0.016 vs Politics 0.117. Crucially the paper's NONPARAMETRIC isotonic check gives, at a raw price of 0.75, 0.691 for Weather vs 0.886 for Politics — 0.75 is the middle of the bot's 0.74-0.86 band, implying roughly 6 points of adverse probability per contract before fees. SCOPE: exact for the bot's 416 same-day rows; past 48h the Weather row rises to 1.20/1.20/1.37, where the paper AGREES with b>1, so it does not contradict the 230 multi-day rows.

**Confidence:** high · **Vote:** 3-0, 2-1, 3-0 across three independent verifications of (a), merged with the corroboration claim

**Evidence.** All three verifiers downloaded the source themselves (curl of the 436KB LaTeXML HTML; pymupdf on the PDF) rather than trusting a summarizer — which mattered, since a first WebFetch pass wrongly reported the paper's balanced-panel caveat as 'not stated'. Headline sentence identical across all three extractions: 'Weather markets exhibit the opposite pattern at short horizons (slopes 0.69-0.97 within 48 hours), where prices are too extreme.' Sec 9.1 states it standalone: 'Weather markets are uniquely overconfident at short horizons, the only domain where prices are too extreme.' Header/row alignment was re-checked against the nine-bin definition in Sec 4.2, ruling out a column misread. Not a logistic-form artifact: the paper says the isotonic result shows the pattern is 'not an artifact of imposing a linear logit slope'. Robust across trade size (Weather Single 0.96, Small 0.94, Medium 0.91, Large 0.89) and across the v1-to-v2 revision (292M to 353M trades), where only one Weather cell moved (0.74 to 0.73). Sample not thin: 26,911 markets, 4.4M trades, 99.5% resolved; smallest Weather cell 472 trades against a 200-trade floor. The weather result is incidental to the paper's headline (political underconfidence), so it is not its cherry-picked finding. WEAKNESS every verifier flagged: unrefereed single-author preprint (Nam Anh Le, stat.AP, v2 4 Aug 2026); one verifier caught a search summarizer falsely calling it peer-reviewed.

**Sources.** <https://arxiv.org/html/2602.19520v2> · <https://arxiv.org/pdf/2602.19520> · <https://www.researchgate.net/publication/401133396_Decomposing_Crowd_Wisdom_Domain-Specific_Calibration_Dynamics_in_Prediction_Markets>

### B2. CHECK (b) CONFIRMED, WITH ONE FRAMING CORRECTION. Compression is a Politics phenomenon at the horizons the bot trades: Politics runs 1.34, 0.93, 1.32, 1.55, 1.48, 1.52, 1.83, 1.83, 1.73 (the quoted 0.93-1.83), replicating on Polymarket at mean 1.45; Sports is 0.90-1.10 across all six bins to 48h (Polymarket 1.06). Politics is also the only domain with a credible trade-size effect (Large 1.74 vs Single 1.19, delta +0.53, CI [0.29,0.75]). CORRECTION: do not say compression is 'not general' — beyond one month every domain compresses (Sports 1.74, Politics 1.73, Weather 1.37, Crypto 1.36). What is Politics-specific is PERSISTENT compression at nearly all horizons. DIRECTIONAL NOTE, not evidence: b=1.487 sits almost exactly on the Politics value (1.45-1.55) and far from the Weather value — what a spurious fit landing on the literature's most famous number would look like.

**Confidence:** high · **Vote:** 2-1

**Evidence.** Verifier extracted all nine Politics and Sports values from the LaTeXML tables; every one matches in order. Stylized Fact 2, verbatim: 'Political markets exhibit persistent underconfidence at nearly all horizons (slopes 0.93-1.83)... Sports markets are close to calibrated at short-to-medium horizons (slopes 0.90-1.10 from 0 to 48 hours).' Table 19 note: 'Political underconfidence replicates on Polymarket (mean 1.45); the two shortest bins are unreliable due to block-number timestamp noise.' Every non-Politics size delta is inside +/-0.07 with CIs crossing zero. The correction comes from Stylized Fact 1: 'At long time horizons, prices in every domain move toward the favorite-longshot pattern.' VERSION SENSITIVITY: v1 gave Polymarket Politics 1.31, v2 gives 1.45 after regenerating from a locked snapshot; the paper concedes its Polymarket trade-size estimate 'is smaller and sensitive to the unified data snapshot'. A verifier searched for contradicting sources and found none disputing the Politics result.

**Sources.** <https://arxiv.org/pdf/2602.19520> · <https://arxiv.org/html/2602.19520v2>

### B3. CHECK (c) — THE NUMBERS ARE VERIFIED BUT ALL THREE STANDALONE (c) CLAIMS WERE VOTED DOWN, SO CITE ONLY THE NARROW VERSION. Verified verbatim: the universal horizon component rises 'from 0.99 (0-1 hour) to 1.32 (beyond one month)', and Table 4's Weather row itself crosses 1.0 between 24-48h (0.97) and 2d-1w (1.20). DO NOT CITE the variance-decomposition shares — two mutually inconsistent versions were offered ('weighted 0.74 vs unweighted 0.30' and 'Table 9 share 0.193') and both parent claims were rejected 0-3. THE CONSEQUENCE IS A FREE TEST ON THE BOT'S OWN DATA: it pools 416 same-day rows (paper regime 0.69-0.97) with 230 multi-day rows (paper regime 1.20-1.37). Two populations the paper reports as opposite-signed are being fitted with one slope. Refitting b separately on the two subsets costs nothing and would show whether the multi-day rows carry the entire pooled 1.487.

**Confidence:** medium · **Vote:** standalone (c) claims rejected 0-3, 0-3, 0-3 and one 1-2; the figures survive only as verbatim extracts inside the accepted verifications of (a) and (b)

**Evidence.** The 0.99-to-1.32 string was extracted verbatim by the verifier of check (b) from Stylized Fact 1 while checking a different claim — it was not the proposition being defended, which is why it is trustworthy despite the (c) claims failing. The long-horizon Weather values were independently extracted by three verifiers, and the paper states 'At longer horizons... weather markets converge to the universal underconfidence pattern.' The paper discretizes horizon into nine bins precisely because slope is not constant across them. WHY THE STANDALONE CLAIMS FAILED: they went past the extracted numbers into a variance decomposition reported incompatibly across versions, and into an assertion that pooling had MANUFACTURED the bot's b>1 — plausible, but never tested against the bot's actual data by anyone in this pass. Label that mechanism PLAUSIBLE BUT UNTESTED; the horizon-split refit is how to test it.

**Sources.** <https://arxiv.org/html/2602.19520v2> · <https://arxiv.org/pdf/2602.19520>

### B4. THE STRONGEST RECONCILIATION: THE PAPER'S 'WEATHER' DOMAIN IS NOT THE BOT'S CONTRACT FAMILY, AND FOUR OTHER STRUCTURAL DIFFERENCES COMPOUND IT. The paper's own published classifier puts into Weather not just daily city high-temperature ladders but HMONTH (monthly), RAINNYC and SNOWNYM (precipitation), TORNADO, HURCAT and ARCTICICE — 19 patterns. Any Weather slope on this dataset is a mixture over families with different horizons, base rates and forecast technologies. Two sharper details: there is no LOW/LOWT/MIN pattern anywhere in the 509-entry table and unmatched tickers are 'classified as Other and excluded', so the bot's KXLOWT ladders are largely absent from the domain check (a) rests on; and KXLOWTAUS is misrouted to Sports/Tennis because 'WTA' is a substring. COMPOUNDING DIFFERENCES, all verbatim: cutoff 31 December 2025, which predates the bot's summer fit window entirely (not a same-period disagreement); the unit is an individual quantity-weighted TRADE, not one snapshot per settled market; the price filter is 5-95 cents versus the bot's narrow 0.74-0.86 band; and the paper 'requires at least 200 trades per analysis cell' — the first half of check (d) — while the bot's b rests on ~538 rows found in-sample after two hypotheses had already failed.

**Confidence:** medium · **Vote:** 2-1 on the mixture mechanism; 1-2 on the narrower KXLOWT-excluded point (treat as suggestive); structural differences confirmed inside the 3-0 verification of (a)

**Evidence.** The verifier fetched the dataset repo's categories.py (19 Weather tuples, lines 439-457) and then — decisively — the PAPER'S OWN code repo, named in its Data Availability statement, finding src/classify.py carries all 19 identical tuples and domain_classification_rules.md stating 'Weather | HIGHNY, RAINNYC, SNOW, TORNADO, HURCAT, ARCTICICE, WEATHER' with 'case-insensitive substring matching'. So the mixture is the paper's classifier, not an inference. Paper body corroborates: 'Weather (temperature records, precipitation, natural events).' A live Kalshi API check (360 Climate-and-Weather series) run through the paper's own get_hierarchy() put 134 in Weather, split by Kalshi's frequency field as daily 64, custom 29, monthly 28, one_off 9, annual 2, hourly 1, weekly 1 — about half non-daily by series count; the HOURLY KXHIGHNYD series also matches 'HIGHNY' and is pooled with the daily ladder. THE MECHANISM IS DEMONSTRATED BY THE PAPER'S OWN SUPPLEMENT: its Simpson's-paradox appendix shows Politics subcategory slopes in one bin spanning -0.14 to +7.22, with the leave-one-out domain aggregate moving from 0.6886 to 1.1829 — across 1.0 — depending which subcategory is dropped. There is NO Weather decomposition anywhere in the supplement, so the paper never tested Weather for the heterogeneity it documented in Politics. LIMIT the verifier acknowledged: series counts are not trade counts (Weather carries 4.4M trades), so the mixture is proven to exist but not proven large enough to flip the sign. SECOND HALF OF CHECK (d) — the ~45.6% structural-variance figure — was asserted only from the abstract page and rejected 0-3; do not cite.

**Sources.** <https://github.com/jon-becker/prediction-market-analysis> · <https://github.com/namanhzz/prediction-market-calibration> · <https://arxiv.org/html/2602.19520v2>

### B5. TIME-CRITICAL, MISSED BY BOTH RESEARCH PASSES: KALSHI MOVED DAILY TEMPERATURE SETTLEMENT FROM THE NWS TO THE WEATHER COMPANY, EFFECTIVE 14 AUGUST 2026 — two weeks ago. The live rules text for the current daily NYC market reads: 'If the maximum temperature recorded at New York City (CLINYC) for Aug 29, 2026, is greater than 86 degrees fahrenheit according to The Weather Company, then the market resolves to Yes.' Series metadata lists settlement_sources as The Weather Company (weather.com/kalshi). The station LABEL is unchanged (CLINYC = Central Park) and TWC 'utilizes NWS as its primary underlying source', but the official and final AUTHORITY is now a commercial vendor, and Kalshi warns 'Preliminary Weather Company data may be subject to rounding and conversion differences from the final reported value.' CONSEQUENCE: Kalshi's help-center weather article, last updated 22 July 2026, predates this and still names the final NWS Daily Climate Report. Three of the four settlement findings here rest on that page and are documented only against a superseded process.

**Confidence:** high · **Vote:** verified live by me today against two primary Kalshi endpoints; supersedes part of the 2-1 two-settlement-authorities claim

**Evidence.** I fetched the Kalshi public API on 2026-08-29 because two confirmed claims disagreed about the daily settlement source. Market KXHIGHNY-26AUG29-T86 rules_primary and rules_secondary quoted above are verbatim from that response; rules_secondary also states 'the official and final value used to determine this market is the maximum/minimum temperature as reported by the Weather Company'. Series KXHIGHNY (frequency 'daily', category 'Climate and Weather') returns the transition text 'daily temperature markets will transition their settlement source from the National Weather Service (NWS) to The Weather Company', effective Friday August 14th. I re-fetched the help page in the same call: it still reads 'These markets settle the next morning based on the high temperature recorded in the final NWS Daily Climate Report', dated July 22, 2026. The linked contract terms PDF (created 12 Dec 2025) is a generic appendix with no settlement source, station or measurement-window text, so it does not resolve the question. A verifier of a separate claim had checked the 27 Aug 2026 Kalshi/Weather Company partnership announcements and concluded 'Neither says TWC replaces NWS' — correct as to the press coverage, but the contract text itself does say so.

**Sources.** <https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXHIGHNY> · <https://api.elections.kalshi.com/trade-api/v2/series/KXHIGHNY> · <https://help.kalshi.com/en/articles/13823837-weather-markets>

### B6. THE BOT'S METAR LOCK IS A PROXY FOR THE SETTLEMENT VALUE, NOT THE SETTLEMENT VALUE — AND THE MIGRATION MAKES THAT MORE TRUE. Kalshi daily temperature markets never settled on METAR/ASOS: under the prior regime they settled on the final NWS Daily Climate Report (CLI) released the following morning, and Kalshi documented two divergence modes — 'Market determination may be delayed in the rare instances of a) a high temperature is not consistent with 6-hr or 24-hr highs reported by METAR or b) the final NWS Climate Report high temperature value is lower than previous preliminary report.' Kalshi would have no reason to write a METAR-inconsistency clause if the numbers were the same. The NWS corroborates the mechanism: the CLI is built from the ASOS Daily Summary Message and quality-controlled, and ASOS records continuously even when not transmitting, so a one-minute spike can set the daily extreme without appearing in any disseminated METAR. Under the new regime the lock proxies a commercial vendor's value whose preliminary readings Kalshi warns may differ from final. This is a CORRECTION to an already-built component, not a new build.

**Confidence:** high · **Vote:** 3-0 and 3-0 on the two underlying claims; scope now narrowed by the settlement migration

**Evidence.** Both underlying claims verified 3-0 against the primary help page, the delay clause confirmed word-for-word by an independent fetch that returned surrounding text the claim had not quoted (ruling out summarizer echo). The parallel low-temperature wording covers KXLOWT: 'settle the next morning based on the low temperature recorded in the final NWS Daily Climate Report'. NWS Chicago FAQ, verbatim: 'NWS meteorologists will address any bad data included in these [Daily Summary Messages] when generating and quality controlling our CLI products prior to disseminating them', plus an F-to-C-to-F round trip that 'may differ... by 1 or 2 degrees', and CLI is 'subject to revision'. Iowa Environmental Mesonet's 'Wagering on ASOS Temperatures' confirms DSM, METAR 6-hour max/min, and CLI/CF6 are three distinct products that can disagree. A verifier searched for any source claiming these markets settle directly on METAR and found none. HONEST LIMIT: Kalshi calls these 'rare instances' and clause (a) names no direction, so the failure RATE is undocumented — 'residual basis risk' is the correct strength; 'METAR locks are often wrong' would not be supported. A secondary source argues the more common discrepancy runs the other way (CLI higher than displayed hourly METARs, catching sub-hourly spikes). POST-MIGRATION STATUS OF BOTH CLAUSES IS UNVERIFIED — they describe an NWS process that no longer determines these markets.

**Sources.** <https://help.kalshi.com/en/articles/13823837-weather-markets> · <https://www.weather.gov/lot/weather_observations_faq> · <https://mesonet.agron.iastate.edu/onsite/news.phtml?id=1469>

### B7. THE NWS CLIMATE DAY RUNS ON LOCAL STANDARD TIME, SO DURING DST THE WINDOW IS 1:00 AM TO 12:59 AM LOCAL CLOCK — one hour off the calendar day for about eight months a year. Any METAR-window lock or same-day feature keyed to local midnight wrongly INCLUDES 00:00-00:59 (belonging to the prior climate day) and wrongly EXCLUDES 00:00-00:59 of the next calendar day (belonging to this one). TWO CORRECTIONS to the original framing: it is a one-hour boundary offset, not 'the wrong 24 hours' — the windows overlap 23 of 24 hours and on most days the shift is a no-op since maxima occur mid-afternoon; and it must be applied PER CITY, because Phoenix and Honolulu never observe DST and have zero offset year-round, so a blanket +1h rule would introduce the very error it is meant to fix — and Phoenix is in the KXHIGH city set. Exposure is asymmetric and worst for a LOCK, which is treated as certainty rather than probability: a warm-advection night at 78F followed by a cloudy 74F day makes a local-midnight accumulator lock a floor the settled max never reaches. KXLOWT is more exposed than KXHIGH, since minima sit nearer the boundary hours.

**Confidence:** medium · **Vote:** 3-0 on the fact as documented; downgraded here because its premise clause names the NWS Climate Report, which no longer determines daily markets

**Evidence.** Kalshi help page, verbatim (returned with more surrounding text than was quoted, ruling out echo): 'The NWS Climate Reports (used for daily temperature markets) use local standard time when reporting daily high temperatures. This means that during Daylight Saving Time, the high temperature will be recorded between 1:00 AM and 12:59 AM local time the following day - not based on the standard midnight-to-midnight range.' INDEPENDENTLY CORROBORATED AT THE NWS END, which is what makes it durable: the verifier pulled the live NYC CLI product (issued 221 AM EDT Sat Aug 29 2026), whose footnote defines LST as local standard time and whose extremes are stamped in LST — 'MAXIMUM 84 109 PM', i.e. 1:09 PM LST = 2:09 PM clock time during EDT. So the LST climate day is real NWS practice, not merely a Kalshi assertion. DST arithmetic: 2nd Sunday March to 1st Sunday November is about 238 days, so 'roughly eight months' holds only for DST-observing cities. WHY ONLY MEDIUM NOW: the help page ties the LST window to 'The NWS Climate Reports (used for daily temperature markets)' — and that premise is exactly what changed on 14 August 2026. Whether The Weather Company's value uses the same LST climate day is undocumented and unverified. The underlying observations are probably still the same NWS/ASOS stream, so the window plausibly carries through, but that is an inference, not a citation.

**Sources.** <https://help.kalshi.com/en/articles/13823837-weather-markets> · <https://forecast.weather.gov/product.php?site=OKX&product=CLI&issuedby=NYC>

### B8. CROSS-VENUE WEATHER ARBITRAGE IS LARGELY NOT ARBITRAGE: KALSHI AND POLYMARKET SETTLE 'THE SAME' NYC DAILY-HIGH MARKET ON DIFFERENT STATIONS AND DIFFERENT VENDORS. Kalshi resolves on New York City (CLINYC), the Central Park station, as reported by The Weather Company; Polymarket resolves on 'the highest temperature recorded at the LaGuardia Airport Station' using Wunderground data for KLGA. Different station AND different vendor, so a price gap is partly or wholly a real difference in the underlying random variable, not a mispricing. Material because Kalshi ladder buckets are 1-3 degrees F wide and Central Park's vegetation damps summer afternoon highs relative to the airports. THE MAGNITUDE IS UNMEASURED ANYWHERE: the academic source raises it as a worked illustration with no weather empirics, and no published distribution of KNYC-versus-KLGA daily-high differences or measured cross-venue basis could be found. Anyone trading this would have to measure the station basis from historical records first, before any price gap could be interpreted.

**Confidence:** high · **Vote:** 3-0

**Evidence.** arXiv 2601.01706v1 (Gebele & Matthes, TUM, 5 Jan 2026, 'Semantic Non-Fungibility and Violations of the Law of One Price in Prediction Markets'), Sec 2.3, verbatim: 'Kalshi's market Highest temperature in NYC? resolves using data from NOAA's Central Park weather station, whereas the corresponding market on Polymarket references measurements from LaGuardia Airport. These locations frequently record different temperatures... markets that appear nearly equivalent at the textual level encode distinct resolution semantics and correspond to meaningfully different contingent claims.' CRUCIALLY the verifier did not rest on the preprint: it re-derived the fact from both venues' live rules — Kalshi's rules_primary naming CLINYC, and two separately dated Polymarket markets (28 Jul and 18 Aug 2026) reading 'the highest temperature recorded at the LaGuardia Airport Station... The resolution source for this market will be information from Wunderground'. Two independent reads found exactly one weather passage and zero weather empirics in the paper; its quantitative content is domain-agnostic (102,275 events, 10 platforms, 2018-2025; 1,501 equivalence classes; 2-4% median execution-aware deviations — pooled across categories, dominated by the 2024 election case study, NOT a weather number, and a claim asserting it was voted down 1-2). The paper's phrase 'NOAA's Central Park' is now imprecise given the TWC migration, which STRENGTHENS the point: the contracts now differ on two axes. Caution the verifier raised: on days when both stations certainly land in the same bucket the basis is zero and a gap could be genuine, so 'partly or wholly' is the defensible phrasing.

**Sources.** <https://arxiv.org/html/2601.01706v1> · <https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXHIGHNY> · <https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA>

### B9. NO VERIFIED SOURCE CURRENTLY SUPPORTS THE BOT'S DIRECTION FOR WEATHER — the counter-evidence that would have rescued b=1.487 was searched for and failed verification. Three claims from Whelan's 'Makers and Takers: The Economics of the Kalshi Prediction Market' pointed the bot's way and were all voted down: that Kalshi's Climate & Weather category shows a Mincer-Zarnowitz price coefficient of +0.031 implying underpriced favourites (1-2); that contracts above 70 cents earn statistically significant positive post-fee returns (0-3); and that the favourite strategy's risk-reward is +2.6% mean against 33% standard deviation, a per-trade Sharpe of about 0.08 (0-3). Whelan's general Kalshi finding — low-price contracts win far less often than break-even after fees while high-price contracts yield small positive returns — was noted as corroborating the broad favourite-longshot pattern, but it is an all-Kalshi result dominated by macro and political contracts, and the same note records that short-horizon weather moves the opposite way. A third-party Kalshi calibration site states it has no settled weather markets with a recorded pre-event price, 'not enough to say anything honest about how accurate this category is'. After two passes the evidence on Kalshi weather price calibration is one-sided against the bot.

**Confidence:** medium · **Vote:** 1-2, 0-3, 0-3 on the three pro-bot claims; a scoped absence claim about what two passes turned up, not proof no such evidence exists

**Evidence.** The Whelan claims failed for reasons visible in the record: the Mincer-Zarnowitz claim required assuming the regression's units were cents in order to convert +0.031 into a 1.031 slope, an inference two of three verifiers would not grant; the >70c post-fee-profitability and Sharpe claims were rejected outright. I report this as a finding rather than burying it because the consequence is decisive: the strategy's only external support in this research effort did not survive, so b=1.487 now stands alone against a primary source reading the other way. This does NOT mean the bot's finding is false — the mixture and horizon-split reconciliations remain live and are testable on the bot's own data. It means the burden of proof sits entirely on the bot's own forward evidence, with no citable prior in its favour.

**Sources.** <https://www.karlwhelan.com/Papers/Kalshi.pdf> · <https://arxiv.org/html/2602.19520v2>

## Appendix C — refuted claims: DO NOT CITE

These failed adversarial verification. Several are attractive and several would have been actionable, which is exactly why they are listed: without this section a future reader re-derives them and treats them as new. Vote is refuters-to-defenders.

### Pass 1 — 16 refuted

- **[1-2]** Isotonic regression is explicitly identified as prone to overfitting on small calibration sets, and the authors recommend parametric beta calibration as the substitute in that regime — directly contraindicating the project's 'not present in code, so genuinely new' isotonic option at n=50-600 total and 10-15 per city, while confirming the already-built beta calibration is the right family for that sample size. Minimum viable n is not stated numerically; the empirical support comes from 41 UCI datasets whose smallest members are ~96-215 instances, with the calibration map fitted on only one third of each training split.
- **[0-3]** The logistic (Platt) calibration family does not contain the identity map, so applying Platt-style calibration to scores that are already well calibrated actively degrades them; the beta family does contain the identity, at a=b=1, c=0, so it can learn a no-op. This is a falsifiable structural property of the two families, and it argues the project's existing Platt-style temperature scaling (fitted per condition_type) carries a downside the METAR-path beta calibration does not.
- **[0-3]** Across 798 (classifier, dataset) pairs on tabular binary classification, Venn-ABERS predictors gave the largest average log-loss reduction (-14.17%), with Beta calibration second (-13.7%) and Platt scaling third (-9.75%); Beta improved log-loss most FREQUENTLY (67.1% of instances) vs Venn-ABERS 63.2% and Platt 49.8%. The authors' explicit recommendation is Beta and Venn-ABERS as the default starting points. This is direct evidence for adding Venn-ABERS (listed as NOT PRESENT IN CODE) and validates the already-built Beta calibration.
- **[0-3]** Isotonic regression and Platt scaling are identified as ACTIVELY HARMFUL for strong models: isotonic is expected to slightly INCREASE log-loss (i.e. negative expected value), and both are named as systematically degrading proper scoring performance. This is evidence AGAINST adding isotonic regression, which the project lists as a genuinely-new candidate, and a caution about the already-implemented single-parameter Platt-style temperature scaling.
- **[0-3]** Direct isotonic-regression calibration (the Zadrozny-Elkan / sklearn-style recipe of fitting PAVA on the same data used to train the scorer) has two documented failure modes: it overfits because the same observations serve both roles, and it emits probabilities of exactly 0 or 1. The latter is not a rare edge case — it occurred in EVERY dataset/classifier experiment in the paper, making the mean log loss infinite each time. Plain isotonic regression is the top 'genuinely new' candidate on this project's list; this is the specific way it breaks.
- **[0-3]** Sigmoid (Platt/logistic) calibration corrects UNDER-confidence but structurally cannot correct over-confidence, because the sigmoid family pushes probabilities away from 0.5 and cannot pull them toward the middle. This means a logistic-in-logit recalibration with slope b>1 is precisely the right functional family for compressed prices (the project's b=1.487 finding), and the method's one known directional failure mode is the opposite of the miscalibration the project measured.
- **[0-3]** Isotonic regression's stated advantages are conditioned on large datasets, and it has a concrete failure mode that is worst at small n: it drives the first and last bins to full confidence (exactly 0 and 1), which is degenerate under log-loss and requires ad-hoc epsilon clipping. The survey's own demonstration of isotonic calibration is run at 10,000 samples and still shows residual error attributed to sparse regions.
- **[0-3]** The standard, named remedy for fitting a calibration map on a small calibration set is multi-fold cross-validated calibrator fitting with prediction averaging (Platt 1999): split into folds, fit a separate model+calibrator pair per fold, and average all pairs' outputs at prediction time. This is the survey's prescribed out-of-sample validation/fitting protocol for small-n calibration, and it is the same scheme the authors say is used for beta calibration.
- **[0-3]** Binned calibration diagnostics are unusable at the project's sample sizes: the Hosmer-Lemeshow goodness-of-fit test for calibration only has satisfactory power above 400 instances, and binned ECE/MCE estimates are dominated by noise when bins hold few instances (a single-instance bin reports the raw 0/1 label as its empirical frequency) and change value with the arbitrary choice of bin count. The survey therefore advises pairing them with proper scoring rules, and points to a resampling-based calibration hypothesis test (Vaicenavicius et al. 2019) as the alternative.
- **[0-3]** The established rule-of-thumb floor for externally validating a binary-outcome prediction model is at least 100 events AND 100 non-events, rising to a minimum of 200 events and 200 non-events before a FLEXIBLE calibration curve can be derived. Applied to this bot: n=50-600 total settled binaries sits at or below the floor for even assessing global calibration, and the per-city cells of 10-15 are roughly an order of magnitude short of the 200/200 needed for any flexible curve — which is exactly what isotonic regression and spline calibration estimate. This is direct evidence AGAINST adding isotonic or spline calibration at current sample sizes.
- **[1-2]** Estimating calibration within sub-ranges of predicted probability (i.e. the shape of a calibration curve) requires strictly LARGER samples than estimating the global O/E ratio and the global calibration slope on the whole dataset. This establishes a data-hunger ordering — intercept/O-E shift < single-parameter slope < flexible curve — that argues for keeping recalibration parametric (a slope+intercept on logit(market)) rather than moving to isotonic/spline shapes, until sample size grows substantially.
- **[0-3]** The paper's precision benchmark for a calibration slope is SE(beta) = 0.051, giving a 95% CI of roughly 0.9 to 1.1 (width 0.2) when the estimate is 1. This is a directly checkable yardstick for the Part C finding: b = 1.487 at z = +3.03 vs 1 implies SE ~= 0.487/3.03 ~= 0.16, i.e. a 95% CI of roughly 1.17-1.80, about three times wider than Riley et al.'s 'precise' target. The compression effect's SIGN is well separated from 1, but its MAGNITUDE is not precisely estimated, so sizing off the point estimate 1.487 is unsupported by this precision standard.
- **[0-3]** Isotonic regression and histogram binning — the two distribution-free calibrators most likely to be reached for at n=50-600 — carry only ASYMPTOTIC calibration guarantees, not finite-sample ones. This is the paper's stated motivation, and it directly qualifies the 'add isotonic regression' option on the project's not-yet-implemented list: at these sample sizes isotonic has no theoretical validity backing it.
- **[0-3]** Venn / Venn-Abers calibration provides a FINITE-SAMPLE, distribution-free guarantee: applied to any in-sample-calibrated predictor it returns a set that provably contains at least one marginally calibrated point prediction at any n, with no asymptotic appeal. This is the specific property that makes Venn-ABERS defensible at n=50-600 where isotonic is not.
- **[0-3]** At small n the Venn prediction set WIDENS rather than silently emitting an overconfident number — the method self-diagnoses exactly the overfitting regime in which histogram binning and isotonic calibration become unreliable. Falsifiable prediction for this project: run at per-city n≈10-15 and the interval should be wide enough to be near-uninformative, which is itself the diagnostic answer about whether per-city calibration is estimable at all.
- **[0-3]** Plain isotonic regression used directly for calibration (the Zadrozny–Elkan / 'DIR' method) is empirically unsafe: it overfits when fitted on the same data that trained the scorer, and in EVERY dataset/classifier combination in this paper it emitted a prediction of exactly 0 or 1 on at least one test point, making mean log loss infinite. This is the specific failure mode of the isotonic option the bot is considering adding.

### Pass 2 — 15 refuted

- **[0-3]** (c) CONFIRMED, and this is directly actionable against the bot's current method. The universal horizon component rises monotonically from 0.99 at 0-1 hour to 1.32 beyond one month, a spread of 0.33 in slope driven by horizon alone. In the paper's variance decomposition the horizon effect DOMINATES all other structural components (weighted R2 contribution 0.74 vs 0.30 unweighted). Time-to-resolution is discretized into nine bins ([0,1h) through [1mo, inf)) precisely because the slope is not constant across them. Consequence for the bot: pooling 416 same-day rows with 230 multi-day rows into a single b=1.487 fit is exactly the aggregation this paper's design rules out — the pooled estimate is a mixture whose value depends on the horizon mix of the sample, not a transferable constant. Any price recalibration must be fitted per horizon bin. Note the bot's same-day population sits in the 0-1h to 24-48h region where the paper's universal component is ~0.99-1.0, i.e. near calibrated, before the negative weather-specific deviation is applied.
- **[0-3]** CLAIM (c) CONFIRMED, AND IT SUPPLIES THE MOST LIKELY RECONCILIATION. The slope is strongly horizon-dependent: the universal horizon component rises from 0.99 at 0-1 hour to 1.32 beyond one month, and horizon is the single largest structural variance component (Table 9: mu(tau) share 0.193, larger than domain at 0.084 or size at 0.068). Critically, the Weather row of Table 4 itself CROSSES 1.0 with horizon — 0.97 at 24-48h, then 1.20 (2d-1w), 1.20 (1w-1mo), 1.37 (1mo+). So weather is overconfident same-day and underconfident multi-day. The bot's pooled fit mixes 416 same-day rows (paper says slope ~0.7-0.9) with 230 multi-day rows (paper says ~1.20-1.37); pooling two populations with opposite-signed slopes can manufacture a spurious pooled b>1, especially if the multi-day rows sit at more extreme prices. This makes 'fit per horizon bin, never pooled' a requirement, not a refinement.
- **[0-3]** CLAIM (b) CONFIRMED, AND WEATHER IS ALREADY NEAR-CALIBRATED SO THERE IS LITTLE RECALIBRATION EDGE TO HARVEST. b>1 compression is a POLITICS phenomenon: Table 4 Politics row spans 0.93-1.83 (1.34, 0.93, 1.32, 1.55, 1.48, 1.52, 1.83, 1.83, 1.73) and the abstract states it replicates on Polymarket. Sports sits near calibrated at 0-48h (1.10, 0.96, 0.90, 1.01, 1.05, 1.08 — exactly the quoted 0.90-1.10 range). The nonparametric metrics agree: Table 6 ECE is 0.016 for Weather versus 0.117 for Politics, a ~7x gap, with Weather among the best-calibrated domains (only Sports 0.008 and Crypto 0.007 are lower). A domain with ECE 0.016 leaves very little mispricing for a price-only recalibration rule to extract, before fees.
- **[0-3]** The paper's headline compression finding is DOMAIN-SPECIFIC TO POLITICS, not weather. The abstract names political markets as the only domain that compresses toward 50%, calls it "the most robust pattern," and reports it replicates on Polymarket. The word "weather" does not appear anywhere in the abstract, title, or comments. This CONFIRMS check (b) at the primary source and means the bot's b=1.487 (prices compressed toward 0.5, favourites underpriced) cannot cite this paper as support: the paper's central thesis is that the sign of the recalibration slope is a property of the domain, and the domain it attributes compression to is not the bot's. The abstract page cannot confirm or refute check (a) — the specific weather slopes 0.69-0.97, the intercept -0.072 [-0.111, -0.034], and the ECE 0.016 vs 0.117 figures are NOT on this page and must be verified against the full HTML/PDF or the replication repo at https://github.com/namanhzz/prediction-market-calibration.
- **[0-3]** Check (d) is CONFIRMED in its second half at the primary source: the paper's Bayesian measurement-error model, propagating first-stage uncertainty under conservative event-clustered standard errors, attributes roughly half of raw across-cell slope variation to estimation noise. Directly applicable to the bot: a slope fitted on ~538 in-sample rows sits well inside the noise band this paper says dominates cell-level slope estimates even at 353M trades. The specific "structural variance 45.6% of total observed variance" figure and the "minimum 200 trades per analysis cell" threshold are NOT stated on the abstract page and remain unverified from this URL.
- **[1-2]** Check (c) is CONFIRMED in direction though not in magnitude: the paper's stated object of measurement is how calibration varies with time-to-resolution (and trade size), and its concluding sentence states calibration is conditional rather than a single pooled number. This is a primary-source basis for the instruction that a price-recalibration slope must be fitted per horizon bin — the bot's current pooling of 416 same-day and 230 multi-day rows into one fit is contrary to the paper's own framing. The specific horizon component values (0.99 at 0-1 hour rising to 1.32 beyond one month) are NOT on the abstract page.
- **[1-2]** This repository is the shared data substrate for the very literature the research question is trying to verify: its README's "Research & Citations" section lists Le's "Decomposing Crowd Wisdom" (the paper whose Weather slope of 0.69-0.97 must be checked) alongside Cao's "Retail-Adjusted Expected Value in Prediction Markets: Calibration, Longshot Bias, and Consumer Welfare" and Bartlett & O'Hara's "Adverse Selection in Prediction Markets: Evidence from Kalshi". The paper's Kalshi data is therefore third-party scraped API data, not exchange-supplied records, and two further directly on-point papers exist on the same substrate.
- **[1-2]** The 339-entry pattern table contains no entry matching "LOW", "LOWT" or "TEMP", and unmatched tickers fall through to a default group of "Other". Under this utility, Kalshi daily LOW-temperature ladders (KXLOWT*) are not classified as Weather at all — meaning roughly half of the bot's own contract population is outside the domain cell whose slope claim (a) rests on.
- **[0-3]** THE RECONCILIATION IS HORIZON MIX, AND IT IS IN THE PAPER'S OWN WEATHER ROW. Weather slopes reverse sign relative to 1.0 as horizon lengthens: the Table 4 Weather row runs 0.69 / 0.84 / 0.73 / 0.87 / 0.91 / 0.97 for bins under 48h, then 1.20 (2d-1w), 1.20 (1w-1mo), 1.37 (1mo+). So within the SAME domain the paper finds overconfidence same-day and compression multi-day. A bot pooling 416 same-day rows with 230 multi-day rows is fitting one slope across two regimes of opposite sign, which is a concrete mechanism by which a pooled b of 1.487 could arise without any same-day edge existing. This also confirms CHECK (c): the universal horizon component rises monotonically from 0.99 at 0-1 hour to 1.32 beyond one month, so recalibration must be fitted per horizon bin, never pooled.
- **[0-3]** CHECK (b) IS CONFIRMED FOR SPORTS AND SUBSTANTIALLY CONFIRMED FOR POLITICS, WITH ONE NUMBER I COULD NOT REPRODUCE. Compression toward 0.5 is the POLITICS phenomenon — the paper calls persistent political underconfidence its most robust pattern and says it replicates on Polymarket — and Sports sits near calibrated at 0.90-1.10 from 0 to 48 hours, exactly as quoted. PRECISE DIFFERENCE: the first pass's Politics range of 0.93-1.83 did not reproduce at the 0-48h window; the Politics values I retrieved from Table 4 in that window are 1.34, 0.93, 1.32, 1.55, 1.48, topping out at 1.55, so 1.83 is either a longer-horizon Politics cell or a size-conditioned cell, not a 0-48h slope. Treat 0.93-1.55 as the verified 0-48h Politics range.
- **[0-3]** The repo documents four Kalshi-weather signal/management mechanisms that are NOT on the owner's already-built list: (i) NLP-style change detection over NWS Area Forecast Discussion narrative text, (ii) a freshness check on NWS/GFS model-update timing, (iii) automatic re-evaluation of resting orders for edge degradation, and (iv) forecast-drift analysis driving early exit of open positions. These are concrete, implementable additions to the bot's signal set — AFD change detection in particular consumes a data source (the forecaster's written discussion) that the bot's ensemble/METAR/bias-correction stack does not touch.
- **[1-2]** Kalshi's Climate & Weather category shows favourite-longshot bias in the SAME direction as the bot's b=1.487 finding (prices compressed toward 0.5, favourites underpriced), not the opposite. Mincer-Zarnowitz regression Y-P = a + b*P on 29,924 Climate & Weather price observations (Table 8, col. 3) gives a price coefficient of +0.031 (SE 0.005, p<0.01) with intercept -0.997 (SE 0.243), F-test p=0.000. Positive slope plus negative intercept means win rates fall below price at low prices and rise above price at high prices. Units are cents (internally consistent with the paper's own 5c and 95c worked examples), so this implies E[Y] = -1.0 + 1.031*P: an 80c weather favourite wins about 81.5% of the time, roughly +1.5c of pre-fee edge. This REFUTES arXiv 2602.19520's claim (a) that weather contracts show slopes BELOW 1, at least for Kalshi over 2021-April 2025; the magnitude (1.031 on the linear/cents scale) is far milder than the bot's logit b=1.487, so the bot's in-sample effect size is probably inflated even though its sign is corroborated.
- **[0-3]** Contracts priced above 70c -- the bot's exact band (0.74-0.86) -- earned statistically significant positive returns AFTER fees on Kalshi, measured across 313,972 Yes and No contract observations with Taker fees imputed (Figure 5). Small positive post-fee returns begin above 50c and reach statistical significance above 70c. Average loss rates for contracts at 10c and under exceed 60%. This is independent, out-of-sample-for-the-bot support that the favourite side is the tradeable side of the effect after fees, on this venue.
- **[0-3]** The realistic risk-reward of the favourite strategy is a mean of +2.6% against a 33% standard deviation of per-contract returns (Makers buying contracts costing 50c and over), i.e. a per-trade Sharpe of about 0.08. The paper cites this variance as one of three reasons the bias has not been arbitraged away. Applied to the bot: ~646 settled markets gives an expected t-statistic of only sqrt(646)*0.08 = 2.0 even if the edge is entirely real, so the bot's in-sample z=+3.03 is larger than a correctly-specified sample of that size should typically produce -- a quantitative reason to suspect its fitted effect is partly noise. It also implies forward validation needs several hundred independent observations before the rule can be sized.
- **[1-2]** Across ten venues and 102,275 events (2018 to Aug 2025), semantically equivalent cross-platform markets sit 2-4% away from execution-adjusted parity on median even among the most liquid pairs, and the authors attribute this to structural frictions rather than informational disagreement. CAVEAT the parent should carry: the paper does not state whether '2-4%' is percentage points of price or a relative percentage, and this figure is pooled across all categories (dominated by the 2024 election case study) — it is NOT a weather-market figure. 'Execution-adjusted' is defined as netting out bid-ask spreads, platform fees, gas costs, tick-size constraints and slippage.

## Appendix D — every source fetched

| Source | Quality | Claims | Pass |
| --- | --- | ---: | --- |
| <https://proceedings.mlr.press/v54/kull17a.html> | primary | 5 | pass 1 |
| <https://www.cs.cornell.edu/~alexn/papers/calibration.icml05.crc.rev3.pdf> | primary | 5 | pass 1 |
| <https://arxiv.org/pdf/2601.19944> | primary | 5 | pass 1 |
| <https://arxiv.org/abs/1211.0025> | primary | 5 | pass 1 |
| <https://arxiv.org/pdf/2112.10327> | primary | 5 | pass 1 |
| <https://onlinelibrary.wiley.com/doi/full/10.1002/sim.9025> | primary | 5 | pass 1 |
| <https://arxiv.org/abs/2502.05676> | primary | 5 | pass 1 |
| <https://arxiv.org/pdf/1211.0025> | primary | 5 | pass 1 |
| <https://arxiv.org/abs/1511.00213> | primary | 5 | pass 1 |
| <https://arxiv.org/html/2606.19642> | primary | 5 | pass 1 |
| <https://academic.oup.com/jrsssb/article/83/5/963/7056107> | primary | 5 | pass 1 |
| <https://npg.copernicus.org/articles/27/23/2020/> | primary | 5 | pass 1 |
| <https://arxiv.org/abs/1805.09091> | primary | 5 | pass 1 |
| <https://rmets.onlinelibrary.wiley.com/doi/10.1002/qj.4844> | primary | 5 | pass 1 |
| <https://www.northlakelabs.com/max/blog/kalshi-weather-postmortem-and-pivot/> | blog | 5 | pass 1, pass 2 |
| <https://github.com/suislanchez/polymarket-kalshi-weather-bot> | blog | 5 | pass 1 |
| <https://github.com/ImMike/polymarket-arbitrage> | blog | 5 | pass 1 |
| <https://arxiv.org/html/2602.19520v2> | primary | 5 | pass 1, pass 2 |
| <https://www.karlwhelan.com/Papers/Kalshi.pdf> | primary | 5 | pass 1, pass 2 |
| <https://datagolf.com/fav-longshot-not-a-bias> | blog | 5 | pass 1, pass 2 |
| <https://www.karlwhelan.com/Papers/PredictionMarkets.pdf> | primary | 5 | pass 1 |
| <https://arxiv.org/abs/2103.08402> | primary | 5 | pass 1 |
| <https://www.cmegroup.com/content/dam/cmegroup/education/files/backtesting.pdf> | primary | 5 | pass 1 |
| <https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf> | primary | 5 | pass 1, pass 2 |
| <https://sites.stat.columbia.edu/gelman/research/unpublished/p_hacking.pdf> | primary | 5 | pass 1, pass 2 |
| <https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf> | primary | 5 | pass 1 |
| <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=685361> | primary | 5 | pass 1 |
| <https://arxiv.org/pdf/2602.19520> | primary | 5 | pass 2 |
| <https://arxiv.org/abs/2602.19520> | primary | 5 | pass 2 |
| <https://github.com/jon-becker/prediction-market-analysis> | primary | 5 | pass 2 |
| <https://www.alphaxiv.org/abs/2602.19520> | secondary | 5 | pass 2 |
| <https://www.researchgate.net/publication/401133396_Decomposing_Crowd_Wisdom_Domain-Specific_Calibration_Dynamics_in_Prediction_Markets> | primary | 5 | pass 2 |
| <https://github.com/alexandermazza/kalshi-trading-mcp> | primary | 5 | pass 2 |
| <https://github.com/Stewyboy1990/weatheredge-bot> | unreliable | 5 | pass 2 |
| <https://news.ycombinator.com/item?id=43073377> | forum | 5 | pass 2 |
| <https://github.com/EddieTGH/kalshi-weather-predictor> | blog | 5 | pass 2 |
| <https://wethr.net/market-resolution> | blog | 5 | pass 2 |
| <https://arxiv.org/html/2601.01706v1> | primary | 5 | pass 2 |
| <https://help.kalshi.com/en/articles/13823837-weather-markets> | primary | 5 | pass 2 |
| <https://www2.gwu.edu/~forcpgm/2026-001.pdf> | primary | 5 | pass 2 |
| <https://www.nber.org/papers/w15923> | primary | 5 | pass 2 |
| <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2345489> | secondary | 5 | pass 2 |
| <https://engineering.atspotify.com/2023/03/choosing-sequential-testing-framework-comparisons-and-discussions/> | blog | 5 | pass 2 |
| <https://arxiv.org/pdf/2606.01650> | primary | 5 | pass 2 |
| <https://arxiv.org/abs/physics/0410039> | primary | 5 | pass 2 |
| <https://improver-gavinevans.readthedocs.io/en/latest/improver.calibration.ensemble_calibration.html> | primary | 5 | pass 2 |
| <https://en.wikipedia.org/wiki/Nonhomogeneous_gaussian_regression> | secondary | 5 | pass 2 |
| <https://ams.confex.com/ams/104ANNUAL/webprogram/Paper429496.html> | primary | 5 | pass 2 |

## Appendix E — run metadata

| | Pass 1 | Pass 2 |
| --- | ---: | ---: |
| Agents | 110 | 110 |
| Search angles | 6 | 6 |
| Sources fetched | 27 | 27 |
| Claims extracted | 135 | 135 |
| Claims verified | 25 | 25 |
| Confirmed | 9 | 10 |
| Refuted | 16 | 15 |
| Dropped to budget | 7 | 8 |
| Findings after synthesis | 7 | 9 |

Pass 1 scope: calibration technique. Pass 2 scope: comparable systems and the favourite-longshot question, launched because pass 1 spent its whole verification budget on calibration and left those unanswered.

Raw per-agent returns, including claims dropped before verification, are in each run's `journal.jsonl` under the session's `subagents/workflows/` directory. Those are unverified by construction and must not be cited as findings.
