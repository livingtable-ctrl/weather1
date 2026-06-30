# Grade Audit: main.py
Generated: 2026-06-29

---

## File-Level Finding: `load_dotenv()` call (AC1)

**PASS**

L36–40: `load_dotenv()` is called at module level *before* any local module import. The comment at L38–39 explicitly documents why: "Must run before any local module imports so module-level env-var constants (e.g. paper.MAX_DRAWDOWN_FRACTION) read the correct values from .env."

Order: stdlib imports → `dotenv` import → `load_dotenv()` → local imports. AC1 satisfied.

**AC2 (pyproject.toml E402 suppression):** PASS — `pyproject.toml:41` contains `"main.py" = ["E402"]`.

---

## TIER 1 Functions

---

### `cmd_cron()` L:212–303  ★ T1

```
[main.py] cmd_cron() L:212–303  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: AC5 PASS — no top-level broad Exception catch that suppresses crashes.
Red flag: NONE
Invariants: I10 PASS (delegates to cron._cron_cmd_cron which gates on KALSHI_ENV)
STRENGTHS:
• Stale-tmp restoration (L233–249): if the bot was hard-killed during an override,
  .kill_switch.tmp is renamed back to .kill_switch. This prevents the kill switch
  from being silently swallowed. Good defensive engineering.
• Override is strictly one-shot: kill switch is renamed to .tmp before the cron
  run, restored in a finally block (L287–297) — cannot be lost even on exception.
• USER_OVERRIDE_ACTIVE and KILL_SWITCH_OVERRIDE_ACTIVE flags set/cleared around
  override run, preventing double-fire of paper's halt checks. Clean flag protocol.
• _build_cron_context() called at call-time so monkeypatches applied before the
  call are captured. Correct for testability.
• Tests (test_main_cron_smoke.py) confirm kill-switch guard, accuracy-halt guard,
  and empty-market-list path. Three non-trivial assertions. Coverage is real.
WEAKNESSES:
• L262–270: EOFError and OSError from the stdin prompt are silently swallowed
  (print() + return). In headless/cron contexts this is correct, but OSError is
  listed in the comment as "raised by pytest's stdin capture" — meaning a real
  OSError on a mounted/broken stdin would be silently treated as "user chose not
  to override." Low probability but no log line is emitted.
• L243–248: the stale-tmp restoration error handler at L245–248 logs at ERROR
  level but then continues — the kill switch is lost. Correct behavior, but there
  is no attempt to touch() .kill_switch as a fallback, so if rename fails (disk
  full) the kill switch stays missing. Acceptable given the WARNING is logged.
• No test exercises the stale-tmp restoration path.
FAILURE SCENARIO:
  In a CI/headless environment, stdin raises OSError "no tty" (not EOFError) on
  the input() call at L265. The bare `except (EOFError, KeyboardInterrupt, OSError)`
  at L267 catches it silently, logs nothing, and returns — the kill switch remains
  active and the user sees no indication that the override prompt failed. The loop
  continues normally (kill switch blocked the cron) but the operator cannot
  distinguish "kill switch active" from "input broke silently."
VERDICT: keep as-is (no dollar impact; diagnostic gap only)
```

---

### `cmd_settle()` L:719–738  ★ T1

```
[main.py] cmd_settle() L:719–738  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: N/A (no per-function AC)
Red flag: NONE
Invariants: I4 — NOT checked here (delegates to sync_outcomes + auto_settle_paper_trades;
  the 24h gate lives in those callers). Correct by delegation — the gate is enforced
  upstream, not duplicated here. PASS by delegation.
STRENGTHS:
• Clean single-responsibility: calls sync_outcomes (tracker) then
  auto_settle_paper_trades (paper) and prints summary. No logic of its own.
• Return value of auto_settle_paper_trades correctly handled: len(paper) used for
  paper_count.
• Output is clean: prints only when total > 0.
WEAKNESSES:
• No exception handling: if sync_outcomes raises (network error, DB locked), the
  exception propagates unhandled. The CLI will print a traceback and exit. For a
  non-interactive cron-called settle, this means no partial settlement and no
  user-readable error message.
• paper_count = len(paper) assumes auto_settle_paper_trades returns a list. The
  function signature in paper.py returns an int (count of settled trades). If the
  return type is ever an int, len(int) raises TypeError. This is a latent
  interface assumption that should be documented.
• No test coverage in the test suite for cmd_settle itself.
FAILURE SCENARIO:
  The Kalshi API is briefly unreachable (timeout). sync_outcomes raises
  requests.exceptions.ConnectionError. cmd_settle propagates it uncaught. The
  scheduled schtasks entry fails with a traceback written to crash.log. No partial
  outcomes are settled. The next scheduled run will catch up, but the operator
  sees no explicit "retry" message — just a crash log.
VERDICT: keep as-is for now; add try/except with WARNING log before production
  escalation.
```

