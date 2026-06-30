# Grade Audit — paper.py

**File:** `paper.py` (3073 lines)
**Grader model:** claude-sonnet-4-6
**Date:** 2026-06-29

---

## TIER 1 Functions

---

### `_load()` L:209–224  ★ T1

```
[paper.py] _load() L:209–224  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: ALL PASS
Red flag: NONE
Invariants: I2 PASS (lock is held by callers), I3 N/A (read-only)
STRENGTHS:
• Validates both legacy CRC32 and modern SHA-256 checksums on every read — two-layer corruption detection.
• Returns a fully-populated default dict when the file doesn't exist, so callers never see a KeyError on 'balance'.
• Auto-migrates missing _version field gracefully.
WEAKNESSES:
• line 211: Opens DATA_PATH without holding _DATA_LOCK. _load() is called from within locked sections, but it is also called from get_all_trades(), get_performance(), and _load()["trades"] patterns in get_current_streak(), is_streak_paused(), etc. where the caller does NOT acquire the lock first. The contract is "lock before calling _load()", but nothing in _load() itself enforces this, making it easy for new callers to accidentally race.
• line 216: Schema migration is a stub — only sets _version=1, does no actual field backfill for genuinely old records missing required keys.
FAILURE SCENARIO (score ≤7):
A caller reads _load() outside a lock (e.g. fear_greed_index() calls _load() directly at L:2362, get_performance() at L:1709, etc.). Two concurrent Flask threads could read an inconsistent snapshot.
VERDICT: keep as-is (lock contract works in practice; all critical paths are locked)
```

---

### `_save()` L:245–254  ★ T1

```
[paper.py] _save() L:245–254  ★ T1
Score: 9/10  |  Confidence: Confirmed
AC: ALL PASS
Red flag: NONE
Invariants: I2 PASS (all callers hold _DATA_LOCK), I3 PASS (delegates to atomic_write_json which uses os.replace())
STRENGTHS:
• Delegates to atomic_write_json which handles temp-file + os.replace() + WinError-32 retry — correct by delegation.
• Strips legacy _crc32 before embedding new SHA-256 _checksum, so old CRC32 fields don't survive the write.
• Logs at ERROR and re-raises on AtomicWriteError — operator cannot miss a write failure.
• Zero logic duplication with the underlying atomic writer.
WEAKNESSES:
• line 252: Catches (AtomicWriteError, RuntimeError) but not OSError. If the disk is full and atomic_write_json raises OSError, the error escapes uncaught and logs nothing at paper.py's level. (atomic_write_json itself logs, so this is minor.)
VERDICT: keep as-is
```

---

### `_drawdown_snapshot()` L:367–390  ★ T1

```
[paper.py] _drawdown_snapshot() L:367–390  ★ T1
Score: 9/10  |  Confidence: Confirmed
AC: AC2 PASS — adds back same-day costs inside a single _DATA_LOCK acquisition; excludes needs_manual_settle trades.
Red flag: NONE
Invariants: I2 PASS (lock acquired, data read, computation done, lock released — no gap)
STRENGTHS:
• Single _DATA_LOCK acquisition for both effective_balance and peak_balance — no TOCTOU between the two values.
• Excludes needs_manual_settle same-day trades from the add-back (archived markets never settle; they should not permanently inflate effective balance).
• Clear inline comment explaining WHY same-day costs are added back.
WEAKNESSES:
• line 382: The lock is acquired with `with _DATA_LOCK:` but then released before computations at L:383–390. This is not a bug for the sum() computation (which operates on data that's already a local variable), but the lock release at L:381 exit means a concurrent writer could modify DATA_PATH before the sum is computed. However, since data is already a local dict copy, the race cannot corrupt the result — this is safe.
• Minor: no log when same_day_locked > 0; operators cannot observe how much is being added back without enabling debug logging.
VERDICT: keep as-is
```

---

### `is_paused_drawdown()` L:418–427  ★ T1

```
[paper.py] is_paused_drawdown() L:418–427  ★ T1
Score: 9/10  |  Confidence: Confirmed
AC: AC3 PASS — uses _drawdown_snapshot(), not raw get_balance().
Red flag: NONE
Invariants: I2 PASS (delegates to _drawdown_snapshot() which is atomic), I8 PASS
STRENGTHS:
• Single responsibility: one comparison, one return.
• Delegates to _drawdown_snapshot() — effective balance and peak from the same consistent read.
• No side effects.
• Comprehensive test coverage (test_not_paused_at_start, test_paused_below_threshold, test_paused_drawdown_ignores_same_day_costs, TestDrawdownScalingFactor, TestHighWaterMark).
WEAKNESSES:
• No log line when returning True — operator cannot see the pause trigger without adding DEBUG logging or querying the state directly. (Score anchor 9 describes this exact pattern.)
VERDICT: keep as-is
```

---

### `drawdown_scaling_factor()` L:430–457  ★ T1

