# SYNTHESIS PROMPT — Grade Audit
# The synthesis agent receives this file plus all per-file grade outputs.

## Your Role

You have received grade reports from agents that each graded one source file of a
live-money weather prediction trading bot. Synthesize all reports into a single
final document. Do not re-derive anything. Do not re-read source files. Work only
from the agent outputs provided.

---

## Decision Matrix

For each system area below, find all TIER 1 findings with score ≤6 from the relevant
files. Determine whether the area is GO (no blockers) or NOT YET (has a blocker).

| System area | Relevant files | Verdict | Blocking finding (if NOT YET) | Severity | Fix time estimate |
|---|---|---|---|---|---|
| Trade placement — same-day METAR path | metar.py, weather_markets.py, order_executor.py | | | | |
| Trade placement — multi-day pipeline | weather_markets.py, ml_bias.py, nws.py, calibration.py | | | | |
| Kelly sizing and position caps | weather_markets.py, cron.py | | | | |
| Balance and drawdown accounting | paper.py, order_executor.py | | | | |
| Settlement and 24h gate | cron.py, tracker.py, paper.py | | | | |
| Calibration and SQL separation | tracker.py, calibration.py, ml_bias.py | | | | |
| Atomic writes and data integrity | safe_io.py, paper.py, monte_carlo.py | | | | |
| Kill switch and circuit breaker | cron.py, circuit_breaker.py, alerts.py | | | | |
| API integration and idempotency | kalshi_client.py, order_executor.py | | | | |
| Graduation gate | paper.py, tracker.py | | | | |

---

## Bottom 10 Functions Overall

Collect all findings with score ≤5 across all files. Rank by score ascending (lowest
first), break ties by TIER (TIER 1 before TIER 2).

| Rank | File | Function | Score | Confidence | Failure scenario (one line) | Fix |
|---|---|---|---|---|---|---|

---

## Red Flags Summary

List every red flag (RF1–RF6) that fired across all files.

| RF# | File | Function | Line | Exact code quote |
|---|---|---|---|---|

---

## Systemic Weaknesses

Patterns appearing in ≥3 functions across ≥2 files. For each:
- Name the pattern
- List all occurrences (file:function)
- State the compound risk — why it matters that multiple functions share this flaw

---

## Systemic Strengths

Patterns done consistently well across ≥3 functions. List them — these set the quality
bar for future contributions.

---

## Dead Code Report

List all files flagged as suspected dead code. For each: name it, list what imports it
(if anything in the live trade path), and state whether removal is safe.

---

## Overall Verdict

One paragraph. Answer: is this system ready to trade live money? If YES, state what
gives you confidence. If NOT YET, state the single highest-risk unfixed finding and
what it would take to clear it.