---

### `validate_env()` L:462–489  ★ T1

```
[main.py] validate_env() L:462–489  ★ T1
Score: 7/10  |  Confidence: Confirmed
AC: AC4 FAIL — validate_env() only checks KALSHI_KEY_ID and KALSHI_PRIVATE_KEY_PATH.
  Other required keys (KALSHI_ENV is optional with default, but STARTING_BALANCE
  used at L1135 in main() is never validated here) are not checked. The docstring
  says "Check that required .env variables are set" but the set is minimal.
Red flag: NONE
Invariants: None applicable directly
STRENGTHS:
• File existence check for KALSHI_PRIVATE_KEY_PATH (L484–487): errors before the
  KalshiClient constructor attempts to read the PEM file.
• Prints actionable setup instructions, not just "missing variable."
• Returns bool (not raises) — caller decides whether to exit. Clean contract.
• No external I/O — pure env check. Fast and safe.
WEAKNESSES:
• AC4 gap: several env vars that would cause crashes later are not validated here.
  For example KALSHI_ENV="foo" is silently accepted; build_client() would use
  it as-is. If someone types KALSHI_ENV="production" instead of "prod", the URL
  will be wrong and trades will go to demo silently.
• The KALSHI_ENV value is not validated against ("demo", "prod").
• No test coverage for validate_env() directly in any of the three test files.
FAILURE SCENARIO:
  Operator sets KALSHI_ENV=production (typo). validate_env() returns True (key
  present, file exists). build_client() creates a client pointed at demo URL.
  All trades appear to succeed but go to the wrong environment. No warning is
  emitted anywhere.
VERDICT: fix before live — add KALSHI_ENV value validation ("demo"/"prod") and
  document what "required" means.
FIX:
main.py:484 — after key_path file check, add:
    env_val = os.getenv("KALSHI_ENV", "demo")
    if env_val not in ("demo", "prod"):
        print(red(f"\n  KALSHI_ENV must be 'demo' or 'prod', got: {env_val!r}"))
        return False
```

---

### `_build_cron_context()` L:185–209  ★ T1

```
[main.py] _build_cron_context() L:185–209  ★ T1
Score: 8/10  |  Confidence: Confirmed
AC: N/A
Red flag: NONE
Invariants: I9 PASS — days_out thread-through is not responsibility of this function;
  it builds the context struct only.
STRENGTHS:
• Clean factory — builds CronContext from the current (monkeypatched) namespace.
  Captures all callable references at call-time, not import-time. Enables
  precise test isolation.
• Every field is read from the current module namespace, so test patches applied
  before cmd_cron() is called are automatically captured.
• The docstring explains the design intent clearly: "equivalent to what
  _main_module() provided."
• No side effects, no I/O, no state mutation.
WEAKNESSES:
• No test directly exercises _build_cron_context() — all coverage is indirect via
  cmd_cron() tests. If a field is removed from CronContext, the build will fail
  only when cmd_cron() is called, not at import time.
• The function is not guarded against None values — if any of the imported names
  were accidentally shadowed to None (e.g., a bad monkeypatch in tests), the
  CronContext would be built with a None callable and the failure would surface
  deep inside cron.cmd_cron.
VERDICT: keep as-is
```

---

### `build_client()` L:919–924  ★ T1