```
[paper.py] drawdown_scaling_factor() L:430–457  ★ T1
Score: 9/10  |  Confidence: Confirmed
AC: AC3 PASS — uses _drawdown_snapshot(), not raw get_balance().
Red flag: NONE
Invariants: I2 PASS (delegates to _drawdown_snapshot()), I8 PASS
STRENGTHS:
• Uses _drawdown_snapshot() for atomic effective_balance + peak read.
• Guards peak <= 0 → returns 1.0 (no division by zero).
• Tier constants are module-level absolutes with an ordering assertion at L:137-139 — verified once at import, never silently wrong.
• L:455: strict < on TIER_4 boundary (not <=) is explicitly commented.
• Full test suite: TestDrawdownScalingFactor (8 cases) + TestDrawdownTiersRelativeToHalt covers every tier boundary.
WEAKNESSES:
• The 5-tier step function creates discontinuous jump at 82% → 85% recovery (0.10 → 0.30 Kelly). A single winning trade crossing the TIER_2 boundary doubles Kelly instantly. Deliberate design, but no comment explaining the intent.
VERDICT: keep as-is
```

---

### `get_balance()` L:341–343  ★ T1

```
[paper.py] get_balance() L:341–343  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: ALL PASS (this is a read-only reporter; trading gates use _drawdown_snapshot())
Red flag: NONE
Invariants: I2 PASS (acquires _DATA_LOCK)
STRENGTHS:
• _DATA_LOCK protects the read — no race against a concurrent _save().
• Single responsibility.
• Used correctly: trading gates call _drawdown_snapshot(), not this function.
WEAKNESSES:
• Acquires _DATA_LOCK internally, then _load() opens the file. If called from inside an already-locked section (e.g. fear_greed_index() calls get_balance() at L:2375 while _DATA_LOCK is an RLock — reentrant, so this is safe), but the double-lock nesting is non-obvious. RLock is the correct choice here; the comment at L:87 explains it.
• Every call to get_balance() reads the entire JSON file from disk. High-frequency callers (dashboard, check_exit_targets loops) could incur unnecessary I/O. No cache layer.
VERDICT: keep as-is
```

---

### `get_peak_balance()` L:346–349  ★ T1

```
[paper.py] get_peak_balance() L:346–349  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: ALL PASS
Red flag: NONE
Invariants: I2 PASS (acquires _DATA_LOCK)
STRENGTHS:
• Acquires _DATA_LOCK — consistent with get_balance().
• Fallback to STARTING_BALANCE when peak_balance key is missing — safe for old records.
WEAKNESSES:
• Same disk-read-per-call issue as get_balance(). Both are called together frequently (e.g. get_max_drawdown_pct() calls both separately — two reads instead of one).
• No test directly exercises the STARTING_BALANCE fallback path (missing key in JSON).
VERDICT: keep as-is
```

---

### `graduation_check()` L:2276–2330  ★ T1

```
[paper.py] graduation_check() L:2276–2330  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: AC4 PASS — uses max_brier=0.23 (≤0.23 gate), not 0.20.
Red flag: NONE
Invariants: I1 — PASS. The Brier is computed by tracker.brier_score(last_n=50) which defaults to min_days_out=1 (multiday_predictions view). Same-day trades are excluded.
STRENGTHS:
• max_brier default is 0.23 (≤0.23) — correct per AC4 and module notes. The old 0.20 threshold is NOT present in the gate logic.
• Uses last_n=50 so old bad weeks age out naturally as new settlements accumulate.
• MIN_BRIER_SAMPLES guard (lifetime ≥ 30) protects against trusting Brier on tiny samples.
• Comment is exemplary — explains WHY the threshold changed and WHY last_n=50 is used.
• Returns None rather than raising when criteria are unmet — clean caller contract.
WEAKNESSES:
• line 2314: tracker.brier_score(last_n=50) uses the primary JOIN path (multiday_predictions + outcomes). If the tracker DB has no outcomes yet (early stage), it falls through to the paper-trades fallback in tracker.brier_score. That fallback applies days_out filtering via Python, not SQL — and treats days_out=None as multi-day (correct per known-intentionals). This is safe but subtle; no test exercises the fallback path through graduation_check specifically.
• No direct test for graduation_check(). The function is exercised indirectly through get_performance() but there is no test that calls graduation_check() with controlled Brier/PnL values and asserts it returns (or does not return) a dict.
FAILURE SCENARIO (score ≤7 would require direct test coverage gap per preamble):
The function passes all structural checks; the only gap is a missing dedicated test. Given the function is 55 lines with clear logic, the risk is low but non-zero.
VERDICT: keep as-is (add a direct test)
```

---

### `settle_paper_trade()` L:869–951  ★ T1

