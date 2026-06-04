# Full System Audit — Kalshi Weather Trading Bot

## Context

This is a live production trading bot (~$818 balance, 59 settled trades) that places
real-money bets on Kalshi weather markets. Two trade types exist with fundamentally
different probability pipelines:

- **Same-day** (`days_out=0`): METAR-locked probabilities, `ci_scale=1.0`, sharp near 0/1
- **Multi-day** (`days_out≥1` or `NULL` for legacy): ensemble blend of GFS/ECMWF/ICON +
  NWS forecast + climatology, smooth 0.3–0.7 range

A SQLite view `multiday_predictions` (defined in `tracker.py` `init_db()`) is the single
source of truth for multi-day analytics:
```sql
CREATE VIEW multiday_predictions AS
  SELECT * FROM predictions WHERE days_out IS NULL OR days_out >= 1
```

Key recent changes (last 2 weeks):
- Same-day/multi-day data fully separated across temperature scaling, GBM bias, Platt
- `_drawdown_snapshot()` in `paper.py` adds back open same-day costs to effective balance
- `load_dotenv()` moved before all local imports so module-level constants read `.env`
- `count_settled_predictions()` now queries `multiday_predictions`
- GBM and Platt application guarded with `days_out > 0` in `weather_markets.py`

---

## Your Task

Read the source files listed below. For **every finding**, you must:
1. Quote the exact file path and line number(s)
2. Paste the relevant code lines
3. Explain what is wrong AND what the correct behaviour should be

**Do not report a finding you cannot cite with a specific line number from source.**

If a pattern looks suspicious but could be intentional or another path compensates,
mark it **UNCERTAIN** and argue both sides. Do not mark it CRITICAL.

Assume code is correct until you can prove otherwise. The bar for CRITICAL is high:
you must show the bug actively fires or will fire on the next plausible code path.

---

## Files to Read (in this order)

1. `paper.py` — balance, drawdown, peak reset, `get_all_trades()`, `get_edge_realization_rate()`
2. `tracker.py` — DB schema, `multiday_predictions` view definition, all SQL queries
3. `ml_bias.py` — temperature scaling train+apply, GBM train+apply, Platt train+apply
4. `calibration.py` — blend weight training queries (`_load_rows`, each calibrate function)
5. `nws.py` — sigma scoping by days_out and condition_type
6. `weather_markets.py` — `analyze_trade()` full flow: blending → temp scaling → GBM → Platt → Kelly
7. `cron.py` — settlement loop, calibration gate, kill switch, drawdown check, ensemble pin
8. `order_executor.py` — trade placement, paper trade recording, retry logic
9. `main.py` — `load_dotenv()` position, `cmd_calibrate()`, `cmd_admin()` reset-peak
10. `safe_io.py` — atomic write implementation
11. `circuit_breaker.py` — thresholds and trigger logic
12. `alerts.py` — Brier alert and anomaly detection

---

## Known-Intentional Patterns — Do NOT Flag These

The following `FROM predictions` (non-view) queries are intentionally unfiltered.
Flagging them as bugs would be a false positive:

- `tracker.py get_brier_by_days_out()` — explicitly segments by days_out in Python;
  needs all rows to populate the "same_day" bucket
- `tracker.py get_history()` — trade history display; should show all trades
- `tracker.py sync_outcomes()` — must check ALL unsettled tickers for new Kalshi outcomes
- `tracker.py get_market_calibration()` — measures Kalshi market prices vs outcomes,
  not our model; same-day market probs are valid input
- `tracker.py purge_old_predictions()` / schema migrations — operate on the raw table
- `paper.py get_all_trades()` — deliberately returns everything; callers filter if needed

---

## Audit Categories

### A. Same-day / Multi-day SQL Separation

For each of the following, read the function, paste the SQL, and confirm the filter:

**A1.** Every function in `tracker.py` that joins `predictions` with `outcomes` to compute
a Brier score, win rate, or calibration metric — does it use `multiday_predictions`
or has an explicit `days_out >= 1` filter? Cross-check against the known-intentional
list above before flagging.

