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
    FEE_CHECK_PATH,
    FEE_SCHEDULE_SCRAPE_PATH,
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
    from trade_cycle import TradeCycleResult

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


def _is_monday_utc() -> bool:
    """True when it is Monday in UTC — the gate on the weekly DB sweep.

    Was `_date.today().weekday() == 0` (0ad8685c) until 96273434
    ("P2-18/P2-25 -- replace date.today() with utc_today() across hot
    path") moved it onto the one canonical clock the rest of that hot path
    uses. The reason is determinism, not any downstream comparison: which
    weekday a host thinks it is decides whether a week's retention sweep
    happens at all, and a local-clock answer makes that depend on where the
    machine is and on DST. (The 7-day marker-file check just below is NOT
    part of that reason -- it compares epoch seconds on both sides and is
    timezone-independent by construction.)

    Extracted from _cmd_cron_body by batch-86 so the claim is testable at
    all. The test named for it
    (tests/test_phase2_batch_h.py::test_monday_check_uses_utc_weekday) had
    been asserting only `date(2026, 6, 1).weekday() == 0` -- a fact about
    the standard library -- followed by `pass`, so nothing would have
    noticed the gate reverting to local time.

    Note for anyone tempted to re-inline this: nothing would notice. This
    module is NOT in tests/test_dead_code_scan.py's `_TARGET_FILES`
    (paper.py, tracker.py, weather_markets.py -- cron.py is only ever read
    there as a *caller* corpus), so an orphaned function here is invisible
    to it. That is why the unit test asserts the call site's own source
    contains `_is_monday_utc()` rather than relying on the scan.
    """
    from utils import utc_today as _utc_today

    return _utc_today().weekday() == 0


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

# Only used by _acquire_cron_lock's no-psutil fallback (unchanged from
# before the create_time-aware check below was added). Deliberately NOT
# used as a general age-based override when psutil IS available -- an
# earlier version of this fix added a 1800s override to that branch,
# reasoning that cron's own internal watchdog (_install_cron_watchdog, 720s
# default) bounds how old a genuinely-running cron process's lock can get.
# That reasoning doesn't hold at 1800s specifically: `cmd_watch`
# (`watch --auto --live`, main.py) also acquires this SAME lock, across one
# run_trade_cycle() per auto-trade cycle, with NO watchdog at all -- a
# session that legitimately runs for a while (well under 1800s per cycle,
# but the OVERALL watch session has no such bound) could plausibly still be
# mid-cycle at 1800s, so an override at that threshold could steal the lock
# from a still-running, still-placing-real-orders watch cycle and let a
# second cron cycle start concurrently -- opus-review-caught before ship.
# See _STUCK_RUNNING_BACKSTOP_SECS below for the much longer (24h) backstop
# that IS safe to apply even to the psutil-available branch, since neither
# cmd_cron nor a single cmd_watch cycle can plausibly reach that age.
_STALE_LOCK_AGE_SECS = 1800

# Shared self-heal backstop for both _acquire_cron_lock's psutil-available
# branch and _is_cron_running: once a lock is this old, override/report-not-
# running regardless of what pid_exists()/_cron_lock_pid_reused conclude --
# neither cmd_cron (bounded by _install_cron_watchdog, 720s default) nor a
# single cmd_watch auto-trade cycle (acquires/releases the lock once per
# cycle, main.py:3923/3949) can plausibly hold this lock anywhere near 24h,
# so a lock this old cannot be a genuine holder no matter how inconclusive
# _cron_lock_pid_reused's own verdict is (e.g. AccessDenied querying a
# reassigned PID -- opus-review-caught: without this, EITHER function could
# get stuck on that specific case forever, reproducing the exact permanent-
# lock-out failure mode this whole batch exists to eliminate).
_STUCK_RUNNING_BACKSTOP_SECS = 86400


def _cron_lock_pid_reused(pid: int, lock_create_time: float | None) -> bool:
    """Return True only when `pid` is POSITIVELY confirmed to be a different
    OS process than the one that originally wrote `lock_create_time` into
    the lock file -- i.e. Windows reused a low-numbered PID for an unrelated
    process after the real cron holder already exited.

    Returns False when this can't be positively confirmed (no create_time
    recorded in the lock -- an old-format lock predating this field -- or
    the process vanished, or querying it raised for any other reason, e.g.
    AccessDenied for a protected process that reused the PID). False here
    means "not disproven", NOT "proven alive" -- callers must still gate on
    pid_exists() themselves. The broad `except Exception` is deliberate
    (opus-review-caught): this function's two web_app.py callers
    (api_run_cron, api_cron_status, via _is_cron_running) have no try/except
    of their own around it, so an unguarded psutil.Error here would become
    an unhandled 500 instead of the safe "can't confirm" default.

    Platform note (opus-review-caught, forward-looking for the VM move --
    this codebase currently only deploys on Windows, same assumption
    safe_io.CrossProcessLock's own docstring already documents): on Windows,
    psutil's create_time() reads GetProcessTimes, an absolute value stamped
    at process creation and stable across the process's life. On Linux,
    psutil instead derives it from boot_time() + /proc/[pid]/stat's
    starttime, and boot_time() itself is *recomputed* from `/proc/stat`'s
    `btime` on every call -- a wall-clock step (e.g. an NTP correction
    shortly after boot) can shift a still-running process's OWN reported
    create_time between two reads, which would make this function
    misreport a genuinely-alive holder as "reused". Not a live risk today;
    revisit this specific assumption before the VM move if its target
    platform ends up being Linux rather than Windows.
    """
    if lock_create_time is None:
        return False
    try:
        # The comparison lives INSIDE this try (opus-review-caught, round 2):
        # a malformed lock_create_time (e.g. a hand-edited or corrupted
        # data/cron.lock with a non-numeric "create_time" field) would raise
        # TypeError on the subtraction below -- if that happened outside the
        # try it would propagate unhandled to this function's two unguarded
        # web_app.py callers (via _is_cron_running), exactly the 500 this
        # function's broad except already exists to prevent for every OTHER
        # failure shape.
        actual_create_time = _psutil.Process(pid).create_time()
        # A genuinely reused PID's create_time differs by seconds-to-hours,
        # never sub-second -- 2.0s is well clear of any clock-rounding noise.
        return abs(float(actual_create_time) - float(lock_create_time)) >= 2.0
    except Exception:
        return False


