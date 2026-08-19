# Batch 2: Order lifecycle / crash-recovery

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch comes from the 2026-08-18 max-depth forensic audit (`audit/AUDIT_REPORT.md` / `.json`). It groups 4 finding(s) that share **kalshi_client.py, order_executor.py, main.py (cmd_watch)** -- doing them together means you only load this subsystem's context once, and avoids two different sessions independently editing the same file in parallel. Live trading is currently dormant (`LIVE_TRADING_ENABLED` unset) -- no active financial exposure today for any item below, but treat items tagged HIGH/MEDIUM as touching a real live-order/live-money surface once trading is enabled.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. AUD-0007 [HIGH | HIGH | E1 | CONFIRMED]: Ambiguous place_order() failure can leave a real live position permanently untracked, unprotected, and re-orderable

**Files:** kalshi_client.py, execution_log.py, order_executor.py, main.py  
**Lines:** kalshi_client.py:517-534 (place_order); kalshi_client.py:551-608 (_find_order_by_client_id); execution_log.py:278-297 (was_recently_ordered); execution_log.py:300-325 (was_traded_today); execution_log.py:328-340 (was_ordered_this_cycle); execution_log.py:343-380 (was_ordered_recently); order_executor.py:269-355 (_recover_pending_orders); order_executor.py:1552-1685 (_place_live_order); main.py:4694-4756 (cmd_order placement)

**Problem:** place_order() catches any exception from the create-order POST and tries to determine whether the order landed anyway via _find_order_by_client_id (3 sequential GET-based lookups: resting, executed, canceled). Each lookup pass individually swallows its own exception and treats a failed lookup as 'not found'. If all 3 lookups also fail, place_order re-raises the original exception even though the order may have genuinely landed on Kalshi. The caller then logs the row status='failed'. Every dedup/anti-thrash guard in execution_log.py deliberately excludes status='failed' rows, and _recover_pending_orders only reconciles status='pending' rows, never 'failed' ones.

**Root cause:** The 'failed' status is overloaded to mean both 'genuinely never sent' (correctly excluded from dedup) and 'sent, but outcome unknown due to a correlated failure in both the placement call and its own reconciliation check' (a rarer but real case). No distinct status/recovery path exists for the second case.

**Evidence:** Independently re-read the full chain: kalshi_client.py 517-534 (place_order except block re-raises only when _find_order_by_client_id returns None), 551-608 (all 3 lookup passes independently swallow exceptions), execution_log.py's 4 dedup functions (278-380, all exclude status='failed'), order_executor.py 269-355 (_recover_pending_orders filters strictly on status=='pending'), and order_executor.py 1552-1685 / main.py 4694-4756 (both pre-log status='pending' then explicitly overwrite to status='failed' on exception, confirming a row that hits this path is never revisited by the pending-only recovery scan).

**Financial risk:** A real live position could sit completely unmanaged indefinitely, and a subsequent retry could double real capital exposure on the same signal with neither copy protected.

**Recommendation:** Distinguish 'confirmed never sent' from 'ambiguous outcome, reconciliation itself failed' with a separate status (e.g. 'unknown'), and have a recovery routine periodically re-check 'unknown'/'failed' live-order rows against the Kalshi API until confirmed.