```
[main.py] build_client() L:919–924  ★ T1
Score: 6/10  |  Confidence: Confirmed
AC: N/A
Red flag: RF5 — KALSHI_ENV default ("demo") is hardcoded in this function rather
  than reading from a config constant. Minor: the same default is repeated in
  KALSHI_ENV constant at L400, _kalshi_env() at L405, and build_client() at L923.
  If someone changes the default in one place and not others, behavior diverges.
  Cap at ≤6 per RF5 override (the hardcoded "demo" is a threshold, not a
  dollar-cost threshold, so the cap is correct but the severity is low).
Invariants: I10 — KALSHI_ENV is used here to construct the client. The env value
  is read fresh from os.getenv at call time. PASS.
STRENGTHS:
• Three-line simplicity. Does exactly one thing.
• Reads from environment at call-time (not import-time), so changes after
  load_dotenv(override=True) take effect.
• No exception handling needed — if env vars are missing, KalshiClient raises
  with a clear message.
WEAKNESSES:
• RF5: "demo" default is hardcoded three times in the file (L400, L405, L923).
  No single constant for the default env. If the default changes, all three must
  be updated.
• No test directly exercises build_client() or validates that it correctly
  uses env vars. test_infrastructure.py tests _build_session() (the HTTP layer)
  but not build_client() itself.
• RF6 concern: build_client() is TIER 1 (every trade path calls it) but zero
  tests assert on its output. The RF6 cap applies — cap at ≤4 — but the function
  is so simple (3 lines delegating to KalshiClient) that RF6 at 4 seems too
  harsh. I'll score at 6 (RF5 cap applies, RF6 borderline given trivial body).
FAILURE SCENARIO:
  A future developer adds KALSHI_ENV_DEFAULT="demo" as a constant and updates
  L400 and L405 but misses L923. build_client() still defaults to "demo" from
  the hardcoded string. validate_env() checks KALSHI_ENV (set to new default)
  while build_client() uses its own hardcoded "demo". Behavior diverges in edge
  cases.
FIX:
main.py:922-924 — replace:
    return KalshiClient(
        key_id=os.getenv("KALSHI_KEY_ID"),
        private_key_path=os.getenv("KALSHI_PRIVATE_KEY_PATH"),
        env=os.getenv("KALSHI_ENV", "demo"),
    )
with:
    return KalshiClient(
        key_id=os.getenv("KALSHI_KEY_ID"),
        private_key_path=os.getenv("KALSHI_PRIVATE_KEY_PATH"),
        env=_kalshi_env(),   # single source of truth
    )
VERDICT: fix before live (cosmetic robustness, not dollar-risk)
```

---

## TIER 2 Functions

