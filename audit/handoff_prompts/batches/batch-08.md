# Batch 8: Between-bucket / METAR settlement domain

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch comes from the 2026-08-18 max-depth forensic audit (`audit/AUDIT_REPORT.md` / `.json`). It groups 4 finding(s) that share **settlement_monitor.py, weather_markets.py, metar.py** -- doing them together means you only load this subsystem's context once, and avoids two different sessions independently editing the same file in parallel. Live trading is currently dormant (`LIVE_TRADING_ENABLED` unset) -- no active financial exposure today for any item below, but treat items tagged HIGH/MEDIUM as touching a real live-order/live-money surface once trading is enabled.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. AUD-0016 [MEDIUM | VERY HIGH | E2 | CONFIRMED]: Between-bucket settlement lock-in can lock YES off the instantaneous METAR reading despite a lower authoritative daily-high, contradicting its own documented invariant

**Files:** settlement_monitor.py, metar.py, cron.py, tests/test_settlement_monitor.py  
**Lines:** settlement_monitor.py:242-274; settlement_monitor.py:401-453; cron.py:1434-1497; tests/test_settlement_monitor.py:170-182

**Problem:** settlement_monitor._check_between_settlement()'s YES branch computes `comp_temp = max(current_temp_f, max_temp_f)` and locks YES when `max_temp_f is not None and lower_f <= comp_temp <= upper_f`. When the freshest instantaneous reading (current_temp_f) exceeds the independently-cached authoritative running daily high (max_temp_f), comp_temp reduces to current_temp_f and the lock is decided purely by the instantaneous reading -- contradicting the function's own docstring ('YES only from a REAL max_temp_f; never locks YES from the current_temp_fallback alone') and the test named for that exact invariant, which only covers max_temp_f=None.

**Root cause:** The `max(current_temp_f, max_temp_f)` combination silently substitutes the instantaneous reading for the authoritative running extreme whenever the instantaneous reading is larger, defeating the 'requires a REAL max_temp_f' guard exactly in the still-rising-temperature case the guard exists to protect against.

**Evidence:** Reproduced this session: `_check_between_settlement(current_temp_f=67.0, lower_f=66.5, upper_f=68.5, max_temp_f=65.0)` returns `{'locked': True, 'outcome': 'yes', 'confidence': 0.7749999999999999, 'comp_temp_f': 67.0}` — comp_temp_f == current_temp_f, confirming the lock is decided by the instantaneous reading while max_temp_f (65.0) is still below the band. Verified tests/test_settlement_monitor.py's TestCheckBetweenSettlement class (L126-272) in full: every test that supplies a non-None max_temp_f sets current_temp_f == max_temp_f (never current_temp_f > max_temp_f), so the gap is untested. Verified downstream: cron.py L1434-1497 reads settlement signals and auto-closes any matching open paper trade via paper.close_paper_early() once confidence>=0.80, with no ticker-family distinction and no human review; also confirmed the between-bucket branch (settlement_monitor.py L401-453) never calls _calibrate_metar_settlement_confidence (only the T-ticker branch at L455-478 does), so its raw confidence (up to 0.95) is used directly against the 0.80 gate.

**Financial risk:** Feeds paper.close_paper_early() with no human review; a forced YES close on a temperature that has only just entered the band and may still climb books an incorrect settlement outcome, corrupting paper P&L, which per d320142d's commit message feeds paper.is_accuracy_halted()'s rolling win-rate that trading_gates.LiveTradingGate also checks -- several steps removed from live-money impact and unverified in this worktree, but a real risk-control input nonetheless.

**Recommendation:** Gate the in-band/YES check on max_temp_f itself, not max(current_temp_f, max_temp_f); use current_temp_f only for the already-correctly-reasoned NO branch. Add a regression test with max_temp_f present-but-lower-than-current_temp_f.

