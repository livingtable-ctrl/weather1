# Full System Audit — Kalshi Weather Trading Bot

## Context

This is a live production trading bot that places real-money bets on Kalshi weather markets.
Current state: ~$818 balance, 59 settled trades (51 multi-day, 8 same-day), master at fee48f8.

Key recent work (last 2 weeks):
- Same-day (METAR, days_out=0) and multi-day (ensemble, days_out≥1) trades separated
- SQLite view `multiday_predictions` created as single source of truth for multi-day analytics
- Effective balance fix: open same-day costs excluded from drawdown calculation
- Temperature scaling, GBM bias, Platt scaling all now have separate same-day paths
- `load_dotenv()` moved before all local imports so module-level constants read .env correctly

## Your Task

Read the actual source files listed below. For every finding you report, you MUST quote
the exact file path and line number(s) and paste the relevant code. Do NOT report a
finding if you cannot produce a specific line-number citation from source.

If a pattern looks suspicious but you cannot confirm it is actually a bug (e.g. the
behaviour is intentional, or another code path compensates), mark it UNCERTAIN and
explain both sides. Do NOT mark it CRITICAL.

## Files to Read (in this order)

1. `paper.py` — balance, drawdown, effective balance, peak reset
2. `tracker.py` — DB schema, multiday_predictions view, all analytics queries
3. `ml_bias.py` — temperature scaling, GBM bias, Platt scaling (train + apply)
4. `calibration.py` — blend weight training queries
5. `weather_markets.py` — analyze_trade() flow: blending → temp scaling → GBM → Platt → Kelly
6. `cron.py` — settlement loop, calibration gate, kill switch check, drawdown check
7. `order_executor.py` — trade placement, retry logic, paper trade recording
8. `main.py` — load_dotenv() position, cmd_calibrate(), cmd_admin(), Kelly wiring

## Audit Categories

### A. Same-day / Multi-day Data Separation

The system has two trade types with fundamentally different probability sources:
- **Same-day** (days_out=0): METAR-locked, ci_scale=1.0, sharp probs near 0/1
- **Multi-day** (days_out≥1 or NULL): ensemble blend of GFS/ECMWF/ICON + NWS + climatology

For EACH of the following, confirm the correct filter is applied and cite line numbers:

1. Every SQL query that reads from `predictions` or `outcomes` — does it use
   `multiday_predictions` view or `AND (p.days_out IS NULL OR p.days_out >= 1)` where
   it should? Flag any that use raw `FROM predictions` when they should be filtered.

2. Temperature scaling (`apply_temperature_scaling`) — confirm same-day path uses
   "sameday" key only with no fallback to global T. Confirm days_out is passed at
   every call site in weather_markets.py.

3. GBM bias correction (`apply_ml_prob_correction`) — confirm there is a `days_out > 0`
   guard at the call site in weather_markets.py. Confirm training query uses
   `multiday_predictions`.

4. Platt scaling (`apply_platt_per_city`) — confirm there is a `days_out > 0` guard
   at the call site. Confirm training query uses `multiday_predictions`.

5. `count_settled_predictions()` — confirm it queries `multiday_predictions`, not raw
   `predictions`.

6. Blend weight calibration (`calibrate_seasonal_weights`, `calibrate_city_weights`,
   `calibrate_condition_weights`) — confirm all three filter to multi-day only.

7. Brier score calls in cron.py and main.py — confirm `min_days_out` is not overridden
   to 0 at any call site (default=1 uses multiday_predictions).

### B. Drawdown and Balance Safety

1. `_drawdown_snapshot()` — confirm it holds the lock for the entire read (single `_load()`
   call). Confirm it sums same-day open costs correctly and excludes `needs_manual_settle`.

2. `is_paused_drawdown()` and `drawdown_scaling_factor()` — confirm both call
   `_drawdown_snapshot()` (not `get_balance()` or `get_peak_balance()` directly).

3. `get_effective_balance()` — confirm it is only a thin wrapper over `_drawdown_snapshot()`.

4. `get_max_drawdown_pct()` — confirm it uses actual `get_balance()` (not effective balance)
   since it is a reporting metric, not a trading decision.

5. `reset_peak_balance()` — confirm it requires `confirmed=True` or raises ValueError.

6. In `cron.py` and `order_executor.py`, confirm that balance-reading and balance-writing
   happen under the correct lock (`_DATA_LOCK`). Look for any path that reads balance,
   makes a trading decision, then writes balance without holding the lock continuously —
   this is a TOCTOU race.

7. Confirm `STARTING_BALANCE` and `MAX_DRAWDOWN_FRACTION` are module-level constants
   read from env AFTER `load_dotenv()` runs in `main.py`. Check the import order.

### C. Settlement and Trade Lifecycle

