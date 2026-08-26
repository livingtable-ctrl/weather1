"""Dead man's switch — run manually to check bot health: py watchdog.py

If the heartbeat file is older than 48 hours, prints a warning and sends
an optional push notification via ntfy.sh (set NTFY_TOPIC in .env).
"""

# Run manually to check bot health: py watchdog.py
import io
import logging
import os
import sys
from datetime import UTC, datetime, timedelta

# Fix Windows console encoding, exactly as main.py:16-19 does. send_alert()'s
# no-topic fallback print()s a message containing U+2014, and `py watchdog.py
# > log.txt` on Windows gives stdout the locale codepage -- so without this,
# a dead man's switch would raise UnicodeEncodeError inside the very branch
# that exists to tell the operator the bot is down (opus review, cosmetic).
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
elif sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - requirements.txt pins python-dotenv
    # A dead man's switch must still run without its niceties (opus review
    # L-1). main.py has an explicit "pip install -r requirements.txt" guard
    # for a broken venv; this module has no such affordance, and cron.py's
    # `from watchdog import update_heartbeat` sits inside a try/except that
    # would swallow the ImportError -- so a missing python-dotenv would stop
    # the heartbeat file being written and make the watchdog raise a FALSE
    # 48h-stale alarm. Degrade to the pre-batch-84 behaviour instead: no
    # .env, but everything else works.
    def load_dotenv(*_args, **_kwargs) -> bool:  # type: ignore[misc]
        return False


# Load .env HERE, before the first local import, exactly as main.py:41 and
# web_app.py:62 do (batch-84 item 2; backlog.txt "`py watchdog.py` NEVER
# CALLS load_dotenv, SO ITS ntfy PUSH ALERT CANNOT BE CONFIGURED FROM .env").
#
# This module's docstring tells the operator to "set NTFY_TOPIC in .env",
# and `py watchdog.py` is a real standalone entry point that never goes
# through main.py -- so the one documented way to configure the dead man's
# switch could not work. send_alert() fell through to its print/log branch
# and the push notification was never sent.
#
# Zero impact in this deployment today, because NTFY_TOPIC is unset either
# way. That is exactly why it was worth fixing rather than leaving: a dead
# man's switch whose alert channel is silently unconfigurable fails in the
# one circumstance nobody is watching.
#
# Why the POSITION and not just the call (batch-79): utils.py binds 54
# constants from os.getenv at module scope (36 of them through float(...)),
# and config.get_config() caches its singleton on first call, so a
# load_dotenv() placed after them is a no-op that merely looks like a fix --
# measured, load_dotenv() after `import utils` leaves utils.MIN_EDGE at the
# 0.07 code default while before it, it is .15 from .env. watchdog imports
# only `paths` (which reads no env vars, and pulls in only safe_io), so this
# call does precede every env-derived binding today; tests/test_dead_man.py's
# TestWatchdogDotenvBootstrap pins both the ordering and the source position,
# so neither a future module-scope import here nor a later move of this line
# can silently reintroduce the bug.
#
# No override=True, deliberately, matching main.py and web_app.py. cron.py
# imports this module lazily at runtime (`from watchdog import
# update_heartbeat`) from inside a long-lived process. That import runs this
# module body exactly ONCE, on the first cron cycle of the process -- not
# every cycle -- but one silent re-read is enough: it would rewrite
# os.environ under every module already loaded, mid-run. An already-set
# variable wins.
load_dotenv()

from paths import (  # noqa: E402 — must follow load_dotenv(), see above
    LAST_HEARTBEAT_PATH as HEARTBEAT_PATH,
)

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
