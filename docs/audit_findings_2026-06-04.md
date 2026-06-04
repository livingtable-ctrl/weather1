# System Audit Findings — 2026-06-04

10 agents, 227 tool calls, then manually verified against source.
1 CRITICAL confirmed by independent verification, 0 downgraded.

**Post-audit source verification corrections (2026-06-04):**
- Original HIGH "update_peak_profits() missing lock" → downgraded to MEDIUM: `py main.py loop`
  and `py main.py web` are separate OS processes so `_DATA_LOCK` provides no cross-process
  protection anyway; within the loop process, no intra-process concurrent writer is active
  when Phase 7 runs. The code defect is real but the race cannot fire in normal operation.
- Original MEDIUM "_mark_needs_manual_settle() missing lock" → downgraded to INFO: same
  reasoning; only called from main cron thread, no concurrent writer at that point.

## Severity Summary

| Severity | Count |
|---|---|
| CRITICAL | 1 |
| HIGH | 3 |
| MEDIUM | 8 |
| INFO/CLEAN | 20 |
| UNCERTAIN | 2 |

---

## CRITICAL

### B1 — `directional_accuracy` includes same-day METAR trades (KNOWN UNFIXED)
**File:** `paper.py` lines 1727–1742
**Also:** `cron.py` lines 617, 632, 689

```python
all_settled = [
    t
    for t in get_all_trades()          # no days_out filter
    if t.get("settled")
    and t.get("net_edge") is not None
    and t.get("outcome") is not None
    and t.get("side") is not None
    and t.get("pnl") is not None
]
natural = [t for t in all_settled if t.get("outcome") in ("yes", "no")]  # no days_out guard
n_natural = len(natural)
if n_natural > 0:
    dir_wins = sum(1 for t in natural if t["outcome"] == t["side"])
    directional_accuracy: float | None = round(dir_wins / n_natural, 4)
```

**Issue:** `get_all_trades()` returns every trade regardless of `days_out`. Same-day METAR
above/below trades use `ci_scale=1.0` and METAR-locked probabilities near 0 or 1, making
them near-certain to resolve in the predicted direction. Their directional accuracy
approaches 100% and inflates the mixed metric above 0.70 even when the multi-day model
has degraded. `cron.py` reads this metric at line 617 and uses it at two decision points:
- Line 689: ensemble pin auto-renews for 168h if `_da >= 0.70`
- Line 632: Brier-drift edge-tightening suppressed if `_directional_accuracy >= 0.70`

Independent verification confirmed: no compensating guard anywhere in the call chain.
8 same-day trades placed 2026-06-04 settle within hours — contamination activates on
the next cron run.

**Impact:** (1) Ensemble pin auto-renews even when multi-day model is degrading, preventing
auto-retirement. (2) Brier-drift edge-tightening suppressed, masking genuine multi-day
degradation. Both effects are invisible in logs — `directional_accuracy >= 0.70` appears
with no indication same-day trades are inflating it.

**Fix:** In `get_edge_realization_rate()` (paper.py ~line 1727), build a separate filtered
list before computing `directional_accuracy`:
```python
multiday_natural = [
    t for t in all_settled
    if t.get("outcome") in ("yes", "no")
    and (t.get("days_out") is None or t.get("days_out") >= 1)
]
```
Expose as `multiday_directional_accuracy` in the returned dict. In `cron.py` lines 617
and 688, read the new key instead of the mixed `directional_accuracy`.

---

## HIGH

### M_LOCK — `update_peak_profits()` missing `_DATA_LOCK` — code defect, low practical risk
**File:** `paper.py` lines 1136–1167
**Severity: MEDIUM** (downgraded from HIGH after verifying execution model)

```python
def update_peak_profits(
    open_trades: list[dict], current_yes_prices: dict[str, float]
) -> bool:
    data = _load()          # no _DATA_LOCK acquired
    changed = False
    for t in data["trades"]:
        ...
        t["peak_profit_pct"] = round(unrealized_profit_pct, 4)
        changed = True
    if changed:
        _save(data)          # no _DATA_LOCK held
```

