# Handoff prompts for the 13 HIGH findings from the 2026-08-18 max-depth audit

Source: `audit/AUDIT_REPORT.md` / `audit/AUDIT_REPORT.json`, produced against branch `claude/code-max-depth-audit-5518e9`, HEAD `d190d09dd699df5266e85650a6ddf8e2d1420891`. Each prompt below is self-contained and can be handed to a fresh session as its opening message.

Every prompt directs the implementing session to follow the 29-step `feedback-implementation-workflow` memory in full (no LOW-tier downgrade — all touch a live-order/live-money/safety-gate path, except AUD-0011 which is docs-only but still full ceremony since it describes that same surface).

## Group A — live-position/loss visibility gap (shared root cause; audit recommends ONE coordinated fix, not five)
- [AUD-0001](AUD-0001.md) — `check_position_limits()` exposure caps blind to live positions (manual `cmd_order` path)
- [AUD-0002](AUD-0002.md) — `_auto_place_trades`' VaR/position-count gates blind to live positions (automated cron/watch path)
- [AUD-0005](AUD-0005.md) — `LiveTradingGate` drawdown/streak checks blind to live losses
- [AUD-0009](AUD-0009.md) — `_count_open_live_orders()` undercounts via wrong status filter
- [AUD-0012](AUD-0012.md) — `_poll_pending_orders`/`_count_open_live_orders` can lose a live order once order volume is high (most related to AUD-0009 specifically)

## Group B — order lifecycle / crash-recovery gaps
- [AUD-0007](AUD-0007.md) — ambiguous `place_order()` failure can leave a position permanently untracked
- [AUD-0008](AUD-0008.md) — `cmd_watch --live` protection loop has zero exception handling
- [AUD-0010](AUD-0010.md) — `_quick_paper_buy()`'s maker branch places unrecorded live orders (reachability not fully settled — verify first)
- [AUD-0013](AUD-0013.md) — `cmd_watch` missing crash-recovery call (confidence downgraded HIGH→MEDIUM during verification — read the narrowing before prioritizing)

## Group C — financial calculation errors
- [AUD-0004](AUD-0004.md) — graduation gate's Brier score contaminated by shadow markets (strongest evidence in the whole audit — reproduced on real production data)
- [AUD-0003](AUD-0003.md) — settlement P&L uses $0 fee for now-taker live fills

## Group D — concurrency
- [AUD-0006](AUD-0006.md) — cron lock TOCTOU race (reproduced)

## Group E — documentation actively misleading an operator
- [AUD-0011](AUD-0011.md) — runbook falsely describes which commands can place live orders

## Suggested sequencing note (not authoritative — surface this as an AskUserQuestion if picking up multiple at once)
Group A's five findings share one root cause per the audit's own recommendation — consider tackling AUD-0001 first (it has the clearest existing helper, `_get_live_open_positions()`) and having AUD-0002/0005/0009/0012 reuse whatever shared accounting path it introduces, rather than five sessions independently inventing five slightly different versions of "read live positions from execution_log."
