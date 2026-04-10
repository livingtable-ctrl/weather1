"""
Desktop toast notifications for strong trade signals.
Uses plyer for cross-platform support (Windows/macOS/Linux).
Silently skips if plyer is not installed.

Also supports Pushover (PUSHOVER_TOKEN + PUSHOVER_USER env vars)
and ntfy.sh (NTFY_TOPIC env var).
"""

from __future__ import annotations

import os

try:
    from plyer import notification as _notif

    _ENABLED = True
except Exception:
    _ENABLED = False


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
    Send a notification via Discord webhook.
    Requires DISCORD_WEBHOOK_URL in environment.
    Returns True if sent successfully.
    """
    import os

    import requests  # type: ignore[import-untyped]

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        return False
    try:
        payload = {
            "embeds": [
                {
                    "title": title,
                    "description": message,
                    "color": color,
                }
            ]
        }
        resp = requests.post(webhook_url, json=payload, timeout=10)
        return resp.status_code in (200, 204)
    except Exception:
        return False


def alert_strong_signal(
    ticker: str, city: str, side: str, net_edge: float, kelly: float
) -> None:
    """
    Send a STRONG BUY notification through all configured backends.
    Tries desktop (plyer), Pushover, and ntfy — succeeds if any one works.
    Never raises.
    """
    title = f"Kalshi Strong Signal — {ticker}"
    msg = (
        f"BUY {side.upper()}  |  Net edge: {net_edge:+.1%}  |  "
        f"Kelly: {kelly:.1%} of bankroll\n{city}"
    )

    # Desktop notification (plyer)
    if _ENABLED:
        try:
            _notif.notify(
                title=title,
                message=msg,
                app_name="Kalshi Weather",
                timeout=10,
            )
        except Exception:
            pass

    # Pushover
    _send_pushover(title, msg)

    # ntfy
    ntfy_topic = os.getenv("NTFY_TOPIC", "")
    if ntfy_topic:
        _send_ntfy(ntfy_topic, title, msg)

    # Discord webhook — green for BUY YES, red for BUY NO
    discord_color = 0xF85149 if side.lower() == "no" else 0x3FB950
    _send_discord(title, msg, color=discord_color)
