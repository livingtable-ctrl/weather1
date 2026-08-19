# Batch 4: Concurrency / locking

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch comes from the 2026-08-18 max-depth forensic audit (`audit/AUDIT_REPORT.md` / `.json`). It groups 4 finding(s) that share **cron.py, main.py, settlement_monitor.py, paper.py** -- doing them together means you only load this subsystem's context once, and avoids two different sessions independently editing the same file in parallel. Live trading is currently dormant (`LIVE_TRADING_ENABLED` unset) -- no active financial exposure today for any item below, but treat items tagged HIGH/MEDIUM as touching a real live-order/live-money surface once trading is enabled.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. AUD-0006 [HIGH | VERY HIGH | E2 | CONFIRMED]: cron._acquire_cron_lock() has a TOCTOU race with no OS-level exclusive-create primitive — reproduced

**Files:** cron.py  
**Lines:** cron.py:205-286

**Problem:** _acquire_cron_lock() checks `if lp.exists(): ...` and, several lines later, calls `lp.write_text(json.dumps(lock_data))` with no intervening OS-level exclusive-create (no O_EXCL open, no msvcrt.locking, no atomic rename-based claim). Two processes racing to acquire the lock when it does not yet exist (or has just gone stale) can both observe exists()==False and both proceed to write, each believing it holds exclusive ownership. This is the ONLY mechanism serializing cmd_cron (cron.py:2409) against cmd_watch --auto's own trade cycle (main.py:3622), web_app.py's /api/run_cron spawn path, and the emos-train/emos-deactivate 'cron in flight' pre-checks (main.py:6682, 6820).

