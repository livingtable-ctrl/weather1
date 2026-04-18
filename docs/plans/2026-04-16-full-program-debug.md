# Full-Program Debug Session — 2026-04-16

**Branch:** `debug/full-program-fixes`
**PR:** #13
**Suite:** 760 passed / 3 skipped (baseline was 740)
**New tests:** 20 in `tests/test_debug_fixes.py`

---

## Scope

Rigorous full-codebase audit and fix pass triggered after all Phase G tasks merged (PR #12 — A/B framework). Two batches of fixes; all committed to PR #13.

---

## Batch 1 — Core bugs (commit ba1a7f4)

### A — `tracker.py`: `analysis_attempts` INSERT OR REPLACE overwrites `was_traded=True`

**Problem:** Three `INSERT OR REPLACE` sites in `log_analysis_attempt`, `batch_log_analysis_attempts`, and `analyze_all_markets`. When cron restarts mid-day, the batch re-scan re-inserts all markets with `was_traded=False`, silently resetting any rows previously marked `was_traded=True` — breaking P&L attribution trade counts.

**Fix:** All three sites now use:
```sql
INSERT ... ON CONFLICT(ticker, target_date) DO UPDATE SET
    analyzed_at   = excluded.analyzed_at,
    forecast_prob = excluded.forecast_prob,
    market_prob   = excluded.market_prob,
    days_out      = excluded.days_out,
    was_traded    = MAX(analysis_attempts.was_traded, excluded.was_traded)
```
`MAX(...)` means `was_traded` can only go `0→1`, never `1→0`.

---

### B — `paper.py`: env var parsing crashes on startup with invalid values

**Problem:** `float(os.getenv("DRAWDOWN_HALT_PCT", "0.50"))` at module level — if the env var is set to a non-numeric string, Python raises `ValueError` at import time, crashing the entire bot.

**Fix:** Added `_env_float(name, default)` and `_env_int(name, default)` helpers that catch `ValueError`, log a warning, and return the default. Applied to `DRAWDOWN_HALT_PCT`, `MAX_DAILY_LOSS_PCT`, `MAX_POSITION_AGE_DAYS`, `MAX_SINGLE_TICKER_EXPOSURE`.

---

### C — `main.py`: `log_prediction` failures silently swallowed

**Problem:** `except Exception: pass` at `main.py` L815 — if the DB write fails (locked, corrupt, disk full), the prediction is silently lost with no log entry.

**Fix:** Replaced with `logging.getLogger(__name__).warning("cmd_analyze: log_prediction failed for %s: %s", ticker, exc)`.

---

### D — `tracker.py`: `sync_outcomes()` silently skips failed markets

**Problem:** `except Exception: continue` with no logging — if Kalshi API times out or rate-limits during outcome sync, the failure is invisible.

**Fix:** Added `_log.warning("sync_outcomes: failed to fetch/record %s: %s", ticker, exc)`.

---

### E — `paper.py`: `entry_prob=0.0` replaced by `0.5` (falsy-zero bug)

**Problem:** Two call sites used `t.get("entry_prob") or 0.5`. If `entry_prob` is exactly `0.0` (valid probability), it evaluates as falsy and is replaced with `0.5`, inflating covariance Kelly signals.

**Locations:** `covariance_kelly_scale` loop (`paper.py` ~L948), `get_attribution` loop (~L1674).

**Fix:**
```python
_ep_raw = t.get("entry_prob")
p_i: float = float(_ep_raw) if _ep_raw is not None else 0.5
```

---

### F+G — `paper.py`: `place_paper_order()` has no input validation

**Problem:** Bad `side` values (e.g. `"maybe"`), out-of-range `entry_prob` (e.g. `1.5`), or `entry_price=0.0` all silently produce incorrect trades with no error.

**Fix:** Three guards added before business logic:
```python
if side not in ("yes", "no"):
    raise ValueError(f"side must be 'yes' or 'no', got {side!r}")
if entry_prob is not None and not (0.0 <= entry_prob <= 1.0):
    raise ValueError(f"entry_prob must be in [0, 1], got {entry_prob}")
if not (0.0 < entry_price <= 1.0):
    raise ValueError(f"entry_price must be in (0, 1], got {entry_price}")
```

---

### H — `main.py`: cron auto-placed trades never reach `predictions` table

**Problem:** `_auto_place_trades` called `log_analysis_attempt` (writes to `analysis_attempts` table) but never `log_prediction` (writes to `predictions` table). `pnl-attribution` queries `predictions`, so it showed zero data for all cron-placed trades — making the feature permanently useless.

**Fix:** Added `log_prediction(...)` call immediately after each successful paper order placement, with independent `target_date` parsing so it's robust to the preceding `log_analysis_attempt` block failing.

---

### perf — `weather_markets.py`: in-memory forecast cache doesn't survive process restart

**Problem:** The 90-minute forecast cache is process-local (`dict`). Every `python main.py analyze` starts cold, hitting Open-Meteo for 3 models × N distinct cities × 1.5s rate-limit = 30–45s of waiting before showing results.

**Fix:** Disk-backed cache at `data/forecast_cache.json`:
- `_load_forecast_disk_cache()` called at module import — populates in-memory `_FORECAST_CACHE` from disk for entries younger than 90 min
- `_save_forecast_disk_entry(cache_key, data)` called after each cache miss — writes to disk in a daemon thread (non-blocking, non-fatal on failure)
- Result: 2nd+ `analyze` run within 90 minutes is nearly instant

---

## Batch 2 — Additional fixes (commit 0474fb2)

### Fix 1 — `.gitignore`
`data/` is already fully gitignored. `data/forecast_cache.json` requires no additional entry. ✅ No action.

### Fix 2 — `win_rate` unsettled trade leakage
Investigated all `win_rate` computation sites. Both pre-filter to `t["settled"] and pnl is not None` before counting wins. **Not a real bug** — `or 0` pattern is harmless inside already-filtered lists.

### Fix 3 — `tracker.py`: `log_prediction` TOCTOU race

**Problem:** `SELECT ... WHERE ticker=? AND date(predicted_at)=date('now')` then `UPDATE` or `INSERT` — two separate SQL statements. Concurrent calls for the same ticker+day could both see `existing=None` and both attempt `INSERT`, producing duplicate rows.

**Fix:**
1. Schema migration v12: `CREATE UNIQUE INDEX IF NOT EXISTS idx_pred_ticker_date ON predictions(ticker, date(predicted_at))`
2. Replaced SELECT+branch with single atomic upsert:
```sql
INSERT INTO predictions (...) VALUES (...)
ON CONFLICT(ticker, date(predicted_at)) DO UPDATE SET
    our_prob=excluded.our_prob, raw_prob=excluded.raw_prob, ...
```
Schema version bumped `11 → 12`.

### Fix 4 — `weather_markets.py`: disk cache grows unboundedly

**Problem:** `_save_forecast_disk_entry` reads the JSON, appends, writes — but never removes old entries. Over weeks the file accumulates stale data for past dates.

**Fix:** After adding the new entry, prune the dict:
```python
raw = {k: v for k, v in raw.items() if now - v.get("ts_posix", 0) < _FORECAST_CACHE_TTL}
```
File now stays bounded to the current 90-minute window.

### Fix 5 — `paper.py`: `portfolio_kelly()` dead production code

**Status: SKIPPED.** Function has 6 active tests in `tests/test_trading.py` (`TestPortfolioKelly`). It is intentionally untested in production code paths but reserved for future multi-position Kelly sizing. Deleting it would break those tests.

### Fix 6 — `main.py`: `_midpoint_price()` inverted spread

**Problem:** If Kalshi API returns `yes_bid > yes_ask` (malformed response), `(bid + ask) / 2` computes a mid-price outside the valid range, silently producing a wrong entry price.

**Fix:**
```python
if bid > ask:
    bid, ask = ask, bid  # guard against inverted spread from API
return round((bid + ask) / 2, 2)
```

---

## Files changed

| File | Changes |
|------|---------|
| `tracker.py` | analysis_attempts upsert (A); sync_outcomes logging (D); log_prediction upsert + migration v12 (Fix 3) |
| `paper.py` | `_env_float/_env_int` (B); entry_prob falsy-zero (E); place_paper_order validation (F+G) |
| `main.py` | log_prediction warning (C); log_prediction wired into _auto_place_trades (H); _midpoint_price guard (Fix 6) |
| `weather_markets.py` | disk-backed forecast cache (perf); cache pruning on write (Fix 4) |
| `tests/test_debug_fixes.py` | 20 new regression tests |
