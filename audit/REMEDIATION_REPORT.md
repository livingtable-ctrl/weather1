# Weather1 Remediation Batch Set 76–80 — Report

Repo: `C:\Users\thesa\claude kalshi` (branch `master`, HEAD `e8d178f1`)
Report date: 2026-08-26
Companion data: `audit/REMEDIATION_REPORT.json` (13 findings, structured)
Handoff prompts: `audit/handoff_prompts/batches/batch-76.md` … `batch-80.md`

## Executive Summary

| Metric | Count |
|---|---|
| Open `backlog.txt` entries at time of audit | 61 |
| Selected as completable in a single session | 14 |
| HIGH | 2 |
| MEDIUM | 6 |
| MEDIUM-HIGH | 1 |
| LOW | 5 |
| Requiring an explicit user design decision | 10 |
| Batches produced | 6 (81 blocked on 76-80) |
| Cross-batch file conflicts | **0** (verified programmatically) |
| Deferred by file contention | 1 |

## Method

The 61 open entries were filtered on one question: *can this be completed in a single session?* That excludes three categories, and the distinction matters because two of them look actionable and are not.

- **Blocked on data accrual, not effort.** EMOS (40-row floor), GEM/UKMO/HRRR graduation, cross-city pooling, richer ML features. No amount of work today moves these; they need settled samples.
- **Blocked on infrastructure or credentials.** The VM move, the `DEMO_BASE` smoke test.
- **Genuinely multi-day.** The rain/snow/hurricane category surface, which the entry itself says has no model architecture for any of the three.

The survivors were then grouped so that **no two batches share a touched file** — the same constraint the 2026-08-18 batch set was built under, and the property that makes parallel worktree sessions safe. Grouping was derived from each entry's own `Files:` block, not from theme, and the result is verified in code rather than by eye (see Verification below).

**Every entry was checked against its own body text rather than its title.** This was not ceremony: three entries in the same pass turned out to be already resolved.

## The correction that shaped this audit

Two entries on the initial shortlist were **already fixed** and had been counted as open for days:

| Entry | Real status |
|---|---|
| `web_app.py`'s two leftover `@_require_auth` decorators | RESOLVED 2026-08-24, batch-61 (both branches taken) |
| `execution_log.get_live_pnl_summary()`'s `open_count` undercount | RESOLVED 2026-08-25, batch-58 |

Both carried a stale `[OPEN]` header *above* a real `[RESOLVED]` header for the same entry. `backlog_index.py` keys off an entry's **first** status bracket, so an entry that gains a resolution header without having its old one removed is counted as open forever. A third instance (`TK_*` synthetic tickers, resolved 2026-08-24 by batch-62) was found and corrected earlier the same day.

A scan of every entry for this pattern — an `[OPEN|PARTIALLY RESOLVED]` header followed within four lines by a `[RESOLVED|CLOSED]` one — found exactly those three. All are now corrected; the open count moved **66 → 61**. The scan is cheap and worth repeating whenever the open count is used for planning, because the failure is silent and inflates the number in the direction of looking like more work remains.

## Batches

| Batch | Theme | Items | Files owned |
|---|---|---|---|
| **[76](handoff_prompts/batches/batch-76.md)** | METAR lock: side inversion + var mislabel | 2 (1 HIGH) | `weather_markets.py`, `metar.py` |
| **[77](handoff_prompts/batches/batch-77.md)** | Circuit-breaker blast radius | 1 (HIGH) | `kalshi_client.py`, `paper.py` |
| **[78](handoff_prompts/batches/batch-78.md)** | Observability & retention | 3 | `tracker.py`, `cron.py`, `trade_cycle.py`, `kalshi_ws.py` |
| **[79](handoff_prompts/batches/batch-79.md)** | Process bootstrap & config durability | 3 | `web.py`, `web_app.py`, `config.py`, `utils.py`, `calibration.py`, `ml_bias.py`, `paths.py`, `main.py` |
| **[80](handoff_prompts/batches/batch-80.md)** | Frontend, alerting, two vacuous tests | 4 | `frontend/src/*`, `notify.py`, `tests/test_trade_improvements.py`, `tests/test_kelly_property.py`, `order_executor.py` |
| **[81](handoff_prompts/batches/batch-81.md)** | Graduation floor + unbiased signal logging | 2 | `weather_markets.py`, `main.py`, `tracker.py`, `cron.py`, `order_executor.py` — **BLOCKED on 76–80** |

**Suggested order if run serially: 77, 76, then any.** 77 is a risk-control path and its fix is well-specified. 76 is the highest-value single item but has the largest design surface.

**Batch 80 is the safest parallel companion** to anything — it shares no file with any other batch and touches no trading decision.

## Top Risks

1. **REM-0003** [HIGH] `kalshi_client.py:93`, `paper.py:1998-2030` — one shared `kalshi_api_read` breaker means a 401 on a *private* endpoint disables `get_market()`, which is **public and unsigned**. Observed live: 8 of 8 open positions fell back to `entry_price`, unrealized P&L read 0.00, and no stop could fire. The bot reported "no loss" at the exact moment it was blind.