1. In `cron.py` settle loop — confirm the 24h gate (`close_time + 24h < now`) is applied
   consistently for all three settlement trigger paths (normal, needs_manual_settle,
   black_swan).

2. Confirm `needs_manual_settle` trades are excluded from:
   - effective balance calculation (same-day locked cost sum)
   - normal settlement attempts (should not retry once flagged)

3. In `order_executor.py` — confirm paper trade records include `days_out`, `close_time`,
   and `cost` fields. Confirm a failed API call does not leave a partial paper trade
   record (i.e. record is only written after confirmation).

4. Confirm `sync_outcomes()` in tracker.py does not settle outcomes for same-day trades
   before their `close_time` has passed.

### D. Calibration Gates and Triggers

1. F3 auto-calibration in `cron.py` — confirm the sentinel count comes from
   `count_settled_predictions()` (multi-day only). Confirm `calibrate_and_save()` is
   called, not just blend-weight calibration.

2. `train_all_temperature_scaling()` — confirm the two-query structure:
   - Multi-day query: `AND (p.days_out IS NULL OR p.days_out >= 1)`
   - Same-day query: `AND p.days_out = 0`
   - Gate for sameday: 20 samples
   - Gate for global: uses `min_samples_global` parameter

3. Confirm the calibration sentinel file (`.last_calibration_count`) is updated after
   both manual calibrate (`main.py`) and auto-calibrate (`cron.py`).

### E. Kelly Sizing and Position Caps

1. Confirm same-day trades use `MAX_SAME_DAY_POSITIONS` cap (default 8) and multi-day
   trades use `MAX_POSITIONS_PER_DATE` cap (default 4). Confirm these are checked
   independently — same-day cap should not consume multi-day slots and vice versa.

2. Confirm `drawdown_scaling_factor()` is applied to Kelly fraction before quantity
   calculation in `weather_markets.py`.

3. Confirm signals are sorted by Kelly descending before date-cap consumption — a
   weaker signal should not claim a cap slot over a stronger one.

4. Confirm `MAX_DAILY_SPEND` cap is enforced separately from position count caps.

### F. Kill Switch and Circuit Breakers

1. Confirm the kill switch is checked at the start of each cron cycle and that a
   PAUSED state prevents order placement (not just signal scanning).

2. Confirm `is_paused_drawdown()` is checked before placing orders, not just before
   scanning. A drawdown that occurs mid-scan (from earlier orders in the same scan)
   should block later orders.

3. In `circuit_breaker.py` — confirm thresholds are read from env or config, not
   hardcoded. If hardcoded, flag as a finding with severity INFO.

4. Confirm black swan Brier check uses `brier_score()` with default `min_days_out=1`
   (multi-day only). A spike in same-day losses should not trigger the black swan halt.

### G. Atomic Writes and Data Integrity

1. In `paper.py` — confirm every path that modifies `paper_trades.json` calls `_save()`
   inside a `with _DATA_LOCK:` block. Look for any code that calls `_load()`, modifies
   the dict, then calls `_save()` outside the lock.

2. In `safe_io.py` (if it exists) — confirm `atomic_write_json()` uses a temp file +
   rename pattern. A crash mid-write should not corrupt the target file.

3. Confirm `tracker.py` DB writes use SQLite WAL mode and that no two functions try to
   hold their own connection objects open across yields or async boundaries.

### H. Error Handling and Degradation

1. In `weather_markets.py` `analyze_trade()` — if temperature scaling fails, confirm
   the trade continues with unscaled probability (degraded but not dropped). Confirm
   this is logged at ERROR level, not silently swallowed.

2. If `sync_outcomes()` fails for a specific ticker, confirm the error is logged and
   the loop continues (does not abort all settlement).

3. In `order_executor.py` — if the Kalshi API returns a non-200 status on order
   placement, confirm the paper trade record is NOT written (no phantom positions).

4. Confirm that if `calibrate_and_save()` raises (e.g. DB read failure), the exception
   is caught and logged, and the cron cycle continues rather than crashing.

## Output Format

For each finding, use this structure:

```
[SEVERITY] Category X.N — Short title
File: filename.py line(s) NNN
Code:
    <paste relevant lines>
Issue: <what is wrong>
Impact: <what breaks or could break>
Fix: <specific change needed>
```

Severity levels:
- **CRITICAL** — active bug, could cause wrong trades or incorrect balance
- **HIGH** — will become a bug as data grows (e.g. missing filter that fires at 50+ samples)
- **MEDIUM** — degrades model quality or reporting accuracy
- **INFO** — style/hygiene, no functional impact
- **UNCERTAIN** — suspicious but could be intentional; explain both sides

After all findings, provide:
1. A count by severity
2. A verdict on same-day/multi-day separation completeness
3. The single highest-risk unfixed issue you found