**Limitations noted by the audit:** Whether this code path has actually executed in production (vs. just being scheduled/dormant) is unverifiable from this worktree.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0016`), `audit/AUDIT_REPORT.md`.

### 2. AUD-0035 [LOW | VERY HIGH | E2 | CONFIRMED]: METAR settlement-lag force-close gate (cron.py's >=0.80 threshold) is mathematically unreachable under the currently fitted calibration model

**Files:** cron.py, settlement_monitor.py, metar.py, ml_bias.py  
**Lines:** cron.py:1471; metar.py:31-57; settlement_monitor.py:277-345; ml_bias.py:494-505

**Problem:** The calibration model systematically compresses the [0.72,0.97] raw range downward through a sigmoid correction such that its output ceiling (0.766) sits below the pre-existing 0.80 force-close threshold.

**Evidence:** Read cron.py:1440-1485 confirming the >=0.80 gate at L1471. Read settlement_monitor.py:277-345 and ml_bias.py:494-505 confirming the sigmoid(a*ln(s)-b*ln(1-s)+c) formula. Read metar.py:31-57 confirming the [0.72,0.97] hard bound. Went beyond the finding's own evidence by reading the REAL currently-fitted calibration file directly from the main clone (paths.py resolves data/ there): C:\Users\thesa\claude kalshi\data\metar_lockout_calibration.json = {a: 0.22619580826228397, b: 0.22619580826228397, c: 0.4000758536385143, n: 33, fitted_at: 2026-08-16}, confirming the docstring's cited coefficients are in fact the live active fit, not stale/hypothetical numbers. Re-ran audit/reproductions/metar_calibration_bound_check.py: max YES-lock 0.7661, max NO-lock 0.5954, gate reachable: False.

**Financial risk:** Currently near-zero per the settlement_monitor.py docstring's own claim (cron.log/schtasks checks reportedly show this path has never fired against real trades) -- not independently re-verified this session since cron.log/schtasks state for the reference deployment machine is unavailable from this worktree.

**Recommendation:** Per backlog.txt's own entry: rescale the 0.80 threshold to the calibrated scale, or fit a settlement-path-specific calibration model once enough settlement-lag outcome rows exist.

**Limitations noted by the audit:** Did not independently re-verify the cron.log/schtasks claim that this mechanism has never actually fired in production.

**Note:** this finding's structured record is missing description, root_cause (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Independently re-derived and re-executed this session, and additionally strengthened beyond both the original finding and the prior verification pass by reading the live main-clone calibration data file directly rather than trusting the docstring's cited numbers -- confirms a=b=0.2262/c=0.4001 are the actual currently-active fitted values (fitted 2026-08-16, 2 days before this audit), not a stale citation. Note this finding is substantially a re-statement of an already-self-documented in-code finding (settlement_monitor.py's own docstring states the same figures almost verbatim) -- correctness unaffected, but novelty is low.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0035`), `audit/AUDIT_REPORT.md`.

### 3. AUD-0038 [LOW | HIGH | E2 | CONFIRMED]: METAR-calibrated T-ticker settlement force-close gate's 'currently dormant' status is a coefficient-snapshot fact, not a durable invariant, given weekly auto-retrain

**Files:** settlement_monitor.py, ml_bias.py, metar.py, cron.py  
**Lines:** settlement_monitor.py:295-323; ml_bias.py:299-322; ml_bias.py:396-491; metar.py:31-57; cron.py:2032-2052

