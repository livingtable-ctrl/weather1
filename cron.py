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
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING

import execution_log
from colors import bold, cyan, dim, green, red, yellow
from kalshi_client import KalshiClient
from paths import (
    CRON_HEARTBEAT_PATH,
    CRON_LAST_RUN_PATH,
    CRON_LOG_PATH,
    DATA_DIR,
    EMOS_PARAMS_PATH,
    GRADUATED_FLAG_PATH,
    KILL_SWITCH_PATH,
    LAST_CALIBRATION_COUNT_PATH,
    LAST_ML_RETRAIN_PATH,
    LAST_MONDAY_SWEEP_PATH,
    LAST_PARAM_SWEEP_PATH,
    LAST_QUARANTINE_SCAN_PATH,
    LAST_WALK_FORWARD_PATH,
    LAST_WEIGHTS_REFRESH_PATH,
    LOCK_PATH,
    MANUAL_OVERRIDE_PATH,
    PROD_REMINDER_PATH,
    RUNNING_FLAG_PATH,
    SIGNALS_CACHE_PATH,
)
from utils import (
    DRIFT_TIGHTEN_EDGE,
    STRONG_EDGE,
    is_trading_paused,
)

if TYPE_CHECKING:
    from kalshi_ws import KalshiWebSocket

# Use the "main" logger name so that existing tests which capture
# logging.getLogger("main") continue to see cron log output.
_log = logging.getLogger("main")

# Tracks the KalshiWebSocket instance _cmd_cron_body() created/started this
# cycle (if any), so cmd_cron()'s outer finally block can stop it regardless
# of how _cmd_cron_body() exits. Without this, a fresh KalshiWebSocket was
# created and started every single cycle with no matching stop() anywhere --
# harmless for one-shot `cron` (the process exits right after), but a real
# thread/socket leak in main.py's `loop`/`watch --auto` in-process loops,
# which call cmd_cron() repeatedly for the lifetime of the process.
_active_ws: KalshiWebSocket | None = None


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

    # Trade-cycle gates (from cron.py / paper.py, re-exported via main) --
    # added for trade_cycle.run_trade_cycle()'s shared gate set (backlog.txt
    # "THE ONLY LIVE-ORDER PATH..."). Routed through ctx rather than imported
    # directly by trade_cycle.py so trade_cycle.py has no import-time
    # dependency on cron.py/paper.py internals, matching the existing seam.
    check_accuracy_halt: Callable[[], tuple[bool, str | None]]
    check_graduation_gate: Callable[[], None]


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

    AUD-0006: the exists()-check + later write_text() below is a TOCTOU race
    on its own -- two processes can both observe exists()==False (or both
    independently decide a stale lock should be overridden) and both write.
    The whole check-then-decide-then-write sequence is wrapped in a real OS
    mutex (keyed off LOCK_PATH + ".mutex", separate from the lock file
    itself so the lock file's own format/tests are untouched) so only one
    caller ever executes this logic at a time; the loser re-checks under the
    mutex and correctly sees the winner's fresh lock.
    """
    import time as _time

    from safe_io import CrossProcessLock

    lp = LOCK_PATH
    _mutex = CrossProcessLock(lp.with_name(lp.name + ".mutex"), timeout=5.0)
    if not _mutex.acquire():
        _log.error(
            "cmd_cron: could not acquire cron-lock mutex within timeout — "
            "failing closed (cannot safely check/write the lock file)"
        )
        return False
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
    finally:
        _mutex.release()


def _release_cron_lock() -> None:
    """Delete the cron lock file.

    AUD-0006 followup (opus review): the acquire-side mutex only serializes
    _acquire_cron_lock's own check-then-write body -- without also taking it
    here, another process's acquire() could observe lp.exists() == True
    (under ITS mutex hold) and then have this unlink() race its own
    lp.read_text() a moment later, turning a perfectly free lock into a
    spurious "unreadable lock file" fail-closed skip. Best-effort: still
    attempts the unlink even if the mutex itself can't be acquired within
    its timeout (never let the locking mechanism block releasing the real
    lock -- leaving the lock file behind would be worse than a narrow race).
    """
    from safe_io import CrossProcessLock

    lp = LOCK_PATH
    _mutex = CrossProcessLock(lp.with_name(lp.name + ".mutex"), timeout=5.0)
    _mutex.acquire()
    try:
        lp.unlink(missing_ok=True)
    except Exception as _e:
        _log.warning("cmd_cron: could not release lock: %s", _e)
    finally:
        _mutex.release()


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


def _check_accuracy_halt() -> tuple[bool, str | None]:
    """Combine paper.is_accuracy_halted()/get_accuracy_halt_reason() into the
    single (halted, reason) shape trade_cycle.run_trade_cycle() consumes via
    CronContext.check_accuracy_halt.
    """
    from paper import get_accuracy_halt_reason, is_accuracy_halted

    if is_accuracy_halted():
        return True, get_accuracy_halt_reason() or "accuracy circuit breaker active"
    return False, None


def _check_spend_cap_vs_balance() -> None:
    """Warn if MAX_DAILY_SPEND exceeds the current paper balance.

    A spend cap that exceeds the available balance can never trigger and indicates
    a config mistake.
    """
    import paper as _paper
    from utils import MAX_DAILY_SPEND as _spend_cap  # F8: was a second env read
    # defaulting to "0" instead of utils.py's real "500.0" default — an unset
    # MAX_DAILY_SPEND made this cosmetic warn-only check silently inert instead
    # of comparing against the actual enforced 500 cap.

    _bal = _paper.get_balance()
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

    override_path = MANUAL_OVERRIDE_PATH
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
        # Fail closed: the file's mere existence means the user deliberately
        # started a pause at some point — a corrupt/unparseable file is far
        # more likely to mean "the pause is still meant to be active but got
        # corrupted" than "safe to resume trading." Previously this returned
        # False (pause silently ignored) at DEBUG level.
        _log.error(
            "_check_manual_override: %s is corrupted (%s) — treating override "
            "as still active (fail closed). Delete the file to clear it manually.",
            override_path,
            exc,
        )
        return True


_ANOMALY_THRESHOLD = 0.12  # pp drift required to flag a market

# Reminder fires once per day after this date when KALSHI_ENV=prod.
# Change this date to push the reminder further out (e.g. after graduation).
_PROD_REMINDER_DATE = _dt.date(2026, 7, 29)

_PROD_REMINDER_CHECKLIST = """\
[1-month prod reminder] Deferred items to review:

  1. emos-train       : EMOS code deployed but emos_params.json absent (fallback mode).
                        Run: py main.py emos-train           (dry run, review the fit)
                        Then: py main.py emos-train --activate   (go live, requires confirm)
                        Two-stage: a+b from all rows, c+d from rows with non-NULL ens_var.

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
                # Distinct key (opus review, 2026-07-31): this caller used to
                # share the default "__system__" key with the dead-man's-
                # switch alert below with no real consequence, since the old
                # in-process-only cooldown reset every fresh cron process
                # anyway. Now that the cooldown persists to disk, sharing a
                # key would let this alert silently suppress the unrelated
                # dead-man's-switch alert for 6h across separate cron runs
                # (or vice versa) -- exactly the hazard send_system_alert()'s
                # own docstring already warns callers to avoid.
                cooldown_key="prod_reminder",
            )
        except Exception as _ntfy_exc:
            _log.debug("prod reminder ntfy failed: %s", _ntfy_exc)
        PROD_REMINDER_PATH.write_text(str(_dt.date.today()))
    except Exception as _exc:
        _log.debug("_check_prod_reminder failed: %s", _exc)


def _log_near_settlement_trades(near: list[dict], db_path: Path) -> tuple[int, int]:
    """Write near-settlement snapshot rows for future calibration analysis.

    `near` is check_expiring_trades()'s output — each entry wraps a stored
    paper-trade record ("trade", see paper.place_paper_order/get_open_trades)
    plus "hours_left". A stored trade record uses "side"/"entry_prob", not
    "recommended_side"/"forecast_prob" (those are analysis-dict field names,
    see order_executor.py) — reading the wrong names here previously left
    trade_side NULL, violating the table's NOT NULL constraint; INSERT OR
    IGNORE silently drops NOT NULL violations instead of raising, so this ran
    "successfully" for over a month while writing zero rows.

    Cannot be back-filled — this is a point-in-time snapshot, so a write is
    attempted every cron cycle a trade is in the 0-2h window; the unique
    index on (ticker, hour) dedupes repeat attempts within the same hour.
    Returns (attempted, written) — written < attempted means some rows were
    silently dropped (NOT NULL violation or dedup conflict).
    """
    import sqlite3
    from datetime import UTC, datetime

    written = 0
    with sqlite3.connect(db_path) as con:
        for nt in near:
            tr = nt["trade"]
            cur = con.execute(
                "INSERT OR IGNORE INTO near_settlement_log "
                "(ticker, our_model_prob, market_yes_price, hours_to_close, "
                " trade_side, days_out, recorded_at) VALUES (?,?,?,?,?,?,?)",
                (
                    tr.get("ticker"),
                    tr.get("entry_prob"),
                    None,  # market_yes_price: Phase 2 — requires live market fetch
                    nt["hours_left"],
                    tr.get("side"),
                    tr.get("days_out", 0),
                    datetime.now(UTC).isoformat(),
                ),
            )
            written += cur.rowcount
    return len(near), written


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