def _acquire_cron_lock() -> bool:
    """
    Try to acquire the cron file lock. Fail CLOSED on every error.

    Returns True only when the lock is cleanly written by this process.
    Returns False in every other case — including I/O errors — so a
    concurrent cron run is never allowed through on an unexpected failure.

    Stale detection is PID-aware when psutil is available:
    - Live PID, matching create_time → block (another instance is really
      running) UNLESS the lock has outlived _STUCK_RUNNING_BACKSTOP_SECS
      (24h) -- see that constant's own comment for why this is safe.
    - Live PID, but create_time doesn't match the lock's recorded value →
      Windows reused the PID for an unrelated process; override immediately.
    - Dead PID → override (process is gone, lock is stale).
    - No psutil → conservative _STALE_LOCK_AGE_SECS age threshold before
      overriding (unchanged from before this create_time-aware check; see
      that constant's own comment for why this fallback is NOT mirrored
      into the psutil-available branch above).

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
            # batch-33 L-6b: default to the lock FILE's own mtime, not 0
            # (the epoch, ~56 years old) and not a fresh _time.time() call
            # (opus-review-caught: that recomputes "now" on every read, so
            # a file permanently missing started_at would report age ~0
            # FOREVER -- the 24h self-heal backstop could then never fire
            # for it, a permanent lockout with no escape, reproduced live:
            # "lock held by live PID N (started 0s ago) -- skipping" on
            # every single acquire attempt). A valid-JSON lock file missing
            # the started_at key (old format, hand-edited) used to default
            # to 0 and let the 24h self-heal backstop override even a LIVE,
            # confirmed-not-reused holder -- mtime is a real, monotonically
            # aging signal instead: fresh for a lock another process just
            # wrote (fail closed, matching the original intent), but still
            # eventually crosses the backstop threshold for a genuinely
            # stuck/abandoned one. Same fallback web_app.py's own
            # os.path.getmtime(LOCK_PATH) already uses for this exact file.
            try:
                _default_started = lp.stat().st_mtime
            except OSError:
                _default_started = _time.time()
            started_at = _default_started
            lock_create_time = None
            try:
                existing = json.loads(lp.read_text())
                pid = existing.get("pid")
                started_at = existing.get("started_at", _default_started)
                lock_create_time = existing.get("create_time")
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
                if _psutil.pid_exists(pid) and not _cron_lock_pid_reused(
                    pid, lock_create_time
                ):
                    age = _time.time() - started_at
                    if age < _STUCK_RUNNING_BACKSTOP_SECS:
                        _log.warning(
                            "cmd_cron: lock held by live PID %d (started %.0fs ago) — skipping",
                            pid,
                            age,
                        )
                        return False
                    # opus-review-caught (round 2, F2): without this, a lock
                    # whose reuse can never be positively confirmed (e.g.
                    # persistent AccessDenied querying the holding PID) would
                    # block cron forever with no self-heal -- the exact
                    # permanent-lock-out failure mode this batch exists to
                    # eliminate. Safe at this age specifically: see
                    # _STUCK_RUNNING_BACKSTOP_SECS's own comment for why
                    # neither cmd_cron nor cmd_watch can reach it genuinely.
                    _log.warning(
                        "cmd_cron: overriding lock for PID %d — age %.0fs exceeds "
                        "the %ds self-heal backstop even though reuse couldn't be "
                        "positively confirmed",
                        pid,
                        age,
                        _STUCK_RUNNING_BACKSTOP_SECS,
                    )
                else:
                    # PID is gone, or was reused by an unrelated process — stale.
                    _log.warning(
                        "cmd_cron: overriding stale lock (PID %d dead or reused by "
                        "a different process)",
                        pid,
                    )
            else:
                # psutil unavailable — use conservative lock age.
                # batch-33 L-6a: this used to read a `heartbeat` field that
                # was written ONCE at acquire time and never refreshed
                # again -- a heartbeat implies periodic liveness, but this
                # was really just a second copy of started_at. Genuinely
                # refreshing it mid-hold would need a background thread
                # (there's no natural sub-cycle checkpoint deep inside a
                # single hung network call to hook a real refresh off of),
                # disproportionate machinery for what this field actually
                # needs to answer -- "how old is this lock" -- so the field
                # is removed and this reads started_at directly instead of
                # keeping a redundant, misleadingly-named duplicate.
                age = _time.time() - started_at
                if age < _STALE_LOCK_AGE_SECS:
                    _log.warning(
                        "cmd_cron: lock age %.0fs < %ds; refusing to override without psutil",
                        age,
                        _STALE_LOCK_AGE_SECS,
                    )
                    return False
                _log.warning(
                    "cmd_cron: overriding stale lock (%.0fs old, psutil unavailable)",
                    age,
                )

        lp.parent.mkdir(exist_ok=True)
        # batch-33 L-6a: no "heartbeat" field -- it duplicated started_at
        # at write time and was never refreshed again, so it never carried
        # any information started_at didn't already have (see the
        # no-psutil fallback's own comment above).
        lock_data = {
            "pid": os.getpid(),
            "started_at": _time.time(),
        }
        if _PSUTIL_AVAILABLE:
            try:
                # float() so a malformed/mocked return value fails INSIDE
                # this best-effort block rather than reaching the
                # json.dumps() below unguarded and aborting the whole
                # acquire over a field that's allowed to just be absent.
                lock_data["create_time"] = float(
                    _psutil.Process(os.getpid()).create_time()
                )
            except Exception:
                pass  # best-effort — an old-format lock without this field
                # still gets the pre-existing pid_exists()-only protection.
        # batch-33 L-6c: route through safe_io's atomic write (temp file +
        # fsync + Windows-retry-safe rename) instead of a bare write_text()
        # -- this was the one non-atomic write left on the cron-lock path.
        # emergency_copy=False: a lock file is trivially reconstructible
        # (worst case, a fresh acquire just writes a new one) and not worth
        # the .emergency/ monitor re-alerting on, same reasoning
        # alerts.check_halt_transition already uses for its own small,
        # disposable state file.
        from safe_io import atomic_write_json

        atomic_write_json(lock_data, lp, emergency_copy=False)
        return True

    except Exception as exc:
        _log.error(
            "cmd_cron: lock acquisition failed: %s — aborting (fail-closed)", exc
        )
        return False  # FAIL CLOSED — never proceed on unexpected error
    finally:
        _mutex.release()


def _release_cron_lock() -> None:
    """Delete the cron lock file -- but ONLY if this process is still the
    one that owns it.

    AUD-0006 followup (opus review): the acquire-side mutex only serializes
    _acquire_cron_lock's own check-then-write body -- without also taking it
    here, another process's acquire() could observe lp.exists() == True
    (under ITS mutex hold) and then have this unlink() race its own
    lp.read_text() a moment later, turning a perfectly free lock into a
    spurious "unreadable lock file" fail-closed skip. Best-effort: still
    attempts the unlink even if the mutex itself can't be acquired within
    its timeout (never let the locking mechanism block releasing the real
    lock -- leaving the lock file behind would be worse than a narrow race).

    H2 (opus-review-caught): a bare unconditional unlink() would also delete
    a DIFFERENT process's lock once one exists to override -- e.g. process A
    holds the lock past _STALE_LOCK_AGE_SECS (no-psutil fallback), process B
    overrides it and starts running, and A's own delayed `finally` then
    unlinks B's fresh lock, leaving B completely unprotected and letting a
    THIRD acquirer start concurrently. The ownership check below (still
    inside the same mutex hold, so no new torn-read risk) makes release a
    no-op whenever the lock currently on disk isn't this process's own.
    """
    from safe_io import CrossProcessLock

    lp = LOCK_PATH
    _mutex = CrossProcessLock(lp.with_name(lp.name + ".mutex"), timeout=5.0)
    _mutex.acquire()
    try:
        try:
            owner_pid = json.loads(lp.read_text()).get("pid")
        except FileNotFoundError:
            return  # already gone -- nothing to release
        except Exception as _read_exc:
            # batch-33 M-3: a torn/empty/PermissionError read used to
            # default owner_pid=None, which the OLD `owner_pid is not None
            # and owner_pid != os.getpid()` guard treated as "no owner to
            # protect" and fell through to unlink() -- deleting a possibly
            # FRESH lock another process just wrote, the exact H2 scenario
            # this whole ownership check exists to prevent. Fail closed
            # instead: skip the unlink whenever ownership can't be
            # positively verified, matching batch-30's own acquire-side
            # "can't confirm -> don't act" reasoning.
            _log.warning(
                "cmd_cron: could not verify lock ownership before release "
                "(%s) -- skipping unlink (fail closed) rather than risk "
                "deleting a lock another process just wrote",
                _read_exc,
            )
            return
        if owner_pid != os.getpid():
            _log.warning(
                "cmd_cron: not releasing lock -- currently held by PID %s, "
                "not this process (%d); an earlier acquire must have "
                "already overridden it as stale",
                owner_pid,
                os.getpid(),
            )
            return
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

    Shares _cron_lock_pid_reused AND _STUCK_RUNNING_BACKSTOP_SECS with
    _acquire_cron_lock (see that constant's own comment) so a Windows
    PID-reuse situation doesn't make this report "running" forever the way
    a bare pid_exists() check would, and an inconclusive reuse verdict
    (e.g. AccessDenied querying a reassigned PID) doesn't either. Applies
    the backstop unconditionally once PID reuse is ruled out -- not only in
    the inconclusive case -- since a genuinely still-running holder can
    never legitimately reach that age either (see the constant's comment);
    keeping the check unconditional here is simpler than branching on why
    reuse couldn't be confirmed. Deliberately does NOT apply
    _STALE_LOCK_AGE_SECS (1800s, `_acquire_cron_lock`'s no-psutil-only
    threshold) -- this is a passive display/rate-limit check for callers
    (the web dashboard's /api/run_cron and /api/cron_status, main.py's EMOS
    activate/deactivate) that don't need or want an ordinary long-running
    session to start reading as "not running" just because it's been up
    for a while.
    """
    import time as _time

    lp = LOCK_PATH
    if not lp.exists():
        return False
    try:
        existing = json.loads(lp.read_text())
        pid = existing.get("pid")
        # batch-33 L-6b: default to the lock FILE's own mtime, not 0 (the
        # epoch) and not a fresh _time.time() call -- see
        # _acquire_cron_lock's identical fix/comment for why a
        # recompute-every-read default would permanently pin this at
        # age-0 instead of actually aging.
        try:
            _default_started = lp.stat().st_mtime
        except OSError:
            _default_started = _time.time()
        started_at = existing.get("started_at", _default_started)
        lock_create_time = existing.get("create_time")
    except Exception:
        return False  # unreadable lock — treat as not running

    if pid and _PSUTIL_AVAILABLE:
        if not _psutil.pid_exists(pid):
            return False
        if _cron_lock_pid_reused(pid, lock_create_time):
            return False
        # Round-2 opus review (M2-11): this is the branch that actually runs
        # (psutil is a hard requirement, requirements.txt) -- same pairing
        # the no-psutil branch's comment below documents, but with a much
        # longer window: after a watchdog os._exit() with PID reuse ruled
        # out, this reports "running" for up to _STUCK_RUNNING_BACKSTOP_SECS
        # (86400s = 24h), which would suppress cmd_cron's stale-.tmp
        # self-heal for that same window. Safe for the identical reason --
        # _acquire_cron_lock (~line 358) checks the SAME predicate against
        # the SAME constant, so cron can't actually run in that window
        # either, meaning a temporarily-"lost" kill switch can't let a
        # trade through. This is the window an operator would actually hit
        # in practice (not the no-psutil fallback below).
        return (_time.time() - started_at) < _STUCK_RUNNING_BACKSTOP_SECS
    # psutil unavailable — treat as running only if the lock is recent
    #
    # batch-32 opus review (L-D): after a watchdog os._exit(), BOTH the lock
    # file and main.py cmd_cron's .kill_switch.tmp are orphaned together --
    # this branch reports "running" for up to _STALE_LOCK_AGE_SECS (1800s)
    # past the crash, which would suppress cmd_cron's stale-.tmp self-heal
    # for that same window. This is safe ONLY because _acquire_cron_lock
    # (this file, no-psutil branch) uses the SAME `started_at` field (was
    # `heartbeat` before batch-33 L-6a removed that redundant duplicate
    # field) and the SAME 1800s constant to decide staleness -- cron can't
    # actually run in that window either, so the temporarily-"lost" kill
    # switch can't let a trade through. If either threshold/field is ever
    # changed independently of the other, this pairing breaks silently.
    # psutil is a hard requirement (requirements.txt) so this whole branch
    # is rare in practice.
    return (_time.time() - started_at) < _STALE_LOCK_AGE_SECS


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
    # batch-33 L-6d: this function's 3 date.today() calls were the only
    # naive-local-time sites left in this file -- every other date
    # comparison in cron.py already goes through utils.utc_today() (see
    # e.g. the Monday-sweep check above). A local date can disagree with
    # UTC around midnight in either direction, letting the "once per day"
    # gate fire twice (or skip a day) right at the boundary.
    from utils import utc_today as _utc_today

    _today = _utc_today()
    if _today < _PROD_REMINDER_DATE:
        return
    try:
        if PROD_REMINDER_PATH.exists():
            last = PROD_REMINDER_PATH.read_text().strip()
            if last == str(_today):
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
        PROD_REMINDER_PATH.write_text(str(_today))
    except Exception as _exc:
        _log.debug("_check_prod_reminder failed: %s", _exc)