**Root cause:** Check-then-act file existence test followed by a plain (non-exclusive) write, instead of an atomic O_EXCL create or a real OS file lock (contrast with paper.py's _CrossProcessDataLock, which does use msvcrt.locking for its own file).

**Evidence:** Self-reproduced this session by running audit/reproductions/cron_lock_race_repro.py (redirects cron.LOCK_PATH to a tempdir, monkeypatches pathlib.Path.exists to rendezvous two threads at a threading.Barrier the instant both have evaluated `if lp.exists():`, then releases both into the write path). Output: `results: [True, True]` — both callers of _acquire_cron_lock() returned True, i.e. both believe they hold the exclusive lock.

**Financial risk:** If two lock holders both run a trade cycle concurrently, each can independently detect the same open live position needing a protective exit (verified cron.py:912-919 calls _check_live_position_exits/_check_live_model_exits on live positions left open from a prior watch --auto --live session) and each submit its own real IOC sell order to Kalshi. execution_log.record_live_exit_fill's compare-and-set (execution_log.py:648-681,734+) prevents double-counting the P&L row but cannot prevent the second real order from reaching the exchange, since that gate only runs after both orders have already been placed. Also amplifies execution_log.was_recently_ordered/was_traded_today (execution_log.py:278-325), which are plain SELECT-then-later-INSERT checks with no DB UNIQUE constraint and rely entirely on this lock's (currently broken) single-holder guarantee.

**Security risk:** None (not attacker-reachable — requires two legitimate local invocations racing).

**Recommendation:** Replace the exists()-then-write_text() pattern with an atomic exclusive-create, e.g. `open(lp, 'x')` (raises FileExistsError if the file already exists) wrapped in the same fail-closed exception handling already present, or reuse paper.py's msvcrt-based _CrossProcessDataLock primitive for this file too.

**Limitations noted by the audit:** Reproduced via two threads within one process racing on Path.exists/write_text, which validates the code-level TOCTOU logic; a fully faithful two-OS-process reproduction was not attempted this session (not necessary to establish the flaw, since the race window is in the shared function's own logic regardless of thread vs. process boundary).

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0006`), `audit/AUDIT_REPORT.md`.

### 2. AUD-0039 [LOW | HIGH | E2 | CONFIRMED]: Kill-switch override rename race can crash cmd_cron with uncaught FileExistsError (Path.rename vs os.replace semantics gap)

**Files:** main.py, cron.py, alerts.py  
**Lines:** main.py:286-354; cron.py:2346-2379; cron.py:1034-1058; alerts.py:564-583

**Problem:** main.py's cmd_cron() wrapper implements a one-shot interactive override for the kill switch: when an operator answers 'y' to 'Override and run this cycle anyway?', it does `_kill_path.rename(_kill_tmp)` (main.py:332) to temporarily move .kill_switch out of the way, restoring it in a `finally` block afterward. This rename is NOT wrapped in try/except. Unlike the rest of the codebase's atomic-write infrastructure (safe_io.atomic_write_json / os.replace, hardened across cluster J commits 94d36402/3a28ae33 specifically because Path.rename()/os.replace() differ on Windows), this call site uses Path.rename(), which raises FileExistsError if the destination already exists, rather than atomically replacing it the way os.replace() does. The repo's own bare-os.replace bypass guard test only regex-matches `os.replace(`, not `.rename(`, so these 3 rename call sites (all in this one function) were never brought into that migration's scope.

**Root cause:** A stale .kill_switch.tmp can be left on disk if the cron watchdog (cron.py:2375 os._exit, 720s timeout) hard-kills the process mid-override-cycle (os._exit bypasses Python `finally` blocks, so the restore-from-tmp step at main.py:346-350 never runs). If, in that same aborted cycle, a black-swan check re-creates .kill_switch (a scenario the finally block's own comment explicitly anticipates: 'black swan re-created it during the run'), the next manual cmd_cron invocation's stale-tmp-restore guard (main.py:290: `_kill_stale_tmp.exists() and not _kill_path.exists()`) is False -- because .kill_switch now exists again -- so the orphaned .kill_switch.tmp is never cleaned up. If the operator then answers 'y' to another override prompt, main.py:332's rename target (.kill_switch.tmp) already exists, and Path.rename() raises FileExistsError uncaught.

**Evidence:** Grepped `\.rename(` across the entire repo (excluding tests/audit) -- exactly 3 hits, all in main.py's cmd_cron wrapper (lines 292, 332, 350); only line 332 is unguarded by try/except or a pre-check that the destination is absent. Directly reproduced in this Windows environment this session: `pathlib.Path('a').rename(pathlib.Path('b'))` where b already exists raises `FileExistsError [WinError 183] Cannot create a file when that file already exists`. Independently confirmed cron.py:2375 `os._exit(1)` is a real watchdog armed inside cron.cmd_cron (reached from main.py's override branch at L342), with its own comment 'hard kill -- no cleanup; preferred over sys.exit so finally blocks don't re-hang'. Independently confirmed the 'black swan re-created it' scenario is a real code path, not speculative: alerts.py:564 activate_black_swan_halt() calls _KILL_SWITCH_PATH.touch() (L582), and cron.py:1034 runs run_black_swan_check unconditionally every cycle including during a user override (per the surrounding comment).

**Financial risk:** Low/none directly -- the kill switch remains present/active throughout this failure (fail-safe direction: trading stays halted), and the crash only occurs on a manual interactive `py main.py cron` invocation (the automated loop path skips this whole block via `_called_from_loop`). The practical harm is an operator being unable to cleanly run a one-shot override cycle exactly when investigating a black-swan-triggered halt, receiving an unhandled traceback instead.

**Recommendation:** Use os.replace() (or safe_io's retry-wrapped equivalent) instead of Path.rename() at main.py:332/292/350 so the operation is atomic-replace rather than fail-on-exists; additionally, change the stale-tmp-restore guard at main.py:290 to also unlink an orphaned .kill_switch.tmp when .kill_switch already exists (mirroring the finally block's own `if _kill_tmp.exists(): if _kill_path.exists(): _kill_tmp.unlink()` logic), rather than only handling the not-exists case.

**Limitations noted by the audit:** The full compound race requires a specific timing overlap (watchdog firing while a black-swan event recreates .kill_switch within the same override cycle) that is plausible but not common; the end-to-end multi-step scenario was not executed live, only each individual link independently confirmed in source. Underlying rename-failure mechanism itself is directly reproduced (E2).

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0039`), `audit/AUDIT_REPORT.md`.

### 3. AUD-0051 [LOW | HIGH | E1 | CONFIRMED]: settlement_monitor.py has no application-level overlap guard; relies entirely on unverified Task Scheduler default policy

**Files:** settlement_monitor.py, main.py  
**Lines:** settlement_monitor.py:126-133; main.py:9142-9179

**Problem:** The daily Task Scheduler entry (schtasks /Create /F /SC DAILY ...) has no analogue of cron.py's LOCK_PATH mechanism; protection against two overlapping runs relies entirely on Windows Task Scheduler's default 'do not start a new instance' policy, which is not explicitly set by the schtasks /Create call and could be silently changed by an operator editing the task's Settings tab.

**Root cause:** No file-lock or PID-based mutual exclusion was added when settlement_monitor.py was wired up as its own scheduled job (commit 64c08693); the module has no lock/PID logic at all.

**Evidence:** Grepped settlement_monitor.py for lock/PID logic — none found (only unrelated METAR 'lock-in' domain terminology unrelated to concurrency). write_settlement_signals (settlement_monitor.py:126-133) performs a full atomic_write_json({'signals': signals, ...}, _SIGNALS_PATH) — a wholesale overwrite of the entire file from the calling process's own in-memory list, not a merge. Verified main.py:9142-9179's schtasks /Create /F /SC DAILY ... registration has no explicit instance-policy flag.

**Financial risk:** A dropped settlement-lag signal could delay a force-close decision that depends on it (per cluster K's settlement-lag force-close gate wiring), though this requires two overlapping runs to actually occur, which is not the documented/intended configuration.

**Recommendation:** Add a lightweight lock (reuse cron.py's pattern, corrected per Finding 1, or paper.py's msvcrt-based lock) to settlement_monitor.py's entry point, independent of whatever Task Scheduler's actual configured overlap policy is.

**Limitations noted by the audit:** Could not verify the actual live Task Scheduler configuration on the user's machine (only the schtasks /Create invocation in source) — the real-world overlap risk depends on settings outside this repo.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0051`), `audit/AUDIT_REPORT.md`.

### 4. AUD-0030 [MEDIUM | HIGH | E2 | CONFIRMED]: paper._CrossProcessDataLock silently fails OPEN after 10 seconds of sustained contention

**Files:** paper.py  
**Lines:** paper.py:171-199

**Problem:** _acquire_file_lock() retries msvcrt.locking for up to a 10.0s deadline (paper.py:180); on continued OSError past the deadline it logs a warning, closes the file handle, and returns without ever setting self._fh (paper.py:187-193). _release_file_lock() then no-ops for that call, and the caller's read-modify-write on paper_trades.json proceeds with no cross-process lock held at all — reverting to exactly the pre-fix in-process-only protection the class's own docstring (paper.py:132-136) says is insufficient ('a load in one could straddle a save in the other and silently revert a settlement or drop a manually-placed trade').

**Root cause:** Deliberate liveness-over-safety tradeoff ('Never let the locking mechanism itself take down trading') — but the fallback silently drops the cross-process safety guarantee entirely rather than e.g. failing the operation or retrying with backoff beyond 10s.

**Evidence:** Read paper.py:171-199 directly. Verified the positions.update_peak_profits (fc8e3555-era) caller comment cited exists at paper.py:1396-1405 and matches the described risk of silently lowering an already-higher peak or writing a peak onto a trade the other process already closed.

**Financial risk:** A lost update to paper_trades.json under this fallback could silently revert a settlement or drop a manually-placed paper trade, corrupting the paper ledger's accuracy (which downstream graduation_check()/accuracy-halt logic and the live-trading gate chain both depend on).

**Recommendation:** At minimum, log this fallback path at a severity that would page/alert an operator (not just warning), and consider whether 10s is long enough given three independent long-lived processes (cron, watch, web_app) can all touch this file.

**Limitations noted by the audit:** E1 — did not attempt to actually drive msvcrt.locking into 10s of contention to observe the fallback firing live.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0030`), `audit/AUDIT_REPORT.md`.

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

At least one item in this batch touches a live-order/live-money/safety-gate path (or is adjacent enough to warrant it) -- this batch does **not** qualify for the steps 11-12 LOW-tier downgrade. Apply the full ceremony as written, all 29 steps, for the batch as a whole.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
