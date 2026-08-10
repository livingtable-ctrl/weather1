"""cmd_schedule() must register a settlement-monitor task that spans every
tracked city's own 5-7pm-local settlement window in a single daily run --
correctly across DST transitions, across local-midnight zone-date-crossings,
and independent of the host machine's own timezone."""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo


def _make_fake_dt(base_utc: datetime, host_tz: ZoneInfo):
    """A stand-in for the `datetime` class, injected via
    `monkeypatch.setattr(main, "datetime", ...)`, that freezes "now" at
    `base_utc` and simulates the host machine's own local clock as
    `host_tz` -- independent of whatever timezone the real test runner
    happens to be in."""

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


def _run_cmd_schedule_and_capture(monkeypatch, fake_dt):
    import main

    monkeypatch.setattr(main.sys, "platform", "win32")
    monkeypatch.setattr("shutil.which", lambda _name: "C:\\Windows\\schtasks.exe")
    monkeypatch.setattr(main, "datetime", fake_dt)

    calls: list[str] = []

    def _fake_run(cmd, shell, capture_output, text):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    # 4 confirm() prompts: scan, email, settle, settlement-monitor.
    answers = iter(["y", "n", "n", "y"])
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: next(answers))

    main.cmd_schedule()
    return calls


def _capturing_run(calls: list[str]):
    """subprocess.run replacement that records the command and reports
    success -- a plain function rather than a `lambda ... or ...`
    one-liner, since that idiom is exactly what triggered a real
    ruff-version disagreement (pinned pre-commit hook vs. a newer local
    ruff) while implementing this."""

    def _run(cmd, shell, capture_output, text):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return _run


def _settlement_call(calls: list[str]) -> str:
    matches = [c for c in calls if "KalshiWeatherSettlementMonitor" in c]
    assert len(matches) == 1, (
        f"expected exactly one schtasks call for the settlement monitor "
        f"task, got {len(matches)}: {calls}"
    )
    return matches[0]


def _extract(cmd: str) -> tuple[str, int]:
    st_match = re.search(r"/ST (\d{2}:\d{2})", cmd)
    assert st_match, f"no /ST time found in: {cmd}"
    dur_match = re.search(r"settlement-monitor (\d+)", cmd)
    assert dur_match, f"no duration found in: {cmd}"
    return st_match.group(1), int(dur_match.group(1))


class TestHappyPath:
    def test_summer_eastern_host(self, monkeypatch):
        """Aug: Eastern EDT(-4) through Pacific/Arizona PDT/MST(-7) -- a
        3-hour spread, 2-hour window each -> 5h span + 10min buffer."""
        fake_dt = _make_fake_dt(
            datetime(2026, 8, 10, 12, 0, tzinfo=UTC), ZoneInfo("America/New_York")
        )
        calls = _run_cmd_schedule_and_capture(monkeypatch, fake_dt)
        start, duration = _extract(_settlement_call(calls))
        assert start == "17:00"
        assert duration == 310

    def test_winter_eastern_host(self, monkeypatch):
        """Jan: Eastern EST(-5) through Pacific PST(-8)/Arizona MST(-7,
        unchanged) -- still a 3-hour max spread (Pacific, not Arizona, is
        now the westmost by 1 more hour than Arizona but Arizona and
        Mountain both shift together with Eastern, so the max stays 3)."""
        fake_dt = _make_fake_dt(
            datetime(2026, 1, 15, 12, 0, tzinfo=UTC), ZoneInfo("America/New_York")
        )
        calls = _run_cmd_schedule_and_capture(monkeypatch, fake_dt)
        start, duration = _extract(_settlement_call(calls))
        assert start == "17:00"
        assert duration == 310


