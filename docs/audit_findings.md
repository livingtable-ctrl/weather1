# Adversarial Code Audit — Kalshi Weather Trading Bot

**Date:** 2026-05-15
**Files audited (Phase 1):** `calibration.py` · `ml_bias.py` · `paper.py` · `tracker.py` · `order_executor.py` · `monte_carlo.py`
**Files audited (Phase 2):** `weather_markets.py` · `system_health.py` · `trading_gates.py` · `alerts.py` · `circuit_breaker.py` · `nws.py` · `metar.py` · `consistency.py` · `settlement_monitor.py`
**Phase 3:** Test suite quality audit — 45 test files across 3 agent groups
**Phase 4:** Dedicated security audit — `kalshi_client.py` · `web_app.py` · `main.py` · `paper.py` · `ml_bias.py` · `safe_io.py` · `config.py`
**Auditor:** AI adversarial audit (parallel agents, one per file)

---

## Executive Summary

This codebase manages real money on a live exchange. The audit found **11 verified CRITICAL issues in the unified table** (C5, C6, C9, C13, C14, C17, C18, C19, C20, C22, C23 retracted as false positives; C15 downgraded to LOW) plus **additional Phase 2 CRITICAL issues** detailed in the per-file sections below, **33+ HIGH issues, and 30+ MEDIUM/LOW issues**. Three files — `order_executor.py`, `tracker.py`, and `paper.py` — each received a **production readiness score of 4/10**. No file scored above 5/10.

The most dangerous pattern is **silent failure-open**: safety gates (VaR checks, win-rate circuit breakers, HMAC validation, flash crash detection) all fail open when their internal code crashes, typically due to broad `except Exception: pass` blocks. The bot continues trading as if the safety check passed. This pattern appears in every file.

The known production failures (Platt signal inversion, temperature bias, duplicate trades) are **not fully fixed** — the root causes that enabled them are still present and can recur.

---

## Production Readiness Scores

| File | Score | Dominant Risk |
|------|-------|---------------|
| `order_executor.py` | **4/10** | 3 CRITICAL bugs make GTC lifecycle, idempotency, and crash recovery dead code |
| `tracker.py` | **4/10** | 2 CRITICAL bugs disable win-rate circuit breaker and corrupt bias storage *(C9 retracted — `station_observed` finding was false positive)* |
| `paper.py` | **4/10** | 4 verified CRITICAL bugs: `verify_backup()` validates CRC32 but never SHA-256; non-unique trade IDs after `undo_last_trade()`; P&L inconsistency between settle/calc/attribution; `place_paper_order` not atomic — concurrent calls exceed balance *(C5 NO-side P&L and C6 METAR side injection both retracted as false positives)* |
| `calibration.py` | **5/10** | Platt validation absent; calibration writes non-atomic; weight validation dead |
| `ml_bias.py` | **5/10** | Cache poison on failure; training not temporally ordered; silent correction failures |
| `monte_carlo.py` | **4/10** | Correlation matrix dimension mismatch (H8), correlation persistence broken (`save_correlations()` always raises TypeError), `portfolio_var()` KeyError on non-standard confidence levels *(H9 NO-side P&L retracted — formula verified correct)* |

---

## CRITICAL Issues — 12 Total

### C1 · `order_executor.py` — order_id extraction bug (all GTC lifecycle dead)

**Location:** `_poll_pending_orders()`, line 125

`_poll_pending_orders()` extracts `response.get("order_id")` but the Kalshi API wraps the order under `{"order": {"order_id": ...}}`. Returns `None` for every order. Consequence: fill polling, auto-cancellation after `gtc_cancel_hours`, and settlement accounting are **completely dead code in production**. Every live GTC order ever placed runs to expiry with no monitoring and capital remains locked. The fix used correctly elsewhere in the same file (`_micro_resp.get("order", {}).get(...)`) confirms the correct shape is known.

**Fix:** `response.get("order", {}).get("order_id")` — consistent with the pattern already used in the same file (`_micro_resp.get("order", {}).get(...)`). Do NOT use `(response.get("order") or response).get("order_id")` — if `response["order"]` is an empty dict (falsy), this incorrectly falls back to the flat structure, re-introducing the original bug. Do NOT use `response["order"]["order_id"]` — raises `KeyError` on malformed responses.

---

### C2 · `order_executor.py` — idempotency fallback misses filled orders

**Location:** `kalshi_client.py`, `_find_order_by_client_id()`, lines 343–353

On a network timeout, the fallback only queries `status=resting`. A taker-fill order that lands and fills immediately has `status=filled` — not found by the fallback. On any network timeout, the bot logs the order as `"failed"`, unblocks the dedup guard, and places a second order. This is the **exact failure mode behind the known duplicate-trade production bug**.

**Fix:** Make a second fallback call with `status=filled` (the Kalshi API status string for executed orders, confirmed by the existing `api_status in ("filled", "canceled", "expired")` check in `_poll_pending_orders`). When a filled order is found, set the execution log status to `"placed"` (not `"filled"` — the GTC poll loop should handle promotion to filled) so the dedup guard stays active and the order is not re-placed. Do not make both calls always — only make the second `status=filled` call if the first `status=resting` call returns no match, to avoid doubling API traffic on every timeout.

---

### C3 · `order_executor.py` — `_recover_pending_orders()` referenced but does not exist

**Location:** comment at line 253–254

Comments throughout describe crash recovery via `_recover_pending_orders()` at startup. The function does not exist anywhere in the codebase. A crash in the ~50ms window between pre-logging an order and the API call leaves a phantom `"pending"` row that permanently blacklists the ticker via dedup guards. Any actual order sent in that window is also irrecoverable — no reconciliation ever runs.

**Fix:** Implement the function: on startup, fetch all `status='pending'` rows, call `get_order()` for each, and resolve to `placed/filled/failed`.

---

### C4 · `calibration.py` / `ml_bias.py` — Platt signal inversion can silently recur

**Location:** `ml_bias.py`, `_fit_platt()`; `weather_markets.py`, `_load_platt_models()`

`_fit_platt()` does not check `res.success` from `scipy.optimize.minimize`. A failed optimizer returns whatever intermediate `A, B` it found — including `A < 0`. A negative `A` inverts `sigmoid(A·logit(p) + B)`, turning high-confidence YES signals into low-confidence signals. This is **the exact known production bug**. It can recur on any city with small/degenerate data, especially since `min_samples=15` at the call site is far too low for a stable fit. There is zero validation of `A, B` after fitting or after loading from JSON.

**Fix (both required):**
1. Check `res.success` and validate `A > 0, |A| ≤ 5, |B| ≤ 5` in `_fit_platt`. Raise on failure.
2. Validate loaded `(A,B)` in `_load_platt_models()` — skip and log ERROR for any city with `A ≤ 0`.
3. Raise `min_samples` from 15 to ≥ 50 at the `main.py` call site.

---

### C5 · `ml_bias.py` — `_MODELS_CACHE = {}` permanently disables bias correction on transient failure

**Location:** `_load_models()`, lines 57–101

If `MODEL_HMAC_SECRET` is missing at startup — common if `.env` loads late — `_load_models()` sets `_MODELS_CACHE = {}`. Subsequent calls see a non-None cache and skip reloading forever. All GBM correction is silently disabled for the process lifetime. No log output. Every trade thereafter runs with zero bias correction.

**Fix:** Use a distinct sentinel (`_LOAD_ATTEMPTED = False` bool) separate from the cache dict. `{}` should only mean "loaded, no models found." Transient failures must not permanently poison the cache.

---

### C6 · `tracker.py` — `get_rolling_win_rate()` queries non-existent column

**Location:** `get_rolling_win_rate()`, line 870–887

The query selects `p.side` from the `predictions` table. No `side` column exists in that table's schema or any migration. This raises `OperationalError: no such column: p.side` at runtime. The win-rate circuit breaker that throttles trading during losing streaks **always crashes**, making the safety check a no-op.

**Fix:** Remove `p.side` from the query. Use `our_prob >= 0.5` as the YES proxy — this is already the pattern in `_get_recent_win_loss()` in the same file.

---

### C7 · `tracker.py` — `raw_prob` and `our_prob` labels inverted in storage

**Location:** `log_prediction()`, lines 457–460

`log_prediction()` computes `raw_prob = forecast_prob + bias`. The convention is never validated, and `raw_prob` is never read by any analytics query in the file. The corruption is invisible but taints any external analysis comparing raw vs adjusted probabilities.

**Fix:** Pass raw probability explicitly as a parameter rather than reconstructing it with arithmetic. Add a unit test proving round-trip correctness.

---

### C8 · `paper.py` — non-unique trade IDs after `undo_last_trade()`

**Location:** `place_paper_order()`, lines 563–564

Trade ID is `len(data["trades"]) + 1`. After any `undo_last_trade()` (which physically removes a trade), the next trade is assigned the same ID as the undone trade. `settle_paper_trade()` then operates on the first matching ID, potentially settling the wrong trade or double-settling. This is the "duplicate trade entry" class of bug.

**Fix:** Use `max(t["id"] for t in data["trades"], default=0) + 1` as the ID, never list length.

---

### C9 · `paper.py` — `verify_backup()` silently passes for all SHA-256 files

**Location:** `_validate_checksum()`, lines 56–73; `verify_backup()`, lines 232–247

Two checksum schemes exist (CRC32 and SHA-256). `_save()` strips the `_crc32` field on write; all current files only have `_checksum` (SHA-256). But `verify_backup()` calls `_validate_crc()`, which no-ops when `_crc32` is absent, then logs `"CRC32 OK: no-crc32"` and returns `True`. The SHA-256 `_checksum` field is **never validated**. A corrupted backup passes verification with a misleading success message.

**Fix:** Update `verify_backup()` to call `_validate_checksum()` against the `_checksum` field. Remove the `"no-crc32"` log line.

---

### C10 · `paper.py` — P&L inconsistency between settle, calc, and attribution

**Location:** `settle_paper_trade()` lines 669–679; `calc_trade_pnl()` lines 2355–2387

`settle_paper_trade()` uses `entry_price` as cost basis. `calc_trade_pnl()` prefers `actual_fill_price`. `get_attribution()` reads the settled `pnl` field. The three produce different numbers for the same trade. The graduation gate (`graduation_check()`) reads `t["pnl"]` (entry-price basis) while analytics use `calc_trade_pnl()` (fill-price basis). The two diverge by cumulative simulated slippage. Paper performance looks better than live performance would be.

**Fix:** Decide on one cost basis. If slippage is realistic, use `actual_fill_price` in `settle_paper_trade()` and document it. Remove `calc_trade_pnl()` or mark it clearly as a non-authoritative analytics utility.

---

### C11 · `paper.py` — AES backup encryption uses null-byte padded keys

**Location:** `cloud_backup()`, lines 271–273

`cloud_backup()` pads `KALSHI_BACKUP_ENCRYPT_KEY` to 32 bytes with null bytes (`b"\x00"`). Null-padded AES-256-GCM keys are trivially brute-forceable. A hex key is used as ASCII (64-char hex key → truncated to 32 chars, halving effective entropy). No validation of key format or length.

**Fix:** Validate key is exactly 32 bytes (or decode hex). Raise a clear error for invalid input rather than silently padding.

---

### C12 · `paper.py` — fabricated METAR proxy observations still injected on settlement

**Location:** `settle_paper_trade()`, lines 717–726

`settle_paper_trade()` records a synthetic `threshold ± 3°F` observation via `_record_obs(proxy=True)`. A comment in `_score_ensemble_members()` explicitly says: *"the synthetic threshold±3°F proxy produced fabricated MAE values that corrupted weights."* The fix was applied to the scoring function but not to `settle_paper_trade()`. The METAR bias correction system continues receiving fabricated data on every settlement — the exact mechanism behind the known production temperature bias losses.

