#!/usr/bin/env python3
"""Kalshi Weather Prediction Markets — run with no arguments for interactive menu."""

import io
import json
import logging
import os
import sys
import time
import traceback as _traceback
import types
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# Fix Windows console encoding for Unicode/emoji characters
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
elif sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Guard: show clear stdout error on missing packages (not a silent stderr crash)
try:
    import dotenv as _dotenv_check  # noqa: F401
    import requests as _requests_check  # noqa: F401
    import tabulate as _tabulate_check  # noqa: F401
except ImportError as _e:
    print(f"\n  ERROR: Required package missing: {_e}")
    print("  Fix:  pip install -r requirements.txt")
    print("  Note: On Windows use  py main.py  not  python main.py\n")
    if sys.platform == "win32" and sys.stdin.isatty():
        try:
            input("  Press Enter to close...")
        except (EOFError, KeyboardInterrupt):
            pass
    sys.exit(1)

from dotenv import load_dotenv

# Must run before any local module imports so module-level env-var constants
# (e.g. paper.MAX_DRAWDOWN_FRACTION) read the correct values from .env.
load_dotenv()

from tabulate import tabulate

import order_executor  # noqa: F401 — imported for side-effects (e.g. _MIN_EDGE_AB_TEST init)
from colors import (
    bold,
    cyan,
    dim,
    edge_color,
    green,
    liquidity_color,
    prob_color,
    red,
    signal_color,
    yellow,
)
from config import BotConfig
from consistency import find_violations, get_shadow_observation_report
from kalshi_client import (
    KalshiClient,
    OrderStatusUnknownError,
    compute_client_order_id,
)
from notify import alert_strong_signal
from order_executor import (  # noqa: F401 — re-exports: tests + main code reference these via main.*
    _auto_place_trades,
    _check_early_exits,
    _check_live_model_exits,
    _check_live_position_exits,
    _count_open_live_orders,  # noqa: F401
    _daily_paper_spend,
    _liquidation_price,
    _log_shadow_predictions,
    _place_live_order,  # noqa: F401
    _poll_pending_orders,
    _prediction_kwargs_from_analysis,
    _reprice_or_cancel_pending_orders,
    _validate_trade_opportunity,  # noqa: F401
    place_paper_order,  # noqa: F401
)
from output_formatters import (
    cmd_balance,
    cmd_history,
    cmd_pnl_attribution,
    cmd_positions,
)
from paths import (
    BLACK_SWAN_PATH,
    CRASH_LOG_PATH,
    CRON_HEARTBEAT_PATH,
    CRON_LAST_RUN_PATH,
    DATA_DIR,
    EXPORTS_DIR,
    LAST_BACKTEST_PATH,
    LAST_CALIBRATION_COUNT_PATH,
    LIVE_CONFIG_PATH,
    METAR_CALIBRATION_PATH,
    ONBOARDED_MARKER_PATH,
    WALK_FORWARD_RESULTS_PATH,
    WATCH_STATE_PATH,
)
from tracker import (
    brier_score,
    brier_score_rolling_with_n,
    export_predictions_csv,
    get_calibration_trend,
    get_source_reliability,
    init_db,
    log_prediction,
    sync_outcomes,
)

# NOTE: these are frozen at process-import time -- if any test ever calls
# importlib.reload(utils) (several do, to re-read an env-var-driven constant
# for a test of utils' own parsing logic), main.<symbol> here permanently
# diverges from the live utils.<symbol> for the rest of that pytest session,
# since reload() rebinds every name in the module but nothing re-imports
# main's copies. is_trading_paused is the highest-risk symbol here (a
# function object, not a plain constant) -- this is the exact bug class
# already hit once for order_executor._prediction_kwargs_from_analysis (see
# backlog.txt's LOG_PREDICTION KWARGS entry) and audited but left latent
# here since no test currently asserts `main.<symbol> is utils.<symbol>`
# identity (see backlog.txt's frozen-import entry for the full audit: 3 of
# the 7 current reload(utils) call sites were converted to
# monkeypatch.setattr(utils, ...) instead, since the functions they feed
# re-import from utils fresh per call; the remaining 4 genuinely need to
# reload utils because they test utils' own env-parsing directly).
from utils import MIN_ARB_EDGE, MIN_EDGE, STRONG_EDGE, is_trading_paused
from weather_markets import (
    _CITY_TZ,
    _KXRAIN_MONTHLY_CITY,
    _KXSNOW_MONTHLY_CITY,
    _KXTEMP_HOURLY_CITY,
    CITY_COORDS,
    _between_metar_gates_active,
    _feels_like,
    _holiday_temp_gates_active,
    _hourly_live_ok,
    _hurricane_count_gates_active,
    _hurricane_next_event_gates_active,
    _rain_gates_active,
    _snow_gates_active,
    _storm_order_gates_active,
    analyze_trade,
    batch_prewarm_forecasts,
    check_ensemble_circuit_health,  # noqa: F401 — used via main.* in cron.py
    detect_hedge_opportunity,
    enrich_with_forecast,
    fetch_temperature_ecmwf,  # noqa: F401 — used via main.* in cron.py
    fetch_temperature_nbm,  # noqa: F401 — used via main.* in cron.py
    fetch_temperature_weatherapi,  # noqa: F401 — used via main.* in cron.py
    flush_ensemble_disk_cache,
    flush_forecast_disk_cache,
    get_weather_forecast,
    get_weather_markets,
    is_between_bracket_ticker,
    is_holiday_temp_ticker,
    is_hurricane_count_ticker,
    is_hurricane_next_event_ticker,
    is_hurricane_ticker,
    is_liquid,
    is_rain_daily_ticker,
    is_rain_holiday_ticker,
    is_rain_weekend_ticker,
    is_storm_order_ticker,
    parse_city_date,
    parse_market_price,
    reset_gate_counts,
)

# H-1: intentionally unvalidated (BotConfig.from_env(), not config.load_and_validate()).
# This runs at MODULE IMPORT TIME -- before sys.excepthook is installed below, and
# before main() ever gets a chance to look at args[0] and decide whether this
# subcommand is exempt from strict trading-parameter validation. Calling .validate()
# here would mean ANY out-of-bounds env value (e.g. a menu-writable KALSHI_FEE_RATE=0,
# or MIN_EDGE>STRONG_EDGE) bricks every CLI command including `py main.py kill` -- the
# runbook's documented emergency halt -- with a raw unhandled traceback and no
# crash.log (batch-09 closed this exact regression for the KALSHI_ENV check;
# batch-29 reopened it for 7 new bounds checks without noticing the same import-time
# hazard applied). Actual bounds validation now happens in main(), after dispatch
# decides the command isn't exempt -- see the config.validate() gate below.
_bot_config = BotConfig.from_env()

# Crash log: write uncaught exceptions (including from threads) to data/crash.log
# so the error survives even when the terminal window closes before the user can read it.
_CRASH_LOG = CRASH_LOG_PATH


def _write_crash_log(header: str, text: str) -> None:
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as _f:
            _f.write(f"\n{'=' * 60}\n{header}\n{'=' * 60}\n{text}\n")
    except Exception:
        pass


def _excepthook(
    exc_type: type[BaseException],
    exc_val: BaseException,
    exc_tb: types.TracebackType | None,
) -> None:
    msg = "".join(_traceback.format_exception(exc_type, exc_val, exc_tb))
    _write_crash_log(
        f"UNCAUGHT EXCEPTION {datetime.now().isoformat(timespec='seconds')}",
        msg,
    )
    sys.__excepthook__(exc_type, exc_val, exc_tb)


sys.excepthook = _excepthook

try:
    import threading as _threading

    def _thread_excepthook(args: _threading.ExceptHookArgs) -> None:
        msg = "".join(
            _traceback.format_exception(
                args.exc_type, args.exc_value, args.exc_traceback
            )
        )
        _write_crash_log(
            f"THREAD EXCEPTION {datetime.now().isoformat(timespec='seconds')} "
            f"thread={args.thread}",
            msg,
        )

    _threading.excepthook = _thread_excepthook
except Exception:
    pass

# Variants sampled round-robin; loser auto-disabled after 50 trades.
REFRESH_SECS = 300  # watch mode interval
_WATCH_STATE_PATH = WATCH_STATE_PATH

import cron as _cron_module  # noqa: E402 — used to set USER_OVERRIDE_ACTIVE flag
import paper as _paper_module  # noqa: E402 — used to set KILL_SWITCH_OVERRIDE_ACTIVE flag
from cron import (  # noqa: E402 (after module-level constants)
    KILL_SWITCH_PATH,  # noqa: F401 — re-exported; tests patch main.KILL_SWITCH_PATH
    LOCK_PATH,  # noqa: F401 — re-exported; tests patch main.LOCK_PATH
    RUNNING_FLAG_PATH,  # noqa: F401 — re-exported; tests patch main.RUNNING_FLAG_PATH
    _acquire_cron_lock,  # noqa: F401 — re-exported for tests that patch main.*
    _check_accuracy_halt,
    _check_graduation_gate,  # used in _build_cron_context() below
    _check_manual_override,  # noqa: F401
    _check_spend_cap_vs_balance,  # noqa: F401
    _check_startup_orders,  # noqa: F401
    _clear_cron_running_flag,  # noqa: F401
    _release_cron_lock,  # noqa: F401
    _write_cron_running_flag,  # noqa: F401
)
from cron import (  # noqa: E402
    CronContext as _CronContext,
)
from cron import (  # noqa: E402
    cmd_cron as _cron_cmd_cron,
)


def _build_cron_context() -> _CronContext:
    """Build a CronContext from the current (possibly monkeypatched) main namespace.

    Called at cmd_cron call-time so test patches applied before the call are
    captured in the context — equivalent to what _main_module() provided.
    """
    return _CronContext(
        check_manual_override=_check_manual_override,
        write_cron_running_flag=_write_cron_running_flag,
        check_startup_orders=_check_startup_orders,
        check_ensemble_circuit_health=check_ensemble_circuit_health,
        get_weather_markets=get_weather_markets,
        enrich_with_forecast=enrich_with_forecast,
        get_weather_forecast=get_weather_forecast,
        fetch_temperature_nbm=fetch_temperature_nbm,
        fetch_temperature_ecmwf=fetch_temperature_ecmwf,
        fetch_temperature_weatherapi=fetch_temperature_weatherapi,
        analyze_trade=analyze_trade,
        auto_place_trades=_auto_place_trades,
        log_shadow_predictions=_log_shadow_predictions,
        sync_outcomes=sync_outcomes,
        check_early_exits=_check_early_exits,
        acquire_cron_lock=_acquire_cron_lock,
        clear_cron_running_flag=_clear_cron_running_flag,
        release_cron_lock=_release_cron_lock,
        check_accuracy_halt=_check_accuracy_halt,
        check_graduation_gate=_check_graduation_gate,
    )


def cmd_cron(
    client: "KalshiClient",
    min_edge: float | None = None,
    sameday_only: bool = False,
) -> None:
    """Wrapper that builds CronContext from the current namespace and delegates to cron.cmd_cron.

    Keeping this wrapper in main.py means call sites and integration tests
    continue to call ``main.cmd_cron(client)`` unchanged.  Test patches on
    ``main.get_weather_markets``, ``main._auto_place_trades`` etc. are picked
    up at call-time because ``_build_cron_context()`` reads the current
    module-level names (which monkeypatch has already replaced).

    ``sameday_only``: see trade_cycle.run_trade_cycle()'s own docstring.
    Only the CLI ``cron --sameday-only`` dispatch below sets this True --
    every other caller (loop, the interactive menu's "Cron" option) keeps
    the default full scan.
    """
    _called_from_loop = getattr(cmd_cron, "_called_from_loop", False)

    # When run manually (not from the loop), offer a one-shot override if the
    # kill switch is active so the user doesn't have to delete the file just to
    # run one cycle.  The loop is non-interactive so it silently skips instead.
    # Use _cron_module.KILL_SWITCH_PATH so test monkeypatches on cron.KILL_SWITCH_PATH
    # are picked up here (hardcoding the path would bypass test isolation).
    _kill_path = _cron_module.KILL_SWITCH_PATH

    # If a previous override run was hard-killed by the cron watchdog (os._exit
    # bypasses finally blocks), .kill_switch.tmp may have been left behind without
    # being renamed back.  Restore it now so the kill switch is never silently lost.
    #
    # M-27: derived from _kill_path.name (not a hardcoded ".kill_switch.tmp"
    # literal) so this can't silently desync from cmd_resume's own derivation
    # (main.py's cmd_resume) if KILL_SWITCH_PATH's filename ever changes.
    _kill_stale_tmp = _kill_path.with_name(_kill_path.name + ".tmp")
    # M-27: this self-heal used to run unconditionally at the top of every
    # cmd_cron call, before the cron lock is acquired (deep inside cron.py's
    # _cmd_cron_body). Without a guard, a scheduled `loop` cycle firing while
    # an operator's manually-answered override is running (which holds the
    # lock and has its OWN .kill_switch moved aside as this same .tmp file)
    # would "restore" the switch mid-override -- halting the authorized
    # override, firing a duplicate kill-switch alert, and leaving the
    # override's own finally block believing nothing happened (its .tmp is
    # gone by the time it checks). _is_cron_running() is the existing
    # read-only lock check (cron.py, already used by web_app.py and the EMOS
    # activate/deactivate guards above) -- skip the self-heal entirely while
    # a live process holds the lock; a genuinely orphaned .tmp (the crashed-
    # watchdog case this exists for) has no live lock holder and is
    # unaffected. Opus review (L-B): only computed when a .tmp actually
    # exists (the overwhelmingly common case is that it doesn't) -- avoids a
    # lock-file read + psutil.pid_exists() + Process.create_time() on every
    # single cmd_cron call for nothing.
    # Opus review (L-C): this narrows the race window from minutes (the old
    # code's window spanned the interactive override prompt plus the whole
    # cron cycle) to milliseconds -- the override's own move-aside
    # (`_kill_path` -> `_kill_stale_tmp`, below) happens before the lock is
    # acquired inside _cron_cmd_cron(), and the lock is released before the
    # override's finally block restores the switch. A scheduled cron firing
    # in either of those specific windows can still race this self-heal.
    # Fail-closed direction (restoring the switch, not losing it) means the
    # residual window is a false-positive halt, not a missed one -- accepted
    # as a real but low-consequence gap rather than a full redesign (e.g. a
    # marker file written around the move-aside itself, independent of lock
    # state) that this fix's scope doesn't require.
    if _kill_stale_tmp.exists():
        _skip_tmp_self_heal = False
        try:
            _skip_tmp_self_heal = _cron_module._is_cron_running()
        except Exception:
            # Round-2 opus review (M2-12): leaving _skip_tmp_self_heal False
            # here means the self-heal PROCEEDS (restores the kill switch)
            # -- the safe/restrictive direction, i.e. fail CLOSED, not fail
            # open. _is_cron_running()'s own default (used correctly by the
            # other _is_cron_running() call sites in this file, which gate
            # whether an action is BLOCKED) is fail-open in ITS context;
            # this guard inverts that relationship since it gates whether a
            # restore happens, not whether one is refused.
            pass
    else:
        _skip_tmp_self_heal = True  # nothing to restore either way
    if _kill_stale_tmp.exists() and not _skip_tmp_self_heal:
        if not _kill_path.exists():
            try:
                import safe_io as _safe_io

                _safe_io._replace_with_retry(str(_kill_stale_tmp), _kill_path)
                import logging as _logging

                _logging.getLogger(__name__).warning(
                    "cmd_cron: restored kill switch from stale .kill_switch.tmp "
                    "(prior override run was hard-killed by the watchdog)"
                )
            except Exception as _restore_exc:
                import logging as _logging

                _logging.getLogger(__name__).error(
                    "cmd_cron: could not restore .kill_switch from .kill_switch.tmp: %s",
                    _restore_exc,
                )
        else:
            # .kill_switch already exists too (e.g. a black-swan check
            # re-created it after the watchdog hard-killed a prior override
            # run, before the rename-back at the bottom of this function
            # could happen) -- the orphaned .tmp would otherwise sit forever
            # and make the next override's move-aside step below raise
            # FileExistsError under plain Path.rename() semantics. Discard
            # it; .kill_switch already being present means the halt is
            # already enforced regardless of what the stale .tmp contained.
            try:
                _kill_stale_tmp.unlink()
                import logging as _logging

                _logging.getLogger(__name__).warning(
                    "cmd_cron: discarded orphaned .kill_switch.tmp "
                    "(.kill_switch already present -- halt already enforced)"
                )
            except Exception as _cleanup_exc:
                import logging as _logging

                _logging.getLogger(__name__).error(
                    "cmd_cron: could not remove orphaned .kill_switch.tmp: %s",
                    _cleanup_exc,
                )
    if _kill_path.exists() and not _called_from_loop:
        _bs_path = BLACK_SWAN_PATH
        _reason_str = ""
        if _bs_path.exists():
            try:
                _bs_data = json.loads(_bs_path.read_text(encoding="utf-8"))
                _reason_str = f"\n  Reason: {_bs_data.get('reason', 'unknown')}"
            except Exception:
                pass
        print(red(f"\n  ⚠  Kill switch active — trading halted.{_reason_str}"))
        print(dim("  Delete data/.kill_switch to permanently resume."))
        # batch-24 item 1 (adjacency finding, opus-review-flagged during
        # testing): this is a SEPARATE kill-switch check from cron.py's own
        # _cmd_cron_body one -- reached only when NOT called from `loop`
        # mode, i.e. exactly the manual `py main.py cron` path this
        # project's real usage runs today. If input() below raises (no
        # attached stdin -- a scripted/headless invocation of this same
        # manual command) this function returns immediately below with
        # nothing beyond the two print()s above, which a non-interactive
        # caller never sees. Fired here, before the prompt, so it covers
        # that silent-return path unconditionally -- same cooldown_key as
        # cron.py's/trade_cycle.py's kill-switch alerts (same real-world
        # event); this code path can't have reached theirs yet since the
        # kill switch hasn't been moved aside and cron.cmd_cron() hasn't
        # been called at this point.
        from notify import send_system_alert as _ks_alert

        # opus-review-caught (F14): _reason_str is formatted for the
        # terminal print above ("\n  Reason: X"), which reads badly inlined
        # into a push-notification body ("...present.\n  Reason: X Remove
        # the file..." -- a literal newline mid-sentence, no space before
        # "Remove"). Collapse it to plain text for the notification body
        # instead of re-deriving from _bs_data (which may be unset if the
        # json.loads above raised).
        #
        # opus-review-caught (2nd round, LOW-4): the original collapse only
        # stripped the LEADING "\n  " -- a reason value with any OTHER
        # embedded newline (reachable: activate_black_swan_halt() builds
        # its own reason from `str(exc)`, which can be multi-line) still
        # broke the single-sentence body, and a reason already ending in
        # "." doubled it. `" ".join(...split())` collapses every whitespace
        # run (any number/kind of embedded newlines or repeated spaces)
        # into single spaces regardless of shape, and `.rstrip(".")` before
        # appending "." avoids a doubled trailing period.
        _reason_plain = (
            " " + " ".join(_reason_str.split()).rstrip(".") + "." if _reason_str else ""
        )
        _ks_alert(
            "Kalshi kill switch engaged",
            f"py main.py cron found data/.kill_switch present.{_reason_plain}"
            " Remove the file to resume trading.",
            cooldown_key="kill_switch",
        )
        try:
            _ans = (
                input(yellow("  Override and run this cycle anyway? (y/N): "))
                .strip()
                .lower()
            )
        except (EOFError, KeyboardInterrupt, OSError):
            # OSError is raised by pytest's stdin capture; EOFError by piped/headless runs.
            print()
            return
        if _ans != "y":
            return
        # Temporarily move the kill switch so cron's internal check doesn't
        # double-fire.  Restored in the finally block — override is one-shot.
        # safe_io._replace_with_retry (not Path.rename, and not a bare
        # replace call -- those are banned outside safe_io.py by
        # tests/test_bare_os_replace_guard.py) so this can't raise
        # FileExistsError if an orphaned .kill_switch.tmp somehow still
        # exists (AUD-0039), and gets the same transient-PermissionError
        # retry every other Windows file-replace in this codebase gets --
        # aborts the override cleanly instead of an uncaught traceback if
        # the move fails for any other reason.
        _kill_tmp = _kill_path.with_name(_kill_path.name + ".tmp")
        try:
            import safe_io as _safe_io

            _safe_io._replace_with_retry(str(_kill_path), _kill_tmp)
        except OSError as _move_exc:
            print(
                red(
                    f"  Could not start override — moving kill switch aside "
                    f"failed: {_move_exc}"
                )
            )
            return
        print(
            yellow(
                "  [override] Running one cycle — kill switch will be restored after.\n"
            )
        )
        try:
            _cron_cmd_cron._called_from_loop = False  # type: ignore[attr-defined]
            _cron_module.USER_OVERRIDE_ACTIVE = True
            _paper_module.KILL_SWITCH_OVERRIDE_ACTIVE = True
            _cron_cmd_cron(
                _build_cron_context(),
                client,
                min_edge=min_edge,
                sameday_only=sameday_only,
            )
        finally:
            _cron_module.USER_OVERRIDE_ACTIVE = False
            _paper_module.KILL_SWITCH_OVERRIDE_ACTIVE = False
            # Opus review (AUD-0039 followup): this restore step used to be
            # completely unguarded inside a finally -- an OSError here (e.g.
            # a transient Windows sharing violation, or another process
            # touching .kill_switch.tmp between the exists() check and the
            # action below) would replace any in-flight exception from the
            # cron cycle and escape as an uncaught traceback, skipping the
            # "restored" confirmation. Now caught and logged instead.
            if _kill_tmp.exists():
                try:
                    if _kill_path.exists():
                        # black swan re-created it during the run -- keep
                        # the fresh copy (it may carry a newer reason than
                        # the stale .tmp), discard the temp.
                        _kill_tmp.unlink(missing_ok=True)
                    else:
                        import safe_io as _safe_io

                        _safe_io._replace_with_retry(str(_kill_tmp), _kill_path)
                except OSError as _restore_exc:
                    import logging as _logging

                    _logging.getLogger(__name__).error(
                        "cmd_cron: could not restore kill switch after override: %s",
                        _restore_exc,
                    )
            print(
                yellow("  [override] Kill switch restored — still active for next run.")
            )
        return

    # Normal (non-override) path: propagate _called_from_loop flag so cron's
    # loop-mode sys.exit guard works.
    _cron_cmd_cron._called_from_loop = _called_from_loop  # type: ignore[attr-defined]
    _cron_cmd_cron(
        _build_cron_context(), client, min_edge=min_edge, sameday_only=sameday_only
    )


def _brier_sparkline() -> str:
    """
    Return a sparkline string showing weekly Brier trend, e.g. "▅▄▃▂▂▁"
    Uses Unicode block chars ▁▂▃▄▅▆▇█ (lower = better Brier score, i.e. lower bar = better).
    Returns empty string if insufficient data.
    """
    try:
        trend = get_calibration_trend(weeks=8)
        if len(trend) < 2:
            return ""
        blocks = "▁▂▃▄▅▆▇█"
        scores = [t["brier"] for t in trend]
        min_s = 0.0
        max_s = 0.25  # random = 0.25
        span = max_s - min_s
        result = ""
        for s in scores:
            # Map brier 0.0=▁ (good) to 0.25=█ (bad)
            normalized = max(0.0, min(1.0, (s - min_s) / span))
            idx = int(normalized * (len(blocks) - 1))
            result += blocks[idx]
        return result
    except Exception:
        return ""


def _ascii_chart(
    values: list[float], width: int = 50, height: int = 8, label: str = ""
) -> str:
    """
    Render a simple ASCII line chart. Returns a multi-line string.
    Uses block characters █ for filled areas.
    Shows min/max labels on Y axis.
    If all values are the same (flat line), shows a flat line without crashing.
    """
    if not values:
        return ""
    min_v = min(values)
    max_v = max(values)
    span = max_v - min_v

    # Downsample or upsample to fit width columns
    n = len(values)
    cols: list[float] = []
    for col in range(width):
        idx = int(col / width * n)
        idx = min(idx, n - 1)
        cols.append(values[idx])

    # Build the grid row by row (top = high value)
    lines: list[str] = []
    mid_row = (height + 1) // 2
    for row in range(height, 0, -1):
        if span == 0:
            # Flat series — draw a single horizontal line at mid-height.
            # The old span=1.0 substitution made every row's threshold
            # exceed every value, so a flat series rendered as a fully
            # blank grid despite the docstring's claim of "a flat line".
            row_str = ("█" if row == mid_row else " ") * len(cols)
        else:
            # (row - 1), not row, so the bottom row's threshold equals
            # min_v exactly — previously it was min_v + span/height,
            # which meant the series minimum was never drawn on any
            # chart (flat or not).
            threshold = min_v + ((row - 1) / height) * span
            row_str = "".join("█" if val >= threshold else " " for val in cols)
        # Y axis label on leftmost row and bottom row
        if row == height:
            label_str = f"${max_v:.0f} "
        elif row == 1:
            label_str = f"${min_v:.0f} "
        else:
            label_str = "       " if max_v >= 1000 else "      "
        lines.append(label_str + "│" + row_str)

    bottom = "       └" + "─" * width
    lines.append(bottom)
    if label:
        lines.append(f"  {label}")
    return "\n".join(lines)


def _load_watch_state() -> set:
    """Load the set of previously-seen tickers from disk (survives restarts)."""
    try:
        if _WATCH_STATE_PATH.exists():
            data = json.loads(_WATCH_STATE_PATH.read_text())
            return set(data.get("tickers", []))
    except Exception as exc:
        _log.debug("_load_watch_state: could not read %s: %s", _WATCH_STATE_PATH, exc)
    return set()


def _save_watch_state(tickers: set) -> None:
    """Persist the set of seen tickers so the next run knows what's new."""
    try:
        _WATCH_STATE_PATH.parent.mkdir(exist_ok=True)
        _WATCH_STATE_PATH.write_text(json.dumps({"tickers": list(tickers)}))
    except Exception as exc:
        _log.warning("_save_watch_state: failed to persist watch state: %s", exc)


KALSHI_ENV = os.getenv("KALSHI_ENV", "demo")


def _target_date_due(target_date_str: str | None, city: str | None) -> bool:
    """Return True if target_date_str is on or before city's local today.

    Parses both sides as real dates rather than comparing raw strings -- a
    non-day-granular ISO value (Bug A, backlog.txt "RAIN / SNOW / HURRICANE
    MARKETS" Step 2) would otherwise compare as a string prefix and could
    sort incorrectly against a full "YYYY-MM-DD" value. Falls back to the
    string compare on any unparseable value, matching this codebase's prior
    behavior at both call sites (cmd_watch_settle's _pending(), the
    main-menu "due today" banner).

    target_date_str is CITY-LOCAL (weather_markets.py's analyze_trade
    return dict stores target_date.isoformat() from parse_city_date()), so
    "today" here must be too -- mirrors _feature_importance_days_out's own
    local-today fix rather than utils.utc_today(), which was wrong for the
    ~4-8h evening window where UTC's calendar date has already rolled over
    but the city's has not. This was the one target_date comparison site
    the 0100bffe/6364b38b fix sweep missed (AUD-0017).
    """
    if not target_date_str:
        return False
    from datetime import date as _date_due

    try:
        from zoneinfo import ZoneInfo as _ZoneInfoDue

        today_date = datetime.now(
            _ZoneInfoDue(_CITY_TZ.get(city or "", "America/New_York"))
        ).date()
    except Exception:
        _log.warning(
            "_target_date_due: ZoneInfo unavailable for city=%s — "
            "falling back to UTC date",
            city,
        )
        today_date = datetime.now(UTC).date()

    try:
        return _date_due.fromisoformat(target_date_str) <= today_date
    except (ValueError, TypeError):
        return target_date_str <= today_date.isoformat()


def _kalshi_env() -> str:
    """Read KALSHI_ENV fresh from the environment each call (survives cmd_settings reload)."""
    return os.getenv("KALSHI_ENV", "demo")


def _market_base_url() -> str:
    """Return the correct Kalshi base URL based on the current env setting."""
    return "https://kalshi.com" if _kalshi_env() == "prod" else "https://demo.kalshi.co"


def _compute_live_orders_possible(cmd: str, args: list) -> bool:
    """True if this CLI invocation's command can reach a real live order --
    either opening new exposure or placing a protective SELL on an existing
    live position. Used only for the startup banner's informational message
    -- the actual safety enforcement is trading_gates.LiveTradingGate.check()
    itself, which this function has no bearing on.

    Every code path below was traced to its own `client.base_url != DEMO_BASE`
    + live-gate call (directly, or via cron.py's own `if client is not None:`
    live-position-protection block) -- opus review of AUD-0014/AUD-0031's
    original fix caught that the first version of this function only covered
    `buy`/`sell`/`analyze`, missing 4 more real paths (HIGH-1/2/3, 2026-08-20
    review). This list is a hand-maintained mirror, not derived from the gate
    itself -- if a new pre_live_trade_check OR pre_live_exit_check call site
    is added anywhere in main.py/cron.py/order_executor.py, this function
    needs a matching update. See TestLiveOrderPathsGuard in
    tests/test_phase2_batch_l.py for a regression guard on that drift.

    Batch-58 item 4 note: the path list below is unchanged by the gate split
    -- the protective-exit path still exists under `cron`/`loop`/
    `watch --live`, it just consults trading_gates.pre_live_exit_check (the
    reduced gate) rather than pre_live_trade_check now.

    Known live-capable paths (opens new exposure unless noted):
      - `watch --live` (with or without `--auto`) -- live=True unlocks
        cmd_watch's `if live:` block (order poll/reprice/protective exits;
        `--auto` additionally enables new-position auto-trading)
      - `buy`/`sell` (cmd_order)
      - `analyze` (cmd_analyze's interactive quick-buy prompt, _quick_paper_buy)
      - `menu` / no-args (the interactive menu's "Analyze" option reaches the
        exact same cmd_analyze -> _quick_paper_buy path as above)
      - `cron` / `loop` (loop dispatches to cron) -- SELL-only: protects an
        already-open live position via _check_live_position_exits/
        _check_live_model_exits, never opens new exposure (see
        LIVE_TRADING_RUNBOOK.md Part 1.7/Part 2 for the opens-vs-protects
        distinction)
    """
    return (cmd == "watch" and "--live" in args) or cmd in (
        "buy",
        "sell",
        "analyze",
        "menu",
        "",
        "cron",
        "loop",
    )


# L-12: MARKET_BASE_URL is dead — nothing reads it; _market_base_url() is used instead.
# Kept here to avoid breaking any external scripts that might import it.
MARKET_BASE_URL = (
    "https://kalshi.com" if KALSHI_ENV == "prod" else "https://demo.kalshi.co"
)


def _header(title: str, width: int = 50) -> None:
    """Print a styled section header."""
    bar = "─" * width
    print(f"\n{bold(f'┌{bar}┐')}")
    padded = title.center(width)
    print(bold(f"│{padded}│"))
    print(f"{bold(f'└{bar}┘')}\n")


def _kv(label: str, value: str) -> None:
    """Print a key-value pair with consistent 10-char label column."""
    print(f"  {label:<10}{value}")


def _format_expiry(close_time: str) -> str:
    """Format time remaining until market close: '2h 15m', '3d 4h', red if <2h."""
    if not close_time:
        return "—"
    try:
        dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
        delta = dt - datetime.now(UTC)
        secs = int(delta.total_seconds())
        if secs < 0:
            return dim("closed")
        hours, rem = divmod(secs, 3600)
        mins = rem // 60
        if hours < 2:
            return red(f"{hours}h {mins}m")
        elif hours < 6:
            return yellow(f"{hours}h {mins}m")
        elif hours < 24:
            return f"{hours}h {mins}m"
        else:
            days = hours // 24
            return f"{days}d {hours % 24}h"
    except Exception:
        return "—"


# ── Startup checks ────────────────────────────────────────────────────────────


def validate_env() -> bool:
    """
    Check that required .env variables are set before doing anything.
    Prints a helpful setup message and returns False if not.
    """
    key_id = os.getenv("KALSHI_KEY_ID")
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")

    missing = []
    if not key_id:
        missing.append("KALSHI_KEY_ID")
    if not key_path:
        missing.append("KALSHI_PRIVATE_KEY_PATH")

    if missing:
        print(red("\n  Missing environment variables: " + ", ".join(missing)))
        print(
            dim("  Copy .env.example to .env and fill in your Kalshi API credentials.")
        )
        print(dim("  Get your keys at: kalshi.com → Account → API Keys\n"))
        return False

    if key_path and not Path(key_path).exists():
        print(red(f"\n  Private key file not found: {key_path}"))
        print(dim("  Check KALSHI_PRIVATE_KEY_PATH in your .env file.\n"))
        return False

    env_val = os.getenv("KALSHI_ENV", "demo")
    if env_val not in ("demo", "prod"):
        print(red(f"\n  KALSHI_ENV must be 'demo' or 'prod', got: {env_val!r}"))
        print(
            dim(
                "  A typo here (e.g. 'production') silently points the client at the wrong URL.\n"
            )
        )
        return False

    return True


def validate_api_key(client: KalshiClient) -> bool:
    """
    Make a lightweight authenticated request to confirm credentials work.
    Returns True if valid, prints an error and returns False if not.
    """
    try:
        client.get_balance()
        print(green("  ✓ API credentials valid\n"))
        return True
    except Exception as e:
        msg = str(e)
        if "401" in msg or "403" in msg or "Unauthorized" in msg:
            print(red("  ✗ API credentials rejected by Kalshi."))
            print(
                dim("  Check your KALSHI_KEY_ID and KALSHI_PRIVATE_KEY_PATH in .env\n")
            )
        else:
            print(yellow(f"  ⚠ Could not verify credentials: {e}"))
            print(dim("  Continuing anyway — may fail on authenticated endpoints.\n"))
            # Message says "continuing anyway" — return value must match, or
            # the sole caller (cmd_balance) silently aborts on a transient
            # network error while telling the user it's proceeding.
            return True
        return False


# P0-15: files that must never be deleted by cleanup — they are updated only when
# explicit calibration commands run, not on every cron cycle.
_PERMANENT_DATA_FILES = {
    "paper_trades.json",
    "seasonal_weights.json",
    "city_weights.json",
    "condition_weights.json",
    "walk_forward_params.json",
    "platt_models.json",
    "live_config.json",
    "retired_strategies.json",
    "member_quarantine.json",
    "learned_weights.json",
    "learned_correlations.json",
    "temperature_scale.json",
    "emos_params.json",
    "correlations.json",
    "metar_lockout_calibration.json",
    # M-19: written only on failure (the AUD-0026 phantom-live-position
    # sentinel), so its mtime never refreshes on success and it would
    # otherwise be deleted after 2 days while the dangerous DB row it warns
    # about survives.
    "execution_log_unsettled_exit_rows.json",
    # M-19: multi-week rain-arb graduation history -- any >=2-day cron pause
    # followed by one CLI invocation would delete it, losing the whole trend.
    "rain_arb_shadow_observations.json",
    # batch-56: same reasoning as the rain-arb file above -- a multi-week
    # blend-vs-single-station accuracy history whose whole purpose is the
    # eventual graduation decision. A 2-day cron pause must not silently
    # reset the sample count back to zero.
    "nearby_station_shadow.json",
}


def cleanup_data_dir() -> None:
    """
    Delete stale cached data files to prevent unbounded growth.
    Skips climate_*.json (1-year TTL managed by climatology.py),
    dot-files, and permanent calibration weight files (_PERMANENT_DATA_FILES).
    Only deletes files older than 2 days to avoid removing files still
    useful for markets that cross midnight.
    """
    import time as _time

    data_dir = DATA_DIR
    if not data_dir.exists():
        return
    cutoff = _time.time() - 2 * 24 * 3600  # 2 days ago
    for f in data_dir.glob("*.json"):
        if f.name.startswith("climate_") or f.name.startswith("."):
            continue
        if f.name in _PERMANENT_DATA_FILES:
            continue
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def auto_settle(client: KalshiClient) -> None:
    """
    Silently sync settled market outcomes in a background thread.
    Runs on every startup so calibration data stays fresh automatically.
    Prints a summary only if new outcomes were found.
    """
    import threading

    def _run():
        try:
            count = sync_outcomes(client)
            if count > 0:
                from paper import auto_settle_paper_trades

                paper_settled = auto_settle_paper_trades(client)
                msg = green(
                    f"\n  [Auto-settle] Recorded {count} new outcome(s). "
                ) + dim("Brier score updated.")
                if paper_settled:
                    msg += dim(
                        f"  {paper_settled} paper trade(s) settled automatically."
                    )
                print(msg + "\n")
        except Exception as exc:
            _log.warning("auto_settle background thread failed: %s", exc)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def auto_backtest(client: KalshiClient) -> None:
    """
    Run a quick 7-day backtest silently in a background thread on startup.
    If recent Brier score has degraded by >0.05 vs. all-time Brier, print a warning.
    Stores result in data/.last_backtest.json for the brief/dashboard to read.
    """
    import threading

    def _run():
        try:
            from backtest import run_backtest

            summary = run_backtest(client, days_back=7, verbose=False)
            result_path = LAST_BACKTEST_PATH
            try:
                result_path.parent.mkdir(exist_ok=True)
                result_path.write_text(json.dumps(summary, default=str))
            except Exception:
                pass

            # Compare recent (7-day) Brier vs all-time
            recent_brier = summary.get("train_brier")
            all_time_brier = brier_score()
            if (
                recent_brier is not None
                and all_time_brier is not None
                and recent_brier > all_time_brier + 0.05
            ):
                print(
                    yellow(
                        f"\n  [Auto-backtest] WARNING: recent Brier {recent_brier:.4f} "
                        f"vs all-time {all_time_brier:.4f} — model may have degraded.\n"
                    )
                )
            # Overfitting guard: compare in-sample (train) vs out-of-sample (val) Brier
            val_brier = summary.get("val_brier")
            train_brier = summary.get("train_brier")
            if train_brier is not None and val_brier is not None:
                try:
                    from backtest import check_overfitting

                    ov = check_overfitting(train_brier, val_brier)
                    if ov["status"] in ("overfit", "severe", "warning"):
                        print(
                            yellow(
                                f"\n  [Auto-backtest] Overfitting check: {ov['status'].upper()} "
                                f"(in={train_brier:.4f} out={val_brier:.4f} "
                                f"degradation={ov['degradation']:+.4f})\n"
                                f"  {ov['recommendation']}\n"
                            )
                        )
                except Exception:
                    pass
        except Exception as exc:
            _log.warning("auto_backtest background thread failed: %s", exc)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def auto_backup() -> None:
    """
    Copy predictions.db, execution_log.db, and paper_trades.json to
    data/backups/ on startup.
    #103: Keeps the last 30 daily backups (was 7) for better point-in-time recovery.
    #101: Also cleans up stray temp files left by interrupted atomic writes.
    AUD batch-25: execution_log.db (the live-order/daily-loss ledger) had no
    local backup at all until now -- only predictions.db and
    paper_trades.json were ever covered here. The WAL-safe .db copy
    (opus-review-caught, once per day per file since it only runs when
    today's backup doesn't exist yet) is measurably slower than the old
    shutil.copy2 -- ~0.5s for a 51MB predictions.db on local disk, up from
    ~0.02s -- but still small next to startup's other work.
    Runs silently — never blocks startup.
    """
    import shutil

    from execution_log import DB_PATH as EXECUTION_LOG_DB_PATH
    from paths import PAPER_TRADES_PATH
    from safe_io import backup_sqlite_db
    from tracker import DB_PATH
    from utils import utc_today as _utc_today

    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    today = _utc_today().isoformat()
    files = [
        DB_PATH,
        EXECUTION_LOG_DB_PATH,
        PAPER_TRADES_PATH,
    ]
    for src in files:
        if not src.exists():
            continue
        dst = backup_dir / f"{src.stem}_{today}{src.suffix}"
        if not dst.exists():  # only once per day
            try:
                if src.suffix == ".db":
                    # WAL-safe: shutil.copy2 on the raw .db file silently
                    # omits anything committed but not yet checkpointed out
                    # of the .db-wal sidecar -- both DBs backed up here run
                    # PRAGMA journal_mode=WAL (AUD batch-25 item 1/3).
                    copy_ok = backup_sqlite_db(src, dst)
                    if not copy_ok:
                        _log.error(
                            "auto_backup: backup copy of %s failed its "
                            "post-copy readability check -- not retained",
                            src.name,
                        )
                        continue
                    # #104: Verify backup integrity after writing. Was
                    # called but its return value discarded -- a backup
                    # that failed its own verification still got retained
                    # and still counted toward the 30-backup pruning
                    # window, potentially evicting the oldest genuinely-
                    # good backup in its place (AUD batch-25 item 3).
                    table = "orders" if src.stem == "execution_log" else "predictions"
                    n = verify_db_backup(dst, table=table)
                    # opus-review-round-2 M4: verify_db_backup returns -1
                    # specifically for a hard failure (almost always "no
                    # such table"), distinct from a genuine 0-row count --
                    # a legitimately empty table (e.g. execution_log.db's
                    # orders table before this bot's first live order) is
                    # NOT a bad backup and must not be deleted.
                    if n < 0:
                        _log.error(
                            "auto_backup: backup verification failed for %s "
                            "(query against %s table failed) -- deleting "
                            "bad copy",
                            dst,
                            table,
                        )
                        try:
                            dst.unlink()
                        except Exception:
                            pass
                else:
                    shutil.copy2(src, dst)
                    # #104: Verify backup integrity after writing
                    try:
                        from paper import cloud_backup, verify_backup

                        verify_backup(dst)
                        cloud_backup(dst)  # #105: optional S3 upload
                    except Exception:
                        pass
            except Exception as exc:
                # AUD batch-25 opus-review M4: was a bare `pass` -- silent
                # even at DEBUG level. backup_sqlite_db can raise (source
                # isn't a valid SQLite DB, disk full, destination locked)
                # in a way shutil.copy2 essentially never did for these
                # files, so this is a NEW failure mode this batch
                # introduced; leaving it silent would mean the exact "old
                # code silently returns success on a bad backup" problem
                # this batch exists to fix reappearing one layer up, with
                # zero trace anywhere.
                _log.error("auto_backup: failed to back up %s: %s", src.name, exc)
    # #103: Prune — keep only the 30 most recent backups per file stem
    for stem in ("predictions", "execution_log", "paper_trades"):
        backups = sorted(backup_dir.glob(f"{stem}_*"))
        for old in backups[:-30]:
            try:
                old.unlink()
            except Exception:
                pass

    # #101: Clean up stray atomic-write temp files
    try:
        from paper import cleanup_temp_files

        cleanup_temp_files()
    except Exception:
        pass


_log = logging.getLogger(__name__)


def verify_db_backup(path, table: str = "predictions") -> int:
    """Re-open a backed-up SQLite DB, count rows in `table`. Logs result (#104).

    `table` defaults to "predictions" (predictions.db). Pass table="orders"
    for an execution_log.db backup (AUD batch-25 item 2) -- its ledger
    lives in a table of that name, not "predictions".

    Returns the real row count (0 is a valid, successful answer -- a
    freshly-reset or never-yet-populated table, e.g. execution_log.db's
    `orders` table before this bot's first live order, is not a failure)
    or -1 if the query itself failed (almost always "no such table",
    which is what a still-uncheckpointed or otherwise genuinely bad copy
    produces) -- opus-review-round-2 M4: an earlier version returned 0 for
    BOTH cases, and auto_backup()'s own "0 means bad, delete it" check
    (right below this function) couldn't tell them apart. Confirmed live
    against the real data/execution_log.db (`orders`=243 rows, but
    `daily_live_loss`=0 rows -- a table that's legitimately empty right
    now): treating any 0 as failure would have deleted a perfectly good
    backup of exactly the file this batch exists to protect, the moment
    that table's row count happened to be zero.

    AUD batch-25 item 3 adjacency fix: `con` used to only get closed on
    the success path -- a query failure (e.g. "no such table", exactly
    what a still-uncheckpointed or otherwise bad copy produces) left the
    connection open. Harmless before this batch (nothing needed the file
    handle released afterward), but auto_backup()'s new "verification
    failed -> delete the bad copy" step (right below this function) now
    depends on it: on Windows, an open sqlite3.Connection to a file blocks
    deleting that file, so the leaked handle silently defeated the very
    delete this batch adds, via that caller's own `except Exception: pass`
    around the unlink -- confirmed live (WinError 32) before adding the
    try/finally below.

    `table` is interpolated directly into the query (sqlite3 has no
    parameter-binding for identifiers, only values) -- opus-review-caught
    (L11): both real call sites pass a literal today, but this is public
    API taking an arbitrary string, so validate against the known set
    rather than trusting every future caller to only ever pass a literal.
    """
    import sqlite3

    path = Path(path)
    if table not in ("predictions", "orders"):
        raise ValueError(f"verify_db_backup: unsupported table {table!r}")
    con = None
    try:
        con = sqlite3.connect(str(path))
        row = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
        n = row[0] if row else 0
        _log.info("backup verified: %s, %d rows", path, n)
        return n
    except Exception as exc:
        _log.warning("backup verification failed for %s: %s", path, exc)
        return -1
    finally:
        if con is not None:
            con.close()


def cmd_settle(client: KalshiClient) -> None:
    """
    Sync settled market outcomes from Kalshi and record them in the tracker.
    Intended for scheduled nightly execution (via schtasks) as well as manual use.
    """
    from paper import auto_settle_paper_trades

    count = sync_outcomes(client)
    paper = auto_settle_paper_trades(client)
    paper_count = len(paper)
    total = count + paper_count
    if total > 0:
        parts = []
        if count:
            parts.append(f"{count} outcome(s) recorded")
        if paper_count:
            parts.append(f"{paper_count} paper trade(s) settled")
        print(green(f"  [Settle] {', '.join(parts)}."))
    else:
        print(dim("  [Settle] No new outcomes to record."))


def cmd_settlement_monitor(client: KalshiClient, args: list[str] | None = None) -> None:
    """Run METAR settlement lag monitor (polls from 5-7 PM local time)."""
    from settlement_monitor import run_settlement_monitor

    duration = 120
    if args:
        try:
            duration = int(args[0])
        except ValueError:
            pass

    _log.info("Starting settlement monitor for %d minutes...", duration)
    run_settlement_monitor(client, duration_minutes=duration)


def cmd_watch_settle(client: KalshiClient, args: list[str] | None = None) -> None:
    """
    Poll every N minutes until all same-day (and past) open trades are settled.
    Usage: py main.py watch-settle [interval_minutes=5]
    Exits automatically when nothing remains to settle.
    """
    import time as _time

    from paper import auto_settle_paper_trades, get_open_trades

    interval = 5
    if args:
        try:
            interval = max(1, int(args[0]))
        except ValueError:
            pass

    def _pending() -> list:
        return [
            t
            for t in get_open_trades()
            if _target_date_due(t.get("target_date"), t.get("city"))
        ]

    print(
        green(
            f"[watch-settle] Watching for same-day settlements (every {interval}m). Ctrl-C to stop."
        )
    )

    while True:
        # Opus-review-noted (AUD-0017, batch-07): this can now exit here on
        # the very first check without ever calling sync_outcomes/
        # auto_settle_paper_trades, whereas the old UTC-anchored _pending()
        # always read evening-window trades as due and guaranteed at least
        # one settle pass. This is intentional, not a regression: a
        # city-local target_date genuinely cannot have settled before its
        # own local day ends, so "nothing pending" here means there is
        # nothing to settle yet, not that a pass was skipped.
        due = _pending()
        if not due:
            print(green("[watch-settle] All due trades settled. Done."))
            break

        tickers = ", ".join(t["ticker"] for t in due)
        print(dim(f"[watch-settle] {len(due)} unsettled: {tickers}"))

        sync_outcomes(client)
        settled = auto_settle_paper_trades(client)
        if settled:
            print(green(f"[watch-settle] Settled {len(settled)} trade(s)."))

        remaining = _pending()
        if not remaining:
            print(green("[watch-settle] All due trades settled. Done."))
            break

        print(
            dim(
                f"[watch-settle] {len(remaining)} still pending — next check in {interval}m…"
            )
        )
        try:
            _time.sleep(interval * 60)
        except KeyboardInterrupt:
            print()
            break


def cmd_loop(client: KalshiClient, args: list[str] | None = None) -> None:
    """
    Self-scheduling run loop — run cron every N hours, auto-settle after 9 PM.
    Usage: py main.py loop [interval_hours=4]
    Leave this running in a terminal. Ctrl-C to stop.
    """
    import time as _time
    from datetime import datetime, timedelta

    from paper import auto_settle_paper_trades

    interval_h = 4
    if args:
        try:
            interval_h = max(1, int(args[0]))
        except ValueError:
            pass
    interval_s = interval_h * 3600

    _KILL_PATH = KILL_SWITCH_PATH

    # L-9: naive datetime.now() reads the HOST's local timezone -- correct
    # only by coincidence on an operator's own machine, and silently wrong
    # (both the displayed cycle timestamps and the "9 PM" auto-settle trigger
    # below) once the bot runs on a UTC-configured VM (the planned host move).
    # ZoneInfo("America/New_York") pins "9 PM" to what it's always meant --
    # Kalshi's own exchange-local time -- matching the rest of this file's
    # established `datetime.now(ZoneInfo(...))` convention (e.g. main.py's
    # _target_date_due/cmd_backtest/_days_out helpers), and correctly handles
    # DST transitions via real tz-aware arithmetic instead of the naive-local
    # subtraction this loop's own "H-10" comment already anticipates trouble
    # from.
    from zoneinfo import ZoneInfo as _LoopZoneInfo

    _LOOP_TZ = _LoopZoneInfo("America/New_York")

    def _now() -> datetime:
        return datetime.now(_LOOP_TZ)

    def _run_cycle(label: str) -> None:
        print(bold(f"\n[loop] ── {label} ── {_now().strftime('%Y-%m-%d %H:%M')} ──"))
        if _KILL_PATH.exists():
            print(
                red(
                    "  Kill switch active — skipping cycle."
                    " Run  py main.py cron  manually to override for one run."
                )
            )
            return
        try:
            cmd_cron._called_from_loop = True  # type: ignore[attr-defined]
            cmd_cron(client)
        except SystemExit as exc:
            # H-9: suppress sys.exit() calls inside cmd_cron — the loop must survive them.
            # SystemExit inherits from BaseException so `except Exception` does not catch it.
            _log.warning(
                "cmd_cron called sys.exit(%s) — suppressed to keep loop running",
                exc.code,
            )
        except Exception as exc:
            print(red(f"  Cron error: {exc}"))
        finally:
            cmd_cron._called_from_loop = False  # type: ignore[attr-defined]

        # Auto-settle if it's 9 PM or later
        if _now().hour >= 21:
            print(dim("  [loop] Post-9PM — running auto-settle…"))
            try:
                sync_outcomes(client)
                n = auto_settle_paper_trades(client)
                if n:
                    print(green(f"  [loop] Settled {n} trade(s)."))
                else:
                    print(dim("  [loop] No new settlements."))
            except Exception as exc:
                print(red(f"  [loop] Settle error: {exc}"))

    print(
        bold(
            f"\n[loop] Starting — cron every {interval_h}h, auto-settle after 9 PM. Ctrl-C to stop."
        )
    )

    # Opus review (L-H): `next_run = _now() + timedelta(...)` is wall-clock
    # arithmetic in America/New_York, so a cycle spanning a DST transition
    # fires up to an hour early (spring-forward) or late (fall-back), twice a
    # year -- strictly better than the pre-fix naive-local behavior (which had
    # the same DST issue AND was wrong about which timezone it was even in
    # after a UTC-host move) and low-consequence (an interval-timing loop, not
    # a safety gate), so left as a documented limitation rather than switching
    # to UTC-computed-then-locally-rendered arithmetic.
    # Run immediately on startup
    _run_cycle("startup run")
    next_run = _now() + timedelta(seconds=interval_s)

    try:
        while True:
            remaining = (next_run - _now()).total_seconds()
            if remaining <= 0:
                _run_cycle("scheduled run")
                next_run = _now() + timedelta(seconds=interval_s)
                remaining = interval_s

            # Show countdown, update every 60s
            h, m = divmod(int(remaining), 3600)
            m //= 60
            print(
                dim(
                    f"  [loop] Next run in {h}h {m}m  ({next_run.strftime('%H:%M')})  — Ctrl-C to stop"
                ),
                end="\r",
                flush=True,
            )
            # H-10: clamp to non-negative — DST changes and NTP syncs can make
            # remaining transiently negative, causing ValueError in time.sleep().
            _time.sleep(max(0.0, min(60.0, remaining)))

    except KeyboardInterrupt:
        print(f"\n{dim('[loop] Stopped.')}")


# ── Client ────────────────────────────────────────────────────────────────────


def build_client() -> KalshiClient:
    return KalshiClient(
        key_id=os.getenv("KALSHI_KEY_ID"),
        private_key_path=os.getenv("KALSHI_PRIVATE_KEY_PATH"),
        env=_kalshi_env(),
    )


# ── Markets list ──────────────────────────────────────────────────────────────


def cmd_markets(client: KalshiClient):
    _header("Open Weather Markets")
    markets = get_weather_markets(client)
    if not markets:
        print(yellow("  No weather markets found."))
        return

    rows = []
    for m in markets:
        prices = parse_market_price(m)
        enriched = enrich_with_forecast(m)
        analysis = analyze_trade(enriched)
        edge = analysis["edge"] if analysis else 0
        sig = analysis["signal"].strip() if analysis else "—"
        ticker = m.get("ticker", "")
        rows.append(
            [
                ticker,
                (m.get("title") or "")[:45],
                prob_color(prices["implied_prob"]),
                signal_color(f"{sig} ({edge:+.0%})") if analysis else dim("—"),
                # float() wrap: volume_fp is a FixedPointCount string
                # ("10.00") on the current live API, not a number -- was
                # displaying the raw string unconverted (cosmetic-only,
                # never crashed here since tabulate just str()s the cell).
                float(m.get("volume_fp") or m.get("volume", 0) or 0),
                cyan(f"{_market_base_url()}/markets/{ticker}"),
            ]
        )

    print(
        tabulate(
            rows,
            headers=["Ticker", "Title", "Mkt P", "Signal", "Vol", "Link"],
            tablefmt="rounded_outline",
        )
    )
    print(
        dim("\n  Tip: py main.py analyze   — shows only the strongest opportunities.")
    )


# ── Single market ─────────────────────────────────────────────────────────────


def _side_aware_entry_price(side: str, prices: dict) -> float:
    """Return the ask-side price to PAY for `side` ("YES"/"yes" or "NO"/
    "no"), for sizing a displayed contract count -- NOT prices["implied_prob"]
    (always the YES mid) unconditionally, which overcounts a NO
    recommendation's displayed contract count (batch-26 item 3: dividing by
    the YES price instead of the higher NO cost understates cost-per-
    contract, e.g. a ~2.4x overcount at a 0.30 YES mid). Falls back to the
    mid (or 1-mid for NO) when a real yes_bid/yes_ask quote isn't present.
    Mirrors weather_markets._price_and_size's own entry_price convention for
    the ask-side computation itself (opus-review-caught: an earlier draft
    gated the NO fallback on the coarser prices["has_quote"] -- true
    whenever yes_ask alone is nonzero -- instead of yes_bid specifically,
    which could return a degenerate 1.0 price when yes_bid is 0 but yes_ask
    isn't) -- NO entry is at no_ask = 1 - yes_bid specifically, not derived
    from whether *some* quote exists. The zero-price fallback differs
    slightly from _price_and_size's (a defensive 0.01 floor on the NO side
    here, vs. a bare 1-market_prob there, opus-round-2-review-caught) --
    both are defensible for a DISPLAY-only sizing estimate; not a byte-for-
    byte port.
    """
    is_yes = side.lower() == "yes"
    price = (
        prices["yes_ask"]
        if is_yes
        else (1.0 - prices["yes_bid"] if prices["yes_bid"] > 0 else 0.0)
    )
    if price <= 0:
        price = (
            prices["implied_prob"]
            if is_yes
            else max(0.01, 1.0 - prices["implied_prob"])
        )
    return price


def cmd_market(client: KalshiClient, ticker: str, verbose: bool = False):
    print(bold(f"\nFetching: {ticker}\n"))
    try:
        market = client.get_market(ticker)
    except Exception as _e:
        short_msg = str(_e)[:120]
        print(
            red(
                "  Could not reach Kalshi API. Check your internet connection and try again."
            )
        )
        print(dim(f"  (Error: {short_msg})"))
        return
    if not market:
        print(red(f"Market '{ticker}' not found."))
        return

    prices = parse_market_price(market)
    enriched = enrich_with_forecast(market)
    forecast = enriched.get("_forecast")
    analysis = analyze_trade(enriched)
    liquid = is_liquid(market)

    # ── Compact summary (always shown) ───────────────────────────────────────
    market_url = f"{_market_base_url()}/markets/{ticker}"
    _header(market.get("title", ticker)[:50])
    print(f"  {cyan(market_url)}")
    _kv("Closes:", (market.get("close_time") or "N/A")[:19].replace("T", " "))
    _kv("Liquid:", liquidity_color(liquid))

    if forecast:
        models = forecast.get("models_used", 1)
        hi_lo = forecast.get("high_range", (forecast["high_f"], forecast["high_f"]))
        high_str = bold(f"{forecast['high_f']:.1f}°F")
        range_str = dim(f"({hi_lo[0]:.0f}–{hi_lo[1]:.0f}° across {models} models)")
        _kv("Forecast:", f"{high_str} high  {range_str}")
        # Feels-like temperature (wind chill / heat index)
        try:
            fl = _feels_like(forecast["high_f"])
            if abs(fl - forecast["high_f"]) >= 3.0:
                _kv("Feels like:", f"{fl:.1f}°F")
        except Exception:
            pass

    # Whale detection
    # volume_fp/open_interest_fp are FixedPointCount strings on the current
    # live API (e.g. "10.00"), not numbers -- float() wrap needed or `> ` /
    # the "{:,}" comma-format spec below both raise on a str. Real bug found
    # live 2026-07-19, same root cause as the is_stale()/is_liquid()/
    # _liquidity_edge_scale TypeErrors fixed the same day.
    volume = float(market.get("volume_fp") or market.get("volume", 0) or 0)
    open_interest = float(
        market.get("open_interest_fp") or market.get("open_interest", 0) or 0
    )
    if volume > 5000 or open_interest > 2000:
        print(
            yellow(
                f"  ⚠  WHALE ALERT — volume: {volume:,}  open interest: {open_interest:,}"
            )
        )

    if analysis:
        edge = analysis["edge"]
        blended = analysis["forecast_prob"]
        kelly = analysis.get("kelly", 0)
        ci_lo = analysis.get("ci_low", blended)
        ci_hi = analysis.get("ci_high", blended)
        side = analysis["recommended_side"].upper()
        # batch-26 item 3: kelly_quantity's price arg must be side-aware, not
        # always prices["implied_prob"] (the YES mid) -- see
        # _side_aware_entry_price's docstring.
        _entry_price_ci = _side_aware_entry_price(side, prices)

        net_edge = analysis.get("net_edge", edge)
        fee_kelly = analysis.get("fee_adjusted_kelly", kelly)
        ci_kelly = analysis.get("ci_adjusted_kelly", fee_kelly)

        print()
        _kv(
            "Our P:",
            f"{bold(f'{blended * 100:.1f}%')}  {dim(f'[CI: {ci_lo * 100:.0f}%–{ci_hi * 100:.0f}%]')}",
        )
        _kv("Mkt P:", f"{prices['implied_prob'] * 100:.1f}%")
        _kv(
            "Edge:",
            f"{edge_color(edge)}  {dim('gross')}  →  {edge_color(net_edge)}  {dim('after fees')}",
        )
        if ci_kelly > 0.005:
            from paper import consensus_fraction_cap, kelly_bet_dollars, kelly_quantity

            _frac_cap = consensus_fraction_cap(analysis)
            bet_dollars = kelly_bet_dollars(
                ci_kelly, client=client, fraction_cap=_frac_cap
            )
            bet_qty = kelly_quantity(
                ci_kelly, _entry_price_ci, client=client, fraction_cap=_frac_cap
            )
            if fee_kelly > 0 and ci_kelly < fee_kelly * 0.85:
                penalty_pct = (fee_kelly - ci_kelly) / fee_kelly
                kelly_label = (
                    f"{bold(f'{fee_kelly * 100:.1f}%')} {dim('→')} "
                    f"{bold(f'{ci_kelly * 100:.1f}% of bankroll')}  "
                    f"{dim(f'(−{penalty_pct:.0%} CI penalty)')}"
                )
            else:
                kelly_label = f"{bold(f'{ci_kelly * 100:.1f}% of bankroll')}"
            _kv(
                "Kelly:",
                f"{kelly_label}  {green(f'→ ${bet_dollars:.2f}  (~{bet_qty} contracts)')}  {dim('fee-adjusted')}",
            )
        elif fee_kelly > 0.005:
            from paper import consensus_fraction_cap, kelly_bet_dollars, kelly_quantity

            _frac_cap = consensus_fraction_cap(analysis)
            bet_dollars = kelly_bet_dollars(
                fee_kelly, client=client, fraction_cap=_frac_cap
            )
            bet_qty = kelly_quantity(
                fee_kelly, _entry_price_ci, client=client, fraction_cap=_frac_cap
            )
            _kv(
                "Kelly:",
                f"{bold(f'{fee_kelly * 100:.1f}% of bankroll')}  {green(f'→ ${bet_dollars:.2f}  (~{bet_qty} contracts)')}  {dim('fee-adjusted')}",
            )
        elif kelly > 0.005:
            _kv(
                "Kelly:",
                dim(f"{kelly * 100:.1f}% of bankroll (negative after fees — skip)"),
            )
        print(f"\n  {signal_color(analysis['signal'].strip())}")
        _kv("Action:", f"BUY {bold(side)} on {ticker}")

        # Show assumed fee rate — matches what analyze_trade() actually used
        # (maker: live/paper entries are always resting midpoint GTC limit
        # orders, which pay $0 on this bot's markets).
        from utils import KALSHI_MAKER_FEE_RATE as _fee

        print(
            dim(
                f"  [Fee: {_fee * 100:.1f}% of profit assumed (maker rate). Set KALSHI_MAKER_FEE_RATE in .env to override]"
            )
        )

        # Show spread cost if notable
        spread_cost = analysis.get("spread_cost", 0.0)
        spread_scale = analysis.get("spread_scale", 1.0)
        if spread_cost >= 0.05 and spread_scale < 1.0:
            print(
                yellow(
                    f"  [Spread cost: {spread_cost:.1%} of mid — Kelly reduced {(1 - spread_scale):.0%}]"
                )
            )

        if not liquid:
            print(dim("  [No quotes yet — place a limit order to set your price]"))
        if analysis.get("ci_width", 0) > 0.30:
            print(
                yellow(
                    f"  [Wide CI ({analysis['ci_width']:.0%}) — high uncertainty, size down]"
                )
            )
        if analysis.get("forecast_anomalous"):
            print(
                yellow(
                    "  [Anomalous forecast — models disagree strongly, Kelly reduced 30%]"
                )
            )
        dq = analysis.get("data_quality", 1.0)
        if dq < 1.0:
            sources_missing = int((1.0 - dq) * 3)
            print(
                yellow(
                    f"  [Partial data — {sources_missing} source(s) unavailable, Kelly scaled down]"
                )
            )
        if abs(edge) < 0.05:
            print(dim("  [Edge too small — consider skipping]"))

        # Log to tracker
        try:
            # backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2 (review-
            # caught): enriched["_date"] is always None for KXRAIN*M tickers
            # by design (parse_city_date() never resolves one) -- fall back
            # to analysis["target_date"] (the close_time-derived date
            # _analyze_monthly_rain_trade() sets) so a manual lookup still
            # logs a real market_date, consistent with the automated path,
            # instead of a NULL row that get_quintile_bias/get_bias can
            # never match against.
            _log_market_date = enriched.get("_date")
            if _log_market_date is None and analysis.get("target_date"):
                try:
                    _log_market_date = date.fromisoformat(analysis["target_date"])
                except (ValueError, TypeError):
                    pass
            log_prediction(
                ticker,
                enriched.get("_city"),
                _log_market_date,
                analysis,
                **_prediction_kwargs_from_analysis(analysis),
                # cmd_market is a pure lookup/display command — it never places an
                # order, so this row must be flagged as shadow (is_shadow=True),
                # not read as a real trade, by callers like
                # get_pnl_by_signal_source's n_shadow count.
                is_shadow=True,
            )
        except Exception as _exc:
            logging.getLogger(__name__).warning(
                "cmd_market: log_prediction failed for %s: %s", ticker, _exc
            )
    else:
        print(
            dim(
                "\n  [Trade analysis unavailable — no forecast or unrecognised ticker format]"
            )
        )

    # ── Verbose details ───────────────────────────────────────────────────────
    if verbose and analysis:
        es = analysis.get("ensemble_stats") or {}
        n = analysis.get("n_members", 0)
        method = analysis.get("method", "?").upper()
        hour = enriched.get("_hour")
        cond = analysis["condition"]
        ct = cond["type"]
        if ct == "above":
            cond_str = f">{cond['threshold']:.1f}°F"
        elif ct == "below":
            cond_str = f"<{cond['threshold']:.1f}°F"
        elif ct == "between":
            cond_str = f"{cond['lower']:.1f}–{cond['upper']:.1f}°F"
        elif ct == "precip_above":
            cond_str = f">{cond.get('threshold', 0):.2f} in"
        else:
            cond_str = "any precip"
        is_precip = ct in ("precip_any", "precip_above")
        time_lbl = f"at {hour:02d}:00 local" if hour is not None else "daily high/low"

        print(f"\n  {bold('─── Verbose breakdown ───')}")
        print(f"  Method:   {method}, {n} ensemble members")
        print(
            f"  Question: {'precip' if is_precip else 'temp'} {cond_str}  ({time_lbl})"
        )
        if es:
            print(
                f"  Spread:   {es['min']:.1f}–{es['max']:.1f}°F  "
                f"(mean {es['mean']:.1f}°F, σ={es['std']:.1f}°F)"
            )
            print(f"  P10–P90:  {es['p10']:.1f}°F – {es['p90']:.1f}°F")

        print(f"\n  {bold('Probability sources:')}")
        if analysis.get("obs_prob") is not None:
            obs = analysis["live_obs"]
            print(
                f"    Live obs:     {analysis['obs_prob'] * 100:.1f}%  "
                f"(current {obs['temp_f']:.1f}°F)"
            )
        if analysis.get("ensemble_prob") is not None:
            print(
                f"    Ensemble:     {analysis['ensemble_prob'] * 100:.1f}%  ({n} members)"
            )
        if analysis.get("nws_prob") is not None:
            print(f"    NWS official: {analysis['nws_prob'] * 100:.1f}%")
        if analysis.get("clim_prob") is not None:
            adj = analysis.get("index_adj", 0)
            adj_s = (
                f"  → {analysis['clim_adj_prob'] * 100:.1f}% after {adj:+.1f}°F index adj"
                if abs(adj) > 0.1
                else ""
            )
            print(f"    Climatology:  {analysis['clim_prob'] * 100:.1f}%{adj_s}")

        bs_dict = analysis.get("blend_sources", {})
        blend_s = "  +  ".join(
            f"{int(v * 100)}% {k}" for k, v in bs_dict.items() if v > 0.01
        )
        print(f"\n  Blend:    {blend_s}")

        bias = analysis.get("bias_correction", 0)
        if abs(bias) > 0.01:
            print(f"  Bias corr:{-bias:+.1%}  (from track record)")

    # ── Orderbook ─────────────────────────────────────────────────────────────
    print(f"\n  {bold('Orderbook:')}")
    try:
        ob = client.get_orderbook(ticker)
        yes_bids = ob.get("yes_dollars", ob.get("yes", []))
        no_bids = ob.get("no_dollars", ob.get("no", []))
        ob_rows = []
        for i in range(min(5, max(len(yes_bids), len(no_bids)))):
            y = yes_bids[-(i + 1)] if i < len(yes_bids) else ["—", "—"]
            n = no_bids[-(i + 1)] if i < len(no_bids) else ["—", "—"]
            ob_rows.append([green(f"${y[0]}"), y[1], red(f"${n[0]}"), n[1]])
        if ob_rows:
            print(
                tabulate(
                    ob_rows,
                    headers=["YES price", "YES qty", "NO price", "NO qty"],
                    tablefmt="rounded_outline",
                )
            )
        else:
            print(dim("  No orders in book."))
    except Exception as e:
        print(dim(f"  Could not load orderbook: {e}"))


# ── Analyze ───────────────────────────────────────────────────────────────────


def _analyze_once(
    client: KalshiClient,
    previous_tickers: set | None = None,
    _liquid_opps_out: list | None = None,
    min_edge: float | None = None,
    show_summary: bool = False,
):
    """Run one analysis pass. Returns set of opportunity tickers found."""
    if min_edge is None:
        min_edge = MIN_EDGE
    markets = get_weather_markets(client)
    # Dedup by ticker + skip stale markets before analysis, matching cron.py's
    # cmd_cron parity (backlog.txt "THE ONLY LIVE-ORDER PATH..." smallest-safe
    # step) -- same market can appear twice under Kalshi's old/new
    # series-ticker formats, and a zero-volume market closing within 60min has
    # no meaningful edge (see weather_markets.is_stale's docstring).
    from weather_markets import is_stale as _is_stale_market

    _seen_tickers: set[str] = set()
    _deduped_markets: list[dict] = []
    _stale_skipped = 0
    for _m in markets:
        _m_ticker = _m.get("ticker", "")
        if _m_ticker in _seen_tickers:
            continue
        _seen_tickers.add(_m_ticker)
        if _is_stale_market(_m):
            _stale_skipped += 1
            continue
        _deduped_markets.append(_m)
    if len(_deduped_markets) < len(markets) - _stale_skipped:
        _log.debug(
            "_analyze_once: deduped %d duplicate ticker(s) before analysis",
            len(markets) - _stale_skipped - len(_deduped_markets),
        )
    if _stale_skipped:
        _log.debug(
            "_analyze_once: skipped %d stale market(s) (no volume, closing within 60min)",
            _stale_skipped,
        )
    markets = _deduped_markets
    liquid_opps: list = []
    no_quote_opps: list = []
    total = len(markets)
    _same_day_seen = 0
    _mkt_prob_skipped = 0
    _divergence_skipped = 0

    # Market-implied temperature distribution (backlog.txt "MARKET-IMPLIED
    # TEMPERATURE DISTRIBUTION FROM THE FULL LADDER"): computed once per scan
    # from the already-fetched sibling ladder (pure CPU, no network calls),
    # mirroring cron.py's cmd_cron wiring of the same signal.
    from weather_markets import (
        compute_market_implied_distributions as _compute_market_implied,
    )
    from weather_markets import resolve_market_implied_for_analysis

    _market_implied_by_event = _compute_market_implied(markets)

    # #64: load open trades once so we can flag hedge opportunities below
    try:
        from paper import get_open_trades as _got

        _open_trades = _got()
    except Exception:
        _open_trades = []

    # A4: ticker→city map built during enrichment for arb exposure checks
    _arb_ticker_city: dict[str, str] = {}

    for i, m in enumerate(markets, 1):
        if total > 5:
            print(f"\r  Scanning [{i}/{total}]...", end="", flush=True)
        try:
            enriched = enrich_with_forecast(m)
            analysis = analyze_trade(enriched)
        except Exception as exc:
            # #109: include ticker in error so failures are debuggable
            import logging as _logging

            _logging.getLogger(__name__).warning(
                "Market analysis failed for %s: %s", m.get("ticker", "?"), exc
            )
            continue
        _arb_ticker_city[m.get("ticker", "")] = enriched.get("_city", "")
        if not analysis:
            continue
        analysis["market_implied"] = resolve_market_implied_for_analysis(
            _market_implied_by_event,
            enriched.get("_city"),
            enriched.get("_date"),
            m.get("ticker", ""),
        )
        # Log-only edge-threshold divisor (backlog.txt "LIQUIDITY-AWARE
        # SIZING + DYNAMIC EDGE THRESHOLD"): mirrors cron.py's wiring --
        # computed at the scan-loop level, never inside analyze_trade
        # itself, and never used for signal classification here either.
        from weather_markets import _liquidity_edge_scale as _liq_scale

        # Accept both legacy (volume/open_interest) and current API names
        # (volume_fp/open_interest_fp) -- matches analyze_trade()'s own
        # liquidity gate and paper.liquidity_kelly_scale exactly.
        _liq_edge_scale = _liq_scale(
            m.get("volume_fp") or m.get("volume") or 0,
            m.get("open_interest_fp") or m.get("open_interest") or 0,
        )
        analysis["liquidity_edge_scale"] = _liq_edge_scale
        # adjusted_edge (not raw edge) matches cron.py's wiring -- both scan
        # paths must derive gated_edge from the same base value so a future
        # correlation check compares like with like regardless of which path
        # logged the row.
        analysis["gated_edge"] = (
            analysis.get("adjusted_edge", analysis.get("edge", 0.0)) / _liq_edge_scale
        )
        # Same-day markets (days_out == 0) are re-enabled (matches cron.py's
        # cmd_cron parity, backlog.txt "THE ONLY LIVE-ORDER PATH..."):
        # analyze_trade uses METAR-locked probabilities for same-day
        # above/below markets, which gives tight CI width -> larger
        # ci_adjusted_kelly. Between markets at days_out == 0 skip the obs
        # override in analyze_trade so they fall back to ensemble and are
        # covered by the between_floor gate.
        if int(analysis.get("days_out", 1)) == 0:
            _same_day_seen += 1
            # fall through — do not skip
        # Market divergence gates (matches cron.py's cmd_cron parity,
        # backlog.txt "WATCH/_analyze_once IS MISSING cron.py's
        # MIN_MARKET_PROB_TO_BET_WITH / MAX_MARKET_DIVERGENCE_RATIO
        # DIRECTIONAL-CONSENSUS GATES"): analyze_trade's own model-market gap
        # gate (weather_markets.py "7d") compares the RAW pre-anchor model
        # probability against the market symmetrically; these two gates
        # additionally check the market's own probability in the direction
        # we'd actually bet -- skip when the market gives our side <25%
        # (MIN_MARKET_PROB_TO_BET_WITH) or when we disagree by more than
        # MAX_MARKET_DIVERGENCE_RATIO -- "the market is right nearly every
        # time" at that level of disagreement.
        from utils import MAX_MARKET_DIVERGENCE_RATIO, MIN_MARKET_PROB_TO_BET_WITH

        _side = analysis.get("recommended_side", "yes")
        _our_p = analysis.get("forecast_prob", 0.5)
        _mkt_p = analysis.get("market_prob", 0.5)
        if _side == "yes":
            _mkt_dir = _mkt_p
            _our_dir = _our_p
        else:
            _mkt_dir = 1.0 - _mkt_p
            _our_dir = 1.0 - _our_p
        if _mkt_dir < MIN_MARKET_PROB_TO_BET_WITH:
            _mkt_prob_skipped += 1
            continue
        if _mkt_dir > 0 and _our_dir / _mkt_dir > MAX_MARKET_DIVERGENCE_RATIO:
            _divergence_skipped += 1
            continue
        # Tag whether this market passes the edge threshold so make_rows can dim it,
        # but do NOT drop it — analyse always shows top 50 regardless of edge.
        _gate_edge = analysis.get("entry_side_edge", analysis["edge"])
        analysis["_passes_edge"] = abs(_gate_edge) >= min_edge
        # #64: tag analysis as a hedge if it reduces existing open exposure
        analysis["_is_hedge"] = detect_hedge_opportunity(analysis, _open_trades)
        liquid = is_liquid(m)
        (liquid_opps if liquid else no_quote_opps).append((enriched, analysis))
        # Fire desktop alert for new strong liquid opportunities
        if (
            liquid
            and "STRONG" in analysis.get("net_signal", "")
            and previous_tickers is not None
            and m.get("ticker") not in previous_tickers
        ):
            alert_strong_signal(
                ticker=m.get("ticker", ""),
                city=enriched.get("_city", ""),
                side=analysis["recommended_side"],
                net_edge=analysis.get("net_edge", analysis["edge"]),
                kelly=analysis.get("fee_adjusted_kelly", analysis.get("kelly", 0)),
            )

    if total > 5:
        print(f"\r  Scanned {total} markets.          ")  # clear progress line
    if _same_day_seen:
        _log.debug(
            "_analyze_once: %d same-day (days_out == 0) market(s) analyzed",
            _same_day_seen,
        )
    if _mkt_prob_skipped:
        _log.debug(
            "_analyze_once: skipped %d market(s) — market gives our side "
            "< min_market_prob_to_bet_with",
            _mkt_prob_skipped,
        )
    if _divergence_skipped:
        _log.debug(
            "_analyze_once: skipped %d market(s) — model/market divergence "
            "> max_market_divergence_ratio",
            _divergence_skipped,
        )

    return _render_analysis_results(
        client,
        markets,
        liquid_opps,
        no_quote_opps,
        previous_tickers,
        min_edge,
        show_summary,
        _open_trades,
        _arb_ticker_city,
        _liquid_opps_out,
    )


def _render_analysis_results(
    client: KalshiClient,
    markets: list,
    liquid_opps: list,
    no_quote_opps: list,
    previous_tickers: set | None,
    min_edge: float,
    show_summary: bool,
    _open_trades: list,
    _arb_ticker_city: dict,
    _liquid_opps_out: list | None = None,
) -> set:
    """Render the interactive analyze/watch table (liquid + no-quote market
    tables, arbitrage surface -- including live corrective-trade PLACEMENT,
    not just display, see the "Arbitrage surface" block below --, portfolio-
    correlation warning, optional summary line) and return the set of all
    opportunity tickers found.

    Extracted from _analyze_once()'s own body (position-protection
    unification's sibling follow-up; see backlog.txt's [CMD_WATCH RUNS THREE
    INDEPENDENT get_weather_markets() SCANS...] entry) so cmd_watch's
    auto-trading loop can call this directly with trade_cycle.run_trade_
    cycle()'s own already-scanned/already-analyzed data instead of running a
    second independent get_weather_markets()+enrich+analyze pass just to
    render the display. Called BY _analyze_once() itself below (unchanged
    behavior for cmd_analyze and plain/non-auto watch, which still source
    this from a fresh scan) and ALSO directly by cmd_watch when auto_trade
    cycle_result is available.

    ``markets``: the DEDUPED/stale-filtered list (matches _analyze_once's own
    ``markets`` var by this point, NOT trade_cycle.TradeCycleResult.markets,
    which is pre-dedup -- use ``.deduped_markets`` when sourcing from a
    cycle_result). ``liquid_opps``/``no_quote_opps``: (enriched, analysis)
    pairs already gate-tagged with ``_passes_edge`` -- from run_trade_cycle(),
    this is aliased to the real ``_passes_threshold`` outcome (see trade_
    cycle.py's own comment on that alias), not a separately-computed cosmetic
    threshold, so display dimming here always matches what actually traded.
    ``min_edge``: only used for the printed "dimmed below >X%" threshold text
    (dimming itself is driven by the pre-tagged ``_passes_edge`` field, not
    recomputed here) -- pass ``TradeCycleResult.effective_min_edge`` when
    sourcing from one, not the raw CLI ``--edge`` value, so the printed
    threshold matches what was actually applied. ``_open_trades``: the caller
    must fetch this itself when not calling from _analyze_once (see
    cmd_watch's cycle_result branch). ``_arb_ticker_city``: pass
    ``TradeCycleResult.ticker_city`` directly when sourcing from one -- do
    NOT derive it from ``.all_results`` (narrower: only markets where
    analyze_trade() returned truthy, unlike this tag point, which is before
    that check -- an opus review caught this exact gap on 2026-08-03, which
    silently bypassed the arb per-city exposure cap and dropped city
    attribution on placed arb trades whenever analyze_trade() returned falsy).
    """

    # backlog.txt "main.py's _rating() CLI TABLE IS A 4TH, STILL-TEXT-DERIVED
    # STAR LADDER": a sentinel (not None) distinguishes "analysis dict never
    # carries a tier field at all" (_analyze_once's own opps -- _rating must
    # keep using the net_edge/risk math below, unchanged) from "tier field
    # present but None" (cycle_result.liquid_opps opps that didn't clear
    # trade_cycle.py's placement gate -- a real, authoritative verdict that
    # must NOT be overridden by raw net_edge magnitude). Plain `None` can't
    # make that distinction since both cases read back as None via .get().
    _NO_TIER = object()

    def _rating(net_edge: float, risk: str, tier: object = _NO_TIER) -> str:
        """★★★ = strong edge + low risk, ★★ = good edge, ★ = fair edge.

        When ``tier`` is passed (a candidate sourced from cycle_result.
        liquid_opps, which does carry the authoritative `tier` field), it
        takes priority over the net_edge/risk math, mirroring trade_cycle.
        py's dashboard-stars ladder's own STRONG-requires-LOW-time-risk /
        MED-or-STRONG-otherwise shape for the 3-star/2-star rungs. Not a
        byte-for-byte match to that ladder or to signals_cache.json's
        `stars` field, though: this table always renders one of the three
        rungs for every row it shows (it has no blank/no-stars case), so a
        gate-failed candidate (tier=None) renders the bottom dim-★ rung
        here where the dashboard/signals_cache ladder would show "" (empty)
        for the same candidate if it also failed the passes_threshold check
        those sites additionally gate on -- a real, deliberate difference in
        contract, not a bug, since this table is displaying "here are your
        top opportunities" rather than "did this clear the alert bar."
        """
        if tier is not _NO_TIER:
            from trade_cycle import TIER_MED, TIER_STRONG

            if tier == TIER_STRONG and risk == "LOW":
                return green("★★★")
            elif tier in (TIER_STRONG, TIER_MED):
                return yellow("★★ ")
            else:
                return dim("★  ")
        ae = abs(net_edge)
        if ae >= STRONG_EDGE and risk != "HIGH":
            return green("★★★")
        elif ae >= 0.12:
            return yellow("★★ ")
        else:
            return dim("★  ")

    def make_rows(opps):
        rows = []
        urls = []
        # Sort best opportunity (highest net edge) first, show top 50 regardless of edge gate
        sorted_opps = sorted(
            opps, key=lambda x: abs(x[1].get("net_edge", x[1]["edge"])), reverse=True
        )[:50]
        for m, a in sorted_opps:
            is_new = (
                previous_tickers is not None and m.get("ticker") not in previous_tickers
            )
            ticker = m.get("ticker", "")
            net_edge = a.get("net_edge", a["edge"])
            risk = a.get("time_risk", "—")
            title = (m.get("title") or ticker)[:38]
            url = f"{_market_base_url()}/markets/{ticker}"
            urls.append((ticker, url))
            if is_new:
                ticker_str = green(f"* {ticker}")
            elif not a.get("_passes_edge", True):
                ticker_str = dim(ticker)
            else:
                ticker_str = ticker
            mkt_pct = f"{a['market_prob'] * 100:.0f}%"
            # Show probability-point gap (directional: positive = favours recommended side)
            _raw_edge = a.get("edge", 0.0)
            _side = a["recommended_side"]
            _disp_edge = _raw_edge if _side == "yes" else -_raw_edge
            edge_pct = (
                green(f"+{_disp_edge * 100:.0f}%")
                if _disp_edge > 0
                else red(f"{_disp_edge * 100:.0f}%")
            )
            # #64: show hedge tag when this trade reduces open directional exposure
            buy_side = bold(a["recommended_side"].upper())
            if a.get("_is_hedge"):
                buy_side = buy_side + cyan(" [HEDGE]")
            rows.append(
                [
                    _rating(net_edge, risk, a.get("tier", _NO_TIER)),
                    ticker_str,
                    title,
                    m.get("_city", ""),
                    m.get("_date").isoformat() if m.get("_date") else "",
                    prob_color(a["forecast_prob"]),
                    mkt_pct,
                    edge_pct,
                    risk,
                    _format_expiry(m.get("close_time", "")),
                    buy_side,
                ]
            )
        return rows, urls

    def _plain_english(analysis: dict, market: dict) -> str:
        """
        Generate a one-sentence plain-English explanation of the trade opportunity.
        Example: "Model thinks 68% chance NYC hits 72°F. Market only prices it at 52%.
        A $10 bet would win $8.40 after fees if correct."
        """
        city = market.get("_city") or market.get("city", "")
        tdate = market.get("_date")
        date_str = tdate.isoformat() if tdate else "target date"
        forecast_prob = analysis.get("forecast_prob", 0.5)
        market_prob = analysis.get("market_prob", 0.5)
        gap = abs(forecast_prob - market_prob)
        side = analysis.get("recommended_side", "yes")
        entry_price = (
            analysis.get("market_prob", 0.5)
            if side == "yes"
            else 1 - analysis.get("market_prob", 0.5)
        )
        # Compute what a $10 bet returns. Maker fee (not taker): live/paper
        # entries are always resting midpoint GTC limit orders, which pay $0
        # on this bot's markets (see KALSHI_MAKER_FEE_RATE).
        stake = 10.0
        from utils import KALSHI_MAKER_FEE_RATE as _fee

        winnings = (1 - entry_price) * (1 - _fee)
        win_amount = round(stake / entry_price * winnings, 2)

        cond = analysis.get("condition", {})
        cond_type = cond.get("type", "")
        if cond_type == "above":
            cond_desc = f"above {cond['threshold']:.0f}°F"
        elif cond_type == "below":
            cond_desc = f"below {cond['threshold']:.0f}°F"
        elif cond_type == "between":
            cond_desc = f"between {cond['lower']:.0f}–{cond['upper']:.0f}°F"
        elif cond_type == "precip_any":
            cond_desc = "any precipitation"
        elif cond_type == "precip_above":
            cond_desc = f"over {cond.get('threshold', 0):.2f} inches of rain"
        else:
            cond_desc = "the condition"

        if side == "yes":
            market_line = (
                f"  The market only prices it at {market_prob:.0%} — a {gap:.0%} gap. "
                f"A $10 bet wins ${win_amount:.2f}\n"
                f"  after fees if you're right (and loses $10 if wrong)."
            )
        else:
            no_price = 1 - market_prob
            market_line = (
                f"  The market prices YES at {market_prob:.0%} — we say only {forecast_prob:.0%} — "
                f"so we buy NO at {no_price:.0%}. A $10 bet wins ${win_amount:.2f}\n"
                f"  after fees if you're right (and loses $10 if wrong)."
            )
        return (
            f"Model thinks there's a {forecast_prob:.0%} chance {city} hits {cond_desc} "
            f"on {date_str}.\n"
            f"{market_line}"
        )

    hdrs = [
        "Rating",
        "ID",
        "Bet Question",
        "City",
        "Date",
        "We Think",
        "Mkt Says",
        "Your Edge",
        "Risk",
        "Closes In",
        "Buy",
    ]

    _liquid_passing = [x for x in liquid_opps if x[1].get("_passes_edge", True)]
    if liquid_opps:
        rows, urls = make_rows(liquid_opps)
        print(
            bold(
                f"\n── Markets — Ready to Trade (top {min(50, len(liquid_opps))},"
                f" {len(_liquid_passing)} above edge threshold) ──\n"
            )
        )
        print(tabulate(rows, headers=hdrs, tablefmt="rounded_outline"))
        print(
            dim(
                f"  Dimmed tickers didn't clear the >{min_edge:.0%} edge threshold"
                " (or another gate the engine applied this cycle)."
            )
        )
        # Top pick plain-English explanation (best above-threshold pick only)
        passing = [(m, a) for m, a in liquid_opps if a.get("_passes_edge", True)]
        if passing:
            best_m, best_a = max(
                passing, key=lambda x: abs(x[1].get("net_edge", x[1]["edge"]))
            )
            explanation = _plain_english(best_a, best_m)
            print(f"\n  {bold('Top pick:')} {explanation}")
        if urls:
            print(dim("\n  Market links:"))
            for ticker, url in urls:
                print(f"    {ticker:<32} {cyan(url)}")
    else:
        print(dim("  No tradeable opportunities right now (none with live quotes)."))

    if no_quote_opps:
        _nq_passing = [x for x in no_quote_opps if x[1].get("_passes_edge", True)]
        rows, urls = make_rows(no_quote_opps)
        print(
            bold(
                f"\n── Markets — No Price Set Yet (top {min(50, len(no_quote_opps))},"
                f" {len(_nq_passing)} above edge threshold) ──\n"
            )
        )
        print(tabulate(rows, headers=hdrs, tablefmt="rounded_outline"))
        print(
            dim(
                "  These markets have no buyers/sellers yet."
                " You can still place a limit order to set your own price."
                f" Dimmed tickers didn't clear the >{min_edge:.0%} edge threshold"
                " (or another gate the engine applied this cycle)."
            )
        )
        if urls:
            print(dim("\n  Market links:"))
            for ticker, url in urls:
                print(f"    {ticker:<32} {cyan(url)}")

    if not liquid_opps and not no_quote_opps:
        print(yellow("  No markets with a valid forecast found right now."))

    # ── Arbitrage surface ────────────────────────────────────────────────────
    try:
        violations = find_violations(markets)
        if violations:
            print(bold("\n── Arbitrage Opportunities ──\n"))
            from trading_gates import LiveTradingGate as _LiveTradingGate

            _arb_gate = _LiveTradingGate()
            _arb_allowed, _arb_gate_reason = _arb_gate.check(client)
            if not _arb_allowed:
                _log.warning(
                    "consistency: skipping all corrective trades — gate blocked: %s",
                    _arb_gate_reason,
                )
                print(
                    yellow(
                        f"  [Arb] All corrective trades skipped — halt active: {_arb_gate_reason}"
                    )
                )
            from weather_markets import MIN_SIGNAL_VOLUME as _ARB_MIN_VOL

            _arb_vol: dict[str, float] = {
                m.get("ticker", ""): float(m.get("volume_fp") or m.get("volume") or 0)
                for m in markets
            }
            # Build city→open-cost map from already-loaded open trades
            _arb_city_cost: dict[str, float] = {}
            for _ot in _open_trades:
                _oc = _ot.get("city") or ""
                _arb_city_cost[_oc] = _arb_city_cost.get(_oc, 0.0) + float(
                    _ot.get("cost", 0.0)
                )

            from paper import place_paper_order as _arb_ppo

            # Tickers with an existing open position will hit
            # place_paper_order's duplicate-open-position guard on whichever
            # leg touches them — most persistently when the bot already
            # holds a directional position on sell_ticker. Skip those
            # violations up front instead of placing leg1, failing leg2,
            # and unwinding leg1 again on every single watch/cron cycle
            # for as long as the violation persists.
            _arb_open_tickers = {
                t["ticker"] for t in _open_trades if not t.get("settled")
            }

            for v in violations:
                print(
                    green(
                        f"  Buy {v.buy_ticker} ({v.buy_prob * 100:.0f}¢)"
                        f" + Sell {v.sell_ticker} ({v.sell_prob * 100:.0f}¢)"
                        f"  → guaranteed +{v.guaranteed_edge * 100:.0f}¢ edge"
                    )
                )
                if hasattr(v, "description") and v.description:
                    print(dim(f"  {v.description}"))

                # backlog.txt "RAIN MARKETS -- CONSISTENCY.PY'S ARBITRAGE
                # CHECK STILL BLANKET-EXCLUDES KXRAIN*M": rain-sourced
                # violations are a first pass -- detect and log, but never
                # auto-place, until a separate later decision graduates
                # them (mirrors this project's shadow-then-graduate
                # pattern for every other new-market-type signal).
                if getattr(v, "is_shadow", False):
                    print(
                        dim(
                            "  [Shadow] rain arbitrage — logged only, not placed"
                            " (see backlog.txt)"
                        )
                    )
                    continue

                # A4: auto-place when gate open, edge, volume, and city-exposure all pass
                if not _arb_allowed:
                    continue
                if v.guaranteed_edge < MIN_ARB_EDGE:
                    continue
                buy_vol = _arb_vol.get(v.buy_ticker, 0.0)
                sell_vol = _arb_vol.get(v.sell_ticker, 0.0)
                if buy_vol < _ARB_MIN_VOL or sell_vol < _ARB_MIN_VOL:
                    print(
                        dim(
                            f"  [Arb] Skipped — volume {buy_vol:.0f}/{sell_vol:.0f}"
                            f" < {_ARB_MIN_VOL}"
                        )
                    )
                    continue
                _arb_city = (
                    _arb_ticker_city.get(v.buy_ticker)
                    or _arb_ticker_city.get(v.sell_ticker)
                    or ""
                )
                _ARB_CITY_LIMIT = 25.0  # max $25 open arb exposure per city-group
                if _arb_city_cost.get(_arb_city, 0.0) >= _ARB_CITY_LIMIT:
                    print(
                        dim(
                            f"  [Arb] Skipped — {_arb_city or 'unknown'} exposure"
                            f" ${_arb_city_cost.get(_arb_city, 0):.2f}"
                            f" >= ${_ARB_CITY_LIMIT:.0f}"
                        )
                    )
                    continue
                if (
                    v.buy_ticker in _arb_open_tickers
                    or v.sell_ticker in _arb_open_tickers
                ):
                    print(
                        dim(
                            f"  [Arb] Skipped — {v.buy_ticker} or {v.sell_ticker} "
                            "already has an open position"
                        )
                    )
                    continue
                try:
                    yes_price = max(0.01, min(0.99, v.buy_prob))
                    no_price = max(0.01, min(0.99, 1.0 - v.sell_prob))
                    _arb_leg1 = _arb_ppo(
                        v.buy_ticker,
                        "yes",
                        1,
                        yes_price,
                        thesis="consistency-arb",
                        city=_arb_city or None,
                    )
                    try:
                        _arb_ppo(
                            v.sell_ticker,
                            "no",
                            1,
                            no_price,
                            thesis="consistency-arb",
                            city=_arb_city or None,
                        )
                    except Exception as _arb_leg2_exc:
                        # Second leg failed after the first succeeded — this
                        # is no longer a hedged arb, it's a naked directional
                        # bet mislabeled "consistency-arb". Unwind the first
                        # leg immediately instead of leaving it open and
                        # undercounting city exposure for later violations.
                        _unwound = False
                        try:
                            import paper as _paper_arb

                            _paper_arb.close_paper_early(_arb_leg1["id"], yes_price)
                            _unwound = True
                        except Exception as _unwind_exc:
                            # Don't claim success when the unwind itself
                            # failed — that leaves a naked leg open with the
                            # console asserting the opposite of reality.
                            _log.warning(
                                "[Arb] Failed to unwind %s leg #%s after leg2 failure: %s",
                                v.buy_ticker,
                                _arb_leg1.get("id"),
                                _unwind_exc,
                            )
                        if _unwound:
                            print(
                                red(
                                    f"  [Arb] Second leg failed ({_arb_leg2_exc}) — "
                                    f"unwound the {v.buy_ticker} YES leg to avoid a naked position."
                                )
                            )
                        else:
                            print(
                                red(
                                    f"  [Arb] Second leg failed ({_arb_leg2_exc}) — "
                                    f"AND unwind of the {v.buy_ticker} YES leg also failed. "
                                    "A naked position may remain open — check manually."
                                )
                            )
                        continue
                    _arb_city_cost[_arb_city] = (
                        _arb_city_cost.get(_arb_city, 0.0) + yes_price + no_price
                    )
                    print(
                        green(
                            f"  [Arb] Placed: BUY YES {v.buy_ticker} @ {yes_price:.0%}"
                            f" + BUY NO {v.sell_ticker} @ {no_price:.0%}"
                        )
                    )
                except Exception as _arb_exc:
                    print(dim(f"  [Arb] Could not place: {_arb_exc}"))
    except Exception as _arb_outer_exc:
        # L-9: this outer handler covers find_violations()/the gate check/the
        # per-city cost bookkeeping *around* the inner per-violation try above
        # (which already handles the naked-leg unwind and logs at WARNING) --
        # an exception here used to vanish silently even though it's in the
        # same code path that places real paper orders.
        _log.error("consistency: arbitrage placement block failed: %s", _arb_outer_exc)

    # ── Portfolio correlation warning ────────────────────────────────────────
    # Only warn on above-threshold opps — sub-threshold markets aren't being traded.
    all_opps = liquid_opps + no_quote_opps
    _tradeable_opps = [(m, a) for m, a in all_opps if a.get("_passes_edge", True)]
    from collections import Counter

    city_date_counts: Counter = Counter()
    for m, _ in _tradeable_opps:
        key = (m.get("_city", ""), str(m.get("_date", "")))
        city_date_counts[key] += 1
    for (city, dt), cnt in city_date_counts.items():
        if cnt >= 2:
            msg = f"⚠  Correlation: {cnt} opportunities for {city} on {dt}"
            detail = (
                "Size down or pick the highest-edge one — these bets move together."
            )
            inner = max(len(msg), len(detail))
            bar = "─" * (inner + 2)
            print(yellow(f"\n  ┌{bar}┐"))
            print(yellow(f"  │ {msg:<{inner}} │"))
            print(yellow(f"  │ {detail:<{inner}} │"))
            print(yellow(f"  └{bar}┘"))

    if show_summary:
        n_total = len(_tradeable_opps)
        n_scanned = len(markets)
        _tradeable_liquid = [x for x in _tradeable_opps if is_liquid(x[0])]
        if _tradeable_opps:
            best_m, best_a = max(_tradeable_opps, key=lambda x: abs(x[1]["edge"]))
            _be_raw = best_a["edge"]
            _be_side = best_a["recommended_side"]
            best_edge = _be_raw if _be_side == "yes" else -_be_raw
            best_ticker = best_m.get("ticker", "")
            opp_word = "opp" if n_total == 1 else "opps"
            print(
                dim(
                    f"\n  {n_scanned} markets scanned · {n_total} {opp_word}"
                    f" ({len(_tradeable_liquid)} liquid)"
                    f" · best edge {best_edge:+.1%} {best_ticker}"
                )
            )
        else:
            print(
                dim(
                    f"\n  {n_scanned} markets scanned"
                    f" · no opportunities cleared the {min_edge:.0%} threshold"
                    " (or another gate)"
                )
            )

    found = {m.get("ticker") for m, _ in all_opps}
    # Expose only above-threshold liquid opps to callers (e.g., auto-trade watch mode).
    # The display shows all markets, but auto-trading must only see edge-qualifying ones.
    if _liquid_opps_out is not None:
        _liquid_opps_out.extend(
            (m, a) for m, a in liquid_opps if a.get("_passes_edge", True)
        )
    return found


_LIVE_CONFIG_PATH = LIVE_CONFIG_PATH
_LIVE_CONFIG_DEFAULT: dict = {
    "max_trade_dollars": 50,
    "daily_loss_limit": 200,
    "max_open_positions": 10,
    "gtc_cancel_hours": 24,
}


def _load_live_config() -> dict:
    """Load live trading hard stops from data/live_config.json.

    Creates the file with safe defaults if it does not exist.
    Returns the config dict, merged over _LIVE_CONFIG_DEFAULT so a missing key
    (partial/hand-edited file) can't silently fail open -- e.g. callers read
    `cfg.get("daily_loss_limit", float("inf"))`, so a config dict missing that
    key entirely would disable the daily-loss circuit breaker instead of using
    the safe $200 default.
    """
    import logging as _cfg_log
    import math

    try:
        with open(_LIVE_CONFIG_PATH, encoding="utf-8") as f:
            loaded = json.load(f)
    except FileNotFoundError:
        # Opus review (M-C): mkdir()/write_text() here can themselves raise
        # OSError (read-only data dir, disk full, an AV lock during create) --
        # that's a NEW exception raised while already handling
        # FileNotFoundError, so the `except OSError` clause below (which only
        # wraps the original `try:` block above) can't catch it. Same AUD-0008
        # failure mode this whole function exists to close, just one branch
        # over -- give the create step its own guard instead.
        try:
            _LIVE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _LIVE_CONFIG_PATH.write_text(
                json.dumps(_LIVE_CONFIG_DEFAULT, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            _cfg_log.getLogger(__name__).warning(
                "_load_live_config: could not create default %s (%s) — using "
                "in-memory defaults this cycle",
                _LIVE_CONFIG_PATH,
                exc,
            )
        return dict(_LIVE_CONFIG_DEFAULT)
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        # M-20: corrupted live_config.json (interrupted write) must fall back to
        # defaults — previously an unhandled JSONDecodeError crashed the watch path.
        _cfg_log.getLogger(__name__).error(
            "_load_live_config: %s is corrupted (%s) — using defaults",
            _LIVE_CONFIG_PATH,
            exc,
        )
        return dict(_LIVE_CONFIG_DEFAULT)
    except OSError as exc:
        # M-26: a transient error (AV-scan PermissionError, a Windows sharing
        # violation, a disk hiccup) on open()/read() must not propagate -- this
        # is called every cycle inside cmd_watch's persistent `while True` loop,
        # whose only exception handler is `except KeyboardInterrupt` (the exact
        # failure mode AUD-0008 already fixed for the sibling position-
        # protection block a few lines below this call site).
        _cfg_log.getLogger(__name__).warning(
            "_load_live_config: could not read %s (%s) — using defaults this cycle",
            _LIVE_CONFIG_PATH,
            exc,
        )
        return dict(_LIVE_CONFIG_DEFAULT)

    if not isinstance(loaded, dict):
        _cfg_log.getLogger(__name__).error(
            "_load_live_config: %s did not contain a JSON object (got %s) — "
            "using defaults",
            _LIVE_CONFIG_PATH,
            type(loaded).__name__,
        )
        return dict(_LIVE_CONFIG_DEFAULT)

    # Opus review (M-D): merging over the default fixes a MISSING key, but a
    # present-and-null (or wrong-typed, e.g. a string) value would still
    # overwrite the safe default and pass the plain dict merge -- callers'
    # `cfg.get("daily_loss_limit", float("inf"))` only helps when the key is
    # absent, not when it's `None`; a `None` there raises TypeError on the
    # first numeric comparison in the same live-order path M-26 set out to
    # protect. Validate each KNOWN key's type before accepting it from
    # `loaded`; unrecognized extra keys pass through unchanged (harmless).
    merged = dict(_LIVE_CONFIG_DEFAULT)
    for _key, _default_val in _LIVE_CONFIG_DEFAULT.items():
        _val = loaded.get(_key, _default_val)
        # Round-2 opus review (M2-3): json.load() accepts bare NaN/Infinity
        # (a non-standard-JSON Python extension) as a real float, so the
        # isinstance check alone let `{"daily_loss_limit": NaN}` through --
        # every consumer's gate is `live_loss >= daily_loss_limit`, which is
        # always False against NaN, silently disabling the circuit breaker.
        # math.isfinite() rejects NaN/+-Infinity the same way the type check
        # rejects a string, closing the exact fail-open direction this
        # function exists to prevent.
        if (
            isinstance(_val, int | float)
            and not isinstance(_val, bool)
            and math.isfinite(_val)
        ):
            merged[_key] = _val
        elif _key in loaded:
            _cfg_log.getLogger(__name__).warning(
                "_load_live_config: %s has a non-numeric %s (%r) — using default %s",
                _LIVE_CONFIG_PATH,
                _key,
                _val,
                _default_val,
            )
    for _key, _val in loaded.items():
        if _key not in _LIVE_CONFIG_DEFAULT:
            merged[_key] = _val
    return merged


def _resolve_price(client: KalshiClient, ticker: str, side: str) -> float | None:
    """
    Fetch the best available price for a ticker+side.
    Returns None if no live quote exists — caller should prompt the user.
    """
    try:
        market = client.get_market(ticker)
        prices = parse_market_price(market)
        # NO entry is at no_ask = 1 - yes_bid, not the raw API no_bid
        # (= 1 - yes_ask, the price a NO *seller* receives) — same fix
        # applied elsewhere in weather_markets.py (search "L8-A / L2-A").
        p = (
            prices["yes_ask"]
            if side == "yes"
            else (1.0 - prices["yes_bid"] if prices["yes_bid"] > 0 else 0.0)
        )
        if p and p > 0:
            return p
        # Fall back to mid-price when no ask/bid is present
        mid = prices["implied_prob"]
        if mid and mid > 0:
            return mid if side == "yes" else 1 - mid
    except Exception as _e:
        logging.getLogger(__name__).debug(
            "_resolve_price: failed for %s/%s: %s", ticker, side, _e
        )
    return None


def _prompt_price() -> float | None:
    """Prompt for a price; loops on empty/invalid input, 'q' to cancel."""
    while True:
        raw = input(dim("  No live quote — enter price 0–1 (q to cancel): ")).strip()
        if raw.lower() == "q":
            return None
        if not raw:
            continue
        try:
            p = float(raw)
            if 0 < p < 1:
                return p
            print(red("  Price must be strictly between 0 and 1."))
        except ValueError:
            print(red("  Enter a decimal like 0.45"))


def _quick_paper_buy(client: KalshiClient) -> None:
    """Prompt to paper-buy a ticker directly after seeing analyze output."""
    if is_trading_paused():
        print(
            red(
                "  TRADING_PAUSED is set in .env — order placement is disabled.\n"
                "  Remove TRADING_PAUSED to resume trading."
            )
        )
        return
    try:
        while True:
            raw = input(dim("\n  Quick paper buy — ticker (q to skip): ")).strip()
            if raw.lower() == "q":
                return
            if raw:
                ticker = raw.upper()
                break
        # backlog.txt "RAIN / SNOW / HURRICANE MARKETS": this path is
        # reachable without going through analyze_trade() or cmd_order first
        # (review-caught, Snow Step 2 -- the maker-order branch below can
        # place a REAL live order, and check_position_limits()'s own
        # exception path deliberately fails open, so this was the one
        # unguarded path to a live order for these ticker families). Same
        # explicit refuse-outright guards as cmd_order's own, not just
        # reliance on check_position_limits(). Round-2 review caught that
        # this reasoning is ticker-family-agnostic, and applies MOST
        # sharply to rain -- unlike hurricane/snow, rain's shadow gate is
        # live and accumulating real settled predictions today, so this is
        # not a theoretical gap for it.
        if is_hurricane_count_ticker(ticker) and not _hurricane_count_gates_active():
            print(
                red(
                    f"  {ticker}: hurricane season-count markets are shadow-only until "
                    "HURRICANE_TRADING_ENABLED=1 and >=20 settled hurricane-count "
                    "predictions exist — refusing to place this order."
                )
            )
            return
        if (
            is_hurricane_next_event_ticker(ticker)
            and not _hurricane_next_event_gates_active()
        ):
            print(
                red(
                    f"  {ticker}: hurricane time-to-next-event markets are shadow-only "
                    "until HURRICANE_NEXT_EVENT_TRADING_ENABLED=1 and >=20 settled "
                    "predictions exist — refusing to place this order."
                )
            )
            return
        if is_holiday_temp_ticker(ticker) and not _holiday_temp_gates_active():
            print(
                red(
                    f"  {ticker}: holiday temperature markets are shadow-only until "
                    "HOLIDAY_TEMP_TRADING_ENABLED=1 and >=20 settled predictions "
                    "exist — refusing to place this order."
                )
            )
            return
        if (
            is_rain_daily_ticker(ticker)
            or is_rain_weekend_ticker(ticker)
            or is_rain_holiday_ticker(ticker)
        ):
            print(
                red(
                    f"  {ticker}: daily/weekend/holiday rain markets are "
                    "track-only — no probability model is ever computed for "
                    "these tickers — refusing to place this order."
                )
            )
            return
        if is_storm_order_ticker(ticker) and not _storm_order_gates_active():
            print(
                red(
                    f"  {ticker}: hurricane storm-order markets are shadow-only until "
                    "STORM_ORDER_TRADING_ENABLED=1 and >=20 settled predictions "
                    "exist — refusing to place this order."
                )
            )
            return
        if (
            is_hurricane_ticker(ticker)
            and not is_hurricane_count_ticker(ticker)
            and not is_hurricane_next_event_ticker(ticker)
            and not is_storm_order_ticker(ticker)
        ):
            print(
                red(
                    f"  {ticker}: hurricane markets are not supported yet — refusing to place this order."
                )
            )
            return
        if (
            ticker.upper().startswith(tuple(_KXRAIN_MONTHLY_CITY))
            and not _rain_gates_active()
        ):
            print(
                red(
                    f"  {ticker}: monthly rain markets are shadow-only until RAIN_TRADING_ENABLED=1 "
                    "and >=20 settled rain predictions exist — refusing to place this order."
                )
            )
            return
        if (
            ticker.upper().startswith(tuple(_KXSNOW_MONTHLY_CITY))
            and not _snow_gates_active()
        ):
            print(
                red(
                    f"  {ticker}: monthly snow markets are shadow-only until SNOW_TRADING_ENABLED=1 "
                    "and >=20 settled snow predictions exist — refusing to place this order."
                )
            )
            return
        # batch-52 H-2 (opus review): _hourly_live_ok also excludes Miami
        # specifically -- see its own docstring in weather_markets.py.
        if ticker.upper().startswith(
            tuple(_KXTEMP_HOURLY_CITY)
        ) and not _hourly_live_ok(ticker):
            print(
                red(
                    f"  {ticker}: hourly-directional temperature markets are shadow-only "
                    "until HOURLY_TRADING_ENABLED=1 and >=20 settled hourly predictions "
                    "exist — refusing to place this order."
                )
            )
            return
        # batch-40 "Between-bracket calibration design", Decision 2: same
        # explicit refuse-outright treatment as the families above, keeping
        # this path fail-closed even if check_position_limits' own call
        # raises rather than returning ok=False. is_between_bracket_ticker
        # classifies by the "-B<val>" suffix, not a prefix, since between
        # shares its ticker family with above/below.
        if is_between_bracket_ticker(ticker) and not _between_metar_gates_active():
            print(
                red(
                    f"  {ticker}: between-bracket markets are shadow-only until "
                    "BETWEEN_TRADING_ENABLED=1 and >=20 settled between-bracket "
                    "predictions exist — refusing to place this order."
                )
            )
            return
        while True:
            side = (
                input(dim(f"  Side for {ticker} (yes/no, q to cancel): "))
                .strip()
                .lower()
            )
            if side == "q":
                return
            if side in ("yes", "no"):
                break
        price = _resolve_price(client, ticker, side)
        if price is None:
            price = _prompt_price()
        if price is None:
            return
        # Order type prompt: market taker vs limit maker
        print(
            dim(
                "  Order type: (1) Market taker [7% fee]  "
                "(2) Limit maker [0% fee, may not fill]"
            )
        )
        order_type_raw = input(dim("  Choose (1/2, default 1): ")).strip()
        use_maker = order_type_raw == "2"
        maker_price: float | None = None
        if use_maker:
            # Suggest mid as limit price
            try:
                mkt = client.get_market(ticker)
                prices_mk = parse_market_price(mkt)
                suggested = prices_mk["mid"]
                if suggested <= 0:
                    suggested = price
            except Exception:
                suggested = price
            maker_raw = input(
                dim(f"  Limit price (Enter for mid {suggested:.3f}): ")
            ).strip()
            if maker_raw:
                try:
                    maker_price = float(maker_raw)
                    if not 0 < maker_price < 1:
                        print(red("  Invalid price — using market order."))
                        use_maker = False
                except ValueError:
                    print(red("  Invalid price — using market order."))
                    use_maker = False
            else:
                maker_price = suggested

        raw_qty = input(dim("  Qty (Enter for Kelly auto-size): ")).strip()
        qty_arg = [raw_qty] if raw_qty.isdigit() and int(raw_qty) > 0 else []
        thesis_raw = input(dim("  Why? (optional thesis, Enter to skip): ")).strip()
        thesis = thesis_raw if thesis_raw else None
        # Check streak/daily loss halt before proceeding
        try:
            from paper import is_daily_loss_halted, is_streak_paused

            # Pass client so this includes unrealized MTM on open positions,
            # matching trading_gates.py's check (2026-07-09) -- otherwise this
            # halt is blind to positions currently underwater but not settled.
            if is_daily_loss_halted(client):
                from paper import get_daily_pnl

                daily_pnl = get_daily_pnl(client)
                print(
                    red(
                        f"  Daily loss limit reached (${daily_pnl:.2f} today). Trading halted."
                    )
                )
                return
            # Opus-review-caught (L2): pass client here too, same reasoning
            # as is_daily_loss_halted just above -- otherwise this warning
            # stays blind to a real live streak.
            if is_streak_paused(client):
                print(yellow("  Warning: on a 3+ loss streak — Kelly is halved."))
        except Exception:
            pass
        # Place order directly with thesis
        try:
            qty = int(qty_arg[0]) if qty_arg else None
            # #2: resolve city/target_date unconditionally (not just on the
            # auto-Kelly path) so check_position_limits below can enforce the
            # city/date, directional, and correlated-group exposure caps on
            # explicit-qty manual orders too — previously only the auto-sizing
            # path (portfolio_kelly_fraction) ever saw these caps at all.
            city: str | None = None
            tdate_str: str | None = None
            _enriched_for_limits: dict | None = None
            _market_for_limits: dict | None = None
            # AUD-0010: only ever assigned inside the qty-is-None (auto-Kelly)
            # branch below -- initialized here so the maker-order branch can
            # safely reference it for entry_prob bookkeeping regardless of
            # whether the user supplied an explicit qty.
            analysis: dict | None = None
            try:
                from weather_markets import enrich_with_forecast as _ewf_limits

                _market_for_limits = client.get_market(ticker)
                _enriched_for_limits = _ewf_limits(
                    _market_for_limits, fetch_forecast=False
                )
                city = _enriched_for_limits.get("_city")
                _tdate_for_limits = _enriched_for_limits.get("_date")
                tdate_str = _tdate_for_limits.isoformat() if _tdate_for_limits else None
            except Exception:
                pass  # best-effort — city/date-scoped caps just get skipped below

            if qty is None:
                from paper import (
                    consensus_fraction_cap,
                    kelly_quantity,
                    portfolio_kelly_fraction,
                )
                from weather_markets import analyze_trade
                from weather_markets import enrich_with_forecast as _ewf_kelly

                try:
                    if _market_for_limits is None:
                        raise ValueError("market enrichment unavailable")
                    # 2026-07-09 follow-up: analyze_trade() hard-gates on
                    # _forecast being truthy (returns None otherwise). The
                    # city/date enrichment above is fetch_forecast=False (a
                    # cheap parse-only call for check_position_limits), so
                    # it can't be reused here — that made this branch always
                    # compute qty=0. Fetch a real forecast-bearing enrichment.
                    enriched = _ewf_kelly(_market_for_limits)
                    analysis = analyze_trade(enriched)
                    fee_kelly = (
                        analysis.get("ci_adjusted_kelly", 0.0) if analysis else 0.0
                    )
                    adj_kelly = portfolio_kelly_fraction(
                        fee_kelly, city, tdate_str, side=side, client=client
                    )
                    # 2nd-round-opus-review-caught (H-A): this is the ONLY
                    # place that actually sizes the maker-order branch's real
                    # live order (client.place_maker_order below) -- the
                    # is_streak_paused(client) warning above was cosmetic
                    # without this, the exact H1 bug shape at a call site H1
                    # missed.
                    qty = kelly_quantity(
                        adj_kelly,
                        price,
                        client=client,
                        fraction_cap=consensus_fraction_cap(analysis),
                    )
                except Exception:
                    qty = 0

            # Shared pre-trade checks (position limits + large-bet confirm) —
            # applies to BOTH the real-money maker path and the paper taker
            # path below. Previously the maker branch placed its order and
            # returned before either check ran, letting a live maker order
            # bypass every city/date, directional, and correlated-group
            # exposure cap despite the comment above claiming otherwise.
            if qty and qty > 0:
                _price_for_checks = (
                    maker_price if (use_maker and maker_price is not None) else price
                )
                try:
                    from paper import check_position_limits as _cpl

                    _limit_check = _cpl(
                        ticker,
                        qty,
                        _price_for_checks,
                        city=city,
                        target_date_str=tdate_str,
                        side=side,
                        client=client,
                    )
                    if not _limit_check.get("ok", True):
                        print(
                            red(
                                f"  Position limit check failed: {_limit_check.get('reason', 'limit exceeded')}"
                            )
                        )
                        return
                except Exception as _limit_exc:
                    # Silent before 2026-07-09 -- if check_position_limits()
                    # itself raised (e.g. a corrupt paper_trades.json), the
                    # limit check silently no-opped with no trace. Still
                    # allows the order through on error (fail open, matching
                    # this call site's existing behavior), but now visible.
                    _log.warning(
                        "check_position_limits failed for %s, skipping limit check: %s",
                        ticker,
                        _limit_exc,
                    )

                from paper import get_balance as _gb_qpb

                _cost_qpb = qty * _price_for_checks
                _balance_qpb = _gb_qpb()
                if _balance_qpb > 0 and _cost_qpb > _balance_qpb * 0.03:
                    _pct_qpb = _cost_qpb / _balance_qpb * 100
                    _confirm_large = (
                        input(
                            yellow(
                                f"  Heads up: this bet is ${_cost_qpb:.2f} ({_pct_qpb:.1f}% of your ${_balance_qpb:.2f} balance). "
                                f"Continue? (y/N): "
                            )
                        )
                        .strip()
                        .lower()
                    )
                    if _confirm_large != "y":
                        print(dim("  Cancelled."))
                        return

            # Maker order (real order, not paper) — only if qty is specified
            if use_maker and maker_price is not None and qty and qty > 0:
                # Gate on the client's own base_url, not a KALSHI_ENV read —
                # see trading_gates.LiveTradingGate.check()'s docstring: a
                # separate env-var read here could disagree with the gate's
                # own notion of prod-ness if they came from different
                # sources. Passing `client` through removes that entirely.
                # `!= DEMO_BASE` (not `== PROD_BASE`) so a client missing
                # base_url entirely defaults to requiring the gate rather
                # than silently skipping it (2026-07-09 follow-up review).
                from kalshi_client import DEMO_BASE

                if getattr(client, "base_url", None) != DEMO_BASE:
                    from trading_gates import pre_live_trade_check

                    try:
                        pre_live_trade_check(client)
                    except RuntimeError as _gate_err:
                        print(red(f"  Live trading gate blocked: {_gate_err}"))
                        return
                    # Batch-22 item 1 (adjacency, confirmed via
                    # AskUserQuestion): this branch is a second manual live-
                    # order path with the exact same gate-coverage gap
                    # cmd_order had -- _place_live_order (the automated live
                    # path) gates every entry on daily live loss, daily live
                    # spend, and max open live positions, but this path had
                    # none of the three. Always a BUY (this whole function is
                    # "quick paper buy"), so no buy/sell scoping needed --
                    # mirrors cmd_order's own gate order exactly.
                    import execution_log as _execution_log_qpb

                    _live_cfg_qpb = _load_live_config()
                    if _execution_log_qpb.get_today_live_loss() >= _live_cfg_qpb.get(
                        "daily_loss_limit", float("inf")
                    ):
                        print(
                            red(
                                f"  Daily live loss limit ${_live_cfg_qpb.get('daily_loss_limit', 'inf')} "
                                "reached — refusing to place this order."
                            )
                        )
                        return
                    from utils import MAX_DAILY_SPEND as _MAX_DAILY_SPEND_QPB

                    if (
                        _execution_log_qpb.get_today_live_spend()
                        >= _MAX_DAILY_SPEND_QPB
                    ):
                        print(
                            red(
                                f"  Daily live spend cap ${_MAX_DAILY_SPEND_QPB:.0f} reached — "
                                "refusing to place this order."
                            )
                        )
                        return
                    _max_open_qpb = _live_cfg_qpb.get("max_open_positions", 10)
                    if order_executor._count_open_live_orders() >= _max_open_qpb:
                        print(
                            red(
                                f"  Max open live positions {_max_open_qpb} reached — "
                                "refusing to place this order."
                            )
                        )
                        return
                # AUD-0010: this places a REAL live order via place_maker_order
                # (client.place_order under the hood) -- pre-log BEFORE the API
                # call, same as every other live-order call site in the repo
                # (order_executor._place_live_order, main.cmd_order), so a crash
                # between here and the response leaves a 'pending' row
                # _recover_pending_orders can reconcile, instead of the prior
                # zero-bookkeeping behavior that left a real position invisible
                # to every dedup guard and protective-exit scanner.
                from execution_log import log_order, log_order_result

                # Opus review follow-up (HIGH): mirrors cmd_order's own
                # _is_live computation exactly (main.py:4647) -- this branch
                # is reachable with a DEMO_BASE client too (the gate check
                # above only SKIPS the gate for demo, it doesn't block
                # placement), so hardcoding live=True would mark a demo-
                # environment rehearsal order live=1 in the single shared
                # execution_log DB: it would count against the real daily
                # live-spend cap, a prod `watch --live` session would poll a
                # demo order_id against prod every cycle, and if it somehow
                # resolved to 'filled' the live exit scanner could place a
                # REAL prod SELL for a position that only ever existed on
                # demo.
                _qpb_is_live = getattr(client, "base_url", None) != DEMO_BASE
                # Opus review follow-up: cmd_order warns explicitly when a
                # live buy will have no close_time (main.py ~4777); this
                # branch had no equivalent warning for either gap, and it
                # has TWO independent ways to end up with zero automated
                # exit coverage: no close_time (positions._passes_exit_gates
                # fails CLOSED -- never exits via stop-loss/breakeven) and
                # no entry_prob (order_executor._check_live_model_exits
                # skips any position with entry_prob is None). entry_prob is
                # only ever computed on the auto-Kelly (qty=None) path
                # above, so any explicit-qty maker order silently has none.
                if _qpb_is_live:
                    _qpb_close_time = (
                        _market_for_limits.get("close_time")
                        or _market_for_limits.get("expiration_time")
                        if _market_for_limits
                        else None
                    )
                    _qpb_entry_prob = (
                        analysis.get("forecast_prob") if analysis else None
                    )
                    if _qpb_close_time is None or _qpb_entry_prob is None:
                        print(
                            yellow(
                                "  [Warning] This live position will be missing "
                                + (
                                    "close_time and entry_prob"
                                    if _qpb_close_time is None
                                    and _qpb_entry_prob is None
                                    else "close_time"
                                    if _qpb_close_time is None
                                    else "entry_prob"
                                )
                                + " -- the automated stop-loss/breakeven and/or "
                                "model-exit scanner will never manage it. "
                                "Monitor and close it manually if needed."
                            )
                        )
                # Minute-bucketed pseudo-cycle so a quick manual retry after a
                # lost response dedups server-side instead of generating a
                # fresh random UUID (place_maker_order's default) and
                # silently double-placing (2026-07-09). Deliberately NOT
                # derived from ticker/side/price/qty alone -- that would
                # dedup across the market's whole life and swallow a
                # legitimate re-place after a cancel. Computed here (before
                # the pre-log, not inside the try below) so the
                # client_order_id pre-computed from it matches exactly what
                # place_maker_order -> place_order will derive internally.
                _maker_cycle = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M")
                # Batch-22 item 2 (adjacency): pre-computed and stored BEFORE
                # the API call, same reasoning as cmd_order's own fix -- a
                # crash between this pre-log and the log_order_result calls
                # below otherwise leaves a row _recover_pending_orders can't
                # reconcile. place_maker_order is a thin place_order()
                # wrapper (action="buy", same idempotency formula).
                _qpb_cid = compute_client_order_id(
                    ticker,
                    side,
                    "buy",
                    qty,
                    maker_price,
                    "good_till_canceled",  # matches place_maker_order's own fixed value
                    _maker_cycle,
                )
                _qpb_log_id = log_order(
                    ticker,
                    side,
                    qty,
                    maker_price,
                    order_type="limit",
                    status="pending",
                    live=_qpb_is_live,
                    response={"client_order_id": _qpb_cid},
                    close_time=(
                        (
                            _market_for_limits.get("close_time")
                            or _market_for_limits.get("expiration_time")
                        )
                        if _market_for_limits
                        else None
                    ),
                    entry_prob=(analysis.get("forecast_prob") if analysis else None),
                    forecast_cycle=order_executor._current_forecast_cycle(),
                )
                try:
                    result = client.place_maker_order(
                        ticker, side, maker_price, qty, cycle=_maker_cycle
                    )
                except OrderStatusUnknownError as _unk_e:
                    # AUD-0007: reconciliation itself couldn't confirm either
                    # way -- 'unknown', not 'failed', so dedup keeps blocking
                    # a retry and _recover_pending_orders re-checks it later.
                    log_order_result(
                        _qpb_log_id,
                        status="unknown",
                        error=str(_unk_e),
                        response={"client_order_id": _unk_e.client_order_id},
                    )
                    print(red(f"  Maker order outcome unknown: {_unk_e}"))
                    return
                except Exception as e:
                    log_order_result(_qpb_log_id, status="failed", error=str(e))
                    print(red(f"  Maker order failed: {e}"))
                    return

                # Opus review follow-up (AUD-0007, round 2): moved out of
                # the try above -- if this bookkeeping write itself raised
                # (e.g. a locked DB) after a genuinely successful placement,
                # the except block would have wrongly marked a REAL live
                # order 'failed'. Round 2 caught that an unhandled exception
                # here would now surface as a raw traceback to the operator
                # instead (this function's own enclosing handlers are
                # `except ValueError` and `except (KeyboardInterrupt,
                # EOFError)`, neither of which is a generic catch-all) --
                # caught locally instead: the pre-logged 'pending' row with
                # no order_id is already handled safely by
                # _recover_pending_orders' existing no-order_id branch.
                # Kalshi's real status enum is resting/canceled/executed --
                # a resting maker order (the common case) translates to
                # None via _kalshi_status_to_internal, defaulting to
                # "pending" -- same established convention as cmd_order's
                # live path and _place_live_order.
                order = result.get("order", result)
                _qpb_filled = (
                    order_executor._to_fill_count(order.get("fill_count_fp")) or 0
                )
                _qpb_status = (
                    order_executor._kalshi_status_to_internal(
                        order.get("status", ""), _qpb_filled
                    )
                    or "pending"
                )
                try:
                    log_order_result(
                        _qpb_log_id,
                        status=_qpb_status,
                        response=order,
                        fill_quantity=_qpb_filled,
                    )
                except Exception as _qpb_bk_exc:
                    print(
                        yellow(
                            "  [Warning] Order placed on exchange but local "
                            f"bookkeeping failed: {_qpb_bk_exc} — check "
                            "execution_log manually."
                        )
                    )
                print(
                    green(
                        f"  Maker limit order placed: {order.get('order_id', '')}  "
                        f"@ ${maker_price:.3f}  ({qty} contracts)"
                    )
                )
                print(
                    dim(
                        "  Order rests in book — will fill only if market moves to your price."
                    )
                )
                return

            if qty and qty > 0:
                from paper import place_paper_order as _ppo_qpb  # noqa: F811

                # opus-review-caught: city/target_date (already derived
                # above for the position-limit check) were never passed
                # through here, leaving the new target_date-freshness guard
                # inert on this path AND (pre-existing, same root cause)
                # every such trade permanently invisible to city/date
                # exposure sums and _multiday_date_counts.
                trade = _ppo_qpb(
                    ticker,
                    side,
                    qty,
                    price,
                    city=city,
                    target_date=tdate_str,
                    thesis=thesis,
                )
                print(green(f"  Paper trade #{trade['id']} placed."))
                # #110: audit trail — record every manual paper buy
                try:
                    from tracker import log_audit

                    log_audit(
                        "manual_buy",
                        ticker=ticker,
                        side=side,
                        price=price,
                        qty=qty,
                        thesis=thesis,
                    )
                except Exception:
                    pass
            else:
                cmd_paper(["buy", ticker, side, f"{price:.3f}"] + qty_arg, client)
        except ValueError as e:
            print(red(f"  Error: {e}"))
    except (KeyboardInterrupt, EOFError):
        print()


def _feature_importance_days_out(target_date_str: str | None, city: str | None) -> int:
    """How many days out a trade was placed, for feature-importance logging.

    target_date_str is an ISO date string (weather_markets.py's analyze_trade
    return dict stores target_date.isoformat(), not a date object) -- must be
    parsed before arithmetic, not subtracted directly. Returns 0 if absent or
    unparseable. target_date is CITY-LOCAL (parse_city_date()), not UTC, so
    "today" here must be too -- mirrors analyze_trade's own local-today fix
    (weather_markets.py) rather than utils.utc_today(), which would be wrong
    for the ~4-8h evening window where UTC's calendar date has already rolled
    over but the city's has not.
    """
    if not target_date_str:
        return 0
    try:
        from zoneinfo import ZoneInfo as _ZoneInfoFi

        _today_fi = datetime.now(
            _ZoneInfoFi(_CITY_TZ.get(city or "", "America/New_York"))
        ).date()
    except Exception:
        _log.warning(
            "_feature_importance_days_out: ZoneInfo unavailable for city=%s — "
            "falling back to UTC date",
            city,
        )
        _today_fi = datetime.now(UTC).date()

    try:
        return (date.fromisoformat(target_date_str) - _today_fi).days
    except (ValueError, TypeError):
        return 0


def cmd_today(client: KalshiClient) -> None:
    """Show a plain-English 'what should I do today?' recommendation."""
    from paper import consensus_fraction_cap, get_balance, kelly_bet_dollars

    # Maker fee (not taker): live/paper entries are always resting midpoint
    # GTC limit orders, which pay $0 on this bot's markets (see
    # KALSHI_MAKER_FEE_RATE).
    from utils import KALSHI_MAKER_FEE_RATE as _fee

    print(bold("\n  ── Today's Recommendation ──\n"))
    print(dim("  Scanning markets for the best opportunity...\n"))

    try:
        markets = get_weather_markets(client)
    except Exception as e:
        print(red(f"  Could not load markets: {e}"))
        return

    # Pre-warm the forecast cache in one batch before the per-market loop.
    # No-op if the cache is already warm from a recent cron run.
    _city_dates: set[tuple[str, str]] = set()
    for _m in markets:
        _city, _td = parse_city_date(_m)
        if _city and _td:
            _city_dates.add((_city, str(_td)))
    batch_prewarm_forecasts(_city_dates)

    # Pre-load 30yr climatology for all cities — downloads once, cached to disk
    # for 1 year. Silent if already cached; prints progress only on first download.
    from climatology import preload_all as _clim_preload

    _clim_preload(CITY_COORDS)

    # Collect top 3 candidates sorted by abs(net_edge) descending
    top_picks: list[tuple[dict, dict]] = []  # (enriched_market, analysis)
    for m in markets:
        enriched = enrich_with_forecast(m)
        analysis = analyze_trade(enriched)
        if not analysis:
            continue
        net_edge = analysis.get("net_edge", analysis["edge"])
        if abs(net_edge) < MIN_EDGE:
            continue
        if not is_liquid(m):
            continue
        if analysis.get("time_risk") == "HIGH":
            continue
        if int(analysis.get("days_out", 1)) == 0:
            continue
        # Market divergence gates (matches cron.py's cmd_cron parity,
        # backlog.txt "WATCH/_analyze_once IS MISSING cron.py's
        # MIN_MARKET_PROB_TO_BET_WITH / MAX_MARKET_DIVERGENCE_RATIO
        # DIRECTIONAL-CONSENSUS GATES") -- see _analyze_once's identical
        # block for the full rationale.
        from utils import MAX_MARKET_DIVERGENCE_RATIO, MIN_MARKET_PROB_TO_BET_WITH

        _side = analysis.get("recommended_side", "yes")
        _our_p = analysis.get("forecast_prob", 0.5)
        _mkt_p = analysis.get("market_prob", 0.5)
        if _side == "yes":
            _mkt_dir = _mkt_p
            _our_dir = _our_p
        else:
            _mkt_dir = 1.0 - _mkt_p
            _our_dir = 1.0 - _our_p
        if _mkt_dir < MIN_MARKET_PROB_TO_BET_WITH:
            continue
        if _mkt_dir > 0 and _our_dir / _mkt_dir > MAX_MARKET_DIVERGENCE_RATIO:
            continue
        top_picks.append((enriched, analysis))
        top_picks.sort(
            key=lambda x: abs(x[1].get("net_edge", x[1]["edge"])), reverse=True
        )
        top_picks = top_picks[:3]

    if not top_picks:
        print(yellow("  No strong opportunities today. Consider waiting."))
        return

    best_m, best_a = top_picks[0]

    def _pick_display(
        enriched: dict, analysis: dict, balance: float, label: str, prices: dict
    ) -> None:
        """Print full detail block for one pick.

        prices: the already-parsed price book to render from. Required, not
        defaulted to parse_market_price(enriched) -- this has exactly one
        caller (the #1 pick, passing its freshly re-fetched quote), so a
        default would be dead code, and the whole point of threading the
        book in is that the detail block and the placement prompt directly
        beneath it must quote the SAME number. A default would silently
        reintroduce the two-prices-on-one-screen split the moment a second
        caller forgot to pass one. The compact runner-up lines further down
        do not come through here at all.
        """
        _ticker = enriched.get("ticker", "")
        _title = enriched.get("title") or _ticker
        _net_edge = analysis.get("net_edge", analysis["edge"])
        _prob_edge = analysis.get("edge", _net_edge)
        _forecast_prob = analysis["forecast_prob"]
        _market_prob = analysis["market_prob"]
        _side = analysis["recommended_side"]
        _time_risk = analysis.get("time_risk", "—")
        _consensus = analysis.get("consensus", "")
        _regime_desc = analysis.get("regime_description", "")
        _n_members = analysis.get("n_members", 0)
        _ci_kelly = analysis.get(
            "ci_adjusted_kelly", analysis.get("fee_adjusted_kelly", 0.0)
        )
        # Batch-60 item 3 (backlog.txt "cmd_today's interactive '[P] Place'
        # flow books the actual paper trade at the bid-ask MID"): this was
        # the mid, correctly side-flipped but never ask-based, so the
        # "If correct: win $X" figure below understated entry cost by half
        # the spread -- the same defect the booking price below had, in the
        # display the operator reads before deciding.
        _entry_price = _side_aware_entry_price(_side, prices)

        _bet_dollars = kelly_bet_dollars(
            _ci_kelly, client=client, fraction_cap=consensus_fraction_cap(analysis)
        )
        _win_per_dollar = (1 - _entry_price) * (1 - _fee)
        _if_correct = (
            round(_bet_dollars / _entry_price * _win_per_dollar, 2)
            if _entry_price > 0 and _bet_dollars > 0
            else 0.0
        )

        _why_parts: list[str] = []
        if _n_members > 0:
            _why_parts.append(f"Our ensemble of {_n_members} weather models")
        if _regime_desc and isinstance(_regime_desc, str):
            _why_parts.append(_regime_desc)
        if _consensus and isinstance(_consensus, str):
            _why_parts.append(_consensus)
        if not _why_parts:
            _why_parts.append("Our weather forecast models")
        _why = ". ".join(_why_parts)

        if abs(_net_edge) >= 0.25 and _time_risk == "LOW":
            _confidence = green("HIGH (all sources agree — consensus signal)")
        elif abs(_net_edge) >= 0.15:
            _confidence = yellow("MEDIUM")
        else:
            _confidence = dim("MODERATE")

        _risk_label = (
            green("LOW")
            if _time_risk == "LOW"
            else (yellow("MEDIUM") if _time_risk != "HIGH" else red("HIGH"))
        )

        print(f"  {bold(label)}")
        print(f"  Market:   {bold(_ticker)}")
        print(f"  Question: {_title}")
        print()
        print(f"  Our model:   {bold(f'{_forecast_prob:.0%}')} chance of YES")
        print(f"  Market says: {bold(f'{_market_prob:.0%}')} chance of YES")
        _disp_edge = _prob_edge if _side == "yes" else -_prob_edge
        _edge_str = (
            green(f"+{_disp_edge:.0%}") if _disp_edge > 0 else red(f"{_disp_edge:.0%}")
        )
        _roi_str = (
            green(f"+{_net_edge:.0%}") if _net_edge > 0 else red(f"{_net_edge:.0%}")
        )
        print(
            f"  Your edge:   {_edge_str} probability gap  ({_roi_str} expected ROI after fees)"
        )
        print()
        print(
            f"  Recommendation: BUY {bold(_side.upper())} at {bold(f'{_entry_price:.0%}')} per contract"
        )
        # Opus round-2 review (L4): the price above now comes from a quote
        # re-fetched at prompt time, while "Market says", "Your edge" and
        # the ROI figure all still come from the scan-time analysis. Before
        # the re-fetch all four moved together. If the book has moved since
        # the scan, say so rather than letting the operator read an edge
        # that no longer exists next to the price they will actually pay.
        # Deliberately NOT recomputing the edge here: net_edge is
        # fee-adjusted by the analysis pipeline, and hand-rolling a
        # replacement in a display function is how the mid-vs-ask defect
        # this batch is fixing got introduced in the first place.
        _fresh_mid = prices.get("implied_prob")
        if _fresh_mid is not None and abs(_fresh_mid - _market_prob) >= 0.02:
            print(
                yellow(
                    f"  [Note] The book moved to {_fresh_mid:.0%} since this scan "
                    f"(analysis used {_market_prob:.0%}) — the price above is "
                    "current, the edge and ROI above are not."
                )
            )
        print()
        print(f"  Why: {_why}")
        print()
        if _bet_dollars > 0:
            _pct_bal = _bet_dollars / balance * 100 if balance > 0 else 0
            print(
                f"  Suggested bet: {green(f'${_bet_dollars:.2f}')} (Kelly sizing, {_pct_bal:.1f}% of your ${balance:.0f} balance)"
            )
            print(f"  If correct: win {green(f'${_if_correct:.2f}')} after fees")
            print(f"  If wrong:   lose {red(f'${_bet_dollars:.2f}')}")
        else:
            print(
                dim(
                    "  Suggested bet: Kelly sizing unavailable — drawdown guard may be active"
                )
            )
        print()
        print(f"  Risk level:  {_risk_label}")
        print(f"  Confidence:  {_confidence}")
        print()

    balance = get_balance()

    from paper import kelly_quantity
    from paper import place_paper_order as _ppo_today  # noqa: F811
    from utils import MAX_DAILY_SPEND

    _ticker1 = best_m.get("ticker", "")
    _side1 = best_a["recommended_side"]

    # Batch-60 item 3: the price the #1 pick is DISPLAYED and BOOKED at.
    # Two separate defects fixed here:
    #   1. it was the bid-ask mid (best_a["market_prob"], side-flipped but
    #      never ask-based), so a placed paper trade recorded a price the
    #      operator could not have gotten -- optimistically biasing the very
    #      paper corpus the live-trading graduation gate reads. Now routed
    #      through _side_aware_entry_price, the same helper cmd_market uses
    #      and the CLI counterpart of the frontend's sideAwareEntryPrice.
    #   2. the quote came from the scan loop above, which can be minutes old
    #      by the time this prompt is answered. Re-fetched once here, BEFORE
    #      the detail block is printed, so the projection, the suggested
    #      contract count, and the booked price are all the same number --
    #      mirrors order_executor.py's own "L1-B: Re-fetch live price before
    #      placement" convention. Deliberately resolved ahead of
    #      _pick_display rather than inside it: only the #1 pick is worth an
    #      extra API call, and splitting the re-fetch across the two would
    #      show two different prices for one contract on the same screen.
    # The re-fetch is best-effort: a failed call, or one returning a market
    # with no real quote, falls back to the scan-time book rather than
    # blocking the placement entirely.
    #
    # The emptiness test is parse_market_price's own has_quote (mid > 0),
    # NOT "the derived entry price is > 0" -- opus-review-caught (F1), and
    # the difference is a live-money-shaped bug in the NO direction. On an
    # all-zero book _side_aware_entry_price returns 0.0 for YES (so a
    # price-based test would correctly reject it) but for NO it falls
    # through to max(0.01, 1.0 - implied_prob) = 1.0, which passes any
    # `> 0` test. That would let a quote-less payload REPLACE a good
    # scan-time book and book the trade at $1.00 -- the maximum possible
    # entry price, a structurally-unwinnable position, and a worse
    # corruption of the graduation-gate corpus than the mid-pricing this
    # item exists to fix.
    _prices1 = parse_market_price(best_m)
    try:
        _fresh_m1 = client.get_market(_ticker1)
        if _fresh_m1:
            # Inside the try on purpose: parse_market_price coerces the
            # quote fields with float(), so a malformed payload raises here
            # rather than at the API call, and must fall back the same way.
            _fresh_prices1 = parse_market_price(_fresh_m1)
            if (
                _fresh_prices1["has_quote"]
                and _side_aware_entry_price(_side1, _fresh_prices1) > 0
            ):
                _prices1 = _fresh_prices1
    except Exception as _quote_err1:
        _log.warning(
            "cmd_today: fresh quote re-fetch failed for %s (%s) -- pricing "
            "from the scan-time book instead",
            _ticker1,
            _quote_err1,
        )
    _entry_price1 = _side_aware_entry_price(_side1, _prices1)

    # Does the book actually quote an ask on the side being BOUGHT? Opus
    # round-2 review (L5): _side_aware_entry_price is shared with
    # cmd_market's display, so when the side's own ask is missing it falls
    # back to a mid-derived estimate rather than refusing -- fine for a
    # sizing hint, wrong for a booking price. A one-sided book (yes_bid == 0
    # with a real yes_ask) therefore still booked a NO trade at
    # max(0.01, 1 - mid) instead of the true no_ask = 1 - yes_bid, keeping
    # exactly the mid-optimism item 3 exists to remove -- newly load-bearing
    # now that this helper sets the recorded price and not just a display.
    # Checked here rather than inside the helper so cmd_market's display
    # behaviour is untouched.
    _has_side_ask1 = (
        _prices1["yes_ask"] > 0 if _side1 == "yes" else _prices1["yes_bid"] > 0
    )

    # ── #1 Primary pick — full detail + placement prompt ─────────────────────
    _pick_display(best_m, best_a, balance, "#1 Best Pick", prices=_prices1)

    _ci_kelly1 = best_a.get("ci_adjusted_kelly", best_a.get("fee_adjusted_kelly", 0.0))
    _frac_cap1 = consensus_fraction_cap(best_a)
    _bet_dollars1 = kelly_bet_dollars(
        _ci_kelly1, client=client, fraction_cap=_frac_cap1
    )
    _qty1 = (
        kelly_quantity(
            _ci_kelly1, _entry_price1, client=client, fraction_cap=_frac_cap1
        )
        if _entry_price1 > 0
        else 0
    )

    try:
        raw = (
            input(
                dim(
                    f"  [P] Place {_side1.upper()} x{_qty1} ${_bet_dollars1:.2f}  [Enter] Skip: "
                )
            )
            .strip()
            .upper()
        )
    except (KeyboardInterrupt, EOFError):
        print()
        return

    if raw == "P":
        # Opus-review-caught (2026-08-03): this is the one interactive
        # placement path in main.py with NO gate check at all -- not
        # TRADING_PAUSED, not paper.check_position_limits() (city/date,
        # directional, correlated-group exposure caps), and not any of the
        # per-ticker-family shadow gates (_rain_gates_active/
        # _snow_gates_active/_hurricane_count_gates_active). cmd_order,
        # cmd_paper, and _quick_paper_buy all check both; this path fell
        # through the same "reachable without analyze_trade()" gap this
        # project has repeatedly found and fixed for those three (see
        # backlog.txt "HURRICANE MARKETS" and its own [[feedback_trace_all_
        # call_sites]]-shaped history) -- except here analyze_trade() DOES
        # run (best_a came from it above), so a shadow-only rain/snow/
        # hurricane-count ticker could still slip through: those markets'
        # own gates are enforced by check_position_limits()/the manual
        # order paths, not by analyze_trade() itself.
        #
        # Round-2 review caught that check_position_limits() alone is not
        # enough: cmd_order/cmd_paper/_quick_paper_buy all pair it with
        # direct refuse-outright guards for exactly this reason -- their own
        # comments say so explicitly ("check_position_limits()'s own
        # exception path deliberately fails open, so this direct guard is
        # not redundant"). Without these, a check_position_limits()
        # exception (its own shadow-gate checks run FIRST inside that
        # function, before the exposure-cap checks) fails open here too,
        # placing a real order on a shadow-only market. Added the same
        # checks, in the same order _quick_paper_buy/cmd_paper use (now eight:
        # trading-paused, hurricane-count, hurricane-next-event, storm-order,
        # blanket-other-hurricane, rain, snow, hourly-directional temperature --
        # grown one at a time as each new shape shipped its own shadow gate).
        if is_trading_paused():
            print(
                red(
                    "  TRADING_PAUSED is set in .env — order placement is disabled.\n"
                    "  Remove TRADING_PAUSED to resume trading."
                )
            )
        elif not _has_side_ask1:
            # See _has_side_ask1's own comment. Refusing is the only honest
            # option: with no ask on this side there is no price the
            # operator could actually have paid, so any number booked here
            # would be invented -- and both available inventions are known
            # to be wrong (the mid understates, and the 1.0 fallback is the
            # unwinnable-position bug F1 caught).
            print(
                red(
                    f"  {_ticker1}: no {'YES ask' if _side1 == 'yes' else 'NO ask'} "
                    "quoted on this market right now, so there is no real "
                    "price to book against — refusing to place this order."
                )
            )
        elif (
            is_hurricane_count_ticker(_ticker1) and not _hurricane_count_gates_active()
        ):
            print(
                red(
                    f"  {_ticker1}: hurricane season-count markets are shadow-only until "
                    "HURRICANE_TRADING_ENABLED=1 and >=20 settled hurricane-count "
                    "predictions exist — refusing to place this order."
                )
            )
        elif (
            is_hurricane_next_event_ticker(_ticker1)
            and not _hurricane_next_event_gates_active()
        ):
            print(
                red(
                    f"  {_ticker1}: hurricane time-to-next-event markets are "
                    "shadow-only until HURRICANE_NEXT_EVENT_TRADING_ENABLED=1 and "
                    ">=20 settled predictions exist — refusing to place this order."
                )
            )
        elif is_holiday_temp_ticker(_ticker1) and not _holiday_temp_gates_active():
            print(
                red(
                    f"  {_ticker1}: holiday temperature markets are shadow-only "
                    "until HOLIDAY_TEMP_TRADING_ENABLED=1 and >=20 settled "
                    "predictions exist — refusing to place this order."
                )
            )
        elif (
            is_rain_daily_ticker(_ticker1)
            or is_rain_weekend_ticker(_ticker1)
            or is_rain_holiday_ticker(_ticker1)
        ):
            print(
                red(
                    f"  {_ticker1}: daily/weekend/holiday rain markets are "
                    "track-only — no probability model is ever computed for "
                    "these tickers — refusing to place this order."
                )
            )
        elif is_storm_order_ticker(_ticker1) and not _storm_order_gates_active():
            print(
                red(
                    f"  {_ticker1}: hurricane storm-order markets are shadow-only "
                    "until STORM_ORDER_TRADING_ENABLED=1 and >=20 settled "
                    "predictions exist — refusing to place this order."
                )
            )
        elif (
            is_hurricane_ticker(_ticker1)
            and not is_hurricane_count_ticker(_ticker1)
            and not is_hurricane_next_event_ticker(_ticker1)
            and not is_storm_order_ticker(_ticker1)
        ):
            print(
                red(
                    f"  {_ticker1}: hurricane markets are not supported yet — refusing to place this order."
                )
            )
        elif (
            _ticker1.upper().startswith(tuple(_KXRAIN_MONTHLY_CITY))
            and not _rain_gates_active()
        ):
            print(
                red(
                    f"  {_ticker1}: monthly rain markets are shadow-only until RAIN_TRADING_ENABLED=1 "
                    "and >=20 settled rain predictions exist — refusing to place this order."
                )
            )
        elif (
            _ticker1.upper().startswith(tuple(_KXSNOW_MONTHLY_CITY))
            and not _snow_gates_active()
        ):
            print(
                red(
                    f"  {_ticker1}: monthly snow markets are shadow-only until SNOW_TRADING_ENABLED=1 "
                    "and >=20 settled snow predictions exist — refusing to place this order."
                )
            )
        # batch-52 H-2 (opus review): _hourly_live_ok also excludes Miami
        # specifically -- see its own docstring in weather_markets.py.
        elif _ticker1.upper().startswith(
            tuple(_KXTEMP_HOURLY_CITY)
        ) and not _hourly_live_ok(_ticker1):
            print(
                red(
                    f"  {_ticker1}: hourly-directional temperature markets are shadow-only "
                    "until HOURLY_TRADING_ENABLED=1 and >=20 settled hourly predictions "
                    "exist — refusing to place this order."
                )
            )
        elif _qty1 < 1 or _bet_dollars1 <= 0:
            print(yellow("  Kelly sizing produced 0 contracts — trade not placed."))
        elif _daily_paper_spend() + _bet_dollars1 > MAX_DAILY_SPEND:
            print(
                yellow(
                    f"  Daily spend cap would be exceeded (${_daily_paper_spend():.2f}/${MAX_DAILY_SPEND:.0f}). Trade not placed."
                )
            )
        else:
            try:
                from paper import check_position_limits as _cpl_today

                _limit_check_today = _cpl_today(
                    _ticker1,
                    _qty1,
                    _entry_price1,
                    city=best_m.get("_city"),
                    target_date_str=best_a.get("target_date"),
                    side=_side1,
                    client=client,
                )
            except Exception as _limit_exc_today:
                _limit_check_today = {"ok": True}
                _log.warning(
                    "cmd_today: check_position_limits failed for %s, skipping "
                    "limit check: %s",
                    _ticker1,
                    _limit_exc_today,
                )
            if not _limit_check_today.get("ok", True):
                # Round-2 review caught: no `return` here, unlike a hard
                # refusal -- every sibling branch above (and the placement-
                # exception branch below) falls through to the runner-ups
                # display rather than cutting it off, and there's no reason
                # this one should be the sole exception.
                print(
                    red(
                        f"  Position limit check failed: {_limit_check_today.get('reason', 'limit exceeded')}"
                    )
                )
            else:
                try:
                    trade = _ppo_today(
                        _ticker1,
                        _side1,
                        _qty1,
                        _entry_price1,
                        entry_prob=best_a["forecast_prob"],
                        net_edge=best_a.get("net_edge"),
                        city=best_m.get("_city"),
                        target_date=best_a.get("target_date"),
                        method=best_a.get("method"),
                        # Opus round-2 review (I2): without close_time,
                        # positions._passes_exit_gates fails CLOSED, so
                        # place_paper_order's own guard comment is literal --
                        # the row "permanently bypasses the 24h stop-loss/
                        # breakeven gates". Every cmd_today placement was
                        # landing in the ledger unmanageable by the automated
                        # protective-exit scanner. days_out likewise feeds the
                        # multi-day slot cap. Both were already in scope at
                        # this call site; only the thesis marker below was
                        # being added when this was spotted.
                        close_time=best_m.get("close_time"),
                        days_out=best_a.get("days_out"),
                        # Batch-60 item 3: makes this path's rows
                        # attributable in the paper corpus. Before this,
                        # a cmd_today placement was indistinguishable from
                        # a cron-placed one, so the mid-vs-ask fix above
                        # left a date boundary nothing recorded -- an audit
                        # could not tell which rows predated it. Mirrors
                        # web_app's own "manual approval via dashboard"
                        # thesis marker on its manual-placement path.
                        thesis="cmd_today interactive [P] place",
                    )
                    cost = round(_entry_price1 * _qty1, 2)
                    print(
                        green(
                            f"\n  ✓ Placed: BUY {_side1.upper()} x{_qty1} @ {_entry_price1:.0%} — cost ${cost:.2f}"
                        )
                    )
                    print(
                        dim(
                            f"  Trade ID: {trade.get('id', '?')}  |  Balance: ${get_balance():.2f}"
                        )
                    )
                    try:
                        from feature_importance import record_feature_contribution

                        # best_a["target_date"] is an ISO string (weather_markets.py's
                        # analyze_trade return dict stores target_date.isoformat()) --
                        # the previous `str - date.today()` here always raised
                        # TypeError, silently swallowed by the except below, so this
                        # call has likely never actually recorded a contribution.
                        _days_out_fi = _feature_importance_days_out(
                            best_a.get("target_date"), best_m.get("_city")
                        )
                        record_feature_contribution(
                            _ticker1,
                            {
                                "ensemble_spread": best_a.get("ensemble_spread", 0)
                                or 0,
                                "model_agreement": 1.0
                                if best_a.get("model_consensus")
                                else 0.0,
                                "days_out": _days_out_fi,
                                "edge": best_a.get("edge", 0) or 0,
                                "kelly_fraction": best_a.get("ci_adjusted_kelly", 0)
                                or 0,
                                "data_quality": best_a.get("data_quality", 0) or 0,
                                "near_threshold": 1.0
                                if best_a.get("near_threshold")
                                else 0.0,
                                "regime": 1.0
                                if best_a.get("regime")
                                in ("heat_dome", "cold_snap", "blocking_high")
                                else 0.0,
                            },
                        )
                    except Exception:
                        pass
                except Exception as e:
                    print(red(f"  Failed to place trade: {e}"))

    # ── Runner-ups #2 and #3 — compact one-liner each ────────────────────────
    if len(top_picks) > 1:
        print(dim("  ── Also consider ") + dim("─" * 44))
        for rank, (rm, ra) in enumerate(top_picks[1:], start=2):
            _rt = rm.get("ticker", "")
            _rs = ra["recommended_side"]
            # Batch-60 item 3, opus-review-caught (F3): the runner-ups are
            # rendered here, NOT through _pick_display, so they kept the
            # mid-based line after the #1 pick moved to the side-aware ask.
            # That put an ask and a mid side by side on one screen with
            # nothing marking them as different measures -- an operator
            # comparing "#1 BUY YES @ 44%" against "#2 BUY YES @ 42%" would
            # be comparing a price they can pay against one they can't.
            # No re-fetch here: unlike the #1 pick these are not placeable
            # from this screen, so the scan-time book is the right source
            # and three extra API calls per run would not be.
            _rep = _side_aware_entry_price(_rs, parse_market_price(rm))
            _rpe = ra.get("edge", 0)
            _rdisp = _rpe if _rs == "yes" else -_rpe
            _redge_s = green(f"+{_rdisp:.0%}") if _rdisp > 0 else red(f"{_rdisp:.0%}")
            _rtr = ra.get("time_risk", "—")
            _rrisk = (
                green("LOW")
                if _rtr == "LOW"
                else (yellow("MED") if _rtr != "HIGH" else red("HIGH"))
            )
            _rck = ra.get("ci_adjusted_kelly", ra.get("fee_adjusted_kelly", 0.0))
            _rbet = kelly_bet_dollars(
                _rck, client=client, fraction_cap=consensus_fraction_cap(ra)
            )
            _rbet_s = f"${_rbet:.0f}" if _rbet > 0 else "—"
            print(
                f"  #{rank}  {bold(_rt)}  BUY {_rs.upper()} @ {_rep:.0%}"
                f"  edge {_redge_s}  risk {_rrisk}  Kelly {_rbet_s}"
            )
        print()


def cmd_brief(client: KalshiClient, send_email: bool = False) -> None:
    """Daily briefing — fast single-screen summary."""
    from paper import (
        check_aged_positions,
        check_expiring_trades,
        check_model_exits,
        get_balance,
        get_current_streak,
        get_daily_pnl,
        get_open_trades,
        graduation_check,
    )

    now = datetime.now(UTC)
    _header(f"Daily Briefing — {now.strftime('%Y-%m-%d %H:%M')} UTC")

    # Balance + daily P&L + streak
    bal = get_balance()
    # client included so this reflects unrealized MTM on open positions, not
    # just trades settled today (see trading_gates.py's 2026-07-09 fix).
    daily_pnl = get_daily_pnl(client)
    pnl_s = (
        green(f"+${daily_pnl:.2f}")
        if daily_pnl >= 0
        else red(f"-${abs(daily_pnl):.2f}")
    )
    streak_kind, streak_n = get_current_streak()
    streak_s = (
        green(f"{streak_n} win streak")
        if streak_kind == "win"
        else red(f"{streak_n} loss streak")
        if streak_kind == "loss"
        else dim("no streak")
    )
    print(
        f"  Balance: {bold(f'${bal:.2f}')}  |  Today P&L: {pnl_s}  |  Streak: {streak_s}"
    )

    # ASCII balance history chart
    try:
        from paper import get_balance_history as _gbh_brief

        history = _gbh_brief()
        if len(history) >= 3:
            balances = [h["balance"] for h in history]
            print(_ascii_chart(balances, width=52, height=6, label="Balance"))
    except Exception:
        pass

    # Open positions + expiring
    open_trades = get_open_trades()
    expiring = check_expiring_trades()
    expiring_soon = [e for e in expiring if e["hours_left"] <= 24]
    print(f"\n  Open positions: {cyan(str(len(open_trades)))}", end="")
    if expiring_soon:
        print(f"  |  {yellow(f'{len(expiring_soon)} expiring within 24h')}", end="")
    print()

    # Top 3 opportunities
    print(bold("\n  ── Top Opportunities ──"))
    try:
        markets = get_weather_markets(client)
        _cd: set[tuple[str, str]] = set()
        for _m in markets:
            _c, _d = parse_city_date(_m)
            if _c and _d:
                _cd.add((_c, str(_d)))
        batch_prewarm_forecasts(_cd)
        from climatology import preload_all as _clim_preload_b

        _clim_preload_b(CITY_COORDS)
        analyzed = []
        for m in markets:
            try:
                enriched = enrich_with_forecast(m)
                analysis = analyze_trade(enriched)
                if (
                    analysis
                    and abs(analysis.get("net_edge", analysis["edge"])) >= MIN_EDGE
                ):
                    analyzed.append((enriched, analysis))
            except Exception:
                continue
        top3 = sorted(
            analyzed,
            key=lambda x: abs(x[1].get("net_edge", x[1]["edge"])),
            reverse=True,
        )[:3]
        if top3:
            for m, a in top3:
                _raw_edge = a.get("edge", 0.0)
                _side = a["recommended_side"]
                _disp_edge = _raw_edge if _side == "yes" else -_raw_edge
                edge_s = (
                    green(f"+{_disp_edge:.0%}")
                    if _disp_edge > 0
                    else red(f"{_disp_edge:.0%}")
                )
                ticker = m.get("ticker", "")
                side = _side.upper()
                print(
                    f"  {ticker:<32} {side:<4} {edge_s}  {dim(a.get('signal', '').strip())}"
                )
        else:
            print(dim("  No opportunities above threshold."))
    except Exception as e:
        print(yellow(f"  ⚠  Could not scan markets: {e}"))

    # Exit signals
    try:
        exits = check_model_exits(client)
        if exits:
            print(bold(f"\n  ── Exit Signals ({len(exits)}) ──"))
            for rec in exits:
                t = rec["trade"]
                reason = (
                    "MODEL FLIPPED" if rec["reason"] == "model_flipped" else "EDGE GONE"
                )
                print(yellow(f"  #{t['id']} {t['ticker']} — {reason}"))
    except Exception:
        pass

    # Graduation check
    grad = graduation_check()
    if grad:
        print(bold(f"\n  {green('GRADUATION CHECK PASSED')} — Ready for live trading!"))
        print(
            f"  {grad['settled']} trades  |  Win rate: {grad['win_rate']:.0%}  |  P&L: +${grad['total_pnl']:.2f}"
        )

    # Aged positions
    aged = check_aged_positions()
    if aged:
        print(bold(f"\n  ── Aged Positions ({len(aged)}) ──"))
        for entry in aged:
            t = entry["trade"]
            # Opus-review-caught (L7): paper and execution_log ids are
            # separate incrementing-int spaces that collide visually --
            # prefix live entries so "#5" can't be misread as the other
            # ledger's #5.
            _id_label = f"LIVE#{t['id']}" if t.get("live") else f"#{t['id']}"
            print(yellow(f"  {_id_label} {t['ticker']} — {entry['age_days']} days old"))

    # Correlated event exposure warning
    try:
        from paper import check_correlated_event_exposure

        corr_warnings = check_correlated_event_exposure()
        if corr_warnings:
            print(bold(f"\n  ── Correlation Warnings ({len(corr_warnings)}) ──"))
            for w in corr_warnings:
                n = len(w["trades"])
                print(
                    yellow(
                        f"  [Warning] {n} {w['city']} positions within 3 days "
                        f"(${w['total_cost']:.2f} at risk) — these are correlated bets"
                    )
                )
    except Exception:
        pass

    # Brier sparkline
    try:
        sparkline = _brier_sparkline()
        if sparkline:
            print(f"\n  Brier trend (recent weeks): {dim(sparkline)}")
    except Exception:
        pass

    print(
        dim(
            "\n  Run 'A' to analyze, 'P' for paper trades, 'T' for today's recommendation"
        )
    )

    # Email briefing if requested
    if send_email:
        try:
            from notify import _send_email
            from paper import get_balance, get_performance

            bal = get_balance()
            perf = get_performance()
            pnl = perf.get("total_pnl", 0.0)
            wr = perf.get("win_rate")
            bs, bs_n = brier_score_rolling_with_n()
            lines = [
                f"Balance: ${bal:.2f}",
                f"P&L: {'+' if pnl >= 0 else ''}${pnl:.2f}",
                f"Win rate: {wr:.0%}" if wr else "Win rate: —",
                f"Brier (3w, n={bs_n}): {bs:.4f}" if bs else "Brier (3w): —",
            ]
            sent = _send_email(
                f"Kalshi Morning Briefing — {datetime.now(UTC).strftime('%Y-%m-%d')}",
                "\n".join(lines),
            )
            if sent:
                print(green("  Morning briefing emailed."))
            else:
                print(
                    dim("  Email not sent (SMTP not configured — set SMTP_* env vars).")
                )
        except Exception as e:
            print(dim(f"  Email failed: {e}"))


def cmd_analyze(
    client: KalshiClient,
    min_edge: float | None = None,
    # --live only toggles the live-price display below (COMMANDS.md) -- it
    # does NOT gate order placement. This command can still place a real
    # live order regardless of this flag, via the interactive quick-buy
    # prompt at the end (_quick_paper_buy) -- see
    # _compute_live_orders_possible()'s docstring.
    live: bool = False,
):
    if min_edge is None:
        min_edge = MIN_EDGE
    _header("Trade Opportunity Scanner")
    if min_edge != MIN_EDGE:
        print(dim(f"  Edge threshold: {min_edge:.0%}  (default {MIN_EDGE:.0%})\n"))
    else:
        print(dim("  Scanning weather markets... (cached after first run)\n"))
    _analyze_once(client, min_edge=min_edge)
    print(bold("\n  How to read this table:"))
    print(dim("  Rating     ★★★ = strong edge, low risk  ★★ = good  ★ = fair"))
    print(dim("  We Think   what our weather models predict the probability is"))
    print(
        dim(
            "  Mkt Says   what you'd pay to buy YES (e.g. 42% = pay $0.42 to win $1.00)"
        )
    )
    print(dim("  Your Edge  how much better our odds are vs the market, after fees"))
    print(
        dim("  Risk       LOW = confident data  HIGH = market closes soon or thin data")
    )
    print(dim("  Buy        YES = bet it happens  NO = bet it doesn't happen"))
    print(dim("  ID         enter this when asked for a ticker to place a paper trade"))
    _quick_paper_buy(client)


# ── Watch mode ────────────────────────────────────────────────────────────────


def cmd_override(action: str, duration_minutes: int = 60) -> None:
    """
    Create a time-limited manual override.
    Overrides expire automatically after duration_minutes.

    Actions:
      pause <minutes>  — pause automated trading for N minutes
      unpause          — remove pause override immediately
      status           — show current override status
    """
    from paths import MANUAL_OVERRIDE_PATH as override_path

    if action == "unpause" or action == "status":
        if not override_path.exists():
            print(dim("  No active manual override."))
            return
        try:
            state = json.loads(override_path.read_text())
            expires = state.get("expires_at", 0)
            import time as _time

            remaining = expires - _time.time()
            if remaining <= 0 or action == "unpause":
                override_path.unlink(missing_ok=True)
                print(green("  Manual override cleared."))
            else:
                print(
                    bold(f"\n  Active override: {state.get('reason', 'manual pause')}")
                )
                print(f"  Expires in: {remaining / 60:.0f} minutes")
        except Exception as exc:
            _log.warning("cmd_override: %s", exc)
        return

    if action == "pause":
        import time as _time

        state = {
            "reason": "manual pause",
            "created_at": _time.time(),
            "expires_at": _time.time() + duration_minutes * 60,
            "duration_minutes": duration_minutes,
        }
        override_path.parent.mkdir(exist_ok=True)
        override_path.write_text(json.dumps(state, indent=2))
        print(yellow(f"  Trading paused for {duration_minutes} minutes."))
        print(dim("  Run `py main.py override unpause` to clear early."))
        return

    print(red(f"  Unknown override action: {action!r}"))
    print(dim("  Usage: py main.py override pause [minutes]  |  unpause  |  status"))


def _parse_accuracy_override_args(args: list) -> tuple[str, int]:
    """Parse `py main.py admin accuracy-override [minutes] ["reason"]`'s
    trailing args (the full CLI args list, so this reads args[2:] onward --
    everything after the action word) into (reason, minutes).

    minutes is optional and positional-first, matching `override
    pause [minutes]`'s existing convention -- if args[2] isn't a whole
    number, treat it (and everything after) as the reason instead and fall
    back to the default 60-minute duration, so the common no-minutes case
    (`admin accuracy-override "some reason"`) doesn't error out.

    Extracted as a standalone function (rather than inline in the CLI
    dispatcher) so this parsing logic is unit-testable on its own.
    """
    mins = 60
    reason_start = 2
    if len(args) > 2:
        try:
            mins = int(args[2])
            reason_start = 3
        except ValueError:
            reason_start = 2
    reason = (
        " ".join(args[reason_start:])
        if len(args) > reason_start
        else "manual admin override"
    )
    return reason, mins


def cmd_admin(
    action: str, reason: str = "manual admin override", minutes: int = 60
) -> None:
    """
    Admin commands for paper trading system.

    Actions:
      reset-loss  — waive today's daily loss limit (e.g. after a bug caused
                    phantom losses).  Expires automatically at midnight UTC.
      reset-peak  — reset the high-water mark to the current settled balance.
                    Use after a rough patch where the original peak is blocking
                    the model from gathering new data. Preserves all trade
                    history, predictions, and Brier data.
      accuracy-override [minutes] ["reason"] — waive the accuracy circuit
                    breaker (rolling win-rate + SPRT checks) for `minutes`
                    minutes (default 60). Use only after actually
                    investigating why it tripped and concluding the cause is
                    already understood/fixed — not as a routine way to push
                    trading through a real losing streak, which is exactly
                    what this gate exists to stop.
      accuracy-clear — remove an active accuracy-halt override early.
      accuracy-status — show whether an accuracy-halt override is active and
                    when it expires.
    """
    if action == "reset-loss":
        from paper import reset_daily_loss_limit

        reset_daily_loss_limit(reason=reason)
        print(
            green(
                "  Daily loss limit waived for the rest of today (UTC).\n"
                "  Run cron now — trading will resume normally.\n"
                "  The override expires automatically at midnight UTC."
            )
        )
        return

    if action == "accuracy-override":
        from paper import (
            get_accuracy_halt_override_status,
            get_accuracy_halt_reason,
            is_accuracy_halted,
            override_accuracy_halt,
        )

        if minutes <= 0:
            print(red(f"  minutes must be positive, got {minutes}"))
            return

        current_reason = get_accuracy_halt_reason() if is_accuracy_halted() else ""
        if current_reason:
            print(yellow(f"  Current halt reason: {current_reason}"))
        existing = get_accuracy_halt_override_status()
        if existing["active"]:
            _remaining = max(0, (existing["expires_at"] - time.time()) / 60)
            print(
                yellow(
                    f"  An override is ALREADY active ({_remaining:.0f} min "
                    f"remaining, reason: {existing['reason']!r}). This will "
                    f"replace it with a fresh {minutes}-minute window."
                )
            )
        print(
            yellow(
                f"  This will bypass the accuracy circuit breaker for {minutes} "
                f"minute(s), regardless of win rate or SPRT status during that "
                f"window — this ALSO lifts the live-order accuracy gate "
                f"(trading_gates.LiveTradingGate), not just paper cron "
                f"placement. Only do this if you've already investigated why "
                f"it tripped. Type 'yes' to confirm: "
            ),
            end="",
            flush=True,
        )
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            print(dim("  Cancelled."))
            return
        if answer != "yes":
            print(dim("  Cancelled."))
            return
        try:
            expires_at = override_accuracy_halt(reason=reason, minutes=minutes)
        except Exception as exc:
            print(red(f"  Override FAILED — the halt is still active: {exc}"))
            return
        expires_str = datetime.fromtimestamp(expires_at, UTC).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
        print(
            green(
                f"  Accuracy circuit breaker overridden for {minutes} minute(s) "
                f"(until {expires_str}).\n"
                f"  Run cron now — trade placement will proceed despite the halt.\n"
                f"  Also lifts the live-order accuracy gate for the same window.\n"
                f"  Clear early with: py main.py admin accuracy-clear"
            )
        )
        return

    if action == "accuracy-clear":
        from paper import clear_accuracy_halt_override

        was_active = clear_accuracy_halt_override()
        if was_active:
            print(green("  Accuracy halt override cleared."))
        else:
            print(dim("  No accuracy halt override was active."))
        return

    if action == "accuracy-status":
        from paper import get_accuracy_halt_override_status, is_accuracy_halted

        status = get_accuracy_halt_override_status()
        if status["active"]:
            expires_str = datetime.fromtimestamp(status["expires_at"], UTC).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
            remaining_min = max(0, (status["expires_at"] - time.time()) / 60)
            print(
                green(
                    f"  Override ACTIVE — expires {expires_str} ({remaining_min:.0f} min remaining)"
                )
            )
            print(dim(f"  Reason: {status['reason']}"))
        else:
            print(dim("  No accuracy halt override is active."))
        if is_accuracy_halted():
            from paper import get_accuracy_halt_reason

            print(
                yellow(
                    f"  Underlying halt is currently active: {get_accuracy_halt_reason()}"
                )
            )
        else:
            print(dim("  Underlying accuracy check is currently passing (not halted)."))
        return

    if action == "reset-peak":
        from paper import (
            MAX_DRAWDOWN_FRACTION,
            get_balance,
            get_peak_balance,
            reset_peak_balance,
        )

        old_peak = get_peak_balance()
        current = get_balance()
        # Use the actual configured drawdown fraction (DRAWDOWN_HALT_PCT,
        # default 0.20) rather than a hardcoded 80% — if the operator has
        # customized it, the old hardcoded prompt showed the wrong floor for
        # an irreversible reset.
        _halt_frac = 1 - MAX_DRAWDOWN_FRACTION
        print(
            yellow(
                f"  This will reset the peak from ${old_peak:.2f} → ${current:.2f}.\n"
                f"  New halt floor: ${current * _halt_frac:.2f}  "
                f"({_halt_frac:.0%} of ${current:.2f}).\n"
                f"  This is irreversible. Type 'yes' to confirm: "
            ),
            end="",
            flush=True,
        )
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            print(dim("  Cancelled."))
            return
        if answer != "yes":
            print(dim("  Cancelled."))
            return
        new_peak = reset_peak_balance(reason=reason, confirmed=True)
        print(
            green(
                f"  Peak balance reset: ${old_peak:.2f} → ${new_peak:.2f}\n"
                f"  Drawdown tiers now recalculated from ${new_peak:.2f}.\n"
                f"  Run cron to resume trading at updated Kelly fractions."
            )
        )
        return

    if action == "sameday-stats":
        from collections import defaultdict

        from paper import get_all_trades as _get_all

        trades = [t for t in _get_all() if t.get("days_out") == 0 and t.get("settled")]

        def _sd_mkt_type(ticker: str) -> str:
            return "between" if "-B" in ticker.upper() else "above_below"

        for label, mkt_key in [
            ("Above/Below", "above_below"),
            ("Between", "between"),
        ]:
            subset = [t for t in trades if _sd_mkt_type(t.get("ticker", "")) == mkt_key]
            print(f"\n  === {label} same-day settled ===")
            if not subset:
                print("  No settled trades yet.")
                continue
            buckets: dict = defaultdict(list)
            for t in subset:
                hour = int(t["entered_at"][11:13])
                buckets[hour].append(t)
            print(f"  {'UTC Hour':>8}  {'N':>4}  {'Win Rate':>9}")
            for h in sorted(buckets):
                rows = buckets[h]
                wr = sum(1 for t in rows if (t.get("pnl") or 0) > 0) / len(rows)
                print(f"  {h:>8}  {len(rows):>4}  {wr * 100:>8.1f}%")
        if not trades:
            print(dim("  No settled same-day trades found."))
        return

    print(red(f"  Unknown admin action: {action!r}"))
    print(
        dim(
            "  Usage: py main.py admin reset-loss | reset-peak | sameday-stats | "
            "accuracy-override [minutes] [reason] | accuracy-clear | accuracy-status"
        )
    )


def cmd_watch(
    client: KalshiClient,
    auto_trade: bool = False,
    min_edge: float = 0.10,
    live: bool = False,
):
    mode = "AUTO-TRADE" if auto_trade else "Watch"
    print(bold(f"{mode} mode — refreshing every 5 minutes. Press Ctrl+C to stop.\n"))
    if auto_trade:
        print(
            yellow(
                "  Auto-trade: STRONG BUY + LOW risk signals → paper orders placed automatically.\n"
            )
        )
    previous: set = _load_watch_state()
    _price_history: dict[str, float] = {}

    try:
        while True:
            # cron.py's own cmd_cron already resets gate counts every cycle --
            # watch mode called neither this nor cron's disk-cache flushes
            # (confirmed via grep: zero references before this fix), since it
            # relies on neither cron.py's call path nor process exit, being
            # meant to run indefinitely (backlog.txt "ONE-SHOT PROCESS
            # LIFECYCLE IS BAKED INTO MODULE STATE"). Reset here, at the start
            # of the cycle whose gate-check outcomes it's about to track --
            # matches cron.py's own placement.
            reset_gate_counts()
            os.system("cls" if sys.platform == "win32" else "clear")
            now = time.strftime("%H:%M:%S")
            print(bold(f"Kalshi Weather Markets — {now}"))
            print(dim("─" * 52))
            print(dim("* = new since last scan   Ctrl+C to exit\n"))
            # Trading decision runs FIRST when auto-trading, before the
            # display scan below -- so the table the operator sees reflects
            # the state right after this cycle's trading decision, not a
            # stale pre-decision snapshot (the more safety-relevant staleness
            # direction: an operator seeing "no signals" moments after a
            # trade actually fired is more confusing than the reverse).
            # Display now sources from run_trade_cycle()'s own already-
            # scanned/already-analyzed data when auto-trading and a
            # cycle_result is available -- position-protection unification's
            # sibling follow-up, backlog.txt's [CMD_WATCH RUNS THREE
            # INDEPENDENT get_weather_markets() SCANS...] entry, now
            # RESOLVED. This leaves cmd_watch running at most TWO independent
            # get_weather_markets() scans per auto-trading cycle:
            # run_trade_cycle()'s own scan (also reused below for price-drift
            # detection via cycle_result.markets) and one more inside
            # _check_early_exits() below (position-protection's own scan,
            # deliberately left unthreaded -- see that entry's ADDENDUM) --
            # down from up to four. Plain/non-auto watch and the
            # cycle_result=None fallback (kill switch active, or the cron
            # lock unavailable) are unaffected -- both still call
            # _analyze_once() directly, which still runs its own full scan
            # exactly as before.
            cycle_result = None
            live_cfg = _load_live_config() if live else None
            if auto_trade:
                # Imported here, not at module/function top, so a plain
                # read-only watch session (auto_trade=False) never imports
                # the trade-decision engine at all.
                from trade_cycle import TIER_STRONG, run_trade_cycle

                ctx = _build_cron_context()
                _lock_acquired = ctx.acquire_cron_lock()
                if not _lock_acquired:
                    print(
                        yellow(
                            "  [Auto] Could not acquire the cron lock (cron is running "
                            "concurrently) — auto-trade skipped this cycle."
                        )
                    )
                else:
                    try:
                        cycle_result = run_trade_cycle(
                            ctx,
                            client,
                            min_edge=min_edge,
                            live=live,
                            live_config=live_cfg,
                            prewarm=False,
                            require_liquid_for_placement=True,
                        )
                        if cycle_result is None:
                            print(
                                yellow(
                                    "  [Auto] Kill switch active — auto-trade skipped this cycle."
                                )
                            )
                    finally:
                        ctx.release_cron_lock()

            # Price drift detection — check all liquid markets
            try:
                _drift_markets = (
                    cycle_result.markets
                    if cycle_result is not None
                    else get_weather_markets(client)
                )
                for _dm in _drift_markets:
                    _dt = _dm.get("ticker", "")
                    _dp = parse_market_price(_dm).get("yes_ask", 0.0) or 0.0
                    if _dt in _price_history and _dp > 0:
                        _delta = _dp - _price_history[_dt]
                        if abs(_delta) >= 0.03:
                            _dir = "▲" if _delta > 0 else "▼"
                            print(
                                yellow(
                                    f"  [Price drift] {_dt}  YES ask {_dir} {abs(_delta):.2f}  ({_price_history[_dt]:.2f} → {_dp:.2f})"
                                )
                            )
                    if _dp > 0:
                        _price_history[_dt] = _dp
            except Exception:
                pass
            liquid_opps: list = []
            if cycle_result is not None:
                # Source the display from run_trade_cycle()'s own already-
                # scanned/already-analyzed data instead of a second
                # independent scan -- position-protection unification's
                # sibling follow-up (see the comment above). _is_hedge isn't
                # computed by run_trade_cycle() itself (it has no use for
                # it), so build it here the same way _analyze_once's own
                # loop does. ticker->city IS exposed directly as
                # cycle_result.ticker_city (opus review, 2026-08-03: an
                # earlier draft rebuilt this from cycle_result.all_results,
                # which is populated only for markets where analyze_trade()
                # returned truthy -- narrower than _analyze_once's own
                # _arb_ticker_city, which tags every successfully-enriched
                # market regardless. cycle_result.ticker_city is tagged at
                # the equivalent point in run_trade_cycle()'s own loop).
                try:
                    from paper import get_open_trades as _cw_got

                    _cw_open_trades = _cw_got()
                except Exception:
                    _cw_open_trades = []
                for _cw_enriched, _cw_analysis in cycle_result.all_results:
                    _cw_analysis["_is_hedge"] = detect_hedge_opportunity(
                        _cw_analysis, _cw_open_trades
                    )
                # Fire the new-STRONG-liquid-opportunity alert -- previously
                # only reachable via _analyze_once's own per-market loop
                # (main.py, the loop above this function), which the
                # cycle_result path bypasses entirely (liquid is implicit:
                # cycle_result.liquid_opps is already the liquid split), using
                # `previous` from BEFORE this cycle's render call reassigns it
                # below, same timing _analyze_once uses internally (opus
                # review, 2026-08-03: a HIGH-severity finding -- this alert
                # silently never fired on the auto-trade watch path without
                # this loop, and worse, was sticky, since _save_watch_state
                # below still recorded those tickers as seen). As of the
                # tier-based fix below, this loop's condition deliberately no
                # longer matches _analyze_once's own STRONG-text condition --
                # _analyze_once's analysis dicts come straight from
                # analyze_trade() and never carry a `tier` key, so that older
                # fallback path (reached when cycle_result is None, e.g. the
                # cron lock is held) still alerts on signal text alone.
                for _cw_alert_enriched, _cw_alert_analysis in cycle_result.liquid_opps:
                    _cw_alert_ticker = _cw_alert_enriched.get("ticker", "")
                    # backlog.txt "DASHBOARD STARS + WATCH-MODE STRONG ALERT
                    # KEY OFF SIGNAL TEXT, NOT THE tier FIELD": read the
                    # authoritative `tier` run_trade_cycle() sets (cleared
                    # every placement gate) instead of net_signal text, which
                    # is driven only by adjusted_edge magnitude.
                    if (
                        _cw_alert_analysis.get("tier") == TIER_STRONG
                        and _cw_alert_ticker not in previous
                    ):
                        alert_strong_signal(
                            ticker=_cw_alert_ticker,
                            city=_cw_alert_enriched.get("_city", ""),
                            side=_cw_alert_analysis["recommended_side"],
                            net_edge=_cw_alert_analysis.get(
                                "net_edge", _cw_alert_analysis["edge"]
                            ),
                            kelly=_cw_alert_analysis.get(
                                "fee_adjusted_kelly", _cw_alert_analysis.get("kelly", 0)
                            ),
                        )
                previous = _render_analysis_results(
                    client,
                    cycle_result.deduped_markets,
                    cycle_result.liquid_opps,
                    cycle_result.no_quote_opps,
                    previous,
                    cycle_result.effective_min_edge,
                    True,
                    _cw_open_trades,
                    cycle_result.ticker_city,
                    liquid_opps,
                )
            else:
                previous = _analyze_once(
                    client,
                    previous,
                    _liquid_opps_out=liquid_opps,
                    min_edge=min_edge,
                    show_summary=True,
                )
            _save_watch_state(previous)
            if live:
                # AUD-0013: cmd_watch only ever reached _recover_pending_orders
                # indirectly via run_trade_cycle(), itself gated on
                # auto_trade=True AND a successful ctx.acquire_cron_lock() a
                # few lines above -- if the lock was contended this cycle,
                # recovery was silently skipped while the exit checks below
                # still ran. Standalone call here mirrors cron.py's own
                # restored early call (cron.py ~898-904) and is a harmless
                # no-op when there's nothing left pending/unknown to recover.
                try:
                    from order_executor import _recover_pending_orders

                    _recover_pending_orders(client)
                except Exception as _rpo_exc:
                    _log.warning(
                        "cmd_watch: _recover_pending_orders failed: %s", _rpo_exc
                    )

                # AUD-0008: this block previously had NO exception handling at
                # all, unlike the three paper-side sibling blocks immediately
                # below it (each already wrapped after a prior "was a silent
                # pass" fix) and unlike cron.py's own equivalent call site
                # (cron.py ~912-923, already guarded). The outer while-loop's
                # only handler is `except KeyboardInterrupt`, so any exception
                # here used to kill the entire persistent watch process,
                # leaving every open live position unprotected until an
                # operator noticed and restarted it -- potentially hours.
                try:
                    _poll_pending_orders(client, config=live_cfg)
                    _reprice_or_cancel_pending_orders(
                        client,
                        config=live_cfg,
                        liquid_opps=(
                            # Filter to threshold-passing candidates only --
                            # cycle_result.liquid_opps is every liquid candidate
                            # regardless of outcome (all_results split by
                            # is_liquid() alone), unlike the pre-extraction
                            # liquid_opps list above which was already filtered
                            # to _passes_edge-True pairs. _reprice_or_cancel_
                            # pending_orders uses ticker presence in this list to
                            # decide whether a resting live order gets left
                            # alone or is eligible for cancel+taker-replace --
                            # passing the unfiltered set would newly expose a
                            # resting order on a below-threshold ticker to that
                            # replacement path, which pre-extraction watch never
                            # did.
                            [
                                p
                                for p in cycle_result.liquid_opps
                                if p[1].get("_passes_threshold")
                            ]
                            if cycle_result is not None
                            else liquid_opps
                        ),
                    )
                    # Live position protection — must run after the two calls
                    # above so a just-filled order is already visible.
                    _check_live_position_exits(client, config=live_cfg)
                    _check_live_model_exits(client, config=live_cfg)
                except Exception as _live_exc:
                    _log.error(
                        "cmd_watch: live order/position protection failed "
                        "(open live positions may be unprotected this cycle): %s",
                        _live_exc,
                    )
            # Check price alerts
            try:
                from alerts import check_alerts, mark_triggered

                triggered = check_alerts(client)
                for item in triggered:
                    a = item["alert"]
                    cp = item["current_price"]
                    print(
                        yellow(
                            f"  [Price alert] {a['ticker']} YES hit {cp:.2f}"
                            f" (target: {a['target_price']:.2f} {a['direction']})"
                        )
                    )
                    mark_triggered(a["id"])
            except Exception as _alert_exc:
                # Was a silent `pass` — a corrupt ledger or API error here
                # could permanently and invisibly stop price-alert checks
                # for the rest of the watch loop with zero trace in bot.log.
                _log.warning("cmd_watch: price-alert check failed: %s", _alert_exc)

            # Price-based stop-loss/breakeven check — unified with cron.py's
            # own paper protection, same thresholds/gates (position-
            # protection unification follow-up; see backlog.txt's [POSITION
            # PROTECTION IS STILL TWO SEPARATE MECHANISMS...] entry).
            # Previously cron-only; plain/auto watch had none. Note this
            # runs even with data/.kill_switch active -- unlike cron.py,
            # which returns before reaching its own copy of this call while
            # the kill switch is set, watch's loop has no kill-switch check
            # at all (pre-existing: the old check_model_exits call this
            # replaced didn't check it either).
            try:
                import paper as _paper_watch

                for _closed in _paper_watch.check_paper_position_exits(client):
                    if _closed["reason"] == "stop_loss":
                        _log.info(
                            "[StopLoss] Closed %s — price breached stop threshold",
                            _closed["ticker"],
                        )
                        print(
                            red(
                                f"  [StopLoss] Closed {_closed['ticker']} — price breached stop threshold"
                            )
                        )
                    else:
                        _log.info(
                            "[BreakEven] Closed %s — fell back to entry after peaking %.0f%% profit",
                            _closed["ticker"],
                            (_closed["trade"].get("peak_profit_pct") or 0) * 100,
                        )
                        print(
                            yellow(
                                f"  [BreakEven] Closed {_closed['ticker']} — scratch exit (peaked then fell to entry)"
                            )
                        )
            except Exception as _sl_exc:
                _log.error(
                    "cmd_watch: paper stop-loss/breakeven check failed: %s", _sl_exc
                )

            # Check open paper positions for model-flip exit + expiring
            # warnings. Model-flip now uses the same order_executor.
            # _check_early_exits() implementation cron.py uses (25pp shift +
            # settlement-convergence gate) instead of the separate
            # paper.check_model_exits() implementation (10pp, no settlement
            # gate) that this automated loop previously called — that
            # function still exists and is used by cmd_brief and the manual
            # Paper > Exit-signals menu, just no longer here (position-
            # protection unification follow-up, same entry as above).
            try:
                from paper import check_expiring_trades

                _early_exits = _check_early_exits(client)
                if _early_exits > 0:
                    print(
                        green(
                            f"  [EarlyExit] Closed {_early_exits} position(s) on model update."
                        )
                    )
                for exp in check_expiring_trades():
                    t = exp["trade"]
                    hrs = exp["hours_left"]
                    label = (
                        red(f"{hrs}h left") if exp["urgent"] else yellow(f"{hrs}h left")
                    )
                    print(
                        f"  [Expiring] #{t['id']} {t['ticker']} "
                        f"{t['side'].upper()} — {label}"
                    )
            except Exception as _model_exit_exc:
                # Was a silent `pass` — e.g. a corrupt paper_trades.json
                # raising CorruptionError (get_open_trades' deliberate
                # fail-closed) would silently and permanently kill model-exit
                # / expiring-trade checks for the rest of the watch loop.
                _log.warning(
                    "cmd_watch: model-exit/expiring-trade check failed: %s",
                    _model_exit_exc,
                )
            opp_count = len(previous)
            opp_word = "opportunity" if opp_count == 1 else "opportunities"
            print(
                dim(
                    f"\nLast scan: {time.strftime('%H:%M:%S')} · {opp_count} {opp_word} found"
                )
            )
            print(
                dim(
                    f"Next refresh in {REFRESH_SECS // 60} min — {time.strftime('%H:%M:%S', time.localtime(time.time() + REFRESH_SECS))}"
                )
            )
            # Flush this cycle's own pending disk-cache entries at the end of
            # the cycle that created them (matching where cron.py's
            # _cmd_cron_body flushes -- near the end of its body, not the
            # start of the next one) -- otherwise a SIGKILL/OOM/crash between
            # cycles loses this cycle's warm-up contribution entirely, since
            # only a clean shutdown's atexit handler would have flushed it.
            flush_forecast_disk_cache()
            flush_ensemble_disk_cache()
            time.sleep(REFRESH_SECS)
    except KeyboardInterrupt:
        print(f"\n{dim('Watch mode stopped.')}")


# ── Forecast ──────────────────────────────────────────────────────────────────


def cmd_forecast(city: str):
    if city not in CITY_COORDS:
        print(
            red(f"Unknown city '{city}'.  Available: {', '.join(CITY_COORDS.keys())}")
        )
        return
    try:
        from zoneinfo import ZoneInfo as _ZoneInfoCf

        today = datetime.now(_ZoneInfoCf(_CITY_TZ.get(city, "America/New_York"))).date()
    except Exception:
        _log.warning(
            "cmd_forecast: ZoneInfo unavailable for city=%s — falling back to UTC date",
            city,
        )
        today = datetime.now(UTC).date()

    print(bold(f"\n7-day forecast for {city}:\n"))
    rows = []
    for i in range(7):
        d = today + timedelta(days=i)
        f = get_weather_forecast(city, d)
        if f:
            models = f.get("models_used", 1)
            hi_r = f.get("high_range", (f["high_f"], f["high_f"]))
            rows.append(
                [
                    bold(f["date"]) if i == 0 else f["date"],
                    bold(f"{f['high_f']:.1f}°F"),
                    f"{f['low_f']:.1f}°F",
                    f"{f['precip_in']:.2f} in",
                    dim(f"{hi_r[0]:.0f}–{hi_r[1]:.0f}°  ({models} models)"),
                ]
            )
    print(
        tabulate(
            rows,
            headers=["Date", "High", "Low", "Precip", "Model range"],
            tablefmt="rounded_outline",
        )
    )

    # Show active model weights for this city
    try:
        from tracker import get_model_weights

        weights = get_model_weights(city, window_days=30)
        if weights:
            weight_parts = "  ".join(
                f"{m}: {w:.0%}" for m, w in sorted(weights.items(), key=lambda x: -x[1])
            )
            print(dim(f"\n  Active model weights (30-day MAE): {weight_parts}"))
        else:
            print(
                dim(
                    f"\n  Active model weights: equal (insufficient history for {city})"
                )
            )
    except Exception:
        pass


def cmd_afd(city: str) -> None:
    """Print the current NWS Area Forecast Discussion for a city (backlog.txt
    "NWS AFD (AREA FORECAST DISCUSSION) PARSING" -- infra-only pass: fetch
    and display only, no confidence/lean scoring yet).
    """
    from nws_afd import CITY_WFO_OFFICE, fetch_afd_discussion

    if city not in CITY_WFO_OFFICE:
        print(
            red(
                f"Unknown city '{city}'.  Available: "
                f"{', '.join(CITY_WFO_OFFICE.keys())}"
            )
        )
        return

    office = CITY_WFO_OFFICE[city]
    discussion = fetch_afd_discussion(city)
    if discussion is None:
        print(
            yellow(
                f"\n  No narrative discussion available right now for AFD{office} "
                "(fetch failed, or today's bulletin doesn't include one of the "
                "known narrative sections -- see nws_afd.py's module docstring)."
            )
        )
        return
    print(bold(f"\nAFD{office} — Area Forecast Discussion for {city}:\n"))
    print(discussion)


# ── Consistency ───────────────────────────────────────────────────────────────


def cmd_consistency(client: KalshiClient):
    _header("Arbitrage Scanner")
    print(dim("  Scanning for consistency violations across related markets...\n"))
    markets = get_weather_markets(client)
    violations = find_violations(markets)
    if not violations:
        print(green("No violations right now — all prices are internally consistent."))
    else:
        print(yellow(f"Found {len(violations)} arbitrage opportunity/ies:\n"))
        rows = []
        for v in violations:
            rows.append(
                [
                    green(v.buy_ticker),
                    f"{v.buy_prob * 100:.1f}%",
                    red(v.sell_ticker),
                    f"{v.sell_prob * 100:.1f}%",
                    bold(f"{v.guaranteed_edge * 100:.1f}%"),
                    # backlog.txt "RAIN MARKETS -- CONSISTENCY.PY'S ARBITRAGE
                    # CHECK STILL BLANKET-EXCLUDES KXRAIN*M": this manual report
                    # is the observation surface for rain's shadow-only first
                    # pass -- mark shadow rows so an operator deciding whether
                    # to graduate them isn't misled by rows that look
                    # auto-tradeable but aren't.
                    dim("shadow") if getattr(v, "is_shadow", False) else "",
                ]
            )
        print(
            tabulate(
                rows,
                headers=[
                    "BUY this",
                    "Price",
                    "SELL this",
                    "Price",
                    "Free edge",
                    "Type",
                ],
                tablefmt="rounded_outline",
            )
        )
        print(
            dim(
                "\nBuy the cheaper contract and sell the pricier one — profit is guaranteed."
                " 'shadow' rows are logged only, never auto-placed."
            )
        )

    # backlog.txt "RAIN ARBITRAGE-CHECK SHADOW SIGNAL HAS NO GRADUATION
    # DECISION YET": this session's live snapshot above only ever shows
    # what's true RIGHT NOW -- the accumulated history from every cron/watch
    # cycle's own shadow-observation recording (consistency.
    # record_shadow_observations) is what the eventual graduation call
    # actually needs. Printed unconditionally (even with zero live
    # violations above) since the report reflects history, not this instant.
    report = get_shadow_observation_report()
    if report is not None and report["cycles_observed"] > 0:
        print(bold("\n── Rain Shadow-Arb Observation History ──\n"))
        print(
            dim(
                f"  {report['cycles_observed']} cycle(s) observed,"
                f" {report['cycles_with_violation']} with a shadow violation"
                f" ({report['violation_rate']:.1%})"
                f" — {report['distinct_pairs']} distinct ladder-pair(s) ever flagged."
            )
        )
        if report["top_pairs"]:
            hist_rows = [
                [
                    p.get("buy_ticker", ""),
                    p.get("sell_ticker", ""),
                    p.get("times_seen", 0),
                    f"{p.get('max_edge', 0.0) * 100:.1f}%",
                    (p.get("last_seen") or "")[:10],
                ]
                for p in report["top_pairs"][:10]
            ]
            print(
                tabulate(
                    hist_rows,
                    headers=[
                        "Buy",
                        "Sell",
                        "Times seen",
                        "Max edge",
                        "Last seen",
                    ],
                    tablefmt="rounded_outline",
                )
            )
        print(
            dim(
                '\n  Not yet a graduation decision — see backlog.txt "RAIN'
                " ARBITRAGE-CHECK SHADOW SIGNAL HAS NO GRADUATION DECISION"
                ' YET" for what to do once this history looks conclusive.'
            )
        )


# ── Dashboard ────────────────────────────────────────────────────────────────


def cmd_dashboard(client: KalshiClient) -> None:
    """Single-screen portfolio health view: balance, positions, calibration."""
    from paper import (
        get_all_trades,
        get_balance,
        get_max_drawdown_pct,
        get_open_trades,
        get_peak_balance,
        get_performance,
    )

    _header("Portfolio Dashboard")

    # ── Account health ────────────────────────────────────────────────────────
    bal = get_balance()
    peak = get_peak_balance()
    dd = get_max_drawdown_pct()
    dd_str = (
        red(f"{dd:.1%}")
        if dd > 0.15
        else yellow(f"{dd:.1%}")
        if dd > 0.05
        else green(f"{dd:.1%}")
    )
    print(
        f"  Balance: {bold(f'${bal:.2f}')}  |  Peak: ${peak:.2f}  |  Drawdown from peak: {dd_str}"
    )

    from paper import drawdown_scaling_factor

    scale = drawdown_scaling_factor()
    if scale < 1.0:
        from paper import MAX_DRAWDOWN_FRACTION as _dd_pct

        if scale == 0.0:
            sizing_str = red(f"PAUSED  (>{_dd_pct:.0%} drawdown from peak)")
        else:
            sizing_str = yellow(f"{scale:.0%} of normal  (recovering from drawdown)")
        print(f"  Sizing:  {sizing_str}")

    perf = get_performance()
    if perf["settled"]:
        wr = perf.get("win_rate")
        pnl = perf.get("total_pnl", 0.0)
        roi = perf.get("roi")
        wr_str = f"{wr:.1%}" if wr is not None else "—"
        pnl_str = green(f"+${pnl:.2f}") if pnl >= 0 else red(f"-${abs(pnl):.2f}")
        roi_str = f"{roi:+.1%}" if roi is not None else "—"
        print(
            f"  Settled: {perf['settled']}  |  Win rate: {wr_str}  |  P&L: {pnl_str}  |  ROI: {roi_str}"
        )

    # ── Rolling Sharpe ───────────────────────────────────────────────────────
    try:
        from paper import get_rolling_sharpe

        sharpe = get_rolling_sharpe(window_days=30)
        if sharpe is not None:
            sharpe_s = (
                green(f"{sharpe:.2f}")
                if sharpe > 1.0
                else yellow(f"{sharpe:.2f}")
                if sharpe > 0
                else red(f"{sharpe:.2f}")
            )
            print(f"  Sharpe (30d): {sharpe_s}  {dim('(annualised, >1.0 = strong)')}")
    except Exception:
        pass

    # ── Calibration ──────────────────────────────────────────────────────────
    bs, bs_n = brier_score_rolling_with_n()
    if bs is not None:
        grade = (
            green("Excellent")
            if bs < 0.10
            else green("Good")
            if bs < 0.18
            else yellow("Fair")
            if bs < 0.25
            else red("Poor")
        )
        print(f"  Brier score: {bold(f'{bs:.4f}')}  {grade}  {dim(f'(3w, n={bs_n})')}")

    # ── Open positions ────────────────────────────────────────────────────────
    open_trades = get_open_trades()
    print(bold("\n  ── Open Positions ──\n"))
    if open_trades:
        pos_rows = []
        exposure_by_city: dict[str, float] = {}
        for t in open_trades:
            pos_rows.append(
                [
                    t["id"],
                    t["ticker"][:30],
                    bold(t["side"].upper()),
                    t["quantity"],
                    f"${t['entry_price']:.3f}",
                    f"${t['cost']:.2f}",
                    t.get("city", "—"),
                    t.get("target_date", "—"),
                ]
            )
            city_key = f"{t.get('city', '?')}/{t.get('target_date', '?')}"
            exposure_by_city[city_key] = exposure_by_city.get(city_key, 0.0) + t["cost"]
        print(
            tabulate(
                pos_rows,
                headers=["#", "Ticker", "Side", "Qty", "Price", "Cost", "City", "Date"],
                tablefmt="rounded_outline",
            )
        )
        print(bold("\n  Exposure by city/date:"))
        for k, amt in sorted(exposure_by_city.items(), key=lambda x: -x[1]):
            pct = amt / bal * 100 if bal > 0 else 0
            bar = "█" * min(20, int(pct / 2))
            print(f"    {k:<30} ${amt:.2f}  ({pct:.1f}%)  {cyan(bar)}")
        # Unrealized P&L (mark-to-market)
        try:
            from paper import get_unrealized_pnl_paper

            # get_unrealized_pnl_paper has no cached-price mode — passing
            # None short-circuits it to n=0, so the mark-to-market section
            # below could never print even with a live client in scope.
            unreal = get_unrealized_pnl_paper(client)
            total_unreal = unreal.get("total_unrealized", 0.0)
            if unreal.get("n", 0) > 0:
                unreal_s = (
                    green(f"+${total_unreal:.2f}")
                    if total_unreal >= 0
                    else red(f"-${abs(total_unreal):.2f}")
                )
                print(f"\n  Unrealized P&L (mark-to-market): {unreal_s}")
        except Exception:
            pass
    else:
        print(dim("  No open positions."))

    # ── Expiry warnings ───────────────────────────────────────────────────────
    try:
        from paper import check_expiring_trades

        expiring = check_expiring_trades()
        if expiring:
            print(bold("\n  ── Expiring Soon ──\n"))
            for exp in expiring:
                t = exp["trade"]
                hrs = exp["hours_left"]
                label = red(f"{hrs}h left") if exp["urgent"] else yellow(f"{hrs}h left")
                print(f"  #{t['id']} {t['ticker']} {t['side'].upper()} — {label}")
            print()
    except Exception:
        pass

    # ── All trades summary ────────────────────────────────────────────────────
    all_t = get_all_trades()
    print(bold("\n  ── Recent Settled Trades ──\n"))
    settled = [t for t in all_t if t["settled"]][-5:]
    if settled:
        s_rows = []
        for t in settled:
            pnl = t.get("pnl", 0.0) or 0.0
            pnl_s = green(f"+${pnl:.2f}") if pnl >= 0 else red(f"-${abs(pnl):.2f}")
            s_rows.append(
                [
                    t["id"],
                    t["ticker"][:28],
                    t["side"].upper(),
                    t["outcome"].upper() if t["outcome"] else "—",
                    pnl_s,
                ]
            )
        print(
            tabulate(
                s_rows,
                headers=["#", "Ticker", "Side", "Result", "P&L"],
                tablefmt="rounded_outline",
            )
        )
    else:
        print(dim("  No settled trades yet."))

    print()


# ── Trade journal ─────────────────────────────────────────────────────────────


def cmd_journal() -> None:
    """Print all paper trades that have a thesis note."""
    from paper import get_all_trades

    all_trades = get_all_trades()
    with_thesis = [t for t in all_trades if t.get("thesis")]
    if not with_thesis:
        print(dim("  No journal entries yet. Add a thesis when placing a trade."))
        return

    _header(f"Trade Journal  ({len(with_thesis)} entries)")
    for t in with_thesis:
        pnl = t.get("pnl")
        settled = t.get("settled", False)
        if settled and pnl is not None:
            outcome_s = (
                green(f"  WIN  +${pnl:.2f}")
                if pnl >= 0
                else red(f"  LOSS -${abs(pnl):.2f}")
            )
        elif settled:
            outcome_s = dim("  settled")
        else:
            outcome_s = yellow("  open")
        date_s = (t.get("entered_at") or "")[:10]
        print(
            f"\n  #{t['id']}  {bold(t['ticker'])}  {t['side'].upper()}"
            f"  @${t.get('entry_price', 0):.3f}  {dim(date_s)}{outcome_s}"
        )
        print(f"  {dim('▸')} {t['thesis']}")
    print()


# ── CSV Export ────────────────────────────────────────────────────────────────


def cmd_export() -> None:
    """Export prediction history and paper trades to CSV in data/exports/."""
    from paper import export_tax_csv, export_trades_csv

    out_dir = EXPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    pred_path = str(out_dir / "predictions.csv")
    paper_path = str(out_dir / "paper_trades.csv")

    n1 = export_predictions_csv(pred_path)
    n2 = export_trades_csv(paper_path)

    if n1:
        print(green(f"  Exported {n1} predictions → {pred_path}"))
    else:
        print(dim("  No predictions to export yet."))
    if n2:
        print(green(f"  Exported {n2} paper trades → {paper_path}"))
    else:
        print(dim("  No paper trades to export yet."))

    # Tax export — paper trades
    # L-9 sweep: UTC year, not a filer's local calendar year -- flagged and
    # deliberately left as-is. export_tax_csv() filters by settled_at[:4],
    # and settled_at is itself stored in UTC throughout this codebase (see
    # paper.py's get_daily_pnl). Switching only this caller to a local
    # timezone would desync the requested tax_year from the UTC basis
    # settled_at is actually compared against -- a real fix needs
    # export_tax_csv() itself to interpret settled_at in the filer's local
    # time, which is a bigger change than this doc/tz nit sweep should make.
    tax_year = datetime.now(UTC).year
    tax_path = str(out_dir / f"paper_tax_{tax_year}.csv")
    n3 = export_tax_csv(tax_path, tax_year=tax_year)
    if n3:
        print(
            green(
                f"  Exported {n3} settled paper trades (tax year {tax_year}) → {tax_path}"
            )
        )
        print(
            dim("  Note: This file is for informational purposes only, not tax advice.")
        )
    else:
        print(dim(f"  No settled paper trades for tax year {tax_year} to export."))

    # Tax export — live orders
    from execution_log import export_live_tax_csv

    live_tax_path = str(out_dir / f"live_tax_{tax_year}.csv")
    n4 = export_live_tax_csv(live_tax_path, tax_year=tax_year)
    if n4:
        print(
            green(
                f"  Exported {n4} settled live orders (tax year {tax_year}) → {live_tax_path}"
            )
        )
    else:
        print(dim(f"  No settled live orders for tax year {tax_year} to export."))


def cmd_order(client: KalshiClient, action: str, args: list):
    if is_trading_paused():
        print(
            red(
                "  TRADING_PAUSED is set in .env — manual order placement is disabled.\n"
                "  Remove TRADING_PAUSED to resume trading."
            )
        )
        return
    if len(args) < 4:
        print(f"Usage: py main.py {action} <ticker> <yes/no> <count> <price>")
        return
    # Opus review (batch-09 round 2, F11): mirror the "market" dispatch's
    # own args[1].upper() -- the buy/sell CLI dispatch never uppercased its
    # ticker, so a lowercase input reached kalshi_client's new AUD-0076
    # format check (which requires uppercase) and produced a confusing
    # "Could not reach Kalshi API" message instead of just working, unlike
    # every other ticker entry point in this file.
    ticker, side, count_str, price_str = args[0].upper(), args[1], args[2], args[3]
    if side not in ("yes", "no"):
        print(red("side must be 'yes' or 'no'"))
        return
    try:
        count, price = float(count_str), float(price_str)
    except ValueError:
        print(red("count and price must be numbers"))
        return
    # Opus review (batch-09 round 2, F9): count=nan/inf parsed fine above
    # (float() accepts them) but then crashed unhandled on int(count) below
    # -- int(nan) raises ValueError, int(inf) raises OverflowError, neither
    # caught by the ValueError guard above since it's already out of scope
    # by this line. Reject non-finite values explicitly before int().
    if count != count or count in (float("inf"), float("-inf")):
        print(red(f"count must be a whole number ≥ 1 (got {count_str})"))
        return
    if count != int(count) or int(count) < 1:
        print(red(f"count must be a whole number ≥ 1 (got {count_str})"))
        return
    # AUD-0040: cmd_order had no local price-range check, unlike web_app.py's
    # /api/close-position (`0.0 < exit_price <= 1.0`) -- mirror that same
    # dollar-fraction convention here rather than relying solely on Kalshi's
    # own API-side validation as the backstop.
    if not (0.0 < price <= 1.0):
        print(red(f"price must be between 0 and 1 (got {price_str})"))
        return

    # backlog.txt "HURRICANE MARKETS": no supported model exists for
    # hurricane/tropical-storm tickers (see is_hurricane_ticker()'s own
    # comment for why this covers several unrelated real prefixes, not just
    # "KXHUR"). analyze_trade()'s own guard only prevents Brier/P&L tracking
    # here, not the order itself -- this path places a real order
    # unconditionally even when analysis fails (see the try/except below).
    # Refuse outright rather than warn-and-continue. This function is one of
    # several manual paths that don't go through analyze_trade() first
    # (main.cmd_paper and web_app's /api/paper-order are two more -- all
    # funnel through paper.check_position_limits(), which carries the same
    # guard, but this direct check keeps cmd_order fail-closed even if that
    # call raises rather than returning ok=False).
    # backlog.txt "HURRICANE MARKETS" -- season-count model (2026-08-03): 5
    # series now have a real model and shadow-only gate, same explicit
    # refuse-outright-until-gated treatment as snow's own block below (for
    # the same fail-closed-even-if-check_position_limits-raises reason).
    if is_hurricane_count_ticker(ticker) and not _hurricane_count_gates_active():
        print(
            red(
                f"  {ticker}: hurricane season-count markets are shadow-only until "
                "HURRICANE_TRADING_ENABLED=1 and >=20 settled hurricane-count "
                "predictions exist — refusing to place this order."
            )
        )
        return
    if (
        is_hurricane_next_event_ticker(ticker)
        and not _hurricane_next_event_gates_active()
    ):
        print(
            red(
                f"  {ticker}: hurricane time-to-next-event markets are shadow-only "
                "until HURRICANE_NEXT_EVENT_TRADING_ENABLED=1 and >=20 settled "
                "predictions exist — refusing to place this order."
            )
        )
        return
    if is_holiday_temp_ticker(ticker) and not _holiday_temp_gates_active():
        print(
            red(
                f"  {ticker}: holiday temperature markets are shadow-only until "
                "HOLIDAY_TEMP_TRADING_ENABLED=1 and >=20 settled predictions "
                "exist — refusing to place this order."
            )
        )
        return
    if (
        is_rain_daily_ticker(ticker)
        or is_rain_weekend_ticker(ticker)
        or is_rain_holiday_ticker(ticker)
    ):
        print(
            red(
                f"  {ticker}: daily/weekend/holiday rain markets are "
                "track-only — no probability model is ever computed for "
                "these tickers — refusing to place this order."
            )
        )
        return
    if is_storm_order_ticker(ticker) and not _storm_order_gates_active():
        print(
            red(
                f"  {ticker}: hurricane storm-order markets are shadow-only until "
                "STORM_ORDER_TRADING_ENABLED=1 and >=20 settled predictions "
                "exist — refusing to place this order."
            )
        )
        return
    if (
        is_hurricane_ticker(ticker)
        and not is_hurricane_count_ticker(ticker)
        and not is_hurricane_next_event_ticker(ticker)
        and not is_storm_order_ticker(ticker)
    ):
        print(
            red(
                f"  {ticker}: hurricane markets are not supported yet — refusing to place this order."
            )
        )
        return

    # Batch-22 item 5: rain previously had no direct guard here at all --
    # every other shadow-only family (hurricane-count, hurricane-next-event,
    # storm-order, unsupported-hurricane, snow, hourly) refuses outright;
    # rain relied solely on paper.check_position_limits() below, which (a)
    # sits inside a try/except that WARNS and CONTINUES on failure rather
    # than blocking the order, and (b) only runs for action == "buy" (a
    # manual live SELL of a rain ticker was entirely unguarded). Mirrors the
    # snow guard's exact shape immediately below for the same fail-closed
    # reasoning, INCLUDING that same guard's known/accepted tradeoff (opus
    # review, LOW #14): if _rain_gates_active() ever flips back to False
    # (its settled-count bar can drop, not just rise) while a live rain
    # position is genuinely open, this also refuses the manual SELL needed
    # to close it, same as the pre-existing snow guard already does today.
    # Not a regression this fix introduces -- accepted here for the exact
    # same reason the snow guard already accepts it.
    if (
        ticker.upper().startswith(tuple(_KXRAIN_MONTHLY_CITY))
        and not _rain_gates_active()
    ):
        print(
            red(
                f"  {ticker}: monthly rain markets are shadow-only until RAIN_TRADING_ENABLED=1 "
                "and >=20 settled rain predictions exist — refusing to place this order."
            )
        )
        return

    # backlog.txt "RAIN / SNOW / HURRICANE MARKETS" -- Snow Step 2
    # (2026-07-30): kept as its own explicit refuse-outright guard -- an
    # opus review originally added this direct check because relying on
    # check_position_limits() alone fails open on an unhandled exception at
    # that call site; that reasoning applies regardless of whether a model
    # exists (and, per batch-22 item 5 above, now applies to rain too). Now
    # conditional on _snow_gates_active() (shadow-only), not unconditional,
    # matching the model's real state.
    if (
        ticker.upper().startswith(tuple(_KXSNOW_MONTHLY_CITY))
        and not _snow_gates_active()
    ):
        print(
            red(
                f"  {ticker}: monthly snow markets are shadow-only until SNOW_TRADING_ENABLED=1 "
                "and >=20 settled snow predictions exist — refusing to place this order."
            )
        )
        return

    # Hourly-directional temperature markets carried no explicit guard on
    # this path (or in paper.check_position_limits(), or on any other manual
    # placement path) -- unlike rain/snow/hurricane, a KXTEMP*H order could
    # place for real regardless of _hourly_gates_active(). Same fail-closed
    # shape as the hurricane/snow guards just above.
    # batch-52 H-2 (opus review): _hourly_live_ok also excludes Miami
    # specifically -- see its own docstring in weather_markets.py.
    if ticker.upper().startswith(tuple(_KXTEMP_HOURLY_CITY)) and not _hourly_live_ok(
        ticker
    ):
        print(
            red(
                f"  {ticker}: hourly-directional temperature markets are shadow-only "
                "until HOURLY_TRADING_ENABLED=1 and >=20 settled hourly predictions "
                "exist — refusing to place this order."
            )
        )
        return

    # batch-40 "Between-bracket calibration design", Decision 2: same
    # fail-closed direct guard as the families above -- this function places
    # a real order unconditionally even when analysis fails, so relying
    # solely on check_position_limits() below is not enough.
    # is_between_bracket_ticker classifies by the "-B<val>" ticker suffix,
    # not a prefix, since between shares its ticker family with above/below.
    if is_between_bracket_ticker(ticker) and not _between_metar_gates_active():
        print(
            red(
                f"  {ticker}: between-bracket markets are shadow-only until "
                "BETWEEN_TRADING_ENABLED=1 and >=20 settled between-bracket "
                "predictions exist — refusing to place this order."
            )
        )
        return

    from execution_log import log_order, log_order_result, was_recently_ordered

    if was_recently_ordered(ticker, side):
        print(
            yellow(
                f"  [Warning] A {side.upper()} order for {ticker} was placed in the last 10 minutes."
            )
        )
        confirm2 = input(yellow("  Place another anyway? (y/N): ")).strip().lower()
        if confirm2 != "y":
            print(dim("  Cancelled to avoid duplicate."))
            return

    # Fetch market and run full analysis so the trade is tracked identically to auto-placed trades.
    _market = None
    _analysis = None
    _enriched = None
    try:
        print(dim("  Fetching market and running analysis..."))
        _market = client.get_market(ticker)
        if _market:
            _enriched = enrich_with_forecast(_market)
            _analysis = analyze_trade(_enriched)
    except Exception as _ae:
        _log.warning("cmd_order: analysis failed for %s: %s", ticker, _ae)
        print(
            yellow(
                f"  Analysis failed ({_ae}) — order will not be tracked in Brier/P&L."
            )
        )

    # Single derivation of this order's target_date, hoisted here (batch-60
    # item 2) so the live-buy freshness guard below and the paper-mirror
    # place_paper_order() call further down read the SAME value instead of
    # computing it twice from the same two sources. Prefers
    # _enriched["_date"] and falls back to _analysis["target_date"] for
    # KXRAIN*M tickers, whose _date is always None by design -- see
    # backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2, whose
    # review-caught fallback this preserves verbatim.
    _date_raw_ord = _enriched.get("_date") if _enriched else None
    _target_date_ord: date | None = (
        _date_raw_ord if isinstance(_date_raw_ord, date) else None
    )
    if _target_date_ord is None and _analysis and _analysis.get("target_date"):
        try:
            _target_date_ord = date.fromisoformat(_analysis["target_date"])
        except (ValueError, TypeError):
            pass
    _target_date_str_ord = _target_date_ord.isoformat() if _target_date_ord else None

    # A LAST-RESORT date for the freshness guard ONLY -- deliberately not
    # folded into _target_date_str_ord above (opus round-2 review, L6).
    #
    # Why it exists (F7): the two sources above both go dark exactly where
    # the new future-side bound matters most. KXRAIN*M/KXDENSNOWM tickers
    # have _date=None by design, and when analyze_trade gates a market OUT
    # -- precisely what it does to a far-future one -- _analysis is None
    # too. So `order buy KXRAINNYCM-27JUN-5.0 ...`, ~300 days out and far
    # beyond RAIN_MAX_DAYS_OUT+3, reached validate_target_date_freshness as
    # a bare None and placed a REAL order unchecked. The daily-temp
    # families the tests exercise hide this: their _enriched["_date"]
    # survives a gated analysis.
    #
    # Why it is scoped to the guard: this is close_time's raw UTC date,
    # while every other consumer of _target_date_str_ord (the trade record,
    # check_position_limits' city/date grouping key, Brier logging) expects
    # the CITY-LOCAL convention -- order_executor._get_live_open_positions
    # explicitly rejected the raw-UTC form for that reason, and
    # weather_markets._days_out_from_close_time documents it as
    # systematically the following day for an ET-calendar-date market.
    # Feeding it to those consumers would trade a missing value for a
    # subtly wrong one. The guard is the one consumer that only needs an
    # order-of-magnitude sanity check, and its 3-day grace absorbs the
    # one-day skew outright.
    _guard_date_str_ord = _target_date_str_ord
    if _guard_date_str_ord is None and _market and _market.get("close_time"):
        try:
            _guard_date_str_ord = (
                datetime.fromisoformat(
                    str(_market["close_time"]).replace("Z", "+00:00")
                )
                .date()
                .isoformat()
            )
        except (ValueError, TypeError):
            pass

    if _analysis:
        _fp = _analysis.get("forecast_prob", 0)
        _mp = _analysis.get("market_prob", 0)
        _ne = _analysis.get("net_edge", 0)
        _kl = _analysis.get("kelly", 0)
        _meth = _analysis.get("method", "?")
        _model_side = "YES" if _fp > _mp else ("NO" if _fp < _mp else "NEUTRAL")
        print(
            f"\n  Model: {_fp:.1%}  Market: {_mp:.1%}  "
            f"Edge: {_ne:+.1%}  Kelly: {_kl:.1%}  Method: {_meth}"
        )
        print(f"  Model recommends: {_model_side}  |  You are placing: {side.upper()}")
        if (side == "yes" and _fp < _mp) or (side == "no" and _fp > _mp):
            print(
                yellow("  [Warning] Your side is opposite to the model recommendation.")
            )

    print(
        f"\n  {bold(action.upper())}  {int(count)} × {ticker}  {bold(side.upper())}  @ ${price:.4f}"
    )
    confirm = input(yellow("  Confirm? (y/N): ")).strip().lower()
    if confirm != "y":
        print(dim("  Cancelled."))
        return

    # Gate on the client's own base_url, not a KALSHI_ENV read — see
    # trading_gates.LiveTradingGate.check()'s docstring: a separate env-var
    # read here could disagree with the gate's own notion of prod-ness if
    # they came from different sources. Passing `client` through removes
    # that entirely. `!= DEMO_BASE` (not `== PROD_BASE`) so a client missing
    # base_url entirely defaults to requiring the gate rather than silently
    # skipping it (2026-07-09 follow-up review).
    from kalshi_client import DEMO_BASE

    # Captured once here (not re-derived later) so the post-fill recording
    # below routes through execution_log/LivePositionStore instead of
    # paper.place_paper_order() for a genuine live order -- see backlog.txt
    # "MANUAL cmd_order LIVE ORDERS..." entry: silently absorbing a real
    # fill into the paper ledger let the automated protective-exit scanner
    # abandon an unmanaged real position on the exchange while believing it
    # had closed it.
    _is_live = getattr(client, "base_url", None) != DEMO_BASE

    if _is_live:
        from trading_gates import pre_live_trade_check

        try:
            pre_live_trade_check(client)
        except RuntimeError as _gate_err:
            print(red(f"  Live trading gate blocked: {_gate_err}"))
            return

    # Batch-22 item 1: _place_live_order (the automated live path) gates
    # every entry on 3 execution_log-backed hard stops (daily live loss,
    # daily live spend, max open live positions) in addition to the shared
    # LiveTradingGate above -- this manual path had none of the three, so
    # repeated manual buy invocations faced no live daily-loss halt, no cap
    # on cumulative same-day live dollars, and no cap on concurrent live
    # positions opened via this path specifically. Mirrors
    # _place_live_order's own gate order (steps 1/1b/2) and, like the
    # position-limit check just below, only for "buy" -- these are all
    # ADDED-exposure caps; applying them to "sell" would block an exit
    # exactly when the account is already at/over a limit and most needs to
    # reduce it (same reasoning as the check_position_limits scoping below).
    #
    # Opus review follow-up, accepted as documented rather than changed:
    # (F10) these gates run after the analysis fetch and the operator's own
    # "Confirm? (y/N)" prompt further up -- a confirmed order can still get
    # refused here. Moving them earlier would mean computing _is_live before
    # this function's existing analysis/confirm flow, a larger reorder for a
    # UX-only cost (a wasted confirm click, not a correctness or financial-
    # risk issue -- the refusal itself is unaffected by where it runs).
    # (F11) mirrors only _place_live_order's steps 1/1b/2 (loss/spend/open-
    # count), not step 3's max_trade_dollars size cap -- deliberate: this
    # manual path lets the operator specify an explicit count, unlike the
    # automated Kelly-sized path step 3 exists to bound; auto-capping the
    # operator's own explicit size here would fight that intent rather than
    # add safety.
    # (F12) an UNMATCHED live sell (no tracked position for this ticker/side
    # -- the `elif action == "sell":` branch further down) reaches Kalshi
    # with none of these 3 checks either, same as every "sell" -- pre-
    # existing, unrelated to this fix (these gates only ever apply to
    # "buy"). Real risk assessed as low: Kalshi itself rejects a sell that
    # would open a new short position rather than reduce an existing one,
    # so this can only ever reduce/close real exposure, never add it.
    if _is_live and action == "buy":
        # Batch-60 item 2 (backlog.txt "LIVE cmd_order BUY NEVER VALIDATES
        # target_date FRESHNESS BEFORE PLACING A REAL ORDER"): the paper-
        # mirror branch further down gets place_paper_order()'s own
        # target_date guard for free, so until now the manual LIVE buy --
        # which never touches place_paper_order at all -- had strictly
        # WEAKER date validation than the automated paper path, on the one
        # path that spends real money. Same shared helper, not a second
        # hand-written copy, so the two can't drift.
        try:
            from paper import validate_target_date_freshness as _vtdf_ord

            _vtdf_ord(ticker, _guard_date_str_ord)
        except ValueError as _stale_err:
            print(red(f"  {_stale_err}"))
            return

        import execution_log as _execution_log_ord

        _live_cfg_ord = _load_live_config()
        if _execution_log_ord.get_today_live_loss() >= _live_cfg_ord.get(
            "daily_loss_limit", float("inf")
        ):
            print(
                red(
                    f"  Daily live loss limit ${_live_cfg_ord.get('daily_loss_limit', 'inf')} "
                    "reached — refusing to place this order."
                )
            )
            return
        from utils import MAX_DAILY_SPEND as _MAX_DAILY_SPEND_ORD

        if _execution_log_ord.get_today_live_spend() >= _MAX_DAILY_SPEND_ORD:
            print(
                red(
                    f"  Daily live spend cap ${_MAX_DAILY_SPEND_ORD:.0f} reached — "
                    "refusing to place this order."
                )
            )
            return
        _max_open_ord = _live_cfg_ord.get("max_open_positions", 10)
        if order_executor._count_open_live_orders() >= _max_open_ord:
            print(
                red(
                    f"  Max open live positions {_max_open_ord} reached — "
                    "refusing to place this order."
                )
            )
            return

    # Position-limit check (city/date, directional, correlated-group caps) —
    # previously enforced on the auto-trade and _quick_paper_buy manual paths
    # but not here, letting the primary manual LIVE-order path stack
    # unlimited exposure on an already-capped city/date. Only for "buy" —
    # check_position_limits treats qty*price as ADDED exposure, so applying
    # it to "sell" (which REDUCES a held position) would hard-block exits
    # exactly when the account is already overexposed and most needs to exit.
    if action == "buy":
        try:
            from paper import check_position_limits as _cpl_order

            _city_ord = _enriched.get("_city") if _enriched else None
            # Batch-60 item 2 adjacency: this used to re-derive the date from
            # _enriched["_date"] ALONE, without the KXRAIN*M fallback the
            # hoisted _target_date_str_ord carries -- so a monthly-rain order
            # reached check_position_limits with target_date_str=None and its
            # city/date, directional, and correlated-group caps were all
            # silently skipped. That contradicted both the fallback's own
            # stated purpose ("so a manual live order gets the same real
            # exposure-cap/correlation grouping key the automated path
            # already has, not a silent None") and check_position_limits'
            # own docstring, which claims those caps "are no longer provably
            # skipped for this ticker family". The original fix added the
            # fallback to the place_paper_order call only and missed the
            # exposure-cap consumer it was written for.
            #
            # Dormant today -- check_position_limits refuses every KXRAIN*M
            # ticker outright while _rain_gates_active() is false, so the
            # grouping key is never reached. It starts mattering the day
            # RAIN_TRADING_ENABLED=1, which is exactly when a newly-graduated
            # family would otherwise inherit "all clear" on caps nothing had
            # ever applied to it.
            _limit_check_ord = _cpl_order(
                ticker,
                int(count),
                price,
                city=_city_ord,
                target_date_str=_target_date_str_ord,
                side=side,
                client=client,
            )
            if not _limit_check_ord.get("ok", True):
                print(
                    red(
                        f"  Position limit check failed: {_limit_check_ord.get('reason', 'limit exceeded')}"
                    )
                )
                return
        except Exception as _limit_exc_ord:
            _log.warning(
                "cmd_order: check_position_limits failed for %s, skipping limit check: %s",
                ticker,
                _limit_exc_ord,
            )

    # A live SELL that matches a currently-tracked open live position closes
    # it (mirrors order_executor._exit_live_position's closes_position_id
    # convention) rather than opening a new one -- resolved BEFORE log_order
    # so closes_position_id can be set on this same row, the same way
    # _exit_live_position sets it upfront. Matched by exact (ticker, side);
    # no match (e.g. reducing a position this bot has no live row for) is a
    # deliberate fail-open — the order still reaches the real exchange
    # either way, just recorded as a fresh live entry (closes_position_id=
    # None) instead of being silently mislabeled or routed into the paper
    # ledger.
    _live_close_position: dict | None = None
    # Batch-60 item 4: the full match list, not just its head -- the
    # settlement site below cascades the filled count across it oldest-first.
    # Initialized out here so that site can read it unconditionally.
    _live_open_matches: list[dict] = []
    if _is_live and action == "sell":
        # Defensive: a DB read failure here must not block placing the real
        # sell order -- per _exit_live_position's own established reasoning,
        # "blocking an exit is exactly backwards when the account already
        # holds a position that needs to close." Falling through with no
        # match is safe (opus review, 2026-08-17): it just routes into the
        # already-defensive "no matching position" branch below.
        try:
            _live_open_matches = [
                _p
                for _p in order_executor._get_live_open_positions()
                if _p["ticker"] == ticker and _p.get("side", "yes") == side
            ]
        except Exception as _lookup_err:
            _log.warning(
                "cmd_order: live position lookup failed for %s, proceeding "
                "without a match: %s",
                ticker,
                _lookup_err,
            )
            _live_open_matches = []
        if _live_open_matches:
            _live_close_position = _live_open_matches[0]
            if len(_live_open_matches) > 1:
                # Opus review (2026-08-17), NEW-M1: multiple open live
                # positions can legally share a ticker+side (see
                # order_executor.py's own _get_live_open_positions callers).
                # This used to close only the OLDEST one regardless of how
                # many contracts actually sold -- batch-60 item 4 replaced
                # that with a FIFO cascade at the settlement site below, so
                # a sell spanning more than one tracked position now settles
                # each in turn instead of leaving the remainder marked open
                # with contracts that no longer exist on the exchange.
                # closes_position_id still names only this first row (the
                # schema supports exactly one referenced row per exit), so
                # the operator warning stays: the linkage is narrower than
                # what the cascade actually settled.
                print(
                    yellow(
                        f"  [Warning] {len(_live_open_matches)} tracked live "
                        f"positions exist for {ticker} {side} -- this sell "
                        "is applied oldest-first across them, but only the "
                        f"oldest (#{_live_close_position['id']}) is recorded "
                        "as this order's closes_position_id."
                    )
                )

    # Needed for a live position to actually be MANAGEABLE once it surfaces
    # via _get_live_open_positions(): positions._passes_exit_gates fails
    # CLOSED (never exits) on a missing close_time, and
    # _check_live_model_exits skips any position with entry_prob None --
    # both silently None before this fix since cmd_order never passed them.
    # Only available when the analysis fetch above succeeded. Opus review
    # (2026-08-17), NEW-M5: the earlier "Analysis failed" warning only says
    # "order will not be tracked in Brier/P&L" -- true but understates it
    # now that a failed analysis on a LIVE buy means the resulting position
    # has NO automated stop-loss/breakeven coverage at all, not just missing
    # accuracy tracking. Say so explicitly for the case that actually
    # matters (a live order proceeding with no close_time).
    if _is_live and action == "buy" and not _market:
        print(
            yellow(
                "  [Warning] No market data was fetched, so this live position "
                "will have NO close_time recorded -- the automated stop-loss/"
                "breakeven scanner will never exit it. Monitor and close it "
                "manually if needed."
            )
        )
    # Captured once (not re-derived at the place_order call below) so the
    # client_order_id computed here for the pre-log and the one
    # place_order() derives internally are guaranteed to match -- both must
    # see the identical cycle value. Batch-22 item 2: pre-computed and
    # stored in response BEFORE the API call so a crash between this pre-log
    # and the log_order_result calls below leaves a row
    # _recover_pending_orders can still reconcile against Kalshi, instead of
    # a dead-end 'sent' status. See kalshi_client.compute_client_order_id's
    # own docstring.
    _cycle = order_executor._current_forecast_cycle()
    _cmd_order_cid = compute_client_order_id(
        ticker,
        side,
        action,
        int(count),
        price,
        # Must match the actual time_in_force the place_order() call below
        # will use for this same _is_live branch.
        "immediate_or_cancel" if _is_live else "good_till_canceled",
        _cycle,
    )
    row_id = log_order(
        ticker,
        side,
        int(count),
        price,
        # AUD-0003: order_type mirrors the actual time_in_force this order
        # is placed with, matching the convention every order_executor.py
        # call site already uses ("limit"=maker/GTC, "market"=taker/IOC) --
        # order_executor._poll_pending_orders' settlement-fee selection
        # depends on this being accurate. Live orders here are always IOC
        # (see the client.place_order call below); non-live (paper/demo)
        # orders get client.place_order's own GTC default.
        order_type=("market" if _is_live else "limit"),
        live=_is_live,
        response={"client_order_id": _cmd_order_cid},
        closes_position_id=(
            _live_close_position["id"] if _live_close_position else None
        ),
        close_time=_market.get("close_time") if _market else None,
        entry_prob=_analysis.get("forecast_prob") if _analysis else None,
        forecast_cycle=_cycle,
    )
    _placed_order: dict | None = None
    # Only mirror what actually filled — a resting/partially-filled order was
    # previously recorded as `count` contracts fully filled, distorting
    # paper P&L, exposure-cap accounting, and Brier tracking until the
    # market settles (or forever, if it never fills).
    # fill_count_fp is a fixed-point-formatted STRING (e.g. "2.00"), not an
    # int — int("2.00") raises ValueError, which crashed cmd_order right
    # here on every real order response (filled or resting) and skipped
    # paper-trade recording entirely. Reuse order_executor's parser rather
    # than reinventing it.
    #
    # Live orders are placed immediate-or-cancel (never resting) -- opus
    # review (2026-08-17) found that a resting GTC order's raw Kalshi status
    # ("resting") has no path to ever being recognized as a manageable
    # position: only order_executor._exit_live_position's automated exits
    # set closes_position_id, and the general poller that later resolves a
    # still-resting order (_poll_pending_orders/_recover_pending_orders) has
    # no awareness of closes_position_id at all, so a resting cmd_order sell
    # would leave the position it was meant to close orphaned forever. IOC
    # resolves synchronously in this same call (matching
    # _exit_live_position's own model exactly) -- confirmed via
    # AskUserQuestion this is an acceptable, deliberate trading-behavior
    # change for the manual live path specifically (it can no longer place a
    # patient resting limit order). Demo/paper mode keeps the prior GTC
    # default -- unaffected either way, since the paper ledger doesn't
    # depend on Kalshi's status vocabulary at all.
    _filled_count = 0
    try:
        # cycle= threads through to the idempotency key (kalshi_client.py's
        # place_order deterministically derives it from ticker+side+action+
        # count+price+cycle) -- omitting it (as this code did before the
        # 2026-08-17 opus review) falls back to a random UUID, so a manual
        # retry of a failed/uncertain cmd_order call gets no server-side
        # dedup protection the automated paths already have. Reuses the same
        # _cycle captured above (not re-derived here) so this call's own
        # internally-computed client_order_id matches the one already
        # pre-logged.
        if _is_live:
            result = client.place_order(
                ticker,
                side,
                action,
                int(count),
                price,
                time_in_force="immediate_or_cancel",
                cycle=_cycle,
            )
        else:
            result = client.place_order(
                ticker, side, action, int(count), price, cycle=_cycle
            )
    except OrderStatusUnknownError as _unk_e:
        # AUD-0007: reconciliation itself couldn't confirm either way -- do
        # NOT mark 'failed' (every dedup guard excludes it, so a real live
        # position could be re-orderable and permanently untracked). Keep
        # dedup blocking a retry; _recover_pending_orders re-checks this row
        # via client_order_id once the API is healthy again.
        log_order_result(
            row_id,
            status="unknown",
            error=str(_unk_e),
            response={"client_order_id": _unk_e.client_order_id},
        )
        print(red(f"  Order outcome unknown: {_unk_e}"))
        raise
    except Exception as e:
        log_order_result(row_id, status="failed", error=str(e))
        print(red(f"  Order failed: {e}"))
        raise

    # Opus review follow-up (AUD-0007, round 2): this whole block used to
    # sit inside the SAME try as the placement call above -- a bookkeeping-
    # only failure (e.g. a locked DB) here would have wrongly marked a REAL
    # live order 'failed', re-opening the exact dedup blind spot this fix
    # exists to close (this was the one call site the round-1/round-2 narrow-
    # the-try pass missed entirely). Caught in its own try below instead of
    # re-raising -- unlike the placement try above, the order genuinely DID
    # land on the exchange by this point, so cmd_order must not report
    # failure to the operator; the pre-logged 'pending' row is already safe
    # per _recover_pending_orders' no-order_id handling if this write fails.
    order = result.get("order", result)
    _placed_order = order
    _filled_count = order_executor._to_fill_count(order.get("fill_count_fp")) or 0
    # Kalshi's real status enum is resting/canceled/executed -- there is
    # no "filled". Storing the raw string directly (as this code did
    # before the 2026-08-17 opus review caught it) means
    # execution_log.get_filled_unsettled_live_orders()'s hardcoded
    # `status = 'filled'` filter NEVER matches, so a real live position
    # would never surface to the protective-exit scanner regardless of
    # everything else this fix does. Translate through the same
    # vocabulary every other live-order call site in order_executor.py
    # already uses. A still-None result (raw status "resting" — only
    # possible in demo/paper mode now that live orders are IOC) is
    # recorded as "pending", matching _recover_pending_orders'
    # established convention for an unresolved order.
    _internal_status = (
        order_executor._kalshi_status_to_internal(
            order.get("status", ""), _filled_count
        )
        or "pending"
    )
    try:
        # fill_quantity recorded at placement time — every other live-order
        # call site in order_executor.py does the same (e.g.
        # _exit_live_position, _reprice_or_cancel_pending_orders) since
        # _get_live_open_positions() falls back to the full requested
        # `quantity` when fill_quantity is NULL, which would silently track
        # a live BUY that only partial-filled at its full requested size.
        log_order_result(
            row_id,
            status=_internal_status,
            response=order,
            fill_quantity=_filled_count,
        )
    except Exception as _bk_exc:
        print(
            yellow(
                "  [Warning] Order placed on exchange but local bookkeeping "
                f"failed: {_bk_exc} — check execution_log manually."
            )
        )
    print(green(f"  Order placed: {order.get('order_id', '')}"))
    print(f"  Status: {order.get('status')}  Filled: {order.get('fill_count_fp', 0)}")

    if _internal_status != "filled":
        print(
            yellow(
                f"  Order {(_placed_order or {}).get('status', _internal_status)} — "
                "nothing filled, not recording a trade."
            )
        )
        return
    _record_count = min(_filled_count, int(count))

    if _is_live:
        # A live fill needs its POSITION recorded via
        # execution_log/LivePositionStore, not paper.place_paper_order() --
        # log_order above already recorded this fill's own row (live=True,
        # closes_position_id set for a matched sell). A sell that closes a
        # tracked live position also needs record_live_exit_fill so that
        # position's row is marked settled with fee-adjusted P&L, the same
        # way order_executor._exit_live_position does for the automated
        # path — otherwise it would sit "open" in execution_log forever
        # even though it was just closed for real on the exchange, and the
        # next cron/watch cycle's protective-exit scan would try to exit it
        # again.
        if _live_close_position is not None:
            try:
                import execution_log as _execution_log_mod
                from execution_log import (
                    record_live_early_exit,
                    record_live_exit_fill,
                    set_exit_row_attribution,
                )

                # Batch-60 item 4 (backlog.txt "Live cmd_order sell only
                # closes the oldest of multiple tracked live positions
                # sharing the same ticker+side"): this used to hand the
                # WHOLE filled count to the oldest match alone.
                # record_live_exit_fill clamps to that position's own
                # quantity, so a sell spanning two positions (e.g. 10 sold,
                # oldest holds 4) fully closed the oldest and left the other
                # 6 marked open in execution_log with no contracts behind
                # them on the exchange -- overstating open exposure and
                # inviting the protective-exit scanner to try selling them
                # again. Now the fill is consumed oldest-first across every
                # match, matching what actually executed.
                #
                # That entry deferred itself pending its root-cause
                # prerequisite (exposure caps blind to execution_log), which
                # is now [RESOLVED 2026-08-18] -- re-decided rather than
                # inheriting the old "no independent action recommended".
                _remaining_fill = _record_count
                _cascade_pnl = 0.0
                _settled_notes: list[str] = []
                _cascade_err: Exception | None = None

                def _reread_open_match(_pid: int) -> dict | None:
                    """This position's CURRENT tracked state, or None if it
                    is genuinely gone/settled. Used to tell apart the two
                    very different things a RuntimeError from
                    record_live_exit_fill can mean -- see the handler below.

                    RAISES on a read failure rather than returning None
                    (opus round-3 review, L1). execution_log.get_order_by_id
                    swallows every exception and returns None itself, which
                    would make a transient DB error indistinguishable from
                    "row gone" -- and "row gone" is the branch that skips
                    the position UNDIMINISHED, moving a still-open
                    position's whole share onto the next match at the wrong
                    cost basis. That is precisely the bug MEDIUM-1 exists to
                    prevent, reintroduced through a different door. Reading
                    the row directly lets a real failure propagate to the
                    caller's stop-the-cascade path, which is the
                    fail-visible direction the rest of this handler uses.
                    """
                    with _execution_log_mod._conn() as _con:
                        _row = _con.execute(
                            "SELECT settled_at, fill_quantity, quantity, price "
                            "FROM orders WHERE id = ?",
                            (_pid,),
                        ).fetchone()
                    if not _row or _row["settled_at"]:
                        return None
                    _q = int(_row["fill_quantity"] or _row["quantity"] or 0)
                    if _q <= 0:
                        return None
                    return {
                        "id": _pid,
                        "quantity": _q,
                        "entry_price": _row["price"],
                    }

                for _match in _live_open_matches:
                    if _remaining_fill <= 0:
                        break
                    if int(_match.get("quantity") or 0) <= 0:
                        continue

                    # Settle against this match's CURRENT size, retrying once
                    # if a concurrent writer moved it under us.
                    #
                    # Opus round-2 review (MEDIUM-1) killed the previous
                    # premise here, which was that record_live_exit_fill
                    # raises RuntimeError for "exactly one cause". It raises
                    # from two places with two different meanings, and its
                    # PARTIAL branch's message ("was already settled by a
                    # concurrent writer") is misleading: that branch also
                    # fires when record_live_partial_exit finds
                    # COALESCE(fill_quantity, quantity) < filled_count, i.e.
                    # the position is STILL OPEN with real contracts, just
                    # smaller than our snapshot. Skipping it outright then
                    # shifted its whole share onto the next match at the
                    # WRONG cost basis -- reproduced: P1=20@0.40 reduced to 2
                    # by cron mid-flight, P2=10@0.50, sell 10 booked all 10
                    # against 0.50 instead of 2@0.40 + 8@0.50, and the tax
                    # export recorded the wrong basis. That is worse than the
                    # abort it replaced, which at least left the discrepancy
                    # visible.
                    _pnl_i: float | None = None
                    _full_i = False
                    _take = 0
                    _cur = _match
                    for _attempt in (0, 1):
                        _take = min(_remaining_fill, int(_cur.get("quantity") or 0))
                        if _take <= 0:
                            break
                        try:
                            _pnl_i, _full_i = record_live_exit_fill(_cur, _take, price)
                            break
                        except RuntimeError as _raced_err:
                            _pnl_i = None
                            try:
                                _cur_now = _reread_open_match(int(_match["id"]))
                            except Exception as _reread_err:
                                # Cannot tell settled-from-reduced, and
                                # guessing either way risks mis-attribution
                                # -- stop and say so (L1).
                                _cascade_err = _reread_err
                                _log.warning(
                                    "cmd_order: could not re-read live position "
                                    "#%s after a contended exit (%s) -- stopping "
                                    "the cascade with %d of %d contracts "
                                    "unattributed",
                                    _match.get("id"),
                                    _reread_err,
                                    _remaining_fill,
                                    _record_count,
                                )
                                break
                            if _cur_now is None:
                                # Genuinely settled by the other writer.
                                # These contracts were never ours to
                                # attribute, so the fill moves to the next
                                # match UNDIMINISHED (do not decrement).
                                _log.warning(
                                    "cmd_order: live position #%s was settled "
                                    "by a concurrent writer (%s) -- skipping "
                                    "it and applying this fill to the next "
                                    "match",
                                    _match.get("id"),
                                    _raced_err,
                                )
                                break
                            if _attempt == 1:
                                # Still contended after one retry: stop
                                # rather than spin against a writer that is
                                # actively moving this row.
                                _cascade_err = _raced_err
                                _log.warning(
                                    "cmd_order: live position #%s kept moving "
                                    "under this exit (%s) -- stopping the "
                                    "cascade with %d of %d contracts "
                                    "unattributed",
                                    _match.get("id"),
                                    _raced_err,
                                    _remaining_fill,
                                    _record_count,
                                )
                                break
                            # Still open, just smaller -- retry against its
                            # real current size so this match still absorbs
                            # its own share at its own entry price.
                            _log.warning(
                                "cmd_order: live position #%s was reduced to "
                                "%d by a concurrent writer -- retrying this "
                                "exit against its current size",
                                _match.get("id"),
                                _cur_now["quantity"],
                            )
                            _cur = _cur_now
                        except Exception as _match_err:
                            # Any OTHER failure is of unknown cause, so stop
                            # rather than re-attributing this position's
                            # contracts to the next one: the sell DID execute
                            # on the exchange, but silently settling someone
                            # else's row with them would corrupt attribution
                            # worse than leaving the remainder for manual
                            # reconciliation.
                            _cascade_err = _match_err
                            _log.warning(
                                "cmd_order: settling live position #%s failed "
                                "(%s) -- stopping the exit cascade with %d of "
                                "%d contracts unattributed",
                                _match.get("id"),
                                _match_err,
                                _remaining_fill,
                                _record_count,
                            )
                            break

                    if _cascade_err is not None:
                        break
                    if _pnl_i is None:
                        # Raced away entirely (or nothing left to take from
                        # this row): move on without consuming the fill.
                        continue

                    _remaining_fill -= _take
                    _cascade_pnl += _pnl_i
                    _settled_notes.append(
                        f"#{_cur['id']} {'closed' if _full_i else 'partially closed'}"
                    )
                    if not _full_i:
                        # AUD-0028: record_live_exit_fill's partial branch
                        # only settles the POSITION row via
                        # record_live_partial_exit, correctly leaving it open
                        # at its reduced size -- but that means THIS sell
                        # order's own row (row_id) is never settled, so its
                        # P&L never gets its own tax-CSV row and never counts
                        # toward get_live_pnl_summary. Mirrors
                        # order_executor._exit_live_position's identical
                        # partial-fill branch, which makes this exact second
                        # call onto its own log_id for the same reason.
                        # Reachable at most once per cascade: a partial means
                        # the fill ran out inside this position, so the loop
                        # exits on the next iteration's _remaining_fill check.
                        #
                        # Repoint the row FIRST (opus review, F2):
                        # closes_position_id was fixed to the OLDEST match
                        # before placement, but the leg whose P&L is about
                        # to land on this row is the LAST one touched. Left
                        # stale, export_live_tax_csv's self-join reports
                        # this leg against the wrong position's entry price
                        # and counts the whole cascade's fill as this leg's
                        # quantity (a 4+6 cascade exported 14 contracts
                        # disposed for a 10-contract sale). A no-op in the
                        # single-match case, where both values already
                        # agree.
                        try:
                            if not set_exit_row_attribution(
                                row_id, int(_cur["id"]), _take
                            ):
                                # Opus round-2 review (L3): a False return
                                # means a concurrent writer settled this row
                                # first, which also makes the
                                # record_live_early_exit below a silent
                                # no-op -- so without this the partial leg's
                                # P&L would vanish with no log line at all
                                # (the except only fires on a raise).
                                _log.warning(
                                    "cmd_order: sell row #%d was already "
                                    "settled by a concurrent writer -- the "
                                    "partial exit of position #%s (pnl=%.4f) "
                                    "is not recorded on it; check "
                                    "execution_log",
                                    row_id,
                                    _cur["id"],
                                    _pnl_i,
                                )
                            record_live_early_exit(
                                row_id, price, "manual_close", _pnl_i
                            )
                        except Exception as _own_row_err:
                            _log.warning(
                                "cmd_order: partial exit of position #%d "
                                "succeeded but settling this sell order's own "
                                "row #%d failed: %s — its P&L will be missing "
                                "from tax export/pnl summary until manually "
                                "corrected",
                                _cur["id"],
                                row_id,
                                _own_row_err,
                            )
                if _settled_notes:
                    print(
                        green(
                            f"  Live position{'s' if len(_settled_notes) > 1 else ''} "
                            f"{', '.join(_settled_notes)} via manual sell — "
                            f"pnl=${_cascade_pnl:+.2f}"
                        )
                    )
                if _cascade_err is not None:
                    print(
                        yellow(
                            "  [Warning] Position bookkeeping stopped early: "
                            f"{_cascade_err} — {_remaining_fill} of "
                            f"{_record_count} sold contracts are not attributed "
                            "to any tracked position; check execution_log."
                        )
                    )
                elif _remaining_fill > 0:
                    # The sell exceeded everything this bot tracks for the
                    # ticker+side (or every match raced away). The old code
                    # clamped and said nothing at all; the cascade can
                    # actually measure the shortfall.
                    #
                    # Opus round-2 review (MEDIUM-2): the first version of
                    # this said the leftover was "recorded on this order's
                    # row only", which was categorically false. Reaching
                    # here requires that no leg was partial (a partial
                    # zeroes the remainder), and row_id is settled ONLY
                    # inside that partial branch -- so row_id was sitting at
                    # settled_at=NULL/pnl=NULL, which excludes it from
                    # export_live_tax_csv, get_live_pnl_summary,
                    # get_live_settlement_streak AND (via its non-NULL
                    # closes_position_id) get_filled_unsettled_live_orders.
                    # The contracts were recorded precisely nowhere, on the
                    # one screen an operator uses to reconcile a real sale.
                    #
                    # Now genuinely settled, reusing the unmatched-sell
                    # shape this file already established further down for
                    # the no-match-at-all case: pnl=0.0 is an explicit
                    # placeholder (there is no tracked entry price for these
                    # contracts), and export_live_tax_csv labels
                    # exit_reason='unmatched_sell' rows
                    # "unmatched_sell_unknown_pnl" with an empty pnl cell
                    # rather than a misleading 0.00, while the rolled-up
                    # summaries exclude them from their SUMs.
                    from execution_log import record_live_early_exit_with_retry

                    # Make this row byte-identical in SHAPE to the
                    # no-match-at-all branch further down before settling it
                    # (opus round-3 review): closes_position_id NULL, and
                    # fill_quantity = the unmatched remainder.
                    #
                    # Round 2 settled the row but left both columns as they
                    # were -- closes_position_id still naming the OLDEST
                    # match (set pre-placement, and never rewritten on this
                    # path since set_exit_row_attribution is only called in
                    # the partial branch, which by construction cannot have
                    # run here) and fill_quantity still the WHOLE fill. That
                    # is F2's exact failure shape on the one branch F2's fix
                    # did not cover: export_live_tax_csv joins on
                    # closes_position_id for the entry price and reads
                    # COALESCE(fill_quantity, quantity) for the amount, so a
                    # 4+6 cascade with a 2-contract remainder exported
                    # 4 + 6 + 12 = 22 contracts for a 12-contract sale, with
                    # the oldest position's 0.40 basis reported twice.
                    # Round 2 traded an under-report of 2 for an over-report
                    # of 10 plus a duplicated cost basis.
                    set_exit_row_attribution(row_id, None, _remaining_fill)
                    _leftover_settled = record_live_early_exit_with_retry(
                        row_id, price, "unmatched_sell", 0.0
                    )
                    if _leftover_settled:
                        print(
                            yellow(
                                f"  [Warning] {_remaining_fill} of {_record_count} "
                                "sold contracts exceeded every tracked live "
                                f"position for {ticker} {side} — recorded on this "
                                f"order's own row #{row_id} with P&L unknown (no "
                                "tracked entry price to compute one against)."
                            )
                        )
                    else:
                        # record_live_early_exit_with_retry returns False for
                        # TWO reasons and they need different advice (opus
                        # round-3 review, L2): retries genuinely exhausted (a
                        # sentinel row was written), or a concurrent writer
                        # settled this row first (no sentinel, and the row is
                        # in fact fine). Sending an operator to an empty
                        # sentinel file to hand-settle an already-settled row
                        # is worse than saying nothing. Re-read to tell them
                        # apart rather than guessing.
                        _row_after = None
                        try:
                            _row_after = _execution_log_mod.get_order_by_id(row_id)
                        except Exception:
                            _row_after = None
                        if _row_after and _row_after.get("settled_at"):
                            print(
                                yellow(
                                    f"  [Warning] {_remaining_fill} of "
                                    f"{_record_count} sold contracts exceeded every "
                                    f"tracked live position for {ticker} {side}. "
                                    f"Row #{row_id} was settled by a concurrent "
                                    "writer, so it is recorded — but under that "
                                    "writer's reason, not as an unmatched "
                                    "remainder. Worth an eyeball in execution_log."
                                )
                            )
                        else:
                            print(
                                red(
                                    f"  [Warning] {_remaining_fill} of "
                                    f"{_record_count} sold contracts exceeded every "
                                    f"tracked live position for {ticker} {side}, and "
                                    f"row #{row_id} could NOT be self-settled after "
                                    "retrying — those contracts are recorded "
                                    "nowhere. See "
                                    "execution_log_unsettled_exit_rows.json and "
                                    "settle this row manually."
                                )
                            )
            except Exception as _live_rec_err:
                _log.warning(
                    "cmd_order: record_live_exit_fill failed for %s: %s",
                    ticker,
                    _live_rec_err,
                )
                print(
                    yellow(
                        "  [Warning] Order filled but position bookkeeping failed: "
                        f"{_live_rec_err} — check execution_log manually."
                    )
                )
        elif action == "sell":
            # Opus review (2026-08-17), NEW-H1: this row was written above as
            # live=True/status='filled'/settled_at=NULL/closes_position_id=
            # None -- exactly the shape execution_log.get_filled_unsettled_live_orders()
            # treats as an OPEN LONG POSITION. Left alone, a real reduce-only
            # sell (of a position this bot doesn't track) would be
            # misread by the protective-exit scanner as a brand-new entry it
            # just bought, and it would later place a REAL exit sell against
            # it -- worse than the original bug this fix resolves, not just
            # a repeat of it. Immediately mark the row settled (pnl unknown
            # -- there is no tracked entry_price to compute one against, so
            # 0.0 is a neutral placeholder, not a real P&L claim) so it can
            # never be mistaken for an open position, while still preserving
            # the historical record that this live sell happened.
            # AUD-0026: bounded retry + a persistent sentinel flag on
            # exhausted retries, instead of a single attempt behind a bare
            # warning log -- a failed write here leaves this row in the
            # exact phantom-open-position shape this whole branch exists to
            # prevent (live=1/status='filled'/settled_at=NULL/
            # closes_position_id=NULL).
            from execution_log import record_live_early_exit_with_retry

            _settled = record_live_early_exit_with_retry(
                row_id, price, "unmatched_sell", 0.0
            )
            if _settled:
                print(
                    yellow(
                        f"  Live sell recorded (execution_log row #{row_id}, live=True) "
                        f"— no matching tracked live position for {ticker}; nothing to "
                        "close. P&L unknown (no tracked entry) -- recorded, not left "
                        "open as a phantom position."
                    )
                )
            else:
                # Opus review follow-up (AUD-0026): the prior version printed
                # the reassuring "not left open as a phantom position"
                # message UNCONDITIONALLY, even when every retry attempt
                # failed -- reporting success on exactly the failure this
                # branch exists to guard against. Row #row_id genuinely IS
                # still live=1/status='filled'/settled_at=NULL right now.
                print(
                    red(
                        f"  [Warning] Live sell for {ticker} was placed, but "
                        f"row #{row_id} could NOT be self-settled after "
                        "retrying -- it is still recorded as an OPEN position "
                        "and the automated exit scanner may try to sell it "
                        "again. See execution_log_unsettled_exit_rows.json "
                        "and settle this row manually."
                    )
                )
        else:
            print(
                green(
                    f"  Live order recorded (execution_log row #{row_id}, live=True)."
                )
            )

    # Brier/prediction-accuracy tracking runs regardless of live vs. paper —
    # independent of which ledger the fill's own P&L lands in.
    if _analysis and _market and _enriched:
        try:
            _city = _enriched.get("_city")
            # Batch-60 item 2: this block previously re-derived the target
            # date from the same two sources the live-buy freshness guard
            # above now reads. Hoisted to a single _target_date_str_ord (see
            # its own comment for the KXRAIN*M fallback rationale) so two
            # copies can't drift into validating one value and recording
            # another.
            #
            # Precisely: the guard reads _guard_date_str_ord, which is this
            # same value plus a close_time last resort the booking path
            # deliberately does not get (see that variable's own comment).
            # So the guard can validate a date where this records None, but
            # never a DIFFERENT date -- the direction that matters. An
            # earlier version of this comment claimed they were always
            # identical, which stopped being true when the close_time
            # fallback was scoped to the guard (opus round-3 review).
            _target_date_str = _target_date_str_ord
            _days_out = int(_analysis.get("days_out", 1))

            if not _is_live:
                _trade = place_paper_order(
                    ticker,
                    side,
                    _record_count,
                    price,
                    entry_prob=_analysis.get("forecast_prob"),
                    net_edge=_analysis.get("net_edge"),
                    city=_city,
                    target_date=_target_date_str,
                    method=_analysis.get("method"),
                    model_forecast_means=_analysis.get("model_forecast_means"),
                    forecast_temp=_analysis.get("forecast_temp"),
                    condition_threshold=_analysis.get("condition", {}).get("threshold"),
                    close_time=_market.get("close_time"),
                    days_out=_days_out,
                )
                print(
                    green(
                        f"  Recorded as paper trade #{_trade['id']} for P&L/Brier tracking."
                    )
                )

            try:
                from tracker import log_analysis_attempt as _log_attempt

                _log_attempt(
                    ticker=ticker,
                    city=_city,
                    condition=_analysis.get("condition", {}).get("type", ""),
                    target_date=_target_date_ord,
                    forecast_prob=_analysis.get("forecast_prob", 0.0),
                    market_prob=_analysis.get("market_prob", 0.0),
                    days_out=_days_out,
                    was_traded=True,
                )
            except Exception as _le:
                _log.warning("cmd_order: log_analysis_attempt failed: %s", _le)

            try:
                log_prediction(
                    ticker,
                    _city,
                    _target_date_ord,
                    _analysis,
                    **_prediction_kwargs_from_analysis(_analysis),
                )
            except Exception as _pe:
                _log.warning("cmd_order: log_prediction failed: %s", _pe)

        except Exception as _rec_err:
            _log.warning("cmd_order: trade analysis recording failed: %s", _rec_err)
            print(yellow(f"  [Warning] Could not record trade analysis: {_rec_err}"))


def cmd_cancel(client: KalshiClient, order_id: str):
    """Cancel a resting order by exchange order_id.

    Batch-58 item 1 (backlog L25336): this is the one raw-CLI path into
    kalshi_client.cancel_order -- argv reaches the REST path segment with no
    normalization anywhere in between. The strip() handles the routine
    shell/copy-paste case (a trailing space or newline on a pasted id);
    anything else malformed is rejected by _validate_order_id_format. Every
    OTHER caller of cancel_order is automated and passes an exchange-sourced
    id, so this is the only site that needs a friendly error rather than a
    traceback.

    Opus review (batch-58, M1): the validation is called EXPLICITLY here
    rather than by catching ValueError around client.cancel_order(). Three
    non-format failures inside that call also raise ValueError --
    _check_error_body's 200-with-error-body convention, a
    requests JSONDecodeError (which subclasses ValueError) on any HTML
    gateway/proxy body, and _sign_headers' missing-credentials check -- so a
    try/except around the network call reported "Invalid order_id: Expecting
    value: line 1 column 1" for a 502 and then returned exit code 0. On an
    operator's emergency-cancel path that asserts the id is malformed when
    the truth is "the cancel's outcome is unknown and the order may still be
    resting." Those failures now stay loud and propagate to main()'s
    top-level handler exactly as they did before this batch.
    """
    from kalshi_client import _validate_order_id_format

    order_id = order_id.strip()
    try:
        _validate_order_id_format("order_id", order_id)
    except ValueError as exc:
        print(red(f"  Invalid order_id: {exc}"))
        return
    result = client.cancel_order(order_id)
    print(green(f"Cancelled: {result}"))


def cmd_sync(client: KalshiClient):
    from paper import auto_settle_paper_trades

    print("Syncing settled markets...")
    count = sync_outcomes(client)
    paper = auto_settle_paper_trades(client)
    print(green(f"Done — {count} outcome(s) recorded, {paper} paper trade(s) settled."))


# ── Onboarding wizard ─────────────────────────────────────────────────────────

_ONBOARDED_MARKER = ONBOARDED_MARKER_PATH


def _needs_onboarding() -> bool:
    """Return True if this looks like a first run (no .env or no trades ever placed)."""
    if _ONBOARDED_MARKER.exists():
        return False
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return True
    from paper import get_all_trades

    return len(get_all_trades()) == 0


def cmd_onboard() -> None:
    """5-step interactive onboarding guide for first-time users."""
    print(bold("\n  ══════════════════════════════════════════"))
    print(bold("   Welcome to Kalshi Weather Trader!"))
    print(bold("  ══════════════════════════════════════════"))
    print()
    print("  This tool helps you find and bet on weather")
    print("  prediction markets on Kalshi.com.")
    print()
    print("  Let's get you set up in 5 steps.")
    print(dim("  Press Enter to continue at each step."))

    try:
        # Step 1
        print(bold("\n  ── Step 1: What is this? ─────────────────"))
        print("  Kalshi lets you bet YES or NO on questions")
        print('  like "Will NYC hit 72°F on April 12?"')
        print()
        print("  If you bet YES at 52¢ and you're right,")
        print("  you win 48¢ per contract (minus a 7% fee).")
        print("  If wrong, you lose your 52¢.")
        print()
        print("  This tool uses weather forecast models to")
        print("  find markets where the price seems wrong.")
        input(dim("  [Press Enter]"))

        # Step 2
        print(bold("\n  ── Step 2: API Keys ──────────────────────"))
        print("  To fetch market data, you need a free")
        print("  Kalshi API key.")
        print()
        print("  1. Go to kalshi.com → Account → API Keys")
        print("  2. Create a new key, download the .pem file")
        print("  3. Copy .env.example to .env")
        print("  4. Fill in KALSHI_KEY_ID and path to .pem")
        print()
        input(dim("  Have you done this? (y/skip): "))

        # Step 3
        print(bold("\n  ── Step 3: Reading the Analyze table ─────"))
        print("  Press A from the main menu to see markets.")
        print()
        print("  The table shows:")
        print(f"  {green('★★★')} = Strong opportunity (>25% edge)")
        print(f"  {yellow('★★')}  = Good opportunity (>15% edge)")
        print(f"  {dim('★')}   = Weak opportunity (>10% edge)")
        print()
        print('  "Edge" = how much better our model thinks')
        print("  the odds are vs. what the market charges.")
        input(dim("  [Press Enter]"))

        # Step 4
        print(bold("\n  ── Step 4: Your first paper trade ────────"))
        print("  Paper trading uses fake money ($1,000 to")
        print("  start) so you can practice risk-free.")
        print()
        print("  To place your first trade:")
        print("  1. Press A to Analyze")
        print("  2. Find a ★★★ signal")
        print("  3. Press P → 2 → Buy")
        print("  4. Follow the prompts")
        print()
        print(dim("  Tip: Start with small bets (1-2 contracts)"))
        print(dim("  until you understand how it works."))
        input(dim("  [Press Enter]"))

        # Step 5
        print(bold("\n  ── Step 5: Tracking your performance ─────"))
        print("  After 10+ trades, press K (Backtest) to")
        print("  see how accurate the model has been.")
        print()
        print("  Press R (Brief) each morning for a quick")
        print("  summary of your positions and opportunities.")
        print()
        print("  Press ? anytime for the help guide.")
        input(dim("  [Press Enter]"))

        print(bold("\n  ══════════════════════════════════════════"))
        print(bold("   You're all set! Press Enter for the menu."))
        print(bold("  ══════════════════════════════════════════"))
        input()

    except (KeyboardInterrupt, EOFError):
        print()

    # Write marker so onboarding only runs once
    try:
        _ONBOARDED_MARKER.parent.mkdir(exist_ok=True)
        _ONBOARDED_MARKER.write_text("onboarded")
    except Exception:
        pass


# ── Setup wizard ──────────────────────────────────────────────────────────────


def cmd_setup():
    from climatology import preload_all

    print(bold("\n╔══════════════════════════════════╗"))
    print(bold("║   Kalshi Weather Setup Wizard    ║"))
    print(bold("╚══════════════════════════════════╝\n"))

    # Repo-relative, matching cmd_settings()'s convention -- not CWD-relative,
    # which could target the wrong file entirely if run from elsewhere.
    env_path = Path(__file__).parent / ".env"

    # ── Step 1: Credentials ───────────────────────────────────────────────────
    print(bold("Step 1 of 3 — Kalshi API credentials"))
    print(dim("Get these at: kalshi.com → Account → Settings → API Keys\n"))

    existing_key = os.getenv("KALSHI_KEY_ID", "")
    existing_pem = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
    existing_env = os.getenv("KALSHI_ENV", "demo")

    # L-9: mask the existing Key ID in the prompt (all but last 4 chars) --
    # re-running setup used to echo it in plaintext into terminal scrollback,
    # which can persist in terminal history/screen-recording tools far longer
    # than the .env file itself does.
    _key_id_display = "…" + existing_key[-4:] if len(existing_key) > 4 else existing_key
    key_id = (
        input(f"  Key ID       [{_key_id_display or 'required'}]: ").strip()
        or existing_key
    )
    pem_path = (
        input(
            f"  Private key  [{existing_pem or './kalshi_private_key.pem'}]: "
        ).strip()
        or existing_pem
        or "./kalshi_private_key.pem"
    )
    env_mode = (
        input(f"  Environment  [demo/prod, default={existing_env}]: ").strip().lower()
        or existing_env
    )
    # AUD-0015 follow-up (opus review, batch-09): a typo'd env_mode used to
    # be persisted to .env with no feedback -- safe today (KalshiClient's
    # inverted whitelist now defaults any non-"prod" value to demo), but
    # normalize case first (round-2 review, F10) so "PROD"/"Prod" don't get
    # needlessly warned-and-defaulted like a genuine typo would be.
    # silently. Catch it here instead of letting the wizard finish thinking
    # it configured prod/demo when it configured demo either way.
    if env_mode not in ("demo", "prod"):
        print(
            yellow(
                f"\n  '{env_mode}' isn't 'demo' or 'prod' — defaulting to 'demo' "
                "(a typo here would otherwise silently point at the wrong URL)."
            )
        )
        env_mode = "demo"

    if not key_id:
        print(yellow("\n  No Key ID entered — skipping credential setup."))
        print(dim("  You can still use market data without credentials."))
    else:
        # dotenv.set_key() updates one key in place, preserving every other
        # line -- a plain write_text() of just these 3 keys previously
        # silently destroyed every other .env setting (TRADING_PAUSED,
        # BREAKEVEN_TRIGGER_PCT, risk limits, etc.) whenever setup was
        # re-run on an already-configured .env (found via a deep code
        # review, 2026-07-08).
        from dotenv import set_key as _set_key_setup

        env_path.touch(exist_ok=True)
        _set_key_setup(str(env_path), "KALSHI_KEY_ID", key_id)
        _set_key_setup(str(env_path), "KALSHI_PRIVATE_KEY_PATH", pem_path)
        _set_key_setup(str(env_path), "KALSHI_ENV", env_mode)
        load_dotenv(override=True)
        print(green("  .env saved.\n"))

        # Test connection
        print(bold("  Testing Kalshi connection..."), end=" ", flush=True)
        try:
            client = build_client()
            client.get_balance()
            print(green("OK"))
        except Exception as e:
            print(red(f"FAILED — {e}"))
            print(
                dim("  Check your Key ID and that the .pem file is in the right place.")
            )

    # ── Step 2: Climate history ───────────────────────────────────────────────
    print(bold("\nStep 2 of 3 — Download 30-year climate history"))
    print(
        dim("  This is a one-time download (~10 seconds per city). Cached forever.\n")
    )

    from pathlib import Path as P

    data_dir = P("data")
    data_dir.mkdir(exist_ok=True)
    missing = [c for c in CITY_COORDS if not (data_dir / f"climate_{c}.json").exists()]

    if not missing:
        print(green("  All climate data already cached — nothing to download."))
    else:
        print(f"  Need to download: {', '.join(missing)}")
        go = input("  Download now? (Y/n): ").strip().lower()
        if go != "n":
            for i, city in enumerate(missing, 1):
                print(f"  [{i}/{len(missing)}] {city}...", end=" ", flush=True)
                try:
                    preload_all({city: CITY_COORDS[city]})
                    print(green("done"))
                except Exception as e:
                    print(red(f"failed — {e}"))
        else:
            print(dim("  Skipped — first 'analyze' run will be slower."))

    # ── Step 3: Done ──────────────────────────────────────────────────────────
    print(bold("\nStep 3 of 3 — You're ready!\n"))
    print("  Try these commands:")
    print(f"    {cyan('py main.py')}              — interactive menu")
    print(f"    {cyan('py main.py analyze')}      — find the best trades right now")
    print(f"    {cyan('py main.py watch')}        — live auto-refreshing dashboard")
    print(f"    {cyan('py main.py forecast NYC')} — 7-day weather forecast")
    print()


# ── Help screen ───────────────────────────────────────────────────────────────


def cmd_kill() -> None:
    """Activate the kill switch — stops all automated trading immediately."""
    # Use the shared KILL_SWITCH_PATH (paths.py, re-exported via cron), not a
    # Path(__file__)-relative path — the latter resolves to the wrong data/
    # dir when this command runs from a git worktree (see paths.py's module
    # docstring), silently no-opping the kill switch since every enforcement
    # point (cron.py, trading_gates.py, order_executor.py, alerts.py) reads
    # KILL_SWITCH_PATH.
    kill_path = KILL_SWITCH_PATH
    kill_path.parent.mkdir(exist_ok=True)
    kill_path.touch()
    print(
        red("  Kill switch ACTIVATED. Automated trading will stop at next cron cycle.")
    )
    print(dim("  Run `py main.py resume` to re-enable trading."))


def cmd_resume() -> None:
    """Remove the kill switch — re-enables automated trading. Also clears black swan state."""
    kill_path = KILL_SWITCH_PATH
    cleared_any = False
    if kill_path.exists():
        kill_path.unlink()
        cleared_any = True
    # AUD batch-25 opus-review M5: same fix as web_app.py's api_resume --
    # during a cmd_cron manual override window, the kill switch is parked
    # at kill_path + ".tmp" and restored when the override finishes.
    # Without also clearing that parked copy, resuming mid-override looks
    # like a no-op ("No kill switch active") and the kill switch silently
    # re-arms itself once the in-flight override ends.
    parked = kill_path.with_name(kill_path.name + ".tmp")
    if parked.exists():
        parked.unlink(missing_ok=True)
        cleared_any = True
    if cleared_any:
        print(green("  Kill switch removed. Trading re-enabled."))
    else:
        print(dim("  No kill switch active."))

    # opus-review-caught (2nd round, LOW-1/LOW-3): clear the kill-switch
    # alert's cooldown UNCONDITIONALLY (not gated on the file having
    # existed) -- resume is the operator's explicit "I've handled this"
    # signal. Without this, a second, genuinely NEW kill-switch engagement
    # within the still-warm 6h window from a prior one would silently not
    # alert (batch-24 item 1's 3 kill-switch check sites -- cron.py,
    # trade_cycle.py, main.py's own -- all share this one cooldown_key).
    try:
        from notify import clear_system_cooldown as _clear_ks_cooldown

        _clear_ks_cooldown("kill_switch")
    except Exception:
        pass

    # P10.2: also clear black swan state file if present
    try:
        from alerts import clear_black_swan_state as _clear_bs
        from alerts import get_black_swan_status as _bs_status

        bs = _bs_status()
        if bs:
            _clear_bs()  # also clears the "black_swan_halt" cooldown (F1)
            print(
                yellow(
                    f"  Black swan state cleared (was: {bs.get('reason', 'unknown')[:60]})"
                )
            )
        else:
            # opus-review-caught (LOW-2): clear_black_swan_state()'s own
            # cooldown-clear is gated on _BLACK_SWAN_PATH.exists() -- if
            # activate_black_swan_halt()'s own state-file WRITE had failed
            # (logged, not fatal -- see its own try/except) while the kill
            # switch still got engaged and the alert still fired, that gate
            # would never open even after resume. Clear the same cooldown
            # key directly here too, independent of whether the state file
            # itself ever existed.
            from notify import clear_system_cooldown as _clear_bs_cooldown

            _clear_bs_cooldown("black_swan_halt")
    except Exception:
        pass


def cmd_drift() -> None:
    """P10.1: Show Brier score drift analysis — detects slow performance degradation."""
    from tracker import detect_brier_drift

    result = detect_brier_drift()
    _header("Brier Drift Analysis", width=58)
    print(f"  Weeks analyzed : {result['weeks_analyzed']}")
    if result["early_brier"] is not None:
        status = red("DRIFT DETECTED") if result["drifting"] else green("OK")
        print(f"  Early Brier    : {result['early_brier']:.4f}")
        print(f"  Recent Brier   : {result['recent_brier']:.4f}")
        delta = result["delta"]
        delta_str = f"{delta:+.4f}"
        print(
            f"  Delta          : {red(delta_str) if result['drifting'] else dim(delta_str)}"
        )
        print(f"  Status         : {status}")
    print(f"\n  {result['message']}\n")


def cmd_version_compare() -> None:
    """P9.1: Compare Brier scores across strategy versions (edge_calc_version)."""
    from tracker import get_brier_by_version

    versions = get_brier_by_version()
    _header("Strategy Version Performance", width=50)
    if not versions:
        print(dim("  No version-stamped predictions settled yet."))
        print(dim("  Predictions will be stamped once trading resumes.\n"))
        return
    print(f"  {'Version':<12} {'Brier':>8} {'Samples':>9}")
    print("  " + "─" * 32)
    for v, info in sorted(versions.items()):
        brier_str = f"{info['brier']:.4f}"
        color_fn = (
            green if info["brier"] < 0.20 else (yellow if info["brier"] < 0.25 else red)
        )
        print(f"  {v:<12} {color_fn(brier_str):>8} {info['n']:>9}")
    print()


def cmd_train_bias() -> None:
    """Train ML bias correction models from tracker DB data."""
    from ml_bias import train_all_temperature_scaling, train_bias_model

    print("Training ML bias models (requires 200+ settled trades per city)...")
    models = train_bias_model(min_samples=200)
    if not models:
        print(
            "Not enough data yet for per-city GBM. Keep trading — retrain after 6 months."
        )
    else:
        print(f"Trained GBM models for: {', '.join(sorted(models.keys()))}")

    print("Training per-condition temperature scaling...")
    trained_ts = train_all_temperature_scaling()
    if not trained_ts:
        print(
            "Not enough data for temperature scaling yet (need 35+ global settled trades)."
        )
    else:
        for key, T in sorted(trained_ts.items()):
            print(f"  [{key}] T={T:.4f}")


def cmd_retire_strategies(run: bool = False) -> None:
    """P9.5: Show retired strategy methods; with --run auto-retires failing ones."""
    from tracker import auto_retire_strategies, get_retired_strategies

    if run:
        newly = auto_retire_strategies()
        if newly:
            print(
                red(
                    f"\n  Retired {len(newly)} strategy method(s): {', '.join(newly)}\n"
                )
            )
        else:
            print(
                green("\n  No new strategies retired — all methods within threshold.\n")
            )

    retired = get_retired_strategies()
    _header("Retired Strategies", width=58)
    if not retired:
        print(dim("  No strategies retired yet.\n"))
        return
    print(f"  {'Method':<30} {'Brier':>8} {'Retired At'}")
    print("  " + "─" * 62)
    for method, info in retired.items():
        brier_str = f"{info.get('brier', 0):.4f}"
        retired_at = info.get("retired_at", "")[:19]
        print(f"  {method:<30} {red(brier_str):>8}  {dim(retired_at)}")
    print()


def cmd_unretire_strategy(method: str, pin_hours: float = 72.0) -> None:
    """Manually un-retire a forecasting method that was auto-retired.

    Writes a 72-hour retirement-immunity pin by default so the next cron run
    cannot immediately re-retire the method.  Pass pin_hours=0 to skip the pin.
    """
    from tracker import unretire_strategy

    if unretire_strategy(method, pin_hours=pin_hours):
        if pin_hours > 0:
            print(
                green(
                    f"\n  ✓ Un-retired '{method}' — pinned for {pin_hours:.0f} h "
                    f"(auto-retirement immunity until pin expires).\n"
                )
            )
        else:
            print(green(f"\n  ✓ Un-retired strategy method: {method}\n"))
    else:
        print(red(f"\n  ✗ Method '{method}' was not retired — nothing to undo.\n"))
        from tracker import get_retired_strategies

        retired = get_retired_strategies()
        if retired:
            print(f"  Currently retired: {', '.join(retired.keys())}\n")
        else:
            print("  No strategies are currently retired.\n")


def cmd_config_check() -> None:
    """P10.3: Show current config fingerprint and detect cross-run changes."""
    from utils import check_config_integrity, get_config_fingerprint

    result = check_config_integrity()
    fp = get_config_fingerprint()

    _header("Config Integrity", width=58)
    status = red("CHANGED") if result["changed"] else green("UNCHANGED")
    print(f"  Status         : {status}")
    print(f"  Current hash   : {result['current_hash']}")
    if result["previous_hash"]:
        print(f"  Previous hash  : {result['previous_hash']}")
    if result["changed_keys"]:
        print(f"  Changed keys   : {', '.join(result['changed_keys'])}")
    print()
    print(f"  {'Parameter':<28} {'Value'}")
    print("  " + "─" * 48)
    for k, v in fp.items():
        highlight = bold if k in result.get("changed_keys", []) else dim
        print(f"  {k:<28} {highlight(str(v))}")
    print()


def cmd_readiness(client) -> bool:
    """
    Run pre-live-trading checklist.  Returns True only if ALL gates pass.
    Usage: py main.py readiness
    Exit code: 0 = ready, 1 = not ready.

    Gates:
      1. Brier < 0.23 over last 60 days (needs 50+ trades)
      2. At least 50 settled trades in the last 60 days
      3. Drawdown < 10%
      4. No circuit breaker currently open
    """
    import backtest as _bt

    _header("Live Trading Readiness Check")
    gates: list[tuple[str, bool, str]] = []

    try:
        # run_backtest() returns train_brier/val_brier/n_markets — it has
        # never returned "brier"/"roc_auc"/"n_trades" (no ROC-AUC computation
        # exists anywhere in this codebase). Those wrong keys made every gate
        # below read fabricated 0.0/0 defaults and fail unconditionally.
        # Prefer the held-out validation Brier when there's enough holdout
        # sample (val_brier_unreliable is False below 10 rows); otherwise
        # fall back to the training-set Brier. The ROC-AUC gate is dropped —
        # there's nothing real to check it against.
        bt = _bt.run_backtest(client, days_back=60)
        n = bt.get("n_markets", 0)
        brier = (
            bt.get("val_brier")
            if not bt.get("val_brier_unreliable", True)
            else bt.get("train_brier")
        )
        brier = brier if brier is not None else 1.0
        gates.append(("Brier < 0.23  (60d)", brier < 0.23, f"Brier={brier:.4f}  n={n}"))
        gates.append(("≥50 trades     (60d)", n >= 50, f"n={n}"))
    except Exception as e:
        gates.append(("Backtest", False, f"Error: {e}"))

    try:
        from paper import get_max_drawdown_pct as _gdd

        dd = _gdd()
        gates.append(("Drawdown < 10%", dd < 0.10, f"drawdown={dd:.1%}"))
    except Exception:
        gates.append(("Drawdown", False, "Could not compute"))

    try:
        import time as _time

        from circuit_breaker import flash_crash_cb as _cb

        any_cooldown = any(_time.time() < exp for exp in _cb._cooldowns.values())
        gates.append(
            (
                "Circuit breaker clear",
                not any_cooldown,
                "active cooldowns" if any_cooldown else "clear",
            )
        )
    except Exception:
        gates.append(("Circuit breaker", False, "Could not check"))

    all_pass = True
    for label, passed, detail in gates:
        icon = green("✓ PASS") if passed else red("✗ FAIL")
        print(f"  {icon}  {label:<30} {dim(detail)}")
        if not passed:
            all_pass = False

    print()
    if all_pass:
        print(green("  ✓ ALL GATES PASSED — system is ready for live trading"))
    else:
        print(red("  ✗ NOT READY — fix failing gates before going live"))

    return all_pass


def cmd_code_audit() -> None:
    """P10.4: Feature sprawl audit — list file sizes and orphan cmd_ functions."""
    import ast

    base = Path(__file__).parent
    py_files = sorted(base.glob("*.py"))

    _header("Code Audit", width=62)
    print(f"  {'File':<35} {'Lines':>7} {'Functions':>10}")
    print("  " + "─" * 56)

    total_lines = 0
    all_defined: dict[str, str] = {}  # name → file

    for fp in py_files:
        try:
            src = fp.read_text(encoding="utf-8")
            lines = src.count("\n")
            total_lines += lines
            try:
                tree = ast.parse(src)
                fns = [
                    n.name
                    for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
                ]
                for fn in fns:
                    all_defined[fn] = fp.name
                fn_count = len(fns)
            except SyntaxError:
                fn_count = 0
            flag = (
                red(" !!!") if lines > 3000 else (yellow(" !") if lines > 1000 else "")
            )
            print(f"  {fp.name:<35} {lines:>7}{flag}  {fn_count:>8}")
        except Exception:
            pass

    print(f"\n  Total: {total_lines:,} lines across {len(py_files)} files")

    # Find cmd_ functions defined but not referenced in the dispatch block
    try:
        main_src = (base / "main.py").read_text(encoding="utf-8")
        dispatch_src = main_src[main_src.find("def main(") :]
        defined_cmds = [n for n in all_defined if n.startswith("cmd_")]
        orphans = [c for c in defined_cmds if c not in dispatch_src]
        if orphans:
            print(f"\n  {yellow('Orphan cmd_ functions (not in dispatch):')}")
            for fn in sorted(orphans):
                print(f"    {dim(fn)}  [{all_defined[fn]}]")
        else:
            print(f"\n  {green('All cmd_ functions are referenced in dispatch.')}")
    except Exception:
        pass
    print()


def cmd_signals() -> None:
    """Show the log-only-signal graduation report (backlog.txt "SIGNAL
    GRADUATION IS A CONVENTION" part b) -- real settled-sample counts for
    every registered log-only signal against its sample floor, replacing
    the need to remember and hand-run each signal's own scattered backlog.txt
    prose trigger. Read-only; never wires anything into the live blend."""
    from weather_markets import get_signal_graduation_report

    report = get_signal_graduation_report()
    print(bold("\n  Signal Graduation Report"))
    print(
        dim(
            "  Sample-floor status only -- the correlation check for each "
            "signal is still a manual judgment call (see notes below)."
        )
    )
    print()
    for row in report:
        if row["sample_floor"] is None:
            status = (
                dim(f"{row['count']} samples, no fixed floor")
                if row["count"] is not None
                else dim("no fixed floor")
            )
        elif row["count"] is None:
            status = yellow("count unavailable")
        elif row["floor_cleared"]:
            status = green(f"{row['count']}/{row['sample_floor']} -- floor cleared")
        else:
            status = dim(f"{row['count']}/{row['sample_floor']}")
        print(f"  {bold(row['name'])}")
        print(f"    status: {status}   backlog: {row['backlog_ref']}")
        print(f"    {dim(row['correlation_note'])}")
        print()


def cmd_features() -> None:
    """Show feature importance summary from historical trades."""
    from feature_importance import get_feature_summary

    summary = get_feature_summary()
    if not summary:
        print(dim("  No feature data yet. Features are recorded as trades are placed."))
        return
    print(bold("\n  Feature Importance Summary"))
    print(f"  {'Feature':<30} {'Win Avg':>10} {'Loss Avg':>10} {'Trades':>8}")
    print("  " + "─" * 62)
    for feat, stats in summary.items():
        win_avg = f"{stats['win_avg']:.4f}" if stats["win_avg"] is not None else "N/A"
        loss_avg = (
            f"{stats['loss_avg']:.4f}" if stats["loss_avg"] is not None else "N/A"
        )
        print(f"  {feat:<30} {win_avg:>10} {loss_avg:>10} {stats['total']:>8}")
    print()


def cmd_help() -> None:
    """Print compact quick-reference guide."""
    _header("Quick Reference", width=58)
    lines = [
        ("A", "Analyze ", "Best opportunities right now, sorted by edge"),
        ("T", "Today   ", "What should I do today? Plain-English recommendation"),
        ("W", "Watch   ", "Auto-refreshes every 5 min, alerts on new signals"),
        ("P", "Paper   ", "Simulate trades, track P&L, set price alerts"),
        ("K", "Backtest", "How well has the model done on past markets?"),
        ("R", "Brief   ", "Morning summary: balance, top picks, warnings"),
        ("B", "Browse  ", "See all open markets for a city"),
        ("S", "Settings", "Change edge thresholds, loss limits, fees"),
        ("?", "Help    ", "This screen"),
    ]
    for key, name, desc in lines:
        print(f"  {bold(key)}  {cyan(name)}  {dim(desc)}")

    print(bold("\n  In analyze table:"))
    print(
        f"    {green('★★★')} = strong edge (>25%)   {yellow('★★')} = good (>15%)"
        f"   {dim('★')} = weak (>10%)"
    )
    print("    Edge = how much better our model is vs market price")
    print("    Risk = LOW (market closes soon, data reliable) / HIGH (far out)")

    print(bold("\n  Tips for beginners:"))
    print(
        f"    {dim('-')} Only bet {green('★★★')} signals until you have 20+ settled trades"
    )
    print(f"    {dim('-')} Never bet more than 5% of your balance on one trade")
    print(f"    {dim('-')} Run K Backtest monthly to check the model is still working")


# ── Browse markets ────────────────────────────────────────────────────────────

# Derived from CITY_COORDS so new cities in data/cities.json appear automatically.
_BROWSE_CITIES = sorted(CITY_COORDS.keys())


def cmd_browse(client: KalshiClient) -> None:
    """Browse open markets by city."""
    _header("Browse Markets by City")

    # City picker
    for i, city in enumerate(_BROWSE_CITIES, 1):
        print(f"  {cyan(str(i)):<5} {city}")
    print()
    raw = input(
        dim(f"  Pick a city (1–{len(_BROWSE_CITIES)}, or Enter for all): ")
    ).strip()

    city_filter: str | None = None
    if raw.isdigit() and 1 <= int(raw) <= len(_BROWSE_CITIES):
        city_filter = _BROWSE_CITIES[int(raw) - 1]

    # Fetch markets
    try:
        all_markets = get_weather_markets(client)
    except Exception as _e:
        short_msg = str(_e)[:120]
        print(
            red(
                "  Could not reach Kalshi API. Check your internet connection and try again."
            )
        )
        print(dim(f"  (Error: {short_msg})"))
        return

    if city_filter:
        # Match city name case-insensitively against the _city field
        cf_lower = city_filter.lower()
        markets = [
            m
            for m in all_markets
            if (m.get("_city") or "").lower() == cf_lower
            or cf_lower in (m.get("title") or "").lower()
        ]
        if not markets:
            # Fall back to substring match on ticker
            markets = [
                m for m in all_markets if cf_lower in (m.get("ticker") or "").lower()
            ]
    else:
        markets = all_markets

    if not markets:
        city_label = city_filter or "all cities"
        print(yellow(f"  No open weather markets found for {city_label}."))
        return

    def _market_price_row(i: int, m: dict, analysis: dict | None = None) -> list:
        """Build a single browse table row, optionally with signal columns."""
        from weather_markets import parse_market_price as _pmp

        prices = _pmp(m)
        yes_bid = prices.get("yes_bid") or 0
        yes_ask = prices.get("yes_ask") or 0
        mid = prices.get("mid") or 0

        bid_s = f"${yes_bid:.2f}" if yes_bid > 0 else dim("—")
        ask_s = f"${yes_ask:.2f}" if yes_ask > 0 else dim("—")
        spread = yes_ask - yes_bid if yes_ask > 0 and yes_bid > 0 else None
        spread_s = f"${round(spread, 2):.2f}" if spread is not None else dim("—")
        mid_s = f"${mid:.2f}" if mid > 0 else dim("—")

        raw_last = m.get("last_price_dollars") or m.get("last_price") or 0
        try:
            last_f = float(raw_last)
            if last_f > 1:
                last_f /= 100.0
        except (TypeError, ValueError):
            last_f = 0.0
        last_s = f"${last_f:.2f}" if last_f > 0 else dim("—")

        raw_vol = m.get("volume_fp") or m.get("volume") or m.get("volume_24h_fp") or 0
        try:
            vol_f = float(raw_vol)
        except (TypeError, ValueError):
            vol_f = 0.0
        raw_oi = m.get("open_interest_fp") or m.get("open_interest") or 0
        try:
            oi_f = float(raw_oi)
        except (TypeError, ValueError):
            oi_f = 0.0
        activity = vol_f + oi_f
        vol_s = f"{activity:,.0f}" if activity > 0 else dim("—")

        closes = _format_expiry(m.get("close_time", ""))
        title = (m.get("title") or m.get("ticker", ""))[:36]
        ticker = m.get("ticker", "")

        row = [
            cyan(str(i)),
            ticker,
            title,
            bid_s,
            ask_s,
            spread_s,
            mid_s,
            last_s,
            vol_s,
            closes,
        ]

        if analysis is not None:
            prob = analysis.get("forecast_prob")
            edge = analysis.get("net_edge") or analysis.get("edge") or 0
            side = analysis.get("recommended_side", "")
            prob_s = f"{prob * 100:.0f}%" if prob is not None else dim("—")
            if edge >= 0.10:
                edge_s = green(f"+{edge * 100:.0f}%")
                signal_s = green(f"BUY {side.upper()}" if side else "BUY")
            elif edge >= 0.05:
                edge_s = yellow(f"+{edge * 100:.0f}%")
                signal_s = yellow("MAYBE")
            elif edge <= -0.05:
                edge_s = red(f"{edge * 100:.0f}%")
                signal_s = red("SKIP")
            else:
                edge_s = dim(f"{edge * 100:.0f}%")
                signal_s = dim("SKIP")
            row += [prob_s, edge_s, signal_s]
        return row

    # Build display table
    ticker_list = [m.get("ticker", "") for m in markets]
    rows = [_market_price_row(i, m) for i, m in enumerate(markets, 1)]

    base_headers = [
        "#",
        "Ticker",
        "Title",
        "Bid",
        "Ask",
        "Spread",
        "Mid",
        "Last",
        "Vol+OI",
        "Closes",
    ]

    def _print_table(rows: list, with_signals: bool = False) -> None:
        headers = base_headers + (["Prob", "Edge", "Signal"] if with_signals else [])
        print(tabulate(rows, headers=headers, tablefmt="rounded_outline"))

    _print_table(rows)
    city_label = city_filter or "all cities"
    print(dim(f"\n  {len(markets)} markets — {city_label}"))

    # Action prompt
    analysis_cache: dict[str, dict] = {}

    while True:
        raw2 = input(
            dim(
                "  # for details  A analyze signals  F forecast  C arbitrage  Enter back: "
            )
        ).strip()
        if not raw2:
            return
        if raw2.upper() == "A":
            from concurrent.futures import ThreadPoolExecutor
            from concurrent.futures import as_completed as _as_completed

            print(dim(f"  Scanning {len(markets)} markets…"))

            def _do_analyze(m: dict) -> tuple[str, dict | None]:
                try:
                    enriched = enrich_with_forecast(m)
                    return m.get("ticker", ""), analyze_trade(enriched)
                except Exception:
                    return m.get("ticker", ""), None

            with ThreadPoolExecutor(max_workers=20) as pool:
                futures = {pool.submit(_do_analyze, m): m for m in markets}
                for fut in _as_completed(futures):
                    ticker_key, result = fut.result()
                    if result:
                        analysis_cache[ticker_key] = result

            signal_rows = [
                _market_price_row(i, m, analysis_cache.get(m.get("ticker", "")))
                for i, m in enumerate(markets, 1)
            ]
            _print_table(signal_rows, with_signals=True)
            buys = sum(
                1
                for m in markets
                if (analysis_cache.get(m.get("ticker", "")) or {}).get("net_edge", 0)
                >= 0.10
            )
            print(
                dim(f"\n  {len(markets)} markets — {buys} strong signals (edge ≥10%)")
            )
        elif raw2.upper() == "F":
            if city_filter:
                cmd_forecast(city_filter)
            else:
                city_in = input(
                    dim(f"  City ({'/'.join(CITY_COORDS.keys())}): ")
                ).strip()
                if city_in:
                    cmd_forecast(city_in)
        elif raw2.upper() == "C":
            cmd_consistency(client)
        elif raw2.isdigit() and 1 <= int(raw2) <= len(ticker_list):
            ticker = ticker_list[int(raw2) - 1]
            verbose = input(dim("  Verbose detail? (y/N): ")).strip().lower() == "y"
            cmd_market(client, ticker, verbose=verbose)
        else:
            print(red("  Invalid choice."))


# ── Settings screen ───────────────────────────────────────────────────────────


def cmd_settings(client: KalshiClient | None = None) -> None:  # noqa: ARG001
    """View and edit configurable settings."""
    import importlib

    import utils as _utils_mod

    # Reload to get latest values
    importlib.reload(_utils_mod)

    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        # also check cwd
        env_path_cwd = Path(".env")
        if env_path_cwd.exists():
            env_path = env_path_cwd

    def _read_env() -> dict[str, str]:
        lines: dict[str, str] = {}
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, _, v = line.partition("=")
                    lines[k.strip()] = v.strip()
        return lines

    def _write_env(key: str, value: str) -> None:
        existing = {}
        existing_lines: list[str] = []
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                existing_lines.append(line)
                if "=" in line and not line.strip().startswith("#"):
                    k, _, _ = line.partition("=")
                    existing[k.strip()] = len(existing_lines) - 1

        if key in existing:
            existing_lines[existing[key]] = f"{key}={value}"
        else:
            existing_lines.append(f"{key}={value}")

        env_path.write_text("\n".join(existing_lines) + "\n")

    while True:
        importlib.reload(_utils_mod)
        env_vals = _read_env()
        _header("Settings")

        setting_keys = [
            ("MIN_EDGE", "minimum edge to show in analyze", "0-1"),
            ("STRONG_EDGE", "threshold for STRONG BUY signal", "0-1"),
            (
                "MAX_DAILY_LOSS_PCT",
                "halt trading if down this % today",
                "0-1 excl",
            ),
            ("MAX_POSITION_AGE_DAYS", "warn on positions older than N days", "int"),
            (
                "KALSHI_FEE_RATE",
                "taker fee (reference only — see below)",
                "0-1 excl",
            ),
            (
                "KALSHI_MAKER_FEE_RATE",
                "maker fee — the rate this bot's own trades actually pay",
                "[0-1)",
            ),
            ("KALSHI_ENV", "demo or prod", "demo/prod"),
        ]

        for i, (key, desc, _fmt) in enumerate(setting_keys, 1):
            cur = env_vals.get(key) or str(getattr(_utils_mod, key, "—"))
            print(f"  {cyan(str(i)):<5} {bold(key):<26} {green(cur):<12} {dim(desc)}")

        print()
        print(f"  {cyan('H')}    History        — past predictions + Brier score")
        print(f"  {cyan('E')}    Export data    — save predictions + trades to CSV")
        print(f"  {cyan('W')}    Web dashboard  — local web dashboard (localhost:5000)")
        print(f"  {cyan('X')}    Simulate       — replay historical markets (sandbox)")
        print(f"  {cyan('Y')}    Weekly summary — generate weekly recap")
        print()

        raw = input(dim("  Number to edit, or letter, or Enter to go back: ")).strip()
        if not raw:
            return

        # Letter shortcuts
        if raw.upper() == "H":
            _c = client if client else build_client()
            cmd_history(_c)
            input(dim("\n  Press Enter to return to settings..."))
            continue
        if raw.upper() == "E":
            cmd_export()
            input(dim("\n  Press Enter to return to settings..."))
            continue
        if raw.upper() == "W":
            import subprocess as _sp
            import time as _time
            import webbrowser as _wb

            _bat = Path(__file__).parent / "start.bat"
            if _bat.exists():
                _sp.Popen(["cmd.exe", "/c", "start", "", str(_bat)], shell=False)
                print(green("  Launching web dashboard via start.bat..."))
                _time.sleep(2)
                _wb.open("http://localhost:5173")
            else:
                _c2 = client if client else build_client()
                cmd_web(_c2)
            continue
        if raw.upper() == "X":
            _c3 = client if client else build_client()
            cmd_simulate(_c3)
            input(dim("\n  Press Enter to return to settings..."))
            continue
        if raw.upper() == "Y":
            cmd_weekly_summary()
            input(dim("\n  Press Enter to return to settings..."))
            continue
        if not raw.isdigit() or not (1 <= int(raw) <= len(setting_keys)):
            print(red("  Invalid choice."))
            continue

        idx = int(raw) - 1
        key, desc, fmt = setting_keys[idx]
        cur = env_vals.get(key) or str(getattr(_utils_mod, key, ""))
        new_val = input(dim(f"  {key} [{cur}] ({fmt}): ")).strip()
        if not new_val:
            continue

        # Validate
        valid = True
        if fmt == "0-1":
            try:
                fv = float(new_val)
                if not 0 <= fv <= 1:
                    valid = False
            except ValueError:
                valid = False
        elif fmt == "0-1 excl":
            # Strictly between 0 and 1 -- unlike the inclusive "0-1" format
            # above, this backs a field whose config.py validate() bound is
            # exclusive on both ends (MAX_DAILY_LOSS_PCT: 0 halts on any
            # loss at all, degenerate; 1 can only trip at exactly 100%
            # loss). Writing 0 or 1 here via the menu would otherwise pass
            # this screen but then fail validate() at the next startup.
            try:
                fv = float(new_val)
                if not 0 < fv < 1:
                    valid = False
            except ValueError:
                valid = False
        elif fmt == "[0-1)":
            # Inclusive of 0.0 (unlike "0-1 excl" above) -- backs
            # KALSHI_MAKER_FEE_RATE, whose config.py validate() bound is
            # `0.0 <= x < 1.0`: $0 is the real, expected maker fee for this
            # bot's markets, not an edge case (see config.py's own comment).
            try:
                fv = float(new_val)
                if not 0 <= fv < 1:
                    valid = False
            except ValueError:
                valid = False
        elif fmt == "int":
            try:
                int(new_val)
            except ValueError:
                valid = False
        elif fmt == "demo/prod":
            if new_val not in ("demo", "prod"):
                valid = False

        if not valid:
            print(red(f"  Invalid value for {key} (expected {fmt})."))
            continue

        # M-25: KALSHI_ENV governs which base_url the session's already-built
        # `client` talks to (kalshi_client.py sets base_url once, at construction
        # -- it never re-reads the env). Hot-editing it here would flip this
        # banner to [DEMO]/[PROD] immediately while every live order this
        # session places still goes to whichever URL `client` was built with --
        # a real order can be placed under a DEMO banner. Refuse the in-session
        # edit rather than risk that desync; a restart picks up the new value
        # through the normal build_client() path at process start.
        if key == "KALSHI_ENV":
            print(
                red(
                    "  KALSHI_ENV can't be changed from this menu — it controls "
                    "which server every live order in this session reaches, and "
                    "this session's client was already built with the old value."
                )
            )
            print(
                dim(
                    "  Edit KALSHI_ENV in .env directly, then restart the bot to "
                    "apply it.\n"
                )
            )
            continue

        # H-1: authoritative check -- run the REAL config.BotConfig.
        # validation_errors() against the would-be env (not a re-implementation
        # of its bounds) so this menu can never write a value validate() would
        # then reject at next startup. Temporarily applied to os.environ (not
        # yet written to .env) so validation sees this edit combined with every
        # other current setting, e.g. catches a MIN_EDGE edit that would push
        # it above the existing STRONG_EDGE, not just this field in isolation.
        #
        # Opus review (M-B): comparing the CANDIDATE's error set against a
        # BASELINE taken before the edit, not refusing on ANY candidate error,
        # matters because validate() checks 17 fields but this menu can only
        # edit 7 of them -- an earlier version of this fix refused every edit
        # (even ones that fix the very field the operator came here to fix)
        # whenever some OTHER, unrelated field was already invalid in .env
        # (e.g. a hand-edited KELLY_CAP), permanently deadlocking the menu
        # with no in-app way to recover. Only refuse when the edit introduces
        # a genuinely NEW error; pre-existing unrelated errors are written
        # through and surfaced as a warning instead.
        import config as _config_mod

        _baseline_errors = set(_config_mod.BotConfig.from_env().validation_errors())
        _orig_env_val = os.environ.get(key)
        os.environ[key] = new_val
        _candidate_errors = set(_config_mod.BotConfig.from_env().validation_errors())
        _new_errors = _candidate_errors - _baseline_errors
        if _new_errors:
            if _orig_env_val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = _orig_env_val
            print(red("  Rejected — would produce an invalid configuration:"))
            for _err in sorted(_new_errors):
                print(red(f"  - {_err}"))
            continue
        _preexisting_errors = _candidate_errors & _baseline_errors
        if _preexisting_errors:
            print(
                yellow(
                    "  Note: .env already has unrelated invalid setting(s) this "
                    "edit doesn't fix — consider running `py main.py config`:"
                )
            )
            for _err in sorted(_preexisting_errors):
                print(yellow(f"  - {_err}"))
        # Valid (or no worse than before) -- os.environ[key] already holds
        # new_val; persist it to .env too.

        # Try python-dotenv first
        try:
            from dotenv import set_key as _set_key

            _set_key(str(env_path), key, new_val)
        except Exception:
            _write_env(key, new_val)

        # Reload env + modules
        #
        # Opus review (L-G): load_dotenv(override=True) re-reads the WHOLE
        # .env file, not just `key` -- if an operator hand-edited KALSHI_ENV
        # in a text editor while this process was running, then used Settings
        # to edit any OTHER field, this reload would silently pick up the new
        # KALSHI_ENV into os.environ. _kalshi_env() (env-fresh) would then
        # report the new value while `client.base_url` (fixed at construction)
        # still targets the old one -- the exact M-25 desync, just triggered
        # by an external file edit instead of a direct menu edit. Snapshot and
        # restore KALSHI_ENV across the reload so only an explicit KALSHI_ENV
        # menu edit (refused above) or a process restart can ever change it.
        # Round-2 opus review (M2-2): pass env_path explicitly -- a bare
        # load_dotenv(override=True) does its own upward directory search
        # (python-dotenv's find_dotenv(), anchored to the real call frame,
        # not affected by any test monkeypatching env_path/__file__), which
        # is redundant with -- and in a test, can silently diverge from --
        # the exact file `_set_key`/`_write_env` above just wrote to.
        # Explicit path removes the ambiguity and makes this correctly
        # testable in isolation; behaves identically in real production
        # since env_path IS what find_dotenv() would have resolved to there.
        _preserved_kalshi_env = os.environ.get("KALSHI_ENV")
        load_dotenv(str(env_path), override=True)
        if _preserved_kalshi_env is None:
            os.environ.pop("KALSHI_ENV", None)
        else:
            os.environ["KALSHI_ENV"] = _preserved_kalshi_env
        try:
            importlib.reload(_utils_mod)
            import paper as _paper_mod

            importlib.reload(_paper_mod)
            # reload() only rebinds utils' own module attributes — main.py
            # value-imported MIN_EDGE/STRONG_EDGE at startup (`from utils
            # import MIN_EDGE, STRONG_EDGE`), so without this the Settings
            # screen would show the new value while cmd_today/cmd_brief kept
            # filtering on the stale pre-edit threshold until process restart.
            global MIN_EDGE, STRONG_EDGE
            MIN_EDGE = _utils_mod.MIN_EDGE
            STRONG_EDGE = _utils_mod.STRONG_EDGE
        except Exception:
            pass

        print(green(f"  Updated {key} → {new_val}"))


# ── Alerts manager ────────────────────────────────────────────────────────────


def _cmd_alerts() -> None:
    """Price alert manager — used in the Paper submenu."""
    from alerts import add_alert, get_alerts, remove_alert

    while True:
        _header("Price Alerts")
        active = get_alerts()
        if active:
            print("  Active alerts:")
            for a in active:
                created = (a.get("created_at") or "")[:10]
                direction_sym = "<" if a["direction"] == "below" else ">"
                print(
                    f"  #{a['id']}  {bold(a['ticker']):<35} YES {direction_sym}"
                    f" {a['target_price']:.2f}  {dim(f'(set {created})')}"
                )
        else:
            print(dim("  No active alerts."))

        print()
        print(f"  {cyan('1')}  Add alert")
        print(f"  {cyan('2')}  Remove alert")
        print(dim("  Enter  Back"))
        print()

        sub = input(dim("  Choose (1/2 or Enter): ")).strip()
        if not sub:
            return

        if sub == "1":
            # Add alert flow
            try:
                ticker_in = input(dim("  Ticker: ")).strip().upper()
                if not ticker_in:
                    continue
                dir_in = (
                    input(dim("  Direction (below/above, default below): "))
                    .strip()
                    .lower()
                    or "below"
                )
                if dir_in not in ("below", "above"):
                    print(red("  Direction must be 'below' or 'above'."))
                    continue
                price_raw = input(dim("  Target YES price (0-1): ")).strip()
                if not price_raw:
                    continue
                try:
                    target = float(price_raw)
                    if not 0 < target < 1:
                        print(red("  Price must be between 0 and 1."))
                        continue
                except ValueError:
                    print(red("  Enter a decimal like 0.35"))
                    continue
                a = add_alert(ticker_in, target, dir_in)
                direction_sym = "<" if dir_in == "below" else ">"
                print(
                    green(
                        f"  Alert set: {a['ticker']} YES {direction_sym} {target:.2f}"
                    )
                )
            except (KeyboardInterrupt, EOFError):
                print()

        elif sub == "2":
            if not active:
                print(dim("  No active alerts to remove."))
                continue
            try:
                id_raw = input(dim("  Alert # to remove (q to cancel): ")).strip()
                if id_raw.lower() == "q":
                    continue
                try:
                    aid = int(id_raw)
                except ValueError:
                    print(red("  Enter an alert number."))
                    continue
                removed = remove_alert(aid)
                if removed:
                    print(green(f"  Alert #{aid} removed."))
                else:
                    print(red(f"  Alert #{aid} not found."))
            except (KeyboardInterrupt, EOFError):
                print()


# ── Walk-forward test ─────────────────────────────────────────────────────────


def cmd_walkforward(client: KalshiClient) -> None:
    """Run a walk-forward validation and display stability metrics."""
    from backtest import run_walk_forward

    _header("Walk-Forward Validation")
    print(dim("  Scoring settled predictions from local DB..."))
    try:
        result = run_walk_forward(client)
    except Exception as e:
        print(red(f"  Walk-forward test failed: {e}"))
        return

    windows = result.get("windows", [])
    if not windows:
        print(
            yellow(
                "  No data found in the walk-forward windows.\n"
                "  This usually means there are no settled markets in the last 180 days.\n"
                "  Try running: py main.py backtest --days 365"
            )
        )
        return

    avg_brier = result.get("avg_brier")
    avg_win_rate = result.get("avg_win_rate")
    stability_score = result.get("stability_score")
    trend = result.get("trend", "")

    brier_s = (
        green(f"{avg_brier:.4f}")
        if avg_brier is not None and avg_brier < 0.18
        else yellow(f"{avg_brier:.4f}")
        if avg_brier is not None and avg_brier < 0.25
        else red(f"{avg_brier:.4f}")
        if avg_brier is not None
        else dim("—")
    )
    wr_s = (
        green(f"{avg_win_rate:.1%}")
        if avg_win_rate is not None and avg_win_rate > 0.55
        else f"{avg_win_rate:.1%}"
        if avg_win_rate is not None
        else dim("—")
    )
    stab_s = (
        green(f"{stability_score:.3f}")
        if stability_score is not None and stability_score > 0.7
        else yellow(f"{stability_score:.3f}")
        if stability_score is not None and stability_score > 0.5
        else red(f"{stability_score:.3f}")
        if stability_score is not None
        else dim("—")
    )
    trend_s = (
        (
            green(trend)
            if "improv" in trend.lower()
            else red(trend)
            if "degrad" in trend.lower()
            else dim(trend)
        )
        if trend
        else dim("—")
    )

    wf_rows = [
        ["Avg Brier", brier_s],
        ["Avg Win Rate", wr_s],
        ["Stability Score", stab_s],
        ["Trend", trend_s],
    ]
    print(tabulate(wf_rows, headers=["Metric", "Value"], tablefmt="rounded_outline"))

    # ── Calibration curve from real logged predictions ───────────────────────
    # This shows WHERE the Brier score is coming from — which probability buckets
    # are miscalibrated and in which direction.  Unlike backtest (which replays
    # synthetic archive data), this uses the actual probabilities logged at trade time.
    #
    # Split multiday vs sameday: ml_bias.py trains separate temperature-scaling T
    # values for each population, and a merged view can hide opposite-signed biases
    # that cancel out in the mean (see tracker.get_multiday_calibration_cli() /
    # get_sameday_calibration_cli()).
    def _print_calibration_block(title: str, calib: dict) -> None:
        if calib["n"] < 10:
            return
        print(bold(f"\n  ── {title} Calibration Curve (predicted vs actual) ──\n"))
        print(dim("  Bucket    Predicted   Actual    N    Bias      Status"))
        print(dim("  " + "─" * 56))
        for _bucket in calib["calibration_buckets"]:
            _avg_p = _bucket["predicted_mean"]
            _avg_a = _bucket["actual_rate"]
            _n = _bucket["n"]
            _bias = _avg_p - _avg_a
            _status = (
                red(f"  LOW {abs(_bias):.0%}")
                if _bias < -0.10
                else yellow(f"  low {abs(_bias):.0%}")
                if _bias < -0.05
                else red(f"  HIGH {_bias:.0%}")
                if _bias > 0.10
                else yellow(f"  high {_bias:.0%}")
                if _bias > 0.05
                else green("  OK")
            )
            print(
                f"  {_avg_p * 100:>5.0f}%     {_avg_p * 100:>6.1f}%   {_avg_a * 100:>6.1f}%  {_n:>3}  {_bias * 100:>+6.1f}%{_status}"
            )

        _mean_p = (
            sum(b["predicted_mean"] * b["n"] for b in calib["calibration_buckets"])
            / calib["n"]
        )
        _mean_a = (
            sum(b["actual_rate"] * b["n"] for b in calib["calibration_buckets"])
            / calib["n"]
        )
        _sys_bias = _mean_p - _mean_a
        _sys_str = (
            red(
                f"  Model predicts {abs(_sys_bias):.1%} TOO LOW on average — buys NO on events that actually happen."
            )
            if _sys_bias < -0.08
            else red(
                f"  Model predicts {_sys_bias:.1%} TOO HIGH on average — buys YES on events that don't happen."
            )
            if _sys_bias > 0.08
            else green("  No significant systematic bias detected.")
        )
        print(f"\n{_sys_str}")
        print(
            dim(
                f"  Mean predicted: {_mean_p:.1%}  |  Mean actual: {_mean_a:.1%}  |  N={calib['n']}"
            )
        )

    try:
        from tracker import get_multiday_calibration_cli, get_sameday_calibration_cli

        _print_calibration_block("Multiday", get_multiday_calibration_cli())
        _print_calibration_block("Sameday", get_sameday_calibration_cli())
    except Exception as _cal_exc:
        _log.debug("cmd_walkforward: calibration curve failed: %s", _cal_exc)

    # ── Per-condition breakdown ────────────────────────────────────────────────
    # Separate axis from the split above (condition_type, not days_out) — kept on
    # the original merged query since it isn't part of the multiday/sameday split.
    try:
        import sqlite3 as _sql

        from tracker import DB_PATH as _DB_PATH

        # NOT wired to tracker's shared exclusion registry, deliberately
        # (batch-57 opus-review finding M5). This is a sixth hand-written
        # condition_type predicate in the codebase, but it is not a duplicate
        # of the five batch-57 consolidated: those all feed a POOLED statistic,
        # where a shadow family's rows contaminate a shared number. This query
        # GROUPS BY condition_type downstream, so each family lands in its own
        # bucket and nothing is pooled -- the shadow exclusion would remove
        # rows without fixing any contamination.
        #
        # Its 'between' drop IS questionable on its own terms: this is billed
        # as a per-condition Brier breakdown, yet it omits one of the three
        # temperature conditions, so 'between' never appears in a comparison
        # whose whole purpose is per-condition. Left unchanged here (it alters
        # `py main.py walkforward` output) and filed in backlog.txt as
        # "CMD_WALKFORWARD'S PER-CONDITION BRIER SILENTLY DROPS 'BETWEEN'".
        _calib_rows = (
            _sql.connect(str(_DB_PATH))
            .execute(
                """
            SELECT p.our_prob, p.condition_type, o.settled_yes
            FROM predictions p
            JOIN outcomes_valid o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL AND o.settled_yes IS NOT NULL
              AND (p.condition_type IS NULL OR p.condition_type != 'between')
            """
            )
            .fetchall()
        )

        if len(_calib_rows) >= 10:
            from collections import defaultdict

            _cond: dict = defaultdict(list)
            for _p, _ct, _a in _calib_rows:
                _cond[_ct or "unknown"].append((float(_p), int(_a)))
            if len(_cond) > 1:
                print(bold("\n  Per-condition Brier:"))
                for _ct, _items in sorted(
                    _cond.items(),
                    key=lambda x: -sum((p - a) ** 2 for p, a in x[1]) / len(x[1]),
                ):
                    _b_ct = sum((p - a) ** 2 for p, a in _items) / len(_items)
                    _avg_p_ct = sum(p for p, _ in _items) / len(_items)
                    _avg_a_ct = sum(a for _, a in _items) / len(_items)
                    _b_str = (
                        red(f"{_b_ct:.4f}")
                        if _b_ct > 0.25
                        else yellow(f"{_b_ct:.4f}")
                        if _b_ct > 0.18
                        else green(f"{_b_ct:.4f}")
                    )
                    print(
                        f"    {_ct:10s}  Brier={_b_str}  pred={_avg_p_ct:.1%}  actual={_avg_a_ct:.1%}  N={len(_items)}"
                    )
    except Exception as _cal_exc2:
        _log.debug("cmd_walkforward: per-condition breakdown failed: %s", _cal_exc2)

    # Offer to update learned weights from tracker MAE data (not win-rates — those
    # are a different format and must not overwrite {model: weight} dicts).
    city_win_rates = result.get("city_win_rates", {})
    if city_win_rates:
        print(
            f"\n  Walk-forward learned win rates for {len(city_win_rates)} city/type(s)."
        )
        try:
            save_choice = (
                input(dim("  Update tracker-derived model weights? (Y/n): "))
                .strip()
                .lower()
            )
            if save_choice != "n":
                # #25/#118: update model weights from tracker MAE data (correct format)
                # Do NOT call save_learned_weights(city_win_rates) — win rates are
                # floats, not {model: weight} dicts, and would corrupt the weight file.
                try:
                    from weather_markets import update_learned_weights_from_tracker

                    tracker_weights = update_learned_weights_from_tracker()
                    if tracker_weights:
                        print(
                            green(
                                f"  MAE-derived weights updated for {len(tracker_weights)} cities."
                            )
                        )
                    else:
                        print(
                            dim(
                                "  No tracker data available yet — keeping existing weights."
                            )
                        )
                except Exception:
                    pass
                print(green("  Walk-forward results logged."))
        except (KeyboardInterrupt, EOFError):
            print()


# ── Walk-Forward Backtesting (paper trade history) ───────────────────────────


def cmd_walk_forward() -> None:
    """Run walk-forward backtest on historical paper trades."""
    import json

    from backtest import run_paper_walk_forward

    result = run_paper_walk_forward()
    if result is None:
        print("Not enough settled trades for walk-forward (need 50+).")
        return

    std_str = f"{result['std_brier']}" if result["std_brier"] is not None else "\u2014"
    print(f"\nWalk-Forward Backtest ({result['n_folds']} folds)")
    print(f"Mean out-of-sample Brier: {result['mean_brier']} \u00b1 {std_str}")
    print()
    print(f"{'Test Period':<25} {'N Train':>8} {'N Test':>8} {'Brier':>8}")
    print("-" * 55)
    for fold in result["folds"]:
        brier_str = f"{fold['brier']:.4f}" if fold["brier"] is not None else "\u2014"
        print(
            f"{fold['test_period']:<25} {fold['n_train']:>8} {fold['n_test']:>8} {brier_str:>8}"
        )

    out_path = WALK_FORWARD_RESULTS_PATH
    out_path.write_text(json.dumps(result, indent=2))
    print(f"\nSaved to {out_path}")


# ── Weekly PDF report ─────────────────────────────────────────────────────────


def cmd_report() -> None:
    """Generate a weekly PDF/text report and print the output path."""
    from pdf_report import generate_weekly_report

    _header("Weekly Report")
    print(dim("  Generating weekly report...\n"))
    try:
        out_path = generate_weekly_report()
        print(green(f"  Report saved → {out_path}"))
    except Exception as e:
        print(red(f"  Failed to generate report: {e}"))


# ── Blend-weight calibration ──────────────────────────────────────────────────


_CALIBRATE_DATA_DIR: "Path | None" = None  # overridable in tests


def cmd_calibrate() -> None:
    """Recompute seasonal and per-city blend weights from settled predictions."""

    from calibration import calibrate_and_save
    from tracker import DB_PATH

    data_dir = _CALIBRATE_DATA_DIR if _CALIBRATE_DATA_DIR is not None else DATA_DIR
    data_dir.mkdir(exist_ok=True)

    print("Running blend-weight calibration from settled predictions…")
    print(f"  Database: {DB_PATH}")

    try:
        seasonal, city, condition = calibrate_and_save(DB_PATH, data_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"\nCalibration skipped — could not read DB: {exc}")
        print(
            "(The predictions table may be missing ensemble_prob/nws_prob/clim_prob columns.)"
        )
        print("Run the app normally to populate predictions, then re-run calibrate.")
        return

    seasonal_path = data_dir / "seasonal_weights.json"
    city_path = data_dir / "city_weights.json"
    condition_path = data_dir / "condition_weights.json"

    if seasonal:
        print(f"\nSeasonal weights ({len(seasonal)} seasons calibrated):")
        for season, w in sorted(seasonal.items()):
            print(
                f"  {season:8s}: ensemble={w['ensemble']:.2f}  clim={w['climatology']:.2f}  nws={w['nws']:.2f}"
            )
    else:
        print(
            "\nSeasonal weights: insufficient data for all seasons — using hardcoded defaults."
        )

    if city:
        print(f"\nCity weights ({len(city)} cities calibrated):")
        for c, w in sorted(city.items()):
            print(
                f"  {c:12s}: ensemble={w['ensemble']:.2f}  clim={w['climatology']:.2f}  nws={w['nws']:.2f}"
            )
    else:
        print("\nCity weights: insufficient data for any city — using defaults.")

    if condition:
        print(f"\nCondition weights ({len(condition)} condition types calibrated):")
        for ctype, w in sorted(condition.items()):
            print(
                f"  {ctype:10s}: ensemble={w['ensemble']:.2f}  clim={w['climatology']:.2f}  nws={w['nws']:.2f}"
            )
    else:
        print(
            "\nCondition weights: insufficient data — using city/seasonal/hardcoded defaults."
        )

    print(f"\nWritten to: {seasonal_path}")
    print(f"           {city_path}")
    print(f"           {condition_path}")

    import weather_markets as _wm

    _wm._CONDITION_WEIGHTS.clear()
    _wm._CONDITION_WEIGHTS.update(condition)

    # Per-city Platt scaling (requires 200+ settled predictions per city)
    try:
        import sqlite3 as _sqlite3

        import safe_io as _safe_io
        import tracker as _tracker
        from ml_bias import train_platt_per_city as _train_platt

        # batch-57 item 2: exclusion sourced from tracker's canonical registry
        # rather than a fifth hardcoded copy of the 6-tuple. Permanent
        # _ALWAYS_EXCLUDED_CONDITION_TYPES, not the gate-coupled
        # _excluded_brier_condition_types(): Platt scaling fits a per-city
        # temperature-probability calibration curve written to
        # data/platt_models.json and consumed by
        # weather_markets._load_platt_models() -- the scale-mismatch class
        # batch-06's opus-review finding M5 kept permanent, so a shadow
        # family graduating to live must NOT start feeding this fit. Same 6
        # members as the literal it replaces: no behaviour change.
        _cond_clause, _cond_params = _tracker._condition_type_not_in_sql(
            _tracker._ALWAYS_EXCLUDED_CONDITION_TYPES
        )
        with _sqlite3.connect(str(DB_PATH)) as _con:
            _con.row_factory = _sqlite3.Row
            _platt_rows = [
                dict(r)
                for r in _con.execute(
                    "SELECT p.city, p.our_prob, o.settled_yes "
                    "FROM multiday_predictions p JOIN outcomes_valid o ON p.ticker = o.ticker "
                    "WHERE o.settled_yes IS NOT NULL AND p.our_prob IS NOT NULL"
                    f"  AND {_cond_clause}",
                    _cond_params,
                ).fetchall()
            ]
        platt = _train_platt(_platt_rows, min_samples=50)
        if platt:
            _platt_path = data_dir / "platt_models.json"
            _safe_io.atomic_write_json(
                {city: list(ab) for city, ab in platt.items()}, _platt_path
            )
            print(green(f"\nPlatt models trained for: {', '.join(sorted(platt))}"))
            print(f"  Written to: {_platt_path}")
            import weather_markets as _wm

            _wm._PLATT_MODELS = None  # invalidate cache so next call reloads
        else:
            print(dim("\nPlatt: need 200+ settled trades per city (not yet)"))
    except Exception as _exc:
        print(dim(f"\nPlatt calibration skipped: {_exc}"))

    # METAR lock-in beta calibration (requires >=10 settled same-day lock-ins
    # in the minority class). Separate from Platt above: METAR-locked
    # predictions are observation-derived, not model-blend outputs, and
    # analyze_trade's METAR branch bypasses Platt/GBM/T-scaling entirely --
    # see backlog.txt's METAR calibration entry. fit_and_save_metar_
    # calibration() is the same shared fit-and-persist function cron.py's
    # weekly auto-retrain calls, so this command and the weekly cycle can't
    # drift out of sync with each other.
    try:
        from ml_bias import fit_and_save_metar_calibration as _fit_save_metar_cal

        _metar_cal = _fit_save_metar_cal()
        if _metar_cal is not None:
            _a, _b, _c = _metar_cal
            print(
                green(
                    f"\nMETAR lock-in calibration trained: a={_a:.3f} b={_b:.3f} c={_c:.3f}"
                )
            )
            print(f"  Written to: {METAR_CALIBRATION_PATH}")
        else:
            print(
                dim(
                    "\nMETAR calibration: need >=10 settled same-day lock-ins "
                    "in the minority class (not yet)"
                )
            )
    except Exception as _metar_exc:
        print(dim(f"\nMETAR calibration skipped: {_metar_exc}"))

    # P1-9: generate learned_weights.json from tracker inverse-MAE data
    try:
        from weather_markets import update_learned_weights_from_tracker as _ulwft

        lw = _ulwft()
        if lw:
            print(f"\nLearned weights updated for: {', '.join(sorted(lw))}")
            lw_path = data_dir / "learned_weights.json"
            print(f"  Written to: {lw_path}")
        else:
            print(
                dim(
                    "\nLearned weights: insufficient tracker data (need 20+ obs per model per city)"
                )
            )
    except Exception as _lw_exc:
        print(dim(f"\nLearned weights skipped: {_lw_exc}"))

    # Global temperature scaling — single-parameter fit that corrects systematic
    # probability bias (e.g. the NWF cold bias that makes predictions run ~18%
    # below actual settlement rates).  T > 1 pushes probabilities toward 0.5;
    # T < 1 pushes toward extremes.  Works reliably on 35+ settled trades.
    print()
    try:
        from ml_bias import train_all_temperature_scaling as _train_all_ts

        trained = _train_all_ts()
        if not trained:
            print(
                dim(
                    "Temperature scaling: need 35+ global settled predictions "
                    "(not yet — run again after more trades settle)."
                )
            )
        else:
            for key, T in sorted(trained.items()):
                label = f"[{key}]" if key != "global" else "[global]"
                if abs(T - 1.0) < 0.05:
                    print(
                        dim(
                            f"Temperature scaling {label}: T={T:.3f} — well-calibrated."
                        )
                    )
                elif T > 1:
                    print(
                        green(
                            f"Temperature scaling {label}: T={T:.3f} — compressing toward 0.5 "
                            f"(predictions were running too extreme)."
                        )
                    )
                else:
                    print(
                        green(
                            f"Temperature scaling {label}: T={T:.3f} — pushing toward extremes "
                            f"(predictions were too conservative)."
                        )
                    )
            print(
                dim(
                    "  Applied automatically per condition type in analyze_trade on next run."
                )
            )
    except ImportError:
        print(
            dim(
                "Temperature scaling skipped: scipy/numpy not installed (pip install scipy numpy)."
            )
        )
    except Exception as _ts_exc:
        print(dim(f"Temperature scaling skipped: {_ts_exc}"))

    # Update the cron sentinel so the next auto-calibration cycle doesn't
    # immediately re-run calibration that was just done manually.
    try:
        from tracker import count_settled_predictions as _count_settled

        _sentinel = LAST_CALIBRATION_COUNT_PATH
        _sentinel.write_text(str(_count_settled()))
    except Exception as _sen_exc:
        _log.warning(
            "cmd_calibrate: could not update calibration sentinel: %s", _sen_exc
        )

    print("\nRestart the app (or re-import weather_markets) to pick up new weights.")


def _cmd_emos_train(activate: bool = False, force: bool = False) -> None:
    """Two-stage EMOS fit: mean calibration (a,b) from a training split,
    variance (c,d) from that split's ens_var rows, validated on a temporally
    held-out slice never used in fitting.

    Fitting and activating are deliberately separate: by default this only
    computes and prints the fit (a dry run) without writing emos_params.json
    -- the file whose mere existence is the ONLY gate weather_markets.py
    checks to switch multi-day above/below/between predictions onto EMOS.
    Pass --activate to actually go live, which still requires typed
    confirmation on top of the flag. This two-gate design exists because a
    prior deploy accidentally went live as a side effect of just running
    this command with no separate go-live step -- see backlog.txt's EMOS
    entry.

    Holds out the most recent ~20% of the ens_var-bearing rows specifically
    (independent review, audit batch-28 item 3 follow-up -- NOT ~20% of all
    rows) for an out-of-sample CRPS check before allowing activation --
    fit_emos had no acceptance gate of its own: a degenerate fit (e.g. a
    collapsed variance coefficient) would otherwise sail straight through to
    save_emos_params. ens_var is only populated on recent forward-fill rows
    (backfilled Previous-Runs-API rows never carry it), so a plain 80/20
    split over ALL rows disproportionately removes exactly the population
    stage 2 needs -- measured on the real production DB, that naive split
    would have dropped ens_var-bearing training rows from 56 to 30, pushing
    a currently-passing dataset below the 40-row floor below. Splitting the
    ens_var subpopulation on its own preserves the floor's original meaning
    regardless of how much non-ens_var backfill data exists; all mean-only
    (no ens_var) rows go entirely to stage-1 training, since they can't be
    scored in the held-out CRPS check anyway.

    --activate refuses to proceed when fewer than 40 TRAINING ens_var rows
    exist (Gneiting 2005's 10-cases-per-parameter floor for 4 EMOS
    parameters), since c/d below 10 rows are hardcoded defaults, not a real
    fit. Also refuses when the new fit's held-out CRPS doesn't beat both a
    no-EMOS baseline and (on a retrain) the currently-active incumbent --
    that comparison fails CLOSED (refuses) rather than open on a computation
    error or on too little held-out data to trust when an incumbent exists
    to protect. Pass --force to override either data-sufficiency refusal --
    NOT the separate a/b coefficient bounds check, which rejects a
    structurally-broken fit outright regardless of --force (but no longer
    skips the rest of the diagnostics on a dry run -- a degenerate fit is
    exactly when an operator most needs to see stage 2 and the held-out
    comparison too).

    Detects an already-active, CORRECTLY-PINNED EMOS (get_emos_status()'s
    active AND t_pinned both true) as a retrain and skips
    reset_temperature_scale_for_emos() entirely in that case -- T was
    already pinned to 1.0 on the first activation. An active-but-NOT-pinned
    EMOS (t_pinned False -- active/T-reset state has diverged) is instead
    treated as if inactive, so the T-reset runs and re-pins it rather than
    perpetuating the divergence.
    """
    try:
        import numpy as np
    except ImportError:
        print("ERROR: numpy not installed.")
        return
    try:
        import properscoring  # noqa: F401
    except ImportError:
        print("ERROR: properscoring not installed. Run: pip install properscoring")
        return

    from ml_bias import (
        EMOS_A_BOUND,
        EMOS_B_BOUNDS,
        EMOS_SIGMA_VAR_FLOOR,
        _load_emos_params,
        fit_emos,
        get_emos_status,
        save_emos_params,
    )
    from tracker import get_emos_training_data

    print("Loading EMOS training data…")
    rows = get_emos_training_data()  # temporally ordered ascending (predicted_at)
    if not rows:
        print("No EMOS training data found. Run: py main.py backfill-emos")
        return

    n_total = len(rows)
    print(f"  {n_total} rows with ens_mean + settled_temp_f")

    # Split the ens_var subpopulation independently (see docstring) -- both
    # non_var_rows and var_rows_all are already temporally ordered, being
    # subsequences of `rows`.
    non_var_rows = [r for r in rows if r["ens_var"] is None]
    var_rows_all = [r for r in rows if r["ens_var"] is not None]

    _HOLDOUT_FRAC = 0.20
    _var_holdout_start = int(len(var_rows_all) * (1 - _HOLDOUT_FRAC))
    if _var_holdout_start > 0:
        var_rows = var_rows_all[:_var_holdout_start]
        held_out_var_rows = var_rows_all[_var_holdout_start:]
    else:
        var_rows, held_out_var_rows = var_rows_all, []

    # Group-aware adjustment (independent review, audit batch-28 item 3
    # round-2 follow-up): multiple predictions of the same (city,
    # market_date) -- different days_out, different cron cycles -- share
    # the same settled_temp_f label and near-identical ens_mean. A plain
    # index cutoff can split one such "event" across train and held-out,
    # leaking its outcome into the fit the held-out check is meant to
    # validate against (measured on the real production DB: 1 of 12
    # held-out rows shared its (city, market_date) with a training row
    # under the naive split). Any held-out row whose group already has a
    # representative in the train split gets moved into train instead --
    # a group split between the two sides is absorbed into train entirely;
    # a group that started life fully within held-out stays fully there.
    def _row_group_key(row: dict, idx: int) -> tuple:
        if row.get("city") is not None and row.get("market_date") is not None:
            return (row["city"], row["market_date"])
        return ("_ungrouped", idx)  # no grouping info -- never merge blindly

    _train_group_keys = {_row_group_key(r, i) for i, r in enumerate(var_rows)}
    _still_held_out = []
    _moved_for_grouping = 0
    for i, r in enumerate(held_out_var_rows, start=len(var_rows)):
        if _row_group_key(r, i) in _train_group_keys:
            var_rows.append(r)
            _moved_for_grouping += 1
        else:
            _still_held_out.append(r)
    held_out_var_rows = _still_held_out

    train_rows = non_var_rows + var_rows
    n = len(train_rows)
    if held_out_var_rows or _moved_for_grouping:
        print(
            f"  Temporal split (ens_var rows only): {len(var_rows)} train / "
            f"{len(held_out_var_rows)} held-out ens_var rows, never used in "
            f"fitting. {len(non_var_rows)} mean-only (no ens_var) rows all go "
            f"to stage-1 training."
            + (
                f" ({_moved_for_grouping} row(s) moved from held-out to train "
                "to keep a same-city/market_date group from straddling the "
                "split.)"
                if _moved_for_grouping
                else ""
            )
        )

    ens_mean_arr = np.array([r["ens_mean"] for r in train_rows])
    settled_temp_arr = np.array([r["settled_temp_f"] for r in train_rows])
    # Rows without ens_var get unit-variance placeholder for stage 1
    ens_var_all = np.array(
        [r["ens_var"] if r["ens_var"] is not None else 1.0 for r in train_rows]
    )

    print("\nStage 1 — fitting a, b (mean calibration) from training rows…")
    try:
        a, b, _, _ = fit_emos(ens_mean_arr, ens_var_all, settled_temp_arr)
    except ValueError as exc:
        print(red(f"\nEMOS stage-1 fit failed: {exc}"))
        return
    print(f"  a = {a:.4f}   b = {b:.4f}")

    # Structurally-broken fit -- flagged here but NOT an early return: an
    # operator running a plain (non---activate) dry run needs to see stage 2
    # and the held-out comparison too, not just one red line (independent
    # review, audit batch-28 item 3 follow-up). Only blocks --activate,
    # checked again further down, and is never overridable by --force there.
    _ab_invalid = not (
        EMOS_B_BOUNDS[0] < b <= EMOS_B_BOUNDS[1] and abs(a) <= EMOS_A_BOUND
    )
    if _ab_invalid:
        print(
            red(
                f"\nINVALID FIT — a={a:.4f} b={b:.4f} outside plausible bounds "
                f"(expected 0<b<={EMOS_B_BOUNDS[1]}, |a|<={EMOS_A_BOUND}°F). This "
                "indicates a degenerate/broken fit, not a data-sufficiency "
                "judgment call — will refuse activation regardless of --force "
                "(diagnostics below still run for review)."
            )
        )

    n_var = len(var_rows)
    print(
        f"\nStage 2 — fitting c, d (variance calibration) from {n_var} training rows with real ens_var…"
    )

    if n_var >= 10:
        vm = np.array([r["ens_mean"] for r in var_rows])
        vv = np.array([r["ens_var"] for r in var_rows])
        vo = np.array([r["settled_temp_f"] for r in var_rows])
        try:
            _, _, c, d = fit_emos(vm, vv, vo)
        except ValueError as exc:
            print(red(f"\nEMOS stage-2 fit failed: {exc}"))
            return
        print(f"  c = {c:.4f}   d = {d:.4f}")
        if d < 0.01:
            # d is d_sq**2 from a real fit_emos() call, so never negative in
            # practice (only reachable here at all via a monkeypatched/
            # hand-edited fit) -- "near zero" covers that case too since a
            # negative d is, if anything, further from a meaningful positive
            # variance response than exactly zero.
            print(
                yellow(
                    f"  WARNING: variance coefficient d={d:.4f} is near zero — "
                    "EMOS sigma will barely respond to ensemble spread, "
                    "discarding the ensemble's own disagreement signal."
                )
            )
    else:
        c, d = 1.0, 0.1
        print(
            f"  WARNING: only {n_var} training ens_var rows (need >= 10). Using defaults c=1.0, d=0.1"
        )

    mean_crps = None
    try:
        import properscoring as ps

        sigma_all = np.sqrt(np.maximum(c + d * ens_var_all, EMOS_SIGMA_VAR_FLOOR))
        mu_all = a + b * ens_mean_arr
        mean_crps = float(
            np.mean(ps.crps_gaussian(settled_temp_arr, mu=mu_all, sig=sigma_all))
        )
        print(f"\nMean CRPS on training set ({n} rows): {mean_crps:.4f}")
    except Exception:
        pass

    # Held-out CRPS acceptance gate -- refuse activation unless the new fit
    # beats both a no-EMOS baseline (raw ensemble Gaussian: mu=ens_mean,
    # sigma=sqrt(ens_var), i.e. identity EMOS params a=0,b=1,c=0,d=1 -- the
    # closest computable stand-in for "T-scaling only" since T-scaling
    # recalibrates a probability rather than fitting its own mu/sigma) and,
    # on a retrain, the currently-active incumbent params -- all measured
    # on the SAME held-out ens_var rows, none of which were used in either
    # fit. Fails CLOSED (independent review, audit batch-28 item 3
    # follow-up): a computation error, or too little held-out data to trust
    # when there's a working incumbent to protect, now REFUSES rather than
    # silently letting a possibly-worse fit through. Only a first activation
    # (no incumbent) with too little held-out data proceeds without the
    # check -- there's nothing at risk of being replaced in that case.
    _incumbent = _load_emos_params()
    _HELD_OUT_MIN = 5
    _crps_gate_passed = True
    if len(held_out_var_rows) >= _HELD_OUT_MIN:
        try:
            import properscoring as ps

            ho_mean = np.array([r["ens_mean"] for r in held_out_var_rows])
            ho_var = np.array([r["ens_var"] for r in held_out_var_rows])
            ho_obs = np.array([r["settled_temp_f"] for r in held_out_var_rows])

            def _held_out_crps(params: tuple[float, float, float, float]) -> float:
                pa, pb, pc, pd = params
                mu = pa + pb * ho_mean
                sigma = np.sqrt(np.maximum(pc + pd * ho_var, EMOS_SIGMA_VAR_FLOOR))
                return float(np.mean(ps.crps_gaussian(ho_obs, mu=mu, sig=sigma)))

            new_crps = _held_out_crps((a, b, c, d))
            baseline_crps = _held_out_crps((0.0, 1.0, 0.0, 1.0))
            print(
                f"\nHeld-out CRPS ({len(held_out_var_rows)} rows, never fit on): "
                f"new={new_crps:.4f}  baseline(raw ensemble)={baseline_crps:.4f}"
            )
            _crps_gate_passed = new_crps < baseline_crps
            if not _crps_gate_passed:
                print(
                    red(
                        f"  New fit does NOT beat the raw-ensemble baseline on "
                        f"held-out data ({new_crps:.4f} >= {baseline_crps:.4f})."
                    )
                )

            if _incumbent is not None:
                incumbent_crps = _held_out_crps(_incumbent)
                print(f"  incumbent (currently active)={incumbent_crps:.4f}")
                if new_crps >= incumbent_crps:
                    _crps_gate_passed = False
                    print(
                        red(
                            f"  New fit does NOT beat the currently-active "
                            f"incumbent on held-out data ({new_crps:.4f} >= "
                            f"{incumbent_crps:.4f})."
                        )
                    )
        except Exception as exc:
            _crps_gate_passed = False
            print(
                red(
                    f"\nHeld-out CRPS check failed to run ({exc}) — refusing "
                    "activation rather than assuming the fit is safe."
                )
            )
    elif _incumbent is not None:
        _crps_gate_passed = False
        print(
            red(
                f"\nOnly {len(held_out_var_rows)} held-out ens_var rows (need >= "
                f"{_HELD_OUT_MIN}) — too few to validate a retrain against the "
                "currently-active incumbent. Refusing."
            )
        )
    else:
        print(
            dim(
                f"\nOnly {len(held_out_var_rows)} held-out ens_var rows (need >= "
                f"{_HELD_OUT_MIN}) — skipping the held-out CRPS gate (no "
                "incumbent to protect on a first activation)."
            )
        )

    if not activate:
        print(
            yellow(
                "\nDRY RUN — EMOS NOT activated. Fit results above are for review only; "
                "no file was written and the live probability method is unchanged.\n"
                "Run 'py main.py emos-train --activate' to go live with these parameters."
            )
        )
        return

    if _ab_invalid:
        print(
            red(
                "\nREFUSING to activate — a/b fit is outside plausible bounds "
                "(see INVALID FIT above). Not overridable by --force."
            )
        )
        return

    _EMOS_VAR_FLOOR = 40
    if n_var < _EMOS_VAR_FLOOR and not force:
        print(
            red(
                f"\nREFUSING to activate — only {n_var} training rows have real "
                f"ens_var (need >= {_EMOS_VAR_FLOOR}, Gneiting 2005's "
                f"10-cases-per-parameter floor for 4 EMOS parameters). c/d above "
                + (
                    "came from a genuine fit on a thin sample, well short of the floor."
                    if n_var >= 10
                    else "are HARDCODED DEFAULTS (c=1.0, d=0.1) — not a real fit at all."
                )
                + " Wait for more forward-fill data, or pass --force to override "
                "(not recommended — sigma would be built on an unreliable variance fit)."
            )
        )
        return

    if not _crps_gate_passed and not force:
        print(
            red(
                "\nREFUSING to activate — new fit underperforms on held-out data "
                "(see above). Pass --force to override (not recommended — this "
                "would put a worse-than-baseline calibration live)."
            )
        )
        return

    try:
        if _cron_module._is_cron_running():
            print(
                red(
                    "\nA cron cycle is currently running — refusing to activate "
                    "mid-scan (would split one scan across two probability "
                    "methods, some markets priced with the old method, some "
                    "with EMOS). Wait for it to finish and try again."
                )
            )
            return
    except Exception:
        pass  # fail open on an inability to check, matching _is_cron_running's own default

    _status = get_emos_status()
    _was_active = bool(_status.get("active")) and _status.get("t_pinned") is True
    _diverged = bool(_status.get("active")) and _status.get("t_pinned") is False
    if _diverged:
        print(
            red(
                "\nWARNING: EMOS is active but temperature_scale.json is NOT "
                "correctly pinned (t_pinned=False) -- treating this as a fresh "
                "activation so the T-reset runs and re-pins it, rather than "
                "perpetuating the divergence. Note: the held-out CRPS gate "
                "above still compares against the currently-active incumbent "
                "-- if it refuses, --force is needed to re-pin here even "
                "though this isn't really a normal retrain."
            )
        )
    if _was_active:
        print(
            yellow(
                f"\nEMOS is already active — this is a RETRAIN (training-split "
                f"n={n} of {n_total} total rows, ens_var-populated n_var={n_var}). "
                f"New a/b/c/d will replace the current fit; temperature_scale.json "
                f"is left untouched (T was already reset to 1.0 on first "
                f"activation and stays there). "
                f"Type 'yes' to confirm: "
            ),
            end="",
            flush=True,
        )
    elif _diverged:
        print(
            yellow(
                f"\nThis will re-pin EMOS's diverged T-reset (training-split "
                f"n={n} of {n_total} total rows, ens_var-populated n_var={n_var}). "
                f"T_global/T_above/T_below/T_between will be reset to 1.0 in "
                f"temperature_scale.json, but NO new pre-EMOS snapshot will be "
                f"written -- the original snapshot from EMOS's first-ever "
                f"activation is retained as-is (first snapshot always wins), "
                f"so emos-deactivate will still restore the true original T "
                f"values, not whatever T happened to be sitting here just now. "
                f"Type 'yes' to confirm: "
            ),
            end="",
            flush=True,
        )
    else:
        print(
            yellow(
                f"\nThis will make EMOS the live probability method for multi-day "
                f"above/below/between predictions (training-split n={n} of "
                f"{n_total} total rows, ens_var-populated n_var={n_var}), "
                f"replacing the current ensemble/climatology blend + temperature scaling. "
                f"It will also reset T_global/T_above/T_below/T_between to 1.0 in "
                f"temperature_scale.json (EMOS's own fit replaces T-scaling's role for "
                f"those condition types — leaving the old T in place would double-"
                f"calibrate on top of it; the pre-reset values are saved so "
                f"emos-deactivate can restore them immediately). "
                f"Type 'yes' to confirm: "
            ),
            end="",
            flush=True,
        )
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        print(dim("  Cancelled — EMOS not activated."))
        return
    if answer != "yes":
        print(dim("  Cancelled — EMOS not activated."))
        return

    from ml_bias import deactivate_emos, reset_temperature_scale_for_emos

    # AUD-0029: re-check immediately before the write, not just before the
    # (unbounded-duration) confirmation prompt above -- a cron cycle that
    # starts during the human's "yes"/no wait is invisible to the earlier
    # check alone, and is exactly the split-scan failure mode this gate
    # exists to prevent.
    try:
        if _cron_module._is_cron_running():
            print(
                red(
                    "\nA cron cycle started while waiting for confirmation — "
                    "refusing to activate mid-scan. Wait for it to finish and "
                    "try again."
                )
            )
            return
    except Exception:
        pass  # fail open on an inability to check, matching _is_cron_running's own default

    try:
        save_emos_params(a, b, c, d, n=n, mean_crps=mean_crps)
        if not _was_active:
            reset_temperature_scale_for_emos()
    except Exception as exc:
        print(red(f"\nACTIVATION FAILED partway through: {exc}"))
        if _was_active:
            # A retrain's only write is save_emos_params, which is atomic
            # (atomic_write_json_with_history either fully replaces the file
            # or leaves it untouched) -- the previous working incumbent is
            # very likely still intact. Deactivating here would needlessly
            # take down a working EMOS over a failed retrain attempt
            # (independent review, audit batch-28 item 3 follow-up).
            print(
                red(
                    "This was a RETRAIN of an already-active EMOS -- NOT "
                    "deactivating, the previous incumbent should still be live. "
                    "Run 'py main.py emos-status' to confirm."
                )
            )
            return
        print(red("Rolling back to avoid a partially-activated state..."))
        try:
            deactivate_emos()
            print(dim("Rollback complete — EMOS is NOT active."))
        except Exception as rollback_exc:
            print(red(f"ROLLBACK ALSO FAILED: {rollback_exc}"))
            print(
                red(
                    "Manual intervention required — check data/emos_params.json "
                    "and data/temperature_scale.json by hand."
                )
            )
        return

    print(green("\nEMOS is now LIVE → data/emos_params.json"))
    if _was_active:
        print(dim("Retrain only — temperature_scale.json left untouched."))
    else:
        print(
            green(
                "T_global/T_above/T_below/T_between reset to 1.0 → data/temperature_scale.json"
            )
        )
    print(
        dim(
            "\nRun 'py main.py emos-status' any time to check, or "
            "'py main.py emos-deactivate' to revert."
        )
    )


def cmd_emos_status() -> None:
    """Show whether EMOS is currently the live probability method."""
    from ml_bias import get_emos_status

    status = get_emos_status()
    if status.get("corrupt"):
        print(
            red(
                f"  emos_params.json exists but is CORRUPT/unreadable: "
                f"{status.get('error')}"
            )
        )
        if status.get("t_pinned") is True:
            print(
                red(
                    "  WARNING: temperature_scale.json IS pinned to the 1.0 "
                    "placeholder for every EMOS-covered condition type, but "
                    "emos_params.json (the fit that placeholder exists to "
                    "defer to) is unreadable -- predictions are currently "
                    "running with NO calibration at all for global/above/"
                    "below/between, not even the pre-EMOS temperature "
                    "scaling. This is urgent."
                )
            )
        print(dim("  Run 'py main.py emos-deactivate' to remove it."))
        return
    if not status["active"]:
        print(
            dim("  EMOS is NOT active — using ensemble/climatology blend + T-scaling.")
        )
        return

    print(green("  EMOS is ACTIVE (live probability method for above/below/between)."))
    if status.get("t_pinned") is False:
        print(
            red(
                "  WARNING: temperature_scale.json is NOT pinned to 1.0 for all "
                "EMOS-covered condition types — active/T-reset state has diverged "
                "(audit batch-28 item 3's t_pinned cross-check). Investigate before "
                "trusting current predictions; 'py main.py emos-deactivate' then "
                "re-activate will re-pin it."
            )
        )
    print(
        f"  a={status['a']:.4f}  b={status['b']:.4f}  c={status['c']:.4f}  d={status['d']:.4f}"
    )
    if status.get("n") is not None:
        print(f"  Trained on n={status['n']} rows", end="")
        if status.get("mean_crps") is not None:
            print(f"  mean_crps={status['mean_crps']:.4f}", end="")
        print()
    if status.get("fitted_at"):
        print(f"  Fitted at: {status['fitted_at']}")


def cmd_emos_deactivate(reason: str = "manual deactivation") -> None:
    """Revert EMOS to inactive, restoring the ensemble/climatology blend + T-scaling path."""
    from ml_bias import deactivate_emos, get_emos_status

    status = get_emos_status()

    if status.get("corrupt"):
        print(
            yellow(
                f"  emos_params.json exists but is CORRUPT/unreadable: "
                f"{status.get('error')}"
            )
        )
        print(yellow("  Type 'yes' to remove it: "), end="", flush=True)
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            print(dim("  Cancelled."))
            return
        if answer != "yes":
            print(dim("  Cancelled."))
            return
        deactivate_emos()
        print(green("  Corrupt emos_params.json removed."))
        return

    if not status["active"]:
        print(dim("  EMOS is not currently active — nothing to do."))
        return

    try:
        if _cron_module._is_cron_running():
            print(
                red(
                    "\nA cron cycle is currently running — refusing to deactivate "
                    "mid-scan (would split one scan across two probability "
                    "methods). Wait for it to finish and try again."
                )
            )
            return
    except Exception:
        pass  # fail open on an inability to check, matching _is_cron_running's own default

    print(
        yellow(
            f"  EMOS is currently active (fitted {status.get('fitted_at', '?')}, "
            f"n={status.get('n', '?')}). Deactivating reverts multi-day "
            f"above/below/between predictions to the ensemble/climatology blend + "
            f"temperature scaling, restoring the pre-activation T values "
            f"immediately (saved when EMOS was activated). "
            f"Type 'yes' to confirm: "
        ),
        end="",
        flush=True,
    )
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        print(dim("  Cancelled — EMOS still active."))
        return
    if answer != "yes":
        print(dim("  Cancelled — EMOS still active."))
        return

    # AUD-0029: re-check immediately before the write -- see the matching
    # comment in cmd_emos_train's activation path.
    try:
        if _cron_module._is_cron_running():
            print(
                red(
                    "\nA cron cycle started while waiting for confirmation — "
                    "refusing to deactivate mid-scan. Wait for it to finish "
                    "and try again."
                )
            )
            return
    except Exception:
        pass  # fail open on an inability to check, matching _is_cron_running's own default

    _, restored = deactivate_emos()
    _log.info(
        "cmd_emos_deactivate: EMOS deactivated (reason: %s, restored=%s)",
        reason,
        restored,
    )
    if not restored:
        print(
            red(
                "  EMOS deactivated, but restoring the pre-activation T values "
                "FAILED -- above/below/between remain pinned at the 1.0 "
                "placeholder until the next scheduled retrain. Re-run "
                "'py main.py emos-status' to check t_pinned, or retry."
            )
        )
        return
    print(
        green(
            "  EMOS deactivated — reverted to ensemble/climatology blend + T-scaling."
        )
    )


def cmd_backfill_emos(force: bool = False) -> None:
    """Backfill EMOS training columns for historical settled predictions.

    Part 1 — settled_temp_f: re-runs audit_settlement for any outcome that is
    missing the observed temperature (trades settled before that column existed).
    With --force, re-runs it for EVERY settled outcome instead — needed after a
    fix to audit_settlement()'s own fetch/threshold logic, since already-filled
    rows otherwise keep whatever (possibly now-stale) value they had.

    Part 2 — ens_mean: fetches the deterministic forecast from the Previous Runs API
    (ICON + GFS + ECMWF AIFS single) at the correct lead time for each multi-day
    prediction missing ens_mean.  ens_var is left NULL for backfill rows.
    Required before running py main.py emos-train.

    Safe to re-run without --force — already-filled rows are skipped by the SQL
    WHERE clause. --force is a deliberate, heavier re-verification pass, not the
    default.
    """
    from tracker import backfill_emos_data

    mode = "FORCE re-verify (all settled outcomes)" if force else "fill missing only"
    print(f"Running EMOS backfill (settled_temp_f + ens_mean/ens_var) — mode: {mode}…")
    try:
        temp_filled, ens_filled = backfill_emos_data(force=force)
        print(
            f"\nDone — settled_temp_f filled: {temp_filled}, ens_mean filled: {ens_filled}"
        )
        if ens_filled == 0:
            print(
                dim(
                    "  No ens_mean filled — Previous Runs API may not have data "
                    "for these dates, or no settled multi-day predictions are missing ens_mean."
                )
            )
    except Exception as exc:
        print(red(f"Backfill failed: {exc}"))
        raise


def cmd_backfill_price_history(client: KalshiClient) -> None:
    """One-off recovery for price_history rows lost to a real bug: sync_outcomes'
    candlestick backfill read market.get("series_ticker"), a field that never
    exists on a real get_market() response — silently no-op'd (no exception, no
    log) for every settlement since the feature shipped, confirmed via
    price_history being fully empty. Fixed at the source (sync_outcomes now falls
    back to the ticker's own prefix); this command recovers the already-settled
    tickers sync_outcomes will never revisit on its own (it only backfills a
    ticker the first time it settles). Safe to re-run — already-filled tickers
    are skipped."""
    from tracker import backfill_price_history

    print("Backfilling price_history for settled tickers missing candlestick data…")
    try:
        filled, failed = backfill_price_history(client)
        print(f"\nDone — price_history backfilled for {filled} ticker(s).")
        if failed:
            print(
                yellow(
                    f"  {failed} ticker(s) failed (see log) — will be retried on "
                    "the next run."
                )
            )
    except Exception as exc:
        print(red(f"Backfill failed: {exc}"))
        raise


def cmd_backfill_daily_temp_settlement() -> None:
    """One-off recovery for outcomes.settled_temp_f rows written before
    audit_settlement()'s daily HIGH/LOW branch switched from an IEM ASOS
    raw-METAR proxy to Kalshi's own settled expiration_value (backlog.txt
    "DATA-DRIVEN SIGMA FROM SETTLED HISTORY + CLI-REPORT SETTLEMENT FETCH").
    Re-runs audit_settlement() for every already-populated daily-temp row so
    it's corrected against Kalshi's real settlement. Safe to re-run —
    already-correct rows are simply re-confirmed.

    Reports the disputed-row count before and after (opus-review-caught,
    2026-08-10): every disputed row in production was flagged by the OLD
    ASOS-proxy comparison this pass replaces, and audit_settlement() now
    clears disputed=1 on a ticker that re-checks clean against Kalshi's own
    settled figure -- surfacing the delta here makes that irreversible
    write visible before/after a live run rather than silent."""
    from tracker import backfill_daily_temp_settlement, get_disputed_count

    disputed_before = get_disputed_count()
    print(
        "Backfilling outcomes.settled_temp_f from Kalshi's own settlement "
        "(expiration_value) for daily HIGH/LOW markets…"
    )
    print(f"  Disputed rows before: {disputed_before}")
    try:
        corrected, failed = backfill_daily_temp_settlement()
        disputed_after = get_disputed_count()
        print(f"\nDone — settled_temp_f corrected for {corrected} ticker(s).")
        print(f"  Disputed rows after: {disputed_after}")
        if failed:
            print(
                yellow(
                    f"  {failed} ticker(s) failed (see log) — left with their "
                    "prior value, will be retried on the next run."
                )
            )
    except Exception as exc:
        print(red(f"Backfill failed: {exc}"))
        raise


def cmd_backfill_ensemble_var() -> None:
    """One-off recovery for ensemble_member_scores rows logged before
    log_member_score() call sites started passing var= ("max"/"min").
    Without var, a model's per-model accuracy tracking pools daily-high and
    daily-low forecast error together, which get_member_bias()'s var-split
    bias-correction (feeding get_ensemble_temps/batch_prewarm_ensemble)
    needs kept apart. Recovers var from tracker.predictions' own
    KXHIGH/KXLOW ticker prefix, joined via (city, market_date). Safe to
    re-run — only ever touches rows still NULL."""
    from tracker import backfill_ensemble_member_scores_var

    print("Backfilling ensemble_member_scores.var from predictions' ticker prefix…")
    updated, unresolved, duplicate_conflict = backfill_ensemble_member_scores_var()
    print(f"\nDone — {updated} row(s) backfilled.")
    if unresolved:
        print(
            yellow(
                f"  {unresolved} row(s) left NULL — no matching predictions row, "
                "or the city/date had both a high and low market and couldn't "
                "be disambiguated."
            )
        )
    if duplicate_conflict:
        print(
            yellow(
                f"  {duplicate_conflict} row(s) left NULL — resolved a var, but "
                "another row already occupies that (city, model, date, var) slot. "
                "These are pre-existing duplicate rows (predating idx_ems_dedup) "
                "that already double-count that city/date/model while NULL; "
                "not something this backfill resolves automatically."
            )
        )


def cmd_backfill_member_brier() -> None:
    """One-off recovery pass populating implied_prob/brier on existing
    ensemble_member_scores rows, from settled paper trades. Run this once
    after implied_prob/brier logging has shipped, to avoid a 1-2 week cold
    start before weather_markets.scan_member_quarantine()'s Brier-based
    detection statistic has enough data (_QUARANTINE_MIN_RECENT_N per model
    in its 14-day window). Safe to re-run — only ever touches rows where
    brier IS NULL."""
    from paper import get_all_trades
    from tracker import backfill_member_brier

    print("Backfilling ensemble_member_scores.implied_prob/brier from settled trades…")
    trades = get_all_trades()
    updated, skipped, errored = backfill_member_brier(trades)
    print(f"\nDone — {updated} row(s) backfilled.")
    if skipped:
        print(
            yellow(
                f"  {skipped} trade(s) skipped — no resolvable condition_type/"
                "threshold, or settled_temp_f not yet in outcomes."
            )
        )
    if errored:
        print(
            yellow(
                f"  {errored} trade(s) errored while computing (malformed record) "
                "— counted and skipped, rest of the batch still ran."
            )
        )


def cmd_backfill_member_actual_temp() -> None:
    """One-off repair pass rewriting ensemble_member_scores.actual_temp from
    the official Kalshi settlement figure (batch-68's A13 audit).

    actual_temp is a frozen copy of outcomes.settled_temp_f taken at
    settlement time. When audit_settlement()'s daily branch switched off the
    IEM ASOS raw-METAR proxy (2026-08-10), backfill-settled-temps corrected
    outcomes but nothing re-derived the rows already copied out of it —
    measured 2026-08-25, 228 of 507 rows still disagreed with the official
    figure, and those rows feed get_dynamic_station_bias() → the live
    forecast bias correction. Safe to re-run: only rows that actually differ
    are touched, so a second pass reports 0 updated.

    Run `backfill-ensemble-var` FIRST: rows with a NULL var cannot be matched
    by this pass at all, and it reports how many are in that state."""
    from paper import get_all_trades
    from tracker import backfill_member_actual_temp

    print("Repairing ensemble_member_scores.actual_temp from official settlements…")
    trades = get_all_trades()
    updated, skipped, conflicts, errored, unreachable = backfill_member_actual_temp(
        trades
    )
    print(f"\nDone — {updated} row(s) corrected.")
    if skipped:
        print(
            yellow(
                f"  {skipped} trade(s) skipped — unsettled, unresolvable ticker/"
                "city/date, a ticker whose var can't be read off its own prefix, "
                "or no settled_temp_f (hourly/monthly rows write settled_value "
                "instead and are correctly excluded)."
            )
        )
    if errored:
        # red, not yellow, and worded as a failure: these are exceptions, not
        # expected exclusions. Folding them into `skipped` above would let a
        # schema change or a locked DB read as routine ineligibility.
        print(
            red(
                f"  {errored} trade(s) RAISED while being processed and were not "
                "applied — this is a failure, not an expected exclusion. Check the "
                "log for the exception before trusting the corrected count."
            )
        )
    if conflicts:
        print(
            red(
                f"  {conflicts} trade(s) named a city/date/var cell already given a "
                "DIFFERENT official value this pass — skipped rather than "
                "overwritten. Two strikes of one event always share a settled "
                "value, so a non-zero count here means a var was derived wrongly "
                "somewhere; investigate before trusting the result."
            )
        )
    if unreachable:
        print(
            yellow(
                f"  {unreachable} row(s) have actual_temp but a NULL var and are "
                "structurally unreachable by this pass — they are NOT covered by "
                "the corrected count above. get_ensemble_member_accuracy() reads "
                "them with no var filter and no time window, so they never age "
                "out. Run `backfill-ensemble-var` and then re-run this."
            )
        )


# ── Interactive menu ──────────────────────────────────────────────────────────


def _cmd_settle_open(client: KalshiClient | None = None) -> None:  # noqa: ARG001
    """Interactively settle an open paper trade by choosing from a list."""
    from paper import get_balance, get_open_trades, settle_paper_trade

    open_trades = get_open_trades()
    if not open_trades:
        print(dim("  No open paper trades to settle."))
        return

    rows = [
        [
            t["id"],
            t["ticker"][:32],
            bold(t["side"].upper()),
            t["quantity"],
            f"${t['entry_price']:.3f}",
            f"${t['cost']:.2f}",
            t.get("target_date", "—"),
        ]
        for t in open_trades
    ]
    print(
        tabulate(
            rows,
            headers=["#", "Ticker", "Side", "Qty", "Price", "Cost", "Date"],
            tablefmt="rounded_outline",
        )
    )
    try:
        while True:
            raw = input(dim("\n  Trade # to settle (q to cancel): ")).strip()
            if raw.lower() == "q":
                return
            if not raw:
                continue
            try:
                trade_id = int(raw)
                break
            except ValueError:
                print(red("  Enter a trade number."))
        while True:
            outcome_raw = (
                input(dim("  Outcome (yes/no, q to cancel): ")).strip().lower()
            )
            if outcome_raw == "q":
                return
            if outcome_raw in ("yes", "no"):
                break
        t = settle_paper_trade(trade_id, outcome_raw == "yes")
        pnl = t.get("pnl", 0.0) or 0.0
        pnl_s = green(f"+${pnl:.2f}") if pnl >= 0 else red(f"-${abs(pnl):.2f}")
        print(
            green(
                f"  Trade #{trade_id} settled {t['outcome'].upper()}  "
                f"P&L: {pnl_s}  Balance: ${get_balance():.2f}"
            )
        )
        # ── Post-mortem ───────────────────────────────────────────────────────
        try:
            from tracker import get_history

            outcome_yes = outcome_raw == "yes"
            entry_prob = t.get("entry_prob")
            print(bold("\n  ── Post-mortem ──"))
            pred_str = f"{entry_prob * 100:.0f}% YES" if entry_prob is not None else "?"
            actual_str = ("YES " + green("✓")) if outcome_yes else ("NO  " + red("✗"))
            if entry_prob is None:
                # No recorded prediction to grade — don't imply a verdict.
                # The old `(False == outcome_yes)` collapse marked this
                # "correct" (green check) whenever the outcome was NO.
                result_mark = dim("—")
            else:
                was_right = (entry_prob > 0.5) == outcome_yes
                result_mark = green("✓") if was_right else red("✗")
            print(f"  You predicted: {pred_str}   Actual: {actual_str}   {result_mark}")
            # Find closest source from tracker prediction record
            ticker = t.get("ticker", "")
            hist = get_history(100)
            pred_rec = next((r for r in hist if r["ticker"] == ticker), None)
            if pred_rec:
                sources = {
                    "Ensemble": pred_rec.get("our_prob"),
                    "NWS": None,
                    "Climatology": None,
                }
                actual_val = 1 if outcome_yes else 0
                best_src = min(
                    (
                        (src, abs(p - actual_val))
                        for src, p in sources.items()
                        if p is not None
                    ),
                    key=lambda x: x[1],
                    default=(None, None),
                )
                if best_src[0]:
                    print(f"  Closest source: {best_src[0]}")
            print(f"  P&L: {pnl_s}")
        except Exception:
            pass
    except (KeyboardInterrupt, EOFError):
        print()


def _menu_watch(client: KalshiClient) -> None:
    """Prompt for edge threshold before entering watch mode."""
    try:
        raw = input("  Edge threshold % (default 10): ").strip()
        min_edge = float(raw) / 100 if raw else 0.10
    except (ValueError, EOFError):
        min_edge = 0.10
    cmd_watch(client, min_edge=min_edge)


def cmd_menu(client: KalshiClient):
    from paper import get_balance as paper_balance

    # Top-level options: (shortcut_key, label, description)
    top_options = [
        ("A", "Analyze ", "find best trades right now"),
        ("T", "Today   ", "what should I do today?"),
        ("L", "Cron    ", "scan markets and place trades now"),
        ("W", "Watch   ", "live auto-refresh dashboard"),
        ("P", "Paper   ", "trades, alerts, results, settle"),
        ("K", "Backtest", "score model on history"),
        ("V", "Validate", "walk-forward model validation"),
        ("X", "Report  ", "generate weekly PDF/HTML report"),
        ("R", "Brief   ", "daily morning summary"),
        ("B", "Browse  ", "explore markets by city"),
        ("S", "Settings", "view & edit thresholds"),
        ("?", "Help    ", "show command guide"),
        ("Q", "Quit    ", ""),
    ]
    key_map = {opt[0].lower(): str(i) for i, opt in enumerate(top_options, 1)}

    # M-25: read from the live client, not a fresh env read (_kalshi_env()).
    # client.base_url is fixed at construction (build_client(), process
    # start) and never re-reads KALSHI_ENV -- an env-fresh banner could flip
    # to [DEMO] the instant an operator edits KALSHI_ENV via the Settings
    # menu while every live order this session places still reaches
    # whichever server `client` was actually built with. Settings now
    # refuses that in-session edit outright (restart required), so this
    # banner reading the client is the other half of that fix: it can never
    # show a state the client doesn't back. Opus review (I-4): hoisted out
    # of the redraw loop (the import doesn't need to repeat every redraw),
    # and made explicit (PROD/DEMO/unrecognized) instead of an implicit
    # not-PROD-means-DEMO fallback -- build_client() only ever produces one
    # of the two constants today, so this can't currently fire, but it fails
    # loudly instead of reassuringly if that ever changes.
    from kalshi_client import DEMO_BASE as _DEMO_BASE
    from kalshi_client import PROD_BASE as _PROD_BASE

    while True:
        _client_base = getattr(client, "base_url", None)
        if _client_base == _PROD_BASE:
            env_text = "[PROD]"
        elif _client_base == _DEMO_BASE:
            env_text = "[DEMO]"
        else:
            env_text = "[UNKNOWN]"
        title_visible = f"   Kalshi Weather Prediction Markets   {env_text}"

        # Build status line
        try:
            raw_bal = paper_balance()
            status_visible = f"  Paper: ${raw_bal:.2f}"
            status_colored = f"  Paper: {green(f'${raw_bal:.2f}')}"
        except Exception:
            raw_bal = None
            status_visible = ""
            status_colored = ""

        try:
            from paper import get_open_trades as _pot

            n_open = len(_pot())
            if n_open:
                status_visible += f"  ·  {n_open} open"
                status_colored += f"  {dim('·')}  {cyan(f'{n_open} open')}"
        except Exception:
            pass

        try:
            bs, bs_n = brier_score_rolling_with_n()
            if bs is not None:
                grade = (
                    "Excellent"
                    if bs < 0.10
                    else "Good"
                    if bs < 0.18
                    else "Fair"
                    if bs < 0.25
                    else "Poor"
                )
                grade_color = (
                    green
                    if grade in ("Excellent", "Good")
                    else yellow
                    if grade == "Fair"
                    else red
                )
                status_visible += f"  ·  Brier: {bs:.3f} {grade} (n={bs_n})"
                status_colored += f"  {dim('·')}  Brier: {grade_color(f'{bs:.3f} {grade}')}  {dim(f'(n={bs_n})')}"
        except Exception:
            pass

        try:
            from paper import fear_greed_index

            fg_score, fg_label = fear_greed_index()
            fg_color = (
                red
                if fg_label == "Fearful"
                else yellow
                if fg_label == "Cautious"
                else (lambda s: s)
                if fg_label == "Neutral"
                else green
                if fg_label == "Confident"
                else bold
            )
            status_visible += f"  ·  Mood: {fg_label} ({fg_score})"
            status_colored += (
                f"  {dim('·')}  Mood: {fg_color(f'{fg_label} ({fg_score})')}"
            )
        except Exception:
            pass

        menu_w = max(50, len(title_visible), len(status_visible))
        bar = "─" * menu_w
        title_pad = " " * max(0, menu_w - len(title_visible))
        title_line = (
            f"   Kalshi Weather Prediction Markets   {dim(env_text)}{title_pad}"
        )
        status_pad = " " * max(0, menu_w - len(status_visible))
        status_line = f"{status_colored}{status_pad}"

        print(bold(f"\n  ┌{bar}┐"))
        print(f"  {bold('│')}{title_line}{bold('│')}")
        print(f"  {bold('│')}{status_line}{bold('│')}")
        print(bold(f"  └{bar}┘\n"))

        # ── Reminder banners ──────────────────────────────────────────────────
        # L-9: the kill-switch/staleness check and the due-trades check used to
        # share one blanket `except Exception: pass` -- split into two try
        # blocks (each logged at WARNING, not silently swallowed) so a bug in
        # the due-trades section can never suppress the halt indication, and
        # vice versa; each failure is now visible instead of invisible.
        try:
            import time as _t

            # batch-24 item 1 opus-review-caught (F7): cron.cmd_cron's finally
            # block deliberately stops refreshing CRON_LAST_RUN_PATH while the
            # kill switch is engaged (so the dead-man's-switch gap can grow --
            # see that block's own comment), which would otherwise make THIS
            # banner misleadingly suggest "press L to start the loop" while the
            # loop is in fact running fine, just halted. Show the kill-switch
            # state instead in that case.
            if KILL_SWITCH_PATH.exists():
                print(
                    red(
                        "  ⚠  Kill switch active — trading halted. "
                        "Run `py main.py resume`, or delete data/.kill_switch.\n"
                    )
                )
            else:
                _last_run_path = CRON_LAST_RUN_PATH
                if not _last_run_path.exists():
                    print(
                        yellow(
                            "  ⚠  Loop hasn't run yet — press L to start the auto-run loop.\n"
                        )
                    )
                else:
                    _hours_since = (_t.time() - _last_run_path.stat().st_mtime) / 3600
                    if _hours_since > 5:
                        print(
                            yellow(
                                f"  ⚠  Cron last ran {_hours_since:.0f}h ago — press L to start the loop.\n"
                            )
                        )
        except Exception as _banner_exc:
            _log.warning(
                "cmd_menu: kill-switch/staleness banner failed: %s", _banner_exc
            )

        try:
            # Unsettled due trades
            from paper import get_open_trades as _got

            _due = [
                t
                for t in _got()
                if _target_date_due(t.get("target_date"), t.get("city"))
            ]
            if _due:
                print(
                    yellow(
                        f"  ⚠  {len(_due)} trade(s) due today — go to P → 3 → 1 to settle.\n"
                    )
                )
        except Exception as _due_exc:
            _log.warning("cmd_menu: due-trades banner failed: %s", _due_exc)

        for i, (key, name, desc) in enumerate(top_options, 1):
            num = cyan(f"  {i:>2}")
            key_str = dim(f"[{key}]")
            if desc:
                print(f"{num} {key_str} {bold(name)}  {dim('·')}  {desc}")
            else:
                print(f"{num} {key_str} {name.strip()}")

        print(
            dim(
                "\n  Tip: press A to scan for trades · run 'py main.py settle' or 'py main.py backtest' when off a game to sync data."
            )
        )
        choice = input(bold(f"\n  Choose (1–{len(top_options)} or letter): ")).strip()
        if not choice.isdigit():
            choice = key_map.get(choice.lower(), choice)
        if not choice.isdigit() or not (1 <= int(choice) <= len(top_options)):
            print(red("  Invalid choice."))
            continue

        idx = int(choice) - 1
        key, _name, _desc = top_options[idx]
        name_stripped = _name.strip()

        if name_stripped == "Quit":
            print(dim("Goodbye."))
            break

        elif name_stripped == "Analyze":
            try:
                cmd_analyze(client)
            except KeyboardInterrupt:
                print(yellow("\n  Analyze cancelled."))
                continue  # skip the Press Enter pause — already returned to menu context

        elif name_stripped == "Today":
            try:
                cmd_today(client)
            except KeyboardInterrupt:
                print()
            except BaseException as exc:
                import traceback as _tb

                print(red(f"\n  Today crashed: {type(exc).__name__}: {exc}"))
                _tb.print_exc()
                try:
                    input(dim("  Press Enter to continue..."))
                except (EOFError, KeyboardInterrupt):
                    pass

        elif name_stripped == "Cron":
            print(bold("\n  ── Run Cron ──\n"))
            print(dim("  Running a cron cycle now (uses cached data if fresh)…\n"))
            sys.stdout.flush()
            try:
                # Do NOT set _called_from_loop=True here — that would bypass the
                # kill switch override prompt.  Instead catch SystemExit explicitly
                # so cron's end-of-scan sys.exit(0) doesn't close the menu.
                cmd_cron(client)
            except SystemExit:
                pass  # normal cron exit — menu keeps running
            except KeyboardInterrupt:
                print(yellow("\n  Cron cancelled."))
            except Exception as exc:
                print(red(f"  Cron error: {exc}"))
            sys.stdout.flush()
            print(
                dim(
                    "\n  Tip: run  py main.py loop  in a separate terminal to auto-run every 4h."
                )
            )

        elif name_stripped == "Watch":
            _menu_watch(client)

        elif name_stripped == "Paper":
            # ── Paper submenu ─────────────────────────────────────────────────
            print(bold("\n  ── Paper Trading ──\n"))
            print(
                f"  {cyan('1')}  {bold('Results    ')}  {dim('·')}  balance, open positions, P&L"
            )
            print(
                f"  {cyan('2')}  {bold('Buy        ')}  {dim('·')}  place a paper trade"
            )
            print(
                f"  {cyan('3')}  {bold('Settle     ')}  {dim('·')}  settle an open trade"
            )
            print(
                f"  {cyan('4')}  {bold('Exit signals')} {dim('·')}  check if model has flipped"
            )
            print(
                f"  {cyan('5')}  {bold('Monte Carlo')}  {dim('·')}  simulate outcomes"
            )
            print(
                f"  {cyan('6')}  {bold('Alerts     ')}  {dim('·')}  price alert manager"
            )
            print(
                f"  {cyan('7')}  {bold('Graduation ')}  {dim('·')}  am I ready to go live?"
            )
            print(
                f"  {cyan('8')}  {bold('Journal    ')}  {dim('·')}  view trade thesis notes"
            )
            print(dim("  Enter/Q  Back"))
            sub = input(dim("\n  Choose (1–8): ")).strip()

            if sub == "1":
                cmd_paper(["results"], client)
            elif sub == "2":
                while True:
                    raw = input(dim("  Ticker (q to cancel): ")).strip()
                    if raw.lower() == "q":
                        break
                    if not raw:
                        continue
                    ticker = raw.upper()
                    while True:
                        side = (
                            input(dim("  Side (yes/no, q to cancel): ")).strip().lower()
                        )
                        if side == "q":
                            ticker = ""
                            break
                        if side in ("yes", "no"):
                            break
                    if not ticker:
                        break
                    price = _resolve_price(client, ticker, side)
                    if price is None:
                        price = _prompt_price()
                    if price is not None:
                        raw_qty = input(
                            dim("  Qty (Enter for Kelly auto-size): ")
                        ).strip()
                        qty_arg = (
                            [raw_qty] if raw_qty.isdigit() and int(raw_qty) > 0 else []
                        )
                        # Check position limits before submenu buy
                        if raw_qty.isdigit() and int(raw_qty) > 0:
                            _sub_city: str | None = None
                            _sub_tdate_str: str | None = None
                            try:
                                from weather_markets import (
                                    enrich_with_forecast as _ewf_sub,
                                )

                                _sub_enriched = _ewf_sub(
                                    client.get_market(ticker), fetch_forecast=False
                                )
                                _sub_city = _sub_enriched.get("_city")
                                _sub_tdate = _sub_enriched.get("_date")
                                _sub_tdate_str = (
                                    _sub_tdate.isoformat() if _sub_tdate else None
                                )
                            except Exception:
                                pass  # best-effort — city/date caps just get skipped below
                            try:
                                from paper import check_position_limits as _cpl_sub

                                _limit_sub = _cpl_sub(
                                    ticker,
                                    int(raw_qty),
                                    price,
                                    city=_sub_city,
                                    target_date_str=_sub_tdate_str,
                                    side=side,
                                    client=client,
                                )
                                if not _limit_sub.get("ok", True):
                                    print(
                                        red(
                                            f"  Position limit check failed: {_limit_sub.get('reason', 'limit exceeded')}"
                                        )
                                    )
                                    break
                            except Exception as _limit_exc:
                                _log.warning(
                                    "check_position_limits failed for %s, skipping limit check: %s",
                                    ticker,
                                    _limit_exc,
                                )

                        # Large bet confirmation for the submenu buy path
                        if raw_qty.isdigit() and int(raw_qty) > 0:
                            from paper import get_balance as _gb_sub

                            _qty_sub = int(raw_qty)
                            _cost_sub = _qty_sub * price
                            _bal_sub = _gb_sub()
                            if _bal_sub > 0 and _cost_sub > _bal_sub * 0.03:
                                _pct_sub = _cost_sub / _bal_sub * 100
                                _confirm_sub = (
                                    input(
                                        yellow(
                                            f"  Heads up: this bet is ${_cost_sub:.2f} ({_pct_sub:.1f}% of your ${_bal_sub:.2f} balance). "
                                            f"Continue? (y/N): "
                                        )
                                    )
                                    .strip()
                                    .lower()
                                )
                                if _confirm_sub != "y":
                                    print(dim("  Cancelled."))
                                    break
                        cmd_paper(
                            ["buy", ticker, side, f"{price:.3f}"] + qty_arg, client
                        )
                    break
            elif sub == "3":
                # ── Settle submenu ────────────────────────────────────────────
                print(bold("\n  ── Settle Trades ──\n"))
                print(
                    f"  {cyan('1')}  {bold('Auto-settle ')}  {dim('·')}  check Kalshi now and settle all due trades"
                )
                print(
                    f"  {cyan('2')}  {bold('Manual      ')}  {dim('·')}  pick a trade and enter outcome yourself"
                )
                print(dim("  Enter/Q  Back"))
                settle_sub = input(dim("\n  Choose (1–2): ")).strip()
                if settle_sub == "1":
                    from paper import auto_settle_paper_trades

                    print(dim("  Checking Kalshi for finalized markets…"))
                    sync_outcomes(client)
                    n = auto_settle_paper_trades(client)
                    if n:
                        print(green(f"  Settled {n} trade(s) automatically."))
                    else:
                        print(
                            dim(
                                "  No markets finalized yet — try again later or use Manual."
                            )
                        )
                elif settle_sub == "2":
                    _cmd_settle_open(client)
            elif sub == "4":
                try:
                    from paper import check_model_exits, close_paper_early
                    from utils import YES_ASK_KEYS, YES_BID_KEYS, coalesce_market_price

                    recs = check_model_exits(client)
                    if not recs:
                        print(
                            green("  All open positions look fine — no exit signals.")
                        )
                    else:
                        print(bold(f"\n  {len(recs)} exit signal(s):\n"))
                        for rec in recs:
                            t = rec["trade"]
                            reason = (
                                "Model flipped direction"
                                if rec["reason"] == "model_flipped"
                                else "Edge evaporated (<3%)"
                            )
                            print(
                                yellow(
                                    f"  #{t['id']}  {t['ticker']}  {t['side'].upper()}"
                                    f"  —  {reason}  (edge now {rec['current_edge']:+.1%})"
                                )
                            )
                            try:
                                choice = (
                                    input(dim("  Close this position now? (y/N): "))
                                    .strip()
                                    .lower()
                                )
                            except (KeyboardInterrupt, EOFError):
                                print()
                                break
                            if choice == "y":
                                try:
                                    _market = rec["market"]
                                    _held_side = rec["held_side"]
                                    _current_prices = {
                                        t["ticker"]: {
                                            "bid": coalesce_market_price(
                                                _market, *YES_BID_KEYS
                                            ),
                                            "ask": coalesce_market_price(
                                                _market, *YES_ASK_KEYS
                                            ),
                                        }
                                    }
                                    exit_price = _liquidation_price(
                                        _current_prices, t["ticker"], _held_side
                                    )
                                    if exit_price is None or exit_price <= 0:
                                        print(
                                            red(
                                                f"  Could not close: no realizable quote for {t['ticker']}"
                                            )
                                        )
                                    else:
                                        # batch-63 item 1: this operator path
                                        # has never checked the kill switch or
                                        # TRADING_PAUSED. That bypass is now
                                        # deliberate, for cmd_close's reason
                                        # (an exit reduces exposure) -- but it
                                        # used to be SILENT: an operator could
                                        # close through an engaged halt without
                                        # being told one was engaged, and
                                        # nothing recorded it. Announce and log.
                                        _engaged = _engaged_halt_gates()
                                        _warn_halt_bypass(_engaged)
                                        _closed = close_paper_early(t["id"], exit_price)
                                        # Own try (round-2 opus review L8):
                                        # the close has COMMITTED by now, and
                                        # this sits inside an `except` that
                                        # prints "Could not close" -- so a
                                        # raise while building the record
                                        # would tell the operator the close
                                        # failed when it did not, prompting a
                                        # retry that reports "already
                                        # settled" and reads as a second
                                        # failure. Same reasoning as
                                        # cmd_close's balance read.
                                        try:
                                            _log_operator_close(
                                                "exit-signals menu",
                                                t["id"],
                                                t["ticker"],
                                                _held_side,
                                                t.get("quantity", t.get("qty", 0)),
                                                exit_price,
                                                (_closed or {}).get("pnl", 0.0),
                                                _engaged,
                                            )
                                        except Exception:  # noqa: BLE001
                                            _log.exception(
                                                "operator close: audit record "
                                                "failed for trade #%s (the close "
                                                "itself succeeded)",
                                                t.get("id"),
                                            )
                                        print(
                                            green(f"  #{t['id']} {t['ticker']} closed.")
                                        )
                                except Exception as _ce:
                                    print(red(f"  Could not close: {_ce}"))
                            else:
                                print(dim(f"  #{t['id']} {t['ticker']} — skipped."))
                except (KeyboardInterrupt, EOFError):
                    print()
            elif sub == "5":
                cmd_montecarlo(client)
            elif sub == "6":
                _cmd_alerts()
            elif sub == "7":
                from paper import graduation_check

                grad = graduation_check()
                if grad:
                    print(
                        bold(
                            f"\n  {green('GRADUATION CHECK PASSED')} — Ready for live trading!"
                        )
                    )
                    print(
                        green(
                            f"  {grad['settled']} trades  |  Win rate: {grad['win_rate']:.0%}"
                            f"  |  P&L: +${grad['total_pnl']:.2f}"
                        )
                    )
                else:
                    print(
                        yellow(
                            "  Not yet — need 30+ settled trades, Brier ≤ 0.23, and +$50 profit."
                        )
                    )
            elif sub == "8":
                cmd_journal()

        elif name_stripped == "Backtest":
            cmd_backtest(client, [])

        elif name_stripped == "Validate":
            cmd_walkforward(client)

        elif name_stripped == "Report":
            cmd_report()

        elif name_stripped == "Brief":
            try:
                cmd_brief(client)
            except KeyboardInterrupt:
                print(yellow("\n  Brief cancelled."))
            except Exception as _e:
                print(red(f"\n  Brief failed: {_e}"))

        elif name_stripped == "Browse":
            cmd_browse(client)

        elif name_stripped == "Settings":
            cmd_settings(client)

        elif name_stripped == "Help":
            cmd_help()

        print(dim("\n  Press Enter to return to menu..."), end="", flush=True)
        input()


# ── Backtest ─────────────────────────────────────────────────────────────────


def cmd_backtest(client: KalshiClient, args: list):
    """
    Run a backtest on finalized Kalshi markets.
    Usage: py main.py backtest [city] [--days N] [--previous-runs]
    """
    from backtest import run_backtest

    city_filter = None
    days_back = 90
    use_previous_runs = False
    _skip_next = False
    for i, a in enumerate(args):
        if _skip_next:
            _skip_next = False
            continue
        if a == "--days" and i + 1 < len(args):
            try:
                days_back = int(args[i + 1])
            except ValueError:
                pass
            # Consume the value token too — without this it fell through to
            # the city_filter branch below on the next iteration, silently
            # clobbering city_filter with the days number (or being clobbered
            # by it, e.g. `backtest --days 180` set city_filter="180").
            _skip_next = True
        elif a == "--previous-runs":
            use_previous_runs = True
        elif not a.startswith("--"):
            city_filter = a

    print(
        bold(
            f"\nRunning backtest (last {days_back} days"
            + (f", {city_filter}" if city_filter else ", all cities")
            + ")...\n"
        )
    )
    print(dim("Fetching finalized markets and archive weather data..."))

    def _bt_progress(i: int, n: int) -> None:
        pct = i / n if n > 0 else 0
        filled = int(pct * 20)
        bar = "█" * filled + "░" * (20 - filled)
        print(f"\r  [{bar}] {pct:.0%}  ({i}/{n})", end="", flush=True)

    try:
        summary = run_backtest(
            client,
            city_filter=city_filter,
            days_back=days_back,
            on_progress=_bt_progress,
            use_previous_runs=use_previous_runs,
        )
    except Exception as e:
        print()  # newline after progress bar
        print(red(f"  Backtest failed: {e}"))
        print(dim("  Tip: check your API credentials and try again."))
        return
    n_scored = summary["n_markets"]
    print(f"\r  Scored {n_scored} weather market(s).              ")
    if n_scored < 30:
        print(
            yellow(
                f"  ⚠  Only {n_scored} markets found — scores may not be reliable."
                f" Try a longer window: py main.py backtest --days 180"
            )
        )

    n = summary["n_markets"]
    if n == 0:
        print(yellow(f"  No scoreable markets found in the last {days_back} days."))
        diag = summary.get("diagnostic", {})
        if diag:
            print(
                dim(
                    f"    Fetched:      {diag['n_fetched']:>4}   weather markets from Kalshi"
                )
            )
            print(
                dim(f"    Result ok:    {diag['n_result_ok']:>4}   had a yes/no result")
            )
            print(
                dim(
                    f"    Parsed:       {diag['n_parsed']:>4}   city + date extractable"
                )
            )
            print(
                dim(
                    f"    In window:    {diag['n_in_window']:>4}   within last {days_back} days"
                )
            )
            print(
                dim(
                    f"    Archive data: {diag['n_archive']:>4}   had historical weather data"
                )
            )
            if diag["n_fetched"] == 0:
                print(
                    yellow("    ↳ No settled markets found — check API connectivity.")
                )
            elif diag["n_in_window"] == 0:
                print(
                    yellow(
                        f"    ↳ All markets outside the {days_back}-day window. Try: py main.py backtest --days 365"
                    )
                )
            elif diag["n_archive"] == 0:
                print(
                    yellow(
                        "    ↳ Archive data missing — markets may be too recent. Try again tomorrow or use --days 180."
                    )
                )
        return

    brier = summary["train_brier"]
    win_rate = summary["win_rate"]
    pnl = summary["total_pnl"]
    val_brier = summary.get("val_brier")
    val_n = summary.get("val_n", 0)
    val_wr = summary.get("val_win_rate")

    print(bold(f"\n── Backtest Results ({n} markets) ──\n"))

    def _brier_str(b: float | None) -> str:
        if b is None:
            return "—"
        if b < 0.20:
            return green(f"{b:.4f}")
        elif b < 0.25:
            return yellow(f"{b:.4f}")
        return red(f"{b:.4f}")

    wr_str = (
        green(f"{win_rate:.0%}")
        if win_rate and win_rate > 0.55
        else f"{win_rate:.0%}"
        if win_rate
        else "—"
    )
    pnl_str = green(f"+{pnl:.2%}") if pnl > 0 else red(f"{pnl:.2%}")

    train_n = n - val_n
    print(
        f"  Brier score:  {_brier_str(brier)}   (train, {train_n} markets — 0.25=random, 0.0=perfect)"
    )
    if val_n > 0:
        overfit_warn = ""
        if brier and val_brier and val_brier > brier + 0.03:
            overfit_warn = f"  {yellow('⚠ possible overfit')}"
        val_wr_str = (
            green(f"{val_wr:.0%}")
            if val_wr and val_wr > 0.55
            else f"{val_wr:.0%}"
            if val_wr
            else "—"
        )
        print(
            f"  Val Brier:    {_brier_str(val_brier)}   (holdout, {val_n} markets){overfit_warn}"
        )
        print(f"  Val win rate: {val_wr_str}")
    print(f"  Win rate:     {wr_str}   (picking better side vs market)")
    print(f"  Sim P&L:      {pnl_str}   (quarter-Kelly sizing, 5% cap, maker fees)")

    # Show worst 5 and best 5
    rows = summary["rows"]
    rows_sorted = sorted(rows, key=lambda r: r["brier_sq"], reverse=True)
    worst = rows_sorted[:5]
    best = sorted(rows, key=lambda r: r["brier_sq"])[:5]

    print(bold("\n  Worst calls (highest Brier error):"))
    w_rows = [
        [
            r["ticker"],
            r["city"],
            r["date"],
            f"{r['our_prob'] * 100:.0f}%",
            f"{r['market_prob'] * 100:.0f}%",
            "YES" if r["actual"] else "NO",
            red("WRONG") if not r["won"] else green("RIGHT"),
        ]
        for r in worst
    ]
    print(
        tabulate(
            w_rows,
            headers=["Ticker", "City", "Date", "Our P", "Mkt P", "Actual", "Call"],
            tablefmt="rounded_outline",
        )
    )

    print(bold("\n  Best calls (lowest Brier error):"))
    b_rows = [
        [
            r["ticker"],
            r["city"],
            r["date"],
            f"{r['our_prob'] * 100:.0f}%",
            f"{r['market_prob'] * 100:.0f}%",
            "YES" if r["actual"] else "NO",
            green("RIGHT") if r["won"] else red("WRONG"),
        ]
        for r in best
    ]
    print(
        tabulate(
            b_rows,
            headers=["Ticker", "City", "Date", "Our P", "Mkt P", "Actual", "Call"],
            tablefmt="rounded_outline",
        )
    )

    # ── Benchmark Comparison ─────────────────────────────────────────────────
    bench_yes = summary.get("bench_yes_pnl", 0.0)
    bench_mkt = summary.get("bench_market_pnl", 0.0)
    bench_rand = summary.get("bench_random_pnl", 0.0)

    def _wr_from_rows(rows_list: list[dict], side_key: str) -> str:
        if not rows_list:
            return "—"
        wins = sum(1 for r in rows_list if r.get(side_key + "_won", False))
        return f"{wins / len(rows_list):.0%}"

    # Compute benchmark win rates
    def _bench_wr(rows_list: list[dict], bench: str) -> str:
        if not rows_list:
            return "—"
        if bench == "yes":
            wins = sum(1 for r in rows_list if r.get("actual") == 1)
        elif bench == "market":
            wins = sum(
                1
                for r in rows_list
                if (r.get("market_prob", 0.5) > 0.5 and r.get("actual") == 1)
                or (r.get("market_prob", 0.5) <= 0.5 and r.get("actual") == 0)
            )
        else:
            import random as _rand

            rng = _rand.Random(42)
            wins = sum(
                1
                for r in rows_list
                if (rng.random() > 0.5 and r.get("actual") == 1)
                or (rng.random() <= 0.5 and r.get("actual") == 0)
            )
        return f"{wins / len(rows_list):.0%}"

    our_wr_str = f"{win_rate:.0%}" if win_rate else "—"
    # These are bankroll-fraction returns (backtest.py stakes are Kelly
    # fractions capped at 0.05), not dollar amounts — the same `pnl` prints
    # correctly as "+35.00%" a few lines above this table; formatting it
    # with a "$" here made an identical quantity read as ~$0.35.
    bench_rows_table = [
        [
            "Our model",
            (green(f"+{pnl:.2%}") if pnl >= 0 else red(f"{pnl:.2%}")),
            our_wr_str,
        ],
        [
            "Always YES",
            (green(f"+{bench_yes:.2%}") if bench_yes >= 0 else red(f"{bench_yes:.2%}")),
            _bench_wr(rows, "yes"),
        ],
        [
            "Follow market",
            (green(f"+{bench_mkt:.2%}") if bench_mkt >= 0 else red(f"{bench_mkt:.2%}")),
            _bench_wr(rows, "market"),
        ],
        [
            "Random",
            (
                green(f"+{bench_rand:.2%}")
                if bench_rand >= 0
                else red(f"{bench_rand:.2%}")
            ),
            _bench_wr(rows, "random"),
        ],
    ]
    print(bold("\n  ── Benchmark Comparison ──"))
    print(
        tabulate(
            bench_rows_table,
            headers=["Strategy", "P&L", "Win%"],
            tablefmt="rounded_outline",
        )
    )

    # ── Calibration curve from live tracker (not archive replay) ────────────
    # This shows how well your LIVE model's probabilities predict outcomes —
    # separate from the synthetic archive replay above, which uses different
    # (fake) probabilities and can't diagnose the real model's bias.
    #
    # Split multiday vs sameday — see the matching note in cmd_walkforward();
    # ml_bias.py fits separate T values for each population and a merged view can
    # hide opposite-signed biases that cancel out in the mean.
    def _print_live_calibration_block(title: str, calib: dict) -> None:
        if calib["n"] < 10:
            return
        print(
            bold(
                f"\n  ── {title} Live Model Calibration (real predictions vs outcomes) ──\n"
            )
        )
        print(dim("  Predicted   Actual    N    Bias"))
        print(dim("  " + "─" * 36))
        for _bucket in calib["calibration_buckets"]:
            _bp_avg = _bucket["predicted_mean"]
            _ba_avg = _bucket["actual_rate"]
            _bb_bias = _bp_avg - _ba_avg
            _bb_s = (
                red(f"{_bb_bias * 100:>+6.1f}%  ← predictions TOO LOW")
                if _bb_bias < -0.10
                else green(f"{_bb_bias * 100:>+6.1f}%")
                if abs(_bb_bias) < 0.05
                else yellow(f"{_bb_bias * 100:>+6.1f}%")
            )
            print(
                f"  {_bp_avg * 100:>6.1f}%   {_ba_avg * 100:>6.1f}%  {_bucket['n']:>3}   {_bb_s}"
            )
        _bt_mean_p = (
            sum(b["predicted_mean"] * b["n"] for b in calib["calibration_buckets"])
            / calib["n"]
        )
        _bt_mean_a = (
            sum(b["actual_rate"] * b["n"] for b in calib["calibration_buckets"])
            / calib["n"]
        )
        _bt_sys = _bt_mean_p - _bt_mean_a
        print()
        if _bt_sys < -0.08:
            print(
                red(
                    f"  Systematic bias: {_bt_sys * 100:+.1f}% — model runs LOW. Run  py main.py calibrate  to train temperature scaling."
                )
            )
        elif _bt_sys > 0.08:
            print(
                red(
                    f"  Systematic bias: {_bt_sys * 100:+.1f}% — model runs HIGH. Run  py main.py calibrate  to train temperature scaling."
                )
            )
        else:
            print(
                green(
                    f"  Systematic bias: {_bt_sys * 100:+.1f}% — no significant global bias."
                )
            )

    try:
        from tracker import get_multiday_calibration_cli, get_sameday_calibration_cli

        _print_live_calibration_block("Multiday", get_multiday_calibration_cli())
        _print_live_calibration_block("Sameday", get_sameday_calibration_cli())
    except Exception as _bt_cal_exc:
        _log.debug("cmd_backtest: calibration curve failed: %s", _bt_cal_exc)

    # ── Breakdown by condition type ──────────────────────────────────────────
    import re as _re
    from collections import defaultdict

    def _ticker_type(ticker: str) -> str:
        t = ticker.upper()
        if "RAIN" in t or "SNOW" in t or "PRECIP" in t:
            return "precip"
        m = _re.search(r"-([TB])\d", t)
        if m:
            return {"T": "above/below", "B": "between"}.get(m.group(1), "unknown")
        if "HIGH" in t:
            return "above"
        if "LOW" in t:
            return "below"
        return "unknown"

    by_type: dict = defaultdict(list)
    for r in rows:
        ct = _ticker_type(r.get("ticker", ""))
        by_type[ct].append(r)
    if by_type:
        print(bold("\n  ── Breakdown by condition type ──"))
        ctype_rows = []
        for ct, ct_rows in sorted(by_type.items()):
            wins = sum(1 for r in ct_rows if r.get("won"))
            brier_avg = sum(r["brier_sq"] for r in ct_rows) / len(ct_rows)
            win_pct = wins / len(ct_rows) if ct_rows else 0
            ctype_rows.append([ct, len(ct_rows), f"{win_pct:.0%}", f"{brier_avg:.3f}"])
        print(
            tabulate(
                ctype_rows,
                headers=["Type", "Trades", "Win%", "Brier"],
                tablefmt="rounded_outline",
            )
        )

    # ── Breakdown by city (when no city filter applied) ────────────��──────────
    if not city_filter:
        by_city_bt: dict = defaultdict(list)
        for r in rows:
            city_key = r.get("city") or "unknown"
            by_city_bt[city_key].append(r)
        if by_city_bt:
            print(bold("\n  ── Breakdown by city ──"))
            city_bt_rows = []
            for city_key, city_rows in sorted(by_city_bt.items()):
                wins = sum(1 for r in city_rows if r.get("won"))
                win_pct = wins / len(city_rows) if city_rows else 0
                total_pnl_city = sum(r.get("pnl", 0.0) or 0.0 for r in city_rows)
                pnl_s = (
                    green(f"+${total_pnl_city:.2f}")
                    if total_pnl_city >= 0
                    else red(f"-${abs(total_pnl_city):.2f}")
                )
                city_bt_rows.append([city_key, len(city_rows), f"{win_pct:.0%}", pnl_s])
            print(
                tabulate(
                    city_bt_rows,
                    headers=["City", "Trades", "Win%", "P&L"],
                    tablefmt="rounded_outline",
                )
            )


# ── Operator close (batch-63 item 1) ─────────────────────────────────────────


def _engaged_halt_gates() -> list[str]:
    """Names of the operator halt gates currently engaged, or [].

    Shared by the two OPERATOR-initiated paper-close paths that
    deliberately run THROUGH those gates (cmd_close, and the interactive
    paper menu's exit-signals close) so they cannot drift into disagreeing
    about which gates a close is bypassing. One definition, two callers, on
    purpose -- this project has a recurring bug class of a shared safety
    check having exactly one caller forget its own copy; see
    trading_gates._check_never_skippable's own note on the same pattern.

    This is a REPORTING helper, not a gate: neither caller blocks on a
    non-empty result. See cmd_close's docstring for why.
    """
    engaged = []
    if KILL_SWITCH_PATH.exists():
        engaged.append("kill switch")
    if is_trading_paused():
        engaged.append("TRADING_PAUSED")
    return engaged


def _exit_side_quote(
    client, ticker: str, side: str
) -> tuple[float | None, float | None, str | None]:
    """(realizable_price, ceiling, why_not) for an open position's exit side.

    `realizable_price` is what closing right now would actually realize --
    a YES holder can only realize yes_bid, a NO holder only 1 - yes_ask.
    None when that side of the book is empty or the lookup failed.

    `ceiling` is an upper bound on any defensible exit price, taken from the
    OPPOSITE side (round-2 opus review L5). A one-sided book is "common
    overnight" per positions.liquidation_price's own docstring, and when the
    exit side is the empty one, the deviation cross-check in cmd_close has
    nothing to compare against and silently drops -- so `close 42 0.95`
    against a book whose YES ask is 0.05 would book a fabricated $9.50 of
    proceeds straight into balance -> peak_balance -> graduation P&L. A
    holder can never realize more than the other side is asking, so that
    price is a sound bound even when their own side is empty.

    Both are clamped to (0, 1] (round-2 opus review M1). kalshi_client.
    get_market is deliberately warn-only on an out-of-range field, so a
    malformed yes_bid of 105 coalesces to 1.05 -- and an unclamped 1.05 was
    still being used as the cross-check REFERENCE, refusing an operator's
    correctly-typed 0.60 while quoting an impossible $1.050 realizable price
    back at them. The command exists to work when other things are broken;
    it must not be blocked by the broken thing.

    The try covers ONLY the lookup/parse -- `_liquidation_price`'s
    price-SELECTION logic is deliberately outside it, matching the boundary
    web_app's own close route documents (opus review F6): a bug in the
    selection logic must raise loudly rather than be misreported to the
    operator as "no quote available" alongside a legitimate miss.
    """

    def _sane(price: float | None) -> float | None:
        return price if price is not None and 0.0 < price <= 1.0 else None

    try:
        from utils import YES_ASK_KEYS, YES_BID_KEYS, coalesce_market_price

        if client is None:
            raise RuntimeError("no Kalshi client available")
        # The {"bid","ask"} shape _liquidation_price expects, built the same
        # way the menu's exit-signal close does. NOT
        # weather_markets.parse_market_price's shape (yes_bid/yes_ask) --
        # passing that dict through unconverted would make both .get()s
        # return None and silently report "no quote" for every position.
        market = client.get_market(ticker)
        prices = {
            ticker: {
                "bid": coalesce_market_price(market, *YES_BID_KEYS),
                "ask": coalesce_market_price(market, *YES_ASK_KEYS),
            }
        }
    except Exception as exc:  # noqa: BLE001 -- reported to the operator
        return None, None, str(exc)

    quote = prices[ticker]
    # The opposite side, in the holder's own price space: a YES holder can
    # never realize more than yes_ask, a NO holder never more than
    # 1 - yes_bid.
    raw_ceiling = (
        quote["ask"]
        if side == "yes"
        else (1.0 - quote["bid"] if quote["bid"] else None)
    )
    return _sane(_liquidation_price(prices, ticker, side)), _sane(raw_ceiling), None


def _log_operator_close(
    source: str,
    trade_id: int,
    ticker: str,
    side: str,
    qty,
    exit_price: float,
    pnl: float,
    engaged: list[str],
) -> None:
    """Audit record for an operator-initiated paper close.

    Shared by BOTH operator paths, and emitted UNCONDITIONALLY -- not only
    when a halt was bypassed (opus review F9). The first version logged
    unconditionally from the CLI but only-when-bypassed from the menu, so
    reconstructing "what did the operator close, and when" from the log
    produced an incomplete picture that looked complete.

    The bypass itself is what makes this path acceptable at all (see
    cmd_close's docstring), so the record has to exist for every close.
    """
    _log.warning(
        "operator close (%s): paper trade #%s %s %s x%s @ %.4f, pnl %.2f%s",
        source,
        trade_id,
        ticker,
        side,
        qty,
        exit_price,
        pnl,
        f" (bypassed: {', '.join(engaged)})" if engaged else "",
    )


def _warn_halt_bypass(engaged: list[str]) -> None:
    """Print the deliberate-bypass notice for a non-empty _engaged_halt_gates()."""
    if not engaged:
        return
    print(
        yellow(
            f"  ⚠  {' and '.join(engaged)} engaged — closing anyway.\n"
            "     Closing REDUCES exposure; these gates block new exposure."
        )
    )


def cmd_close(client: KalshiClient | None, args: list) -> None:
    """Close an open PAPER position by trade id, regardless of the kill
    switch or TRADING_PAUSED.

    Usage: py main.py paper close <trade_id> [exit_price]
           py main.py close <trade_id> [exit_price]   (top-level alias)

    batch-63 item 1. This is the only path that can close an ARBITRARY open
    paper position while either gate is engaged, and it bypasses both
    DELIBERATELY. Read this before "fixing" it by adding a gate.

    Both gates exist to stop risk-INCREASING action. Closing a position
    removes exposure, so freezing exits under a halt makes the account
    strictly riskier at the exact moment the operator reached for the halt.
    That is the same principle batch-58 used to build
    trading_gates.pre_live_exit_check, and this does not contradict it:
    58 kept the kill switch blocking the BOT's automated live exits
    (order_executor._exit_live_position), and its own docstring hands this
    question here, saying the answer "must be an explicit operator action,
    not this gate quietly deciding on their behalf". Typing a trade id at a
    shell prompt is that explicit action. Nothing here reaches the real
    exchange either -- close_paper_early only writes the paper ledger --
    so two of the four checks 58 kept (prod-ness, LIVE_TRADING_ENABLED)
    are not even meaningful on this path.

    /api/close-position keeps BOTH gates and its 503. Do not mirror this
    bypass there: a dashboard button is misclickable in a way a typed trade
    id is not, which is the whole reason the capability lives on the CLI.

    Every close through this path is logged at WARNING with the engaged
    gates named, so a bypass is always reconstructible from the log.
    """
    from paper import close_paper_early, get_balance, get_open_trades

    if not args:
        print("Usage: py main.py paper close <trade_id> [exit_price]")
        return
    try:
        trade_id = int(args[0])
    except (TypeError, ValueError):
        print(red("  trade_id must be an integer."))
        return

    # exit_price is optional: omitted means "use the live realizable quote".
    exit_price: float | None = None
    if len(args) > 1:
        try:
            exit_price = float(args[1])
        except (TypeError, ValueError):
            print(red("  exit_price must be a number in (0, 1]."))
            return
        # Fast-fail on an obviously bad typed price BEFORE the quote lookup,
        # so the operator gets "must be in (0, 1]" rather than a confusing
        # deviation message from the cross-check below. The authoritative
        # check is the one further down, which covers the DERIVED price too.
        if not (0.0 < exit_price <= 1.0):
            print(red("  exit_price must be in (0, 1]."))
            return

    trade = next((t for t in get_open_trades() if t.get("id") == trade_id), None)
    if trade is None:
        print(red(f"  No OPEN paper trade #{trade_id}. `py main.py paper` lists them."))
        return

    side = (trade.get("side") or "yes").lower()
    ticker = trade.get("ticker") or "?"
    typed = exit_price is not None

    # One quote lookup, used for BOTH jobs: deriving the price when none was
    # given, and sanity-checking it when one was.
    derived, ceiling, quote_err = _exit_side_quote(client, ticker, side)

    if exit_price is None:
        # Deliberately NOT falling back to entry_price or a fabricated mark:
        # booking a made-up exit price into the ledger is worse than refusing
        # and telling the operator to state one, which is exactly the case
        # the optional argument exists for.
        if derived is None:
            detail = f" ({quote_err})" if quote_err else ""
            print(
                red(f"  No realizable {side.upper()} quote for {ticker}{detail}.\n")
                + dim(
                    f"  Pass a price explicitly: py main.py paper close {trade_id} 0.42"
                )
            )
            return
        exit_price = derived
    elif derived is not None and abs(exit_price - derived) > 0.15:
        # Mirrors /api/close-position's own +/-0.15 cross-check (audit-M-9),
        # which exists because close_paper_early does no validation and a
        # supplied price feeds proceeds -> balance -> drawdown tier,
        # peak_balance and graduation total_pnl (opus review F2). Without it
        # `close 42 0.95` against a 5c book books a fat-fingered WIN, and the
        # confirmation preview renders it as +P&L rather than as an error.
        # Skipped, not enforced, when no quote could be reached -- that is
        # the no-quote case a typed price is FOR, and it matches the web
        # route's own stance.
        print(
            red(
                f"  ${exit_price:.3f} deviates from the current {side.upper()}-side "
                f"realizable price ${derived:.3f} by more than 0.15 -- refusing "
                "(stale price?)."
            )
        )
        return
    elif derived is None and ceiling is not None and exit_price > ceiling:
        # The exit side of the book is empty, so there is no realizable price
        # to deviate FROM -- but the opposite side still bounds what this
        # position could possibly be worth (round-2 opus review L5). Without
        # this, the one-sided-book case silently skipped every price check.
        print(
            red(
                f"  ${exit_price:.3f} is above the most this {side.upper()} "
                f"position could realize (${ceiling:.3f}) -- refusing. "
                "The exit side of the book is empty."
            )
        )
        return

    # The (0, 1] contract applies to the FINAL price whatever its origin
    # (opus review F4). kalshi_client.get_market is deliberately warn-only on
    # an out-of-range field -- it logs and hands back what the API said,
    # leaving the decision to its caller -- so a malformed yes_bid of 105
    # coalesces to 1.05 and would otherwise book proceeds ABOVE the $1.00/
    # contract maximum payout straight into balance and peak_balance.
    if not (0.0 < exit_price <= 1.0):
        print(red("  exit_price must be in (0, 1]."))
        return

    # Name every engaged gate rather than closing silently through it. This
    # is the audit trail for a deliberate bypass, so it goes to the log at
    # WARNING as well as to the operator's screen.
    engaged = _engaged_halt_gates()
    _warn_halt_bypass(engaged)

    qty = trade.get("quantity", 0)
    est_pnl = round(exit_price * qty - trade.get("cost", 0.0), 2)
    pnl_preview = (
        green(f"+${est_pnl:.2f}") if est_pnl >= 0 else red(f"-${abs(est_pnl):.2f}")
    )
    print(
        f"  Close #{trade_id}  {ticker}  {side.upper()}  x{qty}  "
        f"@ ${exit_price:.3f}   est. P&L {pnl_preview}"
    )
    try:
        confirm = input(yellow("  Confirm close? (y/N): ")).strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return
    if confirm != "y":
        print(dim("  Cancelled."))
        return

    try:
        # Origin is recorded, not collapsed (opus review F7): /api/close-
        # position keeps "manual_close" distinct from a quote-derived close
        # for audit, and the distinction matters MORE here -- a typed price
        # is the one that skipped the cross-check when no quote was reachable.
        closed = close_paper_early(
            trade_id,
            exit_price,
            reason="operator_close_manual" if typed else "operator_close",
        )
    except ValueError as exc:
        print(red(f"  {exc}"))
        return
    except Exception as exc:  # noqa: BLE001 -- surfaced, not swallowed
        print(red(f"  Could not close: {exc}"))
        return

    pnl = closed.get("pnl", 0.0)
    _log_operator_close("cli", trade_id, ticker, side, qty, exit_price, pnl, engaged)
    pnl_str = green(f"+${pnl:.2f}") if pnl >= 0 else red(f"-${abs(pnl):.2f}")
    # The close is already committed AND already logged by this point, so the
    # confirmation must not depend on a second ledger read succeeding (opus
    # review F10): get_balance() -> paper._load() can raise on a corrupt or
    # unreadable file, and a traceback here would tell the operator the close
    # FAILED when it did not -- prompting a retry that then reports "already
    # settled", reading like a second failure.
    try:
        balance_note = f"  Balance: ${get_balance():.2f}"
    except Exception as exc:  # noqa: BLE001
        balance_note = f"  (balance unavailable: {exc})"
    print(green(f"  #{trade_id} {ticker} closed.") + f"  P&L: {pnl_str}{balance_note}")


# ── Paper trading ────────────────────────────────────────────────────────────


def cmd_paper(args: list, client: KalshiClient | None = None):
    """
    Paper trading commands:
      paper buy <ticker> <yes/no> <price> [qty]
      paper results
      paper settle <trade_id> <yes/no>
      paper close <trade_id> [exit_price]
      paper reset
    """
    from paper import (
        consensus_fraction_cap,
        get_all_trades,
        get_balance,
        get_open_trades,
        get_performance,
        is_paused_drawdown,
        kelly_bet_dollars,
        kelly_quantity,
        portfolio_kelly_fraction,
        reset_paper_account,
        settle_paper_trade,
    )
    from paper import (
        place_paper_order as _ppo_paper_cmd,  # noqa: F811
    )

    sub = args[0].lower() if args else "results"

    if sub == "buy":
        # Sibling manual paths (_quick_paper_buy, cmd_order) both refuse to
        # place while TRADING_PAUSED is set; this path never checked, so it
        # could place trades through the exact flag currently relied on to
        # keep the bot paper-only/paused.
        if is_trading_paused():
            print(
                red(
                    "  TRADING_PAUSED is set in .env — order placement is disabled.\n"
                    "  Remove TRADING_PAUSED to resume trading."
                )
            )
            return
        # qty is optional — omit to auto-size via Kelly compounding
        if len(args) < 4:
            print("Usage: py main.py paper buy <ticker> <yes/no> <price> [qty]")
            print("       Omit qty to auto-size using Kelly × current balance")
            return
        ticker = args[1]
        side = args[2].lower()
        if side not in ("yes", "no"):
            print(red("side must be 'yes' or 'no'"))
            return
        # backlog.txt "RAIN / SNOW / HURRICANE MARKETS": same reachable-
        # without-analyze_trade()/cmd_order gap _quick_paper_buy had
        # (review-caught, Snow Step 2) -- check_position_limits()'s own
        # exception path deliberately fails open, so this direct guard is
        # not redundant even though this path only ever places a paper
        # order, not a live one. Round-2 review caught this applies to
        # rain too -- unlike hurricane/snow, rain's shadow gate is live
        # and accumulating real settled predictions today.
        if is_hurricane_count_ticker(ticker) and not _hurricane_count_gates_active():
            print(
                red(
                    f"  {ticker}: hurricane season-count markets are shadow-only until "
                    "HURRICANE_TRADING_ENABLED=1 and >=20 settled hurricane-count "
                    "predictions exist — refusing to place this order."
                )
            )
            return
        if (
            is_hurricane_next_event_ticker(ticker)
            and not _hurricane_next_event_gates_active()
        ):
            print(
                red(
                    f"  {ticker}: hurricane time-to-next-event markets are shadow-only "
                    "until HURRICANE_NEXT_EVENT_TRADING_ENABLED=1 and >=20 settled "
                    "predictions exist — refusing to place this order."
                )
            )
            return
        if is_holiday_temp_ticker(ticker) and not _holiday_temp_gates_active():
            print(
                red(
                    f"  {ticker}: holiday temperature markets are shadow-only until "
                    "HOLIDAY_TEMP_TRADING_ENABLED=1 and >=20 settled predictions "
                    "exist — refusing to place this order."
                )
            )
            return
        if (
            is_rain_daily_ticker(ticker)
            or is_rain_weekend_ticker(ticker)
            or is_rain_holiday_ticker(ticker)
        ):
            print(
                red(
                    f"  {ticker}: daily/weekend/holiday rain markets are "
                    "track-only — no probability model is ever computed for "
                    "these tickers — refusing to place this order."
                )
            )
            return
        if is_storm_order_ticker(ticker) and not _storm_order_gates_active():
            print(
                red(
                    f"  {ticker}: hurricane storm-order markets are shadow-only until "
                    "STORM_ORDER_TRADING_ENABLED=1 and >=20 settled predictions "
                    "exist — refusing to place this order."
                )
            )
            return
        if (
            is_hurricane_ticker(ticker)
            and not is_hurricane_count_ticker(ticker)
            and not is_hurricane_next_event_ticker(ticker)
            and not is_storm_order_ticker(ticker)
        ):
            print(
                red(
                    f"  {ticker}: hurricane markets are not supported yet — refusing to place this order."
                )
            )
            return
        if (
            ticker.upper().startswith(tuple(_KXRAIN_MONTHLY_CITY))
            and not _rain_gates_active()
        ):
            print(
                red(
                    f"  {ticker}: monthly rain markets are shadow-only until RAIN_TRADING_ENABLED=1 "
                    "and >=20 settled rain predictions exist — refusing to place this order."
                )
            )
            return
        if (
            ticker.upper().startswith(tuple(_KXSNOW_MONTHLY_CITY))
            and not _snow_gates_active()
        ):
            print(
                red(
                    f"  {ticker}: monthly snow markets are shadow-only until SNOW_TRADING_ENABLED=1 "
                    "and >=20 settled snow predictions exist — refusing to place this order."
                )
            )
            return
        # batch-52 H-2 (opus review): _hourly_live_ok also excludes Miami
        # specifically -- see its own docstring in weather_markets.py.
        if ticker.upper().startswith(
            tuple(_KXTEMP_HOURLY_CITY)
        ) and not _hourly_live_ok(ticker):
            print(
                red(
                    f"  {ticker}: hourly-directional temperature markets are shadow-only "
                    "until HOURLY_TRADING_ENABLED=1 and >=20 settled hourly predictions "
                    "exist — refusing to place this order."
                )
            )
            return
        # batch-40 "Between-bracket calibration design", Decision 2: same
        # explicit refuse-outright treatment as the families above --
        # check_position_limits()'s own exception path fails open, so this
        # direct guard is not redundant even though this path only ever
        # places a paper order. is_between_bracket_ticker classifies by the
        # "-B<val>" ticker suffix, not a prefix, since between shares its
        # ticker family with above/below.
        if is_between_bracket_ticker(ticker) and not _between_metar_gates_active():
            print(
                red(
                    f"  {ticker}: between-bracket markets are shadow-only until "
                    "BETWEEN_TRADING_ENABLED=1 and >=20 settled between-bracket "
                    "predictions exist — refusing to place this order."
                )
            )
            return
        try:
            price = float(args[3])
            qty_s = args[4] if len(args) > 4 else None
            qty = int(qty_s) if qty_s is not None else None
        except ValueError:
            print(red("price must be a decimal; qty (optional) must be an integer"))
            return

        # Drawdown guard: block auto-sizing when drawdown exceeds MAX_DRAWDOWN_FRACTION
        # Opus-review-caught (L2): pass client (in scope on this function's
        # own signature) so this also sees a real live drawdown, not just
        # paper's.
        if is_paused_drawdown(client) and qty is None:
            from paper import MAX_DRAWDOWN_FRACTION, get_peak_balance

            floor = get_peak_balance() * (1 - MAX_DRAWDOWN_FRACTION)
            print(
                red(
                    f"\n  [Drawdown] Auto-sizing paused — balance is below "
                    f"${floor:.0f} ({MAX_DRAWDOWN_FRACTION:.0%} drawdown from peak of ${get_peak_balance():.0f})."
                )
            )
            print(
                dim("  Specify qty manually: paper buy <ticker> <side> <price> <qty>")
            )
            return

        # Get current analysis for Kelly sizing and context
        entry_prob, net_edge, fee_kelly = None, None, 0.0
        enriched: dict | None = None
        analysis: dict | None = None
        if client:
            try:
                market = client.get_market(ticker)
                enriched = enrich_with_forecast(market)
                analysis = analyze_trade(enriched)
                if analysis:
                    entry_prob = analysis["forecast_prob"]
                    net_edge = analysis.get("net_edge")
                    # ci_adjusted_kelly already factors in forecast confidence width
                    fee_kelly = analysis.get(
                        "ci_adjusted_kelly", analysis.get("fee_adjusted_kelly", 0.0)
                    )
            except Exception:
                pass

        # Extract city/date for portfolio Kelly check
        city = enriched.get("_city") if enriched else None
        target_date_obj = enriched.get("_date") if enriched else None
        target_date_str = target_date_obj.isoformat() if target_date_obj else None

        # Auto-size if qty not provided
        if qty is None:
            if fee_kelly and fee_kelly > 0.005:
                adj_kelly = portfolio_kelly_fraction(
                    fee_kelly, city, target_date_str, side=side, client=client
                )
                if adj_kelly < fee_kelly:
                    print(
                        yellow(
                            f"  [Portfolio] Kelly reduced {fee_kelly * 100:.1f}% → "
                            f"{adj_kelly * 100:.1f}% (existing {city}/{target_date_str} exposure)"
                        )
                    )
                _frac_cap = consensus_fraction_cap(analysis)
                qty = kelly_quantity(
                    adj_kelly, price, client=client, fraction_cap=_frac_cap
                )
                bet_amt = kelly_bet_dollars(
                    adj_kelly, client=client, fraction_cap=_frac_cap
                )
                print(
                    f"\n  {bold('Kelly auto-size:')} {adj_kelly * 100:.1f}% of balance "
                    f"= {green(f'${bet_amt:.2f}')} → {bold(str(qty))} contracts"
                )
            else:
                print(
                    yellow(
                        "  No Kelly fraction available — please specify qty manually."
                    )
                )
                print("  Usage: py main.py paper buy <ticker> <yes/no> <price> <qty>")
                return

        balance = get_balance()
        cost = qty * price
        print(
            f"\n  Paper BUY  {bold(str(qty))} × {ticker}  {bold(side.upper())}  @ ${price:.4f}"
        )
        print(f"  Cost: {bold(f'${cost:.2f}')}  |  Paper balance: ${balance:.2f}")
        if entry_prob is not None:
            print(
                f"  Model P: {entry_prob * 100:.1f}%"
                + (f"  Net edge: {net_edge:+.1%}" if net_edge is not None else "")
            )
        confirm = input(yellow("  Confirm paper trade? (y/N): ")).strip().lower()
        if confirm != "y":
            print(dim("  Cancelled."))
            return
        # Position-limit check (city/date, directional, correlated-group
        # caps) — the explicit-qty path here skipped it entirely; only the
        # auto-size path got any exposure scaling (via portfolio_kelly_fraction,
        # which softly scales down rather than hard-blocking).
        try:
            from paper import check_position_limits as _cpl_paper

            _limit_check_paper = _cpl_paper(
                ticker,
                qty,
                price,
                city=city,
                target_date_str=target_date_str,
                side=side,
                client=client,
            )
            if not _limit_check_paper.get("ok", True):
                print(
                    red(
                        f"  Position limit check failed: {_limit_check_paper.get('reason', 'limit exceeded')}"
                    )
                )
                return
        except Exception as _limit_exc_paper:
            _log.warning(
                "cmd_paper: check_position_limits failed for %s, skipping limit check: %s",
                ticker,
                _limit_exc_paper,
            )
        try:
            trade = _ppo_paper_cmd(
                ticker,
                side,
                qty,
                price,
                entry_prob,
                net_edge,
                city=city,
                target_date=target_date_str,
            )
            print(
                green(
                    f"  Paper trade #{trade['id']} placed. "
                    f"Remaining balance: ${get_balance():.2f}"
                )
            )
        except ValueError as e:
            print(red(f"  Error: {e}"))

    elif sub == "settle":
        if len(args) < 3:
            print("Usage: py main.py paper settle <trade_id> <yes/no>")
            return
        try:
            trade_id = int(args[1])
            outcome_yes = args[2].lower() == "yes"
        except (ValueError, IndexError):
            print(red("trade_id must be integer; outcome must be 'yes' or 'no'"))
            return
        try:
            t = settle_paper_trade(trade_id, outcome_yes)
            pnl_str = (
                green(f"+${t['pnl']:.2f}") if t["pnl"] >= 0 else red(f"${t['pnl']:.2f}")
            )
            print(
                f"  Trade #{trade_id} settled {t['outcome'].upper()}  P&L: {pnl_str}  "
                f"Balance: ${get_balance():.2f}"
            )
        except ValueError as e:
            print(red(f"  {e}"))

    elif sub == "close":
        # batch-63 item 1 -- see cmd_close's docstring for why this one
        # deliberately runs while the kill switch / TRADING_PAUSED are
        # engaged, unlike `paper buy` directly above.
        cmd_close(client, args[1:])

    elif sub == "reset":
        confirm = (
            input(yellow("  Reset all paper trades and balance? (y/N): "))
            .strip()
            .lower()
        )
        if confirm == "y":
            reset_paper_account()
            print(green("  Paper account reset to $1,000."))
        else:
            print(dim("  Cancelled."))

    else:  # "results"
        perf = get_performance()
        open_ = get_open_trades()
        all_ = get_all_trades()

        _header("Paper Trading Results")
        _kv("Balance:", bold(f"${perf['balance']:.2f}"))

        # ASCII balance history chart
        try:
            from paper import get_balance_history as _gbh

            history = _gbh()
            if len(history) >= 3:
                balances = [h["balance"] for h in history]
                print(_ascii_chart(balances, width=52, height=6, label="Balance"))
        except Exception:
            pass
        if perf["settled"]:
            wr = (
                f"{perf['win_rate'] * 100:.0f}%"
                if perf["win_rate"] is not None
                else "—"
            )
            roi_ = f"{perf['roi'] * 100:+.1f}%" if perf["roi"] is not None else "—"
            pnl_ = (
                green(f"+${perf['total_pnl']:.2f}")
                if perf["total_pnl"] >= 0
                else red(f"${perf['total_pnl']:.2f}")
            )
            _kv("Settled:", str(perf["settled"]))
            _kv("Win rate:", wr)
            _kv("ROI:", roi_)
            _kv("P&L:", pnl_)

        if open_:
            print(bold(f"\n  Open trades ({len(open_)}):"))
            rows = [
                [
                    t["id"],
                    t["ticker"],
                    t["side"].upper(),
                    t["quantity"],
                    f"${t['entry_price']:.4f}",
                    f"${t['cost']:.2f}",
                    t["entered_at"][:10],
                    (t.get("thesis") or "")[:30],
                ]
                for t in open_
            ]
            print(
                tabulate(
                    rows,
                    headers=[
                        "#",
                        "Ticker",
                        "Side",
                        "Qty",
                        "Entry",
                        "Cost",
                        "Date",
                        "Thesis",
                    ],
                    tablefmt="rounded_outline",
                )
            )

        if not all_:
            print(
                dim(
                    "\n  No trades yet.  Try: py main.py paper buy <ticker> yes 10 0.45"
                )
            )

        # ── Settled trade history ─────────────────────────────────────────────
        settled_ = [t for t in all_ if t.get("settled")]
        if settled_:
            settled_.sort(key=lambda t: t.get("settled_at") or "", reverse=True)
            print(bold(f"\n  Settled trades ({len(settled_)}):"))
            s_rows = []
            for t in settled_:
                pnl = t.get("pnl") or 0.0
                pnl_str = (
                    green(f"+${pnl:.2f}") if pnl >= 0 else red(f"-${abs(pnl):.2f}")
                )
                if t.get("outcome") == "early_exit":
                    result = yellow("EXIT")
                else:
                    result = green("WIN ") if pnl > 0 else red("LOSS")
                s_rows.append(
                    [
                        t["id"],
                        t["ticker"],
                        t["side"].upper(),
                        t["quantity"],
                        f"${t['entry_price']:.4f}",
                        f"${t['cost']:.2f}",
                        result,
                        pnl_str,
                        (t.get("settled_at") or "")[:10],
                    ]
                )
            print(
                tabulate(
                    s_rows,
                    headers=[
                        "#",
                        "Ticker",
                        "Side",
                        "Qty",
                        "Entry",
                        "Cost",
                        "Result",
                        "P&L",
                        "Settled",
                    ],
                    tablefmt="rounded_outline",
                )
            )

        # ── Factor exposure, expiry clustering, unrealized P&L ───────────────
        if open_ and client:
            try:
                from paper import (
                    get_expiry_date_clustering,
                    get_factor_exposure,
                    get_unrealized_pnl_paper,
                )

                factor_exp = get_factor_exposure()
                if factor_exp:
                    bias = factor_exp.get("net_bias", "Balanced")
                    bias_s = yellow(bias) if bias != "Balanced" else green(bias)
                    yes_cost = factor_exp.get("yes_cost", 0.0)
                    no_cost = factor_exp.get("no_cost", 0.0)
                    yes_cities = ", ".join(factor_exp.get("cities_long_yes", [])) or "—"
                    no_cities = ", ".join(factor_exp.get("cities_long_no", [])) or "—"
                    print(bold("\n  Directional exposure:"))
                    print(
                        tabulate(
                            [
                                [
                                    "YES positions",
                                    factor_exp.get("yes_count", 0),
                                    f"${yes_cost:.2f}",
                                    yes_cities,
                                ],
                                [
                                    "NO positions",
                                    factor_exp.get("no_count", 0),
                                    f"${no_cost:.2f}",
                                    no_cities,
                                ],
                            ],
                            headers=["Side", "Count", "At risk", "Cities"],
                            tablefmt="rounded_outline",
                        )
                    )
                    print(f"  Net bias: {bias_s}")

                clustering = get_expiry_date_clustering()
                if clustering:
                    print(bold("\n  Expiry date clustering:"))
                    cl_rows = []
                    for item in clustering:
                        cl_rows.append(
                            [
                                item.get("date", "?"),
                                item.get("count", 0),
                                f"${item.get('total_cost', 0):.2f}",
                            ]
                        )
                    print(
                        tabulate(
                            cl_rows,
                            headers=["Expiry date", "Positions", "At risk"],
                            tablefmt="rounded_outline",
                        )
                    )

                upnl = get_unrealized_pnl_paper(client)
                total_upnl = upnl.get("total_unrealized_pnl", 0.0)
                upnl_s = (
                    green(f"+${total_upnl:.2f}")
                    if total_upnl >= 0
                    else red(f"-${abs(total_upnl):.2f}")
                )
                print(f"\n  Unrealized P&L (mark-to-market): {bold(upnl_s)}")
                by_trade = upnl.get("by_trade", [])
                if by_trade:
                    upnl_rows = []
                    for entry in by_trade:
                        pnl_v = entry.get("unrealized_pnl", 0.0)
                        pnl_s = (
                            green(f"+${pnl_v:.2f}")
                            if pnl_v >= 0
                            else red(f"-${abs(pnl_v):.2f}")
                        )
                        upnl_rows.append(
                            [
                                entry.get("trade_id", "?"),
                                entry.get("ticker", "?"),
                                pnl_s,
                            ]
                        )
                    print(
                        tabulate(
                            upnl_rows,
                            headers=["#", "Ticker", "Unrealized P&L"],
                            tablefmt="rounded_outline",
                        )
                    )
            except Exception:
                pass

        # ── Graduation check ─────────────────────────────────────────────────
        from paper import graduation_check as _grad_check

        grad = _grad_check()
        if grad:
            print(
                bold(f"\n  {green('GRADUATION CHECK PASSED')} — Consider going live!")
            )
            print(
                green(
                    f"  {grad['settled']} trades  |  Win rate: {grad['win_rate']:.0%}  "
                    f"|  Total P&L: +${grad['total_pnl']:.2f}"
                )
            )


# ── Monte Carlo simulation ────────────────────────────────────────────────────


def cmd_montecarlo(client: KalshiClient) -> None:  # noqa: ARG001
    """Run 1000 Monte Carlo simulations on the current open paper positions."""
    from monte_carlo import simulate_portfolio
    from paper import get_open_trades

    open_trades = get_open_trades()
    if not open_trades:
        print(dim("  No open paper trades to simulate."))
        return

    _header("Monte Carlo Portfolio Simulation")
    print(
        dim(f"  Simulating 1000 outcomes for {len(open_trades)} open position(s)...\n")
    )

    result = simulate_portfolio(
        open_trades, n_simulations=1000, include_distribution=True
    )

    if result.get("all_past_date"):
        print(
            yellow(
                f"  All {len(open_trades)} open position(s) have already passed their"
                " settlement date (UTC). Nothing to simulate — outcomes are decided,"
                " just awaiting official settlement."
            )
        )
        return

    med = result["median_pnl"]
    p10 = result["p10_pnl"]
    p90 = result["p90_pnl"]
    pp = result["prob_positive"]
    pr = result["prob_ruin"]
    bal = result["current_balance"]

    sim_pnls = result.get("pnl_distribution", [])
    actual_max = sim_pnls[-1] if sim_pnls else p90
    actual_min = sim_pnls[0] if sim_pnls else p10

    def _pnl_str(v: float) -> str:
        return green(f"+${v:.2f}") if v >= 0 else red(f"-${abs(v):.2f}")

    print(f"  Balance:    ${bal:.2f}")
    print(
        f"  Max: {_pnl_str(actual_max)}  |  p90: {_pnl_str(p90)}  |  Median: {_pnl_str(med)}"
        f"  |  p10: {_pnl_str(p10)}  |  Min: {_pnl_str(actual_min)}"
    )
    print(f"  Prob of profit: {pp:.0%}  |  Ruin risk: {pr:.0%}")

    # ASCII histogram — built from the same 1000-run distribution already computed
    n_sims = result["n_simulations"]

    min_pnl = sim_pnls[0] if sim_pnls else 0.0
    max_pnl = sim_pnls[-1] if sim_pnls else 0.0
    span = max_pnl - min_pnl if max_pnl != min_pnl else 1.0
    n_bins = 10
    bins = [0] * n_bins
    for pnl in sim_pnls:
        idx = min(n_bins - 1, int((pnl - min_pnl) / span * n_bins))
        bins[idx] += 1

    print(bold(f"\n  Outcome distribution ({n_sims} simulations):"))
    max_bin = max(bins) if bins else 1
    for i, count in enumerate(bins):
        lo = min_pnl + (i / n_bins) * span
        hi = min_pnl + ((i + 1) / n_bins) * span
        bar_len = int(count / max_bin * 30)
        bar = "█" * bar_len
        label = f"${lo:+.1f}–${hi:+.1f}"
        color = green if lo >= 0 else red
        print(f"  {label:>16}  {color(bar)}  {count}")
    print()

    if result.get("n_clamped", 0) > 0:
        print(
            dim(
                f"  ℹ  {result['n_clamped']} position(s) had extreme probabilities"
                f" (<5% or >90%) and were clamped to the safe range."
                f" This is a guard against stale data — not an error."
            )
        )


# ── Web dashboard ─────────────────────────────────────────────────────────────


def cmd_web(client: KalshiClient) -> None:
    """Start local web dashboard on http://localhost:5000"""
    try:
        import flask  # noqa: F401
    except ImportError:
        print("Install Flask first: pip install flask")
        return
    from web_app import start_web

    start_web(client, port=5000, open_browser=True)


# ── Simulation sandbox ────────────────────────────────────────────────────────


def cmd_simulate(client: KalshiClient) -> None:
    """Interactive replay of historical markets — test your instincts."""
    _header("Simulation Sandbox")
    print(dim("  Loading last 20 finalized weather markets...\n"))

    try:
        from backtest import _fetch_settled_markets

        all_markets = _fetch_settled_markets(client)
    except Exception as e:
        print(red(f"  Could not load markets: {e}"))
        return

    from weather_markets import (
        enrich_with_forecast,
        parse_market_price,
    )

    weather = [m for m in all_markets if m.get("result") in ("yes", "no")][:20]
    if not weather:
        print(yellow("  No finalized weather markets found."))
        return

    user_pnl = 0.0
    model_pnl = 0.0
    user_wins = 0
    model_wins = 0
    total = 0

    # _user_fee: a human manually taking the displayed price is modeled as a
    # taker fill. _model_fee: the "Model:" P&L below claims to show what this
    # bot's own strategy would have earned (it calls analyze_trade()
    # directly) -- it must use the same maker-fee assumption analyze_trade()
    # itself uses internally, or the two would silently disagree about the
    # model's own edge.
    from utils import KALSHI_FEE_RATE as _user_fee
    from utils import KALSHI_MAKER_FEE_RATE as _model_fee

    print(
        dim(
            "  For each market, decide YES / NO / Skip. The outcome will be revealed.\n"
        )
    )
    try:
        for m in weather:
            ticker = m.get("ticker", "")
            title = (m.get("title") or ticker)[:60]
            result = m.get("result", "")
            prices = parse_market_price(m)
            yes_price = prices["mid"] if prices["mid"] > 0 else 0.5
            close_date = (m.get("close_time") or "")[:10]

            print(f"\n  {bold(ticker)}")
            print(f"  {title}")
            print(f"  Closes: {close_date}   YES price: {yes_price:.2%}")
            print(dim("  (y=YES  n=NO  s=skip)"))

            while True:
                choice = input("  Your bet: ").strip().lower()
                if choice in ("y", "n", "s"):
                    break

            if choice == "s":
                print(dim(f"  Skipped. Outcome was: {result.upper()}"))
                continue

            # Get amount
            while True:
                amt_raw = input("  Amount $: ").strip()
                try:
                    amt = float(amt_raw)
                    if amt > 0:
                        break
                except ValueError:
                    pass
                print(red("  Enter a positive dollar amount."))

            total += 1
            actual_yes = result == "yes"
            user_side = "yes" if choice == "y" else "no"
            user_entry = yes_price if user_side == "yes" else 1 - yes_price
            if user_entry <= 0:
                user_entry = 0.5
            user_won = (user_side == "yes" and actual_yes) or (
                user_side == "no" and not actual_yes
            )
            if user_won:
                winnings = (1 - user_entry) * (1 - _user_fee)
                pnl = amt / user_entry * winnings
                user_pnl += pnl
                user_wins += 1
                print(green(f"  CORRECT! Outcome: {result.upper()}  P&L: +${pnl:.2f}"))
            else:
                user_pnl -= amt
                print(red(f"  WRONG.  Outcome: {result.upper()}  P&L: -${amt:.2f}"))

            # Show what model would have done
            try:
                enriched = enrich_with_forecast(m)
                from weather_markets import analyze_trade

                analysis = analyze_trade(enriched)
                if analysis:
                    model_side = analysis["recommended_side"]
                    model_prob = analysis["forecast_prob"]
                    model_entry = yes_price if model_side == "yes" else 1 - yes_price
                    if model_entry <= 0:
                        model_entry = 0.5
                    model_won = (model_side == "yes" and actual_yes) or (
                        model_side == "no" and not actual_yes
                    )
                    model_stake = 10.0
                    if model_won:
                        mw = (1 - model_entry) * (1 - _model_fee)
                        mpnl = model_stake / model_entry * mw
                        model_pnl += mpnl
                        model_wins += 1
                        print(
                            dim(
                                f"  Model: BUY {model_side.upper()} ({model_prob:.0%})  → RIGHT (+${mpnl:.2f})"
                            )
                        )
                    else:
                        model_pnl -= model_stake
                        print(
                            dim(
                                f"  Model: BUY {model_side.upper()} ({model_prob:.0%})  → WRONG (-${model_stake:.2f})"
                            )
                        )
            except Exception:
                pass

    except (KeyboardInterrupt, EOFError):
        print()

    # Final score
    if total == 0:
        print(dim("\n  No markets played."))
        return

    print(bold(f"\n  ── Final Score ({total} markets) ──"))
    pnl_s = (
        green(f"+${user_pnl:.2f}") if user_pnl >= 0 else red(f"-${abs(user_pnl):.2f}")
    )
    mpnl_s = (
        green(f"+${model_pnl:.2f}")
        if model_pnl >= 0
        else red(f"-${abs(model_pnl):.2f}")
    )
    print(f"  You:   {pnl_s}  Win rate: {user_wins / total:.0%}")
    print(f"  Model: {mpnl_s}  Win rate: {model_wins / total:.0%}  (on $10/trade)")


# ── Weekly summary ────────────────────────────────────────────────────────────


def cmd_weekly_summary() -> None:
    """
    Generate a plain-text weekly recap saved to data/weekly_summary_{date}.txt.
    Covers: trades made this week, settled this week, P&L, Brier score trend,
    best/worst trades, which model sources were most accurate.
    Also prints to terminal.
    """
    from datetime import timedelta

    from paper import get_all_trades, get_balance
    from tracker import brier_score_rolling_with_n, get_calibration_trend

    now = datetime.now(UTC)
    week_start = now - timedelta(days=7)
    week_start_str = week_start.strftime("%Y-%m-%d")

    all_trades = get_all_trades()
    entered_this_week = [
        t for t in all_trades if (t.get("entered_at") or "") >= week_start_str
    ]
    # M-29: filter by settled_at (settlement date), not entered_at (entry
    # date) -- a position entered 10+ days ago that settled yesterday belongs
    # in this week's P&L/win-rate, and a position entered this week that's
    # still open (no settled_at yet) does not. Mirrors paper.py's
    # get_daily_pnl (P0-2/M-9) and cmd_paper's settled-history sort, both of
    # which already use settled_at for exactly this reason.
    settled_this_week = [
        t
        for t in all_trades
        if t.get("settled")
        and t.get("settled_at")
        and (t.get("settled_at") or "") >= week_start_str
    ]

    week_pnl = sum(t.get("pnl") or 0.0 for t in settled_this_week)
    week_wins = sum(1 for t in settled_this_week if (t.get("pnl") or 0) > 0)

    bs, bs_n = brier_score_rolling_with_n()
    trend = get_calibration_trend(weeks=4)
    rel = get_source_reliability()
    balance = get_balance()

    # Best and worst settled trades this week
    best = (
        max(settled_this_week, key=lambda t: t.get("pnl") or 0.0)
        if settled_this_week
        else None
    )
    worst = (
        min(settled_this_week, key=lambda t: t.get("pnl") or 0.0)
        if settled_this_week
        else None
    )

    lines = [
        f"Weekly Summary — {now.strftime('%Y-%m-%d')} (last 7 days)",
        "=" * 55,
        "",
        f"Paper balance:  ${balance:.2f}",
        f"Trades entered: {len(entered_this_week)}",
        f"Trades settled: {len(settled_this_week)}",
        f"Week P&L:       {'+' if week_pnl >= 0 else ''}${week_pnl:.2f}",
        f"Week win rate:  {week_wins / len(settled_this_week):.0%}"
        if settled_this_week
        else "Week win rate:  —",
        f"Brier (3w, n={bs_n}): {bs:.4f}" if bs else "Brier (3w):       —",
        "",
    ]

    if trend:
        lines.append("Brier trend (recent weeks):")
        for t in trend[-4:]:
            lines.append(f"  {t['week']}  {t['brier']:.4f}  (n={t['n']})")
        lines.append("")

    if best:
        lines.append(
            f"Best trade:  #{best['id']} {best['ticker']} P&L +${best.get('pnl', 0):.2f}"
        )
    if worst:
        lines.append(
            f"Worst trade: #{worst['id']} {worst['ticker']} P&L ${worst.get('pnl', 0):.2f}"
        )
    if best or worst:
        lines.append("")

    if rel:
        lines.append("Source reliability (last 30 days):")
        for city_name in sorted(rel.keys()):
            for src in ["ensemble", "nws", "climatology"]:
                stats = rel[city_name].get(src)
                if stats and stats["total"] >= 3:
                    lines.append(
                        f"  {city_name:<10} {src:<12} {stats['rate']:.0%} ({stats['total']} days)"
                    )
        lines.append("")

    lines.append("Note: This is an informational summary. Not financial advice.")

    summary_text = "\n".join(lines)

    # Save to file
    out_dir = DATA_DIR
    fname = f"weekly_summary_{now.strftime('%Y-%m-%d')}.txt"
    out_path = out_dir / fname
    try:
        out_path.write_text(summary_text, encoding="utf-8")
        print(green(f"  Saved → {out_path}"))
    except Exception as e:
        print(yellow(f"  Could not save file: {e}"))

    # Print to terminal
    print()
    for line in lines:
        print(f"  {line}")


# ── Scheduled auto-scan ──────────────────────────────────────────────────────


def cmd_schedule():
    """Register a Windows Task Scheduler job to auto-scan every 3 hours."""
    if sys.platform != "win32":
        print(yellow("Scheduled tasks are only supported on Windows."))
        return

    import shutil
    import subprocess

    schtasks = shutil.which("schtasks")
    if not schtasks:
        print(red("schtasks.exe not found — cannot register scheduled task."))
        return

    script_path = Path(__file__).resolve()
    py_exe = sys.executable

    def _esc_tr(cmd: str) -> str:
        # schtasks /TR "<cmd>" requires any quotes already inside <cmd> to be
        # backslash-escaped, or CommandLineToArgvW mis-tokenizes at the first
        # inner quote (e.g. at a space in the script's own path) and the task
        # silently fails to register — confirmed empirically with schtasks.
        return cmd.replace('"', '\\"')

    task_name = "KalshiWeatherScan"
    task_cmd = f'"{py_exe}" "{script_path}" analyze'

    # Build the schtasks command
    create_cmd = (
        f'schtasks /Create /F /SC HOURLY /MO 3 /TN "{task_name}" '
        f'/TR "{_esc_tr(task_cmd)}" /RL HIGHEST'
    )

    print(bold(f"Registering scheduled task: {task_name}"))
    print(dim(f"Command: {task_cmd}"))
    confirm = input("  Register now? (Y/n): ").strip().lower()
    # Declining just skips THIS task, same as the email/settle/settlement
    # blocks below -- previously this returned from the whole function,
    # silently skipping every later task too (the most likely real user of
    # the settlement-monitor block added below already has this task
    # registered and would naturally decline re-registering it).
    if confirm == "n":
        print(dim("Skipped."))
    else:
        result = subprocess.run(create_cmd, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            print(green(f"\nTask '{task_name}' registered — runs every 3 hours."))
            print(dim("To remove: schtasks /Delete /TN KalshiWeatherScan /F"))
        else:
            print(red(f"Failed: {result.stderr.strip() or result.stdout.strip()}"))
            print(dim("Try running this terminal as Administrator."))

    # ── Daily morning email ──────────────────────────────────────────────────
    email_task = "KalshiWeatherEmail"
    email_cmd = f'"{py_exe}" "{script_path}" brief --email'
    email_create = (
        f'schtasks /Create /F /SC DAILY /ST 07:00 /TN "{email_task}" '
        f'/TR "{_esc_tr(email_cmd)}" /RL HIGHEST'
    )

    print(bold(f"\nRegistering daily email task: {email_task}"))
    print(dim("  Sends a morning briefing email at 07:00 (requires SMTP_* env vars)."))
    confirm_email = input("  Register now? (Y/n): ").strip().lower()
    if confirm_email != "n":
        result_email = subprocess.run(
            email_create, shell=True, capture_output=True, text=True
        )
        if result_email.returncode == 0:
            print(green(f"\nTask '{email_task}' registered — emails at 7am daily."))
            print(dim("To remove: schtasks /Delete /TN KalshiWeatherEmail /F"))
        else:
            print(
                red(
                    f"Failed: {result_email.stderr.strip() or result_email.stdout.strip()}"
                )
            )

    # ── Daily settle task ────────────────────────────────────────────────────
    settle_task = "KalshiWeatherSettle"
    settle_cmd = f'"{py_exe}" "{script_path}" settle'
    settle_create = (
        f'schtasks /Create /F /SC DAILY /ST 21:00 /TN "{settle_task}" '
        f'/TR "{_esc_tr(settle_cmd)}" /RL HIGHEST'
    )

    print(bold(f"\nRegistering daily settle task: {settle_task}"))
    print(dim(f"Command: {settle_cmd}"))
    print(
        dim(
            "  Runs at 21:00 local machine time — adjust if not in your target timezone."
        )
    )
    confirm2 = input("  Register now? (Y/n): ").strip().lower()
    if confirm2 != "n":
        result2 = subprocess.run(
            settle_create, shell=True, capture_output=True, text=True
        )
        if result2.returncode == 0:
            print(green(f"\nTask '{settle_task}' registered — runs daily at 9pm."))
            print(dim("To remove: schtasks /Delete /TN KalshiWeatherSettle /F"))
        else:
            print(red(f"Failed: {result2.stderr.strip() or result2.stdout.strip()}"))

    # ── Daily settlement lag monitor ─────────────────────────────────────────
    # The 20 tracked cities span several US zones, each independently gated
    # to its own local 5-7pm window inside run_settlement_monitor(). A
    # single fixed-duration daily run, anchored to the window-OPEN instant
    # of whichever tracked zone is currently furthest EAST and running
    # until the window-CLOSE instant of whichever tracked zone is
    # currently furthest WEST, covers every city in one task — computed
    # fresh every time this registers (not hardcoded to "Eastern"
    # specifically) from settlement_monitor's own constants and the actual
    # tracked city timezones, so a future city added on EITHER side of the
    # current span doesn't silently fall outside the window.
    import math
    from zoneinfo import ZoneInfo

    settlement_duration: int | None = None
    settlement_start_str = ""
    try:
        # Imported inside the try, not at function top: settlement_monitor
        # has a module-level assertion (_CITY_SERIES_TICKER derivation)
        # that raises if Kalshi has renamed a tracked city's series again
        # — that must skip only this task, not crash cmd_schedule() after
        # the 3 tasks above already registered.
        from settlement_monitor import (
            _MONITOR_CITIES,
            _MONITOR_END_HOUR,
            _MONITOR_START_HOUR,
        )

        def _utc_offset(tz: str) -> timedelta:
            # Always non-None: `datetime.now(ZoneInfo(...))` is inherently
            # tz-aware.
            off = datetime.now(ZoneInfo(tz)).utcoffset()
            assert off is not None
            return off

        _tzs = {c["tz"] for c in _MONITOR_CITIES.values()}
        # Rank zones by UTC offset, not by each zone's own wall-clock
        # "now" — comparing wall-clock instants directly breaks whenever
        # two zones currently sit on different calendar dates relative to
        # each other (e.g. it's already past midnight Eastern while still
        # before midnight Pacific), which is true for several hours every
        # night. Offset comparison has no calendar-date component, so it's
        # immune to that. Largest (least negative) offset = easternmost,
        # whose own local window opens earliest in absolute terms;
        # smallest (most negative) = westernmost, whose window closes
        # latest.
        _open_zone = max(_tzs, key=_utc_offset)
        _close_zone = min(_tzs, key=_utc_offset)

        # Pure duration (open zone's own 2-hour window, widened by however
        # far ahead of the close zone it currently runs) — never touches a
        # wall-clock instant, so it can't inherit the date-crossing issue
        # above either.
        _span_hours = (_MONITOR_END_HOUR - _MONITOR_START_HOUR) + (
            _utc_offset(_open_zone) - _utc_offset(_close_zone)
        ).total_seconds() / 3600
        # +10min buffer (~2 poll intervals; _POLL_INTERVAL_SECONDS=300).
        settlement_duration = math.ceil(_span_hours * 60) + 10

        # The actual start instant only ever needs ONE zone's own
        # wall-clock "today" (no cross-zone date-crossing risk here).
        _start_instant = datetime.now(ZoneInfo(_open_zone)).replace(
            hour=_MONITOR_START_HOUR, minute=0, second=0, microsecond=0
        )
        # Convert that TARGET instant (not "now") to the host's own local
        # wall clock via fromtimestamp(), which asks the OS to localize
        # that specific instant — correctly DST-adjusted for it even when
        # "now" (at registration time) and the target instant fall on
        # opposite sides of a DST transition. A snapshotted fixed offset
        # (`datetime.now().astimezone().tzinfo`) would get this wrong for
        # roughly a 2-3 hour window around each transition, twice a year.
        settlement_start_str = datetime.fromtimestamp(
            _start_instant.timestamp()
        ).strftime("%H:%M")
    except Exception as exc:
        print(red(f"\nSkipping settlement monitor task: {exc}"))

    if settlement_duration is not None:
        settlement_task = "KalshiWeatherSettlementMonitor"
        settlement_cmd = (
            f'"{py_exe}" "{script_path}" settlement-monitor {settlement_duration}'
        )
        settlement_create = (
            f"schtasks /Create /F /SC DAILY /ST {settlement_start_str} "
            f'/TN "{settlement_task}" /TR "{_esc_tr(settlement_cmd)}" /RL HIGHEST'
        )

        print(bold(f"\nRegistering daily settlement monitor task: {settlement_task}"))
        print(dim(f"Command: {settlement_cmd}"))
        print(
            dim(
                f"  Runs {settlement_start_str} local machine time for "
                f"{settlement_duration} minutes, covering every tracked city's "
                "own 5-7pm-local settlement window."
            )
        )
        print(
            dim(
                "  This task runs for hours, not minutes like the others — "
                "Task Scheduler's defaults skip it on battery power and "
                "won't wake a sleeping machine for it. If this host sleeps "
                "or unplugs during its run window, open the task in Task "
                "Scheduler and adjust its Conditions/Settings tabs to match."
            )
        )
        confirm3 = input("  Register now? (Y/n): ").strip().lower()
        if confirm3 != "n":
            result3 = subprocess.run(
                settlement_create, shell=True, capture_output=True, text=True
            )
            if result3.returncode == 0:
                print(
                    green(
                        f"\nTask '{settlement_task}' registered — runs daily at "
                        f"{settlement_start_str}."
                    )
                )
                print(
                    dim(
                        "To remove: schtasks /Delete /TN KalshiWeatherSettlementMonitor /F"
                    )
                )
            else:
                print(
                    red(f"Failed: {result3.stderr.strip() or result3.stdout.strip()}")
                )


def cmd_schedule_cycles() -> None:
    """
    Print Windows Task Scheduler commands to run the cron scan at NWP model
    cycle availability times: 02:15, 08:15, 14:15, 20:15 UTC.

    NWP models initialize at 00/06/12/18 UTC; data becomes available ~2h later.
    Scanning immediately after availability captures maximum market inefficiency.

    Run each printed command once in an elevated Command Prompt (cmd.exe) to
    register the tasks — NOT PowerShell. The printed /TR value uses
    backslash-escaped quotes, which cmd.exe's CommandLineToArgvW parses
    correctly (verified: this is the same convention cmd_schedule() already
    uses successfully via subprocess shell=True); PowerShell's own argument
    tokenization treats `\"` differently and shatters the /TR value at the
    space in this repo's path, so pasting into PowerShell fails registration.
    """
    python_exe = sys.executable
    script_path = Path(__file__).resolve()

    utc_times = [2, 8, 14, 20]

    print(bold("\nNWP Cycle-Aligned Scan Schedule"))
    print(
        dim(
            "Run these commands once in an elevated Command Prompt (cmd.exe) —\n"
            "NOT PowerShell, which mis-parses the escaped quotes below:\n"
        )
    )

    for utc_hour in utc_times:
        utc_dt = datetime.now(UTC).replace(
            hour=utc_hour, minute=15, second=0, microsecond=0
        )
        # fromtimestamp() asks the OS to localize this specific TARGET instant
        # to the host's own local wall clock, correctly DST-adjusted for it —
        # mirrors cmd_schedule()'s settlement-monitor task registration just
        # above. A snapshotted `datetime.now().astimezone().tzinfo` fixed
        # offset (the prior approach here) gets this wrong for any of these
        # 4 daily times that fall on the opposite side of a DST transition
        # from whenever this command happens to be run.
        local_time_str = datetime.fromtimestamp(utc_dt.timestamp()).strftime("%H:%M")
        task_name = f"KalshiCron_{utc_hour:02d}UTC"
        # Each path must be individually quoted (a space in the repo path,
        # e.g. "C:\claude kalshi", otherwise splits the command line) and
        # those inner quotes backslash-escaped for the outer /TR wrapper —
        # previously entirely unquoted, so schtasks handed python.exe
        # 'C:\claude' as argv[0] and every scheduled scan failed silently.
        _tr_value = f'"{python_exe}" "{script_path}" cron'.replace('"', '\\"')
        cmd = (
            f'schtasks /Create /TN "{task_name}" /TR '
            f'"{_tr_value}" '
            f"/SC DAILY /ST {local_time_str} /F /RL HIGHEST"
        )
        print(f"# {utc_hour:02d}:15 UTC ({local_time_str} local)")
        print(cmd)
        print()

    print(dim("To verify tasks were created:"))
    print("schtasks /Query /FO LIST /V | findstr Kalshi")


def cmd_replay(trade_id: str) -> None:
    """
    Replay a single trade decision from stored inputs.
    Shows: inputs at time of trade, edge calculation, validation result, execution details.
    Usage: py main.py replay <trade_id>
    """
    from paper import load_paper_trades

    _log.info("cmd_replay: replaying trade %s", trade_id)

    trades = load_paper_trades()
    trade = next((t for t in trades if str(t.get("id")) == str(trade_id)), None)

    if trade is None:
        try:
            from execution_log import get_order_by_id

            trade = get_order_by_id(trade_id)
        except Exception:
            pass

    if trade is None:
        print(red(f"  Trade {trade_id!r} not found in paper trades or execution log."))
        return

    print(bold(f"\n  Trade Replay — ID {trade_id}"))
    print("  " + "─" * 48)

    for key, value in trade.items():
        print(f"  {dim(key + ':')} {value}")

    print(
        "\n  " + dim("Note: Re-running live edge calculation is not possible without")
    )
    print("  " + dim("historical forecast data. Above shows stored decision inputs."))
    print()


def cmd_undo(max_minutes: int = 5) -> None:
    """
    Reverse the most recently placed (unsettled) paper trade if it was placed
    within the last max_minutes minutes. Refunds the cost to balance.
    Usage: py main.py undo [max_minutes]
    """
    from paper import undo_last_trade

    removed = undo_last_trade(max_minutes=max_minutes)
    if removed is None:
        print(
            dim(
                f"  No unsettled trade placed within the last {max_minutes} "
                "minute(s) to undo."
            )
        )
        return
    print(
        green(
            f"  Undone: {removed.get('ticker', '?')} — refunded "
            f"${removed.get('cost', 0.0):.2f} to balance."
        )
    )


def cmd_shadow_compare(client: KalshiClient) -> None:
    """
    Shadow mode: show what the bot would trade right now without executing.
    Does NOT execute any trades. Pure read-only analysis.
    """
    print(bold("\n  Shadow Mode — Would-Trade Analysis"))
    print("  " + dim("Shows what the bot would trade now vs last actual cron run"))
    print("  " + "─" * 48)

    markets = get_weather_markets(client)
    signals = []
    for m in markets:
        try:
            enriched = enrich_with_forecast(m)
            analysis = analyze_trade(enriched)
            if analysis:
                signals.append(
                    {
                        "ticker": m.get("ticker", ""),
                        "edge": analysis.get("net_edge", analysis.get("edge", 0)),
                        "side": analysis.get("recommended_side", "yes"),
                        "kelly_fraction": analysis.get(
                            "ci_adjusted_kelly",
                            analysis.get(
                                "fee_adjusted_kelly", analysis.get("kelly", 0)
                            ),
                        ),
                    }
                )
        except Exception:
            continue

    if not signals:
        print(dim("  No signals found."))
        return

    # Gate on the same live-refreshed, walk-forward-tuned, safety-clamped
    # value cron/order_executor actually use — not the raw env var, which
    # can diverge (e.g. a tuned walk_forward_params.json exists but
    # PAPER_MIN_EDGE isn't set) and make this "what would the bot do"
    # preview show trades the real pipeline would block, or vice versa.
    from utils import get_paper_min_edge as _gpme_shadow

    would_trade = [
        sig
        for sig in signals
        if sig.get("edge", 0) >= _gpme_shadow()
        and sig.get("kelly_fraction", 0) >= 0.002
    ]

    if not would_trade:
        print(dim(f"  {len(signals)} signals scanned, none meet edge threshold."))
        return

    print(f"\n  {bold(str(len(would_trade)))} trade(s) would be placed:\n")
    for sig in would_trade:
        ticker = sig.get("ticker", "?")
        edge = sig.get("edge", 0)
        side = sig.get("side", "?")
        kelly = sig.get("kelly_fraction", 0)
        print(
            f"    {green(ticker)}  {side.upper()}  edge={edge:.1%}  kelly={kelly:.3f}"
        )

    print()


def cmd_ab_summary() -> None:
    """Show A/B test results for all active tests."""
    from ab_test import list_all_summaries

    summaries = list_all_summaries()
    if not summaries:
        print(
            dim(
                "  No A/B tests found. Tests are created programmatically via ABTest()."
            )
        )
        return
    print(bold("\n  A/B Test Results"))
    print("  " + "─" * 48)
    for test_name, state in summaries.items():
        print(f"\n  {bold(test_name)}")
        for variant, stats in state.items():
            trades = stats.get("trades", 0)
            win_rate = stats.get("wins", 0) / max(trades, 1)
            avg_edge = stats.get("total_edge", 0.0) / max(trades, 1)
            disabled = " [DISABLED]" if stats.get("disabled") else ""
            print(
                f"    {variant}{dim(disabled)}: {trades} trades, "
                f"{win_rate:.0%} win rate, {avg_edge:.3f} avg edge"
            )
    print()


def cmd_sweep() -> None:
    """Run a parameter sweep against historical paper trades."""
    from param_sweep import run_sweep

    print(bold("\n  Parameter Sweep"))
    print("  " + dim("Testing threshold ranges against historical settled trades"))
    run_sweep()


# ── Router ────────────────────────────────────────────────────────────────────


def _validate_config() -> None:
    # Exit in prod if API credentials are absent; warn-only in demo
    if _kalshi_env() == "prod":
        missing = [
            v for v in ("KALSHI_KEY_ID", "KALSHI_PRIVATE_KEY_PATH") if not os.getenv(v)
        ]
        if missing:
            print(f"FATAL: Missing required env vars for prod: {', '.join(missing)}")
            print("Add these to your .env file and restart.")
            raise SystemExit(1)
    else:
        if not os.getenv("KALSHI_KEY_ID") or not os.getenv("KALSHI_PRIVATE_KEY_PATH"):
            _log.debug(
                "_validate_config: KALSHI_KEY_ID/PRIVATE_KEY_PATH not set (demo mode — OK)"
            )


def _check_cron_staleness() -> None:
    """Print a prominent warning if cron hasn't run in 48h.

    Also warns separately if the last FULL (non ``--sameday-only``) scan is
    stale even though cron itself has been running -- a manual-cadence
    operator can keep the bot "alive" with sameday-only cycles for days
    while a broken scheduled full-scan task goes unnoticed, since that
    scenario would otherwise leave the primary check above silent (opus
    review, 2026-08-22; see cron.py's matching in-process check for the
    live-alert half of this, which fires from inside a running cron cycle
    rather than only when a human happens to look at the CLI banner).
    """
    try:
        import json as _j

        _hb = CRON_HEARTBEAT_PATH
        if not _hb.exists():
            return
        _hb_data = _j.loads(_hb.read_text())
        _last = datetime.fromisoformat(_hb_data["last_run"])
        _age_min = (datetime.now(UTC) - _last).total_seconds() / 60
        if _age_min > 2880:  # 48h
            print(
                red(
                    f"\n  WARNING: Cron last ran {_age_min / 60:.0f}h ago.\n"
                    "  Trading is paused until cron runs. Run: py main.py cron\n"
                )
            )
        # Older heartbeat files (written before --sameday-only existed) have
        # no "last_full_scan" key -- every run they recorded WAS a full scan,
        # so falling back to "last_run" for them is correct, not a guess.
        _last_full_iso = _hb_data.get("last_full_scan", _hb_data.get("last_run"))
        if _last_full_iso:
            _full_age_min = (
                datetime.now(UTC) - datetime.fromisoformat(_last_full_iso)
            ).total_seconds() / 60
            if _full_age_min > 2880:  # 48h
                print(
                    red(
                        f"\n  WARNING: Last FULL cron scan was {_full_age_min / 60:.0f}h "
                        "ago (only --sameday-only runs since, if any).\n"
                        "  Multi-day markets are not being scanned. Run: py main.py cron\n"
                    )
                )
    except Exception as _staleness_exc:
        # L-9: a corrupt/partial heartbeat file (interrupted write) used to
        # silently disable this dead-man's-switch banner with no trace --
        # log it so an operator investigating "why didn't I get warned" can
        # find the cause.
        _log.warning("_check_cron_staleness: check failed: %s", _staleness_exc)


def _setup_logging(log_file: str = "bot.log") -> None:
    # Attach rotating file handler (10 MB × 5 backups) so logs survive long runs
    from logging.handlers import RotatingFileHandler

    # Anchor a bare filename to the script directory so the log lands next to main.py
    # regardless of the CWD at launch time (e.g. running from system32 or home dir)
    _log_path = Path(log_file)
    if not _log_path.is_absolute():
        _log_path = Path(__file__).parent / _log_path

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)-15s %(message)s",
        datefmt="%H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fh = RotatingFileHandler(
        str(_log_path), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)

    # Only remove FileHandler instances (our own) — preserve pytest caplog and other handlers
    for h in root.handlers[:]:
        if isinstance(h, logging.FileHandler):
            root.removeHandler(h)
    root.addHandler(fh)
    root.addHandler(ch)


def main():
    args = sys.argv[1:]
    # Round-2 opus review (M2-4): strip --debug HERE, before every dispatch
    # check below -- each early-return exemption (setup/calibrate/schedule-
    # cycles/emos-status/emos-deactivate/kill/resume) matches only
    # `args[0]`, so `py main.py --debug kill` used to skip every one of
    # them and fall through to validate_env()/build_client() -- the exact
    # PEM/credential exposure M-A specifically moved kill/resume earlier to
    # avoid. The actual DEBUG log-level toggle stays at its original spot
    # below (needs _setup_logging() to have already installed handlers);
    # only the stripping moved earlier, via this flag.
    _debug_flag = "--debug" in args
    if _debug_flag:
        args = [a for a in args if a != "--debug"]

    # Round-2 opus review (M2-5): hoisted here (was after every early-return
    # exemption below) so kill/resume -- and setup/calibrate/schedule-cycles/
    # emos-status/emos-deactivate, which share the same early-return shape --
    # get a bot.log trail too. Pure additive setup (installs handlers, no
    # dependency on anything computed below); previously cmd_resume's own
    # "black swan state cleared" log line went nowhere (root logger had no
    # handlers yet -- logging.lastResort only emits WARNING+, and that line
    # logs at INFO) despite genuinely happening.
    _setup_logging()

    # Skip env check for setup command so new users can run it without creds
    if args and args[0].lower() == "setup":
        cmd_setup()
        return

    # calibrate only needs the local DB — no API credentials required
    if args and args[0].lower() == "calibrate":
        cmd_calibrate()
        return

    # schedule-cycles only prints commands — no API credentials required
    if args and args[0].lower() == "schedule-cycles":
        cmd_schedule_cycles()
        return

    # emos-status/emos-deactivate only touch the local DB and data/ files --
    # no API credentials required. This matters most for emos-deactivate:
    # it's the emergency revert for a bad EMOS activation, and a revert must
    # not be blocked by an unrelated broken/rotated API key.
    if args and args[0].lower() in ("emos-status", "emos_status"):
        cmd_emos_status()
        return
    if args and args[0].lower() in ("emos-deactivate", "emos_deactivate"):
        cmd_emos_deactivate()
        return

    # H-1 opus review (M-A): kill/resume -- the runbook's documented emergency
    # halt (LIVE_TRADING_RUNBOOK.md "Immediate halt") and its pair -- moved into
    # this same early-return block, mirroring emos-deactivate immediately above.
    # Merely exempting them from the bounds-check gate below (an earlier version
    # of this fix) was NOT enough: they still fell through to validate_env()
    # (exits 1 if KALSHI_KEY_ID/PRIVATE_KEY_PATH is unset OR the .pem file is
    # missing/unreadable) and build_client() (kalshi_client.py actually parses
    # the PEM via serialization.load_pem_private_key() -- a rotated/corrupted
    # key raises there), neither of which kill/resume need: both only ever
    # touch data/.kill_switch(.tmp), never an API credential or a trading-
    # parameter field.
    if args and args[0].lower() == "kill":
        cmd_kill()
        return
    if args and args[0].lower() == "resume":
        cmd_resume()
        return

    # H-1: trading-parameter bounds check, deferred here (not import time -- see
    # BotConfig.from_env() above). Exempts every command above (all return before
    # reaching here) plus the config self-repair/diagnostic surface itself --
    # opus review (H-A) caught that this gate's own error message told the
    # operator to run `py main.py settings` to fix it, while `settings` was NOT
    # exempt and would hit this exact same gate first, making the printed
    # remedy unreachable. `config`/`config-check` (read-only diagnostic) and
    # `unlock` (cron-lock recovery, no config read at all) share the same
    # "must survive a broken .env to be useful" shape.
    if args and args[0].lower() not in (
        "settings",
        "config-settings",
        "config",
        "config-check",
        "unlock",
    ):
        try:
            _bot_config.validate()
        except ValueError as _cfg_exc:
            print(red(f"\n  Invalid configuration:\n{_cfg_exc}\n"))
            print(
                dim(
                    "  Fix these in .env (or via `py main.py settings`), or run "
                    "`py main.py kill` to halt trading immediately.\n"
                )
            )
            if args[0].lower() in ("cron", "loop"):
                # Unattended invocations (scheduled task / persistent loop) have
                # no human reading this terminal -- a raw exit(1) here previously
                # meant a broken .env silently stopped every scheduled cycle with
                # nobody notified. Mirrors the kill-switch alert's pattern (cron.py).
                try:
                    from notify import send_system_alert as _cfg_alert

                    _cfg_alert(
                        "Kalshi bot: invalid configuration, trading halted",
                        f"py main.py {args[0].lower()} refused to start: {_cfg_exc}",
                        cooldown_key="invalid_config",
                    )
                except Exception:
                    pass
            sys.exit(1)

    if not validate_env():
        if not Path(".env").exists():
            print(
                yellow(
                    "  Tip: run  py main.py setup  to configure your Kalshi API credentials."
                )
            )
            go = input("  Run setup wizard now? (Y/n): ").strip().lower()
            if go != "n":
                cmd_setup()
                return
        sys.exit(1)

    cmd = args[0].lower() if args else ""
    if cmd in (
        "loop",
        "cron",
        "scan",
        "analyze",
        "emos-train",
        "backfill-emos",
        "backfill-price-history",
    ):
        _validate_config()

    # --debug enables verbose logging of API errors and silent exceptions.
    # Already stripped from `args` at the top of this function (M2-4);
    # _setup_logging() also already ran up there (M2-5) -- only the actual
    # log-level toggle happens here.
    if _debug_flag:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.disable(logging.DEBUG)

    # Warn if cron is stale (skip for the cron command itself to avoid noise).
    if not (args and args[0].lower() == "cron"):
        _check_cron_staleness()

    if _kalshi_env() == "prod":
        # KALSHI_ENV=prod always means real market data + your real account balance.
        # It does NOT mean this command can place live orders -- see
        # _compute_live_orders_possible()'s docstring for the full, traced list
        # of command paths that actually can (AUD-0014/AUD-0031/2026-08-20
        # review: this previously only recognized `watch --auto --live`, then
        # only `buy`/`sell`/`analyze` -- both versions missed real paths).
        _live_orders_possible = _compute_live_orders_possible(cmd, args)
        _log.warning("=" * 60)
        if _live_orders_possible:
            _log.warning(
                "RUNNING IN PRODUCTION MODE — LIVE ORDERS ENABLED "
                "(this command can place a real live order)"
            )
        else:
            _log.warning(
                "RUNNING IN PRODUCTION MODE — reading real market data and balance"
            )
            _log.warning("Live orders are NOT placed by this command")
        _log.warning(
            "KALSHI_ENV=prod | STARTING_BALANCE=$%.2f",
            float(os.getenv("STARTING_BALANCE", "1000")),
        )
        _log.warning("=" * 60)

    init_db()
    cleanup_data_dir()

    # No arguments → interactive menu
    if not args:
        client = build_client()
        auto_backup()
        # Show onboarding wizard on first run
        try:
            _do_onboard = _needs_onboarding()
        except Exception:
            _do_onboard = False  # M-18: DB errors must not block the interactive menu
        if _do_onboard:
            cmd_onboard()
        # H-1: the args-based gate above only runs when args[0] is set --
        # `if args and ...` short-circuits False for a bare `py main.py`
        # (this branch). Warn, don't block: the interactive menu is exactly
        # where an operator would go to fix a bad .env via Settings (S), so
        # exiting here would remove the only easy way in to fix it.
        try:
            _bot_config.validate()
        except ValueError as _cfg_exc:
            print(yellow(f"\n  Warning: invalid configuration — {_cfg_exc}\n"))
            print(
                dim(
                    "  Fix via Settings (S) or in .env — some commands (cron, "
                    "today, analyze, ...) will refuse to run until this is "
                    "resolved.\n"
                )
            )
        cmd_menu(client)
        return

    cmd = args[0].lower()
    verbose = "--verbose" in args or "-v" in args
    client = build_client()
    auto_backup()

    if cmd == "menu":
        cmd_menu(client)
    elif cmd in ("today", "t"):
        try:
            cmd_today(client)
        except KeyboardInterrupt:
            print()
        except Exception as exc:
            print(red(f"  Error: {exc}"), file=sys.stderr)
            raise
    elif cmd == "brief":
        cmd_brief(client, send_email="--email" in args)
    elif cmd == "cron":
        # Deep-review followup: this used to default to MIN_EDGE (a display-
        # oriented threshold from .env, not a trading gate) even when --edge
        # was never passed, so cron.py's floor `max(min_edge,
        # get_paper_min_edge())` silently overrode the walk-forward-tuned
        # PAPER_MIN_EDGE on every run, not just when a user explicitly asked
        # to tighten the gate. None means "no explicit override".
        _cron_edge: float | None = None
        if "--edge" in args:
            try:
                _cron_edge = float(args[args.index("--edge") + 1]) / 100
            except (IndexError, ValueError):
                pass
        cmd_cron(client, min_edge=_cron_edge, sameday_only="--sameday-only" in args)
    elif cmd == "unlock":
        if LOCK_PATH.exists():
            LOCK_PATH.unlink()
            print(green("  Cron lock released."))
        else:
            print(dim("  No cron lock file found — nothing to release."))
    elif cmd == "setup":
        cmd_setup()
    elif cmd == "markets":
        cmd_markets(client)
    elif cmd == "analyze":
        min_edge = 0.10
        if "--edge" in args:
            try:
                min_edge = float(args[args.index("--edge") + 1]) / 100
            except (IndexError, ValueError):
                print(
                    red("  --edge expects a number, e.g.: py main.py analyze --edge 5")
                )
        cmd_analyze(client, min_edge=min_edge, live="--live" in args)
    elif cmd == "watch":
        min_edge = 0.10
        if "--edge" in args:
            try:
                min_edge = float(args[args.index("--edge") + 1]) / 100
            except (IndexError, ValueError):
                pass
        cmd_watch(
            client,
            auto_trade="--auto" in args,
            min_edge=min_edge,
            live="--live" in args,
        )
    elif cmd == "market":
        if len(args) < 2:
            print("Usage: py main.py market <ticker> [--verbose]")
        else:
            cmd_market(client, args[1].upper(), verbose=verbose)
    elif cmd == "consistency":
        cmd_consistency(client)
    elif cmd == "history":
        cmd_history(client)
    elif cmd == "sync":
        cmd_sync(client)
    elif cmd == "forecast":
        if len(args) < 2:
            print(
                f"Usage: py main.py forecast <city>  ({'/'.join(CITY_COORDS.keys())})"
            )
        else:
            cmd_forecast(args[1])
    elif cmd == "afd":
        from nws_afd import CITY_WFO_OFFICE

        if len(args) < 2:
            print(f"Usage: py main.py afd <city>  ({'/'.join(CITY_WFO_OFFICE.keys())})")
        else:
            cmd_afd(args[1])
    elif cmd == "balance":
        cmd_balance(client)
    elif cmd == "positions":
        cmd_positions(client)
    elif cmd in ("buy", "sell"):
        cmd_order(client, cmd, args[1:])
    elif cmd == "cancel":
        if len(args) < 2:
            print("Usage: py main.py cancel <order_id>")
        else:
            cmd_cancel(client, args[1])
    elif cmd == "settle":
        cmd_settle(client)
    elif cmd in ("watch-settle", "watch_settle"):
        cmd_watch_settle(client, args[1:])
    elif cmd == "loop":
        cmd_loop(client, args[1:])
    elif cmd == "paper":
        cmd_paper(args[1:], client)
    elif cmd == "close":
        # Alias for `paper close` (batch-63 item 1). PAPER-only, like every
        # other close path in this file -- the live side exits through
        # order_executor._exit_live_position, never through here.
        cmd_close(client, args[1:])
    elif cmd == "backtest":
        cmd_backtest(client, args[1:])
    elif cmd == "dashboard":
        cmd_dashboard(client)
    elif cmd == "export":
        cmd_export()
    elif cmd in ("montecarlo", "simulate-portfolio", "n"):
        cmd_montecarlo(client)
    elif cmd == "web":
        cmd_web(client)
    elif cmd == "restore":
        from cloud_backup import restore_data as _restore

        _restore()
    elif cmd in ("simulate", "sandbox", "x"):
        cmd_simulate(client)
    elif cmd in ("weekly", "y"):
        cmd_weekly_summary()
    elif cmd == "journal":
        cmd_journal()
    elif cmd in ("walkforward", "wf", "validate"):
        # "validate" is the name advertised in the Brier alert — route it here
        cmd_walkforward(client)
    elif cmd in ("walk-forward", "wfbt"):
        cmd_walk_forward()
    elif cmd == "report":
        cmd_report()
    # "kill"/"resume" are handled by the early-return block near the top of
    # main() (M-A) -- both always return before dispatch reaches this elif
    # chain, so no entries for them belong here anymore.
    elif cmd == "features":
        cmd_features()
    elif cmd == "signals":
        cmd_signals()
    elif cmd == "override":
        action = args[1] if len(args) > 1 else "status"
        # CR-6: non-integer minutes arg raises ValueError before cmd_override is called,
        # silently failing the safety-pause command at exactly the wrong moment.
        try:
            mins = int(args[2]) if len(args) > 2 else 60
        except ValueError:
            print(f"Error: minutes must be a whole number, got {args[2]!r}")
            print("Usage: python main.py override [pause|resume|status] [minutes]")
            sys.exit(1)
        cmd_override(action, mins)
    elif cmd == "admin":
        action = args[1] if len(args) > 1 else ""
        if action == "accuracy-override":
            reason, mins = _parse_accuracy_override_args(args)
            cmd_admin(action, reason, mins)
        else:
            reason = " ".join(args[2:]) if len(args) > 2 else "manual admin override"
            cmd_admin(action, reason)
    elif cmd == "replay":
        trade_id = args[1] if len(args) > 1 else ""
        if not trade_id:
            print("Usage: py main.py replay <trade_id>")
        else:
            cmd_replay(trade_id)
    elif cmd == "undo":
        try:
            max_minutes = int(args[1]) if len(args) > 1 else 5
        except ValueError:
            print(f"Error: max_minutes must be a whole number, got {args[1]!r}")
            print("Usage: py main.py undo [max_minutes]")
            sys.exit(1)
        cmd_undo(max_minutes)
    elif cmd == "shadow":
        cmd_shadow_compare(client)
    elif cmd == "ab-summary":
        cmd_ab_summary()
    elif cmd == "sweep":
        cmd_sweep()
    elif cmd == "drift":
        cmd_drift()
    elif cmd in ("version-compare", "versions"):
        cmd_version_compare()
    elif cmd in ("pnl-attribution", "pnl"):
        cmd_pnl_attribution()
    elif cmd == "train-bias":
        cmd_train_bias()
    elif cmd in ("retire", "retire-strategies"):
        do_run = "--run" in args[1:]
        cmd_retire_strategies(run=do_run)
    elif cmd in ("unretire", "unretire-strategy"):
        method_arg = args[1] if len(args) > 1 else ""
        if not method_arg:
            print(
                "Usage: py main.py unretire <method> [--pin HOURS]\n"
                "  e.g.  py main.py unretire ensemble          # 72 h pin (default)\n"
                "        py main.py unretire ensemble --pin 168 # 7-day pin\n"
                "        py main.py unretire ensemble --pin 0   # no pin (re-retires next cron)"
            )
        else:
            _pin_h = 72.0
            _args_rest = args[2:]
            if "--pin" in _args_rest:
                _pi = _args_rest.index("--pin")
                try:
                    _pin_h = float(_args_rest[_pi + 1])
                except (IndexError, ValueError):
                    print(red("  --pin requires a number of hours, e.g. --pin 168"))
                    sys.exit(1)
            cmd_unretire_strategy(method_arg, pin_hours=_pin_h)
    elif cmd in ("config-check", "config"):
        cmd_config_check()
    elif cmd in ("code-audit", "audit"):
        cmd_code_audit()
    elif cmd in ("settlement-monitor", "settle-monitor"):
        cmd_settlement_monitor(client, args[1:])
    elif cmd == "readiness":
        ready = cmd_readiness(client)
        sys.exit(0 if ready else 1)
    elif cmd == "today":
        cmd_today(client)
    elif cmd == "calibrate":
        cmd_calibrate()
    elif cmd in ("emos-train", "emos_train"):
        _cmd_emos_train(activate="--activate" in args, force="--force" in args)
    # emos-status/emos-deactivate are dispatched earlier (credential-free
    # bypass, see the top of main()) and never reach here.
    elif cmd in ("backfill-emos", "backfill_emos"):
        cmd_backfill_emos(force="--force" in args)
    elif cmd in ("backfill-price-history", "backfill_price_history"):
        cmd_backfill_price_history(client)
    elif cmd in (
        "backfill-daily-temp-settlement",
        "backfill_daily_temp_settlement",
    ):
        cmd_backfill_daily_temp_settlement()
    elif cmd in ("backfill-ensemble-var", "backfill_ensemble_var"):
        cmd_backfill_ensemble_var()
    elif cmd in ("backfill-member-brier", "backfill_member_brier"):
        cmd_backfill_member_brier()
    elif cmd in ("backfill-member-actual-temp", "backfill_member_actual_temp"):
        cmd_backfill_member_actual_temp()
    elif cmd in ("settings", "config-settings"):
        cmd_settings(client)
    elif cmd == "onboard":
        cmd_onboard()
    elif cmd == "browse":
        cmd_browse(client)
    elif cmd == "schedule":
        cmd_schedule()
    elif cmd == "schedule-cycles":
        cmd_schedule_cycles()
    else:
        print(red(f"Unknown command: {cmd}"))
        print(dim("Run  py main.py  for the interactive menu."))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Interrupted.")
    except SystemExit as _se:
        if _se.code not in (0, None) and sys.platform == "win32":
            try:
                input(f"\n  Exited (code {_se.code}). Press Enter to close...")
            except (EOFError, KeyboardInterrupt):
                pass
        raise
    except Exception as _top_exc:
        import traceback

        print(f"\n  Fatal error: {_top_exc}")
        traceback.print_exc()
        if sys.platform == "win32":
            try:
                input("\n  Press Enter to close...")
            except (EOFError, KeyboardInterrupt):
                pass
        sys.exit(1)
