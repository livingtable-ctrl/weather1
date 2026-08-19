# Batch 14: INFO-tier confirmations (verify-and-close, minimal code)

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch comes from the 2026-08-18 max-depth forensic audit (`audit/AUDIT_REPORT.md` / `.json`). It groups 14 finding(s) that share **various** -- doing them together means you only load this subsystem's context once, and avoids two different sessions independently editing the same file in parallel. Live trading is currently dormant (`LIVE_TRADING_ENABLED` unset) -- no active financial exposure today for any item below, but treat items tagged HIGH/MEDIUM as touching a real live-order/live-money surface once trading is enabled.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. AUD-0066 [INFO | HIGH | E1 | CONFIRMED]: Far-tail rain climatology blend's additive dry-tilt shift is floor-clipped at 0.0, under-applying the correction for near-zero precipitation distributions

**Files:** acis_precip.py, weather_markets.py  
**Lines:** acis_precip.py:499; weather_markets.py:8858-8933; weather_markets.py:8941-9052

**Problem:** acis_precip.py:499's `shifted = [max(0.0, s + damped_shift_in) for s in remaining_sums]` applies a floor-at-0.0 additive shift to a distribution that is mostly exact zeros (dry days). A negative (dry-tilt) shift gets asymmetrically clipped toward zero more than a positive shift would be. Confirmed shadow-only/log-only: the far-case tilted values feed only forecast_blend_signal['rain_forecast_blend_prob'] (a metadata/logging dict), while blended_prob (the value that actually drives recommended_side/sizing) comes from a separate, earlier remaining_sums_tilted computation.

**Recommendation:** Consider a multiplicative or rank-preserving tilt instead of a floor-clipped additive one if/when this signal is graduated out of shadow-only status.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0066`), `audit/AUDIT_REPORT.md`.

### 2. AUD-0067 [INFO | HIGH | E1 | CONFIRMED]: cmd_watch and cron confirmed to share one effective safety-gate chain via run_trade_cycle (no residual divergence found)

**Files:** trade_cycle.py, main.py, cron.py  
**Lines:** trade_cycle.py:188-212; main.py:3619-3648

**Problem:** Verified that trade_cycle.run_trade_cycle() (shared by cron.py and cmd_watch's auto-trade branch, both via _build_cron_context()) independently checks the kill switch (cron.KILL_SWITCH_PATH.exists()), manual override, accuracy halt, and graduation gate itself (trade_cycle.py:188-212), so cmd_watch inherits the same gate coverage as cron even though it doesn't duplicate cron.py's own pre-check block at cron.py:591-643 (which that block's own comments say exists only for black-swan-abort visibility logging, not as the blocking authority).

**Recommendation:** No action needed.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0067`), `audit/AUDIT_REPORT.md`.

### 3. AUD-0068 [INFO | HIGH | E1 | CONFIRMED]: safe_io bare os.replace() migration is complete repo-wide (cluster J fully resolved for os.replace specifically)

**Files:** safe_io.py

**Problem:** Grepped `os.replace(` across the entire repository outside safe_io.py -- zero remaining bare call sites in production code; only comment/docstring mentions and the guard test's own allowlist. Confirms the migration commits (94d36402, 3a28ae33, f2c03d98) fully closed this specific pattern, though it did not extend to the semantically-similar Path.rename() pattern (see the separate NEW finding on main.py's kill-switch rename race).

**Recommendation:** No action needed for os.replace() specifically.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0068`), `audit/AUDIT_REPORT.md`.

### 4. AUD-0069 [INFO | HIGH | E1 | CONFIRMED]: web_app.py CSRF check (X-Requested-With / method allowlist) applies globally via before_request, no per-route gap found

**Files:** web_app.py  
**Lines:** web_app.py:166-209

**Problem:** Confirmed the CSRF-relevant check (state-changing requests must carry X-Requested-With: XMLHttpRequest when authenticated via Basic Auth) lives in a single @app.before_request hook applied unconditionally to all routes, not a per-route decorator a new route could accidentally omit. Enumerated all 60 @app.route definitions and all POST/DELETE routes (run_cron, cancel-cron, halt, resume, override POST/DELETE, forecast-cache/invalidate, paper-order, close-position) are covered by construction.

**Recommendation:** No action needed; note for future reviewers that this protection is central and would need to move with any auth-model change.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0069`), `audit/AUDIT_REPORT.md`.