```
[paper.py] settle_paper_trade() L:869–951  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: AC1 PASS — entire read-modify-write cycle is within `with _DATA_LOCK:`.
Red flag: NONE
Invariants: I2 PASS (locked RMW), I4 — see weakness below
STRENGTHS:
• Holds _DATA_LOCK across load→modify→save — no TOCTOU window.
• Correctly handles YES/NO side payout: won = (side=='yes' AND outcome_yes) OR (side=='no' AND NOT outcome_yes).
• Fee applied to winnings only (1.0 - entry_price), not the full $1 payout — matches Kalshi's fee model.
• Updates peak_balance atomically inside the same locked section.
• Raises ValueError if trade not found or already settled — clean fail-fast.
• test_no_side_win_recorded_as_win and test_no_side_loss_recorded_as_loss cover the critical NO-side logic.
WEAKNESSES:
• line 869: I4 — The 24h settlement gate (close_time + 24h < now) is NOT checked here. Settlement of a trade can be triggered at any time by auto_settle_paper_trades(). The 24h gate is enforced by check_stop_losses() and check_breakeven_stops(), but NOT by settle_paper_trade() itself. For the auto-settle path, the gate lives in auto_settle_paper_trades() ... but actually, auto_settle_paper_trades() does NOT check close_time + 24h before calling settle_paper_trade(). It checks outcome availability (tracker outcome OR Kalshi finalized status), not timing. The preamble's I4 invariant says "All settlement paths check close_time + 24h < now". This is MISSING from settle_paper_trade() and from auto_settle_paper_trades().
• Confidence: Confirmed — traced the code path from auto_settle_paper_trades() through settle_paper_trade(); no 24h gate exists.
FAILURE SCENARIO:
A trade placed at 23:00 on day D closes at 23:00 on day D+1 (24h market). At 23:01 on day D, Kalshi finalizes the market early (unusual but possible). auto_settle_paper_trades() sees the finalized outcome, calls settle_paper_trade() immediately — the trade settles within 1 hour of placement. The 24h invariant is violated.
In practice, Kalshi high-temperature markets settle after midnight following the target date, so the violation window is narrow. But the memory note says "24h settlement gate added to all 3 exit mechanisms" — this may have been intended to be here.
VERDICT: fix before live (add close_time gate to auto_settle or settle_paper_trade for production)
```

---

### `add_paper_trade()` — NOTE: This function does not exist in the file. The placement function is `place_paper_order()`. See grading below.

---

### `place_paper_order()` L:667–866  ★ T1

```
[paper.py] place_paper_order() L:667–866  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: AC1 PASS — _DATA_LOCK.acquire() at L:715, released in finally: at L:809.
Red flag: NONE
Invariants: I2 PASS (explicit acquire/release with finally), I5 N/A (Kelly is applied upstream by kelly_bet_dollars; this function receives pre-computed quantity/price)
STRENGTHS:
• Validates side, entry_prob, entry_price before touching the lock.
• Checks daily loss halt before acquiring the lock.
• Duplicate-open-position guard (L:747-757) prevents TOCTOU orphans from a cleared execution log.
• Single-ticker exposure cap enforced (L:728-734) before cost deduction.
• MIN_ORDER_COST guard (L:720-724).
• balance check before deduction (L:736-740).
• Trade record is fully populated with all audit fields (city, days_out, close_time, via_kill_switch_override).
• Latency warning at L:811-820 when MAX_ORDER_LATENCY_MS exceeded.
• Lock released in finally: block — safe even on exception.
WEAKNESSES:
• line 864: A/B test update at L:838-865 is wrapped in `except Exception: pass` — silent swallow. If the A/B state write fails (disk full, race), it is lost without a WARNING log. RF1 boundary: the outer try/except catches all exceptions silently. The A/B tracking is non-critical, but the pattern is bad.
• line 822-836: log_price_improvement call after lock release. If it raises, the exception propagates to the caller. The surrounding `except Exception as _e: _log.warning(...)` catches it, so this is fine.
• The is_daily_loss_halted() check at L:709 is outside the lock — a concurrent trade could race past this check before the balance deduction at L:806. This is a TOCTOU on the daily loss limit (minor, as the worst case is one extra trade on the day the limit fires).
• line 800-803: Gaussian fill noise is applied to actual_fill_price but cost is still deducted as entry_price * quantity (L:718+806). The slippage-adjusted actual_fill_price is stored for analytics but does NOT affect balance accounting. This is intentional (per P1-8 comment) but means paper P&L does not reflect slippage costs.
FAILURE SCENARIO:
A/B test exception at L:864 is swallowed silently — `except Exception: pass` with no log. If atomic_write_json fails for the ticker map, the variant assignment is lost and the A/B experiment produces biased data. Not a money-loss scenario, but a data corruption scenario.
VERDICT: fix before live (add WARNING log in the bare `except Exception: pass` at L:864)
FIX: paper.py:864 — replace `except Exception: pass` with `except Exception as _e: _log.warning("place_paper_order: A/B test update failed: %s", _e)`
```

---

### `reset_peak_balance()` L:460–484  ★ T1

```
[paper.py] reset_peak_balance() L:460–484  ★ T1
Score: 9/10  |  Confidence: Confirmed
AC: AC5 PASS — raises ValueError unless confirmed=True; no stdin input is used.
Red flag: NONE
Invariants: I2 PASS (with _DATA_LOCK holds entire RMW)
STRENGTHS:
• confirmed=True guard prevents accidental calls — ValueError is clear and descriptive.
• Holds _DATA_LOCK across load→modify→save — atomic.
• Logs the reset at INFO with reason — operator knows it happened and why.
• Returns new_peak so the caller can confirm the value.
• test_reset_peak_sets_to_current_balance + test_reset_peak_requires_confirmed give full coverage.
WEAKNESSES:
• line 477: Sets peak to data["balance"] (raw balance), not effective_balance. If large same-day positions are open, the raw balance understates the true capital, and the new peak will be set below effective balance. After settlement, peak could jump up, triggering a false "recovery". Minor because reset is a manual admin operation.
VERDICT: keep as-is
```

---

### `get_edge_realization_rate()` L:1782–1909  ★ T1