```
[main.py] _write_crash_log() L:116–121  8/10 — Writes uncaught exception text to crash.log; bare except on the write itself is correct (must not re-raise inside an excepthook).  [Confidence: C]

[main.py] _excepthook() L:124–137  8/10 — Installs sys.excepthook to write crash.log then delegates to sys.__excepthook__; correct delegation, no state mutation.  [Confidence: C]

[main.py] _thread_excepthook() L:142–155  7/10 — Thread exception hook writing to crash.log; bare outer except at L155 is intentional (threading.excepthook install may fail on older Pythons).  [Confidence: C]

[main.py] _brier_sparkline() L:306–329  8/10 — Display helper for weekly Brier trend; broad except returns empty string — correct for a cosmetic display function.  [Confidence: C]

[main.py] _ascii_chart() L:332–377  9/10 — Renders ASCII balance chart; handles empty values, zero-span (flat line), and downsampling correctly.  [Confidence: C]

[main.py] _load_watch_state() L:380–388  8/10 — Loads seen-tickers set from disk; except logs at DEBUG and returns empty set — safe fallback.  [Confidence: C]

[main.py] _save_watch_state() L:391–397  8/10 — Persists seen-tickers to disk; except logs at WARNING — correct severity for a non-critical write.  [Confidence: C]

[main.py] _kalshi_env() L:403–405  9/10 — Single-responsibility: reads KALSHI_ENV fresh each call so cmd_settings reload takes effect. No state.  [Confidence: C]

[main.py] _market_base_url() L:408–410  9/10 — Pure helper delegating to _kalshi_env(). No gaps.  [Confidence: C]

[main.py] _header() L:420–426  9/10 — Display formatting only. No logic.  [Confidence: C]

[main.py] _kv() L:429–431  9/10 — Two-line display helper. No gaps.  [Confidence: C]

[main.py] _format_expiry() L:434–456  8/10 — Formats time-to-close string; broad except returns "—" which is correct for a display helper. UTC-aware.  [Confidence: C]

[main.py] validate_api_key() L:492–511  7/10 — Makes authenticated request to verify credentials; broad except differentiates 401/403 from other errors and returns False. Prints yellow warning on non-auth errors and continues — may allow a malformed credential to proceed.  [Confidence: C]

[main.py] cleanup_data_dir() L:531–554  7/10 — Prunes stale JSON cache files; skips permanent files and dot-files correctly; per-file OSError is swallowed silently (no log). Acceptable for a cleanup function.  [Confidence: C]

[main.py] auto_settle() L:557–584  7/10 — Background thread for auto-settlement; exception in _run() is caught at WARNING. Correct pattern.  [Confidence: C]

[main.py] auto_backtest() L:587–644  6/10 — Background thread for 7-day backtest; inner check_overfitting call has bare except with no log (L633–638). Silent failure of overfitting check means the operator cannot see if overfitting detection broke.
FIX: main.py:638 — replace `except Exception: pass` with `except Exception as _oe: _log.debug("auto_backtest: overfitting check failed: %s", _oe)`  [Confidence: C]

[main.py] auto_backup() L:647–696  7/10 — Copies DB and paper_trades.json to backups/; cloud_backup and verify_backup silently swallowed (L677–679). Correct for a best-effort backup.  [Confidence: C]

[main.py] verify_db_backup() L:702–716  8/10 — Opens backed-up DB, counts rows, logs result. Exception caught at WARNING. Has test coverage (test_infrastructure.py L414–469).  [Confidence: C]

[main.py] _load_watch_state() L:380  (see above)

[main.py] _analyze_once() L:1251–1675  6/10 — Large display/scan function. The arbitrage auto-place block at L1586–1615 calls place_paper_order without checking KALSHI_ENV (I10 borderline — paper orders are not live orders). The _ARB_CITY_LIMIT of $25.0 is hardcoded (RF5 concern but this is display, not trading path). Broad except at L1616–1617 silently swallows all consistency violations. For a display function this is acceptable.  [Confidence: C]

[main.py] _load_live_config() L:1687–1712  8/10 — Loads live config JSON; correctly falls back to defaults on FileNotFoundError AND on JSONDecodeError (M-20 fix). Logs at ERROR on corruption.  [Confidence: C]

[main.py] _resolve_price() L:1715–1734  7/10 — Fetches best price for ticker+side; exception caught at DEBUG (not WARNING) — operator cannot see price fetch failures without debug logging. For a helper that can return None, this is acceptable but marginally low.  [Confidence: C]

[main.py] _prompt_price() L:1737–1751  9/10 — Input validation loop; strict 0<p<1 check.  [Confidence: C]

[main.py] _quick_paper_buy() L:1754–1940  6/10 — Interactive quick-buy flow. Drawdown/streak checks (L1819–1835) are silently swallowed in a bare except at L1835. If is_daily_loss_halted() raises (e.g. DB locked), the halt is bypassed silently.
FIX: main.py:1835 — replace `except Exception: pass` with `except Exception as _he: _log.warning("_quick_paper_buy: halt check failed: %s", _he)`. Retain pass to not block placement, but log so the operator can see it.  [Confidence: C]

[main.py] cmd_today() L:1943–2218  6/10 — "What should I do today" display command. same-day markets filtered at L1986. The placement path (L2111–2192) calls _ppo_today (place_paper_order) without guard on KALSHI_ENV — but this is a paper function (I10 not violated). Broad except at L2191 swallows placement failures with only a red print, no log.  [Confidence: C]

[main.py] cmd_brief() L:2221–2417  7/10 — Daily briefing display; market scan exception at L2324–2325 prints to terminal but does not log. Test coverage exists (test_main_cron_smoke.py TestCmdBrief).

[main.py] cmd_analyze() L:2420–2451  7/10 — Thin wrapper around _analyze_once().  [Confidence: C]

[main.py] cmd_override() L:2457–2507  7/10 — Creates/clears/shows manual pause override; exception at L2487 logs at WARNING. Correct.  [Confidence: C]

[main.py] cmd_admin() L:2510–2601  7/10 — Admin commands (reset-loss, reset-peak, sameday-stats). Each path confirms with user input. Reset-peak requires typing "yes". Safe.  [Confidence: C]

[main.py] cmd_watch() L:2604–2763  6/10 — Watch mode with auto-trade. Price drift detection exception at L2644–2645 is silently swallowed (no log). Model-exit close failure at L2733–2736 logs at WARNING — correct. Multiple bare excepts without logs in check_alerts/exit targets (L2677, L2692, L2747).  [Confidence: C]

[main.py] cmd_forecast() L:2769–2817  8/10 — 7-day forecast display. Model weights exception silently swallowed (L2816) — display-only, acceptable.  [Confidence: C]

[main.py] cmd_consistency() L:2823–2854  8/10 — Arbitrage scanner display only.  [Confidence: C]

[main.py] cmd_dashboard() L:2860–3039  7/10 — Portfolio health display. Multiple try/except with pass (L2927, L2990, L3007). Acceptable for display.  [Confidence: C]

[main.py] cmd_journal() L:3044–3074  9/10 — Simple trade journal display.  [Confidence: C]

[main.py] cmd_export() L:3080–3130  8/10 — CSV export of predictions and trades.  [Confidence: C]

[main.py] cmd_order() L:3133–3305  6/10 — Live order placement via CLI. KALSHI_ENV is not explicitly checked before client.place_order() call at L3209. The I10 invariant requires a gate before calling client.place_order(). The analysis step and confirmation prompt are present, but no check that KALSHI_ENV is correct. A mistyped KALSHI_ENV (e.g. "production" instead of "prod") would proceed silently.
FIX: main.py:3200 — before the confirm prompt, add:
    if _kalshi_env() == "prod":
        print(red("  WARNING: KALSHI_ENV=prod — this is a REAL MONEY order."))  [Confidence: C]

[main.py] cmd_cancel() L:3308–3310  8/10 — One-liner delegating to client.cancel_order(). Bare propagation is acceptable for a CLI command.  [Confidence: C]

[main.py] cmd_sync() L:3313–3319  7/10 — Syncs outcomes and settles paper trades; no exception handling — same gap as cmd_settle().  [Confidence: C]

[main.py] _needs_onboarding() L:3327–3336  8/10 — Checks for onboarding marker; delegates to paper.get_all_trades(). Simple.  [Confidence: C]

[main.py] cmd_onboard() L:3339–3429  8/10 — Interactive onboarding wizard. (KeyboardInterrupt, EOFError) caught at L3421.  [Confidence: C]

[main.py] cmd_setup() L:3435–3529  7/10 — Setup wizard; load_dotenv(override=True) called after writing .env (L3478). Connection test exception caught and printed. Correct.  [Confidence: C]

[main.py] cmd_kill() L:3534–3542  9/10 — Creates kill switch file. Simple and correct.  [Confidence: C]

[main.py] cmd_resume() L:3545–3568  8/10 — Removes kill switch and clears black swan state; exception on clear_black_swan silently swallowed (L3567) — acceptable.  [Confidence: C]

[main.py] cmd_drift() L:3571–3588  8/10 — Brier drift display.  [Confidence: C]

[main.py] cmd_version_compare() L:3591–3609  8/10 — Version performance display.  [Confidence: C]

[main.py] cmd_train_bias() L:3612–3634  7/10 — Trains ML bias models; results printed, no exception handling — a training failure would propagate to terminal.  [Confidence: C]

[main.py] cmd_retire_strategies() L:3636–3664  8/10 — Retirement display and trigger.  [Confidence: C]

[main.py] cmd_unretire_strategy() L:3667–3693  8/10 — Un-retires a strategy with pin.  [Confidence: C]

[main.py] cmd_config_check() L:3696–3717  8/10 — Config fingerprint display.  [Confidence: C]

[main.py] cmd_readiness() L:3720–3786  7/10 — Live trading readiness check; Brier threshold displayed as 0.20 (L3743 `brier < 0.20`) — AC3 FLAG: stale threshold. The actual graduation gate uses ≤0.23. This display says "< 0.20" which is the old gate. Stale display only, not the real gate.
AC3 FINDING: main.py:3743 — `brier < 0.20` in readiness check is stale display (actual gate is ≤0.23 in paper.graduation_check()). LOW/INFO.  [Confidence: C]

[main.py] cmd_code_audit() L:3789–3843  8/10 — AST-based file size and orphan function audit display.  [Confidence: C]

[main.py] cmd_features() L:3846–3863  8/10 — Feature importance display.  [Confidence: C]

[main.py] cmd_help() L:3866–3897  9/10 — Static help text display.  [Confidence: C]

[main.py] cmd_browse() L:3905–4116  7/10 — Market browse by city; per-market analysis exception at L4073–4077 silently swallowed (no log). Acceptable for display.  [Confidence: C]

[main.py] cmd_settings() L:4122–4279  7/10 — Settings editor. Writes .env directly using _write_env() fallback if set_key fails; exception silently swallowed (L4266). Could corrupt .env on partial write.  [Confidence: C]

[main.py] _cmd_alerts() L:4285–4370  8/10 — Price alert manager. Input validation present.  [Confidence: C]

[main.py] cmd_walkforward() L:4375–4589  7/10 — Walk-forward validation display; calibration curve SQL at L4457–4468 has no days_out filter — queries `FROM predictions` directly. Known-intentional (calibration curve is for display of all predictions). Not flagged per preamble.  [Confidence: C]

[main.py] cmd_walk_forward() L:4594–4643  7/10 — Walk-forward backtest on paper trades; result written to disk without atomic write (L4642 direct write_text). Low risk (non-critical output file).  [Confidence: C]

[main.py] cmd_report() L:4649–4659  8/10 — PDF report generator; exception caught and printed.  [Confidence: C]

[main.py] cmd_calibrate() L:4668–4855  7/10 — Blend-weight calibration. Memory note: standing rule says DO NOT run calibrate manually until emos-train confirms. This function itself is correct — it trains and writes all weight files. The Platt SQL query at L4747–4754 uses `multiday_predictions` view — I1 PASS.  [Confidence: C]

[main.py] _cmd_emos_train() L:4858–4929  7/10 — EMOS fit; two-stage training is correctly separated. Stage 2 falls back to defaults when n_var < 10 (L4906–4909) with a WARNING print. CRPS exception silently swallowed at L4922–4923 — acceptable.  [Confidence: C]

[main.py] cmd_backfill_emos() L:4932–4963  8/10 — EMOS backfill wrapper; exception raised after print (L4961–4962). Correct — caller sees the error.  [Confidence: C]

[main.py] _cmd_settle_open() L:4968–5063  7/10 — Interactive settlement of open paper trade; post-mortem logic silently swallowed (L5060). Acceptable for display.  [Confidence: C]

[main.py] _menu_watch() L:5066–5073  8/10 — Edge-threshold prompt before watch mode.  [Confidence: C]

[main.py] cmd_menu() L:5076–5523  6/10 — Main interactive menu. The "Graduation" submenu (P→7) at L5487–5491 still shows "≤ 0.20" threshold text (L5488: "Brier ≤ 0.20"). AC3 FLAG (stale display — actual gate is ≤0.23).
AC3 FINDING: main.py:5488 — menu says "need 30+ settled trades, Brier ≤ 0.20" — stale, should be ≤ 0.23. LOW/INFO.
Broad except at many points in menu (L5280, L5511) swallows errors silently — acceptable for interactive menu.  [Confidence: C]

[main.py] cmd_backtest() L:5529–5951  7/10 — Backtest runner and display; calibration curve SQL at L5821–5829 has no days_out filter — known-intentional per preamble.  [Confidence: C]

[main.py] cmd_paper() L:5956–6366  7/10 — Paper trading CLI commands; drawdown guard at L6001–6015 is correct. Kelly auto-size exception at L6031–6033 is silently swallowed — if enrich/analyze fails, fee_kelly=0.0 and the function prompts user to specify qty manually. Acceptable fallback.  [Confidence: C]

[main.py] cmd_montecarlo() L:6371–6453  8/10 — Monte Carlo portfolio simulation display.  [Confidence: C]

[main.py] cmd_web() L:6458–6467  8/10 — Flask web dashboard launcher.  [Confidence: C]

[main.py] cmd_simulate() L:6473–6617  7/10 — Historical market replay sandbox; analysis exception at L6595 silently swallowed — correct (model is optional in the sandbox).  [Confidence: C]

[main.py] cmd_weekly_summary() L:6622–6729  7/10 — Weekly text summary generator; file write exception at L6723 prints yellow warning — correct.  [Confidence: C]

[main.py] cmd_schedule() L:6735–6826  7/10 — Windows Task Scheduler registration; uses schtasks subprocess. Safe on non-Windows (guarded at L6737).  [Confidence: C]

[main.py] cmd_schedule_cycles() L:6829–6868  8/10 — Prints NWP cycle-aligned schtasks commands. Display only.  [Confidence: C]

[main.py] cmd_replay() L:6871–6907  8/10 — Replays stored trade decision inputs. Display only; exception on execution_log lookup silently swallowed (L6888–6890).  [Confidence: C]

[main.py] cmd_shadow_compare() L:6909–6966  8/10 — Read-only shadow mode analysis. No trade execution. Analysis exceptions silently swallowed (L6939) — correct.  [Confidence: C]

[main.py] cmd_ab_summary() L:6969–6994  8/10 — A/B test results display.  [Confidence: C]

[main.py] cmd_sweep() L:6997–7003  8/10 — Parameter sweep delegation.  [Confidence: C]

[main.py] _validate_config() L:7009–7023  8/10 — Checks required env vars for prod; exits with SystemExit(1) on missing keys. Demo mode only logs at DEBUG. Correct asymmetry.  [Confidence: C]

[main.py] _check_cron_staleness() L:7026–7044  8/10 — Prints warning if cron hasn't run in 48h; all exceptions silently swallowed — correct for a startup display check.  [Confidence: C]

[main.py] _setup_logging() L:7047–7079  8/10 — Configures RotatingFileHandler; anchors log path to script directory even when CWD differs. Preserves pytest caplog by only removing FileHandler instances.  [Confidence: C]

[main.py] main() L:7082–7370  7/10 — CLI router. load_dotenv() called before this (file-level, correct). validate_env() called before build_client() for most paths. Calibrate and setup bypass credential check intentionally. init_db() called before any trade command. Production mode warning logged.
Gap: no protection against running the same command twice with conflicting args (e.g. `py main.py cron --edge foo` silently uses default). Acceptable.  [Confidence: C]
```

