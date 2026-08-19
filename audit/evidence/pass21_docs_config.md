# Pass 21 — Documentation & Configuration — Evidence Notes

Scope: README.md, LIVE_TRADING_RUNBOOK.md, COMMANDS.md, BACKLOG_OPEN.md/backlog.txt,
.env.example, .github/workflows/ci.yml, pyproject.toml, inline docstrings/comments,
env-var defaults, feature flags, logging, CI/CD, scheduled jobs (cron.py/cmd_schedule).

## Key facts established this pass

- trading_gates.py `LiveTradingGate.check()` has 9 sequential checks: TRADING_PAUSED,
  KILL_SWITCH_PATH, base_url/KALSHI_ENV, LIVE_TRADING_ENABLED, is_paused_drawdown,
  is_streak_paused, is_daily_loss_halted, is_accuracy_halted, graduation_check.
  LIVE_TRADING_RUNBOOK.md's Appendix lists only 7 and says "All seven gates must
  pass" -- omits TRADING_PAUSED and the kill switch.

- cron.py hardcodes `run_trade_cycle(..., live=False, ...)` (cron.py:1285) --
  confirmed cron genuinely never places live orders, matching RUNBOOK's claim
  for cron specifically. cmd_watch (main.py:3632-3640) passes `live=live` from
  the `--live` CLI flag -- also matches RUNBOOK.
  HOWEVER: main.py's `cmd_order` (the `buy`/`sell` CLI commands, main.py ~L4333+)
  independently derives `_is_live = getattr(client, "base_url", None) != DEMO_BASE`
  (main.py:4528) and calls `pre_live_trade_check(client)` (main.py:4530-4537) --
  i.e. manual `buy`/`sell` ALSO places real live orders once KALSHI_ENV=prod +
  LIVE_TRADING_ENABLED=true, contradicting RUNBOOK lines 102-104 and 131
  ("only `watch --auto --live` does"). This exact misconception is already
  tracked for main.py's own startup banner as backlog.txt entry L1947 (still
  OPEN as of BACKLOG_OPEN.md) -- but L1947 only covers the console banner, not
  LIVE_TRADING_RUNBOOK.md, which repeats the same false claim in the project's
  primary live-trading safety document.

- utils.py:106 `KELLY_CAP: float = float(os.getenv("KELLY_CAP", "0.25"))` and
  config.py:117-127 `_live_kelly_cap()` both confirm KELLY_CAP IS env-configurable.
  LIVE_TRADING_RUNBOOK.md's Risk Limits table (line 65) claims
  "KELLY_CAP | 0.25 (hardcoded, not env-configurable)" -- factually wrong.
  (MAX_CORRELATED_EXPOSURE's "hardcoded" claim on the same table IS correct --
  paper.py:342 has no os.getenv call for it.)

- README.md lines 118, 192-194 document `python main.py override set 60` /
  `override clear` / `override status`. main.py's actual dispatcher (line 9746)
  and `cmd_override()` (main.py:3249-3299) only implement `pause`/`unpause`/
  `status`; any other action string (e.g. `set`, `clear`) falls through to
  the `else` branch printing "Unknown override action: 'set'" and the correct
  usage string. COMMANDS.md (lines 98-100, 157-162) documents `pause`/`unpause`/
  `status` correctly -- so README.md and COMMANDS.md directly contradict each
  other, and README.md is the one that's wrong. Confirmed via E1 static read
  of the dispatcher and function body (execution attempt was blocked by the
  sandbox's Bash classifier; not needed given the code is unambiguous).

- .env.example line 45-47: "Optional: protect the web dashboard with HTTP
  Basic Auth / Leave empty to disable auth (default for local use) /
  DASHBOARD_PASSWORD=". Reproduced live (E3): calling `web_app._build_app(None)`
  with DASHBOARD_PASSWORD and DASHBOARD_UNPROTECTED both unset raises
  `RuntimeError: DASHBOARD_PASSWORD must be set. The dashboard exposes kill
  switch and trade control endpoints. Set DASHBOARD_UNPROTECTED=true to run
  without a password (dev/test only).` (web_app.py:153-164). So the shipped
  .env.example default (empty DASHBOARD_PASSWORD) does NOT "disable auth" --
  it prevents `python main.py web` from starting at all. Neither
  DASHBOARD_UNPROTECTED nor this requirement is mentioned in README.md.

- README.md's env var table (lines 244-286) does not list any of the 6
  shadow-only `*_TRADING_ENABLED` flags found via grep: HOURLY_TRADING_ENABLED,
  HURRICANE_NEXT_EVENT_TRADING_ENABLED, HURRICANE_TRADING_ENABLED,
  RAIN_TRADING_ENABLED, SNOW_TRADING_ENABLED, STORM_ORDER_TRADING_ENABLED.
  git log -S confirms HURRICANE_TRADING_ENABLED (1a7c9aca, 08-03),
  HURRICANE_NEXT_EVENT_TRADING_ENABLED (46c44435, 08-07), and
  STORM_ORDER_TRADING_ENABLED (9a7583aa, 08-07) were all added within this
  audit's target commit window (cluster G). RAIN_/SNOW_/HOURLY_TRADING_ENABLED
  predate the window.

- README.md line 361: "The bot only trades Kalshi weather markets (temperature
  and precipitation). It ignores all other market types." -- contradicted by
  the hurricane shadow-only models (KXNEXTHURDATE, KXFIRSTHURRICANE,
  KXNEXTCAT5HURDATE) added in cluster G, which are hurricane-event markets,
  not temperature/precipitation, and which main.py explicitly has logic to
  place real orders on once their respective env flags are enabled (recon
  Section 2G, verified main.py ~L4378-4410 refusal logic exists specifically
  because the capability exists).