```
[paper.py] get_edge_realization_rate() L:1782–1909  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: AC6 PASS — multiday_directional_accuracy is computed separately (L:1827-1837) filtering days_out IS NULL OR days_out >= 1 (effectively same logic as multiday_predictions view). Same-day trades with days_out=0 are excluded.
Red flag: NONE
Invariants: I1 — PASS. Uses get_all_trades() (intentionally unfiltered per known-intentionals), but same-day separation is done in Python via the days_out filter at L:1828.
STRENGTHS:
• Two separate accuracy metrics: directional_accuracy (natural settlement only) and multiday_directional_accuracy (multi-day only, natural settlement). Clean separation.
• Pearson correlation computed from scratch in pure Python — no numpy dependency.
• Bucket analysis at 5 edge ranges provides calibration signal.
• Returns early dict (n<5) with all keys present — callers never see KeyError.
• Comment at L:1826-1830 clearly explains WHY same-day is excluded from multiday_directional_accuracy.
WEAKNESSES:
• line 1828: `(_dout := t.get("days_out")) is None or _dout >= 1` — walrus operator in a list comprehension. Trades with days_out=None (legacy, pre-column) are included in multiday_natural. This is intentional (matches tracker.brier_score fallback behavior) but the walrus operator form is hard to read cold without the comment.
• No test directly asserts multiday_directional_accuracy excludes days_out=0 trades. The key is checked via cron.py which reads the dict, but no paper-level unit test asserts the filtering logic.
• get_all_trades() at L:1804 does NOT hold _DATA_LOCK — it calls _load() directly. This is a read-only operation and get_all_trades() is on the known-intentionals list, so it is not flagged. However, the list returned could be stale vs a concurrent write.
VERDICT: keep as-is
```

---

## TIER 2 Functions

---

```
[paper.py] _validate_crc() L:31–42  8/10 — Validates CRC32 checksum; no-op when absent, raises CorruptionError on mismatch; clean backward-compat guard.  [Confidence: C]
```

```
[paper.py] _compute_checksum() L:45–53  8/10 — SHA-256 over sorted JSON keys; deterministic, constant-time input; correct use of sort_keys=True.  [Confidence: C]
```

```
[paper.py] _validate_checksum() L:56–73  8/10 — Constant-time comparison via hmac.compare_digest; accepts legacy lengths 8/16/64; raises CorruptionError on mismatch.  [Confidence: C]
```

```
[paper.py] cleanup_temp_files() L:227–242  7/10 — Removes stray atomic-write temp files; OSError on unlink silently swallowed (acceptable for cleanup utility).  [Confidence: C]
```

```
[paper.py] verify_backup() L:257–276  8/10 — Validates both CRC32 and SHA-256; logs at ERROR on failure; returns bool. Clean.  [Confidence: C]
```

```
[paper.py] cloud_backup() L:279–338  6/10 — S3 upload with AES-GCM encryption option; temp enc file cleaned in finally; encryption failure logs WARNING and falls back to plaintext upload (debatable: should probably abort on enc failure for a trading ledger). Bare `except Exception` on S3 upload logged at WARNING — acceptable for backup.  [Confidence: C]
FIX: Consider aborting on encryption failure rather than uploading plaintext — encrypted backup that silently degraded to plaintext defeats the purpose.
```

```
[paper.py] get_state_snapshot() L:352–364  7/10 — Point-in-time snapshot for cron logging; calls get_balance(), get_open_trades(), get_peak_balance() separately — three disk reads instead of one, no lock across all three (snapshot is not atomic). Acceptable for logging.  [Confidence: C]
```

```
[paper.py] get_effective_balance() L:393–402  8/10 — Thin wrapper over _drawdown_snapshot()[0]; correct delegation, no lock gap. Good.  [Confidence: C]
```

```
[paper.py] get_max_drawdown_pct() L:405–415  8/10 — Intentionally uses raw get_balance() (reporting metric, per AC3 exception and known-intentionals). Guarded against peak <= 0. Good.  [Confidence: C]
```

```
[paper.py] _dynamic_kelly_cap() L:487–512  7/10 — Returns $50 conservative cap when < MIN_BRIER_SAMPLES; scales from $200-$500 on Brier tiers. Bare `except Exception: return 50.0` at L:511 is RF1 boundary — swallowed silently with no log. Should log at WARNING when falling back.  [Confidence: C]
FIX: paper.py:511 — replace `except Exception: return 50.0` with `except Exception as e: _log.warning("_dynamic_kelly_cap: falling back to $50 conservative cap: %s", e); return 50.0`
```

```
[paper.py] _method_kelly_multiplier() L:515–541  7/10 — Per-method Brier scaling; uses higher min-sample threshold (50 vs 30). Bare `except Exception: return 1.0` at L:541 is RF1 boundary — neutral fallback is safe but silent.  [Confidence: C]
FIX: paper.py:541 — add log at WARNING before return 1.0 in exception handler.
```

```
[paper.py] _city_kelly_multiplier() L:544–576  7/10 — Per-city Brier scaling with 4 tiers; returns 1.0 until MIN_CITY_SAMPLES=10. Bare `except Exception: return 1.0` at L:575-576 — silent neutral fallback.  [Confidence: C]
```

```
[paper.py] spread_kelly_multiplier() L:579–594  9/10 — Clean formula; handles spread<=0 and net_edge<=0 edge cases; floors at 0.5; full test coverage (TestSpreadKellyMultiplier 8 tests). Exemplary small function.  [Confidence: C]
```

