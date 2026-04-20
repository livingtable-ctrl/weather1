"""
Desktop toast notifications for strong trade signals.
Uses plyer for cross-platform support (Windows/macOS/Linux).
Silently skips if plyer is not installed.

Also supports Pushover (PUSHOVER_TOKEN + PUSHOVER_USER env vars)
and ntfy.sh (NTFY_TOPIC env var).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

try:
    from plyer import notification as _notif

    _ENABLED = True
except Exception:
    _ENABLED = False

# #123: allow selective enable/disable of notification channels
# Set NOTIFY_CHANNELS=discord,email to only use those two, etc.
_CHANNELS = set(
    os.getenv("NOTIFY_CHANNELS", "desktop,pushover,ntfy,discord,email").split(",")
)

# #94: load custom templates from data/notify_templates.json if present.
# Keys: "strong_signal_title", "strong_signal_body" (Python format strings).
# Fall back to built-in strings if file is absent or malformed.
_TEMPLATES: dict = {}
_TEMPLATES_PATH = Path(__file__).parent / "data" / "notify_templates.json"
try:
    if _TEMPLATES_PATH.exists():
        _TEMPLATES = json.loads(_TEMPLATES_PATH.read_text())
except Exception:
    pass

# #95: per-ticker throttle — suppress repeat notifications within this window.
_NOTIFY_COOLDOWN_SECS = int(os.getenv("NOTIFY_COOLDOWN_SECS", "300"))  # 5 min default
_last_notified: dict[str, float] = {}  # ticker -> last fire timestamp


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
    import requests  # type: ignore[import-untyped]

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
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code in (200, 204):
                any_ok = True
        except Exception:
            pass
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
        # #93: log email failures so user knows notifications aren't reaching them
        print(f"[notify] Email send failed: {exc}", flush=True)
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
    except Exception:
        title = f"Kalshi Strong Signal — {ticker}"
    try:
        msg = _TEMPLATES.get("strong_signal_body", "").format(**ctx) or (
            f"BUY {side.upper()}  |  Net edge: {net_edge:+.1%}  |  "
            f"Kelly: {kelly:.1%} of bankroll\n{city}"
        )
    except Exception:
        msg = (
            f"BUY {side.upper()}  |  Net edge: {net_edge:+.1%}  |  "
            f"Kelly: {kelly:.1%} of bankroll\n{city}"
        )

    import logging as _logging

    _ch_log = _logging.getLogger(__name__)
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
        except Exception:
            successes.append(False)
    elif "desktop" in _CHANNELS:
        successes.append(False)

    # Pushover
    if "pushover" in _CHANNELS:
        successes.append(_send_pushover(title, msg))

    # ntfy
    if "ntfy" in _CHANNELS:
        ntfy_topic = os.getenv("NTFY_TOPIC", "")
        if ntfy_topic:
            successes.append(_send_ntfy(ntfy_topic, title, msg))

    # Discord webhook — green for BUY YES, red for BUY NO
    if "discord" in _CHANNELS:
        discord_color = 0xF85149 if side.lower() == "no" else 0x3FB950
        successes.append(_send_discord(title, msg, color=discord_color))

    # Email
    if "email" in _CHANNELS:
        successes.append(_send_email(title, msg))

    # G7: warn when every configured channel failed to deliver the alert
    if successes and not any(successes):
        _ch_log.warning(
            "alert_strong_signal: all %d channel(s) failed for %s — signal not delivered",
            len(successes),
            ticker,
        )