2. **REM-0001** [HIGH] `weather_markets.py` `analyze_trade` — a monotone-safe lock's probability is floored at 0.72 against a truth near 99.9%, and because side selection is a bare `blended_prob > market_prob`, the understatement **flips the side**. Verified arithmetic: against a market at 0.90 the bot recommends NO with `entry_side_edge = +0.18`, on an outcome the lock has already settled. The market-divergence gate that would catch this sits behind `if not metar_locked:` and never runs on that path.

3. **REM-0008** [MEDIUM] — a routine `git restore .` silently reverts five learned-calibration files to uncalibrated seeds, on a live pricing path, with no warning.

4. **REM-0002** [MEDIUM] — `KXHOLIDAYTMIN` analysed as a daily-maximum market end to end, terminating in a ~20–30 °F sign-flipped sample in the same corrector batch-75 has just finished cleaning. Shadow-only today; fix before the family graduates.

## Two structural observations

**Nine of thirteen findings need a user decision before code.** That is unusually high and it is not indecision — several are of the form *"the safe-looking fix makes the number bigger without closing the hole"* (REM-0001), or *"one parameter cannot serve two horizons"* (REM-0005), or *"this changes what a live-facing surface displays"* (REM-0007). Batch files state the options rather than picking, and say which option closes the defect by construction versus which merely reduces its likelihood.

**Two findings are the same defect at different layers.** REM-0001 and REM-0002 are both a `var`/side label disagreeing with physical reality, and both terminate in `get_dynamic_station_bias()` — the corrector batch-75 repaired hours earlier. They are batched together for that reason: fixing one leaves the corrector reachable by the other.

## Batch 81 — added 2026-08-26, after the accrual measurement

Written after the set above, once the 2026-08-26 `analysis_attempts` drain (scored rows 115 → 584) prompted the question *"should the sample floors be raised now that more data is guaranteed?"*.

**The answer is yes, and the number is ~86** — back-solved from the entry's own "n=20 → 27% power" claim, giving a per-observation effect of 0.3012 and n=86 for 80% power on the same two-sided-95% convention the rest of this repo uses.

**But the premise needed checking, and it was half wrong.** The 6× gain does *not* reach these floors: `analysis_attempts` carries no signal columns, so every registry floor still counts selection-biased `predictions` rows accruing at 0.87–1.13/day. Three of five signals clear 86 today or within four days; the two that do not are 41 and 68 days out. **Logging signal values onto `analysis_attempts` would cut that to ~4 days and make the rows unbiased** — the larger half of the batch's value, and not in the original entry.

The ordering flip worth remembering: `nbm_quantile_prob` is the signal that cleared the floor and fired the activation alert, and at 27 rows it is the *furthest* from measurable. It looked ready because the bar was wrong.

**It also corrects three factual errors in its own source entry** (verified by enumerating the registry): ten of twelve entries use `sample_floor=20`, not nine of eleven; `richer_ml_features` is `None`, not 20; `rain_forecast_blend` is 20, not `None`.

## Deferred by file contention

Not blocked on data or decisions — only on `weather_markets.py` and `main.py` being owned by batches 76 and 79.

| Entry | Severity | Blocked by |
|---|---|---|
| `cron.report_anomalies READS A "forecast_temp_raw" KEY THAT NOTHING HAS EVER WRITTEN` | LOW | `weather_markets.py` (76) + `cron.py` (78) |

The signal-registry floor item that was listed here has been promoted to **batch 81** rather than left deferred — see above.

The first is worth scheduling deliberately rather than letting it drift: nine registry signals share `sample_floor=20`, the graduation report prints "floor cleared" in green, and `_notify_feature_activation` fires an alert on it. It is a bad-decision trap filed before it springs.

## Verification

- **File-conflict freedom is proven, not asserted.** `REMEDIATION_REPORT.json`'s generator walks every finding's `files` list and reports any path claimed by two batches. Result: `NONE`.
- **Every batch file cites `backlog.txt` entries by TITLE, never by line number.** `L`-numbers in this repo drift constantly — they moved five times in one session on 2026-08-25, and again during this audit when three stale headers were removed.
- **Counts in this report were derived at write time**, not carried from an earlier step in the session.

## Limitations

- Severity is inherited from each `backlog.txt` entry's own `Priority:` line, not independently re-assessed. Where an entry's body contradicted its title, the body was followed and the discrepancy is noted in the batch file (REM-0002 is the clearest case — its title understates the blast radius, which an `UPDATE` block in the body corrects).
- "Completable in a single session" is a judgement, not a measurement. REM-0001 and REM-0010 are the two most likely to exceed it: the first has three defensible fixes with different blast radii, the second needs logic extracted into `shared.jsx` before it can be tested at all, because this frontend has no component-render tests.
- The two deferred items are deferred **only** by file ownership. If batches 76 and 79 are not being run, both become immediately available.
