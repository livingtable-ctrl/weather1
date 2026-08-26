"""
Desktop toast notifications for strong trade signals.
Uses plyer for cross-platform support (Windows/macOS/Linux).
Silently skips if plyer is not installed.

Also supports Pushover (PUSHOVER_TOKEN + PUSHOVER_USER env vars)
and ntfy.sh (NTFY_TOPIC env var).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time

from paths import NOTIFY_COOLDOWN_STATE_PATH
from paths import NOTIFY_TEMPLATES_PATH as _TEMPLATES_PATH
from safe_io import atomic_write_json

try:
    import requests as _requests

    _DISCORD_AVAILABLE = True
except ImportError:
    _requests = None  # type: ignore[assignment]
    _DISCORD_AVAILABLE = False

try:
    from plyer import notification as _notif

    _ENABLED = True
except Exception:
    _ENABLED = False

_log = logging.getLogger(__name__)

# #123: allow selective enable/disable of notification channels
# Set NOTIFY_CHANNELS=discord,email to only use those two, etc.
# batch-33 L-4: strip/lower each token -- "discord, email" (a leading space
# after the comma, easy to type by hand) previously produced the literal
# member " email" with a leading space, which matches none of the `in
# _CHANNELS` checks below and silently dropped the channel entirely,
# defeating batch-24's "all configured channels get a delivery attempt"
# guarantee. Also warn on an unrecognized name so a typo doesn't silently
# do nothing either.
_KNOWN_CHANNELS = {"desktop", "pushover", "ntfy", "discord", "email"}
_CHANNELS = {
    c.strip().lower()
    for c in os.getenv("NOTIFY_CHANNELS", "desktop,pushover,ntfy,discord,email").split(
        ","
    )
    if c.strip()
}
_unknown_channels = _CHANNELS - _KNOWN_CHANNELS
if _unknown_channels:
    _log.warning(
        "notify: NOTIFY_CHANNELS contains unrecognized channel name(s) %s "
        "-- known channels are %s",
        sorted(_unknown_channels),
        sorted(_KNOWN_CHANNELS),
    )

# #94: load custom templates from data/notify_templates.json if present.
# Keys: "strong_signal_title", "strong_signal_body" (Python format strings).
# Fall back to built-in strings if file is absent or malformed.
_TEMPLATES: dict = {}
try:
    if _TEMPLATES_PATH.exists():
        _TEMPLATES = json.loads(_TEMPLATES_PATH.read_text())
except Exception as exc:
    _log.warning("notify: failed to load notify_templates.json: %s", exc)

# #95: per-ticker throttle — suppress repeat notifications within this window.
# In-process only by design: alert_strong_signal() only ever runs inside
# `watch`/`watch --auto`'s long-lived loop, never a fresh one-shot cron
# process. Its real duplicate-alert guard is `previous_tickers` (main.py's
# `_load_watch_state()`/`_save_watch_state()`, data/.watch_state.json --
# CORRECTED 2026-07-31, opus review: this IS disk-persisted, unlike what an
# earlier draft of this comment claimed). Deliberately still not extending
# disk persistence to this dict in the same pass as the fix below: that was
# an explicit, separately-confirmed scope decision (send_system_alert()
# only), not something this correction reopens -- see backlog.txt "NOTIFY.
# SEND_SYSTEM_ALERT()'S COOLDOWN IS IN-PROCESS MEMORY ONLY" for the full
# scoping discussion. See send_system_alert()'s _system_cooldown_reserve()
# below for the disk-persisted sibling used by system alerts.
_NOTIFY_COOLDOWN_SECS = int(os.getenv("NOTIFY_COOLDOWN_SECS", "300"))  # 5 min default
_last_notified: dict[str, float] = {}  # ticker -> last fire timestamp


# ---------------------------------------------------------------------------
# Desktop-toast field limits (batch-80 item 2; backlog.txt "A SYSTEM ALERT
# LONGER THAN 256 CHARACTERS CRASHES THE DESKTOP-TOAST BACKEND").
#
# plyer's Windows backend packs the toast into a NOTIFYICONDATAW struct whose
# string members are fixed-width ctypes WCHAR arrays. Assigning a longer
# Python string raises ValueError("string too long") from ctypes, inside
# get_NOTIFYICONDATAW. Verified against the installed plyer on 2026-08-25
# (plyer/platforms/win/libs/win_api_defs.py:52-68):
#
#     szTip       WCHAR * 128   <- app_name  (hardcoded "Kalshi Weather")
#     szInfo      WCHAR * 256   <- message
#     szInfoTitle WCHAR *  64   <- title
#
# THE TITLE LIMIT IS 64, NOT 256. The backlog entry only names the 256-char
# message cap, but szInfoTitle is four times tighter and fails identically --
# a title is simply the likelier of the two to already be short. Both are
# capped here.
#
# Why truncating is still the right fix -- REVISED batch-84 item 1, because
# the Windows path no longer goes through plyer's facade at all.
# WindowsNotification._notify is `thread(target=balloon_tip, ...).start()`,
# so the ValueError is raised on a thread plyer spawns and a wrapper around
# _notif.notify() could never see it. This block used to conclude from that
# "there is no wrapper this module can add that catches it", which was true
# of a facade wrapper but not of the module as a whole: _desktop_notify()
# below now calls balloon_tip on a thread THIS module owns and catches it.
#
# Truncation is still the fix for over-long text, because catching the
# ValueError only turns a silently-lost toast into a correctly-REPORTED lost
# toast. Not sending an over-long string is what actually delivers it.
#
# One unit is reserved for the NUL terminator: ctypes accepts a string of
# exactly the array length (measured -- 256 raises nothing, 257 raises), but
# stores it with no terminator, and Shell_NotifyIconW reads until one. At
# exactly 256 it would read on into the adjacent uVersion field.
#
# UNITS, NOT CHARACTERS. A WCHAR array counts UTF-16 code units, so every
# character above U+FFFF costs two -- 129 emoji raise
# ValueError("string too long (258, maximum length 256)") despite len() 129.
# _truncate_for_desktop budgets in units for that reason; see its own note.
#
# These bounds are the Windows struct's. macOS and Linux backends have their
# own (looser) limits; truncating everywhere costs a few characters on those
# platforms and keeps one code path.
DESKTOP_MESSAGE_MAX = 255
DESKTOP_TITLE_MAX = 63


def _utf16_units(text: str) -> int:
    """Length of `text` in UTF-16 code units -- what a WCHAR array counts.

    ctypes measures a `WCHAR * N` field in UTF-16 code units, not Python
    characters, so any character above U+FFFF costs two. len() and this
    function agree for all-BMP text and diverge exactly where the crash is.

    "surrogatepass" because a bare utf-16-le encode REJECTS an unpaired
    surrogate while ctypes accepts one -- both measured. Without it this
    helper would raise UnicodeEncodeError on input the field would happily
    have taken, which is a failure mode the earlier len()-based version did
    not have, and a reachable one: notify_templates.json is operator-editable
    and JSON permits a lone escaped surrogate, which json.loads turns into a
    real one. Each counts as one unit, which is what ctypes stores.
    """
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _truncate_for_desktop(text: str, limit: int, field: str) -> str:
    """Clip `text` to `limit` UTF-16 code units for the toast, logging if so.

    Returns `text` unchanged when it already fits, so the common case is
    untouched and the log line only appears when something was actually
    dropped -- the current behaviour loses the desktop half of an alert with
    no record at all, which is the substance of the entry.

    Only the DESKTOP copy is clipped. Discord, Pushover, ntfy and email are
    each passed the full original text by both call sites, so this can never
    shorten an alert on a channel that could have carried it.
    """
    if not isinstance(text, str):
        # Defensive: this module's alerting path is the last place a
        # surprise TypeError is acceptable (same reasoning as
        # send_system_alert_detailed's cooldown_secs coercion).
        text = str(text)
    # Hygiene: unreachable with this module's 255/63 constants, but a limit
    # of 0 or 1 would make the text[: limit - 1] slice below produce a
    # LONGER string than it was given.
    #
    # The single kept character is UNIT-checked, not just sliced: at limit 1
    # an astral first character is one code point but TWO units, so a bare
    # text[:1] would return something over the very budget this guard exists
    # to respect -- and strictly worse than the unguarded path, which
    # returned a 1-unit ellipsis. Found by a fuzz sweep in round-2 review.
    if limit <= 1:
        head = text[:1]
        return head if limit == 1 and _utf16_units(head) <= 1 else ""

    original = _utf16_units(text)
    if original <= limit:
        return text
    _log.warning(
        "desktop notify: %s truncated from %d to %d UTF-16 units for the "
        "Windows toast field limit -- the full text was still sent to every "
        "other configured channel",
        field,
        original,
        limit,
    )
    # Clip by UTF-16 UNITS, not by Python characters, and never mid-pair.
    # The budget must be counted the way the struct counts: a WCHAR array of
    # 256 holds 256 UTF-16 code units, and every non-BMP character (an emoji,
    # most obviously) occupies TWO of them. A 129-emoji string has len() 129
    # but raises ValueError("string too long (258, maximum length 256)") --
    # measured, not assumed -- so a code-point budget would let the exact
    # original bug back in on plyer's uncatchable thread. Latent today (no
    # source file in this repo contains a character above U+FFFF), but
    # notify_templates.json is operator-editable and both templates .format()
    # in external `city` and `ticker` strings, which is the same reasoning
    # that made alert_strong_signal's call site worth capping at all.
    #
    # The ellipsis is spent INSIDE the budget, not appended to it -- appending
    # would re-cross the limit and reintroduce the ValueError. U+2026 is BMP,
    # so it costs exactly one unit.
    out: list[str] = []
    used = 0
    for ch in text:
        width = 2 if ord(ch) > 0xFFFF else 1
        if used + width > limit - 1:
            break
        out.append(ch)
        used += width
    return "".join(out) + "…"


# ---------------------------------------------------------------------------
# Desktop delivery confirmation (batch-84 item 1; backlog.txt "NOTIFY.PY
# RECORDS THE DESKTOP CHANNEL AS DELIVERED WHENEVER PLYER'S notify()
# RETURNS, BUT ON WINDOWS THAT ONLY MEANS 'A THREAD WAS STARTED'").
#
# plyer's Windows backend, in full (verified against plyer 2.1.0,
# plyer/platforms/win/notification.py):
#
#     class WindowsNotification(Notification):
#         def _notify(self, **kwargs):
#             thread(target=balloon_tip, kwargs=kwargs).start()
#
# Fire-and-forget. Everything that can fail -- GetModuleHandleW ("Could not
# get windows module instance."), RegisterClassExW, CreateWindowExW, either
# Shell_NotifyIconW ("Shell_NotifyIconW failed."), and the fixed-width WCHAR
# assignment the block above exists to avoid -- raises on plyer's OWN
# thread, where the caller's `except Exception` can never see it. So
# `successes.append(True)` ran unconditionally and a desktop toast that
# never appeared was recorded as delivered.
#
# That is not cosmetic here. send_system_alert() returns `status !=
# "failed"`, and alerts.check_halt_transition/rollback_halt_transition use a
# False return to roll edge-triggered halt state back so the NEXT cycle
# retries instead of treating a lost alert as done. A phantom True defeats
# exactly that, and the "all N channel(s) failed" warning below can never
# fire on a desktop-only failure.
#
# Why not simply stop appending True. Measured 2026-08-26 against this
# deployment's .env: NTFY_TOPIC, PUSHOVER_TOKEN/USER, DISCORD_WEBHOOK_URL(S)
# and SMTP_* are ALL unset, so desktop is the only channel that can succeed
# and its True is the only reason send_system_alert() ever returns True
# today. Recording it as False UNCONDITIONALLY would make every system alert
# "failed" -- cooldown rolled back, halt-transition state rolled back -- and
# re-fire the same alert every cron cycle even when the toast was appearing
# perfectly well. That trades a phantom success for a phantom failure.
# Owning the thread gives a REAL answer instead of picking which lie to tell.
#
# WHAT THIS DOES NOT PROMISE (opus review M-3). If the toast backend fails
# PERSISTENTLY, retry-forever is the outcome, and that is correct rather
# than a bug: with desktop the only configured channel, a genuinely dead
# backend means nothing reaches the operator, and the per-cycle WARNING in
# bot.log is then the only signal that anything is wrong. What changes is
# that the retry is now driven by a real observation instead of never
# happening at all. The realistic way to enter that state is the planned VM
# / Scheduled-Task move: a session-0 non-interactive process has no tray for
# Shell_NotifyIconW to talk to. backlog.txt "[MOVE OFF LOCAL CRON -- HOST ON
# A SMALL ALWAYS-ON VM]" already calls for dropping "desktop" from
# NOTIFY_CHANNELS and configuring Pushover/Discord/email as part of that
# move -- that, not anything in this file, is the actual fix.
#
# macOS and Linux need none of this: OSXNotification._notify and all three
# Linux implementations run synchronously, so their exceptions already reach
# the caller's except. _WIN_BALLOON_TIP is None there and the plyer facade is
# called exactly as before.
# ---------------------------------------------------------------------------
def _resolve_win_balloon_tip():
    """Return plyer's Windows ``balloon_tip``, or None on any other backend.

    Gated on plyer's OWN platform token (plyer.utils.platform), not
    sys.platform directly, so this tracks whatever backend plyer's Proxy
    would actually dispatch to rather than a second, parallel guess. Any
    import failure resolves to None, which falls back to the facade call --
    a plyer upgrade that moves or renames this private module degrades to
    the pre-batch-84 behaviour instead of breaking alerting outright.

    The platform guard is not redundant with that except (opus review I-4):
    on a non-Windows host the win import fails anyway, but noisily -- the
    guard is what keeps a Linux/macOS process from logging a WARNING about a
    backend it was never going to use. Pinned by
    test_a_non_windows_platform_resolves_to_none_without_warning.
    """
    try:
        from plyer.utils import platform as _plyer_platform

        if str(_plyer_platform) != "win":
            return None
        from plyer.platforms.win.libs.balloontip import balloon_tip

        return balloon_tip
    except Exception as exc:  # pragma: no cover - platform/packaging specific
        _log.warning(
            "notify: could not load plyer's Windows balloon_tip (%s) -- desktop "
            "delivery will be reported optimistically, as it was before",
            exc,
        )
        return None


# Resolved eagerly, and NOT additionally gated on `"desktop" in _CHANNELS`
# (opus review L-8 raised the gating as a small saving). Deliberate: the
# saving is ~10 windll entry-point lookups in a Windows process that has
# disabled desktop notifications and would import the same module anyway on
# any facade call -- while binding this constant to _CHANNELS would make the
# two disagree the moment anything rebinds _CHANNELS after import (every
# test in this repo's desktop suite does), silently leaving the Windows path
# disabled while the channel looks enabled. A gate and its enforcement have
# to share a binding; here they would not.
_WIN_BALLOON_TIP = _resolve_win_balloon_tip() if _ENABLED else None

# How long to wait for the toast thread to fail before calling it delivered.
#
# This is a FAILURE-DETECTION window, not a completion deadline, and it can
# only ever be too short -- never wrong in the unsafe direction.
# WindowsBalloonTip.__init__ does its window/icon/Shell_NotifyIconW work and
# THEN sleeps `timeout` seconds (10 here), so the thread is still alive at
# the end of a successful call by construction; a clean join within the
# window is impossible. Every failure mode above raises before that sleep,
# in ctypes/Win32 calls that complete in well under a millisecond, so 0.5s
# is orders of magnitude of headroom. If a pathologically busy shell ever
# did push a genuine failure past it, this reports True and we are exactly
# where the code was before this change -- degraded, never spamming.
#
# The cost is 0.5s of latency on each desktop alert that is actually sent.
# The cooldowns bound repeats of the SAME alert, not the number of distinct
# alerts in one pass, so the honest figure is N x 0.5s wherever N alerts fire
# in a loop (opus review L-4, correcting an earlier "not on any hot path"):
#
#   - order_executor._park_stale_unknown_order builds a per-ROW cooldown key
#     (f"unresolved_live_order:{row_id}"), and _recover_pending_orders calls
#     it once per stranded row at the start of a cron cycle. Its own comment
#     cites "an outage strands four rows in one pass" -- 2s.
#   - alert_strong_signal's key is the ticker, and both call sites
#     (main.py's _analyze_once loop and `watch --auto`'s liquid_opps loop)
#     iterate markets, so a cycle with N newly-STRONG tickers adds N x 0.5s.
#
# No call site holds a lock across it (AST-checked across cron.py, main.py,
# order_executor.py, alerts.py, trade_cycle.py, kalshi_client.py,
# kalshi_weather_index.py, tracker.py, execution_log.py, web_app.py), and
# none is on the live order-PLACEMENT path -- the nearest,
# order_executor.py's mid-cycle drawdown alert, is followed immediately by
# `break`. The cron lock is already held for the whole multi-minute cycle,
# so seconds there are irrelevant; the one place a human would notice is an
# interactive `analyse` render.
#
# No env override, deliberately (opus review I-5 suggested one for a
# headless operator): a second binding for the same value is how a gate and
# its enforcement drift apart, and the headless case wants a working
# channel, not a faster way to mis-report a broken one.
DESKTOP_CONFIRM_SECS = 0.5


def _desktop_notify(title: str, message: str) -> bool:
    """Send one desktop toast; return whether it actually got sent.

    Raises whatever the synchronous (macOS/Linux) plyer backends raise --
    both call sites already wrap this in the try/except that has always
    handled that case. On Windows the BACKEND's exception is suppressed and
    reported as False instead, but this function is still not raise-free
    there (opus review L-7): _truncate_for_desktop runs before the branch on
    both paths, and Thread.start() can raise RuntimeError under thread
    exhaustion. Both call sites keep their try/except for exactly that.
    """
    kwargs = {
        "title": _truncate_for_desktop(title, DESKTOP_TITLE_MAX, "title"),
        "message": _truncate_for_desktop(message, DESKTOP_MESSAGE_MAX, "message"),
        "app_name": "Kalshi Weather",
        "timeout": 10,
    }

    tip = _WIN_BALLOON_TIP
    if tip is None:
        _notif.notify(**kwargs)
        return True

    failures: list[BaseException] = []

    def _run() -> None:
        try:
            tip(**kwargs)
        except BaseException as exc:  # noqa: BLE001 - see below
            # BaseException, not Exception: the entire point is that nothing
            # escapes this thread uncaught the way it did through plyer's.
            # An escaping BaseException surfaces only as pytest's
            # PytestUnhandledThreadExceptionWarning or, in a `py main.py`
            # process, as a THREAD EXCEPTION block in data/crash.log written
            # by main.py's threading.excepthook -- and as nothing at all in
            # any process that does not go through main.py.
            failures.append(exc)
            # LOG HERE, not after the join (opus review M-1). The join
            # ALWAYS times out on the success path by construction, so a
            # failure raised after the confirm window would otherwise be
            # appended to a list nobody reads and recorded nowhere -- worse
            # than the pre-batch-84 state, which at least reached main.py's
            # crash log. Logging at the catch means a late failure still
            # lands in bot.log even though this call already returned True.
            _log.warning(
                "desktop notify: the Windows toast backend failed (%s: %s) -- "
                "the alert was NOT delivered on this channel",
                type(exc).__name__,
                exc,
            )

    # daemon is left to inherit from the calling thread, exactly as plyer's
    # own bare `thread(target=balloon_tip, kwargs=kwargs)` does, so process
    # shutdown behaviour is unchanged by this fix. Pinned by
    # test_the_worker_thread_inherits_the_callers_daemon_flag.
    worker = threading.Thread(target=_run, name="kalshi-desktop-toast")
    worker.start()
    worker.join(DESKTOP_CONFIRM_SECS)

    return not failures


# backlog.txt "NOTIFY.SEND_SYSTEM_ALERT()'S COOLDOWN IS IN-PROCESS MEMORY
# ONLY": send_system_alert()'s own cooldown, unlike the per-ticker one above,
# is persisted to disk so it survives across separate process invocations
# (manual or scheduled cron runs), not just within one long-lived process.
# This lock is THREAD-level protection only (matches circuit_breaker.py's
# own scope for its equivalent lock -- concurrent threads in one process,
# plus avoiding a transient Windows PermissionError mid-os.replace) -- two
# separate `py main.py cron` PROCESSES each hold their own independent
# Lock object, so this does NOT serialize across processes (corrected
# 2026-07-31, opus review: an earlier draft of this comment overclaimed
# cross-process protection). Real cross-process races are not expected in
# this codebase's actual operating model (manual, sequential invocation
# today; a future scheduler would still run one cron cycle at a time), so a
# true cross-process file lock (e.g. msvcrt.locking or an O_EXCL lockfile)
# is deliberately not built here -- would be new, untested infrastructure
# for a risk this project doesn't currently have.
_NOTIFY_COOLDOWN_FILE_LOCK = threading.Lock()


def _read_cooldown_state() -> tuple[dict, bool]:
    """Load the persisted cooldown state dict. Returns (state, ok) -- ok is
    False on any read/parse error (missing key handling is the caller's job;
    an empty-but-ok `{}` is the normal "no cooldown file yet" case)."""
    try:
        state = (
            json.loads(NOTIFY_COOLDOWN_STATE_PATH.read_text())
            if NOTIFY_COOLDOWN_STATE_PATH.exists()
            else {}
        )
        if not isinstance(state, dict):
            raise ValueError(
                f"cooldown state must be a dict, got {type(state).__name__}"
            )
        return state, True
    except Exception as exc:
        _log.warning(
            "notify: failed to load persisted cooldown state (failing open, "
            "not writing to avoid clobbering other keys): %s",
            exc,
        )
        return {}, False


def _write_cooldown_state(state: dict) -> None:
    try:
        # No explicit parent .mkdir() here -- atomic_write_json() already
        # does path.parent.mkdir(parents=True, exist_ok=True) as its own
        # first step (safe_io.py), so a second call here was redundant
        # (opus review, 2026-07-31).
        atomic_write_json(state, NOTIFY_COOLDOWN_STATE_PATH)
    except Exception as exc:
        _log.warning("notify: failed to persist cooldown state: %s", exc)


def _system_cooldown_reserve(
    cooldown_key: str, now: float, cooldown_secs: float
) -> tuple[bool, float]:
    """Check send_system_alert()'s persisted cooldown for `cooldown_key` and,
    if elapsed, atomically RESERVE it by recording `now` as the new
    last-fired timestamp -- read, decision, and write all happen under one
    lock acquisition (matching circuit_breaker.py's established _save_state()
    pattern) rather than two separate acquisitions, so a second THREAD in the
    same process racing on the same key can't both see the cooldown as
    elapsed (see the lock's own comment above for why this does NOT cover
    concurrent processes).

    Returns (reserved, previous_value) -- `reserved` is True iff the caller
    may proceed to attempt delivery; when True, `previous_value` is whatever
    was persisted before this call (0.0 if the key was unseen) so the caller
    can roll the reservation back via _system_cooldown_rollback() if delivery
    ends up failing on every channel (backlog.txt "SEND_SYSTEM_ALERT()'S
    COOLDOWN IS CONSUMED BEFORE DELIVERY IS ATTEMPTED" -- previously this
    function persisted unconditionally on every elapsed check, so a total
    delivery failure during exactly the kind of outage that most needs an
    alert also burned the 6h cooldown with nothing actually delivered).

    Fails OPEN (returns (True, 0.0), allowing the alert to fire; and
    deliberately does NOT attempt to write, to avoid clobbering every OTHER
    caller's already-persisted cooldown with a blind blank-state overwrite)
    on any read/parse error -- a missing, corrupt, or unexpected-shape (valid
    JSON that isn't a dict, e.g. `null`) cooldown file must never silently
    suppress a real system alert. This is a deliberate, freestanding choice
    for an alerting path specifically (better to double-alert than to ever
    silently miss a real one) -- NOT modeled on paper.is_accuracy_halted(),
    which actually fails CLOSED for its own, different reason (corrected
    2026-07-31, opus review: an earlier draft of this docstring cited that
    function as a fail-open precedent, backwards from its real behavior). A
    write failure (state was read successfully, just couldn't be saved) is
    logged but still lets the alert fire this time; if writes keep failing,
    the cooldown silently stops persisting and this degrades back to the
    original in-process-only behavior -- a known, accepted residual risk
    (not fixed here: `atomic_write_json`'s own emergency-copy fallback and
    the existing `.emergency/` monitor, cooldown_key="emergency_copy", would
    independently surface a *sustained* write failure of this kind via a
    separate alert, so this isn't a fully silent failure mode in practice).
    """
    with _NOTIFY_COOLDOWN_FILE_LOCK:
        state, ok = _read_cooldown_state()
        if not ok:
            return True, 0.0
        last = state.get(cooldown_key, 0.0)
        # opus-review-caught (2nd round, MEDIUM-1): `last` comes straight
        # from JSON with no type check -- a hand-edited or otherwise
        # corrupt non-numeric persisted value (e.g. a stray string) made
        # `now - last` raise TypeError out of this function, out of
        # send_system_alert(), and into 3 call sites (cron.py/trade_cycle.py/
        # main.py's kill-switch checks) that rely on this function's own
        # documented "Never raises" contract and don't wrap it themselves.
        # Treat an invalid value the same as an unseen key (fail open).
        if isinstance(last, bool) or not isinstance(last, int | float):
            last = 0.0
        if now - last < cooldown_secs:
            return False, last
        state[cooldown_key] = now
        _write_cooldown_state(state)
        return True, last


def _system_cooldown_rollback(
    cooldown_key: str, reserved_value: float, previous_value: float
) -> None:
    """Undo a _system_cooldown_reserve() reservation after every delivery
    channel failed, so the NEXT call (not a concurrent one -- see below)
    isn't blocked by a cooldown burned on an alert nothing actually received.

    Only rolls back if the persisted value is still exactly what this
    reservation wrote (`reserved_value`) -- if a different call has since
    reserved a newer timestamp for the same key (a legitimate later alert,
    or a concurrent thread that read the rolled-back state before this
    function's lock acquisition), this is a no-op rather than clobbering
    that newer reservation. Removes the key entirely (rather than writing
    back `previous_value`) when the key had no prior record (`previous_value
    == 0.0`), so a never-fired key returns to genuinely "not in the file" --
    the same fail-open default `_system_cooldown_reserve` already treats an
    absent key as, and consistent with never having reserved it at all.
    """
    with _NOTIFY_COOLDOWN_FILE_LOCK:
        state, ok = _read_cooldown_state()
        if not ok:
            return
        if state.get(cooldown_key) != reserved_value:
            return
        if previous_value == 0.0:
            state.pop(cooldown_key, None)
        else:
            state[cooldown_key] = previous_value
        _write_cooldown_state(state)


def clear_system_cooldown(cooldown_key: str) -> None:
    """Remove a persisted send_system_alert() cooldown key so the NEXT
    engagement of that alert type fires immediately instead of waiting out
    the rest of a stale 6h window.

    For alert types whose underlying condition has an explicit operator
    "resolved" action (e.g. `py main.py resume` clearing black-swan state),
    that action should call this so a genuinely NEW occurrence within the
    same 6h window isn't silently swallowed by a cooldown that was reserved
    for the PREVIOUS, now-resolved occurrence (opus-review-caught, batch-24:
    activate_black_swan_halt's cooldown_key="black_swan_halt" would
    otherwise suppress a second, distinct black-swan halt that trips soon
    after an operator investigates and resumes from the first one).
    """
    with _NOTIFY_COOLDOWN_FILE_LOCK:
        state, ok = _read_cooldown_state()
        if not ok or cooldown_key not in state:
            return
        state.pop(cooldown_key, None)
        _write_cooldown_state(state)


def _send_pushover(title: str, message: str) -> bool:
    """
    Send via Pushover API.
    Requires PUSHOVER_TOKEN and PUSHOVER_USER in env.
    Returns True if sent successfully.
    """
    token = os.getenv("PUSHOVER_TOKEN")
    user = os.getenv("PUSHOVER_USER")
    if not token or not user:
        return False
    try:
        import urllib.parse
        import urllib.request

        data = urllib.parse.urlencode(
            {"token": token, "user": user, "title": title, "message": message}
        ).encode()
        req = urllib.request.Request(
            "https://api.pushover.net/1/messages.json",
            data=data,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ascii_header_value(value: str) -> str:
    """Reduce a string to something safe to put in an HTTP header.

    HTTP headers are latin-1 in urllib, so ANY character outside that range
    raises UnicodeEncodeError at request-build time. Found 2026-08-25
    (batch-69): `_send_ntfy` puts the alert title straight into the `Title`
    header, and its bare `except Exception: return False` swallowed that
    exception whole -- so ntfy silently failed, and reported failure, for
    every alert whose title contained a non-latin-1 character. That is not
    hypothetical: `activate_black_swan_halt`'s "⚠ BLACK SWAN HALT
    ACTIVATED" and cron.py's "⚠️ Brier Score Alert" both contain
    U+26A0, which is outside latin-1. Both have been unable to reach ntfy
    for as long as they have existed.

    Non-encodable characters become "?" rather than being dropped, so the
    degradation is visible instead of silently changing the wording. Callers
    keep the ORIGINAL title in the message body so nothing is actually lost.
    """
    try:
        value.encode("latin-1")
        return value
    except (UnicodeEncodeError, AttributeError):
        return str(value).encode("ascii", "replace").decode("ascii")


def _send_ntfy(topic: str, title: str, message: str) -> bool:
    """
    Send via ntfy.sh.
    Requires NTFY_TOPIC in env (or pass topic explicitly).
    Returns True if sent successfully.
    """
    if not topic:
        return False
    try:
        import urllib.request

        url = f"https://ntfy.sh/{topic}"
        # Header must be latin-1-safe (see _ascii_header_value). When the
        # title had to be degraded, prepend the real one to the body so the
        # operator still receives the exact wording -- the body is sent as
        # UTF-8 bytes and has no such restriction.
        safe_title = _ascii_header_value(title)
        body_text = message if safe_title == title else f"{title}\n\n{message}"
        body = body_text.encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Title": safe_title,
                "Content-Type": "text/plain; charset=utf-8",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception as exc:
        # Was a bare `except Exception: return False` with no logging, which
        # is how the latin-1 header bug above stayed invisible. A delivery
        # failure on a configured channel is worth a line in bot.log.
        _log.warning("_send_ntfy: delivery failed: %s", exc)
        return False


def _redact_webhook_url(url: str) -> str:
    """Redact a webhook URL's bearer credential before it ever reaches a log
    line -- a Discord webhook URL's path IS its bearer token
    (/api/webhooks/{id}/{token}), so logging the raw url (or an exception
    whose message embeds it, e.g. requests' own ConnectionError text) at
    WARNING accumulates a fully usable secret in bot.log on every failed
    delivery. batch-33 M-28: batch-24 rerouted every safety alert through
    this function and made failures retry every cycle, so an outage
    previously logged the complete secret URL repeatedly. Keeps only the
    scheme, host, and a short id prefix -- enough to tell webhooks apart in
    the log without exposing anything an attacker could replay.
    """
    if not url:
        # opus-review-caught: an empty string is falsy but not an error --
        # without this guard, the caller's `str(exc).replace(url, ...)`
        # would replace "" with the redacted marker between every single
        # character of the exception message (str.replace's documented
        # behavior for an empty old value). _send_discord's own url list
        # is already filtered to non-empty strings before this is ever
        # called, so this is a defensive guard for this helper's future
        # reuse, not a fix to an observed live bug.
        return "<redacted>"
    try:
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        segments = [p for p in parts.path.split("/") if p]
        id_prefix = segments[-2][:8] if len(segments) >= 2 else "***"
        return f"{parts.scheme}://{parts.netloc}/.../{id_prefix}***"
    except Exception:
        return "<redacted>"


def _send_discord(title: str, message: str, color: int = 0x3FB950) -> bool:
    """
    #92: Send to all configured Discord webhooks (comma-separated DISCORD_WEBHOOK_URLS
    or single DISCORD_WEBHOOK_URL). Returns True if at least one succeeded.
    """
    if not _DISCORD_AVAILABLE:
        return False

    # Support multiple webhooks via DISCORD_WEBHOOK_URLS (comma-separated)
    multi = os.getenv("DISCORD_WEBHOOK_URLS", "").strip()
    single = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    urls = (
        [u.strip() for u in multi.split(",") if u.strip()]
        if multi
        else ([single] if single else [])
    )
    if not urls:
        return False

    payload = {"embeds": [{"title": title, "description": message, "color": color}]}
    any_ok = False
    for url in urls:
        try:
            resp = _requests.post(url, json=payload, timeout=10)
            if resp.status_code in (200, 204):
                any_ok = True
        except Exception as exc:
            # Redact both the explicit url AND any occurrence of the raw
            # url string inside the exception's own message -- `requests`
            # exceptions (e.g. ConnectionError) commonly embed the full
            # request url, including the bearer token in its path, in
            # their str() representation.
            _redacted_url = _redact_webhook_url(url)
            _log.warning(
                "_send_discord: request to %s failed: %s",
                _redacted_url,
                str(exc).replace(url, _redacted_url),
            )
    return any_ok


def _send_email(title: str, message: str) -> bool:
    """
    Send an email notification via SMTP (STARTTLS).
    Reads SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_TO from environment.
    Returns True on success, False if credentials missing or on any error.
    Never raises.
    """
    host = os.getenv("SMTP_HOST")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    to_addr = os.getenv("SMTP_TO")
    if not host or not user or not password or not to_addr:
        return False
    try:
        import smtplib
        from email.mime.text import MIMEText

        port = int(os.getenv("SMTP_PORT", "587"))
        msg = MIMEText(message)
        msg["Subject"] = title
        msg["From"] = user
        msg["To"] = to_addr
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, password)
            server.sendmail(user, [to_addr], msg.as_string())
        return True
    except Exception as exc:
        _log.warning("Email send failed: %s", exc)
        return False


def alert_strong_signal(
    ticker: str, city: str, side: str, net_edge: float, kelly: float
) -> None:
    """
    Send a STRONG BUY notification through all configured backends.
    Tries desktop (plyer), Pushover, and ntfy — succeeds if any one works.
    Never raises.
    """
    # #95: suppress duplicate notifications within the cooldown window
    now = time.time()
    last = _last_notified.get(ticker, 0.0)
    if now - last < _NOTIFY_COOLDOWN_SECS:
        return
    _last_notified[ticker] = now

    # #94: use custom templates if provided, else fall back to built-in strings
    ctx = {
        "ticker": ticker,
        "city": city,
        "side": side.upper(),
        "net_edge": net_edge,
        "net_edge_pct": f"{net_edge:+.1%}",
        "kelly": kelly,
        "kelly_pct": f"{kelly:.1%}",
    }
    try:
        title = _TEMPLATES.get("strong_signal_title", "").format(**ctx) or (
            f"Kalshi Strong Signal — {ticker}"
        )
    except Exception as exc:
        _log.warning("alert_strong_signal: template title format failed: %s", exc)
        title = f"Kalshi Strong Signal — {ticker}"
    try:
        msg = _TEMPLATES.get("strong_signal_body", "").format(**ctx) or (
            f"BUY {side.upper()}  |  Net edge: {net_edge:+.1%}  |  "
            f"Kelly: {kelly:.1%} of bankroll\n{city}"
        )
    except Exception as exc:
        _log.warning("alert_strong_signal: template body format failed: %s", exc)
        msg = (
            f"BUY {side.upper()}  |  Net edge: {net_edge:+.1%}  |  "
            f"Kelly: {kelly:.1%} of bankroll\n{city}"
        )

    successes: list[bool] = []

    # Desktop notification (plyer)
    if _ENABLED and "desktop" in _CHANNELS:
        try:
            # batch-80 item 2: truncated for the Windows toast field limits
            # (inside _desktop_notify). This call site matters as much as
            # send_system_alert's -- both `title` and `msg` here come from
            # operator-editable templates (_TEMPLATES via
            # notify_templates.json), so their length is entirely unbounded
            # by anything in this file.
            #
            # batch-84 item 1: the appended value is what _desktop_notify
            # actually observed, not an unconditional True.
            successes.append(_desktop_notify(title, msg))
        except Exception as exc:
            _log.warning("alert_strong_signal: desktop notify failed: %s", exc)
            successes.append(False)
    elif "desktop" in _CHANNELS:
        successes.append(False)

    # Pushover
    if "pushover" in _CHANNELS:
        successes.append(_send_pushover(title, msg))

    # ntfy — G7 fix: always record an attempt when "ntfy" is configured, even
    # if NTFY_TOPIC is unset (same fix as send_system_alert's identical gap).
    if "ntfy" in _CHANNELS:
        ntfy_topic = os.getenv("NTFY_TOPIC", "")
        successes.append(bool(ntfy_topic) and _send_ntfy(ntfy_topic, title, msg))

    # Discord webhook — green for BUY YES, red for BUY NO
    if "discord" in _CHANNELS:
        discord_color = 0xF85149 if side.lower() == "no" else 0x3FB950
        successes.append(_send_discord(title, msg, color=discord_color))

    # Email
    if "email" in _CHANNELS:
        successes.append(_send_email(title, msg))

    # G7: warn when every configured channel failed to deliver the alert
    if successes and not any(successes):
        _log.warning(
            "alert_strong_signal: all %d channel(s) failed for %s — signal not delivered",
            len(successes),
            ticker,
        )


SYSTEM_COOLDOWN_SECS = 21_600  # 6 hours between system alerts, per cooldown_key


def send_system_alert_detailed(
    title: str,
    message: str,
    cooldown_key: str = "__system__",
    discord_color: int = 0xE3B341,
    cooldown_secs: float | None = None,
) -> tuple[str, int, int]:
    """send_system_alert()'s body, reporting WHICH of its two success cases
    actually happened.

    Returns ``(status, n_succeeded, n_attempted)`` where status is one of:
      "delivered"  -- at least one configured channel accepted the message
      "suppressed" -- the persisted cooldown for `cooldown_key` was still
                      active, so nothing was sent (and nothing needed to be)
      "failed"     -- delivery was attempted and every configured channel
                      failed, or no channel was configured at all

    batch-69 needs this split because send_system_alert() deliberately
    collapses "delivered" and "suppressed" into a single True -- correct for
    its callers, which only ever ask "is there anything to roll back", but
    useless for a delivery LOG, which exists precisely to tell an operator
    whether a message reached them or was swallowed by a cooldown. Rather
    than change that return type across its existing call sites -- an AST
    count on 2026-08-25 found 24 of them across 7 modules (cron.py x13,
    order_executor.py x5, main.py x2, and one each in alerts.py,
    kalshi_weather_index.py, tracker.py, trade_cycle.py) -- the body moved
    here and send_system_alert() became a thin bool-returning wrapper, so
    its documented contract is reproduced exactly, by construction, instead
    of by a second implementation that could drift.

    `cooldown_secs` overrides the default 6h window for this call.
    _system_cooldown_reserve() has always taken the window as a parameter;
    only send_system_alert() hardcoded what it passed. Threading an override
    through is reuse of the existing disk-persisted cooldown, NOT a second
    per-rule throttle sitting beside it.

    Never raises.
    """
    # opus-review-caught (L-6): a bare float() here made the documented
    # "Never raises" contract conditional on the caller having validated
    # cooldown_secs first. This function is on the alerting path -- the one
    # place a surprise TypeError is least acceptable -- so coerce
    # defensively and fall back to the default rather than trusting callers.
    if cooldown_secs is None:
        _SYSTEM_COOLDOWN_SECS: float = SYSTEM_COOLDOWN_SECS
    else:
        try:
            _SYSTEM_COOLDOWN_SECS = float(cooldown_secs)
            # round-2 opus review (L-11): float("nan") passes the try, and
            # `now - last < nan` is always False -- which DISABLES the cooldown
            # and makes the alert fire on every call. bool is an int subclass,
            # so True became a 1-second window. Both must fall back.
            import math as _math

            if isinstance(cooldown_secs, bool) or not _math.isfinite(
                _SYSTEM_COOLDOWN_SECS
            ):
                raise ValueError("non-finite or boolean cooldown_secs")
        except (TypeError, ValueError):
            _log.warning(
                "send_system_alert_detailed: ignoring non-numeric cooldown_secs "
                "%r for key %r — using the %ds default",
                cooldown_secs,
                cooldown_key,
                SYSTEM_COOLDOWN_SECS,
            )
            _SYSTEM_COOLDOWN_SECS = SYSTEM_COOLDOWN_SECS
    now = time.time()
    reserved, previous_value = _system_cooldown_reserve(
        cooldown_key, now, _SYSTEM_COOLDOWN_SECS
    )
    if not reserved:
        # Cooldown still active -- either a previous call for this exact
        # key already delivered successfully within the window, or (much
        # rarer) a concurrent thread is mid-delivery right now. Either way
        # nothing was left undelivered BY THIS CALL, so this isn't a
        # failure any caller should roll anything back over.
        return "suppressed", 0, 0

    successes: list[bool] = []

    # Desktop notification
    if _ENABLED and "desktop" in _CHANNELS:
        try:
            # batch-80 item 2: truncated for the Windows toast field limits
            # (inside _desktop_notify). The known live case is
            # tracker.audit_settlement's Miami index-mismatch alert. The
            # backlog entry put that body at ~1,499 characters; evaluating
            # the real f-string with realistic values renders ~377 (opus
            # review M-2) -- still ~1.5x over the cap and still lost today,
            # but not 6x. Every other channel below still receives the
            # untouched `message`.
            #
            # batch-84 item 1: the appended value is what _desktop_notify
            # actually observed, not an unconditional True. This is the
            # append that decides `status` for a desktop-only deployment,
            # and therefore whether check_halt_transition rolls back.
            successes.append(_desktop_notify(title, message))
        except Exception as exc:
            _log.warning("send_system_alert: desktop notify failed: %s", exc)
            successes.append(False)
    elif "desktop" in _CHANNELS:
        successes.append(False)

    # Pushover
    if "pushover" in _CHANNELS:
        successes.append(_send_pushover(title, message))

    # ntfy — G7 fix: always record an attempt when "ntfy" is configured, even
    # if NTFY_TOPIC is unset, so a fully-empty `successes` list (which the
    # guard below can't distinguish from "no channels configured at all")
    # can't hide a real misconfiguration.
    if "ntfy" in _CHANNELS:
        ntfy_topic = os.getenv("NTFY_TOPIC", "")
        successes.append(bool(ntfy_topic) and _send_ntfy(ntfy_topic, title, message))

    # Discord — orange by default (0xE3B341); caller may override via
    # discord_color for severity-specific coloring (see docstring, F13).
    if "discord" in _CHANNELS:
        successes.append(_send_discord(title, message, color=discord_color))

    # Email
    if "email" in _CHANNELS:
        successes.append(_send_email(title, message))

    n_ok = sum(1 for s in successes if s)
    if not any(successes):
        # opus-review-caught (F8): the rollback must fire whenever nothing
        # was actually delivered -- including when `successes` stayed fully
        # EMPTY (e.g. NOTIFY_CHANNELS="" or a typo'd channel name matches
        # none of desktop/pushover/ntfy/discord/email, so no branch above
        # ever appended anything). Only the WARNING log is gated on
        # `successes` being non-empty -- "0 of 0 configured channels
        # failed" isn't a delivery failure worth alarming about the same
        # way "0 of N configured channels succeeded" is, but the cooldown
        # reservation is equally pointless to keep burned in both cases.
        if successes:
            _log.warning(
                "send_system_alert: all %d channel(s) failed — alert not delivered",
                len(successes),
            )
        # backlog.txt "SEND_SYSTEM_ALERT()'S COOLDOWN IS CONSUMED BEFORE
        # DELIVERY IS ATTEMPTED": total failure must not burn the cooldown --
        # roll the reservation back so the next call (e.g. the following
        # cron cycle) can retry instead of waiting out the full 6h window.
        _system_cooldown_rollback(cooldown_key, now, previous_value)
        return "failed", 0, len(successes)
    return "delivered", n_ok, len(successes)


def send_system_alert(
    title: str,
    message: str,
    cooldown_key: str = "__system__",
    discord_color: int = 0xE3B341,
    cooldown_secs: float | None = None,
) -> bool:
    """
    Send a system-level alert (not trade-specific) through all configured backends.
    Used for operational events like the dead-man's-switch 48h cron gap.

    Uses a 6-hour cooldown keyed by `cooldown_key` (default "__system__", used
    by callers that predate this parameter) so back-to-back cron runs don't
    spam — separate from the per-ticker trade cooldown. A caller for a
    distinct kind of system alert should pass its own `cooldown_key` (opus-
    review-caught: two unrelated alert types sharing the default key would
    otherwise silently suppress each other for 6h, not just repeats of the
    same alert) so unrelated alert types don't interfere with each other.
    Unlike the per-ticker trade-signal cooldown, this one is persisted to
    disk (paths.NOTIFY_COOLDOWN_STATE_PATH via _system_cooldown_reserve())
    so it survives across separate process invocations -- manual `py main.py
    cron` runs today, or a future scheduled task post-VM-migration -- not
    just within one long-lived process (main.py's `loop`/`watch --auto`
    modes). Fixed 2026-07-31; previously in-process-memory only, which meant
    every fresh invocation reset the cooldown and never actually suppressed
    a repeat alert across separate runs.

    `discord_color` defaults to orange (0xE3B341, this function's original
    fixed color). Callers migrated from their own direct _send_discord()
    call (batch-24 item 2: activate_black_swan_halt, the circuit-open
    alert) can pass their prior severity color instead -- opus-review-caught
    (F13): routing everything through this function's old fixed orange lost
    black-swan's/circuit-open's red (0xF85149), which was real signal for
    an operator visually scanning Discord for severity.

    Returns True if the alert was either delivered on >=1 channel or
    suppressed by an already-elapsed-and-successful cooldown (nothing new
    needed sending this call); False only when delivery was actually
    attempted and every configured channel failed (batch-33 M-1: a caller
    tracking its own edge-triggered state, e.g.
    alerts.check_halt_transition, can use a False return to know THIS
    alert never actually reached anyone and roll that state back so the
    next cycle retries instead of silently treating a failed delivery as
    done).
    Never raises.

    batch-69: the body now lives in send_system_alert_detailed(), which
    reports "delivered" and "suppressed" separately for the alert-delivery
    log. This wrapper reproduces the exact bool contract documented above --
    True for both of those, False only for "failed" -- so no existing caller
    changes and the two can't drift apart.
    """
    status, _n_ok, _n_attempted = send_system_alert_detailed(
        title,
        message,
        cooldown_key=cooldown_key,
        discord_color=discord_color,
        cooldown_secs=cooldown_secs,
    )
    return status != "failed"