# Batch-49 item 1: fee-change monitor. Resolved background (do NOT
# re-investigate): the 7.7.26 fee schedule PDF was read directly on
# 2026-08-24 -- weather series pay $0 maker (maker multiplier defaults to
# 0; no weather/climate series in the Non-Standard Fees table). This bot's
# KALSHI_MAKER_FEE_RATE=0/kalshi_fee_rate=0.07 are both confirmed correct
# against that PDF. What this guards against: Kalshi adding a per-series
# maker fee with a single table row, silently invalidating that assumption.
# May never fire -- kept deliberately small (one cron task, one alert, no
# config surface) per the dossier's own "why-not honesty" note.
def _check_fee_change(client) -> None:
    """Once per day: assert every non-taker (maker) fill's fee_cost is $0.

    Checks every maker fill in the account, not filtered to a specific
    series list -- this bot only maker-trades weather/climate series in
    practice, and narrowing the ticker match would risk missing exactly
    the kind of newly-added series this guard exists to catch (same
    reasoning check_series_drift documents for its own ticker matching).

    Covers roughly the trailing day via min_ts (a fixed look-back window,
    not a persisted last-checked cursor) -- deliberately not a second piece
    of persisted state for what's meant to stay a small, forward-only
    guard. This assumes the gap between consecutive runs stays under 25h;
    the gate is "first run of a new UTC date," not "24h since the last
    run," so a host that isn't always-on (this bot's still-pending VM move)
    could in principle leave a gap wider than the window and miss fills
    that occur entirely inside it. Low practical impact -- a real fee
    change is persistent, so the NEXT successful run still catches it --
    but noted here rather than silently assumed away.

    Uses alerts.check_halt_transition (the same false->true edge-tracking
    mechanism batch-24/batch-33 built for risk halts) so a nonzero fee
    alerts once when detected, not every day it stays detected -- this
    isn't itself a halt/pause of anything, just reusing the same "don't
    re-alert on unchanged state" primitive for a different boolean
    condition, same as check_series_drift/refresh_hourly_target_hours reuse
    the once-per-day gate pattern for unrelated checks.
    """
    try:
        from utils import utc_today as _utc_today

        _today = _utc_today()
        if FEE_CHECK_PATH.exists():
            try:
                _existing = json.loads(FEE_CHECK_PATH.read_text())
                if _existing.get("date") == str(_today):
                    return
            except Exception:
                pass  # corrupt/missing state -- treat as "not yet run today"

        _min_ts = int((_dt.datetime.now(UTC) - _dt.timedelta(hours=25)).timestamp())
        fills = client.get_fills(min_ts=_min_ts)

        _nonzero: list[tuple[str, str, float]] = []
        for f in fills:
            if f.get("is_taker"):
                continue  # only maker fills are expected to be $0
            _ticker = f.get("ticker") or f.get("market_ticker") or "?"
            # Accept either spelling: docs.kalshi.com's Fill schema (verified
            # 2026-08-24) documents `fee_cost`, but this repo has already
            # seen Kalshi migrate other fields to a `*_fp` suffix
            # (fill_count_fp, orderbook_fp, queue_position_fp) -- and this
            # account had zero real fills at verification time, so
            # `fee_cost` was confirmed only against docs, never a live
            # response. A genuinely MISSING field (both keys absent) must
            # warn, not silently read as a confirmed $0 -- opus review
            # caught that treating "absent" the same as "present and 0"
            # would let this guard ship permanently blind if the field name
            # is ever wrong, with no log trail to notice.
            if "fee_cost" in f:
                _raw_fee = f.get("fee_cost")
            elif "fee_cost_fp" in f:
                _raw_fee = f.get("fee_cost_fp")
            else:
                _log.warning(
                    "check_fee_change: maker fill %s (%s) has no fee_cost/"
                    "fee_cost_fp field at all -- fee schedule shape may have "
                    "changed. Fill keys: %s",
                    f.get("fill_id") or f.get("trade_id"),
                    _ticker,
                    sorted(f.keys()),
                )
                continue
            try:
                _fee = float(_raw_fee)
            except (TypeError, ValueError):
                _log.warning(
                    "check_fee_change: unparseable fee value on fill %s (%s): %r",
                    f.get("fill_id") or f.get("trade_id"),
                    _ticker,
                    _raw_fee,
                )
                continue
            if _fee != 0.0:
                _nonzero.append(
                    (_ticker, f.get("fill_id") or f.get("trade_id") or "?", _fee)
                )

        if _nonzero:
            for _ticker, _fill_id, _fee in _nonzero:
                _log.error(
                    "check_fee_change: NONZERO maker fee detected -- ticker=%s "
                    "fill_id=%s fee=$%.4f. Kalshi may have added a per-series "
                    "maker fee; re-verify the fee schedule "
                    "(https://kalshi.com/fee-schedule) before trusting "
                    "KALSHI_MAKER_FEE_RATE=0 economics.",
                    _ticker,
                    _fill_id,
                    _fee,
                )

        from alerts import check_halt_transition as _check_fee_transition

        if _check_fee_transition("fee_nonzero", bool(_nonzero)):
            from notify import send_system_alert as _fee_alert

            _summary = "; ".join(
                f"{t} (fill {fid}): ${fee:.4f}" for t, fid, fee in _nonzero[:5]
            )
            if not _fee_alert(
                "Kalshi maker fee changed from $0",
                f"Nonzero maker fee detected on {len(_nonzero)} fill(s): {_summary}",
                cooldown_key="fee_change",
            ):
                from alerts import rollback_halt_transition as _rb_fee

                _rb_fee("fee_nonzero")

        FEE_CHECK_PATH.write_text(json.dumps({"date": str(_today)}))
    except Exception as _fee_exc:
        _log.warning("check_fee_change call failed: %s", _fee_exc)


def _check_fee_schedule_page() -> None:
    """Once per week: best-effort watch of kalshi.com/fee-schedule for
    scheduled upcoming changes mentioning tracked weather series.

    kalshi.com Cloudflare-blocks non-interactive fetches (429, confirmed
    repeatedly 2026-08-23/24, re-confirmed 2026-08-24 while building this)
    -- a 429 (or any other fetch failure) is logged at debug and skipped
    quietly, NOT retried in a loop and NOT itself alerted on. The fills-
    based check in _check_fee_change is the real guard; this is genuinely
    best-effort and may never successfully fetch anything.
    """
    try:
        from utils import utc_today as _utc_today

        _today = _utc_today()
        if FEE_SCHEDULE_SCRAPE_PATH.exists():
            try:
                _existing = json.loads(FEE_SCHEDULE_SCRAPE_PATH.read_text())
                _last = _dt.date.fromisoformat(_existing.get("date", "1970-01-01"))
                if (_today - _last).days < 7:
                    return
            except Exception:
                pass  # corrupt/missing state -- treat as "due"

        import requests

        try:
            # Honest User-Agent -- identifies this as a bot rather than
            # spoofing a browser to get past Kalshi's Cloudflare block. The
            # block fires regardless (confirmed live 2026-08-24), so nothing
            # is gained by pretending otherwise, and this is a
            # non-interactive fetch against a third party's page, not
            # Kalshi's own trading API.
            resp = requests.get(
                "https://kalshi.com/fee-schedule",
                timeout=10,
                headers={"User-Agent": "weather1-kalshi-bot/1.0 (fee-schedule watch)"},
            )
        except Exception as _req_exc:
            _log.debug("check_fee_schedule_page: fetch failed, skipping: %s", _req_exc)
            FEE_SCHEDULE_SCRAPE_PATH.write_text(json.dumps({"date": str(_today)}))
            return

        if resp.status_code == 429:
            _log.debug("check_fee_schedule_page: 429 (Cloudflare-blocked), skipping")
            FEE_SCHEDULE_SCRAPE_PATH.write_text(json.dumps({"date": str(_today)}))
            return
        if resp.status_code != 200:
            _log.debug("check_fee_schedule_page: HTTP %s, skipping", resp.status_code)
            FEE_SCHEDULE_SCRAPE_PATH.write_text(json.dumps({"date": str(_today)}))
            return

        text_lower = resp.text.lower()
        _weather_markers = (
            "weather",
            "climate",
            "temperature",
            "rain",
            "snow",
            "hurricane",
        )
        _change_markers = (
            "upcoming",
            "effective",
            "scheduled",
            "will change",
            "new fee",
        )
        _matched = any(w in text_lower for w in _weather_markers) and any(
            c in text_lower for c in _change_markers
        )
        if _matched:
            _log.warning(
                "check_fee_schedule_page: kalshi.com/fee-schedule mentions both a "
                "weather-series marker and a change marker -- manual review needed "
                "(this is a coarse text scan, not a parsed diff; may be a false "
                "positive)."
            )
        # Opus review follow-up: a real fee-schedule page will almost
        # certainly list weather series alongside an effective date on
        # EVERY successful fetch, so without edge-gating this would re-alert
        # every week forever the moment the 429-block ever lifts (the 6h
        # notify cooldown doesn't suppress a weekly cadence). Same
        # false->true edge mechanism as _check_fee_change above, distinct
        # halt_type so the two don't share state.
        try:
            from alerts import check_halt_transition as _check_sched_transition

            if _check_sched_transition("fee_schedule_page_match", _matched):
                from notify import send_system_alert as _sched_alert

                if not _sched_alert(
                    "Kalshi fee schedule page may reference a weather fee change",
                    "kalshi.com/fee-schedule text matched both a weather-series "
                    "marker and a change-language marker. Manually verify before "
                    "assuming $0 maker fees still hold.",
                    cooldown_key="fee_schedule_page",
                ):
                    from alerts import rollback_halt_transition as _rb_sched

                    _rb_sched("fee_schedule_page_match")
        except Exception as _sched_exc:
            _log.debug(
                "check_fee_schedule_page: alert/transition failed (non-fatal): %s",
                _sched_exc,
            )

        FEE_SCHEDULE_SCRAPE_PATH.write_text(json.dumps({"date": str(_today)}))
    except Exception as _sched_outer_exc:
        _log.debug("check_fee_schedule_page call failed: %s", _sched_outer_exc)


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


