# Batch 1: Live-position visibility (coordinated root cause)

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch comes from the 2026-08-18 max-depth forensic audit (`audit/AUDIT_REPORT.md` / `.json`). It groups 6 finding(s) that share **paper.py, order_executor.py** -- doing them together means you only load this subsystem's context once, and avoids two different sessions independently editing the same file in parallel. Live trading is currently dormant (`LIVE_TRADING_ENABLED` unset) -- no active financial exposure today for any item below, but treat items tagged HIGH/MEDIUM as touching a real live-order/live-money surface once trading is enabled.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. AUD-0001 [HIGH | VERY HIGH | E2 | CONFIRMED]: check_position_limits() exposure caps are structurally blind to live positions opened via cmd_order (regression introduced by the e5331a8d live-fill-routing fix)

**Files:** paper.py, main.py  
**Lines:** paper.py:3447; paper.py:1299-1301; paper.py:1598-1673; paper.py:3629-3685; main.py:4528-4569

**Problem:** check_position_limits()'s exposure accounting was designed around a single ledger (paper_trades.json) that, prior to e5331a8d, happened to also receive live fills. e5331a8d correctly stopped writing live fills into that ledger but did not add execution_log-sourced live exposure into check_position_limits' accounting.

**Evidence:** Independently read paper.py:3447-3686 (check_position_limits full body), paper.py:1299-1301 (get_open_trades reads only paper_trades.json), paper.py:1598-1673 (all four exposure getters call get_open_trades exclusively), main.py:4528 (_is_live derivation) and main.py:4546-4569 (cmd_order buy path calling check_position_limits). Grepped paper.py for 'execution_log' -- zero functional references, only comments. Grepped repo-wide for _get_live_open_positions -- never consumed by check_position_limits or any exposure getter. Re-ran audit/scratch/repro_exposure_blind.py this session: output reproduced exactly -- {'ok': True, 'reason': None, 'existing_cost': 0, 'limit': 250.0} for a second live buy that should breach the 15% directional cap.

**Financial risk:** Real live money: once LIVE_TRADING_ENABLED=true, repeated manual cmd_order live buys on the same city/date (or correlated group) can silently exceed all configured exposure caps, with the CLI reporting each individually as 'ok'. Dormant in this credential-less worktree; live in the real deployment.

**Security risk:** None -- internal risk-control gap, not attacker-facing.

**Recommendation:** Have check_position_limits() also incorporate open live positions from execution_log (via order_executor._get_live_open_positions()) into its exposure accounting before comparing against caps. Already tracked in backlog.txt.

**Limitations noted by the audit:** Did not independently re-verify order_executor._auto_place_trades' automated (non-manual) live path for the same blindness, nor web_app.py's live-order paths (if any).

**Note:** this finding's structured record is missing description, root_cause (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Fully re-confirmed by independent code read (not trusting the finding's own description) and independent re-execution of its reproduction script this session. No refuting evidence found anywhere in paper.py or execution_log.py's cross-references. Matches an already-existing prior verification pass's conclusion but this session performed its own from-scratch read rather than trusting that file.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0001`), `audit/AUDIT_REPORT.md`.

### 2. AUD-0002 [HIGH | VERY HIGH | E1 | CONFIRMED]: _auto_place_trades' position-count/VaR/concentration gates are seeded only from the paper ledger, blind to real live exposure

**Files:** order_executor.py  
**Lines:** 2364; 2402-2443; 2916-2941; 3037-3053

**Problem:** _open_trades_list = get_open_trades() (paper.py's JSON ledger) is the sole feed for MAX_CONCURRENT_POSITIONS, per-date/same-day concentration caps, and the VaR gate, regardless of live=True/False. No execution_log-derived live-position source is ever merged in; only a same-cycle in-memory append (F6, order_executor.py:3037-3053) adds the current cycle's own live fills, which does not cover positions opened in prior watch/cron cycles.

**Root cause:** No execution_log/get_filled_unsettled_live_orders/_get_live_open_positions call exists anywhere inside _auto_place_trades (spans order_executor.py:2294 to end of file, 3340) feeding these specific risk gates.

**Note:** this finding's structured record is missing evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Confirmed line 2364 `_open_trades_list = get_open_trades()` is imported from paper.py. Confirmed MAX_CONCURRENT_POSITIONS check at line 2436 and the F6 same-cycle append at 3037-3053 exactly as described, with the append's own comment corroborating the blind-spot rationale. Contrast claim (get_today_live_spend() being the analogous already-fixed dollar-spend blind spot, execution_log.py:439-486) verified — it explicitly documents 'previously blind to live orders entirely' as the exact same class of bug already fixed for spend but left unfixed here for position count/VaR. No refutation found.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0002`), `audit/AUDIT_REPORT.md`.

