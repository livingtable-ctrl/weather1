# Batch 13: Rain/hurricane/shadow-signal misc correctness

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch comes from the 2026-08-18 max-depth forensic audit (`audit/AUDIT_REPORT.md` / `.json`). It groups 7 finding(s) that share **weather_markets.py, cron.py, tracker.py, schema_validator.py** -- doing them together means you only load this subsystem's context once, and avoids two different sessions independently editing the same file in parallel. Live trading is currently dormant (`LIVE_TRADING_ENABLED` unset) -- no active financial exposure today for any item below, but treat items tagged HIGH/MEDIUM as touching a real live-order/live-money surface once trading is enabled.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. AUD-0022 [MEDIUM | HIGH | E1 | CONFIRMED]: Shadow-only far-tail rain-blend signal shares the global _ensemble_cb circuit breaker with the live temperature trading blend's prewarm fetch

**Files:** weather_markets.py, circuit_breaker.py, trade_cycle.py  
**Lines:** weather_markets.py:8016-8149 (_fetch_ensemble_precip_multiday, record_failure at 8128-8129); weather_markets.py:108-113 (_ensemble_cb construction: failure_threshold=3, recovery_timeout=300, burst_window=2.0); weather_markets.py:2009-2014 (Tier-1 blend-critical temp models loop, shares _ensemble_cb); weather_markets.py:8818-8829 (author's own comment documenting this exact risk); trade_cycle.py:309-310 (prewarm runs once, before per-market analysis loop at 314)

**Problem:** d190d09d extends the shadow-only rain_forecast_blend_prob signal to reach _fetch_ensemble_precip_multiday for early-month monthly-rain tickets. Each per-model fetch that returns an all-null response calls _ensemble_cb.record_failure() on the SAME global CircuitBreaker instance that the real Tier-1 temp-blend prewarm loop depends on. The outer try/except in _analyze_monthly_rain_trade does not cover this side effect, which happens inside the fetch helper's own internal except block before control returns to the caller.

**Root cause:** A circuit breaker instance scoped to an entire external API family rather than per-consumer, combined with a newly-reachable code path whose own false-failure guard is an approximate heuristic, not a guarantee.

**Evidence:** Read of weather_markets.py:8016-8149, 100-139, 2009-2014, 8750-8836 confirms every mechanical claim. weather_markets.py:8818-8829 contains the original author's own comment independently stating almost the identical concern. circuit_breaker.py:42-144 confirms CircuitBreaker persists state to disk (paths.CB_STATE_PATH, atomic-written) by default -- this is genuinely cross-process (cron.py and a separately-running watch --auto --live process share this state file), not merely intra-process.

**Financial risk:** Soft degradation of the real live temperature trading blend's forecast ensemble diversity for a bounded window, potentially biasing the probability estimate feeding Kelly-sized live/paper trades.

**Recommendation:** Give the far-tail blend's multiday fetch its own dedicated circuit breaker instance, consistent with the commit's own stated design intent.

**Limitations noted by the audit:** The burst_window=2.0s absorption narrows the practical trigger scenario to failures across multiple distinct tickets more than 2 seconds apart within one cycle. The commit's own authors were aware of and partially mitigated this risk class (the 6-day guard); this finding's distinct contribution is the downstream consequence on the REAL temperature blend, which their own reasoning does not address.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0022`), `audit/AUDIT_REPORT.md`.

### 2. AUD-0027 [MEDIUM | VERY HIGH | E1 | CONFIRMED]: Settlement-lag force-close signal is wired to paper positions only, never live

**Files:** cron.py, settlement_monitor.py  
**Lines:** cron.py:1434-1497; settlement_monitor.py:277-359 (calibration confidence-bound docstring)

**Problem:** cron.py's settlement-lag force-close block (1434-1497) imports paper.close_paper_early/paper.get_open_trades and matches signals only against paper positions built from paper.get_open_trades(). Grepping settlement_signal/read_settlement_signals usage across order_executor.py, positions.py, and main.py returns zero matches -- only cron.py (consumer), settlement_monitor.py (producer), and web_app.py (read-only display) reference it at all.

**Root cause:** The METAR settlement-lag force-close feature (cluster K) was built and wired against paper.py's ledger only; no equivalent live-position force-close path was added alongside it.

**Evidence:** Independently re-read cron.py:1434-1497, confirming the block's data source is exclusively paper.get_open_trades()/paper.close_paper_early. Independently re-ran the grep across order_executor.py, positions.py, main.py for settlement_signal|read_settlement_signals -- confirmed zero matches. Independently re-read settlement_monitor.py:277-359's docstring, which states the calibrated confidence never exceeds ~0.766 (YES-lock) / ~0.595 (NO-lock) against a real fitted model (a=b=0.2262, c=0.4001), permanently below cron.py's >=0.80 gate, and is corroborated by cron.log having zero 'SETTLEMENT LAG signal' entries and the daily task never being registered via schtasks on this machine.

**Financial risk:** Currently low in practice: settlement_monitor.py's own docstring documents the calibrated confidence never reaches cron's own >=0.80 force-close threshold under current production coefficients, so the mechanism is presently dormant even for paper. The live-position gap would become consequential the moment that calibration/threshold mismatch is separately fixed.

**Recommendation:** Extend the settlement-lag force-close block (or add a live-specific sibling) to also match against live open positions (execution_log's get_filled_unsettled_live_orders), mirroring how positions.py already unified paper/live for stop-loss/breakeven.

**Limitations noted by the audit:** Currently masked by the documented dormancy of the underlying signal -- this is a latent gap, not an active one, under today's calibration coefficients.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0027`), `audit/AUDIT_REPORT.md`.