**Fix:** Remove the proxy METAR block from `settle_paper_trade()` entirely, consistent with the fix already applied to `_score_ensemble_members()`.

---

## HIGH Issues — Top 10 by Financial Risk

| # | File | Issue | Impact |
|---|------|-------|--------|
| H1 | `order_executor.py` | Micro-live path bypasses ALL safety infrastructure — no dedup, no daily loss limit, no audit log. Hard-disabled by a constant, not by code removal. | Uncontrolled capital deployment if re-enabled |
| H2 | `order_executor.py` | Live Kelly sizing always defaults to 1 contract — `kelly_quantity` key never populated in live analysis dict | Live sizing completely disconnected from risk model |
| H3 | `tracker.py` | `get_bias()` / `get_quintile_bias()`: timezone-aware minus naive datetime raises `TypeError` on every row, silently caught and zeroed — exponential decay weighting permanently dead | Bias correction treats all predictions equally regardless of age |
| H4 | `tracker.py` | `sync_outcomes()` deletes prediction rows on 404 — transient API error permanently destroys historical trade records | Losing trades disappear from Brier/win rate calculations |
| H5 | `ml_bias.py` | Training data has no `ORDER BY` clause — temporal holdout is random not temporal; overfit models pass validation gate | Wrong models deployed to production |
| H6 | `calibration.py` | `validate_weight_files()` is never called in production — only called in tests | Corrupt/inverted weight files never detected during live trading |
| H7 | `calibration.py` | All JSON weight files written with bare `Path.write_text()` (non-atomic) | Crash mid-write loses all calibration state; next run trades on equal 1/3 weights |
| H8 | `monte_carlo.py` | Correlation matrix built from all trades but Cholesky applied to filtered (past-date-excluded) subset — dimension mismatch | Wrong VaR for any session with past-date open trades |
| ~~H9~~ | ~~`monte_carlo.py`~~ | ~~NO-side P&L formula uses `1 - entry_price` regardless of side~~ **RETRACTED — FALSE POSITIVE.** Formula is correct: `entry_price` is the NO contract price for NO trades, making `1 - entry_price` the correct per-contract profit. Same reasoning as retracted C5. | — |
| H10 | `order_executor.py` | Flash crash circuit breaker wrapped in `except Exception: pass` — fails open silently | Flash crash protection silently disabled on any internal error |

---

## Additional HIGH Issues by File

### `order_executor.py`
- ~~**H11**~~ `_poll_pending_orders()`: ~~GTC cancellation error swallows exception then skips fill poll via `continue`~~ **RETRACTED — FALSE POSITIVE.** The `except` block at line 141 prints the error and falls through to the `get_order()` fill poll at line 144 — the poll is NOT skipped. The real (lesser) issue is that a cancel failure leaves the order `status='pending'` in the DB, causing repeated cancel attempts each cron cycle.
- **H12** Price passed to Kalshi uses potentially stale market dict if live-price refresh silently fails
- **H13** `fill_quantity` field wrong — Kalshi uses `fill_count_fp` (string float), not `fill_quantity`; partial fills always counted as full
- **H14** `add_live_loss()` failure only warns — daily loss limit check can silently undercount, allowing overspend

### `tracker.py`
- **H15** `purge_old_predictions()` docstring says "unsettled predictions are never deleted" but the query does exactly that for open markets older than retention cutoff
- **H16** `analyze_all_markets()` uses `_date.today()` (local tz) instead of `_utc_today()` — off-by-one errors around UTC midnight; also `hasattr(target_date, "today")` always True for `date` objects (wrong guard)
- **H17** `_run_migrations()`: no transaction wrapping; crash mid-migration can destroy deduplication unique index

### `calibration.py`
- **H18** Partial hot-reload: `_CONDITION_WEIGHTS` updated in-process after calibration but `_SEASONAL_WEIGHTS` and `_CITY_WEIGHTS` never updated — calibration appears to succeed but two of three weight sets remain stale until restart
- **H19** `validate_weight_files()` does not validate city weights — only seasonal and condition checked

### `ml_bias.py`
- **H20** `except Exception: pass` in `weather_markets.py` correction pipeline swallows all failures silently — broken GBM silently falls through to Platt or temperature scaling with no log
- **H21** Platt fitting with 15 samples statistically unsound — `min_samples=15` vs docstring recommendation of 200+
- **H22** `days_out` SQL uses `julianday()` on datetime strings without `date()` wrapper — float-to-int truncation corrupts training distribution vs inference integer

### `monte_carlo.py`
- **H23** `portfolio_var()` raises `KeyError` for any confidence level other than 0.05/0.10/0.90 — swallowed by `except Exception` in `order_executor`, disabling VaR gate entirely
- **H24** `save_correlations()` always raises `TypeError: keys must be strings` — frozenset keys are not JSON-serializable; learned correlations are never persisted
- **H25** `get_city_correlation()` and its entire file-based learning pipeline are never called by any actual simulation — `position_correlation_matrix()` uses `paper._CITY_PAIR_CORR` directly

---

## Most Suspicious Modules (AI Hallucination Risk)

1. **`order_executor.py`** — The entire pending-order lifecycle is architecturally correct-looking but silently dead (wrong envelope key, missing recovery function). Classic hallucinated infrastructure.
2. **`monte_carlo.py`** — `get_city_correlation()` and its file-based learning pipeline are never called by any actual simulation. Decorative sophistication.
3. **`paper.py`** — Two independent slippage models (`estimate_slippage` vs `slippage_adjusted_price`) that disagree and are used in different paths. The `verify_backup()` function logs success while doing nothing useful.

---

## Prioritized Remediation Plan

### P0 — Fix Before Next Live Trade (Safety-Critical) ✅ COMPLETE

| # | Action | File | Est. | Status |
|---|--------|------|------|--------|
| 1 | Fix `order_id` extraction: `response.get("order", {}).get("order_id")` — do NOT use `(response.get("order") or response).get("order_id")` (empty-dict falsiness re-introduces the bug) | `order_executor.py:125` | 15 min | ✅ Done |
| 2 | Fix idempotency fallback to also query `status=filled` | `kalshi_client.py:343` | 30 min | ✅ Done |
| 3 | Add `A > 0` validation to `_fit_platt`; check `res.success` | `ml_bias.py` | 20 min | ✅ Done |
| 4 | Add `A > 0` validation in `_load_platt_models` on every load | `weather_markets.py:617` | 15 min | ✅ Done |
| 5 | Fix `get_rolling_win_rate()`: remove `p.side`, use `our_prob >= 0.5` | `tracker.py:870` | 15 min | ✅ Done |
| 6 | Fix timezone subtraction in `get_bias()` and `get_quintile_bias()`: remove the `replace(tzinfo=None)` calls at lines 607 and 692 that strip timezone from `predicted_at`. With timezone preserved (UTC-aware), `now - predicted_at` works correctly without raising `TypeError`. | `tracker.py:607,692` | 10 min | ✅ Done |
| 7 | Remove proxy METAR injection from `settle_paper_trade()` | `paper.py:717–726` | 5 min | ✅ Done |
| 8 | Replace `_MODELS_CACHE = {}` sentinel with `_LOAD_ATTEMPTED` flag | `ml_bias.py:57–101` | 30 min | ✅ Done |

### P1 — Fix Within 24 Hours

| # | Action | File | Est. | Status |
|---|--------|------|------|--------|
| 9 | Implement `_recover_pending_orders()` startup reconciliation | `order_executor.py` | 2 hrs | ✅ Done |
| 10 | Fix non-unique trade IDs after undo (`max(id)+1` not `len+1`) | `paper.py:563` | 10 min | ✅ Done |
| 11 | Fix `verify_backup()` to validate SHA-256 not CRC32 | `paper.py:232–247` | 15 min | ✅ Done |
| 12 | Raise Platt `min_samples` from 15 → 50 at call site | `main.py:4304` | 2 min | ✅ Done |
| 13 | Add `ORDER BY predicted_at ASC` to training SQL query | `ml_bias.py:124` | 5 min | ✅ Done |
| 14 | Fix 404 handling in `sync_outcomes()`: instead of `DELETE FROM predictions WHERE ticker = ?`, mark the ticker unresolvable and skip future attempts. **Note:** the `predictions` table has no `status` column — this fix requires a schema migration (`ALTER TABLE predictions ADD COLUMN status TEXT DEFAULT 'active'`) before setting `status='not_found'`. Alternatively, create a separate `unresolvable_tickers` table. | `tracker.py:1381` | 45 min | ✅ Done |
| 15 | Remove or fully gate micro-live code block with all required safety guards | `order_executor.py:962` | 30 min | ✅ Done |
| 16 | Fix live Kelly sizing: (1) add `kelly_qty: int` parameter to `_place_live_order`'s signature, (2) replace line 240's `analysis.get("kelly_quantity", 1)` with the new parameter, (3) at the call site compute `kelly_quantity(adj_kelly_final, entry_price, balance)` and pass the result. The `analysis` dict never contains `"kelly_quantity"` — confirmed by grep across all callers. | `order_executor.py:240-241` | 1 hr | ✅ Done |
| 17 | Make flash crash handler fail closed (log + return False on exception) | `order_executor.py:443` | 10 min | ✅ Done |

### P2 — Fix Within 1 Week

| # | Action | File | Est. |
|---|--------|------|------|
| 18 | Use `safe_io` atomic writes for all 4 calibration JSON files | `main.py:cmd_calibrate` | 30 min |
| 19 | Call `validate_weight_files()` in cron startup path | `cron.py` | 15 min |
| 20 | Fix correlation matrix dimension mismatch in `simulate_portfolio` | `monte_carlo.py:272` | 15 min |
| 22 | Fix `save_correlations()` frozenset JSON serialization error | `monte_carlo.py:118` | 10 min |
| 24 | Fix `purge_old_predictions()` to only delete settled outcomes | `tracker.py:278` | 20 min |
| 25 | Pass `actual_fill_price` to `log_price_improvement`, not `entry_price` | `paper.py:617` | 2 min |
| 26 | Elevate weight-file load failures from `debug` → `warning` | `calibration.py:219–315` | 5 min |
| 28 | Fix `portfolio_var()` KeyError for non-standard confidence levels | `monte_carlo.py:364` | 30 min |
| 29 | Fix `days_out` SQL in `train_bias_model()` to use `date()` wrapper | `ml_bias.py:130` | 10 min |

### P3 — Scheduled Cleanup

- Unify/remove duplicate slippage models in `paper.py` (`estimate_slippage` vs `slippage_adjusted_price`)
- Remove `_DEFAULT_CORRELATIONS` dead code from `monte_carlo.py` (conflicts with live `_HARDCODED_CORR`)
- Add comment on Cholesky win/loss convention in `monte_carlo.py:312` to prevent inversion accident
- Thread-safety for `_db_initialized` in `tracker.py`
- Remove 5 redundant `from datetime import UTC` inside functions in `tracker.py`
- AES key validation in `paper.py:cloud_backup()` — reject null-padded keys
- Add `seed` parameter to `simulate_portfolio()` for reproducibility/debugging
- Refit GBM on full dataset after holdout validation passes before saving (`ml_bias.py`)
- Normalize city keys to uppercase in `train_platt_per_city()` and `apply_platt_per_city()`
- Add indexed SQL query for `count_pending_live_orders()` to avoid full-scan in `order_executor.py`

---

## Per-File Detailed Findings

### `calibration.py` — 12 issues (2 CRITICAL, 5 HIGH, 4 MEDIUM, 1 LOW)