### 5. AUD-0070 [INFO | HIGH | E1 | CONFIRMED]: Admin accuracy-circuit-breaker override (cluster M) confirmed CLI-only, not dashboard-reachable

**Files:** web_app.py, main.py, paper.py

**Problem:** Recon flagged this as worth checking. Confirmed by enumerating all @app.route definitions in web_app.py (60 routes) that none correspond to the accuracy-circuit-breaker override command added in 251e838e; it is reachable only via CLI.

**Recommendation:** No action needed; flag if a future change ever adds a dashboard route for this, since it would need its own explicit auth/CSRF consideration beyond the generic before_request check.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0070`), `audit/AUDIT_REPORT.md`.

### 6. AUD-0071 [INFO | VERY HIGH | E2 | CONFIRMED]: trade_cycle.py's STRONG/MED placement-gate mirror uses a different None-fallback for net_edge than the real validate() gate it mirrors

**Files:** trade_cycle.py, order_executor.py, weather_markets.py  
**Lines:** trade_cycle.py:467-471; trade_cycle.py:649-671; order_executor.py:2011-2015; weather_markets.py:7797-7902 (_price_and_size, single shared source of both fields)

**Problem:** Commit c9b0fc02 (and its follow-up 55918ede) added a mirror of order_executor._validate_trade_opportunity's edge gates into trade_cycle.py's STRONG/MED tier classification, specifically to prevent tier-classification from disagreeing with the real placement gate (the exact bug class of the KXHIGHTSEA-26AUG07-T85 live incident cited in that commit). I independently reproduced the mirror and the real gate side by side and found one residual discrepancy: trade_cycle's net_edge variable falls back None -> analysis.get('edge') -> 0.0, while validate()'s real edge variable falls back None -> 0.0 directly, with no raw-edge fallback.

**Recommendation:** No action required -- already documented and accepted by the team with correct reasoning, and my broader grep closes the remaining audit gap (hourly/arb paths) the original finding had left open, with the same 'unreachable' conclusion holding.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0071`), `audit/AUDIT_REPORT.md`.

### 7. AUD-0072 [INFO | HIGH | E1 | CONFIRMED]: log_prediction's UTC-based days_out fallback remains for callers that do not supply analysis days_out

**Files:** tracker.py  
**Lines:** 864-886

**Problem:** tracker.py's log_prediction() prefers analysis[days_out] (analyze_trade's city-local value) when present, but falls back to max(0, (market_date - utils.utc_today()).days) when the caller does not supply it, documented as covering shadow/lookup writes built from a bare market dict. This fallback still uses UTC and clamps at 0, so it can silently store days_out=0 for a trade whose real city-local days_out is 1 during the nightly window.

**Recommendation:** No action required beyond what is already documented; could adopt the same ZoneInfo pattern if this fallback path is revisited for other reasons.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0072`), `audit/AUDIT_REPORT.md`.

### 8. AUD-0073 [INFO | LOW | E1 | CONFIRMED]: ml_bias.get_emos_status() mislabels a concurrent EMOS deactivation race as file corruption

**Files:** ml_bias.py  
**Lines:** 1207-1222

**Problem:** get_emos_status() checks `_EMOS_PARAMS_PATH.exists()` then separately reads the file's contents; if deactivate_emos() deletes the file between the check and the read, the read raises FileNotFoundError, caught by a broad `except Exception` and reported as `{'active': False, 'corrupt': True, ...}` instead of the correct `{'active': False}`.

**Note:** this finding's structured record is missing root_cause, evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Read ml_bias.py:1207-1222 directly — confirmed the exists()-then-read_text() TOCTOU pattern and the single broad `except Exception` clause with no FileNotFoundError/JSONDecodeError distinction, matching the claim exactly. Confirmed deactivate_emos() (ml_bias.py:1352-1370) does unlink the file, making this a real (if narrow and low-impact) race. Practical severity genuinely low: get_emos_status is a diagnostic/status-display function, not a trading gate, and deactivate_emos is an infrequent operator-invoked action. No refutation found; original INFO severity and LOW confidence-in-practical-impact are appropriate.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0073`), `audit/AUDIT_REPORT.md`.