### 3. AUD-0036 [LOW | HIGH | E1 | CONFIRMED]: Live cmd_order sell only closes the oldest of multiple tracked live positions sharing the same ticker+side (operator-warned, not auto-fixed)

**Files:** main.py, order_executor.py, execution_log.py  
**Lines:** main.py:4577-4666; order_executor.py:1077-1115; execution_log.py:535-556

**Problem:** Multiple live positions can legally share a ticker+side because nothing prevents duplicate live entries (same root cause as the check_position_limits() blindness finding). closes_position_id supports referencing only one prior row per exit.

**Evidence:** Read main.py:4577-4666 directly, confirming the code, the 'Opus review (2026-08-17), NEW-M1' comment, and the yellow warning print exactly as described. Additionally verified the 'oldest' claim at the SQL level (beyond the original finding's evidence): order_executor._get_live_open_positions() (order_executor.py:1077-1115) calls execution_log.get_filled_unsettled_live_orders() (execution_log.py:535-556), whose query is `ORDER BY placed_at` ascending -- confirming _live_open_matches[0] genuinely is the oldest by placed_at.

**Financial risk:** Low-to-moderate: if duplicate live positions accumulate (enabled by Finding 1), an operator may believe a full exit occurred when others remain open, though the warning surfaces this if read.

**Recommendation:** Already correctly deferred by its own authors pending the exposure-cap fix (Finding 1), which is the real root cause preventing duplicate live entries from accumulating. No independent action recommended.

**Limitations noted by the audit:** Did not verify whether order_executor._exit_live_position (the automated protective-exit scanner) has the same one-at-a-time limitation for its own multi-position scenario.

**Note:** this finding's structured record is missing description, root_cause (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Fully confirmed by independent code read, and strengthened beyond the original finding by tracing the ordering claim ('oldest') down to the actual SQL ORDER BY placed_at clause rather than trusting the variable naming/comment. No refuting evidence found.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0036`), `audit/AUDIT_REPORT.md`.

### 4. AUD-0041 [LOW | VERY HIGH | E1 | CONFIRMED]: cmd_order writes 'buy'/'sell' into execution_log's order_type column, which every other write site (and the schema's own comment) uses for 'market'/'limit'

**Files:** main.py, execution_log.py, order_executor.py  
**Lines:** main.py:4658 (order_type=action); execution_log.py:135 (schema comment); order_executor.py:737,836,1241,1649,3088,3258

**Problem:** execution_log.py's orders table schema documents order_type as holding "market" or "limit", and every write site in order_executor.py (6 call sites) writes exactly one of those literal strings. main.cmd_order is the sole exception: it calls log_order(..., order_type=action, ...) where action is the CLI verb "buy" or "sell".

**Root cause:** This is the codebase's original bug, present since the first execution_log integration (commit 1e3faca6, April 2026) and never corrected; e5331a8d re-touched this exact call site without noticing or fixing the pre-existing misuse.

**Evidence:** Direct read confirms execution_log.py:135 schema comment ("market" or "limit") and all 6 order_executor.py call sites (737,836,1241,1649,3088,3258) using "limit"/"market" literals. `git log -S "order_type=action" -- main.py` shows only commit 1e3faca6 introduces the string (never toggled since). `git show e5331a8d -- main.py` diff confirms the log_order() call at this site was rewritten (new kwargs added across the same commit) while order_type=action was carried through unchanged. grep across execution_log.py/web_app.py/output_formatters.py confirms no SELECT/read of order_type exists anywhere -- dormant, no active consumer.

**Financial risk:** None currently (no code reads this field for any decision), but any future feature distinguishing maker vs taker fills by order_type (a natural fix for the settlement-fee finding above) would need this corrected first.

**Recommendation:** Fix cmd_order's log_order() call to pass a real order_type value, mirroring order_executor's time_in_force-derived convention.

**Limitations noted by the audit:** No current downstream consumer found reading this field, so real-world impact today is limited to data-quality/future-maintenance risk.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0041`), `audit/AUDIT_REPORT.md`.

### 5. AUD-0043 [LOW | HIGH | E1 | CONFIRMED]: Far-tail rain blend's logged n_members metadata doesn't reflect the deterministic cross-product's true effective sample size

**Files:** weather_markets.py  
**Lines:** weather_markets.py:8830-8940; weather_markets.py:8896-8898 (combined_totals cross-product); weather_markets.py:8918-8933 (forecast_blend_signal metadata); weather_markets.py:8737, 8941-8943 (independent blended_prob computation, unaffected)

**Problem:** d190d09d's far-tail case computes combined_totals as the deterministic cross product of member_totals (near-forecast ensemble, ~30-130 members) and tail_sums_tilted (historical tail years, >=15). The commit's own comment explains this cross-product IS the exact expected value of pairing each near member with a tail value, computed exhaustively rather than sampled -- mathematically sound for computing forecast_blend_prob itself. However, the logged composition metadata rain_forecast_blend_n_members is set to n_members (the near-ensemble count) only, not any measure of the tail-year count or the pair (n_members, n_tail_years).

**Root cause:** The cross product's raw length (n_members * n_tail_years, potentially several hundred to ~1000) is not an independent-sample count -- each near member is paired with every tail year and vice versa, so the genuine 'effective sample size' for statistical-uncertainty purposes is bounded by min(n_members, n_tail_years), typically the tail-year count (~15-30, the smaller of the two in practice). Logging only n_members (silently discarding the tail-year count from the metadata, even though tail_days is logged) could let a future graduation/calibration analysis (which the commit's own comment says this metadata exists to support) mistake this signal's effective precision for something larger than it really is.

**Evidence:** Read weather_markets.py L8830-8940 in full. Confirmed combined_totals = [m + t for m in member_totals for t in tail_sums_tilted] (L8896-8898); forecast_blend_signal (L8918-8933) only stores rain_forecast_blend_n_members: n_members (the near-member count) and rain_forecast_blend_tail_days (a calendar day count, not a tail-year count) -- the tail sample count (len(tail_sums_tilted)) is computed but never logged; grepped for tail_sums_tilted/tail_years/len(tail_sums) across the whole file and confirmed the tail-year length is used only for the >=15 gate check (L8858) and a debug log on the skip path (L8907), never captured in the success-path metadata. Also confirmed (going beyond the original finding's own MEDIUM-confidence caveat) via a repo-wide grep for 'rain_forecast_blend' that no other module or test references these fields -- the caveat the original author raised ('did not verify whether some other part of the codebase already has access to the tail-year count via another path') is directly checked and found false: no such other path exists.

**Financial risk:** None currently -- confirmed shadow/log-only: blended_prob is computed at L8941-8943 from remaining_sums_tilted, set independently at L8737 well before the far-tail block runs, and forecast_blend_signal is merged into the returned analysis only as a nested 'signals' key (L9050-9054), never read back into blended_prob/rec_side/Kelly sizing anywhere in this function.

**Recommendation:** If/when this signal is revisited for graduation, also log the tail-year sample count (len(tail_sums_tilted)) alongside n_members so effective-sample-size can be assessed correctly. Not urgent: this signal is shadow/log-only today and does not affect blended_prob/rec_side/sizing.

**Limitations noted by the audit:** This is a minor documentation/completeness observation about future-graduation readiness, not a bug affecting any current computation or decision.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0043`), `audit/AUDIT_REPORT.md`.

