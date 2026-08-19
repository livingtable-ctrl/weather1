# Pass 21 (Sections 31 & 32, Documentation & Configuration) — Independent Verification

Verifier session, 2026-08-17. All 8 findings re-checked against current worktree HEAD
(d190d09d) by opening cited files/lines directly. Summary below; full per-finding
verdicts returned via StructuredOutput to the orchestrator.

## Results
1. README/.env.example missing LIVE_TRADING_ENABLED — CONFIRMED (E1). Grep for
   `LIVE_TRADING_ENABLED` across README.md and .env.example returns zero matches;
   trading_gates.py:69-70 reads it as a required `== "true"` check.
2. LIVE_TRADING_RUNBOOK.md Appendix "no override" claim — CONFIRMED (E1).
   LIVE_TRADING_RUNBOOK.md:242 literally says "There is no override short of
   modifying source code." paper.py:2544-2580 (`is_accuracy_halted`) checks a
   time-boxed override flag file first and returns False (not halted) while it's
   active — a genuine no-source-change override, wired to `admin accuracy-override`
   (main.py:3369+).
3. KALSHI_ENV=prod startup banner stale claim — CONFIRMED (E1). main.py:9567-9579
   text matches finding verbatim; main.py:4528-4534 shows cmd_order places live
   orders via `pre_live_trade_check()` whenever `client.base_url != DEMO_BASE`,
   independent of the banner's cmd/args check. backlog.txt:1947-1984 confirms an
   open, unfixed entry for exactly this.
4. COMMANDS.md "watch --live" alone implies live routing — CONFIRMED (E1).
   COMMANDS.md:30 and :193 read as claimed; main.py:3614-3615 shows
   `run_trade_cycle()` (the only placement call in cmd_watch) is gated solely by
   `if auto_trade:`, i.e. `--auto`, not `--live`. LIVE_TRADING_RUNBOOK.md:127-129
   already uses the correct combined phrasing, confirming the asymmetry.
5. README documents nonexistent `override set/clear` — PARTIALLY DISPROVEN (E1).
   README.md:118,192-194 do say `set|clear|status` while cmd_override() (main.py:
   3249-3299) only recognizes pause/unpause/status — that part of the finding is
   real. But the finding's central behavioral claim ("falls through and returns
   with zero output... silently no-ops... indistinguishable from a successful
   pause") is FALSE: main.py:3298-3299 has an explicit fallback branch that prints
   `Unknown override action: 'set'` plus a usage hint, for any unrecognized action.
   Traced the dispatch site (main.py:9746-9756) confirming `override set 60` really
   reaches this exact branch (action="set", mins=60 parses fine, cmd_override("set",
   60) hits neither the pause nor unpause/status branch). So the real bug is a
   loud, self-correcting CLI/doc naming mismatch, not a silent failure — downgrades
   financial_risk substantially from the original writeup.
6. cmd_schedule() docstring stale ("every hour", 1 task) — CONFIRMED (E1).
   main.py:8962-8963 docstring unchanged; actual /MO 3 (main.py ~8991) and success
   message "runs every 3 hours" confirmed; 4th task (KalshiWeatherSettlementMonitor,
   main.py:9065-9184) confirmed added by commit 64c08693 without a docstring touch.
7. Five shadow-only trading flags undocumented — CONFIRMED (E1). Grep across
   README.md/COMMANDS.md/LIVE_TRADING_RUNBOOK.md/.env.example for all 5 names
   (HURRICANE_TRADING_ENABLED, HURRICANE_NEXT_EVENT_TRADING_ENABLED,
   STORM_ORDER_TRADING_ENABLED, SNOW_TRADING_ENABLED, HOURLY_TRADING_ENABLED)
   returns zero matches; all 5 are real, live-checked gates in main.py/paper.py/
   weather_markets.py.
8. Exposure-cap blind spot (L1994) not surfaced in runbook — CONFIRMED (E1).
   paper.check_position_limits (paper.py:3447+) traced end-to-end: its only
   exposure source is `get_open_trades()` (paper ledger); no execution_log/
   LivePositionStore reference anywhere in the function body. backlog.txt:1999+
   confirms the same finding, filed and still open. LIVE_TRADING_RUNBOOK.md's
   exposure-cap table (line 63) and monitoring section never mention this gap.

No files modified outside audit/. No repo state changed.
