# Where is the edge, if anywhere — and what would end this project

You are picking up a Kalshi weather-market trading bot (`C:\Users\thesa\claude kalshi`,
repo `livingtable-ctrl/weather1`) that has run for months and has **not found an edge**.
Your job is not to keep it alive. It is to run the few measurements that would either
locate a real edge or establish there isn't one, and then say plainly which happened.

**This is a research task, not an implementation task.** Use the web as well as the repo —
the single most important open question below turns on published work about prediction-market
calibration, not on anything in this codebase. Read `backlog.txt` (top entries first) and
`MEMORY.md` before doing anything.

## How to work this

**Use the `deep-research` skill for the literature question in task 1.** It fans out parallel
searches, fetches sources, adversarially verifies each claim, and returns a cited report.
That is the right shape for "is the favourite-longshot bias real and exploitable after
costs in a market like this one", which is the question the whole brief turns on.

**Use the `unlazy` skill before any code change or any conclusion you intend to publish.**
Write the gates first, make the riskiest outcome runnable, and mutation-test your own
oracle. This repo has shipped vacuous gates before -- a checker that embedded the number it
was meant to prove -- and the session that wrote this brief hit the same class of bug twice
in its own audit tooling.

**Three searches were already run; treat them as a starting point, not a result.** Verify
them independently and go further:

1. The favourite-longshot bias and whether it survives transaction costs in binary
   event markets. What was found: b>1 means the market is underconfident (prices compressed
   toward 50c); the effect is generally judged "efficient within transaction costs"; it is
   reported most exploitable near $0.05-0.15 and $0.75-0.92. **Confirm or refute this from
   primary sources -- the summary above came from secondary web results, not papers.**
2. Kalshi's fee schedule. What was found: taker `0.07 x C x P x (1-P)`, maker
   `M x 0.0175 x C x P x (1-P)` with the series multiplier `M = 0` for weather. This matches
   the repo. **Re-check it -- if `M` ever becomes non-zero for weather series, the maker-only
   thesis in this brief dies immediately.** `cron._check_fee_change` monitors it daily.
3. Kalshi weather-market calibration at scale. What was found: independent reporting claims
   these markets are well calibrated across ~70,000-73,000 resolved daily markets, a 70c
   contract resolving yes ~70% of the time. **This is the single most load-bearing external
   claim in the brief** -- it is what makes task 1's selection test necessary. It came from
   a secondary source. Find the primary data or a better source before relying on it.

Worth searching that nobody has: whether anyone has published on **execution** in binary
event markets specifically -- whether a resting maker-only strategy can actually capture a
calibration edge that a taker cannot, and what fill rates that implies. That is the exact
mechanism this brief proposes, and it is the part with no evidence behind it.

**Verification discipline, non-negotiable.** Every number in this document was measured on
2026-09-09 and several move. Three oracles in `.unlazy/` bind them to the live corpus and
will tell you immediately if the document has drifted:

    python .unlazy/verify_prompt_numbers.py docs/HANDOFF-where-is-the-edge-2026-09-09.md
    python .unlazy/verify_prompt_structure.py --selftest docs/HANDOFF-where-is-the-edge-2026-09-09.md
    python .unlazy/mutate_prompt_oracle.py docs/HANDOFF-where-is-the-edge-2026-09-09.md

Run the first one before you start. If it fails, the corpus has moved and the failing
figure is named -- re-derive it and correct this document rather than working around it.

## How to treat the numbers in this document

Every figure here was measured from source on **2026-09-09**. The corpus is live and
several of these move. **Re-derive any number you intend to rely on** — do not quote this
document as a source. Where a figure is closed and will not move, it says so.

Open the live DB **read-only**: `sqlite3.connect("file:" + path + "?mode=ro", uri=True)`.
Importing `tracker` runs `init_db()` and **writes**. `data/` resolves to the **main clone**
even from a worktree.

## The single most important fact

**Every dollar this bot ever made came from a bug, and the bug was correctly fixed.**

P&L by (condition_type, method) over settled paper trades:

| condition | method | n | P&L | win% |
|---|---|---|---|---|
| `above` | `metar_lockout` | 17 | **+282.81** | 82.4% |
| `below` | `metar_lockout` | 3 | +21.00 | 66.7% |
| `below` | `ensemble` | 53 | +15.97 | 35.8% |
| `between` | `ensemble` | 40 | −100.75 | 42.5% |
| `above` | `ensemble` | 77 | −101.20 | 39.0% |
| `between` | `metar_lockout` | 69 | **−184.45** | 63.8% |