### 6. AUD-0052 [LOW | HIGH | E1 | CONFIRMED]: tracker.count_settled_signal_rows() builds SQL via f-string interpolation of column/json_key parameters

**Files:** tracker.py:2671-2742

**Problem:** count_settled_signal_rows() interpolates its `column` and `json_key` parameters directly into the SQL string rather than using parameterized placeholders.

**Root cause:** Column/JSON-path names can't be parameterized with `?` placeholders in SQLite, so the function trusts callers to only ever pass fixed literal identifiers, with no runtime validation.

**Evidence:** Read tracker.py:2671-2742 directly — confirmed `where = f"json_extract(p.signal_values, '$.{json_key}') IS NOT NULL"` and `where = f"p.{column} IS NOT NULL"` exactly as described, plus the f-string table-name interpolation `f"SELECT COUNT(*) FROM {table} p ...WHERE {where}"`. Grepped every call site in weather_markets.py (lines 6867, 6889 via the _count_signal_column/_count_signal_json_key factory functions at weather_markets.py:6854-6890) and confirmed all registry entries (weather_markets.py:6946-7088) pass hardcoded string literals ('run_trend_delta', 'implied_mean', 'gated_edge', 'ensemble_spread_f', 'nbm_quantile_prob', 'ecmwf_consensus_gap_prob', etc.), not derived values. Also grepped tests/test_tracker.py callers — all use literal strings.

