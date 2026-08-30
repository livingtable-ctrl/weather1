Task: design the forward-validation protocol for the price-recalibration rule
("option 5" / "option I"), then build the shadow log that starts its clock.
Protocol first — the log is worthless without it.

START BY READING (all committed on master):
  - docs/calibration-and-edge-research-2026-08-29.md  §2, §3, §7, §8
  - backlog.txt "TWO WAYS OUT OF THE NO-EDGE RESULT..." — option I is the rule,
    and its "WHY THIS IS NOT YET AN EDGE" block is the caveat list, not preamble
  - backlog.txt "PROJECT DIRECTION AFTER THE NO-EDGE RESULT" — option 5

THE RULE. Model-free, uses no weather forecast. Fit y ~ a + b*logit(market_prob)
on settled markets; where the recalibrated probability disagrees with the raw
price by more than a threshold, bet the side recalibration favours. The original
in-sample fit was b=1.4871, z=+3.03 against the null b=1. Its discovery table
used thresholds 0.05 (n=135, net +4.98%) and 0.08 (n=42, net +10.46%) — do not
invent a new threshold; those, and the two others the entry says were tried, are
the search that creates the multiple-testing problem below.

NUMBERS ARE A SNAPSHOT — RE-DERIVE THEM, DO NOT TRUST THEM. The cron writes new
rows daily; this population grew from 646 to 670 in the hours between the doc
being written and this prompt. As re-measured on the unbiased population
(analysis_attempts, outcome NOT NULL, both probs NOT NULL): 670 rows total; core
temperature (above/below/between) b=+1.336, SE 0.101, z=+3.32, n=642; same-day
+1.244 (z=+2.14, n=435); multi-day +1.431 (z=+1.76, n=207). All ten sub-cells sit
above 1.

Two things about that, both load-bearing:
  - Two cells DO reach conventional significance alone — same-day z=+2.14 and
    'above' z=+2.92, and 'above' survives a Bonferroni correction for ten cells.
    But the cells overlap heavily ('above' is ~55% of core and shares every row
    with the d0/d1+ split), so they are not ten independent votes and they do not
    address the multiple-testing problem. Do not quote them as corroboration.
  - It is all in-sample, on the same rows the rule was found in. None of it is
    evidence the rule works. That is what the forward log is for.
  - analysis_attempts upserts days_out, so a row only stays at d>=1 if the market
    stopped being scanned. The d>=1 slice is selected ~3x on base rate. Relevant
    to how you stratify the forward log.

WHY IT NEEDS A REAL PROTOCOL, not just "log it for 60 days":
  - Found in-sample after ~4 thresholds were tried, following two hypotheses that
    had already failed on the same data. Textbook forking paths.
  - Published counter-evidence (arXiv 2602.19520v2, confirmed 3-0) puts Kalshi
    *Weather* slopes at 0.69-0.97 within 48h of resolution — the opposite sign —
    and its isotonic estimate at price 0.75 is 0.691, while every pick this rule
    makes is a favourite priced 0.74-0.86. If that describes these contracts, the
    book loses ~6 points of probability per contract before fees.
  - BUT that paper is not obviously about these contracts, and the reconciliation
    is documented: its "Weather" domain pools daily ladders with monthly, precip,
    tornado, hurricane and arctic-ice tickers; its classifier has no LOW/LOWT/MIN
    pattern so KXLOWT is largely excluded; its data ends 2025-12-31, before this
    project's window opens; and its unit is a quantity-weighted trade over a 5-95c
    filter, not one snapshot per settled market. Beyond 48h its own Weather row
    rises to 1.20-1.37. Treat the conflict as unresolved, not as a verdict —
    building the log is still the right move.
  - Severe downside skew: risking ~0.79 to win ~0.21. A few losses erase many wins.
  - Kalshi's fee is ~0.07*p*(1-p) per contract — UNVERIFIED, both research passes
    failed to confirm it. Confirm it before using it in any net-of-fee figure.

WHAT I NEED FROM YOU:
 1. A pre-committed protocol, written into backlog.txt BEFORE any code:
    - exactly what gets logged per pick, and the decision rule that generates it
    - the multiple-testing haircut this rule is held to, given the search that
      produced it (Harvey & Liu's haircut Sharpe, deflated Sharpe, and Gelman &
      Loken's forking-paths paper were all located but never read — read them)
    - the minimum number of independent forward observations before it may be
      sized at all, derived, not guessed. Note "settled count" != "independent
      samples": one city-day's ladder rungs are one weather event.
    - the stopping rule and the no-peeking discipline: when it is judged, what
      result kills it, and what stops you re-cutting the data until it passes
 2. Then the log itself. exit_rule_shadow_log (cron.py, 107 rows) is the proven
    pattern but NOT a drop-in — it is positions-shaped (entry_price, cost,
    peak_profit_pct). Option 5 needs a picks-shaped table. Shadow only; it must
    place nothing.

CONSTRAINTS:
  - Live trading is dormant and this does not change that. Shadow only.
  - Do not re-propose, all measured dead: blending the model with the price
    (c=-0.041, held-out t=+1.01); fading the model (|z|<1 everywhere); ladder
    coherence arb (built, zero violations ever); market-making (~$0.05/round
    trip); isotonic regression (contraindicated below ~1000 cases);
    vector/Dirichlet scaling (collapse to the beta calibration already shipped).
  - Do not "improve the forecast". The ensemble has no skill against the price
    and is -$213 lifetime. This rule deliberately uses no weather model.
  - Do not start the separate refit of the paper's public data on daily ladders
    only. It is the other half of the plan and belongs in its own session.
  - Follow the 29-step implementation workflow. Scope every pytest run.