### 9. AUD-0074 [INFO | HIGH | E1 | CONFIRMED]: ForecastCache disk snapshot is last-writer-wins across independent processes

**Files:** forecast_cache.py  
**Lines:** forecast_cache.py:185-204; forecast_cache.py:206-227

**Problem:** ForecastCache/PersistentForecastCache's store is strictly in-process (self._store: dict), so separate cron/watch/web_app processes each hold an independent copy; dump_to_disk/load_from_disk round-trip through a single shared JSON file with no cross-process merge — the last process to dump_to_disk() wins and silently discards any newly-learned entries a losing process added.

**Recommendation:** No action needed given the low-impact caches involved; if this pattern is reused for higher-value state in the future, a read-merge-write should be considered.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0074`), `audit/AUDIT_REPORT.md`.

### 10. AUD-0075 [INFO | VERY HIGH | E1 | CONFIRMED]: web_app.py: two @_require_auth route decorators remain despite before_request comment claiming they were removed

**Files:** web_app.py:1911, web_app.py:1952, web_app.py:170-172

**Problem:** web_app.py's before_request handler comment states 'Route-level @_require_auth decorators were removed (WA-16)', but @_require_auth still decorates api_emos_status and api_weather_alerts.

**Recommendation:** Remove the two leftover decorators or update the before_request comment.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0075`), `audit/AUDIT_REPORT.md`.

### 11. AUD-0077 [INFO | VERY HIGH | E3 | CONFIRMED]: Verified: web_app.py's dev server does NOT block concurrent requests behind an open SSE stream, despite Werkzeug's own run_simple() defaulting threaded=False

**Files:** web_app.py  
**Lines:** web_app.py:3323 (_app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)); web_app.py:358-384 (/api/stream, infinite generator loop with time.sleep(10)); web_app.py:386-410 (/api/stream/markets, same shape); web_app.py:960 (in-code comment claiming 'Flask serves requests threaded (threaded=True default)')