```
[paper.py] kelly_bet_dollars() L:597–641  8/10 — Handles all three STRATEGY modes; applies drawdown scaling to all strategies (M-11 comment); applies streak pause; applies method multiplier; uses dynamic Brier cap. is_streak_paused() and drawdown_scaling_factor() each do a disk read — two separate reads not under a single lock. Minor staleness risk. Full test coverage (TestKellyCompounding, TestDrawdownScaling, test_kelly_bet_dollars_*). No I5 check here — Kelly fraction is passed in from caller; this function does not validate 0<p<1 itself, but the callers are responsible for that.  [Confidence: C]
```

```
[paper.py] kelly_quantity() L:644–664  8/10 — round() instead of int() prevents truncation-to-zero bug (L8-B comment); clamped to [1,100]; guards price <= 0 and dollars < min_dollars. Full test coverage.  [Confidence: C]
```

```
[paper.py] _score_ensemble_members() L:954–1000  7/10 — Reads settled_temp_f from tracker outcomes (correct — avoids METAR-at-settlement vs daily-high confusion); skips when NULL (returns early, will retry). Bare `except Exception` at L:976-979 and L:999 — swallowed silently with only a debug log. DB errors during scoring are quiet.  [Confidence: C]
```

```
[paper.py] close_paper_early() L:1003–1031  8/10 — Holds _DATA_LOCK across full RMW; updates peak_balance; raises ValueError on unknown id. Correct early-exit accounting (proceeds = exit_price * qty; pnl = proceeds - cost). Good.  [Confidence: C]
```

```
[paper.py] get_open_trades() L:1034–1036  7/10 — Acquires _DATA_LOCK; returns list comprehension. No I4 note needed (read-only). Fine. Returns a snapshot; concurrent modify after release won't affect the returned list.  [Confidence: C]
```

```
[paper.py] validate_paper_trades_integrity() L:1039–1071  7/10 — Checks duplicate IDs, balance drift formula, missing settled_at/pnl. The balance formula (STARTING_BALANCE + settled_pnl - open_cost) is correct but early_exit trades are included in settled_pnl since pnl is set for them too — correct. Holds _DATA_LOCK. Broad `except Exception` swallows any error and returns a diagnostic string — acceptable for an integrity check utility.  [Confidence: C]
```

```
[paper.py] check_stop_losses() L:1074–1142  7/10 — 24h gate via close_time enforced on EVERY trade; skips missing/unparseable close_time with WARNING (strict per I4 principle). Returns list of tickers, not settled directly. Missing close_time causes skip not crash. Full test coverage (TestCheckStopLosses 7 tests). One gap: if STOP_LOSS_MULT is None (not 0), the `if STOP_LOSS_MULT <= 0` check would raise TypeError. In practice STOP_LOSS_MULT comes from utils and is always a float.  [Confidence: C]
```

```
[paper.py] update_peak_profits() L:1145–1177  7/10 — Holds _DATA_LOCK across full RMW; only saves when changed (avoids unnecessary disk writes). Skips settled trades and trades with missing price data. Good.  [Confidence: C]
```

```
[paper.py] check_breakeven_stops() L:1180–1231  7/10 — Reads peak_profit_pct from trade dict (not a fresh load); 24h gate enforced; skips missing close_time with WARNING. Requires update_peak_profits() to have been called first — documented. Good.  [Confidence: C]
```

```
[paper.py] _exposure_denom() L:1234–1237  7/10 — Floors at STARTING_BALANCE so drawdown never loosens caps. Calls get_balance() which acquires _DATA_LOCK. Called from within locked sections (place_paper_order) where the lock is already held; RLock handles reentry correctly.  [Confidence: C]
```

```
[paper.py] get_city_date_exposure() L:1240–1247  7/10 — Calls get_open_trades() (locked) then _exposure_denom() (locked) — two separate lock acquisitions. No TOCTOU risk for a read-only metric, but two disk reads.  [Confidence: C]
```

```
[paper.py] get_directional_exposure() L:1250–1259  7/10 — Same pattern as get_city_date_exposure(); correct directional filtering. Good.  [Confidence: C]
```

```
[paper.py] get_total_exposure() L:1262–1265  7/10 — Simple sum / _exposure_denom(); two lock acquisitions (get_open_trades + _exposure_denom). Correct.  [Confidence: C]
```

```
[paper.py] get_ticker_exposure() L:1268–1271  7/10 — Correct filter; same two-lock pattern. Good.  [Confidence: C]
```

```
[paper.py] position_age_kelly_scale() L:1274–1293  7/10 — Falls back to 1.0 on date-parse errors; returns 1.0 when no existing position. MAX_POSITION_AGE_DAYS <= 0 guard prevents division-by-zero. Good.  [Confidence: C]
```

```
[paper.py] get_correlated_exposure() L:1296–1315  7/10 — Returns 0.0 for unrecognized cities; uses _exposure_denom() correctly. Good.  [Confidence: C]
```

```
[paper.py] check_exit_targets() L:1318–1353  6/10 — Bare `except Exception: continue` at L:1351 — RF1. Any error fetching or processing a market is silently swallowed. An API timeout, a bad market format, or a KeyError in close_paper_early would all be invisible. Should log at WARNING.  [Confidence: C]
FIX: paper.py:1351 — replace `except Exception: continue` with `except Exception as _e: _log.warning("check_exit_targets: error processing %s: %s", t.get("ticker"), _e); continue`
```

