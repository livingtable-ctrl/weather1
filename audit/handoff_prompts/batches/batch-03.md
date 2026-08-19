# Batch 3: Settlement & fee accounting

## Context

Repo: weather1 (Kalshi weather-trading bot). Branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891` at the time these batches were written (2026-08-18) -- **re-verify this is current before starting** (workflow step 1): other batches from this same grouping may already be merged, and this project routinely runs many parallel worktree sessions. `git fetch` + `git log origin/master` before touching anything.

This batch comes from the 2026-08-18 max-depth forensic audit (`audit/AUDIT_REPORT.md` / `.json`). It groups 5 finding(s) that share **order_executor.py, execution_log.py** -- doing them together means you only load this subsystem's context once, and avoids two different sessions independently editing the same file in parallel. Live trading is currently dormant (`LIVE_TRADING_ENABLED` unset) -- no active financial exposure today for any item below, but treat items tagged HIGH/MEDIUM as touching a real live-order/live-money surface once trading is enabled.

**Do NOT touch other batches' files while working this one** -- batches were constructed so no two share a touched file; if you find yourself needing to edit something outside this batch's file list, stop and check whether another batch already covers it (see the full batch list in `audit/handoff_prompts/batches/INDEX.md`) rather than expanding scope silently.

## Items in this batch

### 1. AUD-0003 [HIGH | VERY HIGH | E1 | CONFIRMED]: Settlement P&L for taker (IOC)-filled live orders is computed with the $0 maker fee, not Kalshi's real taker fee

**Files:** order_executor.py, main.py, utils.py, execution_log.py, tests/test_live_execution.py  
**Lines:** order_executor.py:432-433; order_executor.py:566-580; main.py:4702-4711 (e5331a8d); utils.py:83,99; execution_log.py:535-556,734-804

**Problem:** order_executor._poll_pending_orders() computes realized P&L for every live position at market settlement using KALSHI_MAKER_FEE_RATE (0.0), justified by a comment that live orders are always resting maker GTC. Commit e5331a8d changed cmd_order's live order placement to time_in_force='immediate_or_cancel' (a taker fill), so an entry via cmd_order that settles at market expiry (rather than being manually sold) is settled with the wrong (zero) fee, overstating profit. The pre-existing automated taker-cross reprice fallback (order_executor.py:989-1015, gated by _clears_taker_fee) shares the identical gap for entries and predates this audit window.

**Root cause:** e5331a8d introduced a taker (IOC) live-order entry path without updating the downstream settlement-PnL computation's hardcoded maker-fee assumption; the pre-existing auto-path taker-cross reprice fallback shares the same unaddressed gap.

**Evidence:** Verified directly: order_executor.py:432-433 imports KALSHI_MAKER_FEE_RATE unconditionally; execution_log.get_filled_unsettled_live_orders() (execution_log.py:535-556) makes no maker/taker distinction in its query; main.py:4702-4711 confirmed cmd_order live orders are always IOC post-e5331a8d; order_executor.py:989-1015's _clears_taker_fee-gated taker-cross confirmed to place entry replacements as IOC too. By contrast execution_log.record_live_exit_fill (execution_log.py:734-804) correctly uses real KALSHI_FEE_RATE for exits, with an explicit comment (L742-750) that this assumption is IOC-specific -- confirming awareness of IOC=taker on the exit side that was never carried over to entry settlement. tests/test_live_execution.py:983,1057,1123 assert the $0-fee formula exactly as described, confirming this is current, tested, intended behavior.

**Financial risk:** Overstates real live P&L for any position entered via cmd_order (now always IOC/taker post e5331a8d) or via the auto-trader's taker-cross reprice path and later closed by market settlement rather than an explicit sell; feeds execution_log.add_live_loss()/get_today_live_loss(), which trading_gates.LiveTradingGate.check() uses via paper.is_daily_loss_halted(), making the daily-loss circuit breaker less likely to trip when it legitimately should. Currently non-operative (LIVE_TRADING_ENABLED unset, no live=1 rows exist) but a live, currently-tested-and-intentional code path that will misstate real money once live trading is enabled.

**Recommendation:** Track whether each live order row's ENTRY fill was maker or taker and select KALSHI_FEE_RATE vs KALSHI_MAKER_FEE_RATE accordingly in _poll_pending_orders' settlement formula, mirroring record_live_exit_fill's existing correct treatment of exits.

**Limitations noted by the audit:** Did not execute a live or demo trade to observe an actual taker fee being charged. Severity assumes Kalshi charges a nonzero taker fee, per utils.py's own documented fee schedule.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0003`), `audit/AUDIT_REPORT.md`.

### 2. AUD-0026 [MEDIUM | HIGH | E1 | CONFIRMED]: cmd_order's unmatched-sell settlement fallback can leave the exact phantom-position shape its own fix was designed to prevent

**Files:** main.py, execution_log.py  
**Lines:** main.py:4806-4829 (elif action == 'sell': unmatched-sell branch); execution_log.py:535-556 (get_filled_unsettled_live_orders); execution_log.py:601-681 (record_live_early_exit)