**Limitations noted by the audit:** Requires a fairly specific, sustained/correlated network-outage shape (original POST fails AND all 3 subsequent reconciliation GETs also fail) rather than a single transient blip — narrows practical frequency but does not eliminate it.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0007`), `audit/AUDIT_REPORT.md`.

### 2. AUD-0008 [HIGH | VERY HIGH | E1 | CONFIRMED]: cmd_watch --live position-protection block has zero exception handling; a single failure kills the entire persistent watch process

**Files:** main.py, order_executor.py, cron.py  
**Lines:** main.py:3759-3790 (if live: block); main.py:3575-3911 (cmd_watch loop, only KeyboardInterrupt caught); order_executor.py:1376-1446 (_check_live_position_exits); order_executor.py:1448-1536 (_check_live_model_exits); cron.py:912-923 (equivalent block, guarded)

**Problem:** cmd_watch's `if live:` block calls _poll_pending_orders, _reprice_or_cancel_pending_orders, _check_live_position_exits, and _check_live_model_exits with no surrounding try/except, inside a `while True:` loop whose only exception handler catches KeyboardInterrupt. _check_live_position_exits itself has no internal try/except anywhere in its body. cron.py's equivalent call site wraps the same two functions in a broad except, confirming the gap is cmd_watch-specific.

**Root cause:** cmd_watch's live-protection block was never given the same defensive try/except treatment its own paper-side siblings received in the same function, and was not brought in line with cron.py's already-guarded equivalent.

**Evidence:** Independently re-read main.py:3558-3913 in full. Confirmed the `if live:` block at 3759-3790 has zero try/except, while the three subsequent blocks in the same function (3792-3810, 3822-3850, 3861-3889) are each individually wrapped in `except Exception as ...:` with explicit comments about the silent-permanent-kill risk. Confirmed the outer loop's sole handler is `except KeyboardInterrupt:` at 3911. Read order_executor.py:1376-1446 in full — zero try/except in _check_live_position_exits' body. Read cron.py:898-923 — confirmed the equivalent pair of calls is wrapped in `try/except Exception as _live_exit_exc:`.

**Financial risk:** All open live positions go completely unprotected for however long it takes an operator to notice the crashed process and restart it -- potentially hours if unattended.

**Recommendation:** Wrap the `if live:` block's 4 calls in the same try/except-and-log pattern already used for the paper-side checks immediately below, matching cron.py's existing guard.

**Limitations noted by the audit:** The exact trigger exception was not exercised; the finding is about the structural absence of any handler, which is deterministic regardless of the specific trigger.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0008`), `audit/AUDIT_REPORT.md`.

### 3. AUD-0010 [HIGH | MEDIUM | E1 | CONFIRMED]: _quick_paper_buy()'s maker-order branch places real live orders but never records the fill in execution_log

**Files:** main.py  
**Lines:** 2170-2539; 2465-2511; 2494-2496; 2511; 3216-3249; 3243

**Problem:** main.py's _quick_paper_buy() has a maker-order branch (main.py ~2465-2511) that calls client.place_maker_order(...) at 2494-2496, prints a success message, and returns at 2511 — with no call to execution_log.log_order, record_live_exit_fill, record_live_settlement, or any other persistence. This is the exact bug class e5331a8d (2026-08-17) just fixed for cmd_order, but that fix and its predecessors (bb91374f, 105cf4ce) never touched _quick_paper_buy.

