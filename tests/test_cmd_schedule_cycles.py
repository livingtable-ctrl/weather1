"""cmd_schedule_cycles() must convert each of the 4 fixed UTC scan times
(02/08/14/20:15) to the host machine's own local wall-clock time by
localizing each TARGET instant (fromtimestamp()), not by snapshotting the
host's UTC offset once at call time and applying it to every target -- the
snapshot approach is wrong for any target instant on the opposite side of a
DST transition from the moment this command happens to be run. Mirrors
test_cmd_schedule_settlement_monitor.py's own regression coverage for the
identical bug class in cmd_schedule()'s settlement-monitor task."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def _make_fake_dt(base_utc: datetime, host_tz: ZoneInfo):
    """A real datetime subclass (not a Mock) with a working astimezone/
    tz-aware now()/fromtimestamp() -- a plain Mock() standing in for
    datetime.now(tz)/fromtimestamp(ts) can't prove which zone a call
    actually resolved to."""

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


def _run_and_capture_times(monkeypatch, capsys, fake_dt) -> dict[int, str]:
    import main

    monkeypatch.setattr(main, "datetime", fake_dt)
    main.cmd_schedule_cycles()
    out = capsys.readouterr().out
    times = dict(
        (int(h), t)
        for h, t in re.findall(r"# (\d{2}):15 UTC \((\d{2}:\d{2}) local\)", out)
    )
    assert len(times) == 4, f"expected 4 scan times printed, got: {times}\n{out}"
    return times


class TestHappyPath:
    def test_summer_eastern_host(self, monkeypatch, capsys):
        """Aug: host on Eastern, EDT (UTC-4) throughout -- no transition in view."""
        fake_dt = _make_fake_dt(
            datetime(2026, 8, 10, 12, 0, tzinfo=UTC), ZoneInfo("America/New_York")
        )
        times = _run_and_capture_times(monkeypatch, capsys, fake_dt)
        assert times == {2: "22:15", 8: "04:15", 14: "10:15", 20: "16:15"}

    def test_winter_eastern_host(self, monkeypatch, capsys):
        """Jan: host on Eastern, EST (UTC-5) throughout -- no transition in view."""
        fake_dt = _make_fake_dt(
            datetime(2026, 1, 15, 12, 0, tzinfo=UTC), ZoneInfo("America/New_York")
        )
        times = _run_and_capture_times(monkeypatch, capsys, fake_dt)
        assert times == {2: "21:15", 8: "03:15", 14: "09:15", 20: "15:15"}


class TestHostTimezoneIndependence:
    """Opus-review-caught: every TestHappyPath case used an Eastern host, so
    a broken monkeypatch (main.datetime silently not taking effect) would
    still produce output byte-identical to the real unpatched clock on this
    Eastern-timezone dev machine -- test_summer_eastern_host's assertion
    matched the real, unmocked current-machine output during review.
    Mirrors test_cmd_schedule_settlement_monitor.py's own
    TestHostTimezoneIndependence: a UTC host makes local == UTC, so any
    output other than a straight echo of the input hours proves the
    monkeypatch is real and load-bearing."""

    def test_utc_host_is_a_straight_echo(self, monkeypatch, capsys):
        fake_dt = _make_fake_dt(datetime(2026, 6, 1, 12, 0, tzinfo=UTC), UTC)
        times = _run_and_capture_times(monkeypatch, capsys, fake_dt)
        assert times == {2: "02:15", 8: "08:15", 14: "14:15", 20: "20:15"}


class TestDstTransitionRegression:
    """Regression coverage for the bug this batch fixed: the old code
    snapshotted `datetime.now().astimezone().tzinfo` once (at whatever
    instant this command happens to be run) and reused that fixed offset
    for all 4 target times. Registering shortly before a DST transition
    silently mis-converts every target time that falls after the
    transition. Mutation-tested: reverting the fix (restoring the
    snapshot-based conversion) makes the post-transition entries below fail
    by exactly one hour, matching the pattern the settlement-monitor
    regression tests already established for the identical bug class."""

    def test_spring_forward_pre_transition_registration(self, monkeypatch, capsys):
        # 2026-03-08 00:30 EST (pre-transition; ET springs forward to EDT
        # at 02:00 local that day, i.e. 07:00 UTC). Old buggy code snapshots
        # EST(-5) and applies it to every target, including the 3 that fall
        # after the 07:00 UTC transition (when the real offset is EDT, -4).
        # Old buggy code: {2: "21:15", 8: "03:15", 14: "09:15", 20: "15:15"}
        # (08/14/20 all one hour behind correct).
        fake_dt = _make_fake_dt(
            datetime(2026, 3, 8, 5, 30, tzinfo=UTC), ZoneInfo("America/New_York")
        )
        times = _run_and_capture_times(monkeypatch, capsys, fake_dt)
        assert times == {2: "21:15", 8: "04:15", 14: "10:15", 20: "16:15"}

    def test_fall_back_pre_transition_registration(self, monkeypatch, capsys):
        # 2026-11-01 00:30 EDT (pre-transition; ET falls back to EST at
        # 02:00 local that day, i.e. 06:00 UTC). Old buggy code snapshots
        # EDT(-4) and applies it to every target, including the 3 that fall
        # after the 06:00 UTC transition (when the real offset is EST, -5).
        # Old buggy code: {2: "22:15", 8: "04:15", 14: "10:15", 20: "16:15"}
        # (08/14/20 all one hour ahead of correct).
        fake_dt = _make_fake_dt(
            datetime(2026, 11, 1, 4, 30, tzinfo=UTC), ZoneInfo("America/New_York")
        )
        times = _run_and_capture_times(monkeypatch, capsys, fake_dt)
        assert times == {2: "22:15", 8: "03:15", 14: "09:15", 20: "15:15"}