**Problem:** When a manual live sell via cmd_order has no matching tracked position, the code immediately calls record_live_early_exit(row_id, price, 'unmatched_sell', 0.0) specifically so the just-logged row isn't later misread as a new open position by the automated exit scanner. That call is wrapped only in a broad except Exception with a warning log and no retry or alternate fail-closed handling.

**Root cause:** If the record_live_early_exit DB write itself fails, the row is left exactly in the dangerous shape (live=True, status='filled', settled_at=NULL, closes_position_id=None) the surrounding comment says must never happen -- there is no retry and no compensating mechanism.

**Evidence:** Independently re-read main.py's unmatched-sell branch (4806-4829): the try/except around record_live_early_exit only logs a warning, no retry. Confirmed execution_log.get_filled_unsettled_live_orders() (535-556) WHERE clause matches exactly `live = 1 AND status = 'filled' AND settled_at IS NULL AND closes_position_id IS NULL` -- exactly the row shape this failure leaves.

**Financial risk:** Low direct financial risk (spurious exit orders should be rejected by Kalshi as there's no real position to sell), but produces a recurring, silent operational anomaly and log/alert noise, and consumes an execution_log row's dedup slot indefinitely.

**Recommendation:** Add a bounded retry to this specific settle call, or fail closed by writing a distinct marker/flag file the operator is alerted to.

**Limitations noted by the audit:** Requires both a manual cmd_order sell of an untracked ticker AND a DB write failure at that specific moment -- a narrow window, but the consequence is a real, self-perpetuating failure mode once triggered.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0026`), `audit/AUDIT_REPORT.md`.

### 3. AUD-0028 [MEDIUM | VERY HIGH | E2 | CONFIRMED]: cmd_order's manual partial live-sell never settles its own execution_log row, reproducing the 'aggregate-only P&L' bug the same day's earlier commit fixed for the automated path

**Files:** main.py, execution_log.py  
**Lines:** 4780-4793; 734-804

**Problem:** cmd_order's matched-position live-sell branch (main.py:4780-4793) calls only execution_log.record_live_exit_fill(_live_close_position, _record_count, price). For a partial fill, that function settles only the referenced POSITION row via record_live_partial_exit (correctly leaves settled_at NULL, position stays open) but never calls record_live_early_exit on the SELL order's own row (main.py's row_id, created earlier via log_order with closes_position_id set) — unlike order_executor._exit_live_position's equivalent partial-fill branch, which makes a required second call `execution_log.record_live_early_exit(log_id, exit_price, reason, partial_pnl)` (order_executor.py:1320) to settle the exit order's own row.

**Root cause:** cmd_order's live-sell path (commit e5331a8d) was not updated to mirror _exit_live_position's two-call settlement pattern for partial fills, even though the same-day earlier commit 105cf4ce had just added exactly this second call to fix the identical bug on the automated path.

**Note:** this finding's structured record is missing evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Read main.py:4780-4805 directly: confirmed only one record_live_exit_fill call in the `if _live_close_position is not None:` branch, no follow-up record_live_early_exit(row_id,...). Note: main.py DOES call record_live_early_exit at line 4823, but that is in a separate `elif action == 'sell':` branch for an UNMATCHED sell (no tracked position) — a genuinely different code path, not a refutation. Read execution_log.py:734-804 (record_live_exit_fill): confirmed its partial branch (784-792) only calls record_live_partial_exit(position['id'], ...) targeting the POSITION row, never touching the exit order's own row in either its partial or full-close branch. Cross-checked order_executor.py:1279-1332 to confirm _exit_live_position's partial branch DOES make the extra record_live_early_exit(log_id,...) call that cmd_order lacks. Also confirmed downstream effect: get_live_pnl_summary's total_pnl (execution_log.py:914-921) requires settled_at IS NOT NULL AND pnl IS NOT NULL, which the unsettled sell-order row never satisfies. Description matches current source exactly.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0028`), `audit/AUDIT_REPORT.md`.

### 4. AUD-0049 [LOW | HIGH | E2 | CONFIRMED]: was_traded_today/was_recently_ordered/was_ordered_recently already treat any fill (entry OR exit) on a ticker+side as blocking re-entry -- pre-existing design, not changed by the closes_position_id-adding commits

**Files:** execution_log.py  
**Lines:** 278-297; 300-325; 343-380

**Problem:** None of these three dedup-guard SQL queries filter on closes_position_id, unlike execution_log.get_today_live_spend() which explicitly excludes closes_position_id-set rows. Verified this is NOT a regression: a fresh entry-only row (no exit row at all) already independently trips all three guards, so the exit row is redundant to the blocking effect, not its cause.