**A2.** `count_settled_predictions()` — confirm it queries `multiday_predictions`, not
raw `predictions`. This guards graduation threshold and F3 auto-calibration trigger.

**A3.** All three blend-weight functions in `calibration.py`
(`calibrate_seasonal_weights`, `calibrate_city_weights`, `calibrate_condition_weights`) —
confirm `_load_rows()` and any inline queries include
`AND (p.days_out IS NULL OR p.days_out >= 1)`.

**A4.** `ml_bias.py train_all_temperature_scaling()` — confirm:
- Main (multi-day) query has `AND (p.days_out IS NULL OR p.days_out >= 1)`
- Separate sameday query has `AND p.days_out = 0`
- Sameday gate is 20 samples
- "sameday" key is stored in `temperature_scale.json` and never falls back to global T

**A5.** `ml_bias.py train_bias_model()` — confirm query uses `FROM multiday_predictions`,
not `FROM predictions`.

**A6.** Platt training query in `main.py cmd_calibrate()` — confirm it uses
`FROM multiday_predictions`.

**A7.** In `weather_markets.py analyze_trade()`:
- Confirm `apply_temperature_scaling()` is called with `days_out=days_out` keyword argument
- Confirm GBM correction block has `days_out > 0` guard before calling `apply_ml_prob_correction()`
- Confirm Platt block has `days_out > 0` guard before calling `apply_platt_per_city()`
- Confirm all three guards check the correct `days_out` variable (set earlier in the same function)

---

### B. Ensemble Pin and Directional Accuracy Contamination

**B1.** In `cron.py`, the ensemble pin auto-renewal checks `directional_accuracy >= 0.70`.
Trace where `directional_accuracy` comes from (it calls `get_edge_realization_rate()`
in `paper.py`). That function uses `get_all_trades()` which returns ALL settled trades
including same-day.

- Does same-day trades being included inflate `directional_accuracy`?
- Same-day METAR trades have high directional accuracy by construction (METAR observations
  are accurate). Could a batch of settled same-day wins keep the ensemble pin alive even
  if multi-day directional accuracy has degraded?
- Is there a `days_out` filter anywhere in `get_edge_realization_rate()` or its callers?

Flag this CRITICAL if there is no filter. Flag UNCERTAIN if the inflation is bounded.

**B2.** `get_edge_realization_rate()` in `paper.py` also computes `economic_win_rate`
and Pearson correlation — confirm these are not used as graduation or halt criteria
without a days_out filter.

---

### C. NWS Sigma Scoping

**C1.** In `nws.py`, confirm the sigma ladder is:
- `days_out <= 0`: `sigma=1.0` for all condition types
- `days_out == 1` AND `condition_type == "between"`: `sigma=1.0`
- `days_out == 1` AND above/below: `sigma=2.0` (NOT 1.0 — applying sigma=1 here
  would compound with `_nws_days_out_scale` weight doubling)
- `days_out <= 2`: `sigma=2.0`
- `days_out <= 5`: `sigma=3.0`
- else: `sigma=4.0`

Any deviation from this exact ladder is a CRITICAL bug — the between-only scoping
at days_out=1 was specifically engineered to fix a structural 38.4% cap issue.

