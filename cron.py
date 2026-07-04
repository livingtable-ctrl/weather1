"""cron.py — Background cron runner extracted from main.py.

Contains cmd_cron and its private cron-only helpers.
Path constants (LOCK_PATH, KILL_SWITCH_PATH, RUNNING_FLAG_PATH) are defined
here; main.py re-exports them.  Tests that need to redirect paths should
patch ``cron.LOCK_PATH`` (not ``main.LOCK_PATH``).
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

import execution_log
from colors import bold, cyan, dim, green, red, yellow
from kalshi_client import KalshiClient
from paths import KILL_SWITCH_PATH, LOCK_PATH, PROD_REMINDER_PATH, RUNNING_FLAG_PATH
from utils import (
    CITY_MIN_PROB_EDGE,
    DRIFT_TIGHTEN_EDGE,
    MAX_MARKET_DIVERGENCE_RATIO,
    MED_EDGE,
    MIN_EDGE,
    MIN_MARKET_PROB_TO_BET_WITH,
    MIN_PROB_EDGE,
    PAPER_MIN_EDGE,
    STRONG_EDGE,
    is_trading_paused,
    min_prob_edge_for_days_out,
)

# Use the "main" logger name so that existing tests which capture
# logging.getLogger("main") continue to see cron log output.
_log = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Path constants (owned here; main.py re-exports them)
# ---------------------------------------------------------------------------

# Set to True by the manual override path in main.cmd_cron to suppress the
# black swan re-check for one run when the user has explicitly acknowledged
# the halt condition.  Always reset to False in a finally block.
USER_OVERRIDE_ACTIVE: bool = False


# ---------------------------------------------------------------------------
# CronContext — explicit dependency injection replacing _main_module() hack
# ---------------------------------------------------------------------------


@dataclass
class CronContext:
    """All callable dependencies that cmd_cron needs from outside cron.py.

    Constructed in main.py at call-time so test monkeypatching of
    ``main.get_weather_markets`` etc. is picked up automatically.
    """

    # Lock / flag management (defined in cron.py, re-exported via main)
    acquire_cron_lock: Callable[[], bool]
    release_cron_lock: Callable[[], None]
    write_cron_running_flag: Callable[[], None]
    clear_cron_running_flag: Callable[[], None]

    # Startup checks (defined in cron.py / main.py)
    check_manual_override: Callable[[], bool]
    check_startup_orders: Callable[[], None]

    # Weather data (from weather_markets)
    get_weather_markets: Callable
    enrich_with_forecast: Callable
    analyze_trade: Callable
    get_weather_forecast: Callable
    fetch_temperature_nbm: Callable
    fetch_temperature_ecmwf: Callable
    fetch_temperature_weatherapi: Callable
    check_ensemble_circuit_health: Callable

    # Execution (from order_executor, re-exported via main)
    auto_place_trades: Callable
    log_shadow_predictions: Callable
    check_early_exits: Callable

    # Outcome tracking (from tracker)
    sync_outcomes: Callable


# ---------------------------------------------------------------------------
# Exported cron helpers
# ---------------------------------------------------------------------------


def _write_cron_running_flag() -> None:
    """Write UTC ISO timestamp to RUNNING_FLAG_PATH; warn if a fresh flag already exists."""
    import time as _time

    rfp = RUNNING_FLAG_PATH
    try:
        if rfp.exists():
            age = _time.time() - rfp.stat().st_mtime
            if age < 600:
                _log.warning(
                    "cmd_cron: previous cron run may not have completed cleanly "
                    "(flag age=%.0fs < 600s)",
                    age,
                )
        rfp.parent.mkdir(exist_ok=True)
        rfp.write_text(
            __import__("datetime")
            .datetime.now(__import__("datetime").timezone.utc)
            .isoformat()
        )
    except Exception as _e:
        _log.warning("cmd_cron: could not write running flag: %s", _e)


def _clear_cron_running_flag() -> None:
    """Delete RUNNING_FLAG_PATH if it exists."""
    try:
        RUNNING_FLAG_PATH.unlink(missing_ok=True)
    except Exception as _e:
        _log.warning("cmd_cron: could not clear running flag: %s", _e)


def _check_startup_orders() -> None:
    """Warn if any orders were placed in the last 5 minutes (double-execution guard)."""
    import time as _time

    try:
        recent = execution_log.get_recent_orders(limit=50)
        cutoff = _time.time() - 300  # 5 minutes
        for order in recent:
            placed_at_str = order.get("placed_at", "")
            if not placed_at_str:
                continue
            try:
                from datetime import datetime as _dt

                placed_dt = _dt.fromisoformat(placed_at_str)
                if placed_dt.tzinfo is None:
                    placed_dt = placed_dt.replace(tzinfo=UTC)
                placed_ts = placed_dt.timestamp()
            except ValueError:
                continue
            if placed_ts >= cutoff:
                _log.warning(
                    "cmd_cron: recent order detected at startup — "
                    "possible double-execution (ticker=%s side=%s placed_at=%s)",
                    order.get("ticker", "?"),
                    order.get("side", "?"),
                    placed_at_str,
                )
    except Exception as _e:
        _log.warning("cmd_cron: _check_startup_orders failed: %s", _e)


try:
    import psutil as _psutil

    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False


def _acquire_cron_lock() -> bool:
    """
    Try to acquire the cron file lock. Fail CLOSED on every error.

    Returns True only when the lock is cleanly written by this process.
    Returns False in every other case — including I/O errors — so a
    concurrent cron run is never allowed through on an unexpected failure.

    Stale detection is PID-aware when psutil is available:
    - Live PID  → block (another instance is really running).
    - Dead PID  → override (process is gone, lock is stale).
    - No psutil → conservative 1800 s age threshold before overriding.
    """
    import time as _time

    lp = LOCK_PATH
    try:
        if lp.exists():
            # CR-1: safe defaults so `if pid` at line below never raises NameError
            # when the inner try block exits via the except path.
            pid = None
            started_at = 0
            heartbeat = 0
            try:
                existing = json.loads(lp.read_text())
                pid = existing.get("pid")
                started_at = existing.get("started_at", 0)
                heartbeat = existing.get("heartbeat", started_at)
            except Exception as parse_err:
                # Fail closed: corrupt / unreadable lock means we cannot verify whether
                # another cron instance is running. Remove the bad file and refuse to
                # proceed — callers can retry. (Old plain-integer-PID format also hits
                # this path; the safer choice is still to block rather than proceed.)
                _log.warning(
                    "cmd_cron: unreadable lock file (%s) — fail-closed, aborting",
                    parse_err,
                )
                try:
                    lp.unlink()
                except OSError:
                    pass
                return False

            if pid and _PSUTIL_AVAILABLE:
                if _psutil.pid_exists(pid):
                    age = _time.time() - started_at
                    _log.warning(
                        "cmd_cron: lock held by live PID %d (started %.0fs ago) — skipping",
                        pid,
                        age,
                    )
                    return False
                # PID is gone — safe to override.
                _log.warning("cmd_cron: overriding stale lock from dead PID %d", pid)
            else:
                # psutil unavailable — use conservative heartbeat age.
                age = _time.time() - heartbeat
                if age < 1800:
                    _log.warning(
                        "cmd_cron: lock age %.0fs < 1800s; refusing to override without psutil",
                        age,
                    )
                    return False
                _log.warning(
                    "cmd_cron: overriding stale lock (%.0fs old, psutil unavailable)",
                    age,
                )

        lp.parent.mkdir(exist_ok=True)
        lock_data = {
            "pid": os.getpid(),
            "started_at": _time.time(),
            "heartbeat": _time.time(),
        }
        lp.write_text(json.dumps(lock_data))
        return True

    except Exception as exc:
        _log.error(
            "cmd_cron: lock acquisition failed: %s — aborting (fail-closed)", exc
        )
        return False  # FAIL CLOSED — never proceed on unexpected error


def _release_cron_lock() -> None:
    """Delete the cron lock file."""
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except Exception as _e:
        _log.warning("cmd_cron: could not release lock: %s", _e)


def _is_cron_running() -> bool:
    """Read-only check: return True if a cron process holds the lock right now.

    Uses the same PID-aware logic as _acquire_cron_lock but never writes.
    Returns False (not running) when the lock file is absent, stale, or unreadable,
    so callers default to allowing a new run rather than blocking indefinitely.
    """
    import time as _time

    lp = LOCK_PATH
    if not lp.exists():
        return False
    try:
        existing = json.loads(lp.read_text())
        pid = existing.get("pid")
        started_at = existing.get("started_at", 0)
        heartbeat = existing.get("heartbeat", started_at)
    except Exception:
        return False  # unreadable lock — treat as not running

    if pid and _PSUTIL_AVAILABLE:
        return bool(_psutil.pid_exists(pid))
    # psutil unavailable — treat as running only if the lock is recent
    return (_time.time() - heartbeat) < 1800


def _check_graduation_gate() -> None:
    """Prevent accidental live trading before enough settled predictions exist.

    Reads ENABLE_MICRO_LIVE env var. If 'true', verifies tracker has at least
    utils.MIN_BRIER_SAMPLES settled predictions before allowing live trading to proceed.

    Raises:
        RuntimeError: when ENABLE_MICRO_LIVE='true' and count < MIN_BRIER_SAMPLES.
    """
    if os.getenv("ENABLE_MICRO_LIVE", "false").lower() != "true":
        return

    import tracker
    import utils as _utils

    count = tracker.count_settled_predictions()
    if count < _utils.MIN_BRIER_SAMPLES:
        raise RuntimeError(
            f"Graduation gate: {count} settled predictions < "
            f"MIN_BRIER_SAMPLES={_utils.MIN_BRIER_SAMPLES}. "
            f"Set ENABLE_MICRO_LIVE=false or accumulate more paper trades."
        )


def _check_spend_cap_vs_balance() -> None:
    """Warn if MAX_DAILY_SPEND exceeds the current paper balance.

    A spend cap that exceeds the available balance can never trigger and indicates
    a config mistake.
    """
    import paper as _paper

    _bal = _paper.get_balance()
    _spend_cap = float(os.getenv("MAX_DAILY_SPEND", "0"))
    if _spend_cap > 0 and _spend_cap > _bal:
        logging.getLogger(__name__).warning(
            "[cron] MAX_DAILY_SPEND=%.2f exceeds current balance=%.2f — cap will never trigger",
            _spend_cap,
            _bal,
        )


def _check_manual_override() -> bool:
    """
    Returns True if a valid (non-expired) manual override is active.
    Auto-clears expired overrides.
    """
    import time as _time

    override_path = Path(__file__).parent / "data" / ".manual_override.json"
    if not override_path.exists():
        return False
    try:
        state = json.loads(override_path.read_text())
        expires = state.get("expires_at", 0)
        if _time.time() > expires:
            override_path.unlink(missing_ok=True)
            _log.info("_check_manual_override: expired override cleared")
            return False
        remaining = (expires - _time.time()) / 60
        _log.warning(
            "Manual override active — trading paused (%.0f min remaining): %s",
            remaining,
            state.get("reason", "manual pause"),
        )
        return True
    except Exception as exc:
        _log.debug("_check_manual_override: %s", exc)
        return False


_ANOMALY_THRESHOLD = 0.12  # pp drift required to flag a market

# Reminder fires once per day after this date when KALSHI_ENV=prod.
# Change this date to push the reminder further out (e.g. after graduation).
_PROD_REMINDER_DATE = _dt.date(2026, 7, 29)

_PROD_REMINDER_CHECKLIST = """\
[1-month prod reminder] Deferred items to review:

  1. emos-train       : EMOS code deployed but emos_params.json absent (fallback mode).
                        Run: py main.py emos-train
                        Two-stage: a+b from all 79 rows, c+d from 15 with non-NULL ens_var.

  2. below_gate       : Gate is DORMANT until count_settled_below_predictions() >= 30.
                        Check count, then set BELOW_GATE_ENABLED=1 in .env.

  3. sameday-reserve  : Dormant until 150 same-day settled.
                        Run: py main.py admin sameday-stats at 150, then set
                        SAME_DAY_RESERVE_SLOTS + SAME_DAY_RESERVE_AFTER_HOUR_UTC in .env.

  4. learned_weights  : Locked until ~150-200 multi-day settled.
                        Do NOT update before that threshold.

  5. G2/G4 splits     : Split weather_markets.py + paper.py after graduation
                        (Brier last-50 <= 0.23 gate clears).
