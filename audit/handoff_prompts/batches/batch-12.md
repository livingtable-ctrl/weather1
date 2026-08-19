# Batch 12: Performance & reliability misc

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch comes from the 2026-08-18 max-depth forensic audit (`audit/AUDIT_REPORT.md` / `.json`). It groups 7 finding(s) that share **order_executor.py, trade_cycle.py, web_app.py, settlement_monitor.py** -- doing them together means you only load this subsystem's context once, and avoids two different sessions independently editing the same file in parallel. Live trading is currently dormant (`LIVE_TRADING_ENABLED` unset) -- no active financial exposure today for any item below, but treat items tagged HIGH/MEDIUM as touching a real live-order/live-money surface once trading is enabled.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. AUD-0021 [MEDIUM | VERY HIGH | E3 | CONFIRMED]: _log_shadow_predictions() re-opens the paper ledger and a fresh SQLite connection once per shadow ticker per cron cycle instead of once per batch

**Files:** order_executor.py, paper.py, tracker.py  
**Lines:** order_executor.py:2214-2291 (_log_shadow_predictions); order_executor.py:2617,2627,2637,2644,2654,2661 (per-ticker single-item call sites); order_executor.py:2364 (contrast: _open_trades_list fetched once for the main path); paper.py:396-405 (_load, full read+SHA256 every call); tracker.py:413-419 (_conn, fresh sqlite3.connect+3 PRAGMAs every call)

**Problem:** Commit 25aef473 correctly hoisted the 6 shadow-only gate booleans (_hourly_gates_active() etc.) to run once per _auto_place_trades() call instead of once per ticker, explicitly to stop wasting a live price refetch + 5000-sim VaR calc on shadow-only candidates. But the shadow-logging call it routes to, _log_shadow_predictions([item], live=live), is still invoked once PER shadow-routed ticker (6 separate call sites in the per-ticker loop, each passing a single-item list). Inside that function, every call does an unconditional paper.get_open_trades() -> paper._load() (full JSON read + SHA-256 checksum of the whole paper_trades.json ledger, no caching) and opens a brand-new tracker._conn() (sqlite3.connect + 3 PRAGMA statements against predictions.db) via `with tracker._conn() as _con:`. The function's own docstring claims this work is 'batched onto a single connection... rather than one connection open/close per opp', but every real call site defeats that by passing a single-item list, so no actual batching occurs across a scan's shadow tickers.

**Root cause:** The per-ticker shadow-routing loop in _auto_place_trades() (order_executor.py ~L2613-2665) calls _log_shadow_predictions() once per matching ticker instead of collecting all shadow-routed items and making one batched call after the loop (or reusing the already-open connection/already-loaded open_tickers set the main placement path establishes once at L2364-2367 for the very same purpose).

**Evidence:** Grepped all 6 call sites of _log_shadow_predictions in order_executor.py and confirmed each passes `[item]` (a single-item list), contradicting the function's own 'batched onto a single connection' docstring claim. Read paper._load() (paper.py L396-405) and tracker._conn() (tracker.py L413-419) and confirmed neither caches/memoizes -- both do real file/DB I/O on every call. Ran a direct timing benchmark (audit/reproductions/shadow_n_plus_1_bench.py) against the real main-clone data files (paper_trades.json: 234,053 bytes/233 trades; predictions.db: 47,280,128 bytes): _load()-equivalent (read+parse+sha256) averaged 3.20ms/call (n=30, min 2.19ms, max 6.14ms); _conn()-equivalent (sqlite3.connect+3 PRAGMAs) averaged 1.78ms/call (n=30, min 0.80ms, max 11.48ms). Projected added time per cron cycle scales with shadow-ticker count: ~53ms @5 tickers, ~158ms @15, ~317ms @30, ~528ms @50 -- all pure waste on top of what a single fetch-once-reuse pattern would cost.

**Financial risk:** None directly -- this only affects shadow (non-trading) prediction logging, not order placement or sizing. Indirect risk is limited to CPU/IO cost and (for the shadow families with low settlement velocity, e.g. hurricane-count/storm-order) a compounding, effectively-unbounded-duration inefficiency rather than a one-time cost.

**Recommendation:** Accumulate shadow-routed (ticker, item) pairs during the per-ticker loop instead of calling _log_shadow_predictions() inline per match; make one call with the full list after the loop (or before placement, preserving the existing ordering guarantee), letting the function's own single-connection/single-get_open_trades() design actually apply across the whole batch as documented.