The +$282.81 looks like the crown jewel. It is not. **All 17 of those trades fall between
2026-06-05 and 2026-06-21 — every one before commit `e395392b` (2026-06-25), which added
the guard requiring the METAR observation's local date to equal `target_date`. Post-guard:
zero trades, $0.** Before that guard, 62 of 88 locks came from 00–02h UTC scans — 20:00–22:00
the *previous* local evening, when the target climate day had not started and the
observation could not legitimately settle anything. The "informational advantage" was
reading yesterday's weather.

The guard was correct and must not be relaxed, but **the margin is smaller than earlier
write-ups claim and you should not repeat their figures.** Re-derived 2026-09-09 over all
106 settled `metar_lockout` rows: the removed 00–02h UTC window scored **59.7% correct at
Brier 0.2974 (n=62)** — which reproduces exactly — while the *surviving* hours scored
**68.2% at Brier 0.2533 (n=44)**, not the 80.8% / 0.1562 the backlog records. The gap is
8.5 points, not 21. **And note the surviving window's Brier of 0.2533 is itself worse than
0.25**, i.e. worse than answering 0.5 to everything. The guard removed the worse half of a
bad distribution; it did not leave a good one behind.

**What remains after the fix:** two monotone-safety vetoes have closed the non-`between`
lock path, so the lock's only live surface is `between` — which lost **−$184.45 at a 63.8%
win rate** (high win rate, larger losses than wins: the signature of buying near-certainty)
and which the operator has since disabled (`BETWEEN_TRADING_ENABLED` unset). `metar_lock_shadow_log`
holds **143 evaluations with 3 locks (2.1%), and all 3 are `between`-bracket**. The
mechanism now fires only on the condition type that is switched off, and its profitable
history was an artifact.

## The rest of the position

- Realised paper loss: **archived era −$432.36 over 25 trades (closed, will not move)**;
  live era **−$13.88 over 269 settled as of 2026-09-09 (moves — re-derive it)**. Total
  ≈ **−$446.25**. Note the live figure has drifted from −$51.99 to −$13.88 in a week as
  trades settled; any narrative built on a single snapshot of it is fragile.
- **No Brier skill versus the market.** The model does not beat the price it trades against.
- `ensemble` is **retired** (Brier 0.2570 lifetime / 0.2711 rolling > 0.25; recent
  directional accuracy 30% over the last 20 multi-day trades, trending down from 51%
  lifetime). Independently reproduced on the correctly-filtered population. **Do not
  un-retire it** — `unretire_strategy` also installs a 72-hour pin suppressing
  re-retirement. It recovers only via probation: 15 settled rows needed, ~4 held, at most
  one per UTC day and only when cron runs.
- The weekly parameter sweep reports in-sample win rates of 60–64% across every
  `PAPER_MIN_EDGE` value and a **holdout of 36.2%, exactly equal to baseline**. The
  parameter does nothing out of sample. Treat that ~27-point gap as this repo's house
  signature of overfitting.
- The bot currently places approximately nothing. That is the machinery working.

## Already refuted — do not re-derive these

1. **Not the forecast** — but **the "halved" figure does not reproduce; do not repeat it.**
   Earlier write-ups say July forecast error halved 2.68 → 1.18°F. Re-derived 2026-09-09
   over all settled core rows, mean |error| by month is **May 2.69, Jun 2.80, Jul 2.01,
   Aug 2.15** — a 28% fall in July that partly rebounded, not a halving, and 1.18 appears
   nowhere. The *direction* survives (July error fell and the daily-HIGH bias went to ~zero
   while probabilities got worse, so the problem is downstream of the forecast) but the
   magnitude was overstated. Re-derive before citing.
2. **Not weather/ENSO.** The bias is var-specific and time-varying in a way climate cannot
   be: daily-HIGH was −1.72°F in May–June then vanished (+0.29, −0.17) in July–August while
   daily-LOW stayed cold throughout. A regime moves both. Cause identified as a hand-coded
   correction table (`_STATION_BIAS_LOW`, since deleted) — see `weather_markets.py` ~line 811.
3. **Not fees.** Entries are resting midpoint GTC limit orders (maker) costing **$0**;
   `cost` reconciles to `quantity * entry_price` at mean, median and max. Applying
   `kalshi_taker_fee` invents ~$135 that was never charged and inverts conclusions. Kalshi's
   maker fee is `M × 0.0175 × C × P × (1−P)` with the series multiplier `M = 0` for weather;
   `cron._check_fee_change` asserts this daily and alerts if it ever changes.
4. **Not sigma.** Out-of-sample refits made Brier *worse* at all four cutoffs; fitted sigma
   lands at 2.76–3.01°F, essentially the shipped 3.0 cap.
5. **Not adverse selection on fills.** Permutation p=0.142 after correcting a coverage
   artifact. Resting fills are 96–100% realistic.