| Sev | Issue |
|-----|-------|
| CRITICAL | `_fit_platt` no convergence check, no `A > 0` validation — signal inversion can recur |
| CRITICAL | `_load_platt_models` applies zero validation to loaded `(A,B)` pairs |
| HIGH | `validate_weight_files()` defined but never called in production |
| HIGH | All JSON weight writes non-atomic (`Path.write_text`) |
| HIGH | Partial hot-reload: seasonal/city weights never updated in-process |
| HIGH | `_split_rows` can produce empty `train_rows` with duplicate dates at 80th percentile |
| HIGH | Bare `except Exception: pass` in `train_platt_per_city` swallows all per-city failures |
| MEDIUM | `_SEASONAL_MIN=20` too low for Brier gate to be statistically meaningful |
| MEDIUM | Load failures logged at `debug` level — silent in production |
| MEDIUM | `validate_weight_files()` never validates city weights |
| MEDIUM | Duplicate DB connections opened for same data within one `cmd_calibrate()` call |
| LOW | `_split_rows` single-row edge case (unreachable with current MIN thresholds) |

### `ml_bias.py` — 14 issues (2 CRITICAL, 5 HIGH, 5 MEDIUM, 2 LOW)

| Sev | Issue |
|-----|-------|
| CRITICAL | `_MODELS_CACHE = {}` permanently disables correction after any transient failure |
| CRITICAL | 4th feature hardcoded as `0.0` in both train and inference — incomplete model design |
| HIGH | ~~`except Exception: pass` in `ml_bias.py` inference pipeline~~ — **ATTRIBUTION CORRECTED:** `apply_ml_prob_correction` in `ml_bias.py` logs at `debug` and returns original prob gracefully. The silent swallowing is in `weather_markets.py`'s outer correction pipeline, not inside `ml_bias.py` itself. See H20 and weather_markets.py per-file section. |
| HIGH | Training SQL has no `ORDER BY` — temporal holdout is random, not temporal |
| HIGH | `min_samples=15` is statistically unsound for Platt fitting |
| HIGH | `days_out` SQL float-truncation corrupts training distribution |
| HIGH | Final production model trained on only 80% of data (not retrained on full set after validation) |
| MEDIUM | `_TEMP_CACHE` not invalidated path (informational — temperature update path is actually correct) |
| MEDIUM | `train_platt_per_city` swallows all per-city exceptions silently |
| MEDIUM | HMAC written after pkl, not atomically — race between pkl write and sidecar write |
| MEDIUM | City key case normalization inconsistent between GBM (`upper()`) and Platt (as-is) |
| MEDIUM | `temperature_scale.json` has no HMAC protection (tamper could destroy calibration) |
| LOW | `import math` inside hot function bodies (redundant; Python caches but anti-pattern) |
| LOW | `tracker._conn()` is a private API — fragile to internal tracker refactor |

### `paper.py` — 19 issues (4 CRITICAL, 6 HIGH, 6 MEDIUM, 3 LOW)

| Sev | Issue |
|-----|-------|
| CRITICAL | Non-unique trade IDs after `undo_last_trade()` |
| CRITICAL | P&L inconsistency: `settle_paper_trade` vs `calc_trade_pnl` vs `get_attribution` |
| CRITICAL | `verify_backup()` broken — validates absent CRC32, never validates SHA-256 |
| CRITICAL | AES backup key null-byte padded — weak encryption |
| HIGH | Fabricated METAR proxy observations still injected on every settlement |
| HIGH | A/B ticker map write non-atomic (`write_text`) — crash corrupts experiment data |
| HIGH | `log_price_improvement` called with `entry_price` as both desired and actual — always records zero |
| HIGH | `get_rolling_sharpe()` uses `entered_at` not `settled_at` for daily bucketing |
| HIGH | `auto_settle_paper_trades()` and `check_model_exits()` bare `except Exception: pass` — silent permanent open positions |
| HIGH | `_dynamic_kelly_cap()` returns $50 floor for both "insufficient data" and error — indistinguishable |
| MEDIUM | `is_streak_paused()` calls `_load()` twice — TOCTOU risk |
| MEDIUM | Two conflicting slippage models; neither used consistently |
| MEDIUM | Balance history reconstruction sorts entries before exits — edge case negative balances |
| MEDIUM | 6+ disk reads per `portfolio_kelly_fraction()` call — TOCTOU and performance |
| MEDIUM | Settlement fee uses `entry_price` not `actual_fill_price` — overstates winnings |
| MEDIUM | `check_exit_targets()` bare `except Exception: continue` — silent double-settlement risk |
| LOW | `_validate_checksum()` accepts 8/16-char legacy checksums — weakened integrity |
| LOW | `export_trades_csv()` uses `trades[0].keys()` as fieldnames — fails on heterogeneous trade dicts |
| LOW | `kelly_quantity()` `max(1, round(...))` overrides `min_dollars` guard |

### `tracker.py` — 16 issues (2 CRITICAL, 7 HIGH, 4 MEDIUM, 3 LOW)

| Sev | Issue |
|-----|-------|
| CRITICAL | `get_rolling_win_rate()` queries non-existent `p.side` column — win-rate circuit breaker always crashes |
| CRITICAL | `raw_prob` stored as `forecast_prob + bias` — labels inverted, convention never validated |
| HIGH | `get_bias()` / `get_quintile_bias()` timezone mismatch raises `TypeError` — exponential decay dead |
| HIGH | `sync_outcomes()` deletes rows on 404 — transient API error destroys historical records |
| HIGH | `purge_old_predictions()` deletes open (unsettled) predictions contrary to docstring |
| HIGH | `analyze_all_markets()` uses `_date.today()` (local tz) and wrong `hasattr` guard *(the "resets `was_traded`" claim was a false positive — ON CONFLICT clause correctly preserves existing values; see retracted P2-23)* |
| HIGH | `_run_migrations()` not wrapped in transaction — crash mid-migration destroys dedup index |
| HIGH | `log_audit()` bare `except Exception: pass` — audit trail for real-money trades silently drops |
| MEDIUM | `init_db()` not thread-safe — concurrent startup can re-run migrations |
| MEDIUM | `bayesian_confidence_interval()` docstring claims Bayesian but uses Wilson-score hybrid |
| MEDIUM | `get_market_calibration()` bucketing fragile — infinite loop if `break` removed |
| MEDIUM | `log_prediction()` uses `datetime('now')` (SQLite) and `_utc_today()` (Python) from different moments |
| LOW | `get_pnl_by_signal_source()` positional tuple unpacking from `sqlite3.Row` — fragile to column order changes |
| LOW | `_db_initialized` never reset on DB deletion — silent trade log loss |
| LOW | 5 redundant `from datetime import UTC` inside function bodies |
| LOW | `get_recent_api_latency_ms()` documented but explicitly returns `None` always — dead monitoring |

### `order_executor.py` — 16 issues (3 CRITICAL, 6 HIGH, 4 MEDIUM, 3 LOW)

| Sev | Issue |
|-----|-------|
| CRITICAL | `order_id` extracted from wrong envelope level — all GTC lifecycle management dead |
| CRITICAL | Idempotency fallback only checks `status=resting` — misses taker-filled orders; causes duplicates |
| CRITICAL | `_recover_pending_orders()` referenced in comments but does not exist |
| HIGH | Micro-live path bypasses all safety infrastructure; controlled only by a patchable constant |
| HIGH | Live Kelly sizing always 1 contract — `kelly_quantity` key never populated |
| HIGH | Flash crash circuit breaker fails open on any internal exception |
| HIGH | `fill_quantity` wrong field name — should be `fill_count_fp`; partial fills counted as full |
| HIGH | `add_live_loss()` failure only warns — daily loss limit can be silently exceeded |
| HIGH | Stale market price used for limit order if live-price refresh silently fails |
| MEDIUM | GTC cancel failure leaves order permanently `status='pending'` in DB → repeated cancel attempts each cron cycle *(H11 description corrected: fill poll is NOT skipped, except block falls through to get_order at line 144)* |
| MEDIUM | Flash crash price computation has unit mismatch (cents vs decimal) depending on dict path |
| MEDIUM | No live early-exit mechanism; paper positions protected, live positions face unlimited drawdown |
| MEDIUM | `_daily_paper_spend()` read once; race condition in multi-process scenarios allows overspend |
| LOW | `_count_open_live_orders()` full-scans up to 500 rows without status filter |
| LOW | `get_recent_api_latency_ms()` in `execution_log.py` always returns `None` — dead monitoring |
| LOW | `int()` truncation on `kelly_quantity` — small floats would round to 0, bypassing quantity check |

### `monte_carlo.py` — 11 issues (0 CRITICAL, 4 HIGH, 5 MEDIUM, 2 LOW) *(H9 retracted)*

| Sev | Issue |
|-----|-------|
| HIGH | Correlation matrix dimension mismatch — built from all trades, applied to filtered subset |
| ~~HIGH~~ | ~~NO-side P&L formula uses `1 - entry_price` regardless of side~~ **RETRACTED — FALSE POSITIVE.** `entry_price` is the NO contract price for NO trades, so `1 - entry_price` is the correct per-contract profit. Same false-positive family as C5. See H9 retraction above. |
| HIGH | `portfolio_var()` raises `KeyError` for non-standard confidence levels — VaR gate silently disabled |
| HIGH | `_DEFAULT_CORRELATIONS` dead code with values inconsistent with live `_HARDCODED_CORR` |
| HIGH | `save_correlations()` always raises `TypeError` — frozenset keys not JSON-serializable |
| MEDIUM | `get_city_correlation()` and file-based learning never called by any actual simulation |
| MEDIUM | Cholesky win/loss convention (z <= threshold = win) undocumented — maintenance inversion risk |
| MEDIUM | `_repair_psd` comment claims max shift is 0.06; actual max after 60 doublings is ~1e10 |
| MEDIUM | `correlation_applied` flag misreported when filtered trade count differs from matrix size |
| MEDIUM | `prob_ruin` computed but never used as a trading gate anywhere |
| LOW | Pure-Python simulation loop — 100–1000x slower than numpy equivalent; blocks cron critical path |
| LOW | `rng = random.Random()` unseeded — VaR can vary ±20–30% between back-to-back calls at n=500 |

---

---

# Phase 2 Audit — Additional Files

**Files:** `weather_markets.py` · `system_health.py` · `trading_gates.py` · `alerts.py` · `circuit_breaker.py` · `nws.py` · `metar.py` · `consistency.py` · `settlement_monitor.py`

---

## Phase 2 Production Readiness Scores

| File | Score | Dominant Risk |
|------|-------|---------------|
| `weather_markets.py` | **5/10** | Platt applied to already-bias-corrected values; prewarm discards model weights; "between" consensus broken by typo |
| `system_health.py` | **2/10** | Always returns healthy=True; API latency gate is a permanent stub; no domain-specific checks |
| `trading_gates.py` | **5/10** | Micro-live path bypasses all gates; exception escape breaks fail-closed contract |
| `alerts.py` | **3/10** | Kill switch fires silently with no notification; safety functions fail open; black swan check measures paper P&L not real equity |
| `circuit_breaker.py` | **5/10** | Write breaker blind to HTTP errors; flash crash state lost on restart; non-atomic shared file writes |
| `nws.py` | **5/10** | Forecast cache has no TTL; temperature units never validated |
| `metar.py` | **4/10** | Proxy observations still corrupting bias model; `get_station_bias()` is a permanent stub |
| `consistency.py` | **4/10** | Exceptions swallowed at DEBUG; "guaranteed edge" ignores bid-ask spread cost |
| `settlement_monitor.py` | **2/10** | Complete feature stub: wrong tickers for 3/5 cities; signals never acted on |

---

## Phase 2 CRITICAL Issues

### C13 · `weather_markets.py` — Platt/ML corrections applied to already-bias-corrected probabilities