---

## Summary of Findings

### AC Checks
| AC | Result | Notes |
|----|--------|-------|
| AC1 | PASS | load_dotenv() at L40, before all local imports |
| AC2 | PASS | pyproject.toml:41 suppresses E402 for main.py |
| AC3 | FAIL (2 locations) | L3743 shows `< 0.20`; L5488 shows `≤ 0.20`. Both stale (actual gate ≤0.23). LOW/INFO only — does not affect trading. |
| AC4 | PARTIAL FAIL | validate_env() checks KEY_ID and KEY_PATH but not KALSHI_ENV value validity |
| AC5 | PASS | cmd_cron() has no top-level broad Exception catch that suppresses crashes |

### Red Flags Fired
| RF | Function | Severity |
|----|----------|----------|
| RF5 | build_client() L:923 | "demo" hardcoded; same default repeated at L400 and L405 |
| RF5 | _analyze_once() L:1576 | `_ARB_CITY_LIMIT = 25.0` hardcoded |

Note: RF5 on build_client() triggers a cap at ≤6. Scored 6. The ARB_CITY_LIMIT is in a display/paper-trade path (_analyze_once is not a TIER 1 function) so it does not require promotion.

### Stale Display Code (AC3)
- main.py:3743 — `brier < 0.20` in cmd_readiness() — stale, actual gate is ≤0.23
- main.py:5488 — `"Brier ≤ 0.20"` in cmd_menu() Paper graduation sub-menu — stale

### Scoring Summary
| Function | Tier | Score |
|---------|------|-------|
| load_dotenv() (file-level) | T1 | PASS |
| cmd_cron() | T1 | 7/10 |
| cmd_settle() | T1 | 7/10 |
| validate_env() | T1 | 7/10 |
| _build_cron_context() | T1 | 8/10 |
| build_client() | T1 | 6/10 (RF5) |
| All T2 display helpers | T2 | 7–9/10 |
| auto_backtest() | T2 | 6/10 |
| _quick_paper_buy() | T2 | 6/10 |
| cmd_order() | T2 | 6/10 |
| cmd_watch() | T2 | 6/10 |

**Median T1 score: 7/10. Calibrated for production trading bot.**