6. **Not the SPRT halt.** Real bug (the breaker computed its window from 49 monthly-rain
   rows and zero temperature rows), fixed in `8c89c104`, verified in production. Never the
   binding constraint.

## The structural finding that frames everything

`weather_markets.py` blends the model into the market price and then **discards whatever
still disagrees**. Pull toward the market, then throw away the disagreements. What survives
is where the model already agreed — exactly where there is nothing to win.

Two knobs, and they differ in how you can move them:

- `_MARKET_ANCHOR_BETWEEN` / `_ABOVE` / `_BELOW` (0.25 / 0.10 / 0.10) are
  **`os.getenv`-overridable** (`MARKET_ANCHOR_BETWEEN` etc., documented as "set to 0.0 to
  disable"). Unanchoring is a **config change**.
- `MAX_MODEL_MKT_GAP: float = 0.25` is a **hardcoded constant**. Widening it is a code edit.

The gate's stated justification (a comment claiming 74%/50%/**20%** win rates by gap bucket)
**does not reproduce**. Re-derived over the 342 settled core predictions it is roughly
61/54/**57**% — the load-bearing "model is anti-informative at large disagreement" claim
does not hold. Status is UNVERIFIED rather than refuted, because `our_prob` is stored
post-anchor so the buckets are compressed, and the pre-anchor gap is stored nowhere.
**Re-derive this yourself; n grows daily and the exact figures drift.**

## The research question that matters most

The option-5 price-recalibration rule **reads no weather forecast at all**. It fits
`y ~ a + b*logit(market_prob)` on settled markets and trades where the recalibrated
probability disagrees with the raw price. Discovery `b = 1.4871`, **z = +3.03 vs the null
b = 1**; frozen coefficients `a = −0.12856, b = +1.33635`, SE 0.10118, **z = +3.323**. It is
the only statistically significant result in the project, and it says the *market* is
miscalibrated — nothing about weather.

**b > 1 is the favorite–longshot bias.** It means the market is *underconfident*: prices
insufficiently extreme, compressed toward 50¢, favourites underpriced and longshots
overpriced. This is one of the most documented phenomena in betting and prediction markets.
Two things from the literature bear directly on whether it is worth anything here:

- The bias is generally judged **"efficient within transaction costs"** — it exists, but
  spreads and fees usually consume it. It is reported most exploitable roughly in the
  **$0.05–$0.15 and $0.75–$0.92** bands, and unexploitable at true extremes where liquidity
  dries up. The 14 logged picks have a mean executable price of **0.7243 (range 0.59–0.90)**
  and **6 of 14 fall inside those bands**. **This bot pays $0 maker fees and rests rather
  than crosses** — removing both cost terms the literature says kill the edge. That
  combination is the strongest remaining thesis in this project.
  *(An earlier draft cited 0.7487 from the backlog's projected pick set and called it "at
  the edge of the upper band"; the actually-logged picks measure 0.7243. Use the log.)*

**The rule is one-sided, and that is not a detail.** Re-derived from the frozen coefficients
on 2026-09-09: the negative intercept means that at a 0.50 market the rule already says
0.4679, and the YES/NO crossover sits at market_prob **0.5944**. With the frozen 0.05
threshold, **NO fires for market_prob up to 0.442 and YES never fires below 0.995.** All
**14 of 14 logged picks are NO**, which is structural rather than coincidental.

So the pre-registered forward test is **not a symmetric calibration test**. It is a
directional bet that the market overprices YES on low-probability contracts — i.e. a pure
**longshot fade**, which is the classic favourite–longshot trade. Two consequences the next
session must carry:

1. It can only ever detect miscalibration in one direction. A market that is *under*pricing
   longshots would produce zero picks and look like "no signal".
2. Fading longshots has a characteristic payoff shape: **many small wins and occasional
   large losses.** That is exactly the shape of `between` + `metar_lockout` in the table
   above — 63.8% win rate and −$184.45. **Before trusting a high win rate in the forward
   test, check the P&L shape, not the hit rate.** This project has already been fooled once
   by that pattern.
- **But:** independent reporting on Kalshi weather markets finds them *well calibrated at
  scale* — across roughly 70,000–73,000 resolved daily markets, a 70¢ contract resolves yes
  close to 70% of the time. **That is flatly inconsistent with b = 1.336 on a well-sampled
  population.** So the discovery is most likely a property of the *filtered subsample the
  bot sees* (gated by liquidity, spread, price band and its own scan cadence), not of the
  market.

**Your first task is to test exactly that**, and it is cheap: fit `b` on the widest
unfiltered settled population you can assemble, and separately on the bot's gate-passing
subsample. If `b → 1` unfiltered while staying >1 filtered, the "edge" is a selection
artifact of the bot's own gates and the pre-registration is measuring its own filter. If
`b > 1` survives unfiltered, you have located a real, documented, and possibly tradeable
inefficiency — and the maker-only execution is the reason it might survive costs.

This project has been bitten by exactly this class of error repeatedly (population
mismatch, survivorship, selection). Assume selection until you have ruled it out.

### The accrual problem

Current state: **14 picks logged, 10 settled, 4 distinct target days. The first
pre-registered look needs 1,100 settled picks.** At the current rate that is *years*.

Can the sample accrue faster without touching the registration? It logs ~4 picks per cycle
from ~68 analysed markets and already replays retired-method markets so the `ensemble`
retirement doesn't starve it. More cycles or a wider analysed population accrue faster — an
engineering change to cadence and scope, not to the rule. **The registration is SEALED**:
coefficients, threshold (0.05), side rule and stopping rule may not be altered. Altering any
of them ends it and starts a new clock. If 1,100 is unreachable, say so — that is a finding.

## What to deliver

1. **A verdict on the weather thesis.** The evidence above is close to conclusive. State
   whether it adds up to "no edge in weather forecasting on Kalshi for this operator," or
   name the specific measurement that would show otherwise.
2. **The selection test on `b`**, with the fitted values, sample definitions, and a clear
   statement of which way it came out.
3. **A stopping rule**, written into `backlog.txt`: a date, a sample size, and a threshold
   that, if unmet, means shutting down. The operator has asked twice whether this is worth
   continuing; a pre-committed answer beats another month of analysis.
4. Anything you file goes in `backlog.txt` in the existing entry style, with a dated header
   and citations you have re-derived.

**"Keep collecting data and see" is not a deliverable.** If that is your recommendation,
state exactly what sample by what date would change the answer. If you cannot, recommend
shutting it down.

## Constraints — not negotiable

- **Shadow only. Place nothing.** The console banner says `PRODUCTION MODE — LIVE ORDERS
  ENABLED` with `KALSHI_ENV=prod` while `.env` implies paper-only (`LIVE_TRADING_ENABLED`
  unset). **Resolve which is authoritative before running anything that could place.**
- **The pre-registration is sealed.**
- Follow the repo's 29-step workflow for any code change. **Step 11, the independent opus
  review, is never skipped** — it caught a live-circuit-breaker bug in the session that
  produced this document, and its blocking finding was one the author had missed.
- **Never run bare `pytest`.** Always scope it. Lint via `.unlazy/check_lint.py` and capture
  its exit status directly — do not pipe it through `tail`, which discards it.

## Where the evidence lives

- `predictions.db`: `predictions`, `outcomes` / `outcomes_valid`, `multiday_predictions`
  (a view: `days_out IS NULL OR days_out >= 1` — it **excludes same-day**, which has bitten
  two separate gates), `metar_lock_shadow_log` (every lock evaluation and its reason),
  `price_recal_shadow_log`, `price_history` (~32k hourly OHLC bars),
  `orderbook_depth_snapshots` (~21k).
- `data/paper_trades.json` (live era), `data/paper_archive/` (the earlier era — **easy to
  miss, and missing it once understated the loss by 9×**), `data/retired_strategies.json`.

## Traps this project has actually fallen into

- **Reproducing a number does not verify the claim it supports** — seven wrong inferences in
  one night, every arithmetic step exact.
- **A profitable stratum can be a bug.** Date-split every winning subset against the commit
  that changed its semantics. The +$282.81 above was 17-for-17 pre-guard.
- **Rows with no observation are not negative outcomes.** Counting 32 no-coverage rows as
  "did not fill" manufactured a $90 finding that vanished under permutation.
- **Optimizing one side of a tradeoff inverts the answer.** Scan-time scored on tradeable
  price share alone said "4 hours earlier, +63%"; the accuracy term reversed it (early locks
  53% correct, late 74%).
- **A sibling query missing its twin's filter.** Check both the "fixed" and the
  "deliberately not fixed" lists in any audit registry — the SPRT bug was on neither.
- **Instrument columns can mean something narrower than their name.** `scan_local_hour` is
  the *scan's* hour in the market city while the lock gates on the *observation's*, so rows
  with `scan_local_hour >= 14` legitimately read "too early (13h < 14h local)".
- Line citations drift constantly. Re-derive every one in a final pass.

## How to disagree with this document

Everything above is one session's reading, and that session made and corrected several
wrong calls in the process — including one that would have moved the scan four hours in the
wrong direction. If you find a claim here that does not reproduce, **the measurement wins**.
Say so explicitly, show the re-derivation, and correct the record in `backlog.txt` rather
than silently working around it.