**Limitations noted by the audit:** The benchmark approximates paper._validate_checksum's exact SHA-256 body (sha256 over a sorted json.dumps of the trades list) rather than importing paper.py directly, to avoid unrelated import-time/worktree-path side effects noted elsewhere in this audit's own environment notes -- the magnitude is representative but not a byte-for-byte reproduction of the real checksum computation. Did not instrument a live cron run to count real-world shadow-ticker batch sizes; the 5/15/30/50-ticker projections are illustrative scaling points, not measured live counts.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0021`), `audit/AUDIT_REPORT.md`.

### 2. AUD-0050 [LOW | HIGH | E1 | CONFIRMED]: trade_cycle.py's prewarm ThreadPoolExecutor tasks are not cancelled on timeout and outlive the phase that spawned them

**Files:** trade_cycle.py, cron.py  
**Lines:** trade_cycle.py:1136-1173; cron.py:2375-2377

**Problem:** _run_batch_prewarm_for_pairs submits up to 8 per-city-date prewarm tasks and waits on as_completed(warm_futures, timeout=200); on TimeoutError it only logs and falls through, and the finally: warm_pool.shutdown(wait=False) does not pass cancel_futures=True (default False) and cannot stop already-running worker threads regardless. Already-submitted _warm_one_tracked calls keep running on background threads while run_trade_cycle proceeds into the next (analysis) phase.

**Root cause:** shutdown(wait=False) only stops new task submission; it neither cancels queued futures nor interrupts running ones, so the 'prewarm phase' the rest of the code treats as finished is not actually over.

**Evidence:** Read trade_cycle.py:1136-1173 and cron.py:2375-2377 directly: as_completed(..., timeout=200) at line 1157, TimeoutError handling at 1164-1170 (log + fall through, no cancellation), shutdown(wait=False) at 1172, and cron.py's watchdog os._exit(1) hard-kill (no cleanup) at 2375-2377.

**Financial risk:** Low — the touched caches are internally locked, so this is a performance/hang-risk finding rather than a P&L-affecting one.

**Recommendation:** Pass cancel_futures=True to shutdown() (Python 3.9+) to at least drop queued-but-not-started tasks, and consider whether already-running prewarm threads need an explicit cooperative-cancellation flag if their side effects (cache writes) should not race with the next phase's reads.

**Limitations noted by the audit:** E1 — theoretical interpreter-hang consequence via atexit._python_exit was reasoned from documented CPython behavior, not observed directly this session.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0050`), `audit/AUDIT_REPORT.md`.

### 3. AUD-0053 [LOW | VERY HIGH | E3 | CONFIRMED]: web_app.py's /api/trades route loads the entire paper ledger twice in one request, with no caching across the ~7 routes (plus the /api/stream SSE loop) that each independently call get_open_trades()/get_all_trades()

**Files:** web_app.py, paper.py  
**Lines:** web_app.py:1405 (open_trades = get_open_trades()); web_app.py:1475 (all_trades = get_all_trades()); web_app.py:126, 1181, 1497, 3039 (other independent call sites); paper.py:1299-1301 (get_open_trades), 1922-1923 (get_all_trades), both -> _load(); paper.py:227 (_DATA_LOCK, cross-process file lock)

**Problem:** web_app.py's api_trades() (the handler for /api/trades) calls paper.get_open_trades() at L1405 and then paper.get_all_trades() at L1475 -- both route independently through paper._load(), which does a full open()+json.load()+SHA-256-checksum of data/paper_trades.json with no caching or memoization (see the companion finding on _log_shadow_predictions for _load()'s measured per-call cost). That's two full ledger reads to serve one HTTP request, when a single get_all_trades() call (filtering its own result for open trades) would suffice. More broadly, at least 7 distinct call sites across web_app.py (_build_stream_data used by the /api/stream SSE loop that re-fires every 10s for as long as any dashboard tab is open, /api/live_signals, /api/trades x2, /api/risk, /api/close-position, and one more status-adjacent site) each independently re-read and re-checksum the same file with zero request-scoped or short-TTL caching. The frontend's useData.js fires all 17 dashboard endpoints in parallel every 60s via Promise.allSettled, so several of these land at the same instant. The lock protecting these reads (_DATA_LOCK) is a cross-process file lock (Windows msvcrt.locking-based), so this also adds real inter-process contention against cron.py's own concurrent writes, not just in-process overhead.

