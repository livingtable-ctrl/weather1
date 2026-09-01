"""cmd_schedule() must register two daily `cron --sameday-only` tasks at the
host-local wall times corresponding to 01:30 and 03:00 UTC.

Nothing in this repo scheduled a same-day-only scan before this: every
`scan_runs` row is mode='cron', never 'cron-sameday'. The METAR lock-in is
gated on the market's own local day already being late (metar._LOCK_IN_HOUR),
so it can only fire on a same-day market scanned in its city's afternoon or
evening -- which the 3-hourly analyze task and the four full cycle-aligned
cron tasks were never aimed at.

Every expected time here is RE-DERIVED from the UTC target via the standard
library, never copied from the implementation or written as a bare literal:
a literal would pass just as happily against a hardcoded output, and would
not notice the DST-tracking property these tests exist to pin down.
"""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

# The two UTC instants cmd_schedule() must target. Named once here and used
# both to drive the expectation and to name the tasks, so a change to one
# without the other fails rather than silently agreeing with itself.
SAMEDAY_UTC_TIMES = ((1, 30), (3, 0))


def _make_fake_dt(base_utc: datetime, host_tz: ZoneInfo):
    """Stand-in for the `datetime` class, injected via
    `monkeypatch.setattr(main, "datetime", ...)`, freezing "now" at
    `base_utc` and simulating the host's own local clock as `host_tz`.

    Mirrors tests/test_cmd_schedule_settlement_monitor.py's helper of the
    same name deliberately rather than importing it: that file owns the
    settlement-monitor task's contract, this one owns the same-day tasks',
    and a shared helper would couple two independent task registrations so
    that changing one test's clock model silently moves the other's.
    """

    class _FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return base_utc.astimezone(host_tz).replace(tzinfo=None)
            return base_utc.astimezone(tz)

        @classmethod
        def fromtimestamp(cls, ts, tz=None):
            if tz is None:
                return datetime.fromtimestamp(ts, tz=host_tz).replace(tzinfo=None)
            return datetime.fromtimestamp(ts, tz=tz)

    return _FakeDT


def _capturing_run(calls: list[str]):
    def _run(cmd, shell, capture_output, text):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return _run


def _drive(monkeypatch, base_utc, host_tz, answers):
    """Run cmd_schedule() under a frozen clock and captured schtasks calls.

    `answers` is the full 6-prompt sequence in cmd_schedule()'s own order:
    scan, email, settle, settlement-monitor, sameday-05UTC, sameday-23UTC.
    """
    import main

    monkeypatch.setattr(main.sys, "platform", "win32")
    monkeypatch.setattr("shutil.which", lambda _name: "C:\\Windows\\schtasks.exe")
    monkeypatch.setattr(main, "datetime", _make_fake_dt(base_utc, host_tz))

    calls: list[str] = []
    monkeypatch.setattr(subprocess, "run", _capturing_run(calls))
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: next(it))

    main.cmd_schedule()
    return calls


def _expected_local(base_utc: datetime, host_tz: ZoneInfo, hh: int, mm: int) -> str:
    """The host-local wall time of `hh:mm` UTC on base_utc's UTC date.

    Computed with astimezone(), an independent route to the answer from the
    implementation's fromtimestamp() -- so this agrees with the production
    code only when both are actually right, not because they share a helper.
    """
    target = base_utc.astimezone(UTC).replace(
        hour=hh, minute=mm, second=0, microsecond=0
    )
    return target.astimezone(host_tz).strftime("%H:%M")


def _sameday_calls(calls: list[str]) -> dict[int, str]:
    out: dict[int, str] = {}
    for c in calls:
        m = re.search(r'/TN "KalshiCronSameday_(\d{2})UTC"', c)
        if m:
            hour = int(m.group(1))
            assert hour not in out, f"duplicate task for {hour:02d}UTC: {calls}"
            out[hour] = c
    return out


def _st_time(cmd: str) -> str:
    m = re.search(r"/ST (\d{2}:\d{2})", cmd)
    assert m, f"no /ST time in: {cmd}"
    return m.group(1)


# Declines the first four tasks and accepts only the two same-day ones, so a
# stray registration from another block cannot be mistaken for one of these.
SAMEDAY_ONLY_YES = ["n", "n", "n", "n", "y", "y"]