**Root cause:** _quick_paper_buy was written/reviewed as a paper-trading helper; its --live maker-order fallback is functionally live-order code never subjected to the execution_log-routing review the cmd_order/order_executor cluster received. backlog.txt (RESOLVED header at line 7442, dated 2026-07-30 — the finding's original citation of '2026-07-31' is off by one day) already flagged '_quick_paper_buy() can place a REAL LIVE maker order' and added only ticker-family shadow-gate guards, not post-fill bookkeeping.

**Evidence:** Read main.py:2170-2539 in full. grep for execution_log|log_order|record_live restricted to that range matches only the sibling paper (non-maker) branch (~2514-2531). Cross-checked every place_order/place_maker_order call site in the repo via grep across *.py: order_executor.py's 6 sites and main.py:4703/4713 (cmd_order, logged via log_order at 4653) are all preceded by execution_log.log_order; main.py:2494 is the sole exception.

**Financial risk:** An operator who hits the maker branch (via the `analyze` command / interactive 'Analyze' menu, not cmd_today — see verification_notes) gets a real, unmanaged Kalshi position invisible to the bot's own exit/reconciliation logic — the same 'phantom unmanaged live position' failure mode e5331a8d closed for cmd_order.

**Security risk:** None beyond the financial/operational risk described.

**Recommendation:** Route _quick_paper_buy's maker branch through execution_log.log_order/record_live_exit_fill, or remove the live/maker branch entirely.

**Limitations noted by the audit:** E1 static evidence, not a runtime reproduction.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0010`), `audit/AUDIT_REPORT.md`.

### 4. AUD-0013 [HIGH | MEDIUM | E1 | CONFIRMED]: cmd_watch --auto --live has no standalone _recover_pending_orders() call; crash-window phantom 'pending' live rows stay invisible to live position protection whenever the cron lock is contended

**Files:** main.py, order_executor.py, trade_cycle.py, cron.py, execution_log.py, LIVE_TRADING_RUNBOOK.md  
**Lines:** order_executor.py:269-355; order_executor.py:1077-1115 (_get_live_open_positions); order_executor.py:424-540 (_poll_pending_orders, filter at 442/455); execution_log.py:535-556 (status='filled' filter); cron.py:888-923 (early recovery restored ahead of exit checks); cron.py:2346-2381 (watchdog default 720s, docstring says 8min but code default is 12min); main.py:3615-3648 (run_trade_cycle only called if auto_trade AND lock acquired); main.py:3759-3790 (if live: exit checks run unconditionally, not gated on cycle_result); trade_cycle.py:219-226 (_recover_pending_orders call site); LIVE_TRADING_RUNBOOK.md:131

**Problem:** order_executor._recover_pending_orders() reconciles execution_log 'pending' rows against Kalshi's live API. Called from cron.py (standalone) and trade_cycle.run_trade_cycle() (near its top). cmd_watch never calls it directly -- only reaches it indirectly via run_trade_cycle(), gated on auto_trade=True AND ctx.acquire_cron_lock() succeeding. If the shared cron lock is held by a concurrent cron.py run, cmd_watch's cycle_result stays None and recovery is skipped that cycle, yet the `if live:` block still runs _check_live_position_exits/_check_live_model_exits unconditionally.

**Root cause:** cluster A's cron/cmd_watch unification routes cmd_watch's live-position-protection through run_trade_cycle() only when the shared cron lock is free; the standalone _recover_pending_orders() safeguard added to cron.py was never mirrored into cmd_watch's own flow.

**Evidence:** Grep confirms exactly two real call sites (cron.py:900-904, trade_cycle.py:222-226); main.py's 2 hits (4683,4729) are comment-only. Read of main.py:3558-3790 confirms the `if live:` block at 3759 is not gated on cycle_result. Read of order_executor.py:269-356 (_recover_pending_orders) traced in full this session.

**Financial risk:** Materially narrower than originally characterized -- see verification_notes. The common case (order placed, response logged, not yet polled as filled) is already independently self-healed every cmd_watch cycle by its own unconditional _poll_pending_orders() call at main.py:3760, regardless of lock/cycle_result state -- no exposure gap there. The one case unique to _recover_pending_orders (a pending row with no stored response/order_id, i.e. the true crash-window case) cannot be resolved to a protected 'filled' status by _recover_pending_orders either -- it marks the row 'sent' (a dedup-blacklist marking only), which is still excluded from _get_live_open_positions()'s status='filled' filter. So the claimed 'cron.py will self-heal it within 3 hours' mechanism does not actually restore exit-protection visibility for that sub-case, whether or not cmd_watch calls it. The real, narrower consequence of the missing call is dedup-state staleness (the ticker stays ambiguously 'pending' in cmd_watch's own bookkeeping longer than necessary), not an unprotected live position with a real dollar exposure window.

**Recommendation:** Add a standalone _recover_pending_orders(client) call in cmd_watch's live-order loop, mirroring cron.py's own restored early call.

**Limitations noted by the audit:** Confidence on the code-level asymmetry (cmd_watch missing a direct call cron.py has) is solid. Confidence on the described financial-risk consequence is downgraded to MEDIUM after tracing what _recover_pending_orders can/cannot actually resolve -- the scenario where cmd_watch's gap causes a real unprotected-live-position window could not be reconstructed; the more concrete/real consequence is a bounded dedup-bookkeeping staleness, not the described 10-15 minute zero-protection exposure.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0013`), `audit/AUDIT_REPORT.md`.

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

At least one item in this batch touches a live-order/live-money/safety-gate path (or is adjacent enough to warrant it) -- this batch does **not** qualify for the steps 11-12 LOW-tier downgrade. Apply the full ceremony as written, all 29 steps, for the batch as a whole.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