**Problem:** The T-ticker settlement-lag force-close gate (cron.py's >=0.80 threshold) is currently unreachable under the coefficients fitted as of 2026-08-16 (a=b=0.2262, c=0.4001) -- calibrated confidence never exceeds ~0.766 (YES) / ~0.595 (NO). This is specific to that coefficient snapshot. ml_bias.fit_metar_calibration() refits these coefficients weekly (cron.py L2032-2052) from live settlement data, bounded only by a>0/|a|<=5/|b|<=5. No test or runtime check ties the 'stays below 0.80' claim to future retrains -- a future week's fit could push the calibrated output above 0.80 and silently reactivate this force-close path with no alert.

**Root cause:** The dormancy conclusion was verified against one point-in-time coefficient fit and documented as current fact, but the coefficients are refit on a recurring schedule with no corresponding re-verification or monitoring tied to the threshold comparison.

**Evidence:** settlement_monitor.py:295-323 docstring confirmed to state the coefficient-specific dormancy claim (including the exact a=b=0.2262, c=0.4001 figures and cron.log/schtasks verification story). ml_bias.py:299-322 (_fit_platt) confirmed bounds are exactly `a>0, |a|<=5, |b|<=5` -- no bound relates to the 0.80 threshold. Independently read+verified the live data file: paths.METAR_CALIBRATION_PATH resolves (per the worktree-data-dir gotcha) to the main clone's data/metar_lockout_calibration.json, which currently contains a=b=0.22619580826228397, c=0.4000758536385143 -- matching the docstring's cited figures exactly. Independently recomputed apply_metar_calibration's output at metar.py's fixed input range [0.72,0.97]: YES-lock ceiling sigmoid(0.2262*logit(0.97)+0.4001)=0.766, NO-lock confidence-space ceiling=0.595 -- both reproduce the docstring's claimed numbers exactly. Confirmed a future fit near the a<=5/b<=5 boundary (e.g. a=b=5) would push the calibrated output to ~1.0, well past 0.80. Confirmed cron.py:2032-2052's weekly retrain block only fits/saves/logs the new coefficients with zero comparison against the 0.80 threshold and zero alerting on a dormant-to-active transition.

**Financial risk:** Low today (path is dormant); the risk is a future, unreviewed transition to active behavior in a path whose YES-branch has the separate correctness issue reported in Finding 1 above (the between-bucket sibling).

**Recommendation:** Add a lightweight check at retrain time comparing the newly-fitted calibration's output range against cron.py's 0.80 force-close threshold, so a transition from dormant to active is visible rather than silent.

**Limitations noted by the audit:** This is a process/monitoring gap, not a demonstrated present-day incorrect behavior -- the current dormancy claim is now independently re-derived from the live coefficient file (not just taken from the commit message), which strengthens confidence over the original finding's own E1 rating.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0038`), `audit/AUDIT_REPORT.md`.

### 4. AUD-0020 [MEDIUM | HIGH | E1 | CONFIRMED]: _compute_persistence_prob's same-day daily-extreme fix (b0f4cad2) covers only var="max" (HIGH markets); var="min" (LOW markets) still uses the instantaneous METAR reading instead of the true running daily low

**Files:** weather_markets.py, metar.py, tests/test_weather_markets.py, backlog.txt  
**Lines:** weather_markets.py:6090-6154; weather_markets.py:6121 (var=="max" special case); weather_markets.py:6142-6143 (var=="min" falls through to instantaneous temp_f); weather_markets.py:12016-12024 (0.15 weight blend, daily path); weather_markets.py:10214-10215 (0.15 weight blend, hourly path); metar.py:374-423 (fetch_metar_daily_extreme, supports extreme="min"); tests/test_weather_markets.py:5756-5781 (test_uses_instantaneous_temp_for_min_var)

**Problem:** Commit b0f4cad2 (2026-08-17) fixed _compute_persistence_prob's same-day (days_out==0) 'prefer today's observed extreme' branch, but scoped the fix to var=="max" only: it resolves a METAR station and calls metar.fetch_metar_daily_extreme(station, tz, local_today, "max") to get the true running daily high instead of the misleading instantaneous reading. No equivalent branch exists for var=="min" -- all min-var, days_out==0 calls still fall through to the raw instantaneous temp_f reading (weather_markets.py:6142-6143), exactly the defect class the max-side fix was written to eliminate.

**Root cause:** The backlog.txt entry that drove b0f4cad2 ("PREFER TODAY'S OBSERVED MAX BRANCH IS DEAD CODE") discusses only the HIGH/max case throughout its filing, resolution narrative, and the AskUserQuestion options presented to the user -- var=="min" is never mentioned or considered. The fix was applied literally to the branch as originally scoped rather than generalized to both extremes, even though metar.fetch_metar_daily_extreme() already supports extreme="min" (and is already used that way elsewhere in the same file, by _metar_lock_in's between-branch for LOW markets).

**Evidence:** Independently re-read weather_markets.py:6090-6154 in full this session and confirmed the `if var == "max" and days_out == 0 and _live:` guard (L6121) is the only branch that calls fetch_metar_daily_extreme; the `else` branch (L6142-6143, which also covers var=="min") uses `_live.get("temp_f")` unconditionally with no daily-low lookup at all. metar.py:374-423's fetch_metar_daily_extreme implementation confirmed to fully support extreme="min" (`return max(temps) if extreme == "max" else min(temps)`, L423). tests/test_weather_markets.py:5756-5781 read in full: test_uses_instantaneous_temp_for_min_var's docstring states "var='min' must use the instantaneous current temp, not max_temp_f (the daily-max special case only applies to var='max')" and its body asserts exactly this (current_temp==61.0, the instantaneous temp_f, not any daily-extreme value) -- confirming this is the current, deliberately-tested behavior. Traced persistence_p's usage: it is blended into live analyze_trade's blended_prob at a real, non-shadow 0.15 weight (weather_markets.py:12016-12024, `w_persist = 0.15` gated on `persistence_p is not None and days_out <= 2`), and into _analyze_hourly_trade's blended_prob the same way (L10214-10215, `blended_prob = 0.85 * ens_prob + 0.15 * persistence_p`) -- both unconditional production code paths, not behind any shadow/trading-disabled flag.

**Financial risk:** This is a real (non-shadow) input to live trade probability/edge calculation for same-day LOW-type daily and hourly temperature markets whenever METAR has not yet locked. At a diluted 15% blend weight the net effect on blended_prob is muted but directionally consistent (biases the persistence component toward overestimating how warm the day currently reads relative to its already-realized low), which could contribute to mispriced edge/Kelly sizing on affected markets. Financial exposure could not be quantified this session (no live/paper trade reproduction run).

**Recommendation:** Generalize the var=="max" branch in _compute_persistence_prob to also handle var=="min" symmetrically, calling metar.fetch_metar_daily_extreme(station, tz, local_today, "min") when var=="min" and days_out==0, falling back to temp_f exactly as the max branch does on failure. Update or replace the test_uses_instantaneous_temp_for_min_var regression test to assert the new (symmetric) behavior once fixed.

**Limitations noted by the audit:** Did not verify how often days_out==0 LOW markets actually reach this code path un-locked by METAR in production, so real-world frequency/magnitude of the resulting bias is not quantified. Did not execute pytest this session (static trace only, consistent with the audit's read-only scope).

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0020`), `audit/AUDIT_REPORT.md`.

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

At least one item in this batch touches a live-order/live-money/safety-gate path (or is adjacent enough to warrant it) -- this batch does **not** qualify for the steps 11-12 LOW-tier downgrade. Apply the full ceremony as written, all 29 steps, for the batch as a whole.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