class TestBothTasksRegistered:
    @pytest.mark.parametrize(
        "tz_name,base_utc",
        [
            # Summer, US eastern host: 03:00 UTC is 23:00 local, 01:30 is 21:30.
            ("America/New_York", datetime(2026, 8, 10, 12, 0, tzinfo=UTC)),
            # Summer, US pacific host: 03:00 UTC is 20:00 of the PREVIOUS
            # local day -- the case a naive "UTC hour == local hour"
            # implementation breaks, and the slot where the western cities
            # reach the confidence factor's hour-20 saturation point.
            ("America/Los_Angeles", datetime(2026, 8, 10, 12, 0, tzinfo=UTC)),
            # WINTER eastern: the same UTC targets land an hour earlier local
            # than the summer row above. A snapshotted fixed UTC offset taken
            # at registration time cannot produce both rows.
            ("America/New_York", datetime(2026, 1, 15, 12, 0, tzinfo=UTC)),
            # Non-US host, east of UTC: proves the conversion is the host's,
            # not a hardcoded US assumption.
            ("Europe/London", datetime(2026, 8, 10, 12, 0, tzinfo=UTC)),
        ],
    )
    def test_local_start_times_match_the_utc_targets(
        self, monkeypatch, tz_name, base_utc
    ):
        host_tz = ZoneInfo(tz_name)
        calls = _drive(monkeypatch, base_utc, host_tz, SAMEDAY_ONLY_YES)
        sameday = _sameday_calls(calls)

        assert sorted(sameday) == [hh for hh, _ in SAMEDAY_UTC_TIMES], (
            f"expected one task per UTC target {SAMEDAY_UTC_TIMES}, got "
            f"{sorted(sameday)}: {calls}"
        )
        for hh, mm in SAMEDAY_UTC_TIMES:
            assert _st_time(sameday[hh]) == _expected_local(base_utc, host_tz, hh, mm)

    def test_both_tasks_run_cron_with_the_sameday_flag(self, monkeypatch):
        """The whole point of these tasks is the flag. Without it they are
        two more FULL scans, which the repo already had four of."""
        calls = _drive(
            monkeypatch,
            datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
            ZoneInfo("America/New_York"),
            SAMEDAY_ONLY_YES,
        )
        sameday = _sameday_calls(calls)
        assert len(sameday) == 2
        for hour, cmd in sameday.items():
            tr = re.search(r'/TR "(.*?)" /RL', cmd)
            assert tr, f"no /TR value in: {cmd}"
            value = tr.group(1)
            assert value.endswith("cron --sameday-only"), (
                f"{hour:02d}UTC task does not run `cron --sameday-only`: {value!r}"
            )
            # Negative, with the positive control immediately below it: these
            # must not be the analyze task the 3-hourly job already runs.
            assert " analyze" not in value
            assert " cron " in value + " "
            # Assert on the FLAGS ONLY, never the whole command: the /TR
            # payload embeds sys.executable and the repo path, so a substring
            # test against `cmd` fails on a checkout living under any path
            # segment starting "MO" (a MOnorepo, a user MOrgan) -- and these
            # tests are not Windows-gated, so they run on POSIX CI too.
            flags = cmd.split(" /TR ")[0]
            assert "/RL HIGHEST" in cmd
            # /SC DAILY alone is satisfied by `/SC DAILY /MO 2` -- a task that
            # runs every OTHER day. schtasks flags are CASE-INSENSITIVE, so
            # `/mo 2` must be caught too, and it can appear anywhere in the
            # flags, not only before /ST.
            assert not re.search(r"\s/MO\b", flags, re.I), flags
            # Token asserts, not adjacency: `/Create /F ... /SC DAILY /ST` and
            # `/Create /TN ... /SC DAILY /ST ... /F` are byte-equivalent to
            # schtasks, and cmd_schedule_cycles() already uses the other
            # order -- an innocuous harmonisation must not fail this test.
            toks = flags.split()
            assert "/F" in toks, flags
            assert toks[toks.index("/SC") + 1] == "DAILY", flags
            assert "/ST" in toks, flags
            # /F is load-bearing, not cosmetic: without it `schtasks /Create`
            # on an existing task name prompts "already exists, replace?" on
            # stdin, and because the call uses capture_output=True the prompt
            # is invisible while the child still holds the terminal. `py
            # main.py schedule` would hang with no output on any re-run --
            # which is exactly what this block's own comment tells the
            # operator to do after a DST change.
            assert "/Create /F " in cmd

    def test_paths_are_quoted_and_escaped_for_schtasks(self, monkeypatch):
        """The repo's own path contains a space ("claude kalshi"). An
        unquoted /TR hands python.exe a truncated argv[0] and the task fails
        silently -- the exact bug cmd_schedule_cycles() documents having
        shipped once already."""
        calls = _drive(
            monkeypatch,
            datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
            ZoneInfo("America/New_York"),
            SAMEDAY_ONLY_YES,
        )
        for cmd in _sameday_calls(calls).values():
            tr = re.search(r'/TR "(.*?)" /RL', cmd)
            assert tr
            # Both the interpreter and the script path carry their own
            # backslash-escaped quotes.
            assert tr.group(1).count('\\"') >= 4, tr.group(1)