### 3. AUD-0005 [HIGH | VERY HIGH | E2 | CONFIRMED]: LiveTradingGate's drawdown/streak risk-halt checks read only the paper ledger, never execution_log — blind to real live trading losses

**Files:** trading_gates.py, paper.py, order_executor.py, execution_log.py  
**Lines:** trading_gates.py:72-110; paper.py:626-635; paper.py:2436-2454; paper.py:575-598; paper.py:2664-2696; paper.py:3383-3437; order_executor.py:1567-1602

**Problem:** trading_gates.LiveTradingGate.check() is the single mandatory pre-check before every live order (cmd_order and the shared cron/watch --auto --live engine). Of its five risk sub-checks, four (is_paused_drawdown, is_streak_paused, is_daily_loss_halted, graduation_check) never read execution_log.db — they all compute exclusively from paper.py's own JSON ledger (paper_trades.json). Even is_daily_loss_halted(client), the one sub-check that accepts a live client, only uses that client to fetch market quotes for repricing paper.py's own paper open positions (get_unrealized_pnl_paper); its realized-P&L term still comes from the paper ledger. The same paper-only functions (is_paused_drawdown/is_streak_paused) are also called directly from order_executor._auto_place_trades, the shared batch-placement path used for both paper and live orders in cron/watch.

**Root cause:** is_paused_drawdown()/is_streak_paused()/get_daily_pnl() were written when paper.py's ledger was the only trade record in the system and were never extended to also read execution_log.db once live trading became a separate ledger. Commit e5331a8d (2026-08-17) explicitly stopped routing live cmd_order fills into the paper ledger at all (fixing a phantom-position bug), which as a side effect guarantees these particular risk gates can now never see live losses through any path.

**Evidence:** Independently re-read trading_gates.py in full (140 lines) and confirmed check() calls exactly these 5 paper.* functions. Read paper.py's is_paused_drawdown (L626-635) and _drawdown_snapshot (L575-598): both read only _load() (paper_trades.json), no execution_log reference anywhere. Read is_streak_paused (L2436-2454): reads only _load()["trades"]. Read get_daily_pnl/is_daily_loss_halted (L2664-2754) and get_unrealized_pnl_paper (L3383-3437): confirmed the client param is used only to fetch live market quotes to mark paper.py's own get_open_trades() to market — never reads execution_log. Confirmed is_paused_drawdown/is_streak_paused are called directly in order_executor._auto_place_trades (L2339, L2358), the shared batch path for both live=True and live=False. Independently RAN audit/reproductions/verify_pass20_gate_paper_only.py myself this session (uses only a throwaway tempfile.TemporaryDirectory(), monkeypatches paper.DATA_PATH/execution_log.DB_PATH at the attribute level, never touches real project data/): after simulating 10 real $95 live losses via execution_log.add_live_loss (execution_log.get_today_live_loss() correctly reports $950.00), paper.is_paused_drawdown() and paper.is_streak_paused() both still return False, with paper.get_balance()/get_peak_balance() both unchanged at 1000.0.

**Financial risk:** Real dollar risk once LIVE_TRADING_ENABLED is turned on: a slow live-account bleed spread across multiple days, or a genuine consecutive-loss streak, would never be caught by either is_paused_drawdown() or is_streak_paused(). Currently dormant (LIVE_TRADING_ENABLED unset in this environment), so no live exposure exists right now; this is a structural code defect independent of current env state. Confirmed that _place_live_order does have its own separate, already-working single-day check via execution_log.get_today_live_loss() (order_executor.py L1577) — that control is distinct from and does not cover the multi-day-drawdown/streak gap this finding describes.

**Security risk:** None directly — internal risk-management/reliability gap, not externally exploitable.