"""


def _check_prod_reminder() -> None:
    """Log a deferred-items checklist once per day after _PROD_REMINDER_DATE in prod mode."""
    if os.getenv("KALSHI_ENV", "demo").lower() != "prod":
        return
    if _dt.date.today() < _PROD_REMINDER_DATE:
        return
    try:
        if PROD_REMINDER_PATH.exists():
            last = PROD_REMINDER_PATH.read_text().strip()
            if last == str(_dt.date.today()):
                return
        _log.warning(_PROD_REMINDER_CHECKLIST)
        try:
            from notify import send_system_alert as _alert

            _alert(
                "Kalshi bot — 1-month prod reminder",
                "Deferred items need review: emos-train, below_gate, sameday-reserve, learned_weights, G2/G4. Check bot.log for details.",
            )
        except Exception as _ntfy_exc:
            _log.debug("prod reminder ntfy failed: %s", _ntfy_exc)
        PROD_REMINDER_PATH.write_text(str(_dt.date.today()))
    except Exception as _exc:
        _log.debug("_check_prod_reminder failed: %s", _exc)


def check_market_anomalies(signals: list[dict]) -> list[dict]:
    """Return signals where |blended_prob − market_price| > _ANOMALY_THRESHOLD."""
    return [
        s
        for s in signals
        if abs(s.get("blended_prob", 0.5) - s.get("market_price", 0.5))
        > _ANOMALY_THRESHOLD
    ]


def report_anomalies(anomalies: list[dict]) -> None:
    """Print anomaly warnings; no-op when list is empty."""
    if not anomalies:
        return
    print(f"\n  Market anomalies ({len(anomalies)}) — price drifted against model:")
    for a in anomalies:
        ticker = a.get("ticker", "?")
        our = a.get("blended_prob", 0.0)
        mkt = a.get("market_price", 0.0)
        raw_temp = a.get("forecast_temp_raw")
        temp_str = f"  raw={raw_temp:.1f}°F" if raw_temp is not None else ""
        print(
            f"  {ticker:<35} our={our:.0%}  market={mkt:.0%}"
            f"  drift={mkt - our:+.0%}{temp_str}"
        )
    _log.warning("Anomalies flagged: %s", [a.get("ticker") for a in anomalies])


def _cmd_cron_body(
    ctx: CronContext, client: KalshiClient, min_edge: float = MIN_EDGE
) -> bool | None:
    """Core scan logic — extracted from cmd_cron so it can be wrapped in try/finally."""
    # P8.3 — hard kill switch: touch data/.kill_switch to halt immediately
    if KILL_SWITCH_PATH.exists():
        _log.critical(
            "KILL SWITCH ACTIVATED — halting cron execution immediately. Remove data/.kill_switch to resume."
        )
        print(
            red(
                "\n  \u26a0  KILL SWITCH ACTIVE \u2014 trading halted. Delete data/.kill_switch to resume.\n"
            )
        )
        return None

    # P8.4 — manual override check (time-limited pause)
    if ctx.check_manual_override():
        _log.warning("cmd_cron: manual override active — skipping this run")
        return None

    from paper import get_accuracy_halt_reason as _get_accuracy_halt_reason
    from paper import is_accuracy_halted as _is_accuracy_halted

    if _is_accuracy_halted():
        _reason = _get_accuracy_halt_reason()
        _log.warning(
            "ACCURACY HALT ACTIVE: %s — skipping all trades this cycle",
            _reason or "accuracy circuit breaker active",
        )
        return None

    # Dead-man's-switch: if more than 48h have elapsed since the last cron run completed,
    # log a warning and fire a system notification so the user knows the bot went quiet.
    # .cron_last_run is written in the cmd_cron finally block on every completion, so a
    # gap > 48h means the process was stopped or crashing for at least two days.
    try:
        _last_run_path = Path(__file__).parent / "data" / ".cron_last_run"
        if _last_run_path.exists():
            import time as _gap_time

            _gap_hours = (_gap_time.time() - _last_run_path.stat().st_mtime) / 3600
            if _gap_hours > 48:
                _log.warning(
                    "cmd_cron: %.0fh since last cron run — gap alert fired",
                    _gap_hours,
                )
                from notify import send_system_alert as _sys_alert

                _sys_alert(
                    "Kalshi cron gap detected",
                    f"Last run was {_gap_hours:.0f}h ago — check the bot.",
                )
    except Exception as _gap_exc:
        _log.debug("cmd_cron: dead-man's-switch check failed: %s", _gap_exc)

    # Graduation gate — prevent accidental live trading before sufficient predictions exist
    try:
        _check_graduation_gate()
    except RuntimeError as _gate_err:
        _log.error("%s", _gate_err)
        return None

    # Spend cap validation — warn if MAX_DAILY_SPEND exceeds current balance
    _check_spend_cap_vs_balance()

    # 1-month prod reminder — fires once per day after _PROD_REMINDER_DATE in prod mode
    _check_prod_reminder()

    # Kalshi series drift detection — once per day, observational only, never
    # blocks trading (found the original stale-ticker bug via manual
    # investigation; this catches the next one automatically).
    try:
        from weather_markets import check_series_drift as _check_series_drift

        _check_series_drift(client)
    except Exception as _drift_exc:
        _log.debug("check_series_drift call failed: %s", _drift_exc)

    from datetime import UTC, datetime

    print(
        cyan(
            f"  [cron] scan starting \u2014 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        ),
        flush=True,
    )

    # Settle any resolved trades before scanning so same-day slot counts reflect
    # current open risk, not yesterday's expired-but-not-yet-settled positions.
    # Running settlement first means _same_day_open in order_executor is clean at
    # trade time \u2014 expired Jun(N-1) same-day trades won't block Jun(N) slots.
    try:
        from paper import auto_settle_paper_trades as _pre_settle

        _pre_settled = _pre_settle(client)
        if _pre_settled:
            _pre_net = sum(t.get("pnl") or 0.0 for t in _pre_settled)
            _pre_str = (
                f"+${_pre_net:.2f}" if _pre_net >= 0 else f"-${abs(_pre_net):.2f}"
            )
            print(
                green(
                    f"  [PreSettle] {len(_pre_settled)} trade(s) settled before scan \u2014 net P&L: {_pre_str}"
                )
            )
    except Exception as _pre_settle_exc:
        _log.warning("cmd_cron: pre-scan settlement failed: %s", _pre_settle_exc)

    # Log trades within 0–2h of close for future calibration analysis.
    # Data cannot be back-filled — write every cycle, deduplicate via unique index.
    try:
        import sqlite3 as _nsl_sqlite

        from paper import check_expiring_trades as _check_expiring
        from tracker import DB_PATH as _NSL_DB

        _near = [t for t in _check_expiring(warn_hours=2) if t["hours_left"] >= 0]
        if _near:
            with _nsl_sqlite.connect(_NSL_DB) as _nsl_con:
                for _nt in _near:
                    _tr = _nt["trade"]
                    _nsl_con.execute(
                        "INSERT OR IGNORE INTO near_settlement_log "
                        "(ticker, our_model_prob, market_yes_price, hours_to_close, "
                        " trade_side, days_out, recorded_at) VALUES (?,?,?,?,?,?,?)",
                        (
                            _tr.get("ticker"),
                            _tr.get("forecast_prob"),
                            None,  # market_yes_price: Phase 2 — requires live market fetch
                            _nt["hours_left"],
                            _tr.get("recommended_side"),
                            _tr.get("days_out", 0),
                            datetime.now(UTC).isoformat(),
                        ),
                    )
            _log.info("near_settlement_log: logged %d trade(s)", len(_near))
    except Exception as _nsl_err:
        _log.warning("near_settlement_log: write failed: %s", _nsl_err)

    # When neither dynamic nor static same-day reservation is active, remind the user
    # to enable dynamic mode once enough data has accumulated.
    try:
        from utils import (
            SAME_DAY_DYNAMIC_SLOTS,
            SAME_DAY_RESERVE_MIN_SAMPLES,
            SAME_DAY_RESERVE_SLOTS,
        )

        if not SAME_DAY_DYNAMIC_SLOTS and SAME_DAY_RESERVE_SLOTS == 0:
            from tracker import count_settled_sameday_predictions

            _sd_count = count_settled_sameday_predictions()
            if _sd_count >= SAME_DAY_RESERVE_MIN_SAMPLES:
                print(
                    yellow(
                        f"  [SameDayReserve] {_sd_count} same-day trades settled — "
                        f"set SAME_DAY_DYNAMIC_SLOTS=1 in .env to activate dynamic per-band cap scaling."
                    )
                )
    except Exception:
        pass

    # EMOS readiness reminder: print until emos_params.json exists (training done).
    # Reminds operator to run backfill-emos and, once ~40 rows accumulated, emos-train.
    # 40 = Gneiting 2005 minimum: 10 forecast cases per parameter × 4 EMOS parameters.
    _EMOS_PARAMS_PATH = Path(__file__).parent / "data" / "emos_params.json"
    if not _EMOS_PARAMS_PATH.exists():
        try:
            from tracker import count_emos_ready_predictions

            _emos_n = count_emos_ready_predictions()
            _EMOS_TRAIN_GATE = 40
            if _emos_n == 0:
                print(
                    yellow(
                        f"  [EMOS] ens_mean rows: {_emos_n}/{_EMOS_TRAIN_GATE} — "
                        f"run 'py main.py backfill-emos' to populate history."
                    )
                )
            elif _emos_n < _EMOS_TRAIN_GATE:
                print(
                    yellow(
                        f"  [EMOS] ens_mean rows: {_emos_n}/{_EMOS_TRAIN_GATE} — "
                        f"accumulating; run 'py main.py backfill-emos' if new trades settled."
                    )
                )
            else:
                print(
                    yellow(
                        f"  [EMOS] ens_mean rows: {_emos_n} — READY. "
                        f"Implement and run 'py main.py emos-train' to fit EMOS parameters."
                    )
                )
        except Exception:
            pass

    # Weekly DB retention sweep (runs on Monday only, at most once per 7 days).
    # Uses a marker file so back-to-back cron runs on the same Monday don't
    # re-run the sweep.  A skipped Monday is handled automatically: next Monday
    # the marker will be ≥14 days old and the sweep fires normally.
    from utils import utc_today as _utc_today

    _MONDAY_SWEEP_PATH = Path(__file__).parent / "data" / ".last_monday_sweep"
    if _utc_today().weekday() == 0:  # Monday UTC
        _sweep_age = (
            (datetime.now(UTC).timestamp() - _MONDAY_SWEEP_PATH.stat().st_mtime) / 86400
            if _MONDAY_SWEEP_PATH.exists()
            else 999.0
        )
        if _sweep_age >= 7:
            try:
                from tracker import prune_api_requests as _prune_api
                from tracker import purge_old_predictions as _purge

                _purge(retention_days=730)
                _prune_api(days_to_keep=90)

                from feature_importance import prune_feature_log as _prune_features

                _prune_features()

                from tracker import prune_old_analysis_attempts as _prune_attempts

                _prune_attempts(days=30)

                # Compact the SQLite DB after pruning removes rows.
                from tracker import vacuum_database as _vacuum_db

                _vacuum_db()
            except Exception as _sweep_exc:
                _log.warning("cmd_cron: Monday sweep failed: %s", _sweep_exc)
            finally:
                _MONDAY_SWEEP_PATH.parent.mkdir(exist_ok=True)
                _MONDAY_SWEEP_PATH.touch()

    # Update heartbeat on every cycle so watchdog.py can detect silent crashes
    try:
        from watchdog import update_heartbeat as _update_hb

        _update_hb()
    except Exception as _hb_exc:
        _log.warning("cmd_cron: update_heartbeat failed: %s", _hb_exc)

    ctx.write_cron_running_flag()
    ctx.check_startup_orders()

    # Item 19: validate weight files at startup so missing/malformed entries
    # are surfaced in the log before any trade analysis begins.
    try:
        from calibration import validate_weight_files as _vwf

        _vwf()
    except Exception as _vwf_exc:
        _log.warning("cmd_cron: validate_weight_files failed: %s", _vwf_exc)

    # Reconcile any 'pending' live orders left by a previous crash
    if client is not None:
        try:
            from order_executor import _recover_pending_orders

            _recover_pending_orders(client)
        except Exception as _rpo_exc:
            _log.warning("cmd_cron: _recover_pending_orders failed: %s", _rpo_exc)

    # Phase 1 — surface prolonged Open-Meteo outages immediately
    try:
        ctx.check_ensemble_circuit_health()
    except Exception as _e:
        _log.debug("cmd_cron: check_ensemble_circuit_health failed: %s", _e)

    # Phase 9 — snapshot circuit state so we can detect newly-opened circuits after scan
    try:
        from weather_markets import (
            _ensemble_cb,
            _forecast_cb,
            _pirate_cb,
            _weatherapi_cb,
        )

        _pre_scan_cb_states = {
            "open_meteo_forecast": _forecast_cb.is_open(),
            "open_meteo_ensemble": _ensemble_cb.is_open(),
            "weatherapi": _weatherapi_cb.is_open(),
            "pirate_weather": _pirate_cb.is_open(),
        }
        _scan_cbs = {
            "open_meteo_forecast": _forecast_cb,
            "open_meteo_ensemble": _ensemble_cb,
            "weatherapi": _weatherapi_cb,
            "pirate_weather": _pirate_cb,
        }
    except Exception as _e:
        _log.debug("cmd_cron: circuit state snapshot failed: %s", _e)
        _pre_scan_cb_states = {}
        _scan_cbs = {}

    # P8.2 — anomaly detection at start of cron cycle
    try:
        from alerts import run_anomaly_check as _run_anomaly_check

        _detected_anomalies, _should_halt = _run_anomaly_check(log_results=True)
        if _should_halt:
            if USER_OVERRIDE_ACTIVE:
                # Kill-switch override already acknowledged — suppress anomaly halt too
                # so the user isn't double-prompted in the same manual run.
                _log.warning(
                    "cmd_cron: anomaly halt suppressed (kill-switch override active): %s",
                    _detected_anomalies,
                )
            elif not getattr(cmd_cron, "_called_from_loop", False):
                # Interactive manual run — offer one-shot override inline.
                print(yellow(f"\n  ⚠  Anomaly halt: {', '.join(_detected_anomalies)}"))
                print(dim("  Anomaly check re-runs next cycle regardless."))
                try:
                    _anom_ans = (
                        input(yellow("  Override and run this cycle anyway? (y/N): "))
                        .strip()
                        .lower()
                    )
                except (EOFError, KeyboardInterrupt, OSError):
                    _anom_ans = ""
                if _anom_ans != "y":
                    _log.error(
                        "cmd_cron: anomaly halt triggered — stopping trade placement this cycle: %s",
                        _detected_anomalies,
                    )
                    return None
                _log.warning(
                    "cmd_cron: anomaly halt overridden by user for this cycle: %s",
                    _detected_anomalies,
                )
            else:
                _log.error(
                    "cmd_cron: anomaly halt triggered — stopping trade placement this cycle: %s",
                    _detected_anomalies,
                )
                return None
        elif _detected_anomalies:
            _log.warning(
                "cmd_cron: soft anomaly warnings (below halt threshold), continuing: %s",
                _detected_anomalies,
            )
    except Exception as _e:
        _log.debug("cmd_cron: run_anomaly_check failed: %s", _e)

    # Black swan emergency shutdown check.  Always runs — even during a user
    # override — so conditions that arise MID-RUN (after trades are placed) are
    # caught immediately rather than waiting for the next cycle.  If the check
    # fires during an override run it recreates .kill_switch; the finally block
    # in main.cmd_cron detects this and keeps the new file rather than restoring
    # the original, so the halt is still enforced after the one permitted cycle.
    try:
        from alerts import run_black_swan_check as _run_black_swan_check

        _bs_conditions = _run_black_swan_check(client=client)
        if _bs_conditions:
            _log.critical(
                "cmd_cron: BLACK SWAN conditions triggered — halting. Conditions: %s",
                _bs_conditions,
            )
            return None
    except Exception as _e:
        _log.debug("cmd_cron: run_black_swan_check failed: %s", _e)

    # Snapshot directional accuracy once for use by drift detection and pin logic below.
    # Directional accuracy measures whether the model's predicted direction is correct
    # on naturally-settled trades (excluding stop-loss exits). When it's high, Brier
    # degradation is being caused by stop losses rather than bad forecasting — tightening
    # edge thresholds in that scenario reduces opportunity without fixing the real problem.
    _directional_accuracy: float | None = None
    try:
        from paper import get_edge_realization_rate as _get_err

        _err = _get_err()
        _directional_accuracy = _err.get("multiday_directional_accuracy")
    except Exception as _e:
        _log.debug("cmd_cron: directional_accuracy fetch failed: %s", _e)

    # Drift detection; tighten STRONG_EDGE for this run when drifting.
    # Skip tightening when directional accuracy is high (≥ 0.70): in that case Brier
    # degradation is from stop-loss exits, not model errors, so raising the edge
    # threshold would reduce opportunity without improving forecast quality.
    _effective_strong_edge = STRONG_EDGE
    _drift_result: dict = {"drifting": False}
    try:
        from tracker import detect_brier_drift as _detect_brier_drift

        _drift_result = _detect_brier_drift()
        if _drift_result["drifting"]:
            if _directional_accuracy is not None and _directional_accuracy >= 0.70:
                _log.info(
                    "cmd_cron: Brier drift detected but directional_accuracy=%.2f — "
                    "drift is from stop-loss exits, not model errors; skipping edge tighten",
                    _directional_accuracy,
                )
            else:
                _effective_strong_edge = STRONG_EDGE + DRIFT_TIGHTEN_EDGE
                _log.warning(
                    "cmd_cron: %s — tightening STRONG_EDGE to %.2f for this run",
                    _drift_result["message"],
                    _effective_strong_edge,
                )
    except Exception as _e:
        _log.debug("cmd_cron: detect_brier_drift failed: %s", _e)

    # Strategy retirement check (log-only, non-blocking).
    # Pass current directional accuracy so methods are not retired when direction is
    # correct (>= 0.65) — elevated Brier in that case is a calibration issue, not a
    # forecasting failure, and is addressable without halting signal generation.
    try:
        from tracker import auto_retire_strategies as _auto_retire

        _newly_retired = _auto_retire(
            current_directional_accuracy=_directional_accuracy,
            dir_accuracy_guard=0.65,
        )
        if _newly_retired:
            _log.warning("cmd_cron: auto-retired strategy methods: %s", _newly_retired)
    except Exception as _e:
        _log.debug("cmd_cron: auto_retire_strategies failed: %s", _e)

    # Auto-extend ensemble pin when it is within 48 h of expiry and directional
    # accuracy is still healthy. The pin prevents auto-retirement of a method whose
    # Brier is high due to stop-loss exits rather than bad direction. Without this,
    # the pin requires manual renewal every 7 days to keep the bot trading.
    #
    # NOTE: this covers a DIFFERENT failure mode than auto_retire_strategies()'s
    # rolling-Brier guard — that guard only rescues a method whose Brier has
    # genuinely recovered recently (rolling <= threshold). It does nothing when
    # Brier stays chronically elevated because of stop-loss mechanics despite
    # correct direction, since rolling Brier stays bad too in that case. Keep
    # both mechanisms; they are not redundant.
    try:
        import json as _json_pin
        from datetime import timedelta as _td_pin
        from pathlib import Path as _Path_pin

        _pins_path = _Path_pin(__file__).parent / "data" / "strategy_pins.json"
        _pins: dict = {}
        if _pins_path.exists():
            try:
                _pins = _json_pin.loads(_pins_path.read_text())
            except Exception:
                pass
        _ensemble_expiry_str = _pins.get("ensemble")
        _should_renew = False
        if _ensemble_expiry_str:
            try:
                _expiry_dt = datetime.fromisoformat(_ensemble_expiry_str)
                _hours_left = (_expiry_dt - datetime.now(UTC)).total_seconds() / 3600
                if _hours_left < 48:
                    _should_renew = True
            except Exception:
                _should_renew = True  # malformed expiry — renew to be safe
        # Also renew if pin is missing entirely (ensemble unprotected)
        if not _ensemble_expiry_str:
            _should_renew = True
        if _should_renew:
            _da = _directional_accuracy if _directional_accuracy is not None else 0.0
            if _da >= 0.70:
                _pins["ensemble"] = (datetime.now(UTC) + _td_pin(hours=168)).isoformat()
                _pins_path.write_text(_json_pin.dumps(_pins, indent=2))
                _log.info(
                    "cmd_cron: auto-renewed ensemble pin for 168 h "
                    "(directional_accuracy=%.2f)",
                    _da,
                )
            else:
                _log.warning(
                    "cmd_cron: ensemble pin expiring but directional_accuracy=%.2f < 0.70 "
                    "— not auto-renewing; check model quality",
                    _da,
                )
    except Exception as _e:
        _log.debug("cmd_cron: ensemble pin auto-renew failed: %s", _e)

    # Config integrity check (log warning if changed)
    try:
        from utils import check_config_integrity as _check_config_integrity

        _cfg = _check_config_integrity()
        if _cfg["changed"]:
            _log.warning(
                "cmd_cron: config changed since last run — keys: %s",
                _cfg["changed_keys"],
            )
    except Exception as _e:
        _log.debug("cmd_cron: check_config_integrity failed: %s", _e)

    # Optional: start WebSocket for real-time price feeds.
    # Created here; subscribed and started after market list is fetched so the
    # subscribe() call (which must precede start()) has real tickers to use.
    _ws = None
    try:
        from kalshi_ws import KalshiWebSocket

        api_key = os.getenv("KALSHI_API_KEY", "")
        key_pem = os.getenv("KALSHI_PRIVATE_KEY_PEM", "")
        if api_key and key_pem:
            _ws = KalshiWebSocket(api_key, key_pem)
    except Exception as exc:
        _log.debug("WebSocket not available: %s", exc)

    # H-1: import inside try so a missing/broken kalshi_ws module doesn't crash
    # _cmd_cron_body before any market analysis runs.
    try:
        from kalshi_ws import get_ws_health as _get_ws_health

        _ws_h = _get_ws_health()
        if _ws_h["stale"]:
            _log.warning(
                "[cron] WebSocket cache is stale (idle %.0fs) — mid-prices may be unreliable",
                _ws_h["idle_secs"],
            )
    except Exception as _ws_health_err:
        _log.debug("WebSocket health check unavailable: %s", _ws_health_err)

    log_path = Path(__file__).parent / "data" / "cron.log"
    log_path.parent.mkdir(exist_ok=True)
    if log_path.exists() and log_path.stat().st_size > 5 * 1024 * 1024:
        try:
            log_path.replace(log_path.with_suffix(".log.1"))
        except OSError:
            pass

    # P0.5: Log state snapshot at the start of every cron run for consistency auditing.
    try:
        from paper import get_state_snapshot

        snap = get_state_snapshot()
        _log.info(
            "cmd_cron: state snapshot balance=%.2f open_trades=%d peak=%.2f",
            snap["balance"],
            snap["open_trades_count"],
            snap["peak_balance"],
        )
    except Exception as _e:
        _log.warning("cmd_cron: could not capture state snapshot: %s", _e)

    med_opps: list = []  # edge 15–24%, LOW or MEDIUM risk
    strong_opps: list = []  # edge 25%+, any time risk
    signals_cache: list = []
    scanned = 0
    _consistency_skip = False  # P3-14: init before try so it is always bound
    _dbg: dict = {
        "no_analysis": 0,
        "same_day": 0,  # informational only — same-day markets are no longer filtered
        "mkt_prob": 0,
        "divergence": 0,
        "net_edge": 0,
        "prob_edge": 0,
        "passed": 0,
    }
    # Hoist gate-count helpers so they are always bound even if the try block
    # exits early (exception path) and the finally block references them.
    from weather_markets import get_gate_counts as _get_gate_counts
    from weather_markets import reset_gate_counts as _reset_gate_counts

    try:
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import as_completed as _as_completed

        markets = ctx.get_weather_markets(client)
        scanned = len(markets)
        print(dim(f"  [cron] scanning {scanned} market(s)\u2026"), flush=True)

        # P3-14: consistency check \u2014 log violations; halt auto-trading if too many
        try:
            from consistency import find_violations as _find_violations

            _violations = _find_violations(markets)
            if _violations:
                _log.warning(
                    "cmd_cron: %d consistency violation(s) detected: %s",
                    len(_violations),
                    [v.description for v in _violations[:5]],
                )
                if len(_violations) > 5:
                    _consistency_skip = True
                    _log.error(
                        "cmd_cron: %d violations exceed threshold (5) \u2014 skipping auto-trading this cycle",
                        len(_violations),
                    )
        except Exception as _ce:
            # M-3: treat a broken consistency module as a safety failure — halt trading
            _log.warning(
                "cmd_cron: consistency check raised an exception — "
                "skipping auto-trading this cycle: %s",
                _ce,
            )
            _consistency_skip = True

        if _ws is not None:
            try:
                _ws_tickers = [m.get("ticker") for m in markets if m.get("ticker")]
                if _ws_tickers:
                    _ws.subscribe(_ws_tickers)
                _ws.start()
                _log.info(
                    "WebSocket thread started with %d ticker(s)", len(_ws_tickers)
                )
            except Exception as _ws_exc:
                _log.debug("WebSocket start failed: %s", _ws_exc)
                _ws = None

        # Pre-warm forecast/model caches for all unique city/date pairs so the
        # parallel scan hits cache instead of making redundant network requests.
        # Use parse_city_date (no network calls) to avoid tripping the forecast
        # circuit breaker before batch_prewarm_forecasts gets a chance to run.
        from weather_markets import parse_city_date as _parse_city_date

        _city_dates: set[tuple[str, str]] = set()
        for _m in markets:
            _city, _td = _parse_city_date(_m)
            if _city and _td:
                _city_dates.add((_city, str(_td)))
        if _city_dates:
            _n_pairs = len(_city_dates)
            print(
                dim(
                    f"  [cron] pre-warming forecasts for {_n_pairs} city/date pair(s)..."
                ),
                flush=True,
            )

            # Step 1a: batch Open-Meteo forecast (3 HTTP calls cover all cities)
            from weather_markets import (
                batch_prewarm_ensemble,
                batch_prewarm_forecasts,
                flush_ensemble_disk_cache,
            )

            _om_models = ["gfs_seamless", "ecmwf_ifs025", "icon_seamless"]
            _n_models = len(_om_models)

            def _om_progress(current: int, total: int, model: str, ok: bool) -> None:
                _tick = "OK" if ok else "FAIL"
                print(
                    dim(f"  [OM batch] [{current}/{total}] {model:<20} {_tick}"),
                    flush=True,
                )

            _batch_written = batch_prewarm_forecasts(
                _city_dates, progress_cb=_om_progress
            )
            print(
                dim(
                    f"  [OM batch] {_batch_written} cache entries written"
                    f" across {_n_models} models"
                ),
                flush=True,
            )

            # Step 1b: batch ensemble prewarm (6 calls: 3 models × 2 vars)
            # Replaces ~90 individual calls during analysis (was ~270 s at 1.5 s/call).
            _ens_models = [*_om_models]  # icon_seamless, ecmwf_ifs025, gfs_seamless
            _ens_vars = 2

            def _ens_progress(current: int, total: int, label: str, ok: bool) -> None:
                _tick = "OK" if ok else "FAIL"
                print(
                    dim(f"  [ENS batch] [{current}/{total}] {label:<26} {_tick}"),
                    flush=True,
                )

            _ens_written = batch_prewarm_ensemble(
                _city_dates, progress_cb=_ens_progress
            )
            print(
                dim(
                    f"  [ENS batch] {_ens_written} cache entries written"
                    f" across {len(_ens_models)} models × {_ens_vars} vars"
                ),
                flush=True,
            )
            # Flush to disk immediately so a canceled run still warms the next run.
            flush_ensemble_disk_cache()

            # Step 2: per-city sources that don't support batching.
            # Covers NBM, ECMWF, WeatherAPI, NWS daily forecast, METAR, and MOS
            # so that analyze_trade finds all caches warm and makes zero live
            # network calls per market during the analysis pool phase.
            def _warm_one(city_date: tuple[str, str]) -> None:
                _c, _d = city_date
                _dt = __import__("datetime").date.fromisoformat(_d)
                # ── Open-Meteo point models ──────────────────────────────────
                try:
                    ctx.fetch_temperature_nbm(_c, _dt)
                except Exception:
                    pass
                try:
                    ctx.fetch_temperature_ecmwf(_c, _dt)
                except Exception:
                    pass
                try:
                    ctx.fetch_temperature_weatherapi(_c, _dt)
                except Exception:
                    pass
                # ── NWS daily forecast (cached per city, covers all dates) ──
                try:
                    from nws import get_nws_daily_forecast as _nws_daily
                    from weather_markets import CITY_COORDS as _city_coords

                    _coords = _city_coords.get(_c)
                    if _coords:
                        _nws_daily(_c, _coords)
                except Exception:
                    pass
                # ── METAR current observation (cached per station, 5-min TTL) ─
                try:
                    from metar import fetch_metar as _fetch_metar
                    from weather_markets import (
                        _metar_station_for_city as _metar_sta,
                    )

                    _msta = _metar_sta(_c)
                    if _msta:
                        _fetch_metar(_msta)
                except Exception:
                    pass
                # ── MOS forecast (cached per station/date/model, 1-hour TTL) ──
                try:
                    import mos as _mos_mod

                    _mos_sta = _mos_mod.get_mos_station(_c)
                    if _mos_sta:
                        _mos_mod.fetch_mos_best(_mos_sta, target_date=_dt)
                except Exception:
                    pass
                # ── NWS hourly obs (600s TTL; used for same-day obs override and
                #    persistence baseline — not batched, must prewarm per city) ──
                try:
                    from nws import get_live_observation as _nws_obs
                    from weather_markets import CITY_COORDS as _city_coords2

                    _coords2 = _city_coords2.get(_c)
                    if _coords2:
                        _nws_obs(_c, _coords2)
                except Exception:
                    pass
                try:
                    from nws import get_live_precip_obs as _nws_precip_obs
                    from weather_markets import CITY_COORDS as _city_coords3

                    _coords3 = _city_coords3.get(_c)
                    if _coords3:
                        _nws_precip_obs(_c, _coords3)
                except Exception:
                    pass

            import threading as _threading

            _warm_done = 0
            _warm_lock = _threading.Lock()

            def _warm_one_tracked(city_date: tuple[str, str]) -> None:
                nonlocal _warm_done
                _warm_one(city_date)
                with _warm_lock:
                    _warm_done += 1
                    _cur = _warm_done
                    # print inside the lock so a slow thread can't print a stale
                    # counter after a faster thread already printed a higher one
                    print(
                        f"  [NBM/WA]  warming city sources... ({_cur}/{_n_pairs})",
                        end="\r",
                        flush=True,
                    )

            _warm_pool = ThreadPoolExecutor(max_workers=min(_n_pairs, 8))
            try:
                _warm_futures = [
                    _warm_pool.submit(_warm_one_tracked, _cd) for _cd in _city_dates
                ]
                try:
                    for _wf in _as_completed(_warm_futures, timeout=200):
                        try:
                            _wf.result()
                        except Exception as _prewarm_exc:
                            # M-4: log at DEBUG so transient per-city failures are traceable
                            _log.debug(
                                "cmd_cron: prewarm failed for a city: %s", _prewarm_exc
                            )
                except TimeoutError:
                    _log.warning(
                        "cmd_cron: city source warm-up timed out after 200s — "
                        "%d/%d pairs completed; analysis will skip MOS for uncached markets",
                        _warm_done,
                        _n_pairs,
                    )
            finally:
                _warm_pool.shutdown(wait=False)
            print(flush=True)  # newline after in-place counter

        # Suppress probing on any circuit that opened during prewarm.
        # Analysis should use fallback sources immediately, not stall every
        # recovery_timeout seconds waiting on a probe that may also fail.
        from weather_markets import _ensemble_cb, _forecast_cb, _nbm_om_cb

        for _cb in (_nbm_om_cb, _ensemble_cb, _forecast_cb):
            if _cb.seconds_open() > 0:
                _cb.suppress_probe()
                _log.warning(
                    "cron: circuit '%s' open after prewarm — probing suppressed for this run",
                    _cb.name,
                )

        def _enrich_and_analyze(m: dict) -> tuple[dict, dict, dict | None]:
            enriched = ctx.enrich_with_forecast(m)
            return m, enriched, ctx.analyze_trade(enriched)

        _analysis_batch: list[dict] = []  # #perf: collect for single bulk insert
        # Dedup by ticker before analysis — same market can appear twice when the
        # Kalshi API returns it under both the old series format (KXHIGH-NYC-…)
        # and the new format (KXHIGHNY-…) in the same batch.
        _seen_analysis_tickers: set[str] = set()
        _deduped_markets: list[dict] = []
        for _dm in markets:
            _dm_ticker = _dm.get("ticker", "")
            if _dm_ticker not in _seen_analysis_tickers:
                _seen_analysis_tickers.add(_dm_ticker)
                _deduped_markets.append(_dm)
        if len(_deduped_markets) < len(markets):
            _log.debug(
                "cmd_cron: deduped %d duplicate ticker(s) before analysis",
                len(markets) - len(_deduped_markets),
            )
        scanned = len(_deduped_markets)  # L-2: report post-dedup count in summary

        _reset_gate_counts()

        # Per-market analysis timeout: 6 min total for all markets.
        # All network sources (NWS, METAR, MOS, NBM) are prewarmed before this
        # pool starts, so each market should hit only in-memory caches.
        # Workers reduced to 8 (was 12): fewer concurrent SSL connections lowers
        # the chance of Windows SSL hangs; cache-warm analysis is CPU-bound so
        # 8 workers saturate the pipeline without racing on network resources.
        # Manual pool (no `with`) so shutdown(wait=False) can be used in finally
        # — `with ThreadPoolExecutor` calls shutdown(wait=True) on __exit__,
        # which blocks forever on a hung Windows SSL socket.
        # Watchdog hard-kills at 720s as backstop.
        _ANALYSIS_TIMEOUT_S = 360
        _pool = ThreadPoolExecutor(max_workers=8)
        try:
            _futures = {
                _pool.submit(_enrich_and_analyze, m): m for m in _deduped_markets
            }
            _timed_out = False
            try:
                for fut in _as_completed(_futures, timeout=_ANALYSIS_TIMEOUT_S):
                    if KILL_SWITCH_PATH.exists():
                        _log.warning(
                            "cmd_cron: kill switch activated mid-scan — stopping analysis"
                        )
                        break
                    try:
                        m, enriched, analysis = fut.result()
                    except Exception as exc:
                        # CR-2: log at WARNING so a completely broken model is visible
                        # (previously silent — all markets could fail with zero log output)
                        # Use _futures[fut] to recover the market dict — `m` is unbound
                        # on the first failing future because dict-comprehension loop vars
                        # don't leak into the enclosing scope in Python 3.
                        _failed_mkt = _futures.get(fut, {})
                        _log.warning(
                            "cmd_cron: analysis failed for %s: %s — skipping ticker",
                            _failed_mkt.get("ticker", "?")
                            if isinstance(_failed_mkt, dict)
                            else "?",
                            exc,
                        )
                        _dbg["analysis_errors"] = _dbg.get("analysis_errors", 0) + 1
                        continue
                    if not analysis:
                        _dbg["no_analysis"] += 1
                        continue
                    net_edge = analysis.get(
                        "net_edge", analysis.get("edge", 0.0)
                    )  # H-2: avoid KeyError
                    adjusted_edge = analysis.get("adjusted_edge", net_edge)
                    # Collect analysis attempt for bulk DB insert after loop.
                    try:
                        import datetime as _dt

                        _td = analysis.get("target_date") or enriched.get(
                            "_target_date"
                        )
                        if isinstance(_td, str):
                            try:
                                _td = _dt.date.fromisoformat(_td)
                            except ValueError:
                                _td = None
                        _analysis_batch.append(
                            {
                                "ticker": m.get("ticker", ""),
                                "city": enriched.get("_city"),
                                "condition": str(analysis.get("condition", "")),
                                "target_date": _td,
                                "forecast_prob": analysis.get("forecast_prob", 0.0),
                                "market_prob": analysis.get("market_prob", 0.0),
                                "days_out": int(analysis.get("days_out", 0)),
                                "was_traded": False,
                            }
                        )
                    except Exception:
                        pass
                    # Same-day markets (days_out == 0) are re-enabled. analyze_trade
                    # uses METAR-locked probabilities for same-day above/below markets,
                    # which gives tight CI width → larger ci_adjusted_kelly → the only
                    # realistic path to qty >= 1 while in TIER_3 drawdown. Between
                    # markets at days_out == 0 skip the obs override in analyze_trade
                    # (line 4917) so they fall back to ensemble and are covered by the
                    # between_floor gate. The same divergence, gap, liquidity, and
                    # min_prob_edge gates still apply to all same-day candidates.
                    if int(analysis.get("days_out", 1)) == 0:
                        _dbg["same_day"] += 1
                        # fall through — do not skip
                    # Market divergence cap: skip when we disagree with the market by
                    # more than 2.5× — the market is right nearly every time in that case.
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
                        _dbg["mkt_prob"] += 1
                        continue
                    if (
                        _mkt_dir > 0
                        and _our_dir / _mkt_dir > MAX_MARKET_DIVERGENCE_RATIO
                    ):
                        _dbg["divergence"] += 1
                        continue
                    # Track whether this candidate clears both edge gates.
                    # Below-threshold candidates are still written to signals_cache
                    # so the dashboard can show them; only candidates that pass are
                    # eligible for auto-trading (strong_opps / med_opps / log entry).
                    _passes_threshold = True
                    if abs(adjusted_edge) < PAPER_MIN_EDGE:
                        _dbg["net_edge"] += 1
                        _passes_threshold = False

                    # Probability-edge gate: require minimum conviction based on
                    # market horizon (further out = more time for repricing + more
                    # ensemble uncertainty) and per-city Brier overrides.
                    _prob_edge = abs(
                        analysis.get("forecast_prob", 0.5)
                        - analysis.get("market_prob", 0.5)
                    )
                    _city_key = enriched.get("_city", "")
                    _days_out_val = int(analysis.get("days_out", 1))
                    _city_min = CITY_MIN_PROB_EDGE.get(_city_key, MIN_PROB_EDGE)
                    _days_min = min_prob_edge_for_days_out(_days_out_val)
                    _min_edge = max(_city_min, _days_min)
                    if _passes_threshold and _prob_edge < _min_edge:
                        _dbg["prob_edge"] += 1
                        _passes_threshold = False

                    if _passes_threshold:
                        _dbg["passed"] += 1
                    signal = analysis.get(
                        "net_signal", analysis.get("signal", "")
                    ).strip()
                    time_risk = analysis.get("time_risk", "\u2014")
                    stars = (
                        "\u2605\u2605\u2605"
                        if _passes_threshold
                        and "STRONG" in signal
                        and time_risk == "LOW"
                        else "\u2605\u2605"
                        if _passes_threshold and "STRONG" in signal
                        else "\u2605"
                        if _passes_threshold
                        else ""
                    )
                    # Only write a log entry for candidates that cleared the gates.
                    if _passes_threshold:
                        entry = {
                            "ts": datetime.now(UTC).isoformat(),
                            "ticker": m.get("ticker", ""),
                            "signal": signal,
                            "net_edge": round(net_edge, 4),
                            "city": enriched.get("_city", ""),
                        }
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write(json.dumps(entry) + "\n")
                    _tdate = enriched.get("_date")
                    from weather_markets import parse_market_price as _pmp

                    _prices = _pmp(m)
                    signals_cache.append(
                        {
                            "ticker": m.get("ticker", ""),
                            "city": enriched.get("_city", "\u2014"),
                            "target_date": (
                                _tdate
                                if isinstance(_tdate, str)
                                else (_tdate.isoformat() if _tdate else None)
                            ),
                            "side": analysis.get("recommended_side", "\u2014").upper(),
                            "signal": signal,
                            "stars": stars,
                            "edge_pct": round(net_edge * 100, 1),
                            "net_edge": round(net_edge, 6),
                            "yes_bid": _prices["yes_bid"],
                            "yes_ask": _prices["yes_ask"],
                            "forecast_prob": round(
                                analysis.get("forecast_prob", 0) * 100, 1
                            ),
                            "market_prob": round(
                                analysis.get("market_prob", 0) * 100, 1
                            ),
                            "time_risk": time_risk,
                            "model_consensus": analysis.get("model_consensus", True),
                            "kelly_dollars": 0.0,  # balance unknown at cron time; filled by web
                            "already_held": False,
                            "near_threshold": analysis.get("near_threshold", False),
                            "is_hedge": analysis.get("_is_hedge", False),
                            "passes_threshold": _passes_threshold,
                            "days_out": int(analysis.get("days_out", 1)),
                            "model_disagreement_f": analysis.get(
                                "model_disagreement_f"
                            ),
                            "model_disagreement_flag": analysis.get(
                                "model_disagreement_flag", False
                            ),
                            # Per-source probabilities for dashboard attribution display
                            "ensemble_prob": round(
                                analysis.get("ensemble_prob", 0) * 100, 1
                            )
                            if analysis.get("ensemble_prob") is not None
                            else None,
                            "nws_prob": round(analysis.get("nws_prob", 0) * 100, 1)
                            if analysis.get("nws_prob") is not None
                            else None,
                            "clim_prob": round(analysis.get("clim_prob", 0) * 100, 1)
                            if analysis.get("clim_prob") is not None
                            else None,
                            "forecast_temp_f": analysis.get("forecast_temp"),
                        }
                    )
                    # Only consider for auto-trading if edge gates passed.
                    if _passes_threshold:
                        if abs(adjusted_edge) >= _effective_strong_edge:
                            strong_opps.append((enriched, analysis))
                        elif abs(adjusted_edge) >= MED_EDGE:
                            med_opps.append((enriched, analysis))
            except TimeoutError:
                _log.error(
                    "cmd_cron: analysis scan timed out after %ds — %d markets processed",
                    _ANALYSIS_TIMEOUT_S,
                    _dbg["passed"]
                    + _dbg["no_analysis"]
                    + _dbg["mkt_prob"]
                    + _dbg["divergence"]
                    + _dbg["net_edge"]
                    + _dbg["prob_edge"],
                    # same_day excluded: it is informational and would double-count
                    # markets that also appear in passed/net_edge/prob_edge
                )
        finally:
            _pool.shutdown(wait=False)  # never block on a stuck SSL thread
    except TimeoutError:
        _log.error(
            "cmd_cron: analysis scan timed out after %ds — %d markets processed so far",
            _ANALYSIS_TIMEOUT_S,
            _dbg["passed"]
            + _dbg["no_analysis"]
            + _dbg["mkt_prob"]
            + _dbg["divergence"]
            + _dbg["net_edge"]
            + _dbg["prob_edge"],
            # same_day excluded: informational only, would double-count
        )
    except Exception as _e:
        import logging as _logging

        _logging.getLogger(__name__).error(
            "cmd_cron: scan loop crashed: %s", _e, exc_info=True
        )

    # #perf: flush analysis attempts in one batch transaction (vs one INSERT per market)
    try:
        from tracker import batch_log_analysis_attempts as _batch_log

        _batch_log(_analysis_batch)
    except Exception:
        pass

    # Write rich signals cache for the web dashboard
    try:
        cache_path = Path(__file__).parent / "data" / "signals_cache.json"
        above_threshold = [s for s in signals_cache if s.get("passes_threshold", True)]
        strong = [s for s in above_threshold if "STRONG" in s["signal"]]
        low_risk = [s for s in strong if s["time_risk"] == "LOW"]
        # Sort: above-threshold candidates first (by edge), then below-threshold (by edge).
        signals_cache.sort(
            key=lambda x: (not x.get("passes_threshold", True), -abs(x["edge_pct"]))
        )
        # Capture gate-level rejection counts so the dashboard can show a
        # filter-breakdown chart without needing any in-memory state from cron.
        try:
            _filter_gate_counts = _get_gate_counts()
        except Exception:
            _filter_gate_counts = {}
        cache_payload = {
            "signals": signals_cache[:200],
            "summary": {
                "scanned": scanned,
                "with_edge": len(
                    above_threshold
                ),  # only counts candidates that cleared edge gates
                "strong": len(strong),
                "low_risk": len(low_risk),
            },
            "filter_stats": {
                "filters": dict(_dbg),
                "gate_counts": _filter_gate_counts,
                "total_scanned": scanned,
            },
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        }
        from safe_io import atomic_write_json as _atomic_write

        _atomic_write(cache_payload, cache_path)
    except Exception:
        pass

    # Check for market anomalies — price drifted >12pp against our model
    _anomaly_signals = [
        {
            "ticker": s["ticker"],
            "blended_prob": s["forecast_prob"] / 100.0,
            "market_price": s["market_prob"] / 100.0,
        }
        for s in signals_cache
    ]
    _anomalies = check_market_anomalies(_anomaly_signals)
    report_anomalies(_anomalies)

    # Act on any active settlement lag signals from the settlement monitor (R20).
    # High-confidence signals (\u226580%) trigger early close of the matched paper trade.
    try:
        from settlement_monitor import read_settlement_signals

        _settlement_sigs = read_settlement_signals()
        if _settlement_sigs:
            _log.info("Settlement lag signals: %d active", len(_settlement_sigs))
            from paper import close_paper_early as _close_early
            from paper import get_open_trades as _get_open_trades

            _open_by_ticker = {t["ticker"]: t for t in _get_open_trades()}
            for sig in _settlement_sigs:
                _sig_ticker = sig["ticker"]
                _sig_outcome = sig.get("outcome", "")
                _sig_conf = sig.get("confidence", 0.0)
                _log.info(
                    "  \u2192 %s %s (conf=%.0f%%, %.1f\u00b0F vs %.1f\u00b0F threshold)",
                    _sig_ticker,
                    _sig_outcome,
                    _sig_conf * 100,
                    sig.get("current_temp_f", 0),
                    sig.get("threshold_f", 0),
                )
                if _sig_conf >= 0.80 and _sig_ticker in _open_by_ticker:
                    _trade = _open_by_ticker[_sig_ticker]
                    # Exit price: 1.0 if signal matches our side, 0.0 if against.
                    _side = _trade.get("side", "yes")
                    if (_side == "yes" and _sig_outcome == "yes") or (
                        _side == "no" and _sig_outcome == "no"
                    ):
                        _exit_price = 0.97  # winning side: near full payout
                    else:
                        _exit_price = 0.03  # losing side: near zero
                    try:
                        _close_early(_trade["id"], _exit_price)
                        _log.info(
                            "Settlement signal: closed %s early at %.2f (conf=%.0f%%, outcome=%s)",
                            _sig_ticker,
                            _exit_price,
                            _sig_conf * 100,
                            _sig_outcome,
                        )
                    except Exception as _ce:
                        _log.warning(
                            "Settlement signal: failed to close %s: %s",
                            _sig_ticker,
                            _ce,
                        )
    except Exception as _e:
        _log.debug("cmd_cron: read_settlement_signals failed: %s", _e)

    # \u2500\u2500 Scan summary line \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    _n_strong = len(strong_opps)
    _n_med = len(med_opps)
    _n_with_edge = _n_strong + _n_med
    _gate_detail = _get_gate_counts()
    _gate_str = (
        " ".join(f"{k}:{v}" for k, v in sorted(_gate_detail.items()))
        if _gate_detail
        else "none"
    )
    print(
        dim(
            f"  [cron] filter breakdown \u2014 no_analysis:{_dbg['no_analysis']} "
            f"same_day_seen:{_dbg['same_day']} mkt_prob:{_dbg['mkt_prob']} "
            f"divergence:{_dbg['divergence']} net_edge:{_dbg['net_edge']} "
            f"prob_edge:{_dbg['prob_edge']} passed:{_dbg['passed']}"
        ),
        flush=True,
    )
    print(dim(f"  [cron] analyze_trade gates \u2014 {_gate_str}"), flush=True)
    if _n_with_edge == 0:
        print(
            dim(
                f"  [cron] Scanned {scanned} market(s) \u2014 no actionable signals found."
            )
        )
    else:
        print(
            dim(
                f"  [cron] Scanned {scanned} market(s) \u2014 "
                f"{_n_with_edge} with edge (strong={_n_strong}, med={_n_med})"
            )
        )

    _trading_paused = is_trading_paused()

    placed_count = 0
    if _trading_paused:
        _log.warning(
            "cmd_cron: TRADING_PAUSED is set — scan/data collection ran, trade placement skipped"
        )
        _n_shadow = ctx.log_shadow_predictions(strong_opps + med_opps)
        if _n_shadow:
            print(
                dim(
                    f"  [cron] Logged {_n_shadow} shadow prediction(s) while paused "
                    "(scoring stays current; no trades placed)."
                )
            )
    elif _consistency_skip:
        _log.warning(
            "cmd_cron: auto-trading skipped this cycle due to consistency violations"
        )
    else:

        def _kelly_sort_key(opp: tuple) -> float:
            a = opp[1]
            return abs(
                a.get(
                    "ci_adjusted_kelly", a.get("kelly_fraction", a.get("net_edge", 0))
                )
                or 0
            )

        strong_opps.sort(key=_kelly_sort_key, reverse=True)
        med_opps.sort(key=_kelly_sort_key, reverse=True)

        # Final kill switch check — a mid-scan activation breaks the analysis loop
        # but without this check placement would still proceed for already-found signals.
        if KILL_SWITCH_PATH.exists():
            _log.warning(
                "cmd_cron: kill switch activated before placement — skipping %d signal(s)",
                len(strong_opps) + len(med_opps),
            )
            return None

        if strong_opps:
            from paper import _dynamic_kelly_cap

            strong_cap = _dynamic_kelly_cap()
            print(
                bold(
                    f"\n  !! {len(strong_opps)} STRONG SIGNAL(S) \u2014 placing paper trades (cap=${strong_cap:.0f}) !!"
                )
            )
            placed_count += (
                ctx.auto_place_trades(strong_opps, client=client, cap=strong_cap) or 0
            )
        if med_opps:
            print(
                bold(
                    f"\n  !! {len(med_opps)} MED SIGNAL(S) \u2014 placing paper trades (cap=$20) !!"
                )
            )
            placed_count += (
                ctx.auto_place_trades(med_opps, client=client, cap=20.0) or 0
            )

    # Auto-settle any pending trades whose markets have resolved
    settled_count = 0
    try:
        settled_count = ctx.sync_outcomes(client)
        if settled_count > 0:
            print(green(f"  [Settle] Recorded {settled_count} new outcome(s)."))
    except Exception as _sync_exc:
        _log.warning("cmd_cron: sync_outcomes failed: %s", _sync_exc)

    # Settle resolved paper trades (marks paper.json won/lost to match tracker outcomes)
    paper_settled_count = 0
    try:
        from paper import auto_settle_paper_trades

        _settled_trades = auto_settle_paper_trades(client)
        paper_settled_count = len(_settled_trades)
        if paper_settled_count > 0:
            _net_pnl = sum(t.get("pnl") or 0.0 for t in _settled_trades)
            for _st in _settled_trades:
                _ticker = _st.get("ticker", "?")
                _side = (_st.get("side") or "?").upper()
                _pnl = _st.get("pnl") or 0.0
                _result = green("WON ") if _pnl > 0 else red("LOST")
                _pnl_str = f"+${_pnl:.2f}" if _pnl >= 0 else f"-${abs(_pnl):.2f}"
                print(f"  [PaperSettle] {_ticker}  {_side}-side  {_result}  {_pnl_str}")
            _net_str = (
                f"+${_net_pnl:.2f}" if _net_pnl >= 0 else f"-${abs(_net_pnl):.2f}"
            )
            print(
                green(
                    f"  [PaperSettle] {paper_settled_count} trade(s) settled — net P&L: {_net_str}"
                )
            )
    except Exception as _e:
        _log.warning("cmd_cron: auto_settle_paper_trades failed: %s", _e)

    # F3: Auto-trigger calibration every 25 new settled trades, but only after
    # reaching 50 total. With fewer samples the grid search overfits to noise —
    # the minimum meaningful calibration sample is 50 predictions.
    try:
        import os as _os_cal

        if not _os_cal.environ.get("PYTEST_CURRENT_TEST"):
            _cal_sentinel = Path(__file__).parent / "data" / ".last_calibration_count"
            import tracker as _tracker_cal

            _current_settled = _tracker_cal.count_settled_predictions()
            _last_cal_count = 0
            if _cal_sentinel.exists():
                try:
                    _last_cal_count = int(_cal_sentinel.read_text().strip())
                except Exception:
                    pass
            if _current_settled >= 50 and _current_settled - _last_cal_count >= 25:
                _log.info(
                    "cmd_cron: F3 auto-calibration triggered "
                    "(%d settled since last run, threshold=25)",
                    _current_settled - _last_cal_count,
                )
                from calibration import calibrate_and_save as _cal_and_save

                _data_dir = Path(__file__).parent / "data"
                try:
                    import weather_markets as _wm_cal

                    _seasonal_w, _city_w, _condition_w = _cal_and_save(
                        data_dir=_data_dir
                    )

                    # Invalidate in-memory cache so the new weights take effect
                    # immediately in this cron run rather than waiting for next restart.
                    _wm_cal._CONDITION_WEIGHTS.clear()
                    _wm_cal._CONDITION_WEIGHTS.update(_condition_w)
                    _wm_cal._SEASONAL_WEIGHTS.clear()
                    _wm_cal._SEASONAL_WEIGHTS.update(_seasonal_w)
                    _wm_cal._CITY_WEIGHTS.clear()
                    _wm_cal._CITY_WEIGHTS.update(_city_w)

                    _cal_sentinel.write_text(str(_current_settled))
                    _log.info(
                        "cmd_cron: F3 calibration complete — "
                        "seasonal(%d) city(%d) condition(%d) weights written",
                        len(_seasonal_w),
                        len(_city_w),
                        len(_condition_w),
                    )
                    print(
                        dim("  [AutoCal] Calibration complete — blend weights updated.")
                    )
                except Exception as _cal_err:
                    _log.warning("cmd_cron: F3 calibration failed: %s", _cal_err)
    except Exception as _e:
        _log.debug("cmd_cron: F3 auto-calibration check failed: %s", _e)

    # Phase 7 — price-based stop-loss check before model-based early exits
    try:
        import paper as _paper_sl

        _open_for_sl = _paper_sl.get_open_trades()
        if _open_for_sl and client is not None:
            _yes_prices: dict[str, float] = {}
            from weather_markets import parse_market_price as _parse_sl_price

            for _t in _open_for_sl:
                try:
                    _mkt = client.get_market(_t["ticker"])
                    # Use parse_market_price so both cents and decimal API formats
                    # are handled correctly.  A raw "/ 100" would mis-price
                    # markets already returned in decimal (0-1) format, making
                    # every position look like a 99% instant loss and firing the
                    # stop on the same cron run the trade was placed.
                    # M-2: use .get() so a missing yes_ask key doesn't raise KeyError
                    _ask = _parse_sl_price(_mkt).get("yes_ask")
                    if _ask is not None:
                        _yes_prices[_t["ticker"]] = _ask
                    else:
                        _log.debug(
                            "[StopLoss] no yes_ask for %s — will fall back to entry_price",
                            _t["ticker"],
                        )
                except Exception:
                    pass
            # Update peak profit highs before any stop checks
            _paper_sl.update_peak_profits(_open_for_sl, _yes_prices)

            _sl_tickers = _paper_sl.check_stop_losses(_open_for_sl, _yes_prices)
            for _sl_ticker in _sl_tickers:
                _sl_trade = next(
                    (t for t in _open_for_sl if t["ticker"] == _sl_ticker), None
                )
                if _sl_trade:
                    _sl_exit_price = _yes_prices.get(
                        _sl_ticker, _sl_trade["entry_price"]
                    )
                    if _sl_trade.get("side") == "no":
                        _sl_exit_price = 1.0 - _sl_exit_price
                    _paper_sl.close_paper_early(_sl_trade["id"], _sl_exit_price)
                    _log.info(
                        "[StopLoss] Closed %s \u2014 price breached stop threshold",
                        _sl_ticker,
                    )
                    print(
                        red(
                            f"  [StopLoss] Closed {_sl_ticker} \u2014 price breached stop threshold"
                        )
                    )

            # Break-even stop: if position was ever up >=30% of cost and has
            # since fallen back to entry, exit at scratch (no loss possible)
            _open_for_sl = _paper_sl.get_open_trades()  # reload after any stop exits
            _be_tickers = _paper_sl.check_breakeven_stops(_open_for_sl, _yes_prices)
            for _be_ticker in _be_tickers:
                _be_trade = next(
                    (t for t in _open_for_sl if t["ticker"] == _be_ticker), None
                )
                if _be_trade:
                    _be_exit_price = _yes_prices.get(
                        _be_ticker, _be_trade["entry_price"]
                    )
                    if _be_trade.get("side") == "no":
                        _be_exit_price = 1.0 - _be_exit_price
                    _paper_sl.close_paper_early(_be_trade["id"], _be_exit_price)
                    _log.info(
                        "[BreakEven] Closed %s \u2014 fell back to entry after peaking %.0f%% profit",
                        _be_ticker,
                        (_be_trade.get("peak_profit_pct") or 0) * 100,
                    )
                    print(
                        yellow(
                            f"  [BreakEven] Closed {_be_ticker} \u2014 scratch exit (peaked then fell to entry)"
                        )
                    )
    except Exception as _e:
        # M-1: stop-loss failures must be ERROR-level — DEBUG is invisible in production
        _log.error(
            "[StopLoss] check_stop_losses failed — stop-loss protection inactive this cycle: %s",
            _e,
        )

    # Weekly Brier alert: notify if score > threshold two weeks running
    try:
        import os as _os_brier

        if not _os_brier.environ.get("PYTEST_CURRENT_TEST"):
            from tracker import get_brier_over_time as _get_brier_weeks
            from utils import BRIER_ALERT_THRESHOLD as _BRIER_THRESH

            _brier_weeks = _get_brier_weeks(weeks=3)
            if len(_brier_weeks) >= 2:
                _recent_two = [w["brier"] for w in _brier_weeks[-2:]]
                if all(b > _BRIER_THRESH for b in _recent_two):
                    from tracker import format_brier_alert as _fmt_brier

                    _brier_msg = (
                        f"Brier score has exceeded {_BRIER_THRESH} for two consecutive weeks "
                        f"({_recent_two[0]:.4f}, {_recent_two[1]:.4f}). "
                        "Review model quality before continuing live trades."
                    )
                    _log.warning("P10.3 Brier alert: %s", _brier_msg)
                    print(red(_fmt_brier(scores=_recent_two)))
                    try:
                        from notify import _send_discord as _brier_discord

                        _brier_discord(
                            "\u26a0\ufe0f Brier Score Alert",
                            _brier_msg,
                            color=0xE3B341,
                        )
                    except Exception:
                        pass
    except Exception as _e:
        _log.debug("cmd_cron: brier alert check failed: %s", _e)

    # Slippage alert: warn if mean fill slippage exceeds threshold
    try:
        import os as _os_slip

        if not _os_slip.environ.get("PYTEST_CURRENT_TEST"):
            from tracker import get_mean_slippage as _get_slip
            from utils import SLIPPAGE_ALERT_CENTS as _SLIP_THRESH

            _mean_slip = _get_slip(days=30)
            if _mean_slip is not None and abs(_mean_slip) > _SLIP_THRESH:
                _slip_msg = (
                    f"Mean live fill slippage over 30 days is {_mean_slip:+.2f}\u00a2 "
                    f"(threshold \u00b1{_SLIP_THRESH}\u00a2). Consider adjusting slippage model."
                )
                _log.warning("P10.4 slippage alert: %s", _slip_msg)
                print(yellow(f"  [SlippageAlert] {_slip_msg}"))
    except Exception as _e:
        _log.debug("cmd_cron: slippage alert check failed: %s", _e)

    # Check open positions for early exit opportunities
    try:
        exits = ctx.check_early_exits(client=client)
        if exits > 0:
            print(green(f"  [EarlyExit] Closed {exits} position(s) on model update."))
    except Exception as _e:
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "cmd_cron: _check_early_exits failed: %s", _e
        )

    # Portfolio VaR summary after placement
    try:
        from monte_carlo import portfolio_var
        from paper import get_open_trades as _get_open

        _open = _get_open()
        if _open:
            _var = portfolio_var(_open, n_simulations=500)
            _exp = None
            try:
                from monte_carlo import simulate_portfolio as _sim

                _exp = _sim(_open, n_simulations=500)["median_pnl"]
            except Exception:
                pass
            _var_s = red(f"-${abs(_var):.2f}") if _var < 0 else green(f"+${_var:.2f}")
            _exp_s = (
                (green(f"+${_exp:.2f}") if _exp >= 0 else red(f"-${abs(_exp):.2f}"))
                if _exp is not None
                else "n/a"
            )
            print(dim(f"  [cron] Portfolio VaR (5%): {_var_s}  |  Expected: {_exp_s}"))
    except Exception:
        pass

    # Calibration readiness reminder — fire once when approaching the 50-trade gate
    # so it doesn't get missed the way the 25-trade auto-calibration did.
    try:
        import os as _os_cal_remind

        if not _os_cal_remind.environ.get("PYTEST_CURRENT_TEST"):
            import tracker as _tk_remind

            _cal_remind_count = _tk_remind.count_settled_predictions()
            if 45 <= _cal_remind_count < 50:
                print(
                    yellow(
                        f"  [CalRemind] {_cal_remind_count}/50 settled predictions — "
                        "run `py main.py calibrate` when you reach 50 to update blend weights."
                    )
                )
    except Exception as _e:
        _log.debug("cmd_cron: calibration reminder failed: %s", _e)

    # Phase 9 — alert if any circuit transitioned closed→open during this scan
    try:
        import os as _os_cb

        if (
            not _os_cb.environ.get("PYTEST_CURRENT_TEST")
            and _pre_scan_cb_states
            and _scan_cbs
        ):
            from notify import _send_discord as _discord_cb

            for _cb_name, _cb_obj in _scan_cbs.items():
                if not _pre_scan_cb_states.get(_cb_name, True) and _cb_obj.is_open():
                    _log.warning(
                        "Circuit '%s' OPENED during cron scan \u2014 notifying",
                        _cb_name,
                    )
                    _discord_cb(
                        f"\u26a1 Circuit Opened: {_cb_name}",
                        f"The `{_cb_name}` data source tripped during cron scan.\n"
                        f"Failures: {_cb_obj.failure_count}  |  "
                        f"Retry in: {round(_cb_obj.seconds_until_retry())}s",
                        color=0xF85149,
                    )
    except Exception as _e:
        _log.debug("cmd_cron: circuit-open alert failed: %s", _e)

    # Windows toast notification (suppressed during test runs)
    try:
        import os as _os
        import subprocess as _sp

        if _os.environ.get("PYTEST_CURRENT_TEST"):
            raise StopIteration  # skip toast in tests

        signals = len(strong_opps) + len(med_opps)
        parts = []
        if signals > 0:
            parts.append(
                f"{placed_count} placed"
                if placed_count == signals
                else f"{signals} signal(s), {placed_count} placed"
            )
        if settled_count > 0:
            parts.append(f"{settled_count} settled")
        msg = ", ".join(parts) if parts else "No signals today"

        # Graduation alert — fires once when all criteria are first met
        _grad_flag = Path(__file__).parent / "data" / "graduated.flag"
        try:
            from paper import graduation_check as _grad_check

            if _grad_check() is not None and not _grad_flag.exists():
                _grad_flag.touch()
                msg = "READY TO GO LIVE \u2014 30 trades, +$50 P&L, Brier \u2264 0.23 met!"
        except Exception:
            pass
        _sp.run(
            [
                "powershell",
                "-WindowStyle",
                "Hidden",
                "-Command",
                f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null;"
                f"$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                f"$template.SelectSingleNode('//text[@id=1]').InnerText = 'Kalshi Bot';"
                f"$template.SelectSingleNode('//text[@id=2]').InnerText = '{msg}';"
                f"$notif = [Windows.UI.Notifications.ToastNotification]::new($template);"
                f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Kalshi Bot').Show($notif);",
            ],
            timeout=10,
            capture_output=True,
        )
    except Exception:
        pass

    # D5: Weekly — retrain ML bias model as new settled trades accumulate.
    # Uses a marker file instead of exact-hour matching so scheduled runs never miss.
    _LAST_ML_RETRAIN_PATH = Path(__file__).parent / "data" / ".last_ml_retrain"
    _should_retrain = False  # declared before try so finally can read it
    try:
        import os as _os_tb

        if not _os_tb.environ.get("PYTEST_CURRENT_TEST"):
            _should_retrain = True
            if _LAST_ML_RETRAIN_PATH.exists():
                _days_since = (
                    datetime.now(UTC).timestamp()
                    - _LAST_ML_RETRAIN_PATH.stat().st_mtime
                ) / 86400
                _should_retrain = _days_since >= 6
            if _should_retrain:
                _log.info(
                    "cmd_cron: running weekly ML bias model retrain (>=6 days since last)"
                )
                from ml_bias import train_all_temperature_scaling as _train_all_ts
                from ml_bias import train_bias_model as _train_bias

                _trained = _train_bias()
                if _trained:
                    print(
                        dim(
                            f"  [MLBias] Retrained {len(_trained)} city model(s): {', '.join(_trained.keys())}"
                        )
                    )
                # Use train_all_temperature_scaling so per-condition T values (between,
                # above, below) are preserved — the old single-T function overwrites the
                # combined JSON format and loses the per-condition entries each cron run.
                _ts_result = _train_all_ts()
                if _ts_result:
                    _parts = [f"{k}={v:.4f}" for k, v in sorted(_ts_result.items())]
                    print(dim(f"  [TempScale] fitted — {', '.join(_parts)}"))

                # F3: auto-calibrate blend weights alongside bias/T-scaling so seasonal
                # and condition weights reflect the most recent settlement data.
                from calibration import calibrate_and_save as _calibrate_blend

                _seas_w, _city_w, _cond_w = _calibrate_blend()

                # Push new weights into the running module so this loop cycle
                # uses them immediately — otherwise they sit on disk until restart.
                import weather_markets as _wm

                _wm._SEASONAL_WEIGHTS = _seas_w
                _wm._CONDITION_WEIGHTS = _cond_w
                _wm._CITY_WEIGHTS = _city_w

                _cond_live = {
                    ct: cw for ct, cw in _cond_w.items() if not cw.get("_uncalibrated")
                }
                if _cond_live:
                    _cal_lines = ", ".join(
                        f"{ct}:nws={_cond_live[ct].get('nws', 0):.2f}"
                        for ct in sorted(_cond_live)
                    )
                    print(dim(f"  [Calibrate] condition weights: {_cal_lines}"))
                else:
                    print(
                        dim(
                            "  [Calibrate] condition weights: all types below min-samples — neutral"
                        )
                    )
                _seas_live = {
                    s: w for s, w in _seas_w.items() if not w.get("_uncalibrated")
                }
                if _seas_live:
                    _seas_lines = ", ".join(
                        f"{s}:nws={_seas_live[s].get('nws', 0):.2f}"
                        for s in sorted(_seas_live)
                    )
                    print(dim(f"  [Calibrate] seasonal weights: {_seas_lines}"))
    except Exception as _e:
        _log.debug("cmd_cron: ML bias retrain failed: %s", _e)
    finally:
        # Touch the marker whenever the retrain block ran — even on exception.
        # Without this, a crash in _train_bias()/_train_all_ts() leaves the marker
        # unwritten and the weekly gate fires on every subsequent cron cycle.
        if _should_retrain:
            _LAST_ML_RETRAIN_PATH.parent.mkdir(exist_ok=True)
            _LAST_ML_RETRAIN_PATH.touch()

    # D5b: Refresh per-city ensemble model weights (learned_weights.json) every 5 days.
    # Uses a SEPARATE gate file (.last_weights_refresh) rather than the data file's
    # own mtime.  The data file mtime only advances when update_learned_weights_from_tracker
    # returns data (>=20 predictions/city); if tracker has insufficient data the function
    # returns {} without writing anything, leaving the mtime old and causing the block
    # to fire on every cron cycle.  The gate file always advances after the attempt.
    # Note: the prewarm for this run already completed, so freshened weights take
    # effect on the *next* cron run — unavoidable without restructuring the flow.
    _WEIGHTS_GATE_PATH = Path(__file__).parent / "data" / ".last_weights_refresh"
    _should_refresh_weights = False  # declared before try so finally can read it
    try:
        import os as _os_lw

        if not _os_lw.environ.get("PYTEST_CURRENT_TEST"):
            _should_refresh_weights = True
            _weights_gate_age = (
                (datetime.now(UTC).timestamp() - _WEIGHTS_GATE_PATH.stat().st_mtime)
                / 86400
                if _WEIGHTS_GATE_PATH.exists()
                else 999.0
            )
            if _weights_gate_age < 5:
                _should_refresh_weights = False
            if _should_refresh_weights:
                from weather_markets import (
                    update_learned_weights_from_tracker as _upd_weights,
                )

                _new_weights = _upd_weights()
                if _new_weights:
                    _cities_updated = sorted(_new_weights.keys())
                    _log.info(
                        "cmd_cron: learned weights refreshed for %d city/model(s) "
                        "(gate was %.1f days old): %s",
                        len(_new_weights),
                        _weights_gate_age,
                        ", ".join(_cities_updated),
                    )
                    print(
                        dim(
                            f"  [ModelWeights] Refreshed weights for"
                            f" {len(_new_weights)} city/model(s)"
                            f" (gate was {_weights_gate_age:.1f}d old)"
                        )
                    )
                else:
                    _log.debug(
                        "cmd_cron: learned weights update skipped — "
                        "insufficient tracker data (min_n=20 per city)"
                    )
    except Exception as _e:
        _log.debug("cmd_cron: learned weights refresh failed: %s", _e)
    finally:
        # Always advance the gate after an attempt so a no-op (insufficient data)
        # doesn't leave the gate at age 999 and refire every cycle.
        if _should_refresh_weights:
            _WEIGHTS_GATE_PATH.parent.mkdir(exist_ok=True)
            _WEIGHTS_GATE_PATH.touch()

    # G5: Weekly — run parameter sweep after bias retrain so sweep sees fresh model.
    # Uses a marker file (same pattern as D5) so the sweep fires on the first cron
    # run after 7 days regardless of when the bot is running — the exact-hour check
    # fired multiple times per hour if cron ran every 15 min, and never fired if the
    # bot wasn't running at Sunday 03:00 UTC.
    _LAST_SWEEP_PATH = Path(__file__).parent / "data" / ".last_param_sweep"
    try:
        import os as _os_sweep

        if not _os_sweep.environ.get("PYTEST_CURRENT_TEST"):
            _should_sweep = True
            if _LAST_SWEEP_PATH.exists():
                _sweep_days_since = (
                    datetime.now(UTC).timestamp() - _LAST_SWEEP_PATH.stat().st_mtime
                ) / 86400
                _should_sweep = _sweep_days_since >= 7
            if _should_sweep:
                _log.info(
                    "cmd_cron: running weekly parameter sweep (>=7 days since last)"
                )
                from param_sweep import run_sweep as _run_sweep

                try:
                    _sweep_result = _run_sweep()
                    if _sweep_result:
                        print(
                            dim(
                                "  [Sweep] Weekly parameter sweep complete — results updated."
                            )
                        )
                except Exception as _sweep_err:
                    _log.warning("cmd_cron: weekly sweep failed: %s", _sweep_err)
                # Refresh PDO/PNA climate indices weekly (cheap, ~2 NOAA CSV fetches).
                # Always-on from day one \u2014 index file is used as a gate for blend activation.
                try:
                    from climate_indices import fetch_pdo_pna

                    fetch_pdo_pna()
                    _log.debug("PDO/PNA indices refreshed")
                except Exception as exc:
                    _log.debug("PDO/PNA refresh failed (non-fatal): %s", exc)

                # Always touch marker after attempting so the gate closes correctly
                # even when param_sweep has no data to work with yet.
                _LAST_SWEEP_PATH.parent.mkdir(exist_ok=True)
                _LAST_SWEEP_PATH.touch()
    except Exception as _e:
        _log.debug("cmd_cron: weekly sweep check failed: %s", _e)

    # Flush ensemble disk cache before exit \u2014 daemon threads were killed before
    # writing; a single synchronous batch write here guarantees the next run
    # starts with a warm ensemble cache and avoids circuit breaker trips.
    try:
        from weather_markets import flush_ensemble_disk_cache as _flush_ensemble

        _flushed = _flush_ensemble()
        if _flushed:
            print(
                dim(f"  [cron] ensemble cache: {_flushed} entries saved to disk"),
                flush=True,
            )
    except Exception as _e:
        _log.debug("ensemble cache flush failed: %s", _e)

    # Sync data/ to cloud (OneDrive / Google Drive / custom path) after every cron run
    try:
        from cloud_backup import backup_data as _backup

        _backup()
    except Exception:
        pass  # never crash the scheduler over a backup failure

    print(
        cyan(
            f"  [cron] scan complete \u2014 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        ),
        flush=True,
    )
    return True  # signals full scan completed (early returns return None)


# ---------------------------------------------------------------------------
# Main cron command
# ---------------------------------------------------------------------------


def _install_cron_watchdog(timeout_secs: int = 720) -> None:
    """Start a daemon thread that hard-kills the process if cron hangs > timeout_secs.

    Used because signal.SIGALRM is unavailable on Windows.  The thread is
    daemonised so it dies automatically when the main thread exits normally.
    Adjust timeout_secs via env var CRON_WATCHDOG_SECS (default 8 min).
    """
    import threading as _threading
    import time as _time_wdog

    _wdog_secs = int(os.getenv("CRON_WATCHDOG_SECS", str(timeout_secs)))

    def _watchdog() -> None:
        _time_wdog.sleep(_wdog_secs)
        # If we're still alive here the cron body hung
        _log.critical(
            "CRON WATCHDOG: cron has been running for %ds — force-killing process to prevent infinite hang",
            _wdog_secs,
        )
        print(
            f"\n  ⚠  CRON WATCHDOG: exceeded {_wdog_secs}s limit — killing process\n",
            flush=True,
        )
        os._exit(
            1
        )  # hard kill — no cleanup; preferred over sys.exit so finally blocks don't re-hang

    _wdog_thread = _threading.Thread(
        target=_watchdog, name="cron-watchdog", daemon=True
    )
    _wdog_thread.start()
    _log.debug("cron watchdog armed: %ds", _wdog_secs)


def cmd_cron(
    ctx: CronContext, client: KalshiClient, min_edge: float = MIN_EDGE
) -> None:
    """Silent background scan — writes to data/cron.log, auto-places strong paper trades."""
    import sys as _sys

    if os.getenv("KALSHI_ENV") == "prod":
        _log.warning("=" * 60)
        _log.warning("CRON RUNNING IN PRODUCTION MODE — REAL MONEY TRADES ENABLED")
        _log.warning(
            "KALSHI_ENV=prod | STARTING_BALANCE=$%.2f",
            float(os.getenv("STARTING_BALANCE", "1000")),
        )
        _log.warning("=" * 60)

    # Arm a hard-kill watchdog.  If the network layer hangs past the socket
    # backstop (a known Windows/SSL edge case), the watchdog ensures cron never
    # blocks forever.  Default: 8 minutes; override via CRON_WATCHDOG_SECS env.
    _install_cron_watchdog()

    if not ctx.acquire_cron_lock():
        _log.warning("cmd_cron: could not acquire lock — skipping this run")
        if not getattr(cmd_cron, "_called_from_loop", False):
            _sys.exit(1)
        return

    _full_scan = False
    try:
        _full_scan = bool(_cmd_cron_body(ctx, client, min_edge))
    except KeyboardInterrupt:
        print()
        _log.warning("cmd_cron: interrupted by user")
    finally:
        ctx.clear_cron_running_flag()
        try:
            _last_run_path = Path(__file__).parent / "data" / ".cron_last_run"
            # L-1: write UTC timestamp — naive local time is inconsistent with all
            # other system timestamps and produces wrong elapsed-time calculations.
            _now_iso = (
                __import__("datetime")
                .datetime.now(__import__("datetime").timezone.utc)
                .isoformat()
            )
            _last_run_path.write_text(_now_iso)
        except Exception:
            pass
        try:
            _hb_path = Path(__file__).parent / "data" / "cron_heartbeat.json"
            try:
                _cycle = (
                    json.loads(_hb_path.read_text()).get("cycle_count", 0) + 1
                    if _hb_path.exists()
                    else 1
                )
            except Exception:
                _cycle = 1
            _hb_path.write_text(
                json.dumps({"last_run": _now_iso, "cycle_count": _cycle})
            )
        except Exception:
            pass
        try:
            import sqlite3 as _sqlite3

            from tracker import DB_PATH as _TRACKER_DB

            with _sqlite3.connect(_TRACKER_DB) as _wc:
                _wc.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception:
            pass
        ctx.release_cron_lock()
    if _full_scan and not getattr(cmd_cron, "_called_from_loop", False):
        _sys.exit(0)