class TestBareEnterAccepts:
    def test_empty_answer_registers_both_tasks(self, monkeypatch):
        """The prompt reads "(Y/n)", so bare Enter must ACCEPT.

        This is not a cosmetic check. `if confirm == "n"` and
        `if confirm != "y"` behave identically for every explicit y/n answer,
        so a mutation between them survives every other test in this file --
        but under `!= "y"` an operator who Enters through `py main.py
        schedule` silently gets NEITHER new task, which is precisely the state
        this change exists to fix.
        """
        calls = _drive(
            monkeypatch,
            datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
            ZoneInfo("America/New_York"),
            ["n", "n", "n", "n", "", ""],
        )
        assert sorted(_sameday_calls(calls)) == [h for h, _ in SAMEDAY_UTC_TIMES]


class TestFailedRegistrationDoesNotAbortTheNext:
    def test_failure_is_reported_and_the_next_task_still_attempted(
        self, monkeypatch, capsys
    ):
        """schtasks exits non-zero without elevation, and /RL HIGHEST makes
        that a common case. A failure on the first task must be reported and
        stepped over, not abort the loop."""
        import main

        monkeypatch.setattr(main.sys, "platform", "win32")
        monkeypatch.setattr("shutil.which", lambda _name: "C:\\Windows\\schtasks.exe")
        monkeypatch.setattr(
            main,
            "datetime",
            _make_fake_dt(
                datetime(2026, 8, 10, 12, 0, tzinfo=UTC), ZoneInfo("America/New_York")
            ),
        )

        calls: list[str] = []

        def _run(cmd, shell, capture_output, text):
            calls.append(cmd)
            failed = f"KalshiCronSameday_{SAMEDAY_UTC_TIMES[0][0]:02d}UTC" in cmd
            return SimpleNamespace(
                returncode=1 if failed else 0,
                stdout="",
                stderr="ERROR: Access is denied." if failed else "",
            )

        monkeypatch.setattr(subprocess, "run", _run)
        it = iter(SAMEDAY_ONLY_YES)
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: next(it))

        main.cmd_schedule()
        out = capsys.readouterr().out

        # Positive control first: the failing command WAS attempted, so the
        # assertion below is about the loop continuing, not about nothing
        # having run at all.
        attempted = _sameday_calls(calls)
        assert sorted(attempted) == [h for h, _ in SAMEDAY_UTC_TIMES]
        # ...and the failure was REPORTED. The docstring promises "reported and
        # stepped over"; without this, replacing the whole `else:` branch with
        # `pass` swallows a failed registration silently and still passes.
        assert "Access is denied" in out, out[-500:]