def _placement_outcome_phrase(placed: int, found: int) -> str:
    """Describe a tier's actual placement outcome for the STRONG/MED console
    banners. `found` (len(strong_opps)/len(med_opps)) is the candidate count
    from analysis; `placed` (result.placed_strong/placed_med) is what
    ctx.auto_place_trades() actually placed. The two can diverge for many
    reasons -- a whole-batch skip (drawdown pause, daily-loss halt, position
    cap, spend cap) that never even reaches a per-candidate check, or a
    per-candidate rejection (already-open, stale price, a strategy
    retirement mid-cycle, Kelly too small, ...) -- so this deliberately does
    NOT name a specific cause (an earlier draft claimed "pre-placement
    re-check failed" for every shortfall, which is wrong for most of the
    whole-batch-skip reasons above and would send an operator chasing the
    wrong subsystem). The real reason is already printed nearby by
    order_executor's own "[Auto] Position cap reached" / "[Auto] Skipped
    N signal(s): <ticker>: <reason>" lines -- point there instead of
    guessing (backlog.txt "STRONG/MED SIGNAL BANNER OVERCLAIMS...").
    """
    if placed >= found:
        return "placing paper trades"
    if placed > 0:
        return f"placed {placed} of {found} (see [Auto] lines above for why the rest were skipped)"
    return f"0 of {found} placed (see [Auto] lines above for why)"