```
[paper.py] portfolio_kelly_fraction() L:1356–1429  7/10 — Clamps to remaining portfolio room (L3-A fix); directional penalty at >MAX_DIRECTIONAL_EXPOSURE; continuous correlated penalty; position age scaling; covariance scaling; city Brier scaling. Complex but each modifier is clearly named. Calls get_total_exposure()/get_city_date_exposure()/get_directional_exposure()/get_correlated_exposure() — many separate disk reads without a single lock; race condition possible for concurrent placement, but practical risk is low. Good test coverage (TestPortfolioKelly, L3-A tests).  [Confidence: C]
```

```
[paper.py] covariance_kelly_scale() L:1432–1487  7/10 — Portfolio Kelly covariance; clamps p to [0.01, 0.99]; skips same-city; defaults unknown pairs to 0.0 (not 0.10 — different from position_correlation_matrix's default of 0.10). This inconsistency is minor. Maps marginal_ratio linearly to [0.3, 1.0]. No test directly exercises covariance_kelly_scale() in isolation.  [Confidence: C]
```

```
[paper.py] portfolio_kelly() L:1490–1541  7/10 — Batch covariance Kelly for a list of positions; uses weather_markets.kelly_fraction; KELLY_CAP applied per position. No test directly exercises this function.  [Confidence: P]
```

```
[paper.py] position_correlation_matrix() L:1544–1587  8/10 — Symmetric matrix; date parsing has ValueError fallback; known city pairs from _CITY_PAIR_CORR; default 0.10 for unknown pairs; 0.0 when either city is absent. Full test coverage (TestPositionCorrelationMatrix 8 cases).  [Confidence: C]
```

```
[paper.py] corr_kelly_scale() L:1590–1607  8/10 — Builds full matrix with appended new trade; uses max absolute correlation; floor at 0.25. Full test coverage (TestCorrKellyScale 4 cases).  [Confidence: C]
```

```
[paper.py] slippage_kelly_scale() L:1610–1628  7/10 — Volume-based 4-tier multiplier; no test coverage. No system-critical path; used for sizing hints only.  [Confidence: P]
```

```
[paper.py] get_all_trades() L:1631–1632  7/10 — Intentionally unfiltered per known-intentionals. Calls _load() without _DATA_LOCK — deliberate since this is a reporting function. Acceptable.  [Confidence: C]
```

```
[paper.py] load_paper_trades() L:1635–1637  7/10 — Alias for get_all_trades(). Fine.  [Confidence: C]
```

```
[paper.py] get_portfolio_expected_value() L:1640–1675  7/10 — Correct formula (cost * net_edge); handles missing net_edge as 0.0; guards total_cost > 0. Reasonable for a reporting function.  [Confidence: C]
```

```
[paper.py] get_sameday_band_stats() L:1678–1704  7/10 — Correctly filters days_out==0; acquires _DATA_LOCK. The band extraction at L:1699 (`t["entered_at"][11:13]`) will raise IndexError if entered_at is shorter than 13 characters. Unlikely but possible for malformed records.  [Confidence: P]
```

```
[paper.py] get_performance() L:1707–1733  7/10 — Calls _load() without _DATA_LOCK at L:1709; uses get_peak_balance() and get_max_drawdown_pct() and get_open_trades() as separate calls. Multiple disk reads, not atomic. Acceptable for a display/reporting function.  [Confidence: C]
```

```
[paper.py] get_profit_factor() L:1736–1779  8/10 — Clean ratio computation; handles no-loss and no-win cases correctly (None vs 0.0); rounds appropriately. Calls _load() without lock (read-only reporting). Good test coverage (TestProfitFactor 4 cases).  [Confidence: C]
```

```
[paper.py] export_trades_csv() L:1912–1921  7/10 — Uses first trade's keys as fieldnames — if trades have heterogeneous fields (some have keys others don't), DictWriter will raise ValueError. Unlikely with the current schema but possible after a migration. No test for heterogeneous records.  [Confidence: P]
```

```
[paper.py] reset_paper_account() L:1924–1926  7/10 — _save() called without _DATA_LOCK — RF2 boundary. Any concurrent read during this single _save() call is protected by atomic_write_json at the file level, but the in-memory state is not protected. However, this is an admin/test function only; not called in production paths.  [Confidence: P]
FIX: paper.py:1925 — wrap in `with _DATA_LOCK:` for correctness even in admin use.
```

```
[paper.py] check_model_exits() L:1929–2003  6/10 — Bare `except Exception: continue` at L:2001 — RF1. analyze_trade() errors are silently swallowed. This is the model re-analysis loop; a systematic error (e.g. API down) would produce empty recommendations silently. Should log at WARNING per trade.  [Confidence: C]
FIX: paper.py:2001 — replace `except Exception: continue` with `except Exception as _exc: _log.warning("check_model_exits: error re-analyzing %s: %s", t.get('ticker'), _exc); continue`
```

```
[paper.py] check_expiring_trades() L:2006–2036  7/10 — Skips trades without close_time; handles parse errors with continue; returns sorted by hours_left. Good defensive coding.  [Confidence: C]
```