**Recommendation:** Add live-account-aware drawdown and consecutive-loss-streak checks sourced from execution_log.db (mirroring get_today_live_loss()/get_today_live_spend()), called from LiveTradingGate.check() when a live client is passed, or as additional explicit steps in order_executor._place_live_order() alongside the existing execution_log.get_today_live_loss() check.

**Limitations noted by the audit:** Did not exhaustively search for an out-of-band monitoring job that might independently catch a slow multi-day live bleed outside the trading_gates/paper/order_executor call chain.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0005`), `audit/AUDIT_REPORT.md`.

### 4. AUD-0009 [HIGH | VERY HIGH | E2 | CONFIRMED]: _count_open_live_orders() only counts status=='pending' live orders, missing already-filled open positions

**Files:** order_executor.py  
**Lines:** 172-175; 1610-1613

**Problem:** The max_open_positions live-trading gate counts only rows with status=='pending', so a filled-but-still-open live position stops being counted once its status transitions to 'filled', even though execution_log.get_filled_unsettled_live_orders() (status='filled' AND settled_at IS NULL) still correctly treats it as an open position.

**Root cause:** Gate uses status=='pending' as its definition of 'open position' instead of the codebase's own authoritative open-position query (status='filled' AND settled_at IS NULL AND closes_position_id IS NULL).

**Note:** this finding's structured record is missing evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Read order_executor.py:172-175 directly — matches claim verbatim (`sum(1 for o in orders if o.get("live") and o.get("status") == "pending")`). Confirmed call site at line 1611 gates _place_live_order. Confirmed execution_log.get_filled_unsettled_live_orders() (execution_log.py:535-556) uses `status='filled' AND settled_at IS NULL AND closes_position_id IS NULL`, a genuinely different and correct definition of 'open'. Re-ran the cited pytest repro myself (not just trusting the prior pass's claim of having run it) — it passed. No refutation found.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0009`), `audit/AUDIT_REPORT.md`.

### 5. AUD-0012 [HIGH | MEDIUM | E2 | CONFIRMED]: _poll_pending_orders and _count_open_live_orders can silently lose a genuinely still-open live order once enough interleaved (mostly paper) orders accumulate in the shared execution_log orders table

**Files:** execution_log.py, order_executor.py  
**Lines:** 937-944; 172-175; 424-443; 3083-3092; 1610-1613

**Problem:** execution_log.get_recent_orders(limit=N) is `SELECT * FROM orders ORDER BY placed_at DESC LIMIT ?` with no WHERE clause on `live` — both _poll_pending_orders (limit=200) and _count_open_live_orders (limit=500) fetch this fixed-size mixed (paper+live) window and filter for live+pending only in Python after truncation, so a real still-pending live order can fall entirely outside the window once enough other (overwhelmingly paper) orders accumulate afterward.

