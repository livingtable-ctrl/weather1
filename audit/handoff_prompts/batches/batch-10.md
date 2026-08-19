# Batch 10: Test-gap sweep

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch comes from the 2026-08-18 max-depth forensic audit (`audit/AUDIT_REPORT.md` / `.json`). It groups 6 finding(s) that share **tests/*.py, conftest.py** -- doing them together means you only load this subsystem's context once, and avoids two different sessions independently editing the same file in parallel. Live trading is currently dormant (`LIVE_TRADING_ENABLED` unset) -- no active financial exposure today for any item below, but treat items tagged HIGH/MEDIUM as touching a real live-order/live-money surface once trading is enabled.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. AUD-0023 [MEDIUM | HIGH | E1 | CONFIRMED]: Accuracy-circuit-breaker admin override has no test proving it actually lifts the LIVE trading gate

**Files:** tests/test_risk_control.py, tests/test_trading_gates.py, trading_gates.py, paper.py, main.py  
**Lines:** trading_gates.py:75-110

**Problem:** Commit 251e838e added `py main.py admin accuracy-override` and its own commit message states this override 'also silently lifts the LIVE-order gate, trading_gates.LiveTradingGate calls the same is_accuracy_halted()'. tests/test_risk_control.py (36 tests) exercises the override exclusively against paper.is_accuracy_halted() called directly. tests/test_trading_gates.py's TestLiveTradingGate class always patches `paper.is_accuracy_halted` with a hardcoded return_value (grepped every occurrence: lines 38, 99, 114, 129, 158, 174, 189, 204, 450, 480 -- all `patch("paper.is_accuracy_halted", return_value=...)`), never with a real ACCURACY_HALT_OVERRIDE_PATH file active. Grepped the whole tests/ directory for ACCURACY_HALT_OVERRIDE / accuracy_override / accuracy-override: only tests/conftest.py (the autouse isolation fixture) and tests/test_risk_control.py reference it at all.

**Root cause:** The override mechanism and the live-trading gate are tested as two separate units, each with the other's real state mocked away, so the integration point the commit message specifically calls out as risky is never exercised end-to-end.

**Evidence:** Ran `grep -n "is_accuracy_halted" trading_gates.py` -> confirmed trading_gates.py imports and calls the exact same paper.is_accuracy_halted function (trading_gates.py:75,107). Ran `grep -rln "ACCURACY_HALT_OVERRIDE\|accuracy_override\|accuracy-override" tests/*.py` -> only conftest.py and test_risk_control.py. Ran `grep -n "accuracy_halt_override\|is_accuracy_halted\|ACCURACY_HALT_OVERRIDE" tests/test_trading_gates.py` -> zero matches for the override-specific names.

**Financial risk:** Low likelihood, but a broken live-gate wiring in the direction of 'override no longer works' would leave a legitimately-recovering bot stuck halted (opportunity cost only); wiring broken the other way (override reaching the live gate more permissively than documented) has no evidence of existing -- flagged purely as an untested path, not an observed bug.

**Security risk:** None directly -- this is a CLI-only admin command, not dashboard-reachable per the commit's own scope statement.

**Recommendation:** Add one integration test in test_risk_control.py or test_trading_gates.py that sets a real accuracy-halt override and calls trading_gates.LiveTradingGate.check() end-to-end (all other gates mocked to pass), asserting allowed=True, plus a companion test proving an EXPIRED override does not.

**Limitations noted by the audit:** Did not attempt to construct the missing integration test or verify by running one; this finding is about absence of coverage, not a demonstrated wiring bug.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0023`), `audit/AUDIT_REPORT.md`.

### 2. AUD-0054 [LOW | HIGH | E1 | CONFIRMED]: frontend authHeader() has no unit test asserting the CSRF header is present in its output

**Files:** frontend/src/useData.js, frontend/src/useData.test.js  
**Lines:** frontend/src/useData.js:28-39

**Problem:** The same 0edf818b commit fixed a real bug where one of the two frontend trees' useData.js never sent the X-Requested-With header at all, causing every POST to 401 unconditionally even with the correct password. frontend/src/useData.test.js has no unit test that calls authHeader() directly and asserts the returned object includes 'X-Requested-With': 'XMLHttpRequest' -- coverage of the header only exists implicitly, through fetchAllSafe's mocked-fetch assertions which check the Authorization value but never the CSRF header value (grepped the whole file for 'Requested': only appears in a code comment).

**Root cause:** Test suite validates the auth-retry orchestration logic (fetchAllSafe) thoroughly but never unit-tests the small, security-relevant authHeader() helper itself in isolation.

**Evidence:** `grep -n "Requested\|headers" frontend/src/useData.test.js` -> only two matches, both about the Authorization field, none about X-Requested-With.

**Financial risk:** None -- purely a client-side regression-guard gap; the server-side enforcement (see the companion finding above) is the actual security boundary, and that too is untested for this exact property, compounding the risk that a silent regression on either side goes unnoticed.

**Security risk:** Low on its own since the server independently enforces the header; but combined with the server-side test gap, there is no automated safety net if a future refactor drops the header from either side.

**Recommendation:** Add a small describe('authHeader') block asserting the CSRF header's presence and value in both the password-set and password-unset cases.

**Limitations noted by the audit:** Frontend test suite (vitest) was not executed this session (nor in this verification pass); this finding is based on static review of the test file's content only.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0054`), `audit/AUDIT_REPORT.md`.

### 3. AUD-0055 [LOW | HIGH | E1 | CONFIRMED]: cmd_order's multi-open-live-position-per-ticker sell branch is untested

**Files:** main.py, tests/test_trading_gates.py, tests/test_live_execution.py  
**Lines:** main.py ~4574-4640 (per git show e5331a8d diff)

**Problem:** e5331a8d's cmd_order live-sell matching logic explicitly handles (and warns about) the case where more than one tracked open live position shares the same ticker+side: it closes only the oldest (by placed_at ascending, confirmed via execution_log.get_filled_unsettled_live_orders()'s `ORDER BY placed_at`), prints an operator warning naming the untouched positions, and leaves the rest open. This is a deliberately-scoped partial fix (the commit's own comment references a separate, unaddressed backlog entry for the structural fix). No test in tests/test_trading_gates.py's TestCmdOrderLiveRecording class or tests/test_live_execution.py exercises this branch: no test creates two live positions with the same ticker+side and verifies (a) the warning prints, (b) exactly the oldest is closed, (c) the newer position(s) remain open and untouched afterward.

**Root cause:** The commit's positive/negative-control test suite covers the single-match and no-match cases thoroughly but the explicitly-called-out multi-match edge case has no test.

**Evidence:** `grep -rn "oldest\|multiple.*tracked live\|len(_live_open_matches)" tests/*.py` -> no matches referencing this code path at all (only unrelated 'oldest' usages in other test files).

**Financial risk:** Low -- this is an already-documented, operator-visible partial fix (the warning message itself is the safety net for a human), not a silent failure mode; but an untested behavior can regress silently (e.g. accidentally closing the newest instead of oldest, or crashing) on a future refactor.

**Recommendation:** Add TestCmdOrderLiveRecording::test_live_sell_with_multiple_tracked_positions_closes_only_oldest, matching the style of the file's existing tests.

**Limitations noted by the audit:** Did not construct or run the missing test; relying on static code read (order_executor.py / execution_log.py SQL) to confirm the described 'closes oldest' behavior is what the code currently does.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0055`), `audit/AUDIT_REPORT.md`.

### 4. AUD-UNMATCHED-56 [MEDIUM | HIGH | E1 | CONFIRMED]: web_app.py's CSRF header enforcement (X-Requested-With) has no test that proves it is actually enforced

**Files:** web_app.py, tests/test_web_auth.py, tests/test_p0_16_cron_endpoint.py, tests/test_web_app.py  
**Lines:** web_app.py:166-209

**Problem:** Commit 0edf818b added a required X-Requested-With: XMLHttpRequest header as the sole CSRF mitigation for all state-changing dashboard endpoints (web_app.py:198-201: `if _flask_request.method in ("GET","HEAD","OPTIONS") or (headers.get("X-Requested-With")=="XMLHttpRequest"): return None` else falls through to a 401). Every existing 'auth succeeds' test (tests/test_web_auth.py's `_basic_auth()` helper, tests/test_p0_16_cron_endpoint.py's identical helper) bundles Authorization AND X-Requested-With together in one dict, so success is only ever tested with both present. The 'auth fails' tests send no Authorization header at all. No test sends a request with a CORRECT password and NO X-Requested-With header and asserts it is rejected -- the specific branch that constitutes the actual CSRF protection.

**Root cause:** Test helpers were written to build a single combined 'valid request' header set rather than isolating the two independent conditions (valid password; valid CSRF header) the auth check ANDs together.

**Evidence:** `grep -n "X-Requested-With\|def test_" tests/test_web_auth.py` shows _basic_auth() always includes both headers, and every 'succeeds' test uses that helper unmodified; the 'without_auth' tests omit Authorization entirely, not just the CSRF header. Same pattern confirmed in tests/test_p0_16_cron_endpoint.py's identical `_basic_auth`. `grep -rln "X-Requested-With" tests/*.py` -> only these two files. `grep -n "Authorization.*Basic\|_basic_auth\|_auth_headers" tests/test_web_app.py` -> only one GET request (exempt from the CSRF check by design), never a POST.

**Financial risk:** None directly observed; this is a defense-in-depth mechanism protecting kill-switch/halt/resume/order-placement endpoints from CSRF. An undetected regression that silently drops the header check would reopen a documented CSRF vector (a malicious page driving a plain <form> POST at these endpoints while the operator has the dashboard open with cached Basic Auth) with no test failure to surface it.

**Security risk:** Regression in a CSRF mitigation for state-changing endpoints including kill-switch and order placement would go undetected by the test suite.

**Recommendation:** Add test_halt_with_correct_password_but_no_csrf_header_returns_401 (and similarly for /api/run_cron, /api/resume) using a header dict with only Authorization set, asserting 401 -- mirroring the existing wrong-password test's structure but isolating the other half of the AND condition.

**Limitations noted by the audit:** Did not modify _check_auth to confirm a regression here would actually pass the rest of the suite silently (that follows directly from the grep evidence, but was not separately verified by mutation-testing this session).

Full record: `audit/AUDIT_REPORT.json` (id `AUD-UNMATCHED-56`), `audit/AUDIT_REPORT.md`.

### 5. AUD-0058 [LOW | VERY HIGH | E1 | CONFIRMED]: METAR calibration production-file write isolation relies on per-test monkeypatches, not an autouse structural guard

**Files:** ml_bias.py, tests/conftest.py, tests/test_ml_bias.py  
**Lines:** ml_bias.py:22; tests/test_ml_bias.py:1863-1958; tests/test_ml_bias.py:1960+

**Problem:** ml_bias.py:22 binds _METAR_CALIBRATION_PATH from paths.METAR_CALIBRATION_PATH at import time. tests/conftest.py has no autouse fixture redirecting this path (only the in-memory _METAR_CACHE/_TEMP_CACHE get autouse isolation). 5d9b6c56's commit message (2026-08-16) confirms this exact gap already caused a real incident: a test's attempt to monkeypatch paths.METAR_CALIBRATION_PATH didn't reach ml_bias._METAR_CALIBRATION_PATH (same import-time-binding hazard as this project's own documented 'monkeypatch env vs attr' pattern), silently writing synthetic coefficients to the real production data file.

**Root cause:** No structural (autouse) isolation exists for this specific file path the way it does for tracker.DB_PATH (isolate_tracker_db) or the climatology caches; correctness currently depends on every test author remembering to patch ml_bias._METAR_CALIBRATION_PATH directly.

**Evidence:** ml_bias.py:22 import-time binding confirmed by read. grep -n -i metar tests/conftest.py shows no autouse fixture for METAR_CALIBRATION_PATH, only in-memory cache fixtures. 5d9b6c56 commit message quoted verbatim describes the prior incident. tests/test_ml_bias.py's TestFitAndSaveMetarCalibration (1863-1958) and TestCmdCalibrateMetarBlock (1960+) both currently patch ml_bias._METAR_CALIBRATION_PATH directly at lines 1907/1950/2010/2049.

**Financial risk:** Low direct financial risk, but a repeat incident would corrupt the production METAR calibration coefficients file, degrading the live temperature-bias correction used in real trade signal generation until manually caught and restored.

**Recommendation:** Add an autouse conftest.py fixture redirecting ml_bias._METAR_CALIBRATION_PATH to tmp_path, mirroring isolate_tracker_db and the climatology cache-dir fixtures.

**Limitations noted by the audit:** E1 — static evidence plus a historical commit message describing a real past occurrence of exactly this gap, not a fresh reproduction this session.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0058`), `audit/AUDIT_REPORT.md`.

### 6. AUD-0059 [LOW | MEDIUM | E1 | CONFIRMED]: No test coverage for check_position_limits() vs execution_log interaction

**Files:** tests/  
**Lines:** tests/test_hurricane_gating.py:352-478 (false-positive match, unrelated execution_log mock)

**Problem:** Despite e5331a8d adding 188 new/changed tests across main.py/order_executor.py/execution_log.py (including a new 470-line tests/test_trading_gates.py), no test asserts or documents whether check_position_limits()'s exposure sums should or do include execution_log-tracked live positions.

**Root cause:** The interaction between check_position_limits() (paper.py) and execution_log (added/expanded across cluster D commits) was never covered by a dedicated test, consistent with the finding above being filed as a known gap rather than an actively-guarded one.

**Evidence:** Re-ran the finding's cited command this session: `grep -rl check_position_limits tests/ | xargs grep -l execution_log` actually returns `tests/test_hurricane_gating.py` -- NOT empty, contradicting the finding's literal stated evidence ('returns no files at HEAD'). Inspected that file's execution_log reference (around line 478): it is an unrelated monkeypatch of `execution_log.was_recently_ordered` inside a duplicate-order-guard test, with no relationship to exposure caps or live-position visibility. Checked all 7 other files referencing check_position_limits (test_hourly_markets.py, test_hurricane_markets.py, test_p1_remaining.py, test_phase2_batch_i.py, test_rain_markets.py, test_snow_markets.py, test_web_app.py) -- none reference execution_log at all. So the substantive conclusion (no test covers this interaction) holds, but the finding misreported its own grep's output.

**Financial risk:** Indirect -- absence of test coverage makes the Finding-1 gap easier to miss or reintroduce in future refactors.

**Recommendation:** Add a test exercising check_position_limits() against a scenario with an open execution_log live position, documenting current behavior (blind) so any future fix has a clear before/after test.

**Limitations noted by the audit:** None beyond standard test-gap caveats.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0059`), `audit/AUDIT_REPORT.md`.

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

At least one item in this batch touches a live-order/live-money/safety-gate path (or is adjacent enough to warrant it) -- this batch does **not** qualify for the steps 11-12 LOW-tier downgrade. Apply the full ceremony as written, all 29 steps, for the batch as a whole.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