```
[paper.py] get_current_streak() L:2039–2079  7/10 — Filters to days_out >= 1 (multi-day only); sorts by settled_at; handles breakeven (pnl==0) as streak-ender (M-10 fix). _load() called without lock. Read-only reporting.  [Confidence: C]
```

```
[paper.py] is_streak_paused() L:2082–2100  7/10 — Requires 3+ consecutive losses AND > 2% balance loss — dual guard prevents trivial pause. Calls _load() without lock; read-only reporting. Acceptable.  [Confidence: C]
```

```
[paper.py] is_accuracy_halted() L:2103–2144  7/10 — Two bare `except Exception: pass` at L:2127 and L:2142 — RF1 boundary. Accuracy and SPRT check failures are silently swallowed, returning False (not halted). This means a crash in tracker.get_rolling_win_rate() would silently fail to halt trading. Should log at WARNING.  [Confidence: C]
FIX: paper.py:2127 and 2142 — add _log.warning() before pass.
```

```
[paper.py] get_accuracy_halt_reason() L:2147–2176  7/10 — Returns empty string on errors (safe). Duplicate `except Exception: pass` pattern with no logging — consistent with is_accuracy_halted() but same RF1 concern.  [Confidence: C]
```

```
[paper.py] get_daily_pnl() L:2179–2203  7/10 — Filters by settled_at[:10] (correct per P0-2/M-9 comments). Bare `except Exception: return settled_pnl` for MTM inclusion — acceptable fallback.  [Confidence: C]
```

```
[paper.py] reset_daily_loss_limit() L:2206–2227  7/10 — Date-keyed flag expires automatically at midnight UTC. Logs at WARNING. `except Exception` on write error logged at ERROR. Correct.  [Confidence: C]
```

```
[paper.py] is_daily_loss_halted() L:2230–2252  7/10 — Override flag checked first; `except Exception: pass` on flag read (never block trading on flag failure — correct). Uses get_balance() for threshold scaling. Calls get_daily_pnl() separately — two reads.  [Confidence: C]
```

```
[paper.py] check_aged_positions() L:2255–2273  7/10 — Read-only; skips missing/unparseable entered_at. Good defensive coding.  [Confidence: C]
```

```
[paper.py] fear_greed_index() L:2333–2391  6/10 — Calls _load() at L:2362 without lock (read-only display); calls get_balance() separately. Non-atomic snapshot. More significantly, the recent win rate component uses all settled trades (not multi-day only) — same-day METAR wins inflate the sentiment score. This is a display function so I1 doesn't apply strictly, but it could mislead the operator.  [Confidence: P]
```

```
[paper.py] check_correlated_event_exposure() L:2394–2459  7/10 — Correctly groups by city and finds 3-day clusters. ValueError/TypeError on date parsing gracefully skipped. No test coverage but pure reporting function.  [Confidence: C]
```

```
[paper.py] export_tax_csv() L:2462–2507  7/10 — Informational reporting; correctly notes not tax advice. Uses settled_at[:4] for year filtering — fragile if settled_at is in a non-ISO format, but all writes use datetime.now(UTC).isoformat() which is always len > 4.  [Confidence: C]
```

```
[paper.py] get_balance_history() L:2510–2548  6/10 — Calls _load() without lock; sorts by entered_at (not settled_at) for entry events — this is correct since entry happens at entered_at. However, sort at L:2547 mixes entry and settlement events: a trade entered Monday settles Friday — both appear in the timeline. Using entered_at for buying and settled_at for settlement is correct, but the final sort on str(ts) treats "" (Start entry has ts="") as lexicographically earliest, which is correct. Minor: no test coverage.  [Confidence: P]
```

```
[paper.py] undo_last_trade() L:2551–2589  5/10 — Calls _load() and _save() without _DATA_LOCK — RF2. A concurrent place_paper_order() could fire between the read and the save, causing the undo to overwrite the concurrent trade's balance change. peak_balance is recomputed by replaying all remaining trades (correct but expensive). max_minutes=5 window is hardcoded — should be env-configurable per RF5 spirit, though this is a minor admin tool.  [Confidence: C]
FAILURE SCENARIO: User runs undo_last_trade() while cron auto_settle fires concurrently. The undo reads the current state, removes the trade, adds back cost. The settlement writes first (with lock). The undo then overwrites with a stale data dict, erasing the settlement record. P&L is lost.
FIX: paper.py:2557 — wrap entire function body in `with _DATA_LOCK:`
```

```
[paper.py] _mark_needs_manual_settle() L:2592–2603  6/10 — Calls _load() and _save() without _DATA_LOCK — RF2. Same race condition as undo_last_trade() but smaller window since it only sets one flag. In practice it is called from auto_settle_paper_trades() which also doesn't hold a lock around the multi-trade loop, so the race exists throughout auto_settle.  [Confidence: C]
FIX: paper.py:2593 — wrap `data = _load()` through `_save(data)` in `with _DATA_LOCK:`
```

```
[paper.py] auto_settle_paper_trades() L:2606–2694  7/10 — Iterates open trades; handles tracker-based and API-based outcomes; guards against cancelled/voided results (H-7 fix); logs settlement failures at ERROR (M-7 fix). However, settle_paper_trade() is called without the outer loop holding _DATA_LOCK — each settlement is individually atomic but the loop itself can interleave with other operations. The 24h gate (I4) is NOT checked here or in settle_paper_trade(). See settle_paper_trade() weakness above.  [Confidence: C]
```