**Financial risk:** None currently — not reachable from any user/network input.

**Security risk:** Latent SQL-injection-shaped pattern; unexploitable today, would become exploitable only if a future caller passed request-derived input.

**Recommendation:** Add an allowlist check inside count_settled_signal_rows() before interpolation, independent of current caller discipline.

**Limitations noted by the audit:** Based on grepping all current call sites (including tests); cannot rule out a caller added after this session.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0052`), `audit/AUDIT_REPORT.md`.

### 7. AUD-0060 [LOW | HIGH | E1 | CONFIRMED]: schema_validator.py's validate_market/validate_forecast/validate_nws_response return values are discarded everywhere they're called

**Files:** schema_validator.py, kalshi_client.py, nws.py, weather_markets.py  
**Lines:** schema_validator.py:36; schema_validator.py:125; schema_validator.py:173; kalshi_client.py:324; kalshi_client.py:343; nws.py:236; weather_markets.py:1524

**Problem:** All three validators are documented as returning bool ("Returns True if valid, False if critical fields are missing/wrong type"), but every production call site (kalshi_client.get_markets/get_market, nws's daily-forecast fetch, weather_markets' Open-Meteo daily-fetch helper) invokes the function as a bare statement, discarding the boolean. Only the internal _log.warning() calls have any observable effect — a market or forecast payload that fails validation proceeds through the caller's normal processing exactly as if it had validated cleanly.

**Root cause:** The module's own docstring states this is intentional ("Logs warnings on violations rather than crashing"), so functionally this is logging-only by design rather than a broken gate that regressed. But the bool return signature invites the opposite assumption from future readers/maintainers.

**Evidence:** Independently read schema_validator.py in full (196 lines) confirming all three functions return bool per docstring. Grepped every call site of validate_market/validate_forecast/validate_nws_response repo-wide (production code + tests): confirmed exactly kalshi_client.py:324, kalshi_client.py:343, nws.py:236, weather_markets.py:1525 as the 4 production call sites, and read each in its surrounding context — all are bare statement calls, return value never captured or branched on. Found an additional supporting detail: nws.py:234-236's own comment ("validate BEFORE recording success so a malformed-but-HTTP-200 response doesn't credit the circuit breaker") implies the validation result was meant to gate _nws_cb.record_success(), but record_success() (L237) runs unconditionally right after regardless of validate_nws_response's return — i.e. this call site's own comment documents an intended gating behavior that isn't actually wired in.

**Financial risk:** Low/indirect — downstream consumers generally already use .get() with defaults and None-checks, so this is a missed defense-in-depth layer rather than an active bug path.

**Recommendation:** Either wire the boolean into the callers (skip processing malformed records) if that protection is actually wanted, or change the return type/docstring to make clear these are logging-only, to prevent a future caller (or the nws.py circuit-breaker comment's own apparent original intent) from assuming otherwise.

**Limitations noted by the audit:** Did not verify whether every possible caller of these three functions was found (grepped the whole repo for the three function names, which should be exhaustive for direct calls).

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0060`), `audit/AUDIT_REPORT.md`.

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

At least one item in this batch touches a live-order/live-money/safety-gate path (or is adjacent enough to warrant it) -- this batch does **not** qualify for the steps 11-12 LOW-tier downgrade. Apply the full ceremony as written, all 29 steps, for the batch as a whole.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
