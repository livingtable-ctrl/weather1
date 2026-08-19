# Pass 21 — Documentation & Configuration (Sections 31-32)

Scope: README.md, LIVE_TRADING_RUNBOOK.md, COMMANDS.md, BACKLOG_OPEN.md/backlog.txt,
inline docstrings/comments, env vars/.env.example, .github/workflows/ci.yml,
cron.py scheduling, vs the 53-commit recent-feature window (2026-08-02..08-17).

## Verified clean (no finding)
- GFS lockout removal (8701f49d): .env.example/COMMANDS.md never referenced
  GFS_LOCKOUT_MINS; config.py's dead field + test allowlist entry both removed
  together; backlog.txt entry properly marked RESOLVED with full changelist.
- config.py's MAX_DAYS_OUT/MAX_CITY_DATE_EXPOSURE/MIN_ARB_EDGE "historical
  divergence" docstrings are accurate explanations of *why* the pattern
  exists (defaults now sourced live from utils.py via `from utils import X
  as _fallback`), not currently-live divergences.
- safe_io.py's Windows os.replace() PermissionError retry (94d36402) is
  tested via explicit monkeypatched PermissionError injection
  (tests/test_safe_io.py:169-263), not incidentally-Windows-only -- CI
  running on ubuntu-latest does exercise this logic correctly.
- circuit_breaker.py's data/.cb_state.json path matches
  LIVE_TRADING_RUNBOOK.md Part 1.5 exactly.
- cron.py's run_trade_cycle() call passes live=False unconditionally
  (cron.py:1285) -- confirms RUNBOOK's "cron never places live orders"
  claim (lines 102-104, 131) is still true post-86b5dc2d/dfcd5f7c refactor.
- BACKLOG_OPEN.md and backlog.txt are both at HEAD (d190d09d), not stale
  relative to git history.
- backlog.txt's own L1947/L1994 entries (prod-banner wording, exposure-cap
  blindness) are detailed, accurate, and cite correct line numbers/reasoning
  -- good backlog hygiene, just not yet implemented.

## Findings filed via StructuredOutput
8 findings, see structured output. Highlights:
- README.md never mentions LIVE_TRADING_ENABLED (the secondary go-live
  interlock) anywhere -- not in the env var table, not in "Graduation to
  live trading". .env.example omits it too.
- LIVE_TRADING_RUNBOOK.md's gate-logic appendix says "no override short of
  modifying source code" -- false since 251e838e added `admin
  accuracy-override`.
- main.py's KALSHI_ENV=prod banner text is stale re: cmd_order's live path
  (e5331a8d) -- already tracked as backlog.txt L1947 [OPEN], confirmed still
  present in code at main.py:9562-9584.
- COMMANDS.md implies `watch --live` alone routes to live orders; actually
  cmd_watch() only calls run_trade_cycle() (the sole placement path) when
  `--auto` is also passed -- `--live` alone is inert/read-only.
- README.md documents `override set`/`override clear` subcommands that do
  not exist in the CLI (real names: pause/unpause/status per main.py:3249)
  -- an unrecognized action silently no-ops with zero output.
- cmd_schedule()'s docstring is stale on both interval ("every hour" vs
  actual "every 3 hours") and scope (registers 4 tasks, docstring describes
  none of the email/settle/settlement-monitor tasks) -- 64c08693 added the
  4th task without touching the docstring.
- The 5 new shadow-only activation flags (HURRICANE_TRADING_ENABLED,
  HURRICANE_NEXT_EVENT_TRADING_ENABLED, STORM_ORDER_TRADING_ENABLED,
  SNOW_TRADING_ENABLED, HOURLY_TRADING_ENABLED) appear in zero static docs.