```
[paper.py] get_rolling_sharpe() L:2700–2736  7/10 — Annualised Sharpe; uses settled_at (L-4 fix); requires 5+ days. stdev=0 guard. Returns None correctly when insufficient data. No test coverage.  [Confidence: P]
```

```
[paper.py] get_attribution() L:2739–2771  7/10 — Correct NO-side win_prob adjustment (L-5 fix). Applies KALSHI_FEE_RATE. No test coverage but pure analytics.  [Confidence: C]
```

```
[paper.py] get_factor_exposure() L:2774–2820  7/10 — Directional YES/NO breakdown; correctly deduplicates city lists. No test coverage.  [Confidence: C]
```

```
[paper.py] get_expiry_date_clustering() L:2823–2847  7/10 — Groups by target_date; returns dates with 2+ positions. Simple and correct.  [Confidence: C]
```

```
[paper.py] get_unrealized_pnl_paper() L:2850–2898  6/10 — Bare `except Exception: continue` at L:2891 — RF1. API errors are silently swallowed. An API outage during the MTM loop would silently return partial results (only the trades it fetched before the error), making the total unrealized look better than it is.  [Confidence: C]
FIX: paper.py:2891 — add `_log.warning("get_unrealized_pnl_paper: failed to fetch %s: %s", t.get('ticker'), ...)` before continue.
```

```
[paper.py] check_position_limits() L:2901–2941  7/10 — Checks per-market cap and global portfolio cap; returns structured ok/reason dict. Good.  [Confidence: C]
```

```
[paper.py] estimate_slippage() L:2947–2967  7/10 — Linear model above depth_scale; capped at 0.05. market_prob parameter accepted but unused — noted in docstring.  [Confidence: C]
```

```
[paper.py] slippage_adjusted_price() L:2970–2989  7/10 — Square-root impact model; clamped to [0.01, 0.99]. Correct for YES (add) and NO (subtract).  [Confidence: C]
```

```
[paper.py] simulate_fill() L:2992–3022  7/10 — Combines partial fill + slippage; 50–90% fill range on thin markets. No test coverage for this specific function.  [Confidence: P]
```

```
[paper.py] simulate_partial_fill() L:3025–3036  8/10 — Minimum fill of 1 contract; uniform 0.5–1.0 of depth estimate. Full test coverage (TestSimulatePartialFill 5 cases).  [Confidence: C]
```

```
[paper.py] calc_trade_pnl() L:3039–3072  7/10 — Uses actual_fill_price for P&L; correct KALSHI_FEE_RATE on winnings (M-8 fix). Fee is applied to the NO side too via the same formula — this is correct since both sides pay fee on winnings only. No test coverage for calc_trade_pnl() directly.  [Confidence: C]
```

---

## Summary

| Tier | Function | Score | Key Issue |
|---|---|---|---|
| T1 | `_load()` | 7 | Lock contract relies on callers; several callers omit lock |
| T1 | `_save()` | 9 | Near-exemplary |
| T1 | `_drawdown_snapshot()` | 9 | Near-exemplary |
| T1 | `is_paused_drawdown()` | 9 | Near-exemplary |
| T1 | `drawdown_scaling_factor()` | 9 | Near-exemplary |
| T1 | `get_balance()` | 8 | Per-call disk read; no cache |
| T1 | `get_peak_balance()` | 8 | Per-call disk read; two separate reads in get_max_drawdown_pct() |
| T1 | `graduation_check()` | 8 | No dedicated unit test; correct Brier threshold (≤0.23) |
| T1 | `settle_paper_trade()` | 8 | I4 — 24h gate missing from settlement path |
| T1 | `place_paper_order()` | 7 | Bare except in A/B test block; is_daily_loss_halted TOCTOU |
| T1 | `reset_peak_balance()` | 9 | Near-exemplary |
| T1 | `get_edge_realization_rate()` | 8 | multiday_directional_accuracy correctly computed and named |

**Critical findings:**
1. **I4 violation — 24h settlement gate missing from settle_paper_trade()/auto_settle_paper_trades()**: The preamble states all settlement paths must check close_time + 24h. Neither function does. In practice, Kalshi only posts finalized results after the actual settlement window, so this rarely fires, but the invariant is violated. Severity: LOW (operational risk minimal) but CONFIRMED.

2. **undo_last_trade() and _mark_needs_manual_settle() call _save() without _DATA_LOCK**: Both are write paths. A concurrent settlement could be overwritten. Severity: MEDIUM for undo_last_trade() (admin function, but still a real data-loss scenario); LOW for _mark_needs_manual_settle() (flag-only write).

3. **Multiple RF1 instances in TIER 2**: check_exit_targets(), check_model_exits(), _dynamic_kelly_cap(), is_accuracy_halted(), get_unrealized_pnl_paper() all have bare `except Exception: continue/pass/return` without any log. These need WARNING logs added.

**Calibrated median for this file: 7.5/10.** The TIER 1 functions are well-engineered with good lock discipline and test coverage. The TIER 2 layer has a consistent RF1 pattern (bare exception swallowing) that needs systematic fixing.
