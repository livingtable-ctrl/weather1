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
_CHANNELS = set(
    os.getenv("NOTIFY_CHANNELS", "desktop,pushover,ntfy,discord,email").split(",")
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
        body = message.encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Title": title, "Content-Type": "text/plain"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


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
            _log.warning("_send_discord: request to %s failed: %s", url, exc)
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
            _notif.notify(
                title=title,
                message=msg,
                app_name="Kalshi Weather",
                timeout=10,
            )
            successes.append(True)
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


def send_system_alert(
    title: str,
    message: str,
    cooldown_key: str = "__system__",
    discord_color: int = 0xE3B341,
) -> None:
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
    Never raises.
    """
    _SYSTEM_COOLDOWN_SECS = 21_600  # 6 hours between system alerts
    now = time.time()
    reserved, previous_value = _system_cooldown_reserve(
        cooldown_key, now, _SYSTEM_COOLDOWN_SECS
    )
    if not reserved:
        return

    successes: list[bool] = []

    # Desktop notification
    if _ENABLED and "desktop" in _CHANNELS:
        try:
            _notif.notify(
                title=title,
                message=message,
                app_name="Kalshi Weather",
                timeout=10,
            )
            successes.append(True)
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