**Issue:** Every other mutating function (`settle_paper_trade`, `close_paper_early`,
`place_paper_order`, `reset_peak_balance`) holds `_DATA_LOCK` for the entire
read-modify-write cycle. `update_peak_profits()` holds no lock. This is a code defect
but the practical race window is narrow: `py main.py loop` and `py main.py web` are
**separate commands** (separate OS processes) so `_DATA_LOCK` is per-process and cannot
protect them against each other regardless. Within `py main.py loop`, the only
intra-process background thread is the startup `auto_settle()` which completes in seconds
— well before Phase 7 (where `update_peak_profits` is called, ~minutes into the cron
cycle). The `ThreadPoolExecutor` used for analysis (8 threads) only calls weather analysis
functions, never paper.py writes. So the race essentially cannot fire in normal operation.

**Impact:** If the web app is somehow run in the same Python process (not the current
architecture), a Flask thread calling `place_paper_order` concurrently could overwrite a
peak_profit_pct update. In the current split-process architecture, cross-process safety is
provided by `os.replace()` in `atomic_write_json`, not `_DATA_LOCK`.

**Fix:** Wrap the entire function body in `with _DATA_LOCK:` to make it consistent with
every other mutating function in the file. Low urgency.

---

### H1 — `train_temperature_scaling()` queries raw `predictions` table — latent contamination trap
**File:** `ml_bias.py` lines 414–417

```python
rows = con.execute(
    "SELECT p.our_prob, o.settled_yes FROM predictions p "
    "JOIN outcomes o ON p.ticker = o.ticker "
    "WHERE p.our_prob IS NOT NULL AND o.settled_yes IS NOT NULL"
).fetchall()
```

**Issue:** Queries `FROM predictions` (raw table), not `FROM multiday_predictions`. This
mixes same-day METAR-derived probs (near 0/1) with multi-day ensemble probs when fitting
global T. The function is not called from any production path today (confirmed by
exhaustive grep). However, a single direct call from a test, backtest, or manual CLI
experiment overwrites `temperature_scale.json` with a contaminated value, silently
miscalibrating live trading until the process restarts.

**Impact:** No active bug today. A single direct call compresses all multi-day predictions
toward 0.5 incorrectly. The correct production function `train_all_temperature_scaling()`
uses the right `days_out` filter (A4 CLEAN).

**Fix:** Delete the function (superseded by `train_all_temperature_scaling()`) or add
`AND (p.days_out IS NULL OR p.days_out >= 1)` to the query.

---

### H2 — `run_anomaly_check()` includes same-day trades — WIN_RATE_COLLAPSE can halt when multi-day model is healthy
**File:** `alerts.py` lines 226–280, 322–331

```python
# entry point (line 322-331):
trades = load_paper_trades()   # returns ALL trades, no days_out filter
anomalies = check_anomalies(trades)

# check_anomalies() (lines 241-278):
recent = sorted(trades, key=lambda t: t.get('placed_at', ...), reverse=True)[:10]
settled = [t for t in recent if t.get('outcome') in ('yes', 'no')]
if len(settled) >= 5:
    win_rate = wins / len(settled)
    if win_rate < 0.30:
        alerts_out.append('WIN RATE COLLAPSE ...')
...
if consec >= 5:
    alerts_out.append(f'CONSECUTIVE LOSSES: {consec} losses in a row')
```

**Issue:** `load_paper_trades()` returns every trade regardless of `days_out`. The 10-trade
recency window and settled slice both include same-day (days_out=0) METAR-locked trades.
With 8 same-day trades placed 2026-06-04, a bad METAR day with 5+ losses triggers
`WIN_RATE_COLLAPSE` (< 30% wins in last 10 settled). `CONSECUTIVE_LOSSES` can also fire
from a streak of same-day losses even when every multi-day prediction is correct.

**Impact:** Trading halts for the next cron cycle even though the multi-day ensemble model
is healthy, missing valid multi-day signals.

**Fix:** In `run_anomaly_check` (line 331), filter to multi-day trades before calling
`check_anomalies`:
```python
trades = [t for t in load_paper_trades() if t.get('days_out') is None or t.get('days_out', 1) >= 1]
```

---

### H3 — Platt scaling exception silently swallowed — bare `except Exception: pass`
**File:** `weather_markets.py` lines 5444–5470