- README.md line 203: "Once ~25 rows are accumulated, an `emos-train` command
  will fit..." -- main.py `_cmd_emos_train`'s `--activate` path hard-refuses
  below `_EMOS_VAR_FLOOR = 40` ens_var rows (main.py:6663-6679). This constant
  was introduced in commit 4557a77b (2026-08-15, "add EMOS activation
  confirmation gate" -- in this audit's target commit window; confirmed via
  `git log -p -S"_EMOS_VAR_FLOOR"`, single hit). Before that commit there was
  no hard floor at all (only a softer n_var>=10 check for a "real" vs
  default-value fit). COMMANDS.md line 62 correctly documents the "40 ens_var
  rows" floor -- so README.md's "~25" now contradicts both the code and
  COMMANDS.md.

- main.py:8963 `cmd_schedule()` docstring: `"""Register a Windows Task
  Scheduler job to auto-scan every hour."""` -- but the function's own
  schtasks command (main.py:8991) uses `/SC HOURLY /MO 3` (every 3 hours),
  and its own success message (main.py:9008) prints "runs every 3 hours".
  Docstring contradicts the function's own body and output. Predates the
  audit's 53-commit window (git blame: d7b2ad7e, 2026-04-09) -- SCOPE D.

- README.md line 278 env var table: `NOTIFY_CHANNELS` default listed as
  `desktop,discord`. notify.py:42 actual default:
  `os.getenv("NOTIFY_CHANNELS", "desktop,pushover,ntfy,discord,email")` --
  matches .env.example line 43, not README.md.

- .github/workflows/ci.yml runs `pytest -v --cov=. --cov-report=term-missing`
  (line 41) then, as a separate step, `pytest --cov=. --cov-fail-under=40 -q`
  (line 44) -- the entire test suite (156 files) executes twice per CI run.
  No functional bug, just wasted CI time -- logged as INFO/PERFORMANCE.

- pyproject.toml's `integration` marker docstring implies integration tests
  are "run with '-m integration'" (i.e. excluded otherwise), but there is no
  `addopts` excluding the marker, and CI's `pytest -v --cov=.` does not pass
  `-m "not integration"` either. tests/test_integration_live.py stays CI-safe
  only because each test calls `pytest.skip()` internally when
  `KALSHI_ENV != "demo"` -- a self-skip convention, not a pytest-config
  exclusion the marker docstring implies. INFO-level.

## Not re-filed as new findings (already tracked elsewhere)

- backlog.txt L1947 (main.py startup banner's `_live_orders_possible` false
  claim) -- distinct code surface from the RUNBOOK finding above but same
  underlying misconception; left as background corroboration, not duplicated.
- backlog.txt "main.py's _rating() CLI TABLE IS A 4TH...STAR LADDER" entry
  (~line 19016) -- a code/display consistency bug, not a doc/config issue,
  and already extensively documented by the project's own backlog with more
  detail than this pass could usefully add.
- config.py's documented BotConfig-vs-utils.py divergence history (MAX_DAYS_OUT,
  MAX_CITY_DATE_EXPOSURE, MIN_ARB_EDGE) -- already flagged repo-wide by the
  recon pass; verified README's stated defaults (MAX_DAYS_OUT=5) match the
  real enforcing utils.py value, so no NEW discrepancy found there this pass.