**Root cause:** No shared/memoized read path exists for the paper ledger across web_app.py's routes; each route (and the SSE background loop) independently calls the public get_open_trades()/get_all_trades() functions, both of which unconditionally re-do the full read+parse+checksum on every call. This pattern predates the audited 2026-08-02..08-17 commit window (git blame on the get_all_trades() call site traces to 2026-04-10) and was not introduced or worsened by the in-window 709b0043 batch-fetch-quotes commit, which touches the same route but adds a genuinely single-call live-quote fetch alongside the pre-existing double-load, not a new one.

**Evidence:** Direct code read of web_app.py L1398-1478 (api_trades) shows both get_open_trades() and get_all_trades() called in the same function body. grep for get_open_trades()/get_all_trades() across web_app.py found 7+ independent call sites (L126, 1181, 1405, 1475, 1497, 1655, 1671, 3039). Confirmed paper._DATA_LOCK (paper.py L227) is a _CrossProcessDataLock instance, not a plain in-process threading.Lock. git blame on web_app.py:1475 traces the get_all_trades() call to a 2026-04-10 commit, predating this audit's commit window.

**Financial risk:** None -- read-only dashboard display path, does not affect trade sizing or placement.

**Recommendation:** In api_trades(), replace the get_open_trades()+get_all_trades() pair with one get_all_trades() call, deriving open_trades via a local filter (mirroring get_open_trades()'s own `[t for t in trades if not t['settled']]` logic) instead of a second _load(). Separately (broader, lower urgency given today's small ledger size), consider a short-TTL (a few seconds) in-process cache in front of paper._load() for read-heavy dashboard call sites, so parallel/near-simultaneous polls of different routes within the same refresh cycle share one read instead of each re-loading independently.

**Limitations noted by the audit:** At today's ledger size (234KB, 233 trades) the absolute cost of this redundancy is a few milliseconds per poll and not user-visible; this is flagged as a real but currently low-impact architectural issue that will scale linearly (and un-necessarily) as the ledger grows, rather than as a currently-measurable user-facing slowdown. Did not instrument the live dashboard under concurrent multi-tab load to measure real-world cross-process lock contention with cron.py running simultaneously.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0053`), `audit/AUDIT_REPORT.md`.

### 4. AUD-0025 [MEDIUM | HIGH | E1 | CONFIRMED]: No automated reconciliation between execution_log's internally-tracked live positions and Kalshi's real /portfolio/positions

**Files:** output_formatters.py, order_executor.py, kalshi_client.py  
**Lines:** output_formatters.py:425-443 (cmd_positions); kalshi_client.py:450-453 (get_positions)