```python
    try:
        _platt = _load_platt_models()
        if _platt:
            from ml_bias import apply_platt_per_city as _apply_platt
            _new_prob = _apply_platt(city, blended_prob, _platt)
            ...
    except Exception:
        pass
```

**Issue:** The temperature scaling block (line 5206) — the structural sister of this block
— logs at ERROR on failure. The Platt block uses `except Exception: pass` with no log
message at any level. If `apply_platt_per_city()` raises (e.g. JSON decode error, missing
key, math domain error), the calibration correction is silently skipped with no trace.

**Impact:** A broken `platt_models.json` would silently miscalibrate every multi-day trade
for the affected city without any log trace. The operator cannot detect the failure via
log monitoring or alerting.

**Fix:** Replace `except Exception: pass` with:
```python
except Exception as _exc:
    _log.warning("analyze_trade: Platt scaling failed for %s: %s", enriched.get('ticker', '?'), _exc)
```

---

## MEDIUM

### INFO_LOCK — `_mark_needs_manual_settle()` missing `_DATA_LOCK`
**File:** `paper.py` lines 2484–2495
**Severity: INFO** (downgraded from MEDIUM — same execution-model caveat as M_LOCK above)

```python
def _mark_needs_manual_settle(trade_id: int) -> None:
    data = _load()         # no lock
    ...
    if changed:
        _save(data)        # no lock
```

The function is only called from `auto_settle_paper_trades()` which runs in the main cron
thread sequentially. No concurrent intra-process writer is active at that point. If the
flag is already set (`needs_manual_settle=True`), `changed` stays `False` and `_save()`
is not called, so repeated calls are safe. Code defect only — no financial fields.

**Fix:** Acquire `_DATA_LOCK` for consistency with the rest of paper.py. Low urgency.

---

### M2 — `needs_manual_settle` trades re-query Kalshi API every cron cycle indefinitely
**File:** `paper.py` lines 2509–2544

`auto_settle_paper_trades()` does not skip trades where `needs_manual_settle=True`. Each
cycle calls `get_outcome_for_ticker` (returns None), falls through to `client.get_market`
(returns 404), re-calls `_mark_needs_manual_settle` (idempotent), and emits a WARNING.
No correctness bug but accumulating archived trades create rate-limit pressure and log
noise indefinitely.

**Fix:** Add `if t.get('needs_manual_settle'): continue` at the top of the inner loop,
before calling `get_outcome_for_ticker`.

---

### M3 — `daily_spent` not incremented after live trade placement — cap can be exceeded within one cycle
**File:** `order_executor.py` lines 747–748, 1026–1053

```python
daily_spent = _daily_paper_spend()   # read once
if daily_spent >= MAX_DAILY_SPEND:
    return 0
# ... live trades placed, daily_spent never updated
```

Paper path correctly re-checks per trade. Live path does not. With multiple strong signals
in one cycle, `MAX_DAILY_SPEND` can be exceeded by up to `(N-1) × trade_cost`. Currently
running in paper mode so not firing. Becomes active when `KALSHI_ENV=prod`.

**Fix:** After each successful live placement, `daily_spent += cost` (variable is already
in scope).

---

### M4 — Kill switch not checked immediately before `auto_place_trades()` call
**File:** `cron.py` lines 1457–1468

Kill switch is checked at cycle start (line 401) and during scan loop (line 1079). No
check immediately before the placement calls at lines 1457–1468. If activated after scan
completes but before placement executes, trades still fire in that cycle.

**Fix:** Add immediately before the placement block:
```python
if KILL_SWITCH_PATH.exists():
    _log.warning("kill switch activated before placement — skipping")
    return None
```

---

### M5 — Black swan Brier `MIN_SAMPLES` gate counts all trades including same-day
**File:** `alerts.py` lines 419–424

```python
settled = [p for p in _get_history() if p.get("settled_yes") is not None]
if len(settled) >= BLACK_SWAN_BRIER_MIN_SAMPLES:
    bs = _brier_score()
```

`get_history()` queries `FROM predictions` (all trades). Sample gate clears using same-day
trades before there are enough multi-day settled predictions for `brier_score()` (which
correctly uses `min_days_out=1`) to be meaningful. Note: the Brier calculation itself is
clean (H2 partial pass) — only the gate count is contaminated.