**Root cause:** Using a generic top-N-of-everything helper for a live-scoped query instead of a dedicated `WHERE live=1 AND status='pending'` SQL query — the fix pattern already exists elsewhere in the same file (get_live_pnl_summary's open_count metric, execution_log.py:922-928, uses exactly that unlimited scoped query).

**Note:** this finding's structured record is missing evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Read execution_log.py:937-944 (get_recent_orders) — confirmed no `live` filter in SQL, matches claim. Read order_executor.py:424-443 (_poll_pending_orders) — confirmed limit=200 + Python-side live/pending filter matching the claim exactly. Confirmed REFRESH_SECS=300 at main.py:211, supporting plausibility of accumulating hundreds of interleaved orders over a multi-hour active session. This finding was reportedly new this session in the prior pass (not from the original run) — I ran the repro fresh myself and it reproduced the exact eviction behavior described. Confidence MEDIUM is appropriate: mechanism is solidly E2-proven, but real-world trigger frequency depends on unobserved production order volume, as the finding itself acknowledges.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0012`), `audit/AUDIT_REPORT.md`.

### 6. Pre-existing backlog item (`backlog.txt:1994`)

```
[OPEN 2026-08-17 -- found by opus review of the "MANUAL cmd_order LIVE
  ORDERS..." fix above; filed separately per the same-payload test since
  this affects EVERY live-order path, not just cmd_order, and fixing it
  would mean changing paper.check_position_limits/get_total_exposure
  themselves, which that entry's own scope boundary explicitly excludes]
  paper.check_position_limits' EXPOSURE CAPS ARE STRUCTURALLY BLIND TO REAL
  LIVE POSITIONS -- paper.get_open_trades() IS THE ONLY SIGNAL THEY EVER READ
Priority: Medium -- a real, repo-wide gap (not specific to cmd_order or to
  this session's fix), but confirmed EMPIRICALLY MOOT today: zero live=1
  rows have ever existed in execution_log (verified via direct query,
  2026-08-17 -- same check the sibling entry above already ran), so there
  is currently no live exposure for these caps to have missed.

Problem:
  paper.get_total_exposure() (paper.py:1620-1623) and
  paper.get_ticker_exposure() (paper.py:1626-1629) both compute their
  totals exclusively from `sum(t["cost"] for t in get_open_trades())` --
  paper.py's own JSON store. paper.check_position_limits() (paper.py:3447),
  the SINGLE shared enforcement point for per-market/portfolio/city-date/
  directional/correlated-group exposure caps across every manual and
  automated placement path in this bot (per its own docstring, "#2: those
  three caps were previously enforced only inside portfolio_kelly_fraction()
  ... every manual order path ... could silently exceed them"), calls
  get_total_exposure() at its MAX_TOTAL_OPEN_EXPOSURE check (paper.py:3645)
  and has no other source of exposure data anywhere in its body. Neither
  function has ever read execution_log for real live positions.
  Confirmed this is NOT specific to cmd_order: order_executor._auto_place_trades
  (the fully-automated `watch --auto --live` path) branches live vs. paper
  as a mutually exclusive if/else (order_executor.py:2966 calls
  _place_live_order for the live branch; order_executor.py:3014-3049 is the
  separate paper `else` branch that calls place_paper_order) -- a live entry
  NEVER also mirrors into paper.place_paper_order(). So exposure caps have
  been structurally blind to the automated live path's own positions this
  entire time, independent of anything cmd_order does.
  Surfaced by this session's cmd_order fix only because, PRE-FIX, cmd_order's
  bug (unconditionally calling place_paper_order() for every live fill,
  buy or sell) happened to ALSO feed this exposure-cap signal as an
  accidental side effect of the recording bug -- never a deliberate
  mechanism, and never true for the automated live path. Post-fix,
  cmd_order's live buys correctly stop writing to paper, which removes that
  accidental signal and brings cmd_order in line with how _auto_place_trades
  has always behaved.

  CORRECTED 2026-08-17 (2nd opus review, NEW-M3): the line above ("not a new
  regression") undersold this. The ROOT architectural gap (exposure caps
  never reading execution_log at all) is genuinely pre-existing and
  repo-wide, but for cmd_order SPECIFICALLY, the fix is a real, concrete
  behavior change: pre-fix, a manual live buy had SOME (wrong in other
  ways, but present) exposure-cap coverage via the accidental paper-mirror
  write; post-fix, it has NONE. That a differently-broken automated path
  already had zero coverage doesn't make removing cmd_order's own
  (accidental) coverage a non-event for cmd_order's own operators -- it is
  a regression for that one path, just one whose root cause and fix both
  belong here rather than in the sibling entry. Still empirically moot
  today (LIVE_TRADING_ENABLED unset), which is why this wasn't treated as
  blocking, but stated precisely rather than downplayed.

Recommendation (not yet actioned -- filed for later decision):
  If/when this needs fixing, get_total_exposure()/get_ticker_exposure()
  (or check_position_limits() directly) would need to also sum cost across
  execution_log's live=1, settled_at IS NULL rows (order_executor.
  _get_live_open_positions() already builds exactly this shape) alongside
  paper's get_open_trades() -- a real design question (one combined
  cross-ledger total vs. two separately-capped totals; whether the
  per-city/date/directional/correlated-group checks, which walk paper's
  trade list structurally, need the same treatment) that needs
  AskUserQuestion before implementing, not guessed at here. Given this is
  currently empirically moot (no live positions exist to be missed), there
  is no urgency forcing the choice.
```

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

At least one item in this batch touches a live-order/live-money/safety-gate path (or is adjacent enough to warrant it) -- this batch does **not** qualify for the steps 11-12 LOW-tier downgrade. Apply the full ceremony as written, all 29 steps, for the batch as a whole.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