def _log_exit_rule_shadow(
    positions: list,
    markets_by_ticker: dict[str, dict],
    db_path,
) -> tuple[int, int, int, str]:
    """Record one row per open position per cycle for exit-rule research.

    Batch-89. OBSERVATION ONLY, and that claim is now structural rather than
    aspirational: this function performs NO network I/O. It reads quotes out
    of the caller's already-fetched scan (`result.markets`).

    The first version fetched its own quotes with client.get_market() per
    position, and an opus review found that is not observation at all --
    every Kalshi read goes through the SHARED, disk-persisted
    _kalshi_cb_read circuit breaker, and CircuitBreaker.is_open() is a
    MUTATOR: it flips HALF-OPEN, zeroes the failure count, designates its
    caller as the single probe, and _save_state()s. order_executor.
    _check_early_exits -- which CLOSES paper positions -- runs later in the
    same cycle on the same breaker, reached via ctx.check_early_exits in
    cmd_cron. A shadow fetch could therefore
    consume the probe slot and, on failure, reopen with a doubled backoff
    that outlives the process, blocking a real exit check. Taking the quotes
    from the scan removes the mechanism rather than guarding it.

    Writes RAW STATE (peak, current unrealized P&L, realizable price, hours
    to close) rather than any rule's verdict, so a different giveback,
    trigger or settlement gate can be scored later on rows it was not chosen
    from. A would-exit boolean would freeze in exactly the parameters there is
    least reason to trust. Logged regardless of the 24h settlement gate, with
    hours_to_close stored, so the gate's own value stays answerable too.

    unrealized_pnl is GROSS -- (price - entry_price) * quantity, with no exit
    fee, and note entry_price * quantity != cost (cost carries the entry
    fee). Everything needed to net it down is stored on the row.

    observed_profit_pct and peak_profit_pct are stored SEPARATELY and never
    blended. observed is this row's unrealized_pnl/cost, from the same quote
    as realizable_price. peak is production's running peak verbatim, computed
    by update_peak_profits from a different (later) fetch -- it is what the
    live breakeven stop fires on, and it is the value that cannot be
    recomputed later. An analysis wanting a self-consistent giveback takes a
    cumulative max of observed over a position's rows; one asking what
    production would have done reads peak.

    Returns (attempted, written, skipped, recorded_at). The stamp is returned
    so the caller can bind a shortfall diagnostic to THIS cycle's rows rather
    than to a wall-clock 'now' that may have crossed an hour boundary since.
    skipped counts positions dropped
    for having no ticker, which would otherwise be invisible in both the data
    and the reporting. written < attempted means rows were dropped by the
    unique index or by a constraint; the caller distinguishes which rather
    than assuming, because asserting a cause it never checked is how
    _log_near_settlement_trades above reported success while writing zero
    rows for over a month.
    """
    import sqlite3
    from datetime import UTC, datetime

    from positions import liquidation_price
    from weather_markets import parse_market_price

    now = datetime.now(UTC)
    now_iso = now.isoformat()
    current_prices: dict[str, dict[str, float]] = {}
    for pos in positions:
        market = markets_by_ticker.get(pos.ticker or "")
        if not market:
            continue
        try:
            quote = parse_market_price(market)
            if quote.get("has_quote"):
                current_prices[pos.ticker] = {
                    "bid": quote.get("yes_bid", 0.0),
                    "ask": quote.get("yes_ask", 0.0),
                }
        except Exception as _q_err:
            _log.debug(
                "exit_rule_shadow_log: unusable quote for %s: %s", pos.ticker, _q_err
            )

    rows = []
    skipped = 0
    for pos in positions:
        if not pos.ticker:
            skipped += 1
            continue
        px = liquidation_price(current_prices, pos.ticker, pos.side)
        pnl = None
        if px is not None and pos.quantity:
            pnl = (px - pos.entry_price) * pos.quantity
        # Stored SEPARATELY, never blended. observed is consistent with this
        # row's own price; peak is production's, from a different fetch. A
        # max() would overwrite the one value that cannot be recomputed with
        # one that can (pnl/cost is right there in the row).
        observed = (pnl / pos.cost) if (pnl is not None and pos.cost) else None
        peak = pos.peak_profit_pct
        hours_to_close = None
        if pos.close_time:
            close_dt = None
            try:
                close_dt = datetime.fromisoformat(pos.close_time.replace("Z", "+00:00"))
            except (ValueError, TypeError, AttributeError):
                close_dt = None
            if close_dt is not None:
                # Normalised OUTSIDE the except above on purpose: an aware
                # minus naive subtraction raises TypeError, and catching it
                # here would silently record NULL for every naive close_time
                # instead of surfacing that the normalisation had stopped
                # working.
                if close_dt.tzinfo is None:
                    close_dt = close_dt.replace(tzinfo=UTC)
                hours_to_close = (close_dt - now).total_seconds() / 3600
        rows.append(
            (
                pos.ticker,
                pos.id,
                pos.side,
                pos.entry_price,
                pos.cost,
                pos.quantity,
                px,
                pnl,
                observed,
                peak,
                hours_to_close,
                now_iso,
            )
        )
    if not rows:
        return 0, 0, skipped, now_iso
    written = 0
    con = sqlite3.connect(db_path)
    try:
        with con:
            for r in rows:
                cur = con.execute(
                    "INSERT OR IGNORE INTO exit_rule_shadow_log "
                    "(ticker, trade_id, side, entry_price, cost, quantity, "
                    " realizable_price, unrealized_pnl, observed_profit_pct, "
                    " peak_profit_pct, hours_to_close, recorded_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    r,
                )
                written += cur.rowcount
    finally:
        # sqlite3.Connection.__exit__ commits/rolls back but does NOT close --
        # see tracker._conn's AUD-0048 docstring. cmd_cron runs inside
        # main.cmd_loop's `while True`, so without this every cycle leaks a
        # handle.
        con.close()
    return len(rows), written, skipped, now_iso


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