def _cmd_cron_body(
    ctx: CronContext,
    client: KalshiClient,
    min_edge: float | None = None,
    sameday_only: bool = False,
) -> bool | None:
    """Core scan logic — extracted from cmd_cron so it can be wrapped in try/finally.

    ``sameday_only``: threaded straight through to trade_cycle.run_trade_cycle()
    -- see that function's own docstring for what it does. Default False.
    """
    # Soft-halt reason (manual override, accuracy halt, graduation gate, anomaly
    # halt). Unlike the kill switch below, these must NOT stop the whole cycle —
    # settlement and stop-loss protection need to keep running (accuracy halt in
    # particular is computed from settled trades, so skipping settlement while
    # halted made the halt self-perpetuating). Only trade placement is skipped,
    # mirroring the existing TRADING_PAUSED handling further down.
    _cron_halted_reason: str | None = None

    # P8.3 — hard kill switch: touch data/.kill_switch to halt immediately.
    # Deliberately still a full stop — this is the one operator-engaged
    # "stop absolutely everything now" mechanism, not one of the soft halts above.
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

    # Manual override / accuracy halt / graduation gate: run_trade_cycle()
    # checks all three itself (via the same ctx methods) and is the actual
    # placement-blocking authority now -- but the anomaly-detection block
    # below still needs to know *before it runs* whether an earlier soft
    # halt already stopped this cycle, so its interactive override prompt
    # isn't reached when answering it wouldn't do anything (see the
    # "anomaly halt also triggered" branch a bit further down, and
    # test_anomaly_override_prompt_skipped_when_already_halted). Also, if
    # the black-swan check below hard-aborts (return None) before
    # run_trade_cycle() is ever reached, THIS is the only place an active
    # override/accuracy-halt/graduation-gate condition gets logged for that
    # cycle at all -- without it, an operator investigating a black-swan
    # abort would see no trace of a simultaneously-active soft halt.
    # Logging here is intentionally duplicated with run_trade_cycle()'s own
    # logging on the normal (non-black-swan-abort) path: check_manual_
    # override() is idempotent but not side-effect-free (it can unlink an
    # expired override file and always logs while one is active), and
    # check_accuracy_halt()/check_graduation_gate() each cost an extra
    # tracker.db round-trip when computed twice -- accepted as a minor,
    # bounded cost in exchange for the black-swan-abort visibility above.
    if ctx.check_manual_override():
        _cron_halted_reason = "manual override active"
        _log.warning(
            "cmd_cron: manual override active — skipping trade placement this run"
        )
    _acc_halted, _acc_reason = ctx.check_accuracy_halt()
    if _acc_halted:
        _cron_halted_reason = _cron_halted_reason or _acc_reason
        _log.warning(
            "cmd_cron: ACCURACY HALT ACTIVE: %s — skipping trade placement this "
            "cycle (settlement/stop-losses still run so the halt can clear)",
            _acc_reason,
        )
    try:
        ctx.check_graduation_gate()
    except RuntimeError as _gate_err:
        _cron_halted_reason = _cron_halted_reason or str(_gate_err)
        _log.error("cmd_cron: %s — skipping trade placement this cycle", _gate_err)

    # Dead-man's-switch: if more than 48h have elapsed since the last cron run completed,
    # log a warning and fire a system notification so the user knows the bot went quiet.
    # .cron_last_run is written in the cmd_cron finally block on every completion, so a
    # gap > 48h means the process was stopped or crashing for at least two days.
    try:
        _last_run_path = CRON_LAST_RUN_PATH
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
                    # Distinct key -- see the prod-reminder call site's
                    # identical comment above for why this matters now that
                    # the cooldown is disk-persisted (opus review, 2026-07-31).
                    cooldown_key="cron_gap",
                )
    except Exception as _gap_exc:
        _log.debug("cmd_cron: dead-man's-switch check failed: %s", _gap_exc)

    # Full-scan staleness check — distinct from the dead-man's-switch above.
    # --sameday-only (opus review, 2026-08-22) keeps .cron_last_run fresh
    # (the process is genuinely alive and scanning), which would otherwise
    # silently mask a scheduled full-scan task having stopped running for
    # days while an operator keeps the bot "alive" with manual sameday-only
    # cycles during that exact gap -- the manual-cadence scenario this mode
    # itself targets. cron_heartbeat.json's last_full_scan (written in the
    # cmd_cron finally block, only advanced on a non-sameday_only run) is
    # the freshness signal for that specific risk.
    try:
        if CRON_HEARTBEAT_PATH.exists():
            _hb_check = json.loads(CRON_HEARTBEAT_PATH.read_text())
            _last_full_iso = _hb_check.get("last_full_scan")
            if _last_full_iso:
                from datetime import UTC as _UTC
                from datetime import datetime as _dt_check

                _full_gap_hours = (
                    _dt_check.now(_UTC) - _dt_check.fromisoformat(_last_full_iso)
                ).total_seconds() / 3600
                if _full_gap_hours > 48:
                    _log.warning(
                        "cmd_cron: %.0fh since last FULL (non-sameday-only) "
                        "scan — full-scan gap alert fired",
                        _full_gap_hours,
                    )
                    from notify import send_system_alert as _sys_alert2

                    _sys_alert2(
                        "Kalshi cron full-scan gap detected",
                        f"Last full multi-day scan was {_full_gap_hours:.0f}h ago "
                        "— only sameday-only runs since. Run: py main.py cron",
                        # Distinct key from "cron_gap" above -- see that call
                        # site's own comment for why a distinct cooldown key
                        # matters now that the cooldown is disk-persisted.
                        cooldown_key="cron_full_scan_gap",
                    )
    except Exception as _full_gap_exc:
        _log.debug("cmd_cron: full-scan staleness check failed: %s", _full_gap_exc)

    # Spend cap validation — warn if MAX_DAILY_SPEND exceeds current balance.
    # This is a cosmetic config-mistake warning, not a safety gate — a
    # paper.get_balance() failure here must not crash the whole cycle before
    # settlement/stop-losses get a chance to run.
    try:
        _check_spend_cap_vs_balance()
    except Exception as _spend_cap_exc:
        _log.warning("cmd_cron: spend cap vs balance check failed: %s", _spend_cap_exc)

    # 1-month prod reminder — fires once per day after _PROD_REMINDER_DATE in prod mode
    _check_prod_reminder()

    from datetime import UTC, datetime

    print(
        cyan(
            f"  [cron] scan starting \u2014 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC"
            + (" (same-day only)" if sameday_only else "")
        ),
        flush=True,
    )

    # Settle any resolved trades before scanning so same-day slot counts
    # reflect current open risk, not yesterday's expired-but-not-yet-settled
    # positions -- restored here at its original early position (also run
    # inside run_trade_cycle(), which becomes a harmless no-op the second
    # time). Several checks between here and the engine call (near-
    # settlement logging, anomaly detection, black-swan check, directional-
    # accuracy snapshot, Brier-drift detection, auto-retirement) read
    # paper.json and must see this cycle's just-resolved trades, not only
    # last cycle's post-place settle -- restoring the early call, not just
    # relying on the engine's later one, is what makes that true again.
    try:
        from paper import auto_settle_paper_trades as _pre_settle

        _early_pre_settled = _pre_settle(client)
        if _early_pre_settled:
            _early_pre_net = sum(t.get("pnl") or 0.0 for t in _early_pre_settled)
            _early_pre_str = (
                f"+${_early_pre_net:.2f}"
                if _early_pre_net >= 0
                else f"-${abs(_early_pre_net):.2f}"
            )
            print(
                green(
                    f"  [PreSettle] {len(_early_pre_settled)} trade(s) settled before scan — net P&L: {_early_pre_str}"
                )
            )
    except Exception as _pre_settle_exc:
        _log.warning("cmd_cron: pre-scan settlement failed: %s", _pre_settle_exc)

    # Log trades within 0–2h of close for future calibration analysis.
    # Data cannot be back-filled — write every cycle, deduplicate via unique index.
    try:
        from paper import check_expiring_trades as _check_expiring
        from tracker import DB_PATH as _NSL_DB

        _near = [t for t in _check_expiring(warn_hours=2) if t["hours_left"] >= 0]
        if _near:
            _attempted, _written = _log_near_settlement_trades(_near, _NSL_DB)
            if _written < _attempted:
                _log.warning(
                    "near_settlement_log: %d/%d trade(s) written — some rows were "
                    "silently dropped (NOT NULL or dedup conflict)",
                    _written,
                    _attempted,
                )
            else:
                _log.info("near_settlement_log: logged %d trade(s)", _written)
    except Exception as _nsl_err:
        _log.warning("near_settlement_log: write failed: %s", _nsl_err)

    # When neither dynamic nor static same-day reservation is active, remind the user
    # to enable dynamic mode once enough data has accumulated. Must check the same
    # above/below settled-trade pool _sameday_effective_cap()'s dynamic formula
    # actually uses (paper.get_sameday_band_stats' baseline) — not
    # count_settled_sameday_predictions(), which counts every days_out=0 market
    # type and can clear the threshold long before the real pool does.
    try:
        from utils import (
            SAME_DAY_DYNAMIC_BAND_HOURS,
            SAME_DAY_DYNAMIC_SLOTS,
            SAME_DAY_RESERVE_MIN_SAMPLES,
            SAME_DAY_RESERVE_SLOTS,
        )

        if not SAME_DAY_DYNAMIC_SLOTS and SAME_DAY_RESERVE_SLOTS == 0:
            from paper import get_sameday_band_stats

            _sd_count = get_sameday_band_stats(SAME_DAY_DYNAMIC_BAND_HOURS)["baseline"][
                "total"
            ]
            if _sd_count >= SAME_DAY_RESERVE_MIN_SAMPLES:
                print(
                    yellow(
                        f"  [SameDayReserve] {_sd_count} same-day above/below trades settled — "
                        f"set SAME_DAY_DYNAMIC_SLOTS=1 in .env to activate dynamic per-band cap scaling."
                    )
                )
    except Exception:
        pass

    # EMOS readiness reminder: print until emos_params.json exists (training done).
    # Reminds operator to run backfill-emos, then (once the user's own real
    # go-live bar of ~80 ens_var rows is cleared -- backlog.txt UPDATE
    # 2026-08-18 -- not the 40-row Gneiting-2005 statistical minimum below,
    # which only governs ens_mean-rows messaging/trainability) emos-train.
    # 40 = Gneiting 2005 minimum: 10 forecast cases per parameter × 4 EMOS parameters.
    _EMOS_PARAMS_PATH = EMOS_PARAMS_PATH
    if not _EMOS_PARAMS_PATH.exists():
        try:
            from tracker import (
                count_emos_ready_predictions,
                count_emos_variance_ready_predictions,
            )

            _emos_n = count_emos_ready_predictions()
            _emos_var_n = count_emos_variance_ready_predictions()
            _EMOS_TRAIN_GATE = 40
            # User's own explicit go-live bar (backlog.txt UPDATE 2026-08-18),
            # stricter than _EMOS_TRAIN_GATE's Gneiting-2005 statistical
            # minimum: readiness/"accumulating" messaging below is keyed off
            # this, not the 40-row floor. _EMOS_TRAIN_GATE itself still governs
            # the ens_mean-rows messaging above (a genuinely different concern:
            # main.py's own emos-train --activate gate) and is left untouched.
            _EMOS_GOLIVE_BAR = 80
            if _emos_n == 0:
                print(
                    yellow(
                        f"  [EMOS] ens_mean rows: {_emos_n}/{_EMOS_TRAIN_GATE} — "
                        f"run 'py main.py backfill-emos' to populate history."
                    )
                )
            elif _emos_n < _EMOS_TRAIN_GATE:
                # backfill-emos DOES move ens_mean (a/b are fit from all rows,
                # not just ens_var ones), so still suggest it here -- it just
                # won't move the ens_var-populated count in the branch below.
                print(
                    yellow(
                        f"  [EMOS] ens_mean rows: {_emos_n}/{_EMOS_TRAIN_GATE}, "
                        f"ens_var-populated: {_emos_var_n}/{_EMOS_GOLIVE_BAR} — "
                        f"run 'py main.py backfill-emos' if new trades settled "
                        f"(won't move the ens_var count, only forward-fill live "
                        f"trades do)."
                    )
                )
            elif _emos_var_n < _EMOS_GOLIVE_BAR:
                # ens_mean already cleared 40, but ens_var (what c/d are
                # actually fit from) hasn't cleared the real go-live bar --
                # backfill-emos can't help this count, only forward-fill live
                # trades populate ens_var.
                print(
                    yellow(
                        f"  [EMOS] ens_mean rows: {_emos_n}, ens_var-populated: "
                        f"{_emos_var_n}/{_EMOS_GOLIVE_BAR} — accumulating from live "
                        f"forward-fill trades."
                    )
                )
            else:
                print(
                    yellow(
                        f"  [EMOS] ens_var-populated rows: {_emos_var_n} — READY "
                        f"(>= {_EMOS_GOLIVE_BAR}-row go-live bar). Run "
                        f"'py main.py emos-train' to review the fit (dry run by "
                        f"default), then add --activate to go live."
                    )
                )
        except Exception:
            pass

    # Weekly DB retention sweep (runs on Monday only, at most once per 7 days).
    # Uses a marker file so back-to-back cron runs on the same Monday don't
    # re-run the sweep.  A skipped Monday is handled automatically: next Monday
    # the marker will be ≥14 days old and the sweep fires normally.
    from utils import utc_today as _utc_today

    _MONDAY_SWEEP_PATH = LAST_MONDAY_SWEEP_PATH
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

    # Reconcile any 'pending' live orders left by a previous crash. Restored
    # here (also run inside run_trade_cycle(), which becomes a harmless
    # no-op the second time -- there's nothing left pending to recover) so
    # it runs BEFORE the live-position-exit checks immediately below, not
    # after them: a live position recovered from status='pending' to
    # status='filled' by this call must be visible to those exit checks in
    # THIS cycle, not just the next one. _check_live_position_exits's own
    # docstring in order_executor.py states this same ordering constraint
    # for _poll_pending_orders/_check_live_position_exits in watch's cycle;
    # the same dependency exists here between recovery and the exit checks.
    if client is not None:
        try:
            from order_executor import _recover_pending_orders

            _recover_pending_orders(client)
        except Exception as _rpo_exc:
            _log.warning("cmd_cron: _recover_pending_orders failed: %s", _rpo_exc)

        # Protect any live position still open from an earlier watch/live
        # session -- cron.py itself never OPENS a new live position (see
        # backlog.txt's [RESTING EXIT ORDERS + OCO...] entry), but it can
        # still place a real live SELL order via the exit checks right below
        # to protect one, and a position opened during a prior
        # `watch --auto --live` run can still be open when a later cron run
        # fires, and previously got zero automated exit management here.
        try:
            from order_executor import (
                _check_live_model_exits,
                _check_live_position_exits,
            )

            _check_live_position_exits(client)
            _check_live_model_exits(client)
        except Exception as _live_exit_exc:
            _log.warning(
                "cmd_cron: live position protection failed: %s", _live_exit_exc
            )

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
            elif _cron_halted_reason is not None:
                # Deep-review followup: an earlier soft-halt (manual
                # override, accuracy halt, graduation gate) already stopped
                # placement this cycle — prompting "Override and run this
                # cycle anyway?" here was misleading: answering "y" only
                # ever suppressed THIS reason, but the combined gate further
                # down (`if _trading_paused or _cron_halted_reason:`) still
                # skips placement for the earlier reason regardless, so the
                # operator believed they'd authorized trading and it
                # silently didn't happen. No prompt needed — trading is
                # already stopped for this cycle either way.
                _log.error(
                    "cmd_cron: anomaly halt also triggered (placement already "
                    "stopped this cycle by: %s): %s",
                    _cron_halted_reason,
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
                    _cron_halted_reason = _cron_halted_reason or (
                        f"anomaly halt: {'; '.join(_detected_anomalies)}"
                    )
                else:
                    _log.warning(
                        "cmd_cron: anomaly halt overridden by user for this cycle: %s",
                        _detected_anomalies,
                    )
            else:
                _log.error(
                    "cmd_cron: anomaly halt triggered — stopping trade placement this cycle: %s",
                    _detected_anomalies,
                )
                _cron_halted_reason = _cron_halted_reason or (
                    f"anomaly halt: {'; '.join(_detected_anomalies)}"
                )
        elif _detected_anomalies:
            _log.warning(
                "cmd_cron: soft anomaly warnings (below halt threshold), continuing: %s",
                _detected_anomalies,
            )
    except Exception as _e:
        # run_anomaly_check is fail-closed internally (an exception inside it
        # already returns should_halt=True) — reaching this handler means
        # something more fundamental broke (e.g. an ImportError from a bad
        # edit to alerts.py). Fail closed here too rather than silently
        # continuing as if the check had passed.
        _log.error("cmd_cron: run_anomaly_check call failed — failing closed: %s", _e)
        _cron_halted_reason = _cron_halted_reason or f"anomaly check error: {_e}"

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
        # Same reasoning as the anomaly-check handler above: run_black_swan_check
        # is fail-closed internally, so reaching here means something more
        # fundamental broke (e.g. activate_black_swan_halt() itself raising
        # while writing the halt files — precisely when the halt matters most).
        _log.error(
            "cmd_cron: run_black_swan_check call failed — failing closed: %s", _e
        )
        _cron_halted_reason = _cron_halted_reason or f"black swan check error: {_e}"

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

    # Per-ensemble-member quarantine scan (log-only outcome messages, but the
    # scan itself DOES gate the live blend -- see weather_markets.py's
    # "Per-member EWMA quarantine" section). Runs at most once/day via a
    # marker file, same idiom as the Monday sweep below. Only ever reached
    # inside _cmd_cron_body, i.e. only after _acquire_cron_lock() succeeds --
    # a double-run here under a broken lock is the same, already-tracked
    # AUD-0006 risk every other line in this function has, not a new one; a
    # lost update just means one scan's quarantine decision is overwritten by
    # the other's, self-heals on the next successful scan.
    try:
        _quarantine_scan_age = (
            (datetime.now(UTC).timestamp() - LAST_QUARANTINE_SCAN_PATH.stat().st_mtime)
            / 86400
            if LAST_QUARANTINE_SCAN_PATH.exists()
            else 999.0
        )
        if _quarantine_scan_age >= 1:
            from weather_markets import _QUARANTINE_CANDIDATE_MODELS as _Q_MODELS
            from weather_markets import _QUARANTINE_TRIP_Z as _Q_TRIP_Z
            from weather_markets import load_member_quarantine_state as _load_q_state
            from weather_markets import scan_member_quarantine as _scan_quarantine

            _q_result = _scan_quarantine()
            if _q_result["newly_quarantined"]:
                _log.warning(
                    "cmd_cron: quarantined ensemble member(s): %s",
                    _q_result["newly_quarantined"],
                )
            if _q_result["released"]:
                _log.info(
                    "cmd_cron: released ensemble member(s) from quarantine: %s",
                    _q_result["released"],
                )
            if _q_result["blocked_by_floor"]:
                _log.warning(
                    "cmd_cron: ensemble member(s) qualify for quarantine but "
                    "blocked by the active-member floor: %s",
                    _q_result["blocked_by_floor"],
                )
            # Daily ewma_z status line, logged every scan (not just when
            # something actually changes) -- z tends to sit well under the
            # trip line for long stretches (see backlog.txt "MEMBER
            # QUARANTINE DETECTION STATISTIC SWAPPED"), so tracking its
            # drift day-to-day is the only way to see a real problem
            # building before it actually trips. WARNING once any
            # non-quarantined candidate's ewma_z crosses half the trip
            # threshold, so it's easy to grep for without reading every
            # day's INFO line.
            try:
                _q_state = _load_q_state()
                _q_status_parts = []
                _q_approaching = []
                for _q_model in _Q_MODELS:
                    _q_entry = _q_state.get(_q_model)
                    if not isinstance(_q_entry, dict) or "ewma_z" not in _q_entry:
                        continue
                    _q_ewma_z = _q_entry["ewma_z"]
                    _q_status_parts.append(f"{_q_model}={_q_ewma_z:.2f}")
                    if not _q_entry.get("quarantined") and _q_ewma_z >= 0.5 * _Q_TRIP_Z:
                        _q_approaching.append(f"{_q_model} (ewma_z={_q_ewma_z:.2f})")
                if _q_status_parts:
                    _log.info(
                        "cmd_cron: quarantine ewma_z (trip=%.1f): %s",
                        _Q_TRIP_Z,
                        ", ".join(_q_status_parts),
                    )
                if _q_approaching:
                    _log.warning(
                        "cmd_cron: ensemble member(s) approaching the quarantine "
                        "trip line (ewma_z >= %.1f): %s",
                        0.5 * _Q_TRIP_Z,
                        _q_approaching,
                    )
            except Exception as _q_status_exc:
                _log.debug(
                    "cmd_cron: quarantine ewma_z status log failed: %s",
                    _q_status_exc,
                )
            LAST_QUARANTINE_SCAN_PATH.parent.mkdir(exist_ok=True)
            LAST_QUARANTINE_SCAN_PATH.touch()
    except Exception as _e:
        _log.debug("cmd_cron: scan_member_quarantine failed: %s", _e)

    # Condition-type weakness check (log-only, non-blocking, no halt gate --
    # see tracker.check_condition_type_weakness's own docstring for why).
    # Surfaces a (method, condition_type) pair running well below a coin
    # flip even when that method's aggregate Brier looks merely mediocre,
    # without needing a manual per-condition-type breakdown to find it.
    try:
        from tracker import check_condition_type_weakness as _check_cond_weak

        for _cond_alert in _check_cond_weak():
            _log.warning("cmd_cron: %s", _cond_alert)
    except Exception as _e:
        _log.debug("cmd_cron: check_condition_type_weakness failed: %s", _e)

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
        from datetime import timedelta as _td_pin

        import tracker as _tracker_pin

        # F7: use tracker's canonical pin accessors instead of a second raw
        # json.loads/write_text implementation — that duplicate was non-atomic
        # (plain write_text, not tempfile+os.replace) and, on a corrupt read,
        # discarded ALL pins (not just the corrupted entry) before the renewal
        # write below overwrote the file, silently wiping every other method's
        # pin. tracker._get_strategy_pins() prunes per-entry and logs a warning
        # on a whole-file read failure instead of returning {} for everything.
        _pins = _tracker_pin._get_strategy_pins()
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
            if _directional_accuracy is not None and _directional_accuracy >= 0.70:
                _pins["ensemble"] = (datetime.now(UTC) + _td_pin(hours=168)).isoformat()
                _tracker_pin._save_strategy_pins(_pins)
                _log.info(
                    "cmd_cron: auto-renewed ensemble pin for 168 h "
                    "(directional_accuracy=%.2f)",
                    _directional_accuracy,
                )
            elif _directional_accuracy is None:
                _log.warning(
                    "cmd_cron: ensemble pin expiring but not enough recent multi-day "
                    "trades to evaluate directional accuracy — not auto-renewing"
                )
            else:
                _log.warning(
                    "cmd_cron: ensemble pin expiring but directional_accuracy=%.2f < 0.70 "
                    "— not auto-renewing; check model quality",
                    _directional_accuracy,
                )
    except Exception as _e:
        _log.warning("cmd_cron: ensemble pin auto-renew failed: %s", _e)

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

    log_path = CRON_LOG_PATH
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

    # get_gate_counts is still read after the scan (scan-summary block below);
    # reset_gate_counts is no longer called here -- run_trade_cycle() resets
    # the counters itself before its own analyze loop runs.
    from trade_cycle import TIER_STRONG, run_trade_cycle
    from weather_markets import get_gate_counts as _get_gate_counts

    # Subscribe+start the WebSocket at the same point in the cycle it ran at
    # pre-extraction -- right after the market fetch, before prewarm/the
    # analysis pool/placement -- via run_trade_cycle()'s on_markets_fetched
    # hook. Without this, WS subscribe/start couldn't happen until AFTER the
    # engine (which now owns the fetch) had already scanned, analyzed, AND
    # placed, leaving order_executor's flash-crash check (which prefers the
    # WS mid-price cache over a REST snapshot) running the entire cycle's
    # placement against a cache that was never populated.
    def _subscribe_and_start_ws(markets: list) -> None:
        if _ws is None:
            return
        try:
            ws_tickers = [t for m in markets if (t := m.get("ticker"))]
            if ws_tickers:
                _ws.subscribe(ws_tickers)
            _ws.start()
            global _active_ws
            _active_ws = _ws
            _log.info("WebSocket thread started with %d ticker(s)", len(ws_tickers))
        except Exception as _ws_exc:
            _log.debug("WebSocket start failed: %s", _ws_exc)

    result = run_trade_cycle(
        ctx,
        client,
        min_edge=min_edge,
        live=False,
        live_config=None,
        prewarm=True,
        effective_strong_edge=_effective_strong_edge,
        require_liquid_for_placement=False,
        # Fold in the anomaly-halt / black-swan-check-error reason (if either
        # fired above) so it still blocks placement inside the engine, not
        # just in this function's own (now-removed) copy of the gate.
        external_halted_reason=_cron_halted_reason,
        on_markets_fetched=_subscribe_and_start_ws,
        sameday_only=sameday_only,
    )
    if result is None:
        # Kill switch tripped inside run_trade_cycle() (e.g. activated
        # mid-scan or immediately before placement) — matches this
        # function's existing "kill switch -> hard abort" contract.
        return None

    # run_trade_cycle() now owns the fetch, so this can no longer print
    # before scanning starts -- reported here instead, right after the
    # engine returns (already past tense: the scan is done by now, not
    # merely starting). len(result.markets) is the pre-dedup raw fetch
    # count, matching the original's `scanned = len(markets)` before dedup.
    print(dim(f"  [cron] scanned {len(result.markets)} market(s)…"), flush=True)

    scanned = result.scanned
    _dbg = result.dbg
    signals_cache = result.signals_cache_entries
    strong_opps = result.strong_opps
    med_opps = result.med_opps
    _consistency_skip = result.consistency_skip

    # Per-signal cron.log JSONL write -- web_app.py's /api/signals endpoint
    # reads data/cron.log as JSONL for the live dashboard, so this is NOT
    # dead output. Reconstructed from signals_cache_entries (the same shape
    # the deleted per-market loop wrote) rather than raw market dicts, since
    # run_trade_cycle() doesn't expose per-market write hooks. Each entry's
    # own "ts" (the engine's per-market analysis-completion timestamp) is
    # used instead of a single timestamp computed once for this whole loop,
    # matching the pre-extraction per-market write's per-completion time.
    for _sig in signals_cache:
        if not _sig.get("passes_threshold"):
            continue
        _entry = {
            "ts": _sig.get("ts") or datetime.now(UTC).isoformat(),
            "ticker": _sig.get("ticker", ""),
            "signal": _sig.get("signal", ""),
            "net_edge": round(_sig.get("net_edge", 0.0), 4),
            "city": _sig.get("city", ""),
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(_entry) + "\n")

    if result.pre_settled:
        _pre_net = sum(t.get("pnl") or 0.0 for t in result.pre_settled)
        _pre_str = f"+${_pre_net:.2f}" if _pre_net >= 0 else f"-${abs(_pre_net):.2f}"
        print(
            green(
                f"  [PreSettle] {len(result.pre_settled)} trade(s) settled before scan — net P&L: {_pre_str}"
            )
        )

    # #perf: flush analysis attempts in one batch transaction (vs one INSERT per market)
    _analysis_batch: list[dict] = []
    for _enriched, _analysis in result.all_results:
        try:
            import datetime as _dt

            _td = _analysis.get("target_date") or _enriched.get("_target_date")
            if isinstance(_td, str):
                try:
                    _td = _dt.date.fromisoformat(_td)
                except ValueError:
                    _td = None
            _analysis_batch.append(
                {
                    "ticker": _enriched.get("ticker", ""),
                    "city": _enriched.get("_city"),
                    "condition": str(_analysis.get("condition", "")),
                    "target_date": _td,
                    "forecast_prob": _analysis.get("forecast_prob", 0.0),
                    "market_prob": _analysis.get("market_prob", 0.0),
                    "days_out": int(_analysis.get("days_out", 0)),
                    "was_traded": False,
                }
            )
        except Exception:
            pass

    try:
        from tracker import batch_log_analysis_attempts as _batch_log

        _batch_log(_analysis_batch)
    except Exception:
        pass

    # Write rich signals cache for the web dashboard. Skipped entirely for
    # --sameday-only (opus review, 2026-08-22): this file is a wholesale-
    # overwritten CURRENT-STATE snapshot (unlike cron.log's per-signal
    # append above, which is additive), and sameday_only's own market list
    # is a small subset by design -- overwriting it here would make the
    # dashboard silently drop every multi-day signal from the prior full
    # scan for however long until the next full scan runs, with no visual
    # indicator anything was truncated. Leaving the prior (full-scan) cache
    # in place is strictly safer than replacing it with a misleadingly
    # narrow one; the same-day signal itself is still fully visible via
    # cron.log, the console output, and any resulting paper trade.
    if not sameday_only:
        try:
            cache_path = SIGNALS_CACHE_PATH
            above_threshold = [
                s for s in signals_cache if s.get("passes_threshold", True)
            ]
            # backlog.txt "DASHBOARD STARS + WATCH-MODE STRONG ALERT KEY OFF
            # SIGNAL TEXT, NOT THE tier FIELD": read the authoritative `tier`
            # trade_cycle.py's classification loop set (now also carried on this
            # same signals_cache entry, see its "tier" key), not signal text --
            # this summary shares cache_payload with the "stars" field the same
            # fix converted, and must agree with it.
            strong = [s for s in above_threshold if s.get("tier") == TIER_STRONG]
            low_risk = [s for s in strong if s["time_risk"] == "LOW"]
            # Sort: above-threshold candidates first (by edge), then below-threshold (by edge).
            signals_cache.sort(
                key=lambda x: (not x.get("passes_threshold", True), -abs(x["edge_pct"]))
            )
            # Capture gate-level rejection counts so the dashboard can show a
            # filter-breakdown chart without needing any in-memory state from cron.
            _filter_gate_counts = result.gate_counts
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
    # Initialized before the try (round-2 opus review, AUD-0027): the live
    # block below reuses this list, and it must stay whatever it was
    # actually populated with even if an exception fires AFTER a successful
    # read_settlement_signals() call (e.g. paper.get_open_trades() itself
    # raising) -- resetting it to [] inside the except would silently
    # disable the live force-close for a cycle where real signals existed,
    # for a failure that has nothing to do with the live path.
    _settlement_sigs: list[dict] = []
    try:
        from settlement_monitor import read_settlement_signals

        # A settlement lag signal encodes a METAR-confirmed outcome fact
        # (the day's high/low has already cleared or missed a threshold),
        # not a time-decaying price edge -- it stays valid until that
        # market settles, so a generous staleness window doesn't risk
        # acting on stale reasoning. The default (120min) predates
        # settlement_monitor.py ever actually being scheduled to run: its
        # own daily task can now run up to ~5 hours (see cmd_schedule() in
        # main.py), and cron itself may run as infrequently as every 6
        # hours (cmd_schedule_cycles()'s 4x/day cadence) -- 120min would
        # silently drop a signal written early in that run before the next
        # cron cycle ever reads it. 720min (12h) comfortably covers the
        # longest run + longest cron gap while staying well under 24h, so
        # it can't reach into a prior trading day's now-irrelevant signals.
        _settlement_sigs = read_settlement_signals(max_age_minutes=720)
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

    # AUD-0027: live equivalent of the paper-only force-close block above --
    # that block matches _settlement_sigs against paper.get_open_trades()
    # only; grepping settlement_signal/read_settlement_signals usage across
    # order_executor.py/positions.py/main.py previously returned zero
    # matches, so a live position confirmed by the same METAR-verified
    # settlement-lag signal got zero automated early-close coverage. Mirrors
    # _check_live_model_exits' exact pattern (raw dict from
    # _get_live_open_positions(), _current_forecast_cycle() for the cycle
    # label, _exit_live_position for the real order) and reuses the SAME
    # _settlement_sigs list computed above rather than re-calling
    # read_settlement_signals.
    #
    # Exit price (round-2 opus review, AUD-0027): winning side uses the same
    # fixed 0.97 the paper block uses, as a LIMIT price on the live IOC
    # order -- genuinely opportunistic: it only fills if a buyer is already
    # offering close to full payout, and if not, the IOC simply doesn't fill
    # (see _exit_live_position's own "did not fill" handling), leaving the
    # position open and still protected by the stop-loss/breakeven/
    # model-exit scanners above and by real settlement -- a safe no-op, not
    # a bad fill. The LOSING side is NOT the mirror-image safe order a fixed
    # 0.03 might suggest: Kalshi's V2 API maps a low-price YES sell to an
    # aggressive "ask" that matches almost any resting bid (see
    # kalshi_client._to_v2_side_price), so it fills near-immediately
    # regardless of where the book actually is -- and _exit_live_position
    # books realized P&L against the LIMIT price passed in, not the real
    # exchange fill price, so a stale-but-nonzero book would silently
    # overstate the realized loss and feed a fabricated number into the
    # daily-loss-limit gate. Priced off the real current book instead
    # (positions.liquidation_price, with the same entry_price fallback on a
    # missing quote), mirroring _check_live_position_exits' own convention
    # exactly for this side.
    if client is not None and _settlement_sigs:
        try:
            from order_executor import (
                _current_forecast_cycle,
                _exit_live_position,
                _get_current_book,
                _get_live_open_positions,
            )
            from positions import liquidation_price as _liquidation_price
            from utils import YES_ASK_KEYS, YES_BID_KEYS, coalesce_market_price

            _live_open_by_ticker: dict[str, list[dict]] = {}
            for _lp in _get_live_open_positions():
                _live_open_by_ticker.setdefault(_lp["ticker"], []).append(_lp)
            if _live_open_by_ticker:
                _live_cycle = _current_forecast_cycle()
                for sig in _settlement_sigs:
                    _sig_ticker = sig["ticker"]
                    _sig_outcome = sig.get("outcome", "")
                    _sig_conf = sig.get("confidence", 0.0)
                    if _sig_conf < 0.80:
                        continue
                    # round-2 opus review: a signal with a missing/malformed
                    # outcome (not exactly "yes"/"no") must not silently
                    # fall through to the LOSING branch below and fire a
                    # real, marketable liquidation of a live position -- the
                    # paper block's equivalent shape only ever writes a fake
                    # ledger row, this one places a real order.
                    if _sig_outcome not in ("yes", "no"):
                        _log.warning(
                            "Settlement signal: skipping LIVE %s -- malformed "
                            "outcome %r",
                            _sig_ticker,
                            _sig_outcome,
                        )
                        continue
                    for _live_pos in _live_open_by_ticker.get(_sig_ticker, []):
                        # round-2 opus review: the whole per-position attempt
                        # (price computation included, not just the final
                        # _exit_live_position call) is now one try/except --
                        # coalesce_market_price can raise ValueError on a
                        # malformed book field, and that must only skip THIS
                        # position, not abort every remaining signal/position
                        # this cycle (mirrors _check_live_model_exits' own
                        # per-position try shape).
                        try:
                            _side = _live_pos.get("side", "yes")
                            _is_winning = (
                                _side == "yes" and _sig_outcome == "yes"
                            ) or (_side == "no" and _sig_outcome == "no")
                            _live_exit_price: float
                            if _is_winning:
                                _live_exit_price = 0.97
                            else:
                                _book = _get_current_book(client, _sig_ticker)
                                _current_prices = (
                                    {
                                        _sig_ticker: {
                                            "bid": coalesce_market_price(
                                                _book, *YES_BID_KEYS
                                            ),
                                            "ask": coalesce_market_price(
                                                _book, *YES_ASK_KEYS
                                            ),
                                        }
                                    }
                                    if _book
                                    else {}
                                )
                                _liq_price = _liquidation_price(
                                    _current_prices, _sig_ticker, _side
                                )
                                _live_exit_price = (
                                    _liq_price
                                    if _liq_price is not None
                                    else _live_pos["entry_price"]
                                )
                            if _exit_live_position(
                                client,
                                _live_pos,
                                _live_exit_price,
                                "settlement_lag",
                                _live_cycle,
                            ):
                                _log.info(
                                    "Settlement signal: closed LIVE %s early at "
                                    "%.2f (conf=%.0f%%, outcome=%s)",
                                    _sig_ticker,
                                    _live_exit_price,
                                    _sig_conf * 100,
                                    _sig_outcome,
                                )
                        except Exception as _lce:
                            _log.warning(
                                "Settlement signal: failed to close LIVE %s: %s",
                                _sig_ticker,
                                _lce,
                            )
        except Exception as _le:
            # round-2 opus review: this guards real live positions -- unlike
            # the paper block's matching DEBUG above, a systematic failure
            # here (e.g. every call raising ImportError) must be operator-
            # visible under default logging, not silently swallowed.
            _log.warning("cmd_cron: live settlement-lag force-close failed: %s", _le)

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
            f"prob_edge:{_dbg['prob_edge']} placement_gate:{_dbg['placement_gate']} "
            f"passed:{_dbg['passed']}"
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

    placed_count = result.placed_strong + result.placed_med
    # These banners announce an ATTEMPT to place, matching the original code's
    # placement (inside the "not halted, not paused, not consistency-skipped"
    # branch) -- strong_opps/med_opps are populated during analysis regardless
    # of halt state, so gate on the same tri-state the original branched on
    # or this would misleadingly announce placement that was actually skipped.
    _placement_was_attempted = (
        not result.halted_reason
        and not is_trading_paused()
        and not result.consistency_skip
    )
    if _placement_was_attempted and result.strong_opps:
        # Defensive fallback: strong_cap is only ever None when placement
        # was skipped or strong_opps was empty, both of which
        # _placement_was_attempted plus the `and result.strong_opps` guard
        # above already rule out -- but format defensively rather than let
        # a future change to that guard turn a skipped-placement edge case
        # into an unhandled TypeError here.
        # The cap is only meaningful for trades that actually got sized
        # against it -- appending "(cap=$X)" when nothing was placed reads
        # like a second, contradictory parenthetical bolted onto a skip
        # explanation that already ends in its own "(...)" .
        _strong_cap_suffix = (
            f" (cap=${(result.strong_cap or 0.0):.0f})"
            if result.placed_strong > 0
            else ""
        )
        print(
            bold(
                f"\n  !! {len(result.strong_opps)} STRONG SIGNAL(S) — "
                f"{_placement_outcome_phrase(result.placed_strong, len(result.strong_opps))}"
                f"{_strong_cap_suffix} !!"
            )
        )
    if _placement_was_attempted and result.med_opps:
        _med_cap_suffix = " (cap=$20)" if result.placed_med > 0 else ""
        print(
            bold(
                f"\n  !! {len(result.med_opps)} MED SIGNAL(S) — "
                f"{_placement_outcome_phrase(result.placed_med, len(result.med_opps))}"
                f"{_med_cap_suffix} !!"
            )
        )
    # shadow_logged_count is only ever nonzero when run_trade_cycle() took the
    # halted/paused branch (see its own trading_paused-or-halted_reason gate) --
    # equivalent to the original's `if _trading_paused or _cron_halted_reason:`
    # condition without needing that boolean here too.
    if result.shadow_logged_count > 0:
        print(
            dim(
                f"  [cron] Logged {result.shadow_logged_count} shadow prediction(s) while paused/halted "
                "(scoring stays current; no trades placed)."
            )
        )

    # Auto-settle any pending trades whose markets have resolved
    settled_count = result.synced_count
    if settled_count > 0:
        print(green(f"  [Settle] Recorded {settled_count} new outcome(s)."))

    # Settle resolved paper trades (marks paper.json won/lost to match tracker outcomes)
    _settled_trades = result.paper_settled
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
        _net_str = f"+${_net_pnl:.2f}" if _net_pnl >= 0 else f"-${abs(_net_pnl):.2f}"
        print(
            green(
                f"  [PaperSettle] {paper_settled_count} trade(s) settled — net P&L: {_net_str}"
            )
        )

    # F3: Auto-trigger calibration every 25 new settled trades, but only after
    # reaching 50 total. With fewer samples the grid search overfits to noise —
    # the minimum meaningful calibration sample is 50 predictions.
    try:
        import os as _os_cal

        if not _os_cal.environ.get("PYTEST_CURRENT_TEST"):
            _cal_sentinel = LAST_CALIBRATION_COUNT_PATH
            import tracker as _tracker_cal

            _current_settled = _tracker_cal.count_settled_predictions()
            _last_cal_count = 0
            if _cal_sentinel.exists():
                try:
                    _last_cal_count = int(_cal_sentinel.read_text().strip())
                except Exception:
                    pass
            _last_cal_count = _tracker_cal.clamp_last_calibration_count(
                _last_cal_count, _current_settled
            )
            if _current_settled >= 50 and _current_settled - _last_cal_count >= 25:
                _log.info(
                    "cmd_cron: F3 auto-calibration triggered "
                    "(%d settled since last run, threshold=25)",
                    _current_settled - _last_cal_count,
                )
                from calibration import calibrate_and_save as _cal_and_save

                _data_dir = DATA_DIR
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

    # Phase 7 — price-based stop-loss check before model-based early exits.
    # check_paper_position_exits() also runs from watch's automated loop --
    # position-protection unification follow-up (see backlog.txt's
    # [POSITION PROTECTION IS STILL TWO SEPARATE MECHANISMS...] entry) so a
    # paper position gets the same price-based protection regardless of
    # which pipeline happens to observe it.
    try:
        import paper as _paper_sl

        for _closed in _paper_sl.check_paper_position_exits(client):
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
        from monte_carlo import simulate_portfolio as _sim
        from paper import get_open_trades as _get_open

        _open = _get_open()
        if _open:
            # One simulation run for both figures — VaR (5th percentile) and
            # median P&L must come from the same sample, not two independent
            # runs at different sample sizes (found via a deep code review,
            # 2026-07-08: previously two separate calls could silently drift
            # to different n_simulations and report numbers with no shared
            # statistical basis).
            _sim_result = _sim(_open)
            _var = _sim_result["p5_pnl"]
            _exp = _sim_result.get("median_pnl")
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

    # Emergency-copy monitor -- backlog.txt "SAFE_IO -- NOTHING MONITORS
    # data/.emergency/ FOR REAL RECOVERY COPIES": atomic_write_json()'s
    # emergency-copy fallback (see the resolved SAFE_IO entry above; also
    # checks system temp, not just data/.emergency/) used to be visible only
    # via one buried ERROR log line at write time -- a log line alone
    # doesn't fix "an operator would only find out by grepping logs" during
    # a silent unattended cron run, so this also fires send_system_alert()
    # (same mechanism as the dead-man's-switch check above) with its own
    # distinct cooldown key so it can't silently suppress (or be suppressed
    # by) the unrelated dead-man's-switch alert sharing the same 6h window.
    # Opus-review-caught: every cron invocation -- manual or scheduled -- is
    # a fresh process, so notify's OLD in-process-only cooldown state used to
    # reset every time and did NOT actually prevent repeat-cycle spam across
    # separate invocations, only within main.py's long-lived `loop`/`watch
    # --auto` modes. That was a pre-existing limitation of send_system_alert()
    # shared by every one of its callers (not introduced here); fixed
    # 2026-07-31 via a disk-persisted cooldown (backlog.txt "NOTIFY.
    # SEND_SYSTEM_ALERT()'S COOLDOWN IS IN-PROCESS MEMORY ONLY"), so this now
    # actually suppresses repeats across manual re-runs and any future
    # scheduled task alike. A real copy here means some write already failed
    # and raised
    # AtomicWriteError -- this doesn't retry or clear it, only surfaces it
    # every cycle until an operator manually recovers the file and deletes
    # it.
    try:
        import os as _os_emrg

        if not _os_emrg.environ.get("PYTEST_CURRENT_TEST"):
            import safe_io as _safe_io_emrg

            _emergency_copies = _safe_io_emrg.check_emergency_copies()
            if _emergency_copies:
                _details = [
                    f"{c['filename']} (mtime={c['mtime']}, {c['size_bytes']}B, {c['path']})"
                    for c in _emergency_copies
                ]
                _log.error(
                    "%d real emergency-copy recovery file(s) need manual attention: %s",
                    len(_emergency_copies),
                    _details,
                )
                from notify import send_system_alert as _emrg_alert

                _emrg_alert(
                    "Kalshi bot — emergency recovery copy needs attention",
                    f"{len(_emergency_copies)} file(s) need manual recovery: "
                    + "; ".join(_details),
                    cooldown_key="emergency_copy",
                )
                print(
                    red(
                        f"  [EmergencyCopy] {len(_emergency_copies)} file(s) need "
                        "manual recovery -- see log for names/mtimes/paths."
                    )
                )
    except Exception as _e:
        _log.debug("cmd_cron: emergency-copy check failed: %s", _e)

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
        _grad_flag = GRADUATED_FLAG_PATH
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
    _LAST_ML_RETRAIN_PATH = LAST_ML_RETRAIN_PATH
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

                # METAR lock-in calibration -- same weekly cadence as T-scaling/
                # blend weights above (2026-08-16: previously manual-only via
                # `py main.py calibrate`, which meant it went stale indefinitely
                # if nobody remembered to run it). fit_and_save_metar_
                # calibration() already has its own EPV-based data floor
                # (min(n_pos,n_neg)>=10) and refuses to save an unreliable fit,
                # so folding it into this unconditional weekly block can't
                # cause a premature activation the way it could for a method
                # without that floor (e.g. EMOS, which got its own explicit
                # confirmation gate for exactly that reason -- METAR's floor
                # check already provides the equivalent protection here).
                from ml_bias import fit_and_save_metar_calibration as _fit_save_metar

                _metar_cal = _fit_save_metar()
                if _metar_cal is not None:
                    _mc_a, _mc_b, _mc_c = _metar_cal
                    print(
                        dim(
                            f"  [MetarCal] fitted — a={_mc_a:.4f} b={_mc_b:.4f} c={_mc_c:.4f}"
                        )
                    )
    except Exception as _e:
        # Bumped from debug to warning: the marker is always touched below
        # (deliberately, to avoid a tight retry loop), so a persistent failure
        # here would otherwise silently stop retraining for good with zero
        # visible trace — a DEBUG line 6 days apart is effectively invisible.
        _log.warning("cmd_cron: ML bias retrain failed: %s", _e)
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
    _WEIGHTS_GATE_PATH = LAST_WEIGHTS_REFRESH_PATH
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
    _LAST_SWEEP_PATH = LAST_PARAM_SWEEP_PATH
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

    # G6: Weekly — re-run the walk-forward backtest so walk_forward_params.json's
    # optimal_min_edge (config.py's highest-priority soft override for
    # PAPER_MIN_EDGE, above the param sweep) doesn't go stale indefinitely.
    # Previously this only updated when someone manually ran `py main.py
    # walk-forward`/`wfbt` — found 2026-07-05 sitting 11 days stale with no
    # automated refresh, unlike the param sweep above it in this same function.
    # Same marker-file gate pattern as the sweep, same 7-day cadence.
    _LAST_WF_PATH = LAST_WALK_FORWARD_PATH
    try:
        import os as _os_wf

        if not _os_wf.environ.get("PYTEST_CURRENT_TEST"):
            _should_wf = True
            if _LAST_WF_PATH.exists():
                _wf_days_since = (
                    datetime.now(UTC).timestamp() - _LAST_WF_PATH.stat().st_mtime
                ) / 86400
                _should_wf = _wf_days_since >= 7
            if _should_wf:
                _log.info(
                    "cmd_cron: running weekly walk-forward backtest (>=7 days since last)"
                )
                from backtest import run_paper_walk_forward as _run_wf

                try:
                    _wf_result = _run_wf()
                    if _wf_result:
                        print(
                            dim(
                                "  [WalkForward] Weekly walk-forward complete — "
                                f"optimal_min_edge={_wf_result.get('optimal_min_edge')}."
                            )
                        )
                except Exception as _wf_err:
                    _log.warning("cmd_cron: weekly walk-forward failed: %s", _wf_err)

                # Always touch marker after attempting so the gate closes correctly
                # even when there's not yet enough paper-trade history (<50 trades).
                _LAST_WF_PATH.parent.mkdir(exist_ok=True)
                _LAST_WF_PATH.touch()
    except Exception as _e:
        # Bumped from debug to warning \u2014 an exception here (e.g. an import
        # failure of the backtest module) hits this outer handler before the
        # marker gets touched, so a persistent failure silently freezes
        # optimal_min_edge (config.py's PAPER_MIN_EDGE override, which gates
        # real trade placement) at its stale value with zero visible trace.
        _log.warning("cmd_cron: weekly walk-forward check failed: %s", _e)

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
        _log.warning("ensemble cache flush failed: %s", _e)

    # Same rationale as the ensemble flush above \u2014 the forecast disk cache
    # used per-entry daemon threads (unreliable at process exit) until this
    # was migrated to the same accumulate-then-batch-flush pattern.
    try:
        from weather_markets import flush_forecast_disk_cache as _flush_forecast

        _flushed_fc = _flush_forecast()
        if _flushed_fc:
            print(
                dim(f"  [cron] forecast cache: {_flushed_fc} entries saved to disk"),
                flush=True,
            )
    except Exception as _e:
        _log.warning("forecast cache flush failed: %s", _e)

    # Sync data/ to cloud (OneDrive / Google Drive / custom path) after every cron run
    try:
        from cloud_backup import backup_data as _backup

        _backup()
    except Exception as _backup_exc:
        # Was a bare `except: pass` — a persistent backup failure could go
        # unnoticed for months with zero trace anywhere. Never crash the
        # scheduler over it, but at least log it.
        _log.warning("cmd_cron: cloud backup failed: %s", _backup_exc)

    # Kalshi series drift detection — once per day, observational only. Placed
    # last (after settlement, scanning, and trade placement all complete) so a
    # slow/retrying Kalshi API call can never delay anything trading-critical
    # (found the original stale-ticker bug via manual investigation; this
    # catches the next one automatically).
    try:
        from weather_markets import check_series_drift as _check_series_drift

        _check_series_drift(client)
    except Exception as _drift_exc:
        _log.warning("check_series_drift call failed: %s", _drift_exc)

    # Hourly-directional target-hour cache refresh — once per city per day,
    # same placement/isolation rationale as check_series_drift above
    # (backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step 2). Feeds
    # weather_markets.get_hourly_target_hour_role(), which gates the real
    # hourly probability model in analyze_trade().
    try:
        from weather_markets import (
            refresh_hourly_target_hours as _refresh_hourly_target_hours,
        )

        _refresh_hourly_target_hours(client)
    except Exception as _hourly_target_exc:
        _log.warning("refresh_hourly_target_hours call failed: %s", _hourly_target_exc)

    # Hurricane season-count current-to-date cache refresh — once per basin
    # per day, same placement/isolation rationale as check_series_drift/
    # refresh_hourly_target_hours above (backlog.txt "HURRICANE MARKETS" --
    # season-count model). Feeds weather_markets._get_cached_hurricane_count_
    # to_date, which tilts the real probability model in analyze_trade().
    try:
        from weather_markets import (
            refresh_hurricane_count_to_date as _refresh_hurricane_count_to_date,
        )

        _refresh_hurricane_count_to_date(client)
    except Exception as _hurricane_count_exc:
        _log.warning(
            "refresh_hurricane_count_to_date call failed: %s", _hurricane_count_exc
        )

    # Per-city registry completeness manifest — once per day, observational
    # only, same placement/isolation rationale as check_series_drift above
    # (backlog.txt "PER-CITY KNOWLEDGE SCATTERED ACROSS ~8 REGISTRIES").
    # No API call involved (pure local data comparison), but self-gated to
    # once per day the same way anyway to avoid log noise every cycle.
    try:
        from weather_markets import log_city_registry_report as _log_city_registry

        _log_city_registry()
    except Exception as _registry_exc:
        _log.warning("log_city_registry_report call failed: %s", _registry_exc)

    # Auto-unretirement probation check — once per day, observational only,
    # same placement/isolation rationale as check_series_drift/
    # log_city_registry_report above (backlog.txt "AUTO UN-RETIREMENT").
    # Generates fresh post-retirement evidence for any currently-retired
    # forecasting method via analyze_trade(bypass_retirement_check=True), and
    # auto-unretires once that evidence clears the threshold. No-ops
    # immediately if nothing is currently retired.
    try:
        from weather_markets import check_retirement_probation as _check_probation

        _check_probation(client)
    except Exception as _probation_exc:
        _log.warning("check_retirement_probation call failed: %s", _probation_exc)

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


def _install_cron_watchdog(timeout_secs: int = 720) -> threading.Event:
    """Start a daemon thread that hard-kills the process if cron hangs > timeout_secs.

    Used because signal.SIGALRM is unavailable on Windows.  The thread is
    daemonised so it dies automatically when the main thread exits normally.
    Adjust timeout_secs via env var CRON_WATCHDOG_SECS (default 8 min).

    Returns a completion Event — the caller must .set() it once the cron cycle
    finishes. Without this, main.py's `loop` command (which calls cmd_cron
    in-process and then sleeps for hours between cycles) would have this
    watchdog thread outlive the cycle it was guarding and force-kill the
    whole idling process partway through the sleep.
    """
    _wdog_secs = int(os.getenv("CRON_WATCHDOG_SECS", str(timeout_secs)))
    _done_event = threading.Event()

    def _watchdog() -> None:
        # wait() returns True the moment the caller signals completion —
        # only a genuine hang lets this fall through to the timeout.
        if _done_event.wait(timeout=_wdog_secs):
            return
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

    _wdog_thread = threading.Thread(target=_watchdog, name="cron-watchdog", daemon=True)
    _wdog_thread.start()
    _log.debug("cron watchdog armed: %ds", _wdog_secs)
    return _done_event


def cmd_cron(
    ctx: CronContext,
    client: KalshiClient,
    min_edge: float | None = None,
    sameday_only: bool = False,
) -> None:
    """Silent background scan — writes to data/cron.log, auto-places strong paper trades.

    ``sameday_only``: see trade_cycle.run_trade_cycle()'s own docstring. Default False.
    """
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
    # The returned event MUST be set before this function returns via any path
    # (including sys.exit()) — otherwise, in main.py's `loop` command, this
    # watchdog thread outlives the cycle it was guarding and force-kills the
    # whole process during the idle sleep between cycles.
    _cron_done_event = _install_cron_watchdog()
    try:
        if not ctx.acquire_cron_lock():
            _log.warning("cmd_cron: could not acquire lock — skipping this run")
            if not getattr(cmd_cron, "_called_from_loop", False):
                _sys.exit(1)
            return

        _full_scan = False
        try:
            _full_scan = bool(
                _cmd_cron_body(ctx, client, min_edge, sameday_only=sameday_only)
            )
        except KeyboardInterrupt:
            print()
            _log.warning("cmd_cron: interrupted by user")
        finally:
            global _active_ws
            if _active_ws is not None:
                try:
                    _active_ws.stop()
                except Exception as _ws_stop_exc:
                    _log.debug("cmd_cron: WS stop failed: %s", _ws_stop_exc)
                _active_ws = None
            ctx.clear_cron_running_flag()
            try:
                _last_run_path = CRON_LAST_RUN_PATH
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
                _hb_path = CRON_HEARTBEAT_PATH
                try:
                    _hb_prev = (
                        json.loads(_hb_path.read_text()) if _hb_path.exists() else {}
                    )
                except Exception:
                    _hb_prev = {}
                _cycle = _hb_prev.get("cycle_count", 0) + 1
                # opus review (2026-08-22): a --sameday-only run must NOT
                # advance last_full_scan -- it skips the multi-day scan this
                # marker exists to track freshness of. Carry the prior value
                # forward (falling back to _now_iso only when no prior
                # heartbeat exists at all, i.e. this repo's very first cron
                # run ever) so main._check_cron_staleness()'s full-scan
                # warning stays meaningful across a run of sameday-only
                # cycles instead of being silently refreshed by them.
                if sameday_only:
                    _last_full_scan = _hb_prev.get("last_full_scan", _now_iso)
                else:
                    _last_full_scan = _now_iso
                _hb_path.write_text(
                    json.dumps(
                        {
                            "last_run": _now_iso,
                            "cycle_count": _cycle,
                            "last_full_scan": _last_full_scan,
                        }
                    )
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
    finally:
        _cron_done_event.set()
