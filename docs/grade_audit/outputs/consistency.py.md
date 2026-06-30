# Grade Audit — consistency.py
Date: 2026-06-29
Grader: claude-sonnet-4-6

## File Overview

Cross-market consistency checker. Three functions total: `_parse_threshold`,
`_group_markets`, `find_violations`. The module-level `Violation` dataclass is also
reviewed.

**Key note from tier2.md:** Check whether it enforces (blocks trades) or only
logs/notifies. If notify-only: flag as INFO — the operator cannot distinguish a
consistency failure from normal operation without monitoring logs.

**Finding:** This module is **notify/detect-only**. `find_violations()` returns a list
of `Violation` objects. Nothing in this file blocks a trade. The caller in the live path
(likely `main.py` or a dashboard scan) decides what to do with violations. This is
flagged below as an INFO-level structural note.

---

## Dataclass: Violation (L:21–28) — TIER 2

No functions; pure data container. Fields are clearly named. `guaranteed_edge` sign
convention (sell_prob − buy_prob historically, but now bid_hi − ask_lo per R27) is
documented inline. No concerns.

---

## Function Grades

[consistency.py] `_parse_threshold()` L:30–65  8/10 — Correctly extracts (condition_type, threshold) using R26 series-prefix-first logic; fallback to title text is clearly labelled "less reliable"; returns None gracefully on no match; handles None/empty series and title via `or ""`. Minor gap: the regex `r"-([TB])(\d+(?:\.\d+)?)$"` accepts kind="T" and assigns it to neither "above" nor "below" — any ticker ending in `-T68` hits the first guard but falls through to the series-check which may or may not succeed, depending on caller data; this edge is obscure but possible if ticker format adds a new kind. No red flags.  [Confidence: Likely]

[consistency.py] `_group_markets()` L:68–120  7/10 — Groups markets correctly by (series, date_str); guards stale/empty books via `has_quote` check (F5 comment); logs a WARNING when date extraction fails (L87–93, good); imports `logging` inline inside the loop which is technically fine but slightly wasteful. Gap: the `import logging as _clog` inside the `for` loop body is called once per market that hits the date-miss branch — Python caches module imports so it is not a correctness issue but is confusing style. More importantly: if `parse_market_price` raises an exception (e.g., malformed market dict), there is no try/except here — the exception propagates silently up to `find_violations`, which has no guard either; the entire scan aborts for all markets rather than skipping the bad one.  [Confidence: Confirmed]
FIX: consistency.py:104 — wrap `prices = parse_market_price(m)` in a try/except that logs a WARNING and continues to the next market.

[consistency.py] `find_violations()` L:123–195  7/10 — Logic correctly implements monotonicity checks for above (decreasing in threshold) and below (increasing in threshold); uses real bid/ask spread for edge calculation (R27), not midpoints; filters p>0 entries; applies 0.01 tolerance to avoid floating-point noise; removes non-positive-edge violations at end (M-16). Gaps: (1) No try/except around the main loop — an unexpected market dict shape from `_group_markets` could abort the entire scan; (2) No log line when violations are found or when the scan completes with zero violations — operator has no visibility without debug logging; (3) The function returns only `real_violations` (edge > 0) which is correct for arb purposes but means a zero-edge violation (exactly breakeven spread) is silently discarded — that may be intentional, but there is no comment explaining it.  [Confidence: Confirmed]

---

## Structural Finding (INFO)

**consistency.py is detect-only — no enforcement path.** `find_violations()` returns a
list; nothing in this file blocks, pauses, or alerts on a trade. If the caller in
`main.py` or the dashboard does not act on the returned violations, the operator will
see nothing. This is acceptable architecture **if** the caller handles alerting, but the
module has no contract or docstring stating what callers must do. A comment on
`find_violations` noting "callers are responsible for acting on violations" would
close this ambiguity.

---

## Summary Table

| Function | Score | Red Flags | Invariants |
|---|---|---|---|
| `_parse_threshold` | 8/10 | None | N/A |
| `_group_markets` | 7/10 | None | N/A |
| `find_violations` | 7/10 | None | N/A |

**File median: 7/10.**

No TIER 1 promotions required (no RF1–RF6 fires).

No trading-decision thresholds, Kelly formula, balance reads, or DB queries in this
file — invariants I1–I10 are not applicable.