def _build_toast_message(
    signals: int,
    placed_count: int,
    settled_count: int,
    halted_reason: str | None,
    risk_halt_notes: list[str],
    graduated: bool,
) -> str:
    """Build the Windows toast notification text for one cron cycle.

    Pure helper extracted from the toast-send block itself (opus-review-
    caught, F15/T2) so it's independently testable: the block that CALLS
    this sits behind a `if os.environ.get("PYTEST_CURRENT_TEST"): raise
    StopIteration` skip (so it never actually sends a real toast during a
    test run), which meant this text-building logic -- including the
    single-quote escaping for the PowerShell string it gets interpolated
    into below -- previously had zero test coverage, including the exact
    case it exists for (a halt reason containing a literal single quote,
    reachable via arbitrary exception text).

    batch-24 item 4: appends halt info (from `halted_reason` and
    `risk_halt_notes`) so a halted cycle's toast is distinguishable from a
    normal quiet cycle -- previously built purely from signal/placed/
    settled counts. When `graduated` is True, the graduation message is
    the headline but halt info is still appended rather than silently
    discarded (opus-review-caught, F15: an earlier version fully
    overwrote `msg` on graduation, dropping any halt text the same cycle
    -- rare, since graduation fires at most once ever, but the two must
    not silently conflict when they do coincide).
    """
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

    halt_display_notes = list(risk_halt_notes)
    if halted_reason:
        halt_display_notes.insert(0, halted_reason)
    halt_text = ""
    if halt_display_notes:
        # Escape embedded single-quotes -- this string is interpolated into
        # a single-quoted PowerShell literal by the caller.
        halt_text = "; ".join(halt_display_notes).replace("'", "''")
        msg = f"{msg} — HALTED: {halt_text}"

    if graduated:
        grad_msg = "READY TO GO LIVE — 30 trades, +$50 P&L, Brier ≤ 0.23 met!"
        msg = f"{grad_msg} — HALTED: {halt_text}" if halt_text else grad_msg

    return msg


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

    # batch-78 item 1. Stamped at the very top, before the kill-switch and
    # black-swan checks below, because those checks can `return None` and a
    # cycle that deliberately halted still RAN -- see _record_scan_run's own
    # comment for why recording it matters.
    from datetime import UTC as _UTC_SCAN
    from datetime import datetime as _dt_scan

    _scan_started_at = _dt_scan.now(_UTC_SCAN).isoformat()

    def _record_scan_run(
        result: TradeCycleResult | None = None,
        *,
        halted_reason: str | None = None,
    ) -> None:
        """Persist one scan_runs row for this cycle. Never raises.

        Called from EVERY exit path of this function that represents a cron
        cycle actually happening -- including the two early `return None`
        halts, which was an opus-review finding (batch-78, reviewer B #1) and
        not merely a tidiness point. get_scan_activity() reads the ABSENCE of
        a row for a covered day as "no scan", i.e. an outage. Recording only
        on the paths that reach run_trade_cycle() would make an engaged kill
        switch or a black-swan halt -- days on which cron ran perfectly and
        deliberately chose not to scan -- report as a dead scheduler. That is
        the same false-outage inversion `scan_coverage_from` exists to
        prevent, arriving by a different route.

        A halted cycle records counts as NULL and `halted_reason` set, which
        get_scan_activity() reads as "cron ran, no scan" -- distinct from both
        "scanned, nothing survived" and "no scan".
        """
        try:
            from tracker import log_scan_run as _log_scan_run

            _log_scan_run(
                _scan_started_at,
                markets_fetched=(None if result is None else len(result.markets)),
                markets_scanned=(None if result is None else result.scanned),
                reached_analysis=(
                    # Per-SCAN analyses. Deliberately NOT the same quantity as
                    # get_scan_activity()'s per-day `reached_analysis`, which
                    # counts analysis_attempts rows -- that table upserts on
                    # (ticker, target_date), so a re-analysed market moves its
                    # row instead of adding one and the two legitimately
                    # disagree. Do not compare them (reviewer B #12).
                    None if result is None else len(result.all_results)
                ),
                scan_completed=(False if result is None else result.scan_completed),
                mode="cron-sameday" if sameday_only else "cron",
                halted_reason=(
                    halted_reason if result is None else result.halted_reason
                ),
            )
        except Exception as _scan_rec_exc:
            # log_scan_run already swallows its own failures at warning level;
            # this guard covers the import and the attribute reads above.
            # WARNING, not debug (reviewer B #4): anything caught here means
            # NO row is written, and a missing row is exactly what
            # get_scan_activity() reports as an outage -- a permanently broken
            # writer would otherwise manufacture a permanent false outage
            # history with no trace above debug level.
            _log.warning("cmd_cron: scan_runs record failed: %s", _scan_rec_exc)

    # Dead-man's-switch: if more than 48h have elapsed since the last
    # non-kill-switch-aborted cron run completed, log a warning and fire a
    # system notification so the user knows the bot went quiet. .cron_last_run
    # is written in the cmd_cron finally block, EXCEPT on a cycle the kill
    # switch aborts (see that block's own comment below the kill-switch
    # check) — so a gap > 48h means either the process was stopped/crashing
    # for two days, or the kill switch has stayed engaged that whole time.
    # Deliberately runs BEFORE the kill-switch check below (batch-24 item 1:
    # this used to sit after the kill-switch return, so it could never fire
    # while the switch stayed engaged — the one scenario a dead-man's-switch
    # most needs to survive).
    #
    # opus-review-noted (2nd round, LOW-7): a known, accepted consequence
    # of freezing CRON_LAST_RUN_PATH while the switch is engaged (see the
    # finally block's own comment) -- the FIRST cycle after a >48h halt is
    # deliberately cleared sees the full accumulated gap and fires this
    # alert once more, a false alarm for an operator who just resumed on
    # purpose. In practice the cron_gap 6h cooldown will usually have
    # already suppressed it from firing during the halt itself, bounding
    # how often this actually surfaces. Not fixed: the alternative (also
    # resetting the gap timer on resume) would need its own hook into every
    # resume path, same complication as the kill_switch/black_swan_halt
    # cooldown-clearing this session already added to cmd_resume -- and
    # unlike those, a stale FALSE POSITIVE alert here is far less costly
    # than a missed real one, so it's not worth the same treatment.
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
        # batch-24 item 1: this abort previously only logged/printed -- an
        # operator relying on push channels (not watching the terminal) got
        # zero signal that the kill switch had engaged. cooldown_key is
        # shared with trade_cycle.py's own kill-switch check (same
        # real-world event) so a simultaneous cron+watch trigger alerts once
        # per 6h window, not twice.
        from notify import send_system_alert as _ks_alert

        _ks_alert(
            "Kalshi kill switch engaged",
            "Cron found data/.kill_switch present and halted this cycle "
            "immediately. Remove the file to resume trading.",
            cooldown_key="kill_switch",
        )
        # batch-78: cron RAN and deliberately did not scan. Without this row
        # the day reads as an outage -- see _record_scan_run's docstring.
        # batch-78: cron RAN and deliberately did not scan. Without this row
        # the day reads as an outage -- see _record_scan_run's docstring.
        _record_scan_run(halted_reason="kill_switch")
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

    # Full-scan staleness check — distinct from the dead-man's-switch above
    # (batch-24 item 1 moved that check earlier in this function, ahead of
    # the kill-switch check — see its own comment there; this one doesn't
    # need the same hoist, since it isn't kill-switch-related).
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
    _MONDAY_SWEEP_PATH = LAST_MONDAY_SWEEP_PATH
    if _is_monday_utc():
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

                # batch-69, opus-review-caught (M10/L-3): alert_deliveries had
                # no pruner wired in, so it grew without bound -- and while
                # the kill switch is engaged, kill_switch_engaged writes a
                # "suppressed" row every single cycle.
                from tracker import (
                    prune_old_alert_deliveries as _prune_alert_deliveries,
                )

                _prune_alert_deliveries(days=90)

                # batch-78 item 2: batch-64's two forward-only tables had no
                # sweep at all -- purge_old_predictions covers only
                # predictions/outcomes, and a grep for DELETE against either
                # of these found nothing. Windows differ per table on
                # purpose: ensemble_member_values feeds A15b's rank
                # histogram and shares the 730-day long-retention constant
                # with purge_old_predictions and prune_scan_runs, while
                # orderbook_depth_snapshots feeds A4/A17's short-horizon
                # replay and has no dedup key at all. See each pruner's own
                # docstring for the measurements behind its number.
                from tracker import (
                    prune_ensemble_member_values as _prune_member_values,
                )
                from tracker import (
                    prune_orderbook_depth_snapshots as _prune_depth,
                )

                # Each wrapped individually (reviewer B #7): the whole sweep
                # body is one try/except with a `finally` that stamps the
                # 7-day marker, so an exception from any one pruner would
                # skip the VACUUM below AND suppress the entire sweep for
                # another week, on one warning line. These three are new
                # failure surface added ahead of the VACUUM, so they must not
                # be able to take the rest of the sweep down with them.
                #
                # Written as separate direct calls rather than a loop over a
                # tuple of function references, matching _prune_scan_runs
                # just below. The loop was equivalent at runtime but put the
                # only occurrence of each name inside a tuple and called it
                # through a loop variable, so tests/test_dead_code_scan.py's
                # call-site scan -- which resolves `alias(` for an aliased
                # import -- could not see either call and reported both
                # pruners FULLY DEAD. Same failure mode, and same fix, as
                # weather_markets._count_market_implied_rain in 2026-08-02:
                # match the convention the scanner reads rather than
                # allowlisting a genuinely-called function, which would
                # exempt it from ever being detected as dead for real.
                try:
                    _prune_member_values(days=730)
                except Exception as _prune_exc:
                    _log.warning(
                        "cmd_cron: ensemble_member_values retention sweep failed: %s",
                        _prune_exc,
                    )

                try:
                    _prune_depth(days=30)
                except Exception as _prune_exc:
                    _log.warning(
                        "cmd_cron: orderbook_depth_snapshots retention sweep "
                        "failed: %s",
                        _prune_exc,
                    )

                # batch-78 item 1: one row per cron cycle, so this is
                # negligible next to the two above -- swept on the same
                # 730-day retention purge_old_predictions uses rather than a
                # window of its own, since a long uptime baseline is the
                # entire point of the table.
                from tracker import prune_scan_runs as _prune_scan_runs

                try:
                    _prune_scan_runs(days=730)
                except Exception as _prune_exc:
                    _log.warning(
                        "cmd_cron: scan_runs retention sweep failed: %s", _prune_exc
                    )

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

        # batch-33 L-8: cron never OPENS a live order itself (see the
        # exit-check comment just below), but a prior `watch --auto --live`
        # session can leave one PENDING (a resting GTC order, not yet
        # filled) or FILLED-but-unsettled when that session stops.
        # _poll_pending_orders was the ONE place that observed fills,
        # auto-cancelled stale/pre-close GTC orders, and recorded
        # settlement outcomes into execution_log -- its only caller was
        # cmd_watch, so a cron-only host (no watch --auto --live running)
        # never ran any of that. It also keeps execution_log's realized-
        # loss data current for whenever watch --auto --live's own live
        # daily-loss brake (_place_live_order's execution_log.get_today_
        # live_loss() check) next runs, so wiring this in here restores
        # that brake's accuracy too, not just GTC/settlement.
        #
        # Also fixes a real, separate ordering bug as a side effect:
        # _check_live_position_exits's own docstring documents "Must run
        # AFTER _poll_pending_orders in the same cycle so a just-filled
        # order is already visible" -- cron.py called that exit check
        # below without ever calling this first, so a live position that
        # filled between watch sessions was invisible to stop-loss/
        # breakeven protection until whichever session happened to run
        # _poll_pending_orders next. Config resolution mirrors order_
        # executor.py's own _resolve_micro_live_config: cron never has a
        # cmd_watch-style live_config in hand, so load the real one
        # directly instead of passing None (which would silently fall
        # back to this function's built-in gtc_cancel_hours=24 default
        # rather than whatever data/live_config.json actually says).
        # Harmless no-op today (no pending/unsettled live order exists to
        # find) -- mirrors _recover_pending_orders' own "nothing to do"
        # framing above.
        try:
            from main import _load_live_config
            from order_executor import _poll_pending_orders

            _poll_pending_orders(client, config=_load_live_config())
        except Exception as _ppo_exc:
            _log.warning("cmd_cron: _poll_pending_orders failed: %s", _ppo_exc)

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
        # backlog L26224 (batch-62): built from the canonical registry rather
        # than a hand-maintained 4-entry map. That map had never picked up
        # _nbm_om_cb/_ecmwf_om_cb/_hrrr_om_cb (nor the newer
        # _ensemble_precip_multiday_cb), so a circuit opening on any of those
        # data sources mid-scan produced no alert at all. All eight are
        # alert-worthy -- the registry's prewarm_scoped flag only governs
        # trade_cycle's probe suppression, not monitoring.
        #
        # Accepted consequence (opus-review-caught, batch-62): six of the
        # eight hit Open-Meteo hosts and will trip together, so a single
        # Open-Meteo outage now emits up to six "Circuit Opened" alerts where
        # it previously emitted two. The per-circuit cooldown key below stops
        # repeats of the SAME circuit for 6h but cannot dedupe correlated
        # ones. Kept deliberately: which specific source tripped is the
        # actionable detail, and collapsing them behind a shared key would
        # hide a genuinely independent second failure inside an unrelated
        # outage's cooldown window.
        from weather_markets import CIRCUIT_BREAKERS

        _scan_cbs = {reg.name: reg.breaker for reg in CIRCUIT_BREAKERS}
        # seconds_open() > 0, NOT is_open(): is_open() is a MUTATOR. Once the
        # recovery timeout has elapsed it flips the breaker to HALF-OPEN,
        # zeroes failure_count, persists that, and returns False -- "you are
        # the probe." A monitor that calls it therefore CONSUMES the one
        # recovery probe, and the next real fetch caller sees is_open()==True
        # and skips the source. Combined with trade_cycle's suppress_probe()
        # (which disables probing for the process lifetime) that wedges the
        # breaker open until restart. Opus-review-caught (batch-62, HIGH):
        # widening this snapshot from 4 breakers to all 8 would have put four
        # live-blend temperature sources (nbm/ecmwf/hrrr/precip) into exactly
        # that trap. seconds_open() and seconds_until_retry() are pure reads.
        _pre_scan_cb_states = {
            name: cb.seconds_open() > 0 for name, cb in _scan_cbs.items()
        }
    except Exception as _e:
        _log.debug("cmd_cron: circuit state snapshot failed: %s", _e)
        _pre_scan_cb_states = {}
        _scan_cbs = {}

    # P8.2 — anomaly detection at start of cron cycle
    try:
        from alerts import check_halt_transition as _check_halt_transition
        from alerts import run_anomaly_check as _run_anomaly_check

        _detected_anomalies, _should_halt = _run_anomaly_check(log_results=True)
        # batch-24 item 4: fire a system alert on the false->true edge of
        # this halt condition, not every cycle it stays engaged. Keyed off
        # `_should_halt` itself rather than whether an override below ends
        # up suppressing PLACEMENT this cycle -- the underlying anomaly
        # condition firing is what an operator needs to know about, even if
        # they (or another halt) already suppressed this cycle's placement.
        #
        # Wrapped in its OWN try/except (opus-review-caught, F5): this
        # whole block sits inside the OUTER try below, whose except treats
        # ANY exception as "run_anomaly_check itself failed" and fails
        # CLOSED (sets _cron_halted_reason, blocking real placement) --
        # appropriate for a genuine anomaly-check failure, but wrong for a
        # failure in the ALERTING call itself (e.g. a corrupt cooldown/
        # transition state file). send_system_alert() is documented "Never
        # raises," but the arithmetic inside _system_cooldown_reserve isn't
        # inside ITS OWN try (only the read is) -- a hand-edited or
        # otherwise malformed persisted cooldown value could still raise
        # there. Without this inner try, that would falsely halt a
        # perfectly healthy trading cycle AND emit a misleading "anomaly
        # halt engaged" alert.
        try:
            # check_halt_transition() returns `active and not was_active`,
            # so a True return already implies _should_halt is True -- no
            # separate `and _should_halt` needed (opus-review-caught, F10).
            if _check_halt_transition("anomaly", _should_halt):
                from notify import send_system_alert as _anom_alert

                # batch-33 M-1: roll the persisted edge back on total
                # delivery failure so the NEXT cycle's observation is
                # treated as a fresh transition and retries the alert,
                # instead of the edge being silently consumed here with
                # nothing actually delivered (see
                # alerts.rollback_halt_transition's own docstring).
                if not _anom_alert(
                    "Kalshi anomaly halt engaged",
                    f"Anomaly halt triggered: {'; '.join(_detected_anomalies)}",
                    cooldown_key="halt_anomaly",
                ):
                    from alerts import rollback_halt_transition as _rb_anom

                    _rb_anom("anomaly")
        except Exception as _anom_alert_exc:
            _log.debug(
                "cmd_cron: anomaly halt transition/alert failed: %s", _anom_alert_exc
            )
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
        try:
            from alerts import check_halt_transition as _check_halt_transition_err

            if _check_halt_transition_err("anomaly", True):
                from notify import send_system_alert as _anom_alert_err

                # batch-33 M-1: same rollback as the primary anomaly-halt
                # alert above.
                if not _anom_alert_err(
                    "Kalshi anomaly halt engaged",
                    f"run_anomaly_check failed — failing closed: {_e}",
                    cooldown_key="halt_anomaly",
                ):
                    from alerts import rollback_halt_transition as _rb_anom_err

                    _rb_anom_err("anomaly")
        except Exception:
            pass

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
            # batch-78: same reasoning as the kill-switch return above -- a
            # deliberate halt is not an outage.
            _record_scan_run(halted_reason="black_swan")
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

    # Daily-loss / drawdown halt observation — batch-24 item 4. These are
    # ALSO checked inside order_executor._auto_place_trades(), but only when
    # there are candidate signals to place (auto_place_trades isn't called
    # on a zero-candidate cycle), which would leave both a quiet halted
    # cycle silently unalerted and the halt's "cleared" transition never
    # observed. Checked here unconditionally, every cycle, purely for
    # alerting/toast visibility — this does NOT gate placement (that
    # remains order_executor's own job).
    #
    # Deliberately called with client=None (paper-only check), NOT the real
    # `client` (opus-review-caught, F6: an earlier version passed `client`
    # here, which is NOT a cheap duplicate of order_executor's own check --
    # is_daily_loss_halted(client)/is_paused_drawdown(client) with a real
    # client fetch live balance/positions via UNCACHED per-open-trade
    # client.get_market() calls (paper.get_unrealized_pnl_paper), adding N
    # extra Kalshi API calls to EVERY cron cycle, doubled on cycles that
    # also place trades since order_executor runs the same checks again
    # with the real client). client=None still catches every
    # paper-balance-driven halt (the vast majority, since live trading is
    # currently dormant) for alerting purposes -- the real, client-aware
    # check still runs at order_executor's own placement gate regardless of
    # what this observation-only block sees.
    #
    # Each halt's check + transition + alert is wrapped in its OWN
    # try/except (opus-review-caught, F4: an earlier version evaluated both
    # booleans eagerly in a tuple literal built before the loop ran, so one
    # raising lost both observations for the cycle, silently, at
    # _log.debug -- with check_halt_transition's disk-persisted state, a
    # lost observation isn't just a missed alert THIS cycle, it can also
    # leave a flag stuck unable to clear).
    _risk_halt_notes: list[str] = []
    _risk_halt_checks: list[tuple[str, Callable[[object], bool], str, str]] = []
    try:
        from paper import is_daily_loss_halted as _is_daily_loss_halted
        from paper import is_paused_drawdown as _is_paused_drawdown_check

        _risk_halt_checks = [
            (
                "daily_loss",
                _is_daily_loss_halted,
                "Kalshi daily loss halt engaged",
                "daily loss limit reached",
            ),
            (
                "drawdown",
                _is_paused_drawdown_check,
                "Kalshi drawdown halt engaged",
                "drawdown guard active",
            ),
        ]
    except Exception as _e:
        _log.debug("cmd_cron: daily-loss/drawdown halt import failed: %s", _e)

    for _halt_type, _halt_check_fn, _halt_title, _halt_note in _risk_halt_checks:
        try:
            _halt_active = _halt_check_fn(None)
        except Exception as _e:
            _log.debug("cmd_cron: %s halt observation failed: %s", _halt_type, _e)
            continue
        if _halt_active:
            _risk_halt_notes.append(_halt_note)
        try:
            from alerts import check_halt_transition as _check_risk_halt_transition

            # opus-review-caught (2nd round, MEDIUM-2): this observer
            # (client=None, paper-only, per F6) and order_executor.py's own
            # cycle-level observer (the real client, sees live MTM/realized
            # loss too) write the SAME halt_type with genuinely different
            # inputs -- whenever the two disagree (e.g. a live-only halt),
            # they flip-flop the shared flag every cycle (cron: False,
            # order_executor: True, cron: False again next cycle, ...),
            # degrading "fire once per engagement" back to "fire at most
            # once per 6h cooldown" -- the exact pre-batch-24-item-4
            # cadence this was meant to improve on. Tracked under a
            # DISTINCT halt_type ("<type>_paper") so this observer's own
            # true/false history never gets overwritten by the
            # client-aware one (or vice versa) -- each observer's flag now
            # correctly reflects only what THAT observer has seen. Both
            # still share the SAME cooldown_key (the un-suffixed name) so
            # the operator gets one alert stream per real condition, not
            # two, regardless of which observer's edge fired it.
            if _check_risk_halt_transition(f"{_halt_type}_paper", _halt_active):
                from notify import send_system_alert as _risk_halt_alert

                # batch-33 M-1: roll back the "<type>_paper" edge (not the
                # un-suffixed one order_executor.py owns) on total delivery
                # failure -- see rollback_halt_transition's own docstring.
                if not _risk_halt_alert(
                    _halt_title,
                    f"{_halt_note} — auto-trade placement is skipped while active.",
                    cooldown_key=f"halt_{_halt_type}",
                ):
                    from alerts import rollback_halt_transition as _rb_risk

                    _rb_risk(f"{_halt_type}_paper")
        except Exception as _e:
            _log.debug("cmd_cron: %s halt transition/alert failed: %s", _halt_type, _e)

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

    # Same-day condition-type weakness check (log-only, non-blocking -- see
    # tracker.check_sameday_condition_type_weakness's own docstring). Same
    # shape as the multi-day check just above, but the multi-day one reads
    # multiday_predictions (days_out>=1) and can never see a between row --
    # this is where batch-40's between-specific visibility actually surfaces
    # operationally, not just in the dashboard.
    try:
        from tracker import (
            check_sameday_condition_type_weakness as _check_sameday_cond_weak,
        )

        for _sameday_cond_alert in _check_sameday_cond_weak():
            _log.warning("cmd_cron: %s", _sameday_cond_alert)
    except Exception as _e:
        _log.debug("cmd_cron: check_sameday_condition_type_weakness failed: %s", _e)

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
            # batch-33 L-8: route through safe_io's Windows-retry-safe
            # rename instead of a bare Path.replace() -- this log file has
            # a GUARANTEED concurrent reader (whatever's tailing bot.log),
            # the exact sharing-violation shape
            # tests/test_bare_os_replace_guard.py's whole guard exists to
            # catch. Previously allowlisted there as a known gap belonging
            # to a different batch's file ownership; this batch owns
            # cron.py, so it's fixed here and the allowlist entry removed.
            from safe_io import _replace_with_retry

            _replace_with_retry(str(log_path), log_path.with_suffix(".log.1"))
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

    # batch-78 item 1: the scan_runs row is written in a `finally` so that a
    # scan which RAISES, or trips the kill switch mid-cycle, still leaves
    # evidence it started. Recording only on the success path would reproduce
    # the exact gap this table exists to close -- a dead cycle and a
    # never-launched one would again look identical in get_scan_activity().
    #
    # Scope of that guarantee, stated precisely (reviewer B #6): `finally`
    # covers Python exceptions ONLY. _install_cron_watchdog's 720s timeout
    # calls os._exit(1), which by design runs no finally blocks, and SIGKILL
    # or power loss do the same -- so a HUNG cycle, the classic "cron is
    # dead" symptom, still leaves no row. Covering that would need
    # finished_at to be nullable and a write-at-start/update-at-end design;
    # `finished_at TEXT NOT NULL` deliberately does not support it, because a
    # half-written row is its own ambiguity.
    #
    # `result` stays None when run_trade_cycle raised OR returned None, so
    # the counts go in as NULL rather than 0 -- 0 would assert "scanned
    # nothing". That does conflate three outcomes (reviewer B #5): a raise, a
    # kill switch tripped BEFORE the scan, and a kill switch tripped after
    # the analysis loop had already finished. In the third case `scanned` and
    # `all_results` were genuinely known and run_trade_cycle discards them on
    # its way out. Recording NULL there understates what was known, which is
    # the safe direction; fixing it properly means changing run_trade_cycle's
    # None-return contract and is out of this batch's scope.
    _scan_result: TradeCycleResult | None = None
    try:
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
        _scan_result = result
    finally:
        _record_scan_run(_scan_result)

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
    from weather_markets import signal_values_from_analysis as _signal_values

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
                    # batch-87. The pre-section-9c value, which is what the
                    # analysis calibration is fitted on. `forecast_prob`
                    # above is 9c's OUTPUT, so fitting on it would train the
                    # correction on itself -- see the column's migration
                    # comment in tracker.py for the measured decay. None on
                    # any analyser that never reached 9c (the precip/snow/
                    # rain/hurricane/tornado/hourly fast paths return before
                    # it), which stores SQL NULL and COALESCEs back to
                    # forecast_prob at read time.
                    "forecast_prob_precal": _analysis.get("forecast_prob_precal"),
                    "market_prob": _analysis.get("market_prob", 0.0),
                    "days_out": int(_analysis.get("days_out", 0)),
                    "was_traded": False,
                    # batch-81 item 2. This is the whole point of the item:
                    # every registry sample floor counted settled
                    # `predictions` rows, which only exist past the
                    # placement gate, so none of THIS stream -- every
                    # analysed market, ~6-7x the volume and structurally
                    # unbiased -- ever reached a floor. Pure dict lookups
                    # off the analysis dict trade_cycle already built; no
                    # network call is added to the scan (see
                    # _ATTEMPT_SIGNAL_FIELDS for the one signal that is
                    # excluded for exactly that reason).
                    # ticker is passed explicitly (and is required by that
                    # function) because it is what separates the temperature
                    # market-implied fit from the monthly-rain one -- the
                    # same slot carries degrees F for KXHIGH*/KXLOW* and
                    # inches for KXRAIN*M.
                    # `or None` rather than a "" default: an empty ticker is not
                    # a known market, and signal_values_from_analysis must be
                    # able to tell "unknown" from "a temperature market", or
                    # it files a monthly-rain fit in inches under the
                    # degrees-F key.
                    "signals": _signal_values(
                        _analysis, _enriched.get("ticker") or None
                    ),
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

    # Batch-89: exit-rule shadow log. Observation only -- no decision reads
    # this, and it runs AFTER check_paper_position_exits above so
    # peak_profit_pct has already been refreshed and persisted this cycle.
    # Own try/except so a logging failure can never interrupt the cycle,
    # matching the near-settlement block earlier.
    try:
        import paper as _ersl_paper
        from tracker import DB_PATH as _ERSL_DB

        _ersl_positions = _ersl_paper.PaperPositionStore().get_open()
        if _ersl_positions:
            # Quotes come from the scan already in hand -- see the writer's
            # docstring for why it must not fetch its own.
            _ersl_markets = {
                m["ticker"]: m
                for m in (result.markets if result else [])
                if m.get("ticker")
            }
            (
                _ersl_att,
                _ersl_wrote,
                _ersl_skipped,
                _ersl_stamp,
            ) = _log_exit_rule_shadow(_ersl_positions, _ersl_markets, _ERSL_DB)
            if _ersl_skipped:
                _log.warning(
                    "exit_rule_shadow_log: %d position(s) had no ticker and were "
                    "not recorded",
                    _ersl_skipped,
                )
            if _ersl_att and _ersl_wrote < _ersl_att:
                # Distinguish dedup from a silent constraint drop rather than
                # asserting a cause. INSERT OR IGNORE swallows both, which is
                # how near_settlement_log reported success on zero rows.
                import sqlite3 as _ersl_sq

                # Bound to THIS cycle's own (ticker, trade_id) pairs and its
                # own stamp -- an hour-wide COUNT(*) compares against rows
                # from other cycles, so a shrinking position count makes
                # "prior >= attempted" true unconditionally and reports a
                # genuine constraint drop as routine dedup. Own try/except:
                # a failure to DIAGNOSE must not be reported as a failure to
                # WRITE, since the write already succeeded.
                _ersl_prior = -1
                try:
                    _ersl_con = _ersl_sq.connect(_ERSL_DB)
                    try:
                        _ersl_prior = _ersl_con.execute(
                            "SELECT COUNT(*) FROM exit_rule_shadow_log WHERE "
                            "strftime('%Y-%m-%dT%H', recorded_at) = "
                            "strftime('%Y-%m-%dT%H', ?) AND ticker IN "
                            "(" + ",".join("?" * len(_ersl_positions)) + ")",
                            [_ersl_stamp] + [p.ticker for p in _ersl_positions],
                        ).fetchone()[0]
                    finally:
                        _ersl_con.close()
                except Exception as _ersl_diag:
                    _log.warning(
                        "exit_rule_shadow_log: wrote %d/%d row(s); could not "
                        "diagnose the shortfall: %s",
                        _ersl_wrote,
                        _ersl_att,
                        _ersl_diag,
                    )
                if _ersl_prior < 0:
                    pass
                elif _ersl_prior >= _ersl_att:
                    _log.info(
                        "exit_rule_shadow_log: %d/%d row(s) written; the rest "
                        "already had a row this UTC hour",
                        _ersl_wrote,
                        _ersl_att,
                    )
                else:
                    _log.warning(
                        "exit_rule_shadow_log: %d/%d row(s) written and dedup "
                        "does NOT account for the difference -- rows were "
                        "silently dropped by a constraint",
                        _ersl_wrote,
                        _ersl_att,
                    )
            elif _ersl_att:
                _log.info("exit_rule_shadow_log: logged %d position(s)", _ersl_wrote)
    except Exception as _ersl_err:
        # Says "failed", not "write failed": this also catches a ledger-load
        # error (paper._load raises CorruptionError on a checksum mismatch),
        # where nothing was even attempted. Asserting a cause the handler
        # never checked is the defect the shortfall branch above exists to
        # avoid; the same discipline applies here.
        _log.warning("exit_rule_shadow_log: skipped this cycle: %s", _ersl_err)

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
                        # batch-24 item 2: was Discord-only via a direct
                        # _send_discord call with its return value discarded
                        # -- routed through send_system_alert so all
                        # NOTIFY_CHANNELS are honored and total-failure is
                        # logged, not silently swallowed.
                        from notify import send_system_alert as _brier_alert

                        _brier_alert(
                            "\u26a0\ufe0f Brier Score Alert",
                            _brier_msg,
                            cooldown_key="brier_alert",
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
            # batch-24 item 2: was Discord-only via a direct _send_discord
            # call with its return value discarded -- routed through
            # send_system_alert so all NOTIFY_CHANNELS are honored. Cooldown
            # key is scoped per-circuit-name so one data source opening
            # doesn't suppress a genuinely different data source's alert for
            # the rest of the 6h window.
            from notify import send_system_alert as _cb_alert

            for _cb_name, _cb_obj in _scan_cbs.items():
                # seconds_open() > 0, not is_open() -- see the Phase 9
                # snapshot above for why a monitor must never call is_open().
                if (
                    not _pre_scan_cb_states.get(_cb_name, True)
                    and _cb_obj.seconds_open() > 0
                ):
                    _log.warning(
                        "Circuit '%s' OPENED during cron scan \u2014 notifying",
                        _cb_name,
                    )
                    _cb_alert(
                        f"\u26a1 Circuit Opened: {_cb_name}",
                        f"The `{_cb_name}` data source tripped during cron scan.\n"
                        f"Failures: {_cb_obj.failure_count}  |  "
                        f"Retry in: {round(_cb_obj.seconds_until_retry())}s",
                        cooldown_key=f"circuit_open:{_cb_name}",
                        discord_color=0xF85149,  # red -- restores the prior color (F13)
                    )
    except Exception as _e:
        _log.debug("cmd_cron: circuit-open alert failed: %s", _e)

    # Windows toast notification (suppressed during test runs)
    try:
        import os as _os
        import subprocess as _sp

        if _os.environ.get("PYTEST_CURRENT_TEST"):
            raise StopIteration  # skip toast in tests

        # Graduation alert — fires once when all criteria are first met
        _grad_flag = GRADUATED_FLAG_PATH
        _graduated_now = False
        try:
            from paper import graduation_check as _grad_check

            if _grad_check() is not None and not _grad_flag.exists():
                _grad_flag.touch()
                _graduated_now = True
        except Exception:
            pass

        msg = _build_toast_message(
            signals=len(strong_opps) + len(med_opps),
            placed_count=placed_count,
            settled_count=settled_count,
            halted_reason=_cron_halted_reason,
            risk_halt_notes=_risk_halt_notes,
            graduated=_graduated_now,
        )
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
                # batch-87: BEFORE the T refit, not after. train_all_temperature_
                # scaling freezes the multi-day T keys once a real analysis
                # calibration exists, so fitting this first means the freeze is
                # already live the first time T is consulted — otherwise the very
                # first retrain after this landed would move T once more (on the
                # selected population) and only then freeze.
                from ml_bias import (
                    fit_and_save_analysis_calibration as _fit_analysis_cal,
                )

                # Own try/except (opus review, batch-87). This call sits
                # FIRST in the D5 block, upstream of the T refit, the blend
                # calibration, the in-process weight push and the METAR fit
                # -- and the block's `finally` touches its 6-day marker
                # unconditionally, so letting an exception escape here would
                # cost all four of them for another six days. The existing
                # METAR fit is placed LAST in this block for exactly this
                # reason; this one cannot be, because the T freeze depends on
                # it having run.
                try:
                    _acal = _fit_analysis_cal()
                    if _acal:
                        print(
                            dim(
                                f"  [AnalysisCal] fitted — a={_acal[0]:.4f} b={_acal[1]:.4f}"
                            )
                        )
                    else:
                        # Report WHICH decline. Two of the five causes are
                        # data-integrity alarms, and a decline also silently
                        # un-freezes the weekly multi-day T refit -- reporting
                        # all of them as "not enough data" hid both.
                        from ml_bias import analysis_calibration_status_message

                        print(
                            dim(
                                "  [AnalysisCal] declined — "
                                + analysis_calibration_status_message()
                            )
                        )
                except Exception as _acal_exc:
                    _log.warning("cmd_cron: analysis calibration failed: %s", _acal_exc)
                    print(dim(f"  [AnalysisCal] failed — {_acal_exc}"))

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

    # batch-64: same accumulate-then-batch-flush pattern as the two flushes
    # above. Member values are forward-only data -- a dropped buffer is a
    # permanently missing sample, not a cold cache -- so flush explicitly
    # here rather than relying solely on the atexit hook.
    try:
        from weather_markets import flush_member_values as _flush_members

        _flushed_mv = _flush_members()
        if _flushed_mv:
            print(
                dim(f"  [cron] ensemble members: {_flushed_mv} rows saved"),
                flush=True,
            )
    except Exception as _e:
        _log.warning("member values flush failed: %s", _e)

    # Sync data/ to cloud (OneDrive / Google Drive / custom path) after every cron run
    try:
        from cloud_backup import backup_data as _backup

        # batch-33 M-21: backup_data()'s bool return was discarded here --
        # batch-25 changed it to specifically surface a failed WAL-safe
        # .db copy (e.g. execution_log.db, the live-order ledger), but with
        # nothing consuming it a permanently-failing backup degraded to
        # "one WARNING per cycle, nothing else" -- the exact silent-
        # backup-failure shape batch-25 exists to eliminate, one layer up.
        # `None` means no sync folder configured at all (not a failure --
        # nothing to alert on); only `False` is a real failure.
        _backup_ok = _backup()
        if _backup_ok is False:
            _log.error(
                "cmd_cron: cloud backup completed with failures this "
                "cycle (see prior WARNING line(s) for which file, or for "
                "a snapshot that came out with no database in it)"
            )
            from notify import send_system_alert as _backup_alert

            _backup_alert(
                "Kalshi cloud backup failing",
                "cloud_backup.backup_data() returned False this cycle -- "
                "either a file failed its post-copy readability check and "
                "was not retained, or (batch-86) today's snapshot directory "
                "contains NO database at all despite .db files being present "
                "in data/, which makes it useless as a restore point. Check "
                "bot.log for the WARNING naming which.",
                cooldown_key="cloud_backup_failed",
            )
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

    # Batch-49 item 1: fee-change monitor -- once per day, fills-based $0-
    # maker-fee assert (real guard) + once per week, best-effort
    # kalshi.com/fee-schedule page watch (may never successfully fetch, see
    # _check_fee_schedule_page's own docstring). One task registration for
    # both halves of item 1, same placement/isolation rationale as
    # check_series_drift above.
    try:
        _check_fee_change(client)
        _check_fee_schedule_page()
    except Exception as _fee_task_exc:
        _log.warning("fee-change monitor task failed: %s", _fee_task_exc)

    # batch-51 item 4: weekly catalog/settlement-source drift watcher --
    # same placement rationale as check_series_drift above (after everything
    # trading-critical), but its own function/cadence since it makes a real
    # API call per known series rather than one bulk diff.
    try:
        from weather_markets import (
            check_catalog_and_settlement_drift as _check_catalog_drift,
        )

        _check_catalog_drift(client)
    except Exception as _catalog_drift_exc:
        _log.warning(
            "check_catalog_and_settlement_drift call failed: %s", _catalog_drift_exc
        )

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

    # batch-52 item 3: Miami Weather Index config_version drift watch --
    # same placement/isolation rationale as check_series_drift above, but
    # deliberately called EVERY cron cycle rather than gated to once/day or
    # once/week: the underlying HTTP call is rate-limited by kalshi_weather_
    # index.py's own 5-minute TTL cache WHILE that cache survives across
    # cycles (opus review L-9: true for main.py's `loop`/`watch --auto`
    # long-lived process modes; a one-shot `python main.py cron` invocation
    # re-fetches every time since the cache is in-memory only -- one extra
    # unauthenticated GET per invocation, negligible impact either way). A
    # methodology version change (KXTEMPMIAH's real settlement source)
    # needs to surface loudly on a timescale much tighter than this batch's
    # other daily/weekly maintenance checks -- it must not depend on a
    # Miami hourly market happening to settle (tracker.audit_settlement's
    # cross-check is the OTHER consumer of this feed, but hourly markets
    # alone don't settle often enough to guarantee timely drift detection).
    #
    # opus review L-8: like every other check in this block, this sits
    # after the kill-switch's own return path -- while the kill switch is
    # engaged (potentially for days), this drift watch is silent too, same
    # as check_series_drift/check_catalog_and_settlement_drift above.
    # Consistent with its siblings' existing behavior; accepted as a
    # documented trade-off rather than special-cased, since re-architecting
    # kill-switch/maintenance-check ordering is out of this batch's scope.
    try:
        from kalshi_weather_index import (
            check_miami_index_config_version as _check_miami_index_version,
        )

        _check_miami_index_version(client)
    except Exception as _miami_index_exc:
        _log.warning(
            "check_miami_index_config_version call failed: %s", _miami_index_exc
        )

    # batch-56: Miami nearby-station blend accuracy sample -- SHADOW ONLY.
    # Records how well an inverse-distance blend of the 8 nearest stations
    # tracks the Kalshi Weather Index versus KMIA alone, building the
    # multi-day history the graduation decision needs. Placed here (rather
    # than in run_trade_cycle alongside record_shadow_observations) because
    # its population is weather stations and the index feed, not the cycle's
    # market list -- it has no dependency on markets having been fetched.
    #
    # record_shadow_sample() never raises; the outer try/except exists only
    # for a failure ABOVE it (e.g. the import). WARNING not DEBUG, same
    # reasoning as its siblings: a permanently-broken recorder must not go
    # unnoticed for months.
    #
    # Cost, stated accurately (an earlier version of this comment claimed
    # "at most one cached round-trip", which is wrong for the dominant
    # deployment mode): both of the module's caches are IN-MEMORY only, so
    # they help a long-lived `loop`/`watch --auto` process but never a
    # one-shot `python main.py cron`, which pays three fresh HTTP calls
    # (NWS /points, NWS /stations, aviationweather /metar) plus the index
    # fetch every invocation -- the same in-memory-only caveat
    # kalshi_weather_index's own comment above records for itself. The
    # module's timeouts are sized so the worst case stays well inside
    # _install_cron_watchdog's hard-kill window; it is placed last in this
    # block so a slow upstream delays only the "scan complete" line.
    #
    # Shares its siblings' documented post-kill-switch placement trade-off --
    # while the kill switch is engaged this collector is silent too. Accepted
    # rather than special-cased: a paused bot has no live trading for this
    # shadow signal to inform anyway.
    try:
        from nearby_station_obs import record_shadow_sample as _record_nearby_sample

        _record_nearby_sample(client)
    except Exception as _nearby_obs_exc:
        _log.warning("record_shadow_sample call failed: %s", _nearby_obs_exc)

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

    Opus-review-noted (F12, batch-24): notify.send_system_alert()'s
    reserve/rollback retries delivery (all configured channel timeouts,
    ~30s worst case) on EVERY call during a sustained network outage,
    where the old cooldown-always-burns behavior would have limited that
    to once per 6h per cooldown_key. With several distinct keys firing the
    same cycle (kill_switch, cron_gap, halt_daily_loss, halt_drawdown, one
    circuit_open:<name> per tripped source), the cumulative worst case
    could approach this watchdog's timeout. Accepted: still well under the
    default 8 minutes for the realistic number of simultaneously-active
    alert keys, and the alternative (silently losing an alert during
    exactly the outage that most needs one, batch-24 item 3) is worse.

    batch-33 M-1 adds a second, compounding retry source on top of the
    above: alerts.check_halt_transition's own false->true edge is now ALSO
    rolled back on total delivery failure (previously the halt flag stayed
    persisted regardless, so a repeat cycle's observation stopped
    reporting a fresh edge at all and never re-attempted delivery). During
    a sustained outage with multiple halts simultaneously engaged
    (anomaly, drawdown/drawdown_paper, daily_loss/daily_loss_paper), each
    now retries its own full channel-timeout delivery attempt every single
    cycle, not just once. Same acceptance reasoning as above still
    applies -- bounded by the same realistic key count, and correct alert
    delivery outweighs the added latency -- but the two retry sources now
    stack, worth knowing if this watchdog's timeout is ever tuned down.
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
                # batch-24 item 1: skip the write while the kill switch is
                # engaged. Unconditionally rewriting this file every cycle
                # reset the dead-man's-switch gap to ~0 on every
                # kill-switch-aborted run, so the 48h gap alert could never
                # fire no matter how long the switch stayed engaged. Leaving
                # the timestamp stale lets that gap grow correctly; the next
                # cycle after the switch is cleared resumes normal writes.
                if not KILL_SWITCH_PATH.exists():
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
                #
                # batch-33 M-5: this used to key ONLY off the `sameday_only`
                # ARGUMENT, ignoring `_full_scan` -- the actual "a full scan
                # completed" outcome computed above. A kill-switch abort,
                # black-swan abort, engine-kill, or a cycle that crashed
                # inside _cmd_cron_body all leave `_full_scan` False (see
                # its own early-return sites, all `return None`), but with
                # sameday_only=False (the normal case) this block still
                # stamped a FRESH last_full_scan anyway -- so all three
                # staleness alarms (main's banner, cron_full_scan_gap,
                # cron_gap) stayed silent no matter how long cron kept
                # failing every cycle. Key off `_full_scan` instead --
                # mirrors the kill-switch freeze already applied to
                # CRON_LAST_RUN_PATH just above.
                if sameday_only or not _full_scan:
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
            # batch-69 item 1: the one alert-rule evaluation pass per cycle.
            #
            # Placed in this `finally`, not at the end of _cmd_cron_body, on
            # purpose: the body has several `return None` early exits (kill
            # switch, black swan, engine kill) and can raise, and those are
            # exactly the cycles an operator most needs an alert out of. Put
            # here it runs on every path.
            #
            # Placed AFTER ctx.release_cron_lock() equally deliberately:
            # evaluation does DB reads and up to five channels' worth of
            # network sends, and none of that needs the cron lock. Holding it
            # across the sends would extend every cycle's lock window by the
            # channels' combined timeouts for no benefit.
            #
            # Fully no-ops unless ALERT_RULES_ENABLED is set (default off) --
            # see alerts.evaluate_alert_rules. cron_gap is not evaluated from
            # here by design; only cmd_alert_check() can honestly evaluate it.
            #
            # TWO EXPOSURES THIS ADDS, both opus-review-raised and accepted:
            #
            # (M-3) `_cron_done_event` is set in the OUTER finally, so this
            # runs while the hard-kill watchdog is still armed. Worst case
            # with all five channels configured is roughly 30-60s per
            # delivery, and the rollback guarantees a retry every cycle
            # during a network outage. `CRON_WATCHDOG_SECS` defaults to 720
            # here, and the cycle is already finished (lock released, every
            # state file written) by this point, so a watchdog kill costs a
            # duplicate exit rather than corrupt state. Bounded further by
            # ALERT_RULES_ENABLED defaulting off.
            #
            # (L-12) Every pre-existing cron alert fired while holding the
            # cron lock; this one deliberately does not. Two cron processes
            # can therefore interleave here. notify's cooldown lock is
            # thread-level only and explicitly does not span processes, and
            # the drawdown edge is a read-then-write on the DB, so a
            # duplicate delivery or a lost state update is possible. Sub-
            # millisecond window for the cooldown, wider for the state write;
            # this project's operating model runs one cron cycle at a time.
            #
            # KNOWN, ACCEPTED GAP: main.cmd_cron has a SECOND kill-switch
            # branch of its own, the interactive `not _called_from_loop`
            # override prompt, which returns before this function is ever
            # called -- so declining that prompt evaluates nothing and writes
            # no delivery row. Left alone deliberately: that branch already
            # fires its own kill-switch alert under this same "kill_switch"
            # cooldown key (batch-24 item 1), and it is by construction a
            # session with an operator reading the halt off the screen. Every
            # unattended path -- scheduled cron, `loop`, and every early
            # return inside _cmd_cron_body -- reaches this hook. Covered by
            # tests/test_cron_integration.py::TestBatch69AlertRuleHook.
            try:
                from alerts import evaluate_alert_rules as _eval_alert_rules

                _alert_summary = _eval_alert_rules(trigger_source="cycle")
                # opus-review-caught (M-7): the summary used to be discarded,
                # so a rule whose predicate raises every cycle was invisible
                # here -- only cmd_alert_check printed errors, and it is not
                # scheduled. Log it at the same level of detail
                # cmd_alert_check does.
                if _alert_summary and not _alert_summary.get("skipped_disabled"):
                    _log.info(
                        "cmd_cron: alert rules evaluated=%d fired=%d delivered=%d "
                        "suppressed=%d failed=%d",
                        _alert_summary.get("evaluated", 0),
                        len(_alert_summary.get("fired", [])),
                        _alert_summary.get("delivered", 0),
                        _alert_summary.get("suppressed", 0),
                        _alert_summary.get("failed", 0),
                    )
                    for _rule_err in _alert_summary.get("errors", []):
                        _log.warning("cmd_cron: alert rule error: %s", _rule_err)
            except Exception as _alert_rules_exc:
                _log.warning(
                    "cmd_cron: alert rule evaluation failed: %s", _alert_rules_exc
                )
        if _full_scan and not getattr(cmd_cron, "_called_from_loop", False):
            _sys.exit(0)
    finally:
        _cron_done_event.set()


def cmd_alert_check(dry_run: bool = False) -> dict:
    """batch-69 item 1: the OUT-OF-BAND alert evaluation pass.

    This is the entry point that exists so `cron_gap` can be evaluated by
    something other than the cron cycle it watches. cmd_cron's own 48h
    dead-man's-switch runs at cycle START, which means it only ever reports a
    gap once cron has already come back and says nothing at all for the whole
    outage — the rule that most needs to fire while the bot is down is the one
    structurally guaranteed not to. Driving THIS from its own scheduler entry,
    independent of the cron task, is what fixes that.

    Deliberately NOT registered with any scheduler by this batch (confirmed
    with the user, 2026-08-25: nothing auto-runs until the design has been
    reviewed), and `cron_gap` correspondingly ships with enabled=0. Register
    it the same way cmd_schedule_cycles() prints the cron entries, then flip
    the rule on.

    `dry_run=True` evaluates every enabled rule and records what WOULD have
    been sent (status="dry_run") without contacting a single channel, and
    without consuming any edge-triggered rule's state. That works even while
    ALERT_RULES_ENABLED is unset, which is the intended way to read real
    evaluation output before the first real message is ever delivered.

    Returns evaluate_alert_rules()'s summary dict.
    """
    from alerts import ALERT_RULES_ENABLED_ENV, alert_rules_enabled
    from alerts import evaluate_alert_rules as _eval_alert_rules

    summary = _eval_alert_rules(trigger_source="external", dry_run=dry_run)

    if summary.get("skipped_disabled"):
        _log.info(
            "cmd_alert_check: %s is not set — nothing evaluated. "
            "Use --dry-run to see what would fire.",
            ALERT_RULES_ENABLED_ENV,
        )
    else:
        _log.info(
            "cmd_alert_check: evaluated=%d fired=%d delivered=%d suppressed=%d "
            "failed=%d dry_run=%s enabled=%s",
            summary.get("evaluated", 0),
            len(summary.get("fired", [])),
            summary.get("delivered", 0),
            summary.get("suppressed", 0),
            summary.get("failed", 0),
            dry_run,
            alert_rules_enabled(),
        )
    for err in summary.get("errors", []):
        _log.warning("cmd_alert_check: %s", err)
    return summary