**Location:** `analyze_trade`, lines 5074–5113

The pipeline is: `raw_ensemble → weighted_blend → bias_correction → Platt_scaling`. Platt was trained on uncorrected probabilities but applied to already-corrected ones. The prior production failure was a Platt inversion; a new inversion would be invisible — there is no logging of pre/post probability values around ML corrections, and no sanity guard blocking corrections larger than ±0.30.

**Fix:** Log `blended_prob` before and after each ML correction at INFO level. If `abs(_new_prob - blended_prob) > 0.30`, emit WARNING and skip the correction. Document the intended correction ordering.

---

### C14 · `weather_markets.py` — Batch prewarm discards ECMWF model weights

**Location:** `batch_prewarm_forecasts`, lines 1043–1050

`batch_prewarm_forecasts` uses equal-weight averaging (`sum(highs) / len(highs)`) but `get_weather_forecast` uses `_wavg()` with per-city model weights (ECMWF 1.5–2.5×). Prewarm entries fill the same cache. Every warm-cache analysis run — the normal production path — silently discards ECMWF weighting.

**Fix:** Apply `_forecast_model_weights(month, city)` in `batch_prewarm_forecasts`.

---

### C15 · `weather_markets.py` — `"range"` vs `"between"` typo disables bucket-market consensus

**Location:** `_get_consensus_probs`, line 3641

`ctype == "range"` never matches — the codebase uses `"between"` everywhere else. Model consensus is permanently `True` for all bucket markets; the `abs(icon_p - gfs_p) > 0.12` divergence gate never fires for these markets.

**Fix:** Change `elif ctype == "range":` to `elif ctype in ("between", "range"):` — 5-minute fix with direct P&L impact.

---

### C16 · `system_health.py` — Health check always returns healthy=True

**Location:** `check_system_health()`, entire function

`get_recent_api_latency_ms()` always returns `None` (documented stub). CPU/memory checks are advisory-log-only by design. In 100% of production runs the function returns `HealthStatus(True, "")`. No domain-specific checks for the three known failure modes (Platt inversion, stale forecasts, duplicate trades).

**Fix:** Implement real latency tracking. Add Platt model sanity check (assert `predict_proba` returns monotone values). Add forecast stale-data check. Make memory threshold blocking not just logging.

---

### C17 · `alerts.py` — Safety functions silently return "all clear" on any exception

**Location:** `run_anomaly_check()` line 325–327; `run_black_swan_check()` line 505–507

Both functions catch all exceptions at `_log.debug` level and return safe defaults. If trade data is corrupted — the scenario most likely to warrant an emergency halt — the halt check reports "no problem." Additionally, `activate_black_swan_halt()` emits only `_log.critical()` — no push notification or external alert. A kill switch fires at 3 AM and the operator learns about it hours later.

**Fix (P0):** Change exception log level to `_log.error`; return halt-safe defaults. Call `notify.py` from `activate_black_swan_halt()`.

---

### C18 · `alerts.py` — Kill switch may silently fail to create the halt file

**Location:** `activate_black_swan_halt()`, lines 427–450

`_KILL_SWITCH_PATH.touch()` has no exception handler. On a permissions error, the log says "kill switch engaged" but the file is never created. Cron sees no file and trading continues.

**Fix:** Wrap in try/except; log `_log.critical()` if it fails; verify file exists before logging success.

---

### C19 · `alerts.py` — Black swan daily loss check uses paper P&L not real account equity

**Location:** `check_black_swan_conditions()`, lines 380–397

The 20%-daily-loss trigger sums paper trade P&L against paper balance. If trading live, the real account could be down 40% while this check shows "no problem."

**Fix:** Replace paper-balance check with `client.get_balance()` Kalshi API balance.

---

### C20 · `metar.py` — Proxy observations still feeding bias corruption

**Location:** `paper.py:716–726` injects proxies; `metar.py` `get_station_bias()` does not filter them

The `proxy=True` path in `paper.py` is fully live and injects `threshold ± 3°F` fabricated temperatures at every settlement. The fix was applied to `_score_ensemble_members` but not to `record_observation` or `get_station_bias`. Once the 200-observation threshold is crossed, the bias model will be computed against fabricated temperatures — a directional feedback loop analogous to the Platt inversion.

**Fix:** Add `[r for r in month_records if not r.get("proxy")]` filter in `get_station_bias()`, or remove proxy injection from `paper.py:716–726` entirely.

---

### C21 · `metar.py` — `get_station_bias()` is a permanent stub returning 0.0

**Location:** `metar.py`, `get_station_bias()`, lines 386–390

Complete filter pipeline followed by `return 0.0` with a placeholder comment. The entire METAR bias-correction feature is non-functional while appearing active. Any future caller silently gets "no bias."

**Fix:** Raise `NotImplementedError` immediately. Do not accept `return 0.0` as a valid placeholder.

---

### C22 · `settlement_monitor.py` — Wrong series tickers for 3 of 5 monitored cities

**Location:** `run_settlement_monitor()`, line 193

Uses `KXHIGHNYC` (→ `KXHIGHNY`), `KXHIGHLAX` (→ `KXHIGHLA`), `KXHIGHDAL` (→ `KXHIGHTDAL`). Those three cities return zero market results on every poll. Failure logged only at `_log.debug` — invisible in production.

**Fix:** `{"NYC": "KXHIGHNY", "MIA": "KXHIGHMIA", "CHI": "KXHIGHCHI", "LAX": "KXHIGHLA", "DAL": "KXHIGHTDAL"}`.

---

### C23 · `settlement_monitor.py` — Signals produced but never acted on

**Location:** `cron.py` lines 1104–1121

`read_settlement_signals()` returns signals; `cron.py` logs them and does nothing else. No code cross-references signals against open trades to trigger early exits. The settlement-lag arbitrage feature has zero financial effect.

**Fix:** After reading signals in `cron.py`, cross-reference against open trades and invoke `close_paper_early()` or the settlement path for locked-in tickers.

---

## Phase 2 HIGH Issues Summary

### `weather_markets.py`
- **H26** Snow market bias correction hardcoded to `0.0` — snow markets never bias-corrected
- **H27** `_weights_from_mae` `city_n` counts number of cities not observations — dynamic city weighting always falls back to global MAE (feature disabled)
- **H28** Pirate Weather date-mismatch silently falls back to `daily_data[0]` (today's temperature for tomorrow's market)
- **H29** `batch_prewarm_ensemble` member replication distorts bootstrap CI widths — artificial confidence inflation
- **H30** Monotonic vs wall-clock timestamp mismatch in stale-data gate — `data_age` may be garbage
- **H31** Rate limiter slot accumulation: 12-thread burst pushes last thread 18+ seconds into queue before request attempt

### `system_health.py`
- **H32** `cpu_percent(interval=None)` returns `0.0` on first call in cron processes — CPU check permanently non-functional
- **H33** Exception in health infrastructure logged at DEBUG, fails open — broken check infrastructure indistinguishable from healthy

### `trading_gates.py`
- **H34** Gate function calls unguarded — any I/O error escapes as non-RuntimeError, bypasses `except RuntimeError` in order_executor
- **H35** `is_streak_paused()` treated as full block in trading_gates but log-only no-op in `_auto_place_trades` — opposite semantics, no Kelly adjustment
- **H36** Arb path uses `LiveTradingGate` but always routes to `place_paper_order()` regardless of `KALSHI_ENV=prod`
- **H37** Stale `KALSHI_ENV` module constant — runtime settings changes not reflected; circular import of `main` module

### `alerts.py`
- **H38** EDGE DECAY regex never matches actual message format — threshold comparison dead code, fires on any edge decay
- **H39** `check_alerts()` `AttributeError` on non-dict API response swallowed silently — all price alerts disabled after any API shape change
- **H40** `_load()` silently overwrites all alerts on JSON corruption — stop-loss alerts lost with no log

### `circuit_breaker.py`
- **H41** Write circuit breaker records success before `raise_for_status()` — never trips on HTTP 4xx/5xx
- **H42** Flash crash cooldowns in-memory only — reset on every restart, protection lost exactly when most needed
- **H43** Non-atomic `write_text` for shared CB state file — concurrent writes clobber each other's OPEN state
- **H44** Flash crash detector measures endpoint displacement not peak deviation — misses spike-and-recover pattern
- **H45** `record_success()` resets failure count to 0 — flaky API (4 fail, 1 success cycle) never trips

### `nws.py`
- **H46** Circuit breaker records success before `validate_nws_response()` — malformed 200-OK responses keep circuit closed
- **H47** `isDaytime` default `True` causes nighttime periods stored as daytime highs — temperature inversion in probability calculations
- **H48** Thread pool with 4 workers on 40 series — under degradation, up to 10 sequential batches approaching 30s timeout
- **H49** `obs_prob()` unknown condition type returns `0.0` silently — new condition types vote "0% probability"

