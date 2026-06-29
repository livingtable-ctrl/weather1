"""Dead man's switch — run manually to check bot health: py watchdog.py

If the heartbeat file is older than 48 hours, prints a warning and sends
an optional push notification via ntfy.sh (set NTFY_TOPIC in .env).
"""

# Run manually to check bot health: py watchdog.py
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

HEARTBEAT_PATH = Path("data") / "last_heartbeat.txt"
_log = logging.getLogger("watchdog")


def is_heartbeat_stale(max_age_hours: int = 48) -> bool:
    # Return True if the heartbeat file is missing or older than max_age_hours
    if not HEARTBEAT_PATH.exists():
        return True
    try:
        last = datetime.fromisoformat(HEARTBEAT_PATH.read_text().strip())
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return (datetime.now(UTC) - last) > timedelta(hours=max_age_hours)
    except Exception:
        return True


def send_alert(message: str) -> None:
    # Send push notification via ntfy.sh if NTFY_TOPIC is configured
    topic = os.getenv("NTFY_TOPIC")
    if not topic:
        print(f"[WATCHDOG ALERT] {message}")
        _log.warning(
            "WATCHDOG: %s (set NTFY_TOPIC in .env to enable push notifications)",
            message,
        )
        return
    try:
        import requests

        resp = requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode(),
            headers={
                "Title": "Kalshi Bot Dead Man Switch",
                "Priority": "urgent",
                "Tags": "warning",
            },
            timeout=10,
        )
        resp.raise_for_status()
        _log.info("WATCHDOG alert sent to ntfy.sh/%s", topic)
    except Exception as exc:
        _log.error("WATCHDOG: failed to send alert: %s", exc)


def update_heartbeat() -> None:
    # Write current UTC timestamp so watchdog knows the bot is alive
    HEARTBEAT_PATH.parent.mkdir(exist_ok=True)
    HEARTBEAT_PATH.write_text(datetime.now(UTC).isoformat(timespec="seconds"))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if is_heartbeat_stale(max_age_hours=48):
        send_alert("Kalshi bot has not run in 48+ hours — check the bot process!")
    else:
        last = HEARTBEAT_PATH.read_text().strip()
        print(f"Bot is alive. Last heartbeat: {last}")