**Note:** this finding's structured record is missing root_cause, evidence, recommendation (a known JSON-completeness gap in the audit's own output -- the content exists, just not in that specific field). Full narrative from adversarial verification, which covers the missing ground: Read execution_log.py:278-380 directly — none of the three WHERE clauses reference closes_position_id, matching the claim. Confirmed the contrast: get_today_live_spend() (execution_log.py:461,478) does explicitly filter `closes_position_id IS NULL` with a documented rationale, unlike the three dedup functions. Re-ran both repro scripts myself; output matches described results exactly. This is a correctly-classified non-finding/observation, not a bug.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0049`), `audit/AUDIT_REPORT.md`.

### 5. AUD-0057 [LOW | HIGH | E1 | CONFIRMED]: cmd_order's unmatched-live-sell placeholder pnl=0.0 is indistinguishable from a real zero-P&L outcome in tax/P&L exports

**Files:** (see full record)

**Problem:** When cmd_order's live sell path (e5331a8d) can't match the sell to any tracked live position, it calls execution_log.record_live_early_exit(row_id, price, 'unmatched_sell', 0.0) to immediately settle the row and keep it from being misread as an open position. The code's own comment explicitly documents this 0.0 as 'a neutral placeholder, not a real P&L claim' because there is no tracked entry_price to compute a real P&L against. However, execution_log.export_live_tax_csv() and get_live_pnl_summary() both filter on settled_at IS NOT NULL AND pnl IS NOT NULL with no field distinguishing a genuine $0 outcome from this placeholder, so a real (possibly nonzero) realized gain/loss from an untracked manual sell will show up as exactly $0.00 in tax exports and P&L summaries.

**Root cause:** There is no tracked entry_price for an unmatched live sell (the position was opened outside this bot's own tracking), so no real P&L can be computed; the chosen design intentionally settles the row with a placeholder value rather than leaving it open, but downstream consumers have no way to flag/filter placeholder rows.

**Evidence:** main.py lines 4806-4829 verified verbatim: `elif action == "sell":` branch, comment '0.0 is a neutral placeholder, not a real P&L claim', then `record_live_early_exit(row_id, price, "unmatched_sell", 0.0)`. execution_log.py lines 807-843 (export_live_tax_csv): base_query WHERE clause is `o.live = 1 AND o.settled_at IS NOT NULL AND o.pnl IS NOT NULL` -- no exit_reason filter. execution_log.py lines 894-934 (get_live_pnl_summary): both today_pnl and total_pnl SQL queries use `WHERE live = 1 AND settled_at ... AND pnl IS NOT NULL` -- no exit_reason filter either. exit_reason='unmatched_sell' IS stored in the row (distinguishable at the raw-DB level) but neither aggregation function reads it.

**Financial risk:** Low -- affects only manual cmd_order sells with no matching tracked live position, an edge case; understates or overstates realized P&L reporting/tax records for that specific trade by an unknown amount.

**Recommendation:** Consider excluding exit_reason='unmatched_sell' rows from get_live_pnl_summary()/export_live_tax_csv() aggregate totals, or flagging them for manual review, since this is a rare-but-real manual-trading edge case (selling a position the bot didn't open/track).

**Limitations noted by the audit:** The finding's own original 'limitations' section asked for a follow-up grep of get_live_pnl_summary()'s WHERE clause before treating this as unaddressed -- that grep is now done as part of this verification and confirms no exit_reason special-casing exists anywhere in execution_log.py.

Full record: `audit/AUDIT_REPORT.json` (id `AUD-0057`), `audit/AUDIT_REPORT.md`.

## Process -- follow the 29-step implementation workflow from memory (`feedback-implementation-workflow`) exactly, in order

At least one item in this batch touches a live-order/live-money/safety-gate path (or is adjacent enough to warrant it) -- this batch does **not** qualify for the steps 11-12 LOW-tier downgrade. Apply the full ceremony as written, all 29 steps, for the batch as a whole.

Non-negotiable highlights regardless of tier: (1) re-verify every item's claims against live state before trusting this prompt's transcription -- re-read the actual current code/docs at the cited locations. (2) Research the real code structure before designing a fix. (3) Surface genuine design decisions via `AskUserQuestion`, don't guess. (7) Write real, mutation-tested tests for anything code-level (via the Edit tool for mutation reverts, never a string-replace script). (8-9) Scoped test run, then lint/mypy. (11) Independent opus review at `effort: high` before push for anything live-money-adjacent -- and if that review's findings get fixed, the fix itself needs its own independent review too. (13) Address every review finding regardless of severity. (14-16) Compressed-pointer memory update before commit; explicit confirmation before commit/push; `git fetch` + rebase-if-diverged immediately before the actual push -- this matters more than usual here since other batches may be pushing to the same branch/master concurrently. (19) If `backlog.txt` gets edited, run `python backlog_index.py` afterward and confirm the entry landed correctly in `BACKLOG_OPEN.md`. (29) Refresh `graphify-out/` (AST always; semantic `--update` too if any item is non-LOW-tier) before committing, if it exists -- scope the refresh to just the files this batch actually changed, not a full incremental sweep (a full sweep pulls in every other in-flight batch's uncommitted work too).

Full step list and tiering rules live in memory under `feedback-implementation-workflow` -- apply all 29 steps in order. **If this memory entry isn't loaded in your session**, its full text is preserved at `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md` -- read it directly rather than proceeding without it.