**Problem:** kalshi_client.get_positions() is called from exactly one place in the entire codebase: output_formatters.cmd_positions(), a manual CLI display command. No automated code path (cron.py, trade_cycle.run_trade_cycle(), order_executor's pollers) ever cross-checks Kalshi's real position list against execution_log's internally tracked live positions.

**Root cause:** The bot's live-position tracking was designed as a self-contained ledger with crash-recovery for the specific placement-crash race, but no periodic ground-truth reconciliation against the exchange's own position endpoint was ever added.

**Evidence:** grep across the repo for '.get_positions(' confirms a single non-test call site (output_formatters.py:426). Confirmed cmd_positions is dispatched only from main.py's manual CLI branch (main.py:9694-9695, 'elif cmd == "positions": cmd_positions(client)'), not from any cron/trade_cycle/order_executor automated path.

**Financial risk:** A drifted internal ledger means the bot's protective-exit system could fail to manage a real position the exchange shows but execution_log does not track. Currently low-probability given existing crash-recovery coverage, but no safety net exists for cases that coverage doesn't handle.

**Recommendation:** Add a lightweight reconciliation check (e.g. inside cmd_watch's cycle or a dedicated cron step) comparing client.get_positions() against tracked live positions, logging a warning on mismatch.

**Limitations noted by the audit:** Did not attempt to induce an actual drift scenario (requires live credentials/orders, out of scope).

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0025`), `audit/AUDIT_REPORT.md`.

### 5. AUD-0029 [MEDIUM | HIGH | E1 | CONFIRMED]: emos-train/emos-deactivate check cron-in-flight before an unbounded human confirmation prompt, not immediately before the write

**Files:** main.py  
**Lines:** main.py:6682-6693; main.py:6820-6830

**Problem:** Both the EMOS activation and deactivation commands call `_cron_module._is_cron_running()` once, then print a confirmation prompt and block on `input()` for an arbitrary human-paced duration, then on 'yes' proceed straight to save_emos_params()/deactivate_emos() with no re-check immediately before the write. A cron cycle that starts during the confirmation window is invisible to this gate.

**Root cause:** Classic check-then-(long-wait)-then-act TOCTOU: the safety check runs before the unbounded-duration side effect (waiting on a human), not after it.

**Evidence:** Read main.py:6663-6753 (activation) and 6788-6849 directly: `_is_cron_running()` called once, followed by `input()`, followed by the write with no second check in between.

**Financial risk:** The failure mode this gate exists to prevent — 'one scan split across two probability methods, some markets priced with the old method, some with EMOS' (per the check's own error message) — can still occur if a cron cycle starts during the confirmation wait, resulting in inconsistent pricing within a single scan.

**Recommendation:** Re-check _is_cron_running() (or better, acquire the actual cron lock) immediately before writing EMOS params, not just before printing the prompt.

**Limitations noted by the audit:** E1 only — static evidence, not a runtime-observed race, since exercising it requires synchronizing an interactive input() prompt with a real cron cycle start.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0029`), `audit/AUDIT_REPORT.md`.

### 6. AUD-0047 [LOW | HIGH | E1 | CONFIRMED]: settlement_monitor.py logs per-city polling failures at DEBUG only, invisible on console for an unattended daily task

**Files:** settlement_monitor.py, main.py, cron.py  
**Lines:** settlement_monitor.py:591-592; settlement_monitor.py:599-600; main.py:9475-9490 (logging setup); cron.py:2053-2058 (analogous debug->warning fix elsewhere)

**Problem:** The only two exception handlers in run_settlement_monitor's polling loop (market-fetch failure at 591-592, general per-city error at 599-600) both log at DEBUG level. main.py's logging setup routes DEBUG to the file handler but the console handler is INFO, so these lines reach bot.log but are invisible during an interactive run.

**Root cause:** The per-city error handling was left at DEBUG when the module was manual/dormant; commit 64c08693 scheduled it as a real unattended daily cron task without revisiting the log level, unlike the analogous ML-retrain block in cron.py which was deliberately bumped from debug to warning with an explicit comment about DEBUG lines being 'effectively invisible' days apart.

**Evidence:** Independently re-read settlement_monitor.py:510-608 (the full polling loop), confirming these are the only two exception handlers, both at exactly lines 591-592 and 599-600, both `_log.debug()`. Confirmed main.py's console handler level (9485, logging.INFO) vs. file handler (9481, logging.DEBUG) via direct read. Confirmed the analogous fix pattern in cron.py:2053-2058 via direct read.

**Financial risk:** None directly (this signal path is documented as currently dormant); primarily an operability/observability gap.

**Recommendation:** Bump these two handlers to WARNING, matching the reasoning already applied to cron.py's ML-retrain block in the same commit window.

**Limitations noted by the audit:** Impact is currently limited since bot.log does capture the DEBUG line, and the underlying signal is separately documented as dormant today.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0047`), `audit/AUDIT_REPORT.md`.

### 7. AUD-0048 [LOW | HIGH | E1 | CONFIRMED]: execution_log.py and tracker.py never explicitly close SQLite connections

**Files:** execution_log.py, tracker.py  
**Lines:** execution_log.py:108-113 (_conn); tracker.py:413 (_conn)

**Problem:** _conn() in both files returns a raw sqlite3.connect(...) object used via `with _conn() as con:`. sqlite3.Connection's context-manager protocol only commits/rolls back the transaction on exit -- it does not close the connection. Neither file ever calls con.close().

**Root cause:** The `with _conn() as con:` idiom is commonly (and incorrectly) assumed to close the connection the way file-object context managers do; sqlite3.Connection's __exit__ only manages the transaction.

**Evidence:** Independently re-ran the grep: execution_log.py has exactly 21 `with _conn() as con:` blocks and 0 `con.close()` calls; tracker.py has exactly 105 and 0 respectively -- both counts match the finding's own citation exactly. Confirmed execution_log.py:108-113 `_conn()` returns a raw `sqlite3.connect(DB_PATH, timeout=30)` with no pooling wrapper.

**Financial risk:** None observed.

**Recommendation:** No urgent action needed given CPython's refcounting behavior; consider explicit con.close() in a finally block if this code is ever run under an alternate Python implementation or under heavy concurrent connection churn.

**Limitations noted by the audit:** Long-standing, low-severity pattern; not connected to the recent commit window specifically.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0048`), `audit/AUDIT_REPORT.md`.

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

At least one item in this batch touches a live-order/live-money/safety-gate path (or is adjacent enough to warrant it) -- this batch does **not** qualify for the steps 11-12 LOW-tier downgrade. Apply the full ceremony as written, all 29 steps, for the batch as a whole.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