class TestOvernightWarning:
    """The sleep/battery/missed-run warning is a production behaviour, not a
    decoration: on a laptop it is the only thing telling the operator why the
    task never ran. Nothing asserted it existed, so deleting the whole block --
    or leaving its hour threshold calibrated for a time the task no longer
    uses -- passed the entire suite.

    The expectation is DERIVED from each task's own resolved local hour rather
    than hardcoded per timezone. A hardcoded list silently rots the next time
    the UTC targets move, which is exactly how the `< 6` threshold survived the
    05:10 -> 01:30/03:00 change while quietly covering nothing.
    """

    OVERNIGHT = range(22, 24), range(0, 7)  # matches main.py's `>=22 or <7`

    @staticmethod
    def _is_overnight(hhmm: str) -> bool:
        h = int(hhmm.split(":")[0])
        return h >= 22 or h < 7

    @pytest.mark.parametrize(
        "tz_name",
        [
            # The operator's own host: 03:00 UTC lands 23:00 local -> warns.
            "America/New_York",
            "America/Chicago",
            # Western hosts: both tasks land in the evening, neither warns.
            "America/Denver",
            "America/Los_Angeles",
            # East of UTC, where both land in the morning.
            "Europe/London",
        ],
    )
    def test_warning_fires_exactly_for_the_overnight_tasks(
        self, monkeypatch, capsys, tz_name
    ):
        calls = _drive(
            monkeypatch,
            datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
            ZoneInfo(tz_name),
            SAMEDAY_ONLY_YES,
        )
        out = capsys.readouterr().out
        sameday = _sameday_calls(calls)
        # Positive control: both tasks registered, so the presence or absence
        # of a warning below is about the warning and not about a dead path.
        assert sorted(sameday) == [h for h, _ in SAMEDAY_UTC_TIMES]

        warned = 0
        for hour, cmd in sameday.items():
            local = _st_time(cmd)
            expect = self._is_overnight(local)
            present = f"{local} is overnight on this host" in out
            assert present is expect, (
                f"{tz_name}: {hour:02d}UTC task resolves to {local} local; "
                f"expected warning={expect}, got {present}"
            )
            warned += present
        if warned:
            # The warning must name the two settings that actually fix it.
            assert "Wake the computer" in out
            assert "AC power" in out

    def test_at_least_one_host_actually_warns(self, monkeypatch, capsys):
        """Guards the parametrized test above against becoming vacuous: if the
        times ever move somewhere no host warns, every case would pass by
        asserting `False is False` and the warning could be deleted freely."""
        _drive(
            monkeypatch,
            datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
            ZoneInfo("America/New_York"),
            SAMEDAY_ONLY_YES,
        )
        assert "is overnight on this host" in capsys.readouterr().out


class TestDeclineIsPerTask:
    def test_declining_the_first_sameday_task_leaves_the_second(self, monkeypatch):
        """Each block prompts independently, like every other task in
        cmd_schedule(). Declining one must not skip the rest -- the bug
        cmd_schedule()'s own scan block documents having had."""
        calls = _drive(
            monkeypatch,
            datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
            ZoneInfo("America/New_York"),
            # UPPERCASE N: the prompt is `(Y/n)` and the answer is passed
            # through .strip().lower(), so dropping that .lower() would
            # REGISTER the task an operator just declined. Every other answer
            # in this file is lowercase, so nothing else catches it.
            ["n", "n", "n", "n", "N", "y"],
        )
        sameday = _sameday_calls(calls)
        # Negative: the declined task registered nothing.
        assert SAMEDAY_UTC_TIMES[0][0] not in sameday
        # Positive control: the harness CAN register the first task -- it did in
        # every test above -- so the absence is the decline, not a dead path.
        assert SAMEDAY_UTC_TIMES[1][0] in sameday


class TestIndependentOfSettlementMonitor:
    def test_registered_even_when_settlement_monitor_import_fails(self, monkeypatch):
        """settlement_monitor has a module-level assertion that fires if
        Kalshi renames a tracked series. That must skip only its own task;
        the same-day tasks are registered after it and must still happen."""
        import sys

        import weather_markets as wm

        monkeypatch.setattr(wm, "KNOWN_WEATHER_SERIES", [])
        monkeypatch.delitem(sys.modules, "settlement_monitor", raising=False)

        # Only 5 prompts are reached: the settlement-monitor block is skipped
        # entirely when its import fails, so it never asks.
        calls = _drive(
            monkeypatch,
            datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
            ZoneInfo("America/New_York"),
            ["n", "n", "n", "y", "y"],
        )
        # Negative: the settlement task did not register.
        assert not any("KalshiWeatherSettlementMonitor" in c for c in calls)
        # Positive control: execution continued past the failure and reached
        # the same-day block, which is what this test is actually about.
        assert sorted(_sameday_calls(calls)) == [h for h, _ in SAMEDAY_UTC_TIMES]