**C2.** In `nws.py obs_prob()` (same-day METAR intraday function, separate from
the NWS forecast function) — confirm it uses `sigma=3.5`, NOT `sigma=1.0`.
The obs function is for current METAR readings mid-day; sigma=1.0 there would produce
near-binary probabilities from an intraday reading (the daily max hasn't been reached yet).

---

### D. Market Anchor for Same-day Trades

**D1.** In `weather_markets.py`, the market anchor (`_MARKET_ANCHOR_BETWEEN`,
`_MARKET_ANCHOR_ABOVE`, `_MARKET_ANCHOR_BELOW`) blends `blended_prob` toward the market
mid-price. Is this anchor applied to same-day trades (days_out=0)?

If yes: for same-day trades, the market price is already very close to 0 or 1 (market
knows the answer is near). Anchoring METAR-derived probs toward this market price could
actually be correct (the market has seen the same METAR data). Mark UNCERTAIN and explain.

If no: confirm there is a days_out guard.

**D2.** The model-market gap gate (`_model_mkt_gap > 0.25`) skips trades where our model
disagrees with the market by >25%. For same-day METAR trades, our model probability IS
derived from the same observation data the market uses — so a gap >25% is more suspicious
than for multi-day. Confirm whether this gate is applied to same-day trades and whether
that is appropriate.

---

### E. Drawdown and Balance Safety

**E1.** `_drawdown_snapshot()` in `paper.py` — confirm:
- The entire function runs under a single `with _DATA_LOCK:` block (one `_load()` call)
- `same_day_locked` sums only trades where `not t.get("settled")` AND `t.get("days_out") == 0`
  AND `not t.get("needs_manual_settle")`
- No path can read balance and then lose the lock before writing (TOCTOU)

**E2.** `is_paused_drawdown()` and `drawdown_scaling_factor()` — confirm both call
`_drawdown_snapshot()`, not `get_balance()` or `get_peak_balance()` directly.

**E3.** `get_max_drawdown_pct()` — confirm it uses actual `get_balance()` (not effective
balance). It is a reporting metric, intentionally not the same as trading decisions.

**E4.** `reset_peak_balance()` — confirm it raises `ValueError` if `confirmed=True` is
not passed. Confirm the CLI prompt in `main.py cmd_admin` requires the user to type
`"yes"` explicitly and cannot be bypassed by piping input.

**E5.** TOCTOU race check — in `order_executor.py` and `cron.py`, look for this pattern:
```
balance = get_balance()          # reads outside lock
if balance > threshold:          # decision
    place_order(...)             # side effect
    deduct_from_balance(...)     # write
```
If `get_balance()` and the subsequent write are not held under the same lock
acquisition, another cron cycle could race between the read and the write.
Report line numbers of any such pattern.

---

### F. Settlement and Trade Lifecycle

**F1.** In `cron.py` settlement loop — confirm the 24h gate
(`close_time + 24h < now`) is applied consistently for ALL settlement trigger paths:
normal settlement, `needs_manual_settle` path, and black swan forced settlement.
If any path skips the 24h gate, flag CRITICAL.

**F2.** `needs_manual_settle` trades — confirm they are excluded from:
- `_drawdown_snapshot()` same-day locked cost sum (`not t.get("needs_manual_settle")`)
- Normal settlement retry loop (should not re-attempt once flagged)
- Any path that tries to call `sync_outcomes()` on these tickers

**F3.** In `order_executor.py` — confirm the paper trade record is written ONLY after
the Kalshi API returns a successful response. A failed API call (non-2xx, timeout,
network error) must not create a phantom position in `paper_trades.json`.

**F4.** Confirm paper trade records include these fields: `days_out`, `close_time`,
`cost`, `side`. Trades placed before 2026-05-28 may have `NULL` close_time — confirm
the 24h gate handles `NULL` gracefully (skips rather than crashes).

---

### G. Kelly Sizing and Position Caps

**G1.** Confirm same-day trades use `MAX_SAME_DAY_POSITIONS` cap and multi-day trades
use `MAX_POSITIONS_PER_DATE` cap. These must be checked independently — a same-day
trade must not consume a multi-day slot and vice versa. Cite the exact check in `cron.py`.

**G2.** Confirm `drawdown_scaling_factor()` is applied to the Kelly fraction before
quantity calculation. Cite the line in `weather_markets.py` where scaling is applied.

**G3.** Confirm signals are sorted by Kelly descending before date-cap consumption.
A weaker signal should not claim a cap slot over a stronger one from the same day.

**G4.** Confirm `MAX_DAILY_SPEND` cap is enforced and counts both same-day and
multi-day spend. Confirm it is not reset mid-scan if the cron loop retries.

---

### H. Kill Switch and Safety Gates

**H1.** Confirm the kill switch is checked at the start of each cron cycle. Confirm
a PAUSED state blocks order placement — not just signal analysis. If the kill switch
is checked before scanning but not before each individual order, a mid-scan kill
switch activation would not take effect until the next cycle.

**H2.** Confirm the black swan Brier check uses `brier_score()` with default
`min_days_out=1`. A spike in same-day losses (METAR bets going wrong) should not
trigger the black swan halt, which is designed to detect multi-day model collapse.

**H3.** In `circuit_breaker.py` — are thresholds hardcoded or read from env/config?
Flag INFO if hardcoded (not wrong, but reduces operability).

**H4.** Confirm `is_paused_drawdown()` uses effective balance (via `_drawdown_snapshot()`)
so same-day open costs don't trigger a false halt.

---

### I. Calibration Gates and Auto-Trigger

**I1.** F3 auto-calibration in `cron.py` — confirm the trigger reads the sentinel and
calls `count_settled_predictions()` (multi-day only). Confirm `calibrate_and_save()`
is called (not just blend-weight calibration). Confirm the sentinel file is updated
after completion.

**I2.** Confirm the calibration sentinel is also updated after `py main.py calibrate`
runs so the next cron cycle doesn't immediately re-run calibration.

**I3.** Confirm the Brier alert in `cron.py` uses `get_brier_over_time()` with default
`min_days_out=1` so same-day trades don't inflate the two-week rolling Brier
that drives the P10.3 alert.

---

### J. Atomic Writes and Data Integrity

**J1.** In `paper.py` — confirm every function that calls `_save()` holds `_DATA_LOCK`
for the entire read-modify-write cycle. Look for patterns where `_load()` and `_save()`
are called in the same function but in separate lock blocks.

**J2.** In `safe_io.py` — confirm `atomic_write_json()` uses a temp file + `os.rename()`
(or equivalent) pattern. A crash between write and rename must not leave a partial
file at the target path.

**J3.** Confirm `tracker.py` enables SQLite WAL mode (`PRAGMA journal_mode=WAL`) in `_conn()`.
Confirm no function holds a connection object open across a `yield` or async boundary
that could cause a lock to be held longer than intended.

---

### K. Error Handling and Degradation

**K1.** In `weather_markets.py analyze_trade()` — if temperature scaling raises an
exception, confirm the trade continues with unscaled probability. Confirm the exception
is logged at ERROR (not DEBUG or silently swallowed).

**K2.** If `sync_outcomes()` fails for a specific ticker (e.g. Kalshi API error),
confirm the loop continues to attempt other tickers rather than aborting all settlement.

**K3.** If `calibrate_and_save()` raises during auto-calibration in `cron.py`,
confirm the exception is caught and logged and the cron cycle continues.

**K4.** In `order_executor.py` — confirm that if the Kalshi API returns a 404 or 500
during order placement, the trade is not double-booked on a retry.

---

### L. load_dotenv() Ordering

**L1.** In `main.py` — confirm `load_dotenv()` is called before ANY local module import
(i.e. before `import paper`, `import order_executor`, `import tracker`, etc.).
Module-level constants like `paper.MAX_DRAWDOWN_FRACTION` are set at import time;
if `load_dotenv()` runs after the import, `.env` overrides have no effect.

**L2.** Confirm `pyproject.toml` has `"main.py" = ["E402"]` under
`[tool.ruff.lint.per-file-ignores]` to suppress the intentional E402 violation.

---

## Output Format

For each finding:

```
[SEVERITY] Category X.N — Short title
File: filename.py line(s) NNN–NNN
Code:
    <paste exact lines from source>
Issue: <what is wrong>
Impact: <what breaks or could break and when>
Fix: <specific change needed, with pseudocode if helpful>
```

Severity levels:
- **CRITICAL** — actively wrong; could cause bad trades, wrong balance, or incorrect halts today
- **HIGH** — will become a bug as data grows (e.g. a missing filter that fires when sample thresholds are hit)
- **MEDIUM** — degrades model quality or reporting accuracy without causing bad trades
- **INFO** — style or operability issue; no functional impact
- **UNCERTAIN** — suspicious but could be intentional; argue both sides and do not recommend a fix

After all findings:
1. Count by severity (CRITICAL / HIGH / MEDIUM / INFO / UNCERTAIN)
2. Verdict: is same-day/multi-day separation complete end-to-end?
3. The single highest-risk unfixed issue found
4. Any category where you could not reach a verdict (file unreadable, logic too complex to trace)