**Fix:** Replace `get_history()` count with `tracker.count_settled_predictions()` (already
queries `multiday_predictions`).

---

### M6 — GBM bias correction exception silently swallowed — bare `except Exception: pass`
**File:** `weather_markets.py` lines 5406–5435

```python
    try:
        from ml_bias import apply_ml_prob_correction, has_ml_model
        if has_ml_model(city):
            _corrected = apply_ml_prob_correction(...)
            ...
    except Exception:
        pass
```

Same structural issue as H4 (Platt) but lower risk because Platt acts as a fallback
when `_city_correction_applied=False`. Root GBM failure still invisible to operator.

**Fix:** `except Exception as _exc: _log.warning("analyze_trade: GBM correction failed for %s: %s", enriched.get('ticker', '?'), _exc)`

---

### M7 — Monte Carlo values same-day trades with full simulation horizon — VaR overstated
**File:** `monte_carlo.py` lines 226–231

```python
_tdate = t.get("target_date")
if _tdate and _tdate < _utc_today().isoformat():
    _log.debug("Monte Carlo: skipping past-date trade %s (%s)", ticker, _tdate)
    continue
```

`target_date == today` is not skipped. Same-day trades are modelled with the same Monte
Carlo path as multi-day trades even though they settle within hours. With up to 8
same-day positions open, VaR and `prob_ruin` are overstated.

**Impact:** Informational/operational. No evidence VaR directly gates trade placement today.
`prob_ruin` threshold (20% of balance) could produce a false anomaly alert if enough
same-day positions are open simultaneously.

**Fix:** For same-day trades (`days_out == 0` or `target_date == today`), either skip them
from the VaR simulation or assign a near-zero residual variance.

---

## UNCERTAIN

### U1 — F3 calibration sentinel not updated on failure — retries every cycle on persistent errors
**File:** `cron.py` lines 1529–1556

Sentinel is only written after `calibrate_and_save()` succeeds. A persistent calibration
error (e.g. schema mismatch after a DB migration) causes retries on every cron cycle
indefinitely with WARNING log spam. Could be intentional for transient error recovery.

**Argue keep:** Transient DB lock errors should retry.
**Argue fix:** Persistent errors (missing scipy, schema mismatch) should not spam logs.
Possible middle ground: update sentinel after 3 consecutive failures.

---

### U2 — Market anchor applies to same-day pre-METAR-locked trades — potential double-counting
**File:** `weather_markets.py` lines 5215–5247

For same-day trades not yet METAR-locked (before 2 PM local or inconclusive observation),
the 10–25% market anchor blends `blended_prob` toward the market mid-price. The ensemble
is already supplemented by live obs (`obs_override`) and METAR-derived persistence.
Could double-count intraday market information.

**Counterargument:** The market encodes real intraday data the ensemble cannot see, so
anchoring is reasonable. The model-market gap gate (7d) provides a harder fallback check.

No empirical data available to determine which effect dominates.

---

## Clean Checks (19)

All of the following were verified correct:

- **A1** — 21 analytics functions in `tracker.py` correctly use `multiday_predictions` view
- **A1** — 4 functions correctly query raw `predictions` (intentional: `get_brier_by_days_out`, `get_market_calibration`, `get_history`, `sync_outcomes`)
- **A2** — `count_settled_predictions()` queries `multiday_predictions` (line 968)
- **A3** — All three calibration functions filter `days_out IS NULL OR days_out >= 1`
- **A4** — `train_all_temperature_scaling()`: correct multi-day and sameday queries, 20-sample gate, `sameday` key stored
- **A5** — `train_bias_model()` queries `FROM multiday_predictions`
- **A6** — Platt training in `main.py` queries `FROM multiday_predictions`
- **A7** — `analyze_trade()`: `apply_temperature_scaling` called with `days_out=days_out`; GBM and Platt guards use `days_out > 0`; METAR-locked path sets `_city_correction_applied=True`
- **B2** — `economic_win_rate`, Pearson correlation not used in graduation, halt, or scaling decisions
- **C1** — NWS sigma ladder matches spec exactly (`nws.py:291–301`)
- **C2** — `obs_prob()` uses `sigma=3.5` (`nws.py:437`)
- **C3** — `_nws_days_out_scale()` returns early at `days_out <= 0`; no weight-doubling at same-day
- **D3** — Between-market guard for live observation present at `weather_markets.py:4917`
- **E1** — `_drawdown_snapshot()` correctly filters `settled=False AND days_out==0 AND needs_manual_settle=False`
- **E2** — `is_paused_drawdown()` and `drawdown_scaling_factor()` both call `_drawdown_snapshot()`
- **E3** — `get_max_drawdown_pct()` not used in any trading decision path
- **E4** — `reset_peak_balance()` raises `ValueError` without `confirmed=True`; CLI requires typing "yes"
- **F2** — `needs_manual_settle` trades excluded from `_drawdown_snapshot()` same-day locked sum
- **F3** — Paper trade written only after `place_paper_order()` succeeds; no phantom position risk
- **F4** — `days_out`, `close_time`, `cost`, `side` present; NULL `close_time` handled with skip-and-warn
- **G1** — `MAX_SAME_DAY_POSITIONS` and `MAX_POSITIONS_PER_DATE` use independent counters
- **G2** — `drawdown_scaling_factor()` applied inside `kelly_bet_dollars()`
- **G3** — Signals sorted by `ci_adjusted_kelly` descending before date-cap consumption (`cron.py:1445–1446`)
- **G5** — `days_out` preserved in `signals_cache`; passed through to `place_paper_order`
- **H2** — `brier_score()` called with `min_days_out=1`; same-day trades excluded from Brier calculation itself
- **H4** — `is_paused_drawdown()` uses effective balance via `_drawdown_snapshot()`
- **I1** — F3 auto-calibration reads `count_settled_predictions()`; writes sentinel after success
- **I2** — `py main.py calibrate` updates sentinel before returning
- **I3** — Brier alert uses `get_brier_over_time()` with `min_days_out=1`
- **I4** — `train_all_temperature_scaling()` sets `_TEMP_CACHE = None` after writing `temperature_scale.json`
- **J2** — `simulate_portfolio()` returns safe zero-result dict on empty portfolio; no NaN/crash
- **K2** — `safe_io.atomic_write_json` uses temp file + `os.replace()` with `fsync`
- **K3** — `tracker._conn()` sets WAL mode; all callers use context manager
- **KE1** — Temperature scaling exception logged at ERROR; trade continues with unscaled prob
- **KE2** — `sync_outcomes()` per-ticker failures use `continue`; loop never aborted
- **KE3** — `calibrate_and_save()` exception caught at WARNING; cron cycle continues
- **KE4** — `_place_live_order` pre-logs before API call; `was_ordered_this_cycle` deduplicates
- **L1** — `load_dotenv()` called at line 41; first local import at line 45
- **L2** — `pyproject.toml` has `"main.py" = ["E402"]` per-file-ignore

---

## Separation Verdict

**Substantially complete with two live gaps.**

Core separation is verified correct across all 21 analytics functions, all three calibration
paths, all ML training paths (`train_all_temperature_scaling`, `train_bias_model`, Platt
training), and all trade-placement guards (GBM/Platt/temperature-scaling guarded by
`days_out > 0`; METAR-locked path sets `_city_correction_applied=True`). The separation
work documented as complete in MEMORY.md is verified complete.

Two live gaps remain:
1. **CRITICAL** — `get_edge_realization_rate()` in `paper.py:1727–1742`: mixed
   `directional_accuracy` used by ensemble pin and Brier-drift suppression
2. **HIGH** — `run_anomaly_check()` in `alerts.py:322–331`: mixed anomaly detection can
   halt multi-day trading on same-day METAR losses

---

## Highest-Risk Unfixed Issue

`paper.py:1727–1742` — `directional_accuracy` contamination. Activates on the next cron
run after today's 8 same-day trades settle. Prevents ensemble retirement and suppresses
edge-tightening — both effects invisible in logs because `directional_accuracy >= 0.70`
appears with no indication same-day trades are inflating it.

---

## Unresolved (design questions)

- **D1** — Whether anchoring same-day pre-METAR trades toward market price double-counts
  intraday information requires empirical edge data to resolve
- **F3** — Whether calibration sentinel should update on failure depends on intent
  (transient retry vs persistent error suppression)