**Problem:** Recorded for later passes' benefit so this isn't re-investigated: web_app.py's start_web() calls _app.run(...) without an explicit threaded=True, and Werkzeug's own werkzeug.serving.run_simple (installed version 3.1.8) defaults threaded=False -- which looked, from static reading alone, like it would let the two infinite-loop/time.sleep(10) SSE endpoints (/api/stream, /api/stream/markets, the former opened persistently by the React frontend's useData.js on every dashboard page load) serialize the single-threaded dev server, blocking every other request (page loads, /api/trades, /api/close-position, etc.) for as long as any browser tab stayed connected. This was verified empirically rather than reported on static evidence alone: built the real web_app._build_app(None) app and ran it via the exact production app.run(...) call, opened a persistent /api/stream connection, and fired 8 /api/status requests at 1s intervals while it stayed open (well inside the first 10s sleep window) -- all 8 completed in 57-270ms (mean 90ms), no delay observed. Root cause of the near-miss: Flask's own Flask.run() (confirmed via inspect.getsource(Flask.run)) does options.setdefault('threaded', True) before delegating to Werkzeug's run_simple, i.e. Flask overrides Werkzeug's own default -- so the in-code comment at web_app.py L960 claiming 'threaded=True default' is correct, just for the wrong layer (Flask's run(), not Werkzeug's run_simple()) than a naive read of Werkzeug's own signature would suggest.

**Recommendation:** No action needed. Documented here so a later pass doesn't re-spend time investigating the same (ultimately incorrect) hypothesis.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0077`), `audit/AUDIT_REPORT.md`.

### 12. AUD-0078 [INFO | HIGH | E1 | CONFIRMED]: ml_bias.py's HMAC sidecar write bypasses the codebase's atomic-write convention (but fails safe on a torn write anyway)

**Files:** ml_bias.py  
**Lines:** ml_bias.py:72-75; ml_bias.py:78-90; ml_bias.py:263,265 (pkl write, also non-atomic)

**Problem:** _write_hmac() writes the HMAC sidecar via a plain Path.write_text() call rather than safe_io.atomic_write_text/atomic_write_json. A process kill mid-write here could leave a truncated/corrupt .hmac file.

**Recommendation:** Low priority: route _write_hmac (and the adjacent .pkl write) through safe_io.atomic_write_text/atomic_write_bytes for consistency.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0078`), `audit/AUDIT_REPORT.md`.

### 13. AUD-0079 [INFO | MEDIUM | E1 | CONFIRMED]: Misleading test docstring in test_full_exit_race_loss_does_not_crash_the_caller

**Files:** tests/test_live_execution.py, order_executor.py  
**Lines:** tests/test_live_execution.py:2913-2960; order_executor.py:1352-1373

**Problem:** The test's docstring says '[the caller] must not raise -- and must not silently report success either', but the test body then asserts `result is True`. This isn't a bug: _exit_live_position's True/False return communicates whether the exchange fill itself succeeded (it did, in this scenario -- only the bookkeeping lost a race to a concurrent writer), and every current caller (order_executor.py's _check_live_position_exits -> store.exit(...)) discards the return value entirely, so there is no actual 'silently report success' failure mode to guard against today. The docstring overstates what the test proves.

**Recommendation:** Reword the docstring's final sentence, or note explicitly that the True/False contract has no current caller that branches on it (so if one is ever added, this test's assumption should be re-examined). NOTE: a caller that branches on it already exists (see verification_notes) -- the recommendation's hedge clause is already triggered, not merely hypothetical.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0079`), `audit/AUDIT_REPORT.md`.

### 14. AUD-0080 [INFO | HIGH | E2 | CONFIRMED]: Recent-commit test suite (2026-08-02..08-17) shows unusually high, self-critical test-writing discipline

**Files:** tests/test_trading_gates.py, tests/test_live_execution.py, tests/test_positions.py, tests/test_settlement_monitor.py, tests/test_rain_markets.py, tests/test_cron_integration.py, tests/test_trade_cycle_engine.py

**Problem:** Across all recent-commit-relevant test files sampled this pass, the dominant pattern is genuine, well-evidenced testing: exact numeric boundary pins (not loose ranges), positive controls proving a mocked branch is still reachable (e.g. TestCmdOrderLiveRecording's demo-mode sibling tests), documented mutation-testing results inline in docstrings, real (tmp-file/tmp-DB) end-to-end assertions rather than mock.called-only checks, and repeated instances of a prior test being caught as vacuous by an opus review round and rewritten to actually discriminate the bug it claims to guard against (e.g. test_rain_markets.py's TestRainForecastBlendSignal tail-tilt test explicitly documents 3 real bug shapes its earlier version would have missed). Ran a subset directly this session (tests/test_trading_gates.py + test_risk_control.py: 67/67 pass; tests/test_positions.py + test_web_auth.py + test_p0_16_cron_endpoint.py: 27/27 pass).

**Recommendation:** None required; noted so this audit's overall test-quality assessment isn't skewed toward assuming pervasive weak coverage based on the handful of gaps found above, which are genuine but narrow.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0080`), `audit/AUDIT_REPORT.md`.

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

This batch is documentation/test/low-risk-code only. If every item you actually touch turns out to be a small, mechanically-verifiable diff with no live-order/live-money/safety-gate surface and no multi-file span, steps 11-12 may collapse to the LOW tier (a single self-review pass + one Agent check instead of a dedicated opus effort:high spawn). Re-assess per item -- don't downgrade the whole batch by default if one item in it turns out bigger than expected.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