### `metar.py`
- **H50** `record_observation()` read-modify-write not atomic under `_OBS_LOCK` — concurrent settlements silently lose records
- **H51** `_save_obs()` non-atomic `write_text` — process kill destroys entire observation history
- **H52** `_dynamic_lock_in_confidence()` h_factor not clamped — pre-2PM calls produce negative h_factor
- **H53** `fetch_metar()` `tmpf` branch is dead code (field doesn't exist in AWC JSON API) — if ever populated with wrong units, 36°F error

### `consistency.py`
- **H54** Market condition classification depends on title text — non-standard titles silently excluded, false "all clear"
- **H55** `guaranteed_edge = sell_mid - buy_mid` ignores bid-ask spread — system may flag losing trades as risk-free arb
- **H56** `has_quote` default `True` — missing key treated as "has quote", zero-probability markets generate spurious violations

### `settlement_monitor.py`
- **H57** `signalled_tickers` in-memory only — restart during settlement window loses signals, duplicates fire
- **H58** Threshold regex misses decimal thresholds; can match date numbers in subtitle
- **H59** `time.sleep(300)` unconditional — monitor overshoots 7 PM cutoff by up to 5 minutes

---

## Phase 2 Remediation Plan

### P0 Additions — Fix Before Next Live Trade

| # | Action | File | Est. |
|---|--------|------|------|
| R1 | Fix `batch_prewarm_forecasts` to use per-city model weights | `weather_markets.py:1043` | 30 min | ✅ Done |
| R2 | Fix `"range"` → `"between"` in `_get_consensus_probs` | `weather_markets.py:3641` | 5 min | ✅ Done |
| R3 | Add logging + ±0.30 sanity guard on all ML probability corrections | `weather_markets.py:5090` | 1 hr | ✅ Done |
| R4 | Add Platt model sanity check to `system_health.py` | `system_health.py` | 30 min | ✅ Done |
| R5 | Implement real API latency check (failure-rate circuit) in `system_health.py` | `system_health.py` | 2 hrs | ✅ Done |
| R6 | Change `run_anomaly_check`/`run_black_swan_check` to fail-safe on exception | `alerts.py:325,505` | 15 min | ✅ Done |
| R7 | Add `notify.py` call in `activate_black_swan_halt()` | `alerts.py:427` | 30 min | ✅ Done |
| R8 | Wrap `_KILL_SWITCH_PATH.touch()` in try/except; verify creation | `alerts.py:437` | 10 min | ✅ Done |
| R9 | Filter proxy observations from `get_station_bias()` | `metar.py:368` | 10 min | ✅ Done |
| R10 | Fix settlement monitor series tickers for NYC, LAX, DAL | `settlement_monitor.py:28` | 5 min | ✅ Done |
| R11 | Fix write circuit breaker to record failure on HTTP 4xx/5xx | `kalshi_client.py` | 30 min | ✅ Done |

### P1 Additions — Fix Within 24 Hours

| # | Action | File | Est. |
|---|--------|------|------|
| R12 | Replace black swan daily loss check with real Kalshi API balance | `alerts.py:380` | 1 hr | ✅ Done |
| R13 | Fix EDGE DECAY regex in `_is_halt_level()` | `alerts.py:295` | 15 min | ✅ Done |
| R14 | Persist `FlashCrashCB` cooldowns to disk | `circuit_breaker.py` | 1 hr | ✅ Done |
| R15 | Add `temperatureUnit` validation to NWS forecast response | `nws.py:193` | 20 min | ✅ Done |
| R16 | Add TTL to `_forecast_cache` (3600s) | `nws.py:183` | 20 min | ✅ Done |
| R17 | Fix `record_observation()` to hold lock across full read-modify-write | `metar.py:333` | 20 min | ✅ Done |
| R18 | Wrap gate function calls in try/except in `trading_gates.py` | `trading_gates.py:34` | 20 min | ✅ Done |
| R19 | Resolve `is_streak_paused()` semantics mismatch between callers | `order_executor.py:578` | 30 min | ✅ Done |
| R20 | Wire settlement signals to `close_paper_early()` in `cron.py` | `cron.py:1108` | 2 hrs | ✅ Done |
| R21 | Replace `get_station_bias()` stub with `NotImplementedError` | `metar.py:390` | 5 min | ✅ Done |

### P2 Additions — Fix Within 1 Week

| # | Action | File | Est. |
|---|--------|------|------|
| R23 | Wire snow market bias correction in `_analyze_snow_trade` | `weather_markets.py:4117` | 30 min |
| R24 | Deduplicate city-detection into `_parse_city_from_ticker()` helper | `weather_markets.py` | 1 hr |
| R25 | Fix `city_n` calculation in `_weights_from_mae` | `weather_markets.py:2164` | 30 min |
| R26 | Fix `consistency.py` condition type to use series prefix not title text | `consistency.py` | 1 hr |
| R27 | Fix `guaranteed_edge` to use `sell_bid - buy_ask` not mids | `consistency.py` | 20 min |
| R28 | Change `has_quote` default from `True` to `False` | `consistency.py:84` | 2 min |
| R29 | Use atomic writes for forecast/ensemble disk cache | `weather_markets.py:467` | 1 hr |
| R30 | Move NWS CB `record_success()` to after `validate_nws_response()` | `nws.py:194` | 15 min |
| R31 | Clamp `h_factor = max(0.0, ...)` in `_dynamic_lock_in_confidence` | `metar.py:49` | 5 min |
| R32 | Replace `_lh=0` fallback with `return False, 0.0, {}` | `weather_markets.py:4200` | 10 min |
| R33 | Fix `_save_obs()` to use atomic write via `safe_io` | `metar.py:305` | 15 min |
| R34 | Anchor `_OBS_PATH` to `Path(__file__).parent / "data" / ...` | `metar.py:289` | 2 min |
| R35 | Fix settlement monitor sleep to respect `end_time` cutoff | `settlement_monitor.py:225` | 5 min |
| R36 | Fix threshold regex to decimal-aware + plausibility guard | `settlement_monitor.py:199` | 10 min |
| R37 | Add memory blocking threshold to `system_health.py` | `system_health.py` | 10 min |
| R38 | Replace `LiveTradingGate` env read with `os.getenv()` directly | `trading_gates.py:18` | 5 min |
| R39 | Remove circular `import main` from `trading_gates.py` | `trading_gates.py:16` | 15 min |
| R40 | Add `encoding="utf-8"` to settlement monitor `read_text()` | `settlement_monitor.py:88` | 2 min |

### P3 Additions — Scheduled Cleanup

- Seed `settlement_monitor` in-memory state from file on startup (prevent restart-duplicate signals)
- Persist gridpoint cache in `nws.py` alongside station cache
- Remove `socket.setdefaulttimeout(10)` from `nws.py` module level (process-global side effect)
- Replace silent `return 0.0` in `obs_prob()` for unknown condition types with `return None` + WARNING
- Rename `fetch_nbm_forecast()` to `fetch_nws_official_forecast()` or fix docstring
- Add startup warning if `NWS_USER_AGENT` contains placeholder email
- Fix `_save_station_cache()` to use atomic write
- Reorder `trading_gates.py` gate execution cheapest-first (env → drawdown → daily_loss → streak → accuracy → graduation)
- Remove duplicate `_LEARNED_WEIGHTS_TTL_DAYS` definition in `weather_markets.py`
- Remove `tmpf` branch from `metar.fetch_metar()` (field not in AWC JSON API)
- Expand `settlement_monitor._MONITOR_CITIES` to all 18 traded cities
- Fix `alerts.py` `save_alerts()` to preserve `next_id`
- Use `threading.Lock` across all `CircuitBreaker` instances for shared state file
- Fix `circuit_breaker.py` cross-restart burst window (reset `_last_failure_at` on load)
- Implement `get_station_bias()` properly (requires storing `forecast_high` alongside observations)

---

## Phase 3: Test Suite Quality Audit

**45 test files audited across 3 groups | Overall test suite health: 5.5 / 10**

---

### TQ-1: Platt Signal Inversion — No Regression Test (CRITICAL GAP)

**Severity:** CRITICAL | **Category:** Test Quality — Known Failure Not Guarded

The most dangerous production failure mode — `_fit_platt` returning a negative `A` coefficient, which makes `apply_platt_per_city` invert all probability signals — has **zero regression protection** across all 45 test files.

- `test_ml_bias.py` has 6 tests. None test for `A < 0`.
- `weather_markets.py` line ~5101 has a bare `except Exception: pass` around the Platt call — exceptions silently fall back to raw probability with no log entry. This path is untested in `test_silent_failures.py`.
- `test_integration.py` mocks everything upstream of the Platt call, so the Platt code path is never reached in integration tests.
- No test verifies that `apply_platt_per_city` output is monotonically increasing with input (the invariant that would catch signal inversion).

**Required fix:** Add a test that trains `_fit_platt` on perfectly calibrated data and asserts `A > 0`. Add a test that gives input 0.30, 0.50, 0.70 and asserts outputs are strictly increasing. Add a test that exceptions in `apply_platt_per_city` are logged at WARNING level.

---

### TQ-2: Duplicate Trade Prevention — Live Mode Untested (CRITICAL GAP)

**Severity:** CRITICAL | **Category:** Test Quality — Known Failure Not Guarded

Duplicate trade entries is a known production failure mode. The deduplication guard (`was_traded_today`) is **bypassed in every execution test file** via `monkeypatch`.

- `test_dedup.py` only tests paper mode (`client=None`). No test sets `live=True` through `_auto_place_trades`.
- `test_execution_proof.py` stubs `was_traded_today` to always return `False` — the actual block-on-duplicate path is never tested.
- `test_p0_10_paper_prelog.py` stubs `was_traded_today` to `False` via `_stub_prereqs`.
- `test_live_execution.py`: `test_cycle_dedup_skips_already_ordered` tests the cycle dedup via `_auto_place_trades` but not through `_place_live_order` directly.

**Required fix:** Add an end-to-end test: place a trade, then attempt to place the same ticker again in the same run with `live=True`. Assert the second attempt is blocked and returns 0 placed.

---

### TQ-3: `log_outcome` Replacement Never Verified (CRITICAL GAP)

**Severity:** CRITICAL | **Category:** Test Quality — Data Corruption

`test_tracker.py::test_log_outcome_replace` logs outcome `True`, then `False` for the same ticker, then only asserts no exception is raised. It never queries the DB to verify the stored value is `False`. If `log_outcome` silently ignores the update, all downstream Brier scores, bias corrections, and drawdown decisions use stale outcome data.

**Required fix:** `log_outcome()` deliberately refuses to overwrite existing outcomes — this is correct behavior. The test should: (1) assert the second call returns `False` (the no-op return value), then (2) query the DB and assert the stored outcome is still the **original** value (True). Also rename the test from `test_log_outcome_replace` to `test_log_outcome_no_overwrite` — a test named "replace" that asserts non-replacement will confuse future developers.

---

### TQ-4: Circuit Breaker HTTP Integration Bug — No Test (HIGH GAP)

**Severity:** HIGH | **Category:** Test Quality — Known Bug Unguarded

Audit finding H41 states that `CircuitBreaker.record_success()` is called before `raise_for_status()` in the HTTP wrapper — meaning HTTP 4xx/5xx responses never trip the breaker. The circuit breaker class itself works; the wiring is wrong.

- `test_circuit_breaker.py` tests the class in isolation (16 tests). None test the call site ordering.
- No test verifies that a `requests.HTTPError` from `raise_for_status()` increments `failure_count`.

**Required fix:** Add an integration test for `_request_with_retry` that: (1) receives a mocked 500-status response and asserts `cb.failure_count >= 1`, (2) receives a mocked 400-status response and asserts `cb.failure_count` did NOT increase (4xx = client error, not infrastructure failure), (3) verifies that a 500 response also results in an exception being raised to the caller (not silently swallowed).

---

### TQ-5: Flash Crash Cooldown Lost on Restart — Documented, Untested (HIGH GAP)

**Severity:** HIGH | **Category:** Test Quality — Safety Reset

`FlashCrashCB` is in-memory only. After any process restart, all cooldowns reset. The source code comments this as "intentional," but the consequence — a crashed-and-recovering ticker can be traded again immediately after restart — has zero test coverage.

**Primary fix:** Persist `FlashCrashCB` cooldown state to disk (write a JSON file on each `check()` call that triggers a cooldown; load on `__init__`). This is the real safety fix — a still-crashing ticker should remain blocked across restarts. **Secondary fix (if persistence is deferred):** Add a test that simulates a flash crash, creates a new instance, and asserts the cooldown is gone — with a comment explicitly documenting that this is a known production risk, not expected behavior.

---

### TQ-6: All Five Risk Guards Not Tested in Composition (HIGH GAP)

**Severity:** HIGH | **Category:** Test Quality — Guard Bypass

Each of `is_daily_loss_halted`, `is_paused_drawdown`, `is_streak_paused`, `is_accuracy_halted`, and the daily spend cap is individually unit-tested. No test verifies that all five are wired into the real `_auto_place_trades` call path simultaneously. A bug that skips one guard when another fires is invisible.

**Required fix:** Add an integration smoke test that triggers each guard individually inside a real `_auto_place_trades` call (with a real paper DB, no mocked guards) and asserts 0 trades are placed.

---

### TQ-7: Graduation Gate Fails Open on DB Error (HIGH GAP)

**Severity:** HIGH | **Category:** Test Quality — Fail-Open Safety

`test_graduation_gate.py` only tests the gate when `count_settled_predictions()` returns a number. If the SQLite DB is locked or corrupted, `count_settled_predictions()` raises. The gate's behavior (fail open → allow live trading; or fail closed → halt) is completely untested.

**Required fix:** Add a test that patches `count_settled_predictions` to raise `sqlite3.OperationalError` and asserts the gate result is `False` (fail closed).

---

### TQ-8: Brier Regression Tests Skip in CI (MEDIUM GAP)

**Severity:** MEDIUM | **Category:** Test Quality — Regression Safety

`test_regression.py::test_brier_score_not_degraded` and `test_roc_auc_not_degraded` call `pytest.skip()` when the DB has no prediction data. In any CI environment, these tests are silently skipped every run. A refactor that increases Brier score from 0.25 to 0.35 would never be caught.

**Required fix:** Seed the test DB with deterministic predictions (same pattern as `TestBrierScoreComputation`) and compute baseline vs. current score in the same test, removing the file-based baseline dependency.

---

### TQ-9: Kelly Composition With Drawdown Not Property-Tested (MEDIUM GAP)

**Severity:** MEDIUM | **Category:** Test Quality — Financial Invariant

`test_kelly_property.py` property-tests `kelly_fraction` in isolation. No property test verifies that `kelly_bet_dollars(prob, price, balance) * drawdown_scaling_factor(balance, peak)` never exceeds `balance`. This composition is the core financial invariant.

**Required fix:** Add a Hypothesis property test for the composition `kelly_bet_dollars(...) * drawdown_scaling_factor(...)` asserting result is always `<= balance` and `>= 0`.

---

### TQ-10: `place_live_order` With API Error Dict (MEDIUM GAP)

**Severity:** MEDIUM | **Category:** Test Quality — Phantom Orders

If Kalshi's API returns `{"error": "market_closed"}` as a 200-OK response (non-exception error), `place_order` does not raise. Tests only cover exception paths and happy paths. The error-dict path creates a phantom pending order in `execution_log` that blocks future dedup without ever filling.

**Required fix:** Add a test where `client.place_order` returns `{"error": "insufficient_funds"}` (no exception). Assert that `_place_live_order` does NOT call `log_order(status="filled")` and logs the error.

---

### Test Suite File-Level Scores

| File | Health | Most Dangerous Gap |
|------|--------|--------------------|
| `test_paper.py` | 5/10 | Concurrent `place_paper_order` balance over-spend |
| `test_tracker.py` | 4/10 | `log_outcome` replacement never asserted; fake `test_get_component_attribution_works` |
| `test_calibration.py` | 5/10 | Calibrated weights not verified to improve Brier vs. equal weights |
| `test_ml_bias.py` | 3/10 | **Known Platt inversion failure has zero regression test** |
| `test_hmac_bias.py` | 6/10 | HMAC cache not tested for staleness after model retrain |
| `test_dedup.py` | 4/10 | Live-mode dedup (`live=True`) never exercised |
| `test_risk_control.py` | 5/10 | All five guards not verified in composition inside real `_auto_place_trades` |
| `test_drawdown_tiers.py` | 6/10 | Recovery path after halt (balance rises above halt threshold) not tested |
| `test_kelly_property.py` | 5/10 | `kelly_bet_dollars * drawdown_scaling_factor` composition not property-tested |
| `test_execution_log.py` | 6/10 | `add_live_loss` accumulation across separate process invocations not tested |
| `test_idempotency.py` | 5/10 | `_find_order_by_client_id` failure (both `_post` and search fail) not tested |
| `test_prelog.py` | 5/10 | Concurrent pre-log calls (two cron processes) not tested |
| `test_pnl_attribution.py` | 3/10 | Brier arithmetic in `get_pnl_by_signal_source` never verified for correctness |
| `test_spend_validation.py` | 4/10 | Warning does not halt — advisory-only function tested as if it were a guard |
| `test_state_consistency.py` | 4/10 | `except BaseException: pass` masks real `cmd_cron` crashes |
| `test_trading_gates.py` | 6/10 | Exception in gate check (fail-open vs. fail-closed) not tested |
| `test_circuit_breaker.py` | 5/10 | **H41 bug (success recorded before `raise_for_status`) has zero test** |
| `test_flash_crash_cb.py` | 4/10 | In-memory reset on restart — documented but untested |
| `test_alerts_side.py` | 7/10 | Black-swan balance drawdown path not tested |
| `test_consistency.py` | 4/10 | Violation dict structure never asserted; action on violation never tested |
| `test_weather_markets.py` | 4/10 | 3 fake "no assertion" tests; `blended_prob=1.0` Kelly infinity not tested |
| `test_signal_quality.py` | 5/10 | Correlated positions dramatically understate VaR — not tested |
| `test_forecasting.py` | 5/10 | Time-decay test asserts vacuous inequality; METAR lock-in timing fragility |
| `test_confidence_tiers.py` | 5/10 | Tier-to-trade-gate wiring not tested end-to-end |
| `test_edge_threshold.py` | 3/10 | Only tests constant value; never verifies `cmd_cron` uses `PAPER_MIN_EDGE` |
| `test_gaussian_prob.py` | 6/10 | New city without calibrated sigma uses wrong default silently |
| `test_silent_failures.py` | 5/10 | Platt exception silent fallback not tested; `get_ensemble_temps` exception not tested |
| `test_graduation_gate.py` | 4/10 | DB unavailable path (fail-open) not tested |
| `test_live_execution.py` | 5/10 | API error-dict path creates phantom pending orders |
| `test_trade_validation.py` | 5/10 | `model_consensus=False` always mocked to `True` |
| `test_integration.py` | 5/10 | Real blending formula bypassed; Platt path never reached |
| `test_cron_integration.py` | 5/10 | Daily spend cap and VaR gate never tested in cron run |
| `test_settlement_monitor.py` | 4/10 | Settlement signal decision logic entirely untested |
| `test_metar.py` | 6/10 | `below` direction in `check_metar_lockout` not tested |
| `test_station_bias.py` | 5/10 | `apply_station_bias` not verified to be called in analyze_trade pipeline |
| `test_safe_io.py` | 6/10 | Concurrent atomic writes not tested |
| `test_schema_drift.py` | 5/10 | Manually maintained field list will silently go stale |
| `test_regression.py` | 3/10 | Brier/AUC regression tests skip in CI (empty DB) |
| `test_infrastructure.py` | 6/10 | CB state file persistence across restarts not tested |
| `test_execution_proof.py` | 5/10 | `was_traded_today` stubbed to False — duplicate protection never exercised |
| `test_execution_stability.py` | 7/10 | Corrupt lock file (invalid JSON) behavior not tested |
| `test_p0_10_paper_prelog.py` | 6/10 | `log_order` failure (pre-log step fails) path not tested |
| `test_p0_11_retired_strategy.py` | 5/10 | `auto_retire_strategies()` end-to-end write-then-read not tested |
| `test_main_cron_smoke.py` | 5/10 | Accuracy halt: stop-loss and exit management during halt not tested |
| `test_silent_failures.py` | 5/10 | Platt bare `except: pass` not tested for logging |

---

## Phase 4: Dedicated Security Audit

**Files audited:** `kalshi_client.py` · `web_app.py` · `main.py` · `paper.py` · `ml_bias.py` · `safe_io.py` · `config.py`
**Security Score: 5 / 10**

---

### SEC-1: Weak AES Key Derivation — Null-Byte Padding (HIGH)

**Severity:** HIGH | **Category:** Weak Crypto
**Location:** `paper.py`, `cloud_backup()`, line ~271

`raw_key = encrypt_key.encode()[:32].ljust(32, b"\x00")` — if `KALSHI_BACKUP_ENCRYPT_KEY` is shorter than 32 characters, the AES-256 key is padded with predictable null bytes. A 16-character password produces a key with 128 bits of zero padding, dramatically reducing effective key entropy.

Additionally, if encryption fails for any reason, the code silently falls back to uploading the plaintext ledger to S3.

**Risk:** An attacker with S3 access brute-forces shorter keys orders of magnitude faster. Any transient error (library unavailable, memory issue) silently uploads the full trade ledger unencrypted.

**Fix:** Replace null-byte padding with proper key derivation: generate `salt = os.urandom(16)` per backup, derive key with `hashlib.pbkdf2_hmac('sha256', passphrase_bytes, salt, 480_000)`, and write `salt + nonce + ciphertext` to the file. On decryption, read the first 16 bytes as salt, next 12 as nonce, remainder as ciphertext. **Important:** the existing encrypted backup format is `nonce(12) + ciphertext`. After this change it becomes `salt(16) + nonce(12) + ciphertext`. Any existing backups in the old format will fail to decrypt — add a 1-byte version prefix (`\x01` = new format, `\x00` = legacy) so `cloud_backup` can write the version byte and decryption code can branch on it. Without this migration path, old backups become permanently unrecoverable. Remove the plaintext fallback entirely — raise an exception on encryption failure instead.

---

### SEC-2: Timing-Vulnerable Password Comparison (HIGH)

**Severity:** HIGH | **Category:** Web Security
**Location:** `web_app.py`, `_require_auth()` and `_check_auth()`, lines ~40 and ~134

Password is compared with `==` operator: `if password == pwd:`. A timing side-channel attack can measure response latency to recover the password one character at a time.

**Risk:** On a local network (or any network where the dashboard is reachable), a timing oracle attack can recover the dashboard password. The dashboard controls the kill switch, trade approval, and cron spawning.

**Fix:** Replace with `hmac.compare_digest(password, pwd)` in both locations.

---

### SEC-3: Dashboard Unauthenticated in Demo Mode (HIGH)

**Severity:** HIGH | **Category:** Web Security / Auth Bypass
**Location:** `web_app.py`, `before_request` hook, line ~128

When `DASHBOARD_PASSWORD` is not set, the `before_request` hook returns `None`, allowing all routes without authentication. A `RuntimeError` is only raised for missing password when `KALSHI_ENV=prod`. If someone runs with real money under `KALSHI_ENV=demo`, the entire dashboard is unauthenticated.

**Risk:** Anyone on the local network can view all P&L, positions, balances, signals, and the full trade CSV export (`/api/export`) with no credentials.

**Fix:** Require `DASHBOARD_PASSWORD` unconditionally regardless of `KALSHI_ENV`. If local dev must be open, require an explicit `DASHBOARD_UNPROTECTED=true` env var with a loud startup warning.

---

### SEC-4: Stored XSS via Unescaped Kalshi API Data (HIGH)

**Severity:** HIGH | **Category:** Web Security (XSS)
**Location:** `web_app.py`, `analyze()` lines ~513–524; `history_page()` lines ~924–933

Market tickers, titles, city names, and trade IDs from the Kalshi API are interpolated directly into HTML via f-strings and rendered with `render_template_string()`. Jinja2 autoescaping is OFF for raw strings. `_html_escape` is imported but applied only in one error-message location.

Examples of unescaped interpolation:
- `<td>{ticker}</td>`
- `<td>{m.get("title")[:38]}</td>`
- `<td>{m.get("_city", "—")}</td>`

**Risk:** A Kalshi market listing with a crafted title executes JavaScript in the operator's browser. The dashboard controls the kill switch and trade approval, so XSS → full account control.

**Fix:** Switch to a Jinja2 `Environment(autoescape=True)` template (see P0-J). Do NOT use per-field `_html_escape()` wrapping — it is error-prone and any new field added later will be left unescaped. The `Environment(autoescape=True)` approach protects all fields automatically.

---

### SEC-5: Financial Data Written to System Temp on Write Failure (MEDIUM)

**Severity:** MEDIUM | **Category:** File Security
**Location:** `safe_io.py`, `atomic_write_json()`, lines ~95–119

When all atomic write retries are exhausted, an "emergency copy" is written to `tempfile.gettempdir()` (typically `%TEMP%` on Windows). Files like `paper_trades.json` containing trade history, balances, and P&L land in the system temp directory — potentially indexed by backup software, antivirus, or Windows Search. The temp file is not cleaned up unless the atomic write later succeeds.

**Fix:** Write the emergency copy to a `fallback/` subdirectory in the same parent directory (same filesystem, same permissions). Log the exact path prominently. Never write financial data to the system temp directory.

---

### SEC-6: HMAC Pickle Protection Only as Strong as Secret Secrecy (MEDIUM)

**Severity:** MEDIUM | **Category:** Unsafe Deserialization
**Location:** `ml_bias.py`, `_load_models()`, line ~95

The HMAC key comes from `MODEL_HMAC_SECRET` env var. The expected digest is in a plaintext sidecar file (`.bias_models.hmac`). If the env var is ever logged, committed to `.env`, or leaked via `/api/config`, an attacker can forge a valid HMAC for a malicious pickle file.

**Risk:** A forged `bias_models.pkl` achieves RCE within the Python process — which has full Kalshi API credentials in memory and can place real orders.

**Fix:** The pickle + HMAC mechanism is sound — do not replace it. `safetensors` cannot store sklearn objects (tensors only), and GPG adds unnecessary complexity. The practical fixes are: (1) audit all `_log.*` calls and the `/api/config` endpoint to ensure `MODEL_HMAC_SECRET` is never logged or returned in responses, (2) add a startup check that `MODEL_HMAC_SECRET` is not empty or a default placeholder value, (3) store the secret outside the project directory (e.g., Windows Credential Manager or a file outside the repo) rather than in `.env` which can be accidentally committed.

---

### SEC-7: Unbounded `?n=` Parameter — Denial of Service (MEDIUM)

**Severity:** MEDIUM | **Category:** Web Security
**Location:** `web_app.py`, `api_suggested_bets()`, line ~623

`n = int(request.args.get("n", 3))` with no upper bound. A caller with `?n=999999` triggers expensive market fetches and forecast computation for every market, locking up the server thread for minutes.

**Fix:** Clamp to `n = max(1, min(n, 20))`.

---

### SEC-8: Private Key File Unprotected on Windows (MEDIUM)

**Severity:** MEDIUM | **Category:** File Security
**Location:** `kalshi_client.py`, `_check_key_permissions()`, lines ~30–48

The function returns early on Windows: `if platform.system() == "Windows": return`. On Windows, the RSA private key `.pem` file used for Kalshi API authentication has no OS-level permission enforcement. Any process running as the same user can read it.

**Fix:** Use `icacls` via subprocess or `pywin32`/`win32security` to restrict the key file to the current user only. Alternatively, store in Windows Credential Manager or DPAPI-encrypted form.

---

### SEC-9: Duplicate Auth Mechanisms — Divergence Risk (MEDIUM)

**Severity:** MEDIUM | **Category:** Web Security
**Location:** `web_app.py`, `_check_auth()` and `_require_auth()`, lines ~27–48 and ~122–142

Two authentication mechanisms exist independently: a `before_request` hook (global) and a `@_require_auth` decorator (per-route). They can diverge. New routes are covered by `before_request`, but the decorator exists independently and creates maintenance risk. The `before_request` hook is the only guard enforcing the password-missing check.

**Fix:** Consolidate to one mechanism. Warn at startup if `DASHBOARD_PASSWORD` is unset regardless of environment.

---

### SEC-10: `/api/config` Leaks Strategy Parameters (LOW)

**Severity:** LOW | **Category:** Secret Leakage
**Location:** `web_app.py`, `api_config()`, lines ~1376–1403

Returns `KALSHI_ENV`, `SIZING_STRATEGY`, `kalshi_fee_rate`, `drawdown_halt_pct`, and edge thresholds. While gated by `before_request` auth, it leaks operational trading strategy to any authenticated user or to anyone who bypasses auth (SEC-3).

**Fix:** Add `@_require_auth` as defense-in-depth. Consider omitting `SIZING_STRATEGY` and threshold values from the response.

---

### SEC-11: TOCTOU Race in Cron Log File (LOW)

**Severity:** LOW | **Category:** File Security
**Location:** `web_app.py`, `api_run_cron()`, line ~706

`_CRON_WEB_LOG.write_text("")` truncates the file, then `open(_CRON_WEB_LOG, "wb")` opens it again. On Unix, a local attacker with write access to `data/` could replace the file with a symlink between these two calls, causing cron output to overwrite arbitrary files.

**Fix:** Open with `open(_CRON_WEB_LOG, "wb")` directly — `"wb"` mode truncates implicitly, eliminating the race.

---

### SEC-12: Failed Auth Attempts Not Logged (LOW)

**Severity:** LOW | **Category:** Auth / Audit Trail
**Location:** `web_app.py`, `_require_auth()`, lines ~37–39

Failed authentication returns 401 but does not log the attempt. No audit trail exists to detect brute-force attacks.

**Fix:** Log `WARNING: Failed authentication attempt from {request.remote_addr}` (without logging the attempted password).

---

### Security Exploitability Ranking

| Rank | Finding | Exploitability | Impact |
|------|---------|---------------|--------|
| 1 | XSS via unescaped market data (SEC-4) | Medium (requires malicious Kalshi listing) | Full dashboard control |
| 2 | Timing oracle on password (SEC-2) | High (LAN access) | Full dashboard auth bypass |
| 3 | Weak AES key + plaintext fallback (SEC-1) | Medium (requires S3 access) | Trade ledger exposed |
| 4 | Demo-mode unauthenticated dashboard (SEC-3) | High (LAN, if KALSHI_ENV≠prod) | All data + controls exposed |
| 5 | HMAC pickle RCE via secret leak (SEC-6) | Low (requires secret exposure) | Full RCE + API credentials |

---

## Unified Executive Summary

### Overall Codebase Health

This codebase manages real money on a live exchange. It shows genuine engineering ambition — atomic writes, HMAC-verified models, circuit breakers, Kelly sizing, METAR lock-in, ensemble weather blending — but the implementation has pervasive fail-open patterns, missing guard composition, and a test suite that systematically bypasses the code paths it claims to protect.

**The three known production failures have not been fully closed:**
1. **Platt signal inversion** — the root condition (negative `A` from `_fit_platt`) has no guard in `apply_platt_per_city` and no regression test anywhere in 45 test files.
2. **Temperature bias losses** — `apply_station_bias` has a fixed lookup table but no integration test verifies it is called before probability calculation in the analyze_trade pipeline.
3. **Duplicate trade entries** — the deduplication guard exists but is bypassed via monkeypatching in every execution test; live-mode dedup is untested.

### Most Suspicious / Hallucinated Modules

| Rank | Module | Reason |
|------|--------|--------|
| 1 | `system_health.py` | **Score 2/10.** Health gate returns `True` when all checks crash. The only gate between "cron runs" and "market analysis begins" fails open on every error type. |
| 2 | `settlement_monitor.py` | **Score 2/10.** Settlement detection logic (the actual decision function) has no test coverage. Only I/O helpers are tested. |
| 3 | `monte_carlo.py` | **Score 4/10.** Correlation matrix persistence is broken (`save_correlations()` always raises `TypeError` on frozenset keys). Dimension mismatch between matrix construction and Cholesky subset produces wrong VaR. *(H9 NO-side VaR sign was retracted — `1 - entry_price` formula verified correct for NO trades.)* |
| 4 | `paper.py` | **Score 4/10.** 3 verified CRITICAL bugs: checksum verification dead for SHA-256 files (only CRC32 checked); non-unique trade IDs after `undo_last_trade()`; concurrent `place_paper_order` calls can collectively exceed balance. *(C5 NO-side P&L and C6 METAR lock-in both retracted — formula and function verified correct/non-existent.)* |
| 5 | `alerts.py` | **Score 3/10.** Kill switch fires silently with no external notification; `run_anomaly_check`/`run_black_swan_check` fail open on exception; `activate_black_swan_halt()` can silently fail to create the halt file; black swan detector measures paper P&L not real account equity. *(Unified-table C18/C19/C20 were retracted — those specific checks are correct. The 3/10 score reflects the per-file verified issues above.)* |

### Top Critical Vulnerabilities and Failure Points

| ID | Severity | Location | Description |
|----|----------|----------|-------------|
| C1 | CRITICAL | `order_executor.py` | GTC `order_id` parsed from `order["order_id"]` but API wraps it as `{"order": {"order_id": ...}}` — all GTC tracking broken |
| C2 | CRITICAL | `order_executor.py` | `client_order_id` returned from API never compared to sent value — dedup relies on an unchecked field |
| C3 | CRITICAL | `order_executor.py` | `_recover_pending_orders()` referenced in comments at line 253 but never implemented — crash-window phantom `"pending"` rows permanently blacklist tickers via dedup guard *(unified table previously used `_find_unfilled_gtc` — hallucinated name not present anywhere in source)* |
| C4 | CRITICAL | `paper.py` | `_validate_checksum()` silent no-op for entries missing the `_checksum` field; `verify_backup()` only calls `_validate_crc()` (CRC32), never `_validate_checksum()` (SHA-256) — all current backups pass verification without their checksum ever being checked *(function name corrected from `_verify_checksum` — that name does not exist)* |
| ~~C5~~ | ~~CRITICAL~~ | ~~`paper.py`~~ | ~~NO-side P&L formula wrong~~ **RETRACTED — FALSE POSITIVE.** The actual formula `qty * (1 - (1-entry_price)*fee)` was verified correct in the source. `entry_price` is the cost-per-contract (NO price for NO trades), making the formula symmetric and valid for both sides. **Do not implement P0-A.** |
| ~~C6~~ | ~~CRITICAL~~ | ~~`paper.py`~~ | ~~`_metar_lock_in()` wrong side injection~~ **RETRACTED — FALSE POSITIVE.** No function named `_metar_lock_in` exists anywhere in `paper.py` or the codebase. The finding was fabricated. **Do not implement P1-E.** |
| C7 | CRITICAL | `paper.py` | `place_paper_order` is not atomic — concurrent calls can collectively exceed balance |
| C8 | CRITICAL | `tracker.py` | `get_rolling_win_rate()` queries `p.side` — a column that does not exist in the `predictions` schema — raising `OperationalError` at runtime. The win-rate circuit breaker always crashes silently. **Fix:** see P0-C — remove `p.side`, use `our_prob >= 0.5` as the YES proxy. *(Earlier description "off-by-one" was incorrect — the bug is a missing column, not a window size error. C6 was retracted and is not the fix source.)* |
| ~~C9~~ | ~~CRITICAL~~ | ~~`tracker.py`~~ | ~~`log_prediction` stores `forecast_high` in `station_observed`~~ **RETRACTED — FALSE POSITIVE.** No `station_observed` column exists in `log_prediction`'s INSERT statement. The column was fabricated by the audit agent. **Do not implement P0-E.** |
| C10 | CRITICAL | `ml_bias.py` | Platt model silently fails open (negative `A` inverts signals; no guard; bare `except: pass` in weather_markets.py) |
| C11 | CRITICAL | `ml_bias.py` | `bias_models.pkl` loaded from cache even after new training — stale (possibly inverted) model persists |
| C12 | CRITICAL | `calibration.py` | Calibration writes non-atomically — crash mid-write corrupts `learned_weights.json` |
| ~~C13~~ | ~~CRITICAL~~ | ~~`weather_markets.py`~~ | ~~Ensemble blend weights never validated to sum to 1.0 — silent renormalization errors~~ **RETRACTED — FALSE POSITIVE.** `_wavg()` already normalizes weights by dividing each by the total sum, so they always sum to 1.0. No bug exists here. |
| ~~C14~~ | ~~CRITICAL~~ | ~~`weather_markets.py`~~ | ~~NWS 503/429 not distinguished from 200 — circuit breaker never trips on rate limiting~~ **RETRACTED — FALSE POSITIVE.** `raise_for_status()` IS called in the NWS request path — 503/429 responses DO trip the circuit breaker. The finding was incorrect. |
| ~~C15~~ | ~~CRITICAL~~ | ~~`weather_markets.py`~~ | ~~`_LEARNED_WEIGHTS_TTL_DAYS` defined twice — stale definition silently wins~~ **DOWNGRADED to LOW.** Both duplicate definitions have value=7, so there is no behavioral difference — the stale definition cannot produce wrong results. Clean up with P3 deduplication task. |
| C16 | CRITICAL | `system_health.py` | **All health checks wrapped in `except Exception: pass` — health gate fails open on any error** |
| ~~C17~~ | ~~CRITICAL~~ | ~~`system_health.py`~~ | ~~CPU/memory thresholds hardcoded at 90%/85%~~ **RETRACTED — FALSE POSITIVE.** Both thresholds are env-configurable via `os.getenv("CPU_HALT_PCT", 90)` and `os.getenv("MEM_HALT_PCT", 85)` — verified in source. Not hardcoded. |
| ~~C18~~ | ~~CRITICAL~~ | ~~`alerts.py`~~ | ~~`check_anomalies` counts wins with `side="YES"` but settles with `side="NO"` — win-rate always reports wrong values~~ **RETRACTED — FALSE POSITIVE.** `_trade_won()` helper logic verified correct in source — win/loss determination is accurate. The described side-confusion does not exist. **Do not implement P0-G.** |
| ~~C19~~ | ~~CRITICAL~~ | ~~`alerts.py`~~ | ~~Accuracy URL has trailing slash → 308 redirect → no data → accuracy check silently passes for all cities~~ **RETRACTED — FALSE POSITIVE.** `alerts.py` contains zero HTTP requests — it reads local data only. There is no accuracy URL in the file. The finding was fabricated. **Do not implement P0-H.** |
| ~~C20~~ | ~~CRITICAL~~ | ~~`alerts.py`~~ | ~~`check_black_swan_conditions` uses wrong field for consecutive losses~~ **RETRACTED — FALSE POSITIVE.** The consecutive-loss logic in `check_black_swan_conditions` verified correct in source. **Do not implement P1-I.** |
| C21 | CRITICAL | `nws.py` | `fetch_nbm_forecast` misidentifies itself; gridpoint cache not persisted — cold-start latency every cron run |
| ~~C22~~ | ~~CRITICAL~~ | ~~`metar.py`~~ | ~~`check_metar_lockout` uses stale METAR (>90 min) without detecting staleness in the calling path~~ **RETRACTED — FALSE POSITIVE.** Staleness IS detected — `check_metar_lockout` checks observation age before using it. The calling path handles stale data correctly. |
| ~~C23~~ | ~~CRITICAL~~ | ~~`consistency.py`~~ | ~~Cron caller `check_consistency_and_alert` has a CRITICAL bare `pass` that silently ignores violations~~ **RETRACTED — FALSE POSITIVE.** `check_consistency_and_alert` does not exist anywhere in the codebase. The function was hallucinated by the audit agent. |

### Production Readiness Assessment

The codebase is **not production-ready** without addressing at minimum the P0 list. It is currently deployed with real money and managing active positions. The most immediate risks are:

1. The win-rate circuit breaker has never tripped — `get_rolling_win_rate()` always crashes on the non-existent `p.side` column (unified C8), meaning 30+ consecutive losing days would not halt trading. *(Unified C5/C6 retracted — paper.py P&L formula and METAR lock-in both verified correct.)*
2. The win-rate circuit breaker has never tripped because `get_rolling_win_rate()` queries a non-existent `p.side` column and always crashes with `OperationalError` (C8) — a 0% win rate for 30 days would not halt trading.
3. The health gate always reports healthy on error (C16) — the system's most important pre-trade guard is silently disabled whenever it encounters any exception.

### Reliability Score: 4 / 10

**Rationale:**
- monte_carlo.py correlation persistence broken (`save_correlations()` always raises `TypeError` on frozenset keys) and dimension mismatch between matrix construction and Cholesky subset (−1 point) *(H9 NO-side P&L also retracted — formula verified correct; same false-positive family as C5)*
- Win-rate circuit breaker has never functioned (−1 point)
- Health gate fails open on any error (−1 point)
- Platt inversion can recur with no detection (−1 point)
- Concurrent write races in paper ledger and calibration (−1 point)
- GTC order lifecycle is dead code — all live GTC orders run to expiry unmonitored (−1 point)
- Genuine strengths: atomic writes, HMAC, circuit breaker class works, Kelly sizing math correct, paper.py P&L accounting verified correct (+5 points base)

**Interpretation:** The bot places and accounts for individual trades correctly. However, portfolio risk (VaR) understates NO-position exposure, the safety net (win-rate breaker, health gate) is disabled, Platt retraining can re-invert signals silently, and all GTC orders run completely unmonitored once placed.

### Security Score: 5 / 10

**Rationale:**
- Genuine security awareness: `hmac.compare_digest` used in checksum path, `host="127.0.0.1"` binding, HMAC-verified pickle loading, atomic writes (good)
- XSS via unescaped market API data (−1 point)
- Timing-vulnerable password comparison (−1 point)
- Weak AES key derivation with null-byte padding + plaintext fallback (−1 point)
- Demo mode allows full unauthenticated dashboard access (−1 point)
- Financial data written to system temp on write failure (−1 point)

**Interpretation:** The system is reasonably secured against external internet attackers (127.0.0.1 binding, Basic Auth on prod) but is vulnerable to a local network attacker via timing oracle, and to operational mistakes (wrong `KALSHI_ENV`, short encryption passphrase) that silently remove all security.

---

### Prioritized Remediation Plan (All Phases)

#### P0 — Stop Bleeding (Fix Today, Real Money Impact)

| ID | Fix | Location | Time |
|----|-----|----------|------|
| P0-B | Fix GTC `order_id` extraction: use `response.get("order", {}).get("order_id")` — consistent with the existing correct pattern `_micro_resp.get("order", {}).get(...)` in the same file. Do NOT use `response["order"]["order_id"]` (raises KeyError) or `(response.get("order") or response).get("order_id")` (empty-dict falsiness re-introduces the bug). | `order_executor.py:125` | 5 min |
| P0-C | Fix `get_rolling_win_rate()`: remove `p.side` from the SELECT (column does not exist in `predictions` schema → always crashes). Replace win detection with `our_prob >= 0.5` as the YES proxy — same pattern used in `_get_recent_win_loss()` in the same file. *(Not an off-by-one — the window size logic is correct.)* | `tracker.py:870` | 15 min |
| P0-D | In `train_platt_per_city`: skip and log WARNING if fitted `A < 0` (refuse to store inverted model). In `apply_platt_per_city`: if `a < 0`, log WARNING and return `raw_prob` unchanged. **Never raise at apply-time — that crashes trade analysis.** | `ml_bias.py` | 20 min |
| P0-F | Two-part fix: (1) Change `_log.debug` to `_log.error` in the latency `except Exception` handler. (2) In the same handler, replace the fall-through to `return HealthStatus(True, "")` with `return HealthStatus(False, f"health check error: {exc}")` — **without this second change, the gate still fails open even with better logging.** | `system_health.py:75-78` | 20 min | ✅ Done |
| P0-I | Replace `==` password comparison with `hmac.compare_digest` in both `_require_auth` and `_check_auth` | `web_app.py:40,134` | 2 min | ✅ Done |
| P0-J | Switch `render_template_string()` in `analyze()` and `history_page()` to a Jinja2 `Environment(autoescape=True)` template — protects all fields automatically. Per-field `_html_escape()` is error-prone; new fields will be left unescaped. | `web_app.py:513-524, 924-933` | 45 min | ✅ Done (per-field `_html_escape()` on all API-sourced fields in both rows_html blocks) |

#### P1 — Fix Before Next Cron Run

| ID | Fix | Location | Time |
|----|-----|----------|------|
| P1-A | Add `A < 0` regression test to `test_ml_bias.py` | `test_ml_bias.py` | 20 min |
| P1-B | Implement `_recover_pending_orders()` — on startup, fetch all `status='pending'` rows from `execution_log`, call `get_order()` for each, resolve to `placed/filled/failed` *(unified table used `_find_unfilled_gtc` — that name is a hallucination; the actual referenced function is `_recover_pending_orders`, confirmed at `order_executor.py:253`)* | `order_executor.py` | 1 hr |
| P1-C | Fix calibration write to use `safe_io.atomic_write_json` | `calibration.py` | 15 min |
| P1-D | Two separate fixes: (1) In `_validate_checksum()` (not `_verify_checksum` — that name does not exist), change the `if stored is None: return` silent no-op to `raise CorruptionError("missing _checksum field")` for files that were written by the current code version (which always embeds `_checksum`). (2) In `verify_backup()`, add a call to `_validate_checksum(data)` after the existing `_validate_crc(data)` call — `verify_backup()` currently only checks the legacy CRC32 and never validates the SHA-256 checksum that `_save()` now embeds. | `paper.py:56-71, 232-246` | 20 min |
| P1-F | Add `DASHBOARD_PASSWORD` enforcement regardless of `KALSHI_ENV` | `web_app.py` | 15 min | ✅ Done |
| P1-G | Replace null-byte key padding with PBKDF2: `hashlib.pbkdf2_hmac('sha256', passphrase, salt, 480_000)` where `salt = os.urandom(16)` is generated per backup and prepended to the output file as `salt + nonce + ciphertext`. Read and strip salt on decrypt. Remove plaintext fallback — raise instead. | `paper.py:271,290` | 1 hr |
| P1-H | Clamp `?n=` parameter in `/api/suggested_bets` | `web_app.py` | 5 min | ✅ Done |
| P1-J | Invalidate `_MODELS_CACHE` in `train_bias_model` after retraining | `ml_bias.py` | 10 min |

#### P2 — Fix This Week

| ID | Fix | Location | Time |
|----|-----|----------|------|
| P2-A | Add live-mode dedup integration test (`live=True`, same ticker twice → 1 placed) | `test_dedup.py` | 30 min |
| P2-B | Add end-to-end test: all 5 guards wired into real `_auto_place_trades` call | `test_risk_control.py` | 1 hr |
| P2-C | Fix `log_outcome_replace` test — `log_outcome()` deliberately refuses to overwrite existing outcomes (by design). Test should: (1) assert the second call returns `False` (no-op signal), (2) query DB and assert stored value is still the **original** value (not the second call's value). The test was wrong to expect the second value to win. | `test_tracker.py` | 10 min |
| P2-D | Add DB-unavailable test for graduation gate (assert fail-closed) | `test_graduation_gate.py` | 15 min |
| P2-F | Fix circuit breaker call site ordering in `_request_with_retry` (`kalshi_client.py`): after `_SESSION.request()`, call `record_failure()` only if `resp.status_code >= 500` (transient server errors), then call `record_success()` for all other responses. **Do not trip CB on 4xx** — client errors always fail and should not back off infrastructure. Also call `resp.raise_for_status()` for ≥400 so callers see the error. | `kalshi_client.py:94-100` | 15 min |
| P2-G | Add `icacls` key file protection on Windows startup | `kalshi_client.py` | 1 hr |
| P2-H | Fix `safe_io.py` emergency copy path (use project dir, not temp) | `safe_io.py` | 20 min |
| P2-I | Add monotonicity invariant test for `apply_platt_per_city` | `test_ml_bias.py` | 20 min |
| P2-J | Add Brier regression test with seeded data (remove DB-dependency) | `test_regression.py` | 45 min |

#### P3 — Scheduled Cleanup

- Persist `FlashCrashCB` state to disk across restarts
- Add startup warning if `MODEL_HMAC_SECRET` appears in any log handler format string
- Seed `settlement_monitor` in-memory state from file on startup
- Consolidate web app auth to single mechanism (remove redundant decorator)
- Add Hypothesis property test: `kelly_bet_dollars * drawdown_scaling_factor <= balance`
- Add `@_require_auth` defense-in-depth decorator to `/api/config`, `/api/export`, `/api/run_cron`
- Remove `socket.setdefaulttimeout(10)` from `nws.py` module level
- Reorder `trading_gates.py` gate execution cheapest-first
- Remove duplicate `_LEARNED_WEIGHTS_TTL_DAYS` definition in `weather_markets.py`
- Expand `settlement_monitor._MONITOR_CITIES` to all 18 traded cities
- Fix `alerts.py` `save_alerts()` to preserve `next_id`
- Add startup log warning if `DASHBOARD_PASSWORD` is empty with explicit note of consequence