class TestDstTransitionRegression:
    """Regression coverage for a real bug found in this implementation:
    snapshotting the host's UTC offset via `datetime.now().astimezone().
    tzinfo` (evaluated at *registration* time) rather than localizing the
    *target* 17:00-Eastern instant produces a permanently-wrong /ST for
    roughly a 2-3 hour window around each US DST transition, twice a
    year. Mutation-tested: reverting the fix (restoring the old
    snapshot-based conversion) makes these fail with /ST off by exactly
    one hour."""

    def test_spring_forward_pre_transition_registration(self, monkeypatch):
        # 2026-03-08 00:30 EST (pre-transition; ET springs forward to EDT
        # at 02:00 local that same day). Old buggy code: /ST 16:00.
        fake_dt = _make_fake_dt(
            datetime(2026, 3, 8, 5, 30, tzinfo=UTC), ZoneInfo("America/New_York")
        )
        calls = _run_cmd_schedule_and_capture(monkeypatch, fake_dt)
        start, duration = _extract(_settlement_call(calls))
        assert start == "17:00"
        assert duration == 310

    def test_fall_back_pre_transition_registration(self, monkeypatch):
        # 2026-11-01 00:30 EDT (pre-transition; ET falls back to EST at
        # 02:00 local that same day). Old buggy code: /ST 18:00.
        fake_dt = _make_fake_dt(
            datetime(2026, 11, 1, 4, 30, tzinfo=UTC), ZoneInfo("America/New_York")
        )
        calls = _run_cmd_schedule_and_capture(monkeypatch, fake_dt)
        start, duration = _extract(_settlement_call(calls))
        assert start == "17:00"
        assert duration == 310


class TestZoneDateCrossingRegression:
    """Regression coverage for a real bug hit while implementing this: an
    earlier version computed the end-of-window instant from the CLOSE
    zone's own independently-observed "now" (`datetime.now(ZoneInfo(close_
    zone)).replace(hour=19, ...)`) rather than from a pure UTC-offset
    delta. Whenever the close zone's current calendar date differs from
    the open zone's (true for several hours nightly -- e.g. it's already
    past midnight Eastern while Pacific is still on the previous
    calendar day), that produced a negative duration. Mutation-tested:
    reverting to the old wall-clock-subtraction approach makes this fail
    with a negative duration."""

    def test_registration_during_eastern_after_midnight_pacific_before(
        self, monkeypatch
    ):
        # 2026-08-10 02:05 EDT = 2026-08-09 23:05 PDT -- Eastern already
        # past midnight into a new calendar day, Pacific still on the
        # previous one.
        fake_dt = _make_fake_dt(
            datetime(2026, 8, 10, 6, 5, tzinfo=UTC), ZoneInfo("America/New_York")
        )
        calls = _run_cmd_schedule_and_capture(monkeypatch, fake_dt)
        start, duration = _extract(_settlement_call(calls))
        assert start == "17:00"
        assert duration == 310


class TestHostTimezoneIndependence:
    def test_non_eastern_host_converts_correctly(self, monkeypatch):
        """Host machine's own clock is UTC, not Eastern -- /ST must reflect
        Eastern's 17:00 (EDT, summer) converted into the HOST's frame
        (21:00 UTC), not just echo "17:00" regardless of host tz. This is
        an independently-derived expectation, not the production formula
        run a second time."""
        fake_dt = _make_fake_dt(datetime(2026, 8, 10, 12, 0, tzinfo=UTC), UTC)
        calls = _run_cmd_schedule_and_capture(monkeypatch, fake_dt)
        start, duration = _extract(_settlement_call(calls))
        assert start == "21:00"
        assert duration == 310


