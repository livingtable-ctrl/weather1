"""_install_cron_watchdog must disarm once the caller signals completion.

Regression for the loop-mode self-kill bug: main.py's `loop` command calls
cmd_cron in-process and then idles for hours between cycles. Before this fix,
the watchdog daemon thread armed inside a completed cycle kept running into
that idle sleep and force-killed the whole process ~timeout_secs after the
cycle *started*, regardless of whether it had already finished.
"""

from __future__ import annotations

import time


def test_watchdog_disarms_on_completion_event(monkeypatch):
    import cron

    exit_calls: list[int] = []
    monkeypatch.setattr(cron.os, "_exit", lambda code: exit_calls.append(code))

    done = cron._install_cron_watchdog(timeout_secs=1)
    done.set()  # simulate cmd_cron's finally block signaling completion
    time.sleep(1.5)  # past the original timeout

    assert exit_calls == [], "watchdog must not fire once completion was signaled"


def test_watchdog_still_fires_on_genuine_hang(monkeypatch):
    import cron

    exit_calls: list[int] = []
    monkeypatch.setattr(cron.os, "_exit", lambda code: exit_calls.append(code))

    cron._install_cron_watchdog(timeout_secs=1)  # never signaled
    time.sleep(1.5)

    assert exit_calls == [1], "watchdog must still force-kill on a genuine hang"