class TestFirstPromptDeclineStillRegistersOthers:
    def test_declining_scan_still_registers_settlement_monitor(self, monkeypatch):
        """Regression coverage: answering "n" to the very first prompt
        (KalshiWeatherScan) previously returned from the whole function,
        silently skipping email/settle/settlement-monitor too -- the
        realistic case for a user who already has the first 3 tasks and
        only wants to add the new 4th one."""
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
        monkeypatch.setattr(subprocess, "run", _capturing_run(calls))
        answers = iter(["n", "n", "n", "y"])
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: next(answers))

        main.cmd_schedule()

        # Negative: scan itself was declined, so it must NOT be registered.
        assert not any("KalshiWeatherScan" in c for c in calls)
        # Positive control: the settlement-monitor task (the one this test
        # exists to check) still got registered despite the first decline.
        settlement_calls = [c for c in calls if "KalshiWeatherSettlementMonitor" in c]
        assert len(settlement_calls) == 1


class TestSettlementMonitorImportFailureIsolated:
    def test_stale_series_error_skips_only_settlement_task(self, monkeypatch):
        """If settlement_monitor's own module-level _CITY_SERIES_TICKER
        assertion fires (a renamed/retired Kalshi series -- the exact
        failure mode settlement_monitor.py's own comment documents),
        cmd_schedule() must skip only the settlement-monitor task, not
        crash after the first 3 tasks already registered."""
        import main
        import weather_markets as wm

        monkeypatch.setattr(main.sys, "platform", "win32")
        monkeypatch.setattr("shutil.which", lambda _name: "C:\\Windows\\schtasks.exe")
        monkeypatch.setattr(
            main,
            "datetime",
            _make_fake_dt(
                datetime(2026, 8, 10, 12, 0, tzinfo=UTC), ZoneInfo("America/New_York")
            ),
        )
        # Force settlement_monitor's module-level derivation to fail on
        # (re)import by making its source data implausible.
        monkeypatch.setattr(wm, "KNOWN_WEATHER_SERIES", [])

        calls: list[str] = []
        monkeypatch.setattr(subprocess, "run", _capturing_run(calls))
        answers = iter(["y", "n", "n", "y"])
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: next(answers))

        import sys

        # Force settlement_monitor's module-level derivation to re-run
        # (against the monkeypatched KNOWN_WEATHER_SERIES above) inside
        # cmd_schedule()'s own `from settlement_monitor import ...`. A
        # module that fails during import is removed from sys.modules by
        # Python itself, and monkeypatch restores KNOWN_WEATHER_SERIES at
        # teardown -- so no manual cleanup/reload is needed here; the next
        # real `import settlement_monitor` anywhere naturally re-imports
        # cleanly against the restored data.
        monkeypatch.delitem(sys.modules, "settlement_monitor", raising=False)

        main.cmd_schedule()  # must not raise

        # Negative: the settlement task must not have registered.
        assert not any("KalshiWeatherSettlementMonitor" in c for c in calls)
        # Positive control: the earlier tasks (unaffected by the import
        # failure) still registered -- proves cmd_schedule() kept running
        # past the failure rather than the list just being empty because
        # nothing ran at all.
        assert any("KalshiWeatherScan" in c for c in calls)


class TestRealTimeIntegration:
    def test_real_clock_produces_plausible_values(self, monkeypatch):
        """Lightweight, non-flaky integration check against the real
        system clock (no time injection) -- wide bounds only, since the
        exact values depend on when this happens to run."""
        import main

        monkeypatch.setattr(main.sys, "platform", "win32")
        monkeypatch.setattr("shutil.which", lambda _name: "C:\\Windows\\schtasks.exe")

        calls: list[str] = []
        monkeypatch.setattr(subprocess, "run", _capturing_run(calls))
        answers = iter(["y", "n", "n", "y"])
        monkeypatch.setattr("builtins.input", lambda *_a, **_kw: next(answers))

        main.cmd_schedule()

        start, duration = _extract(_settlement_call(calls))
        hh, mm = start.split(":")
        assert 0 <= int(hh) <= 23
        assert 0 <= int(mm) <= 59
        # Long enough to beat the bare 120min CLI default (the bug this
        # task exists to fix), not an absurd multi-day duration.
        assert 240 <= duration <= 480
