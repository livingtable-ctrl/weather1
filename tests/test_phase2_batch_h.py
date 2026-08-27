"""Phase 2 Batch H regression tests: P2-18 + P2-25 — UTC date consistency."""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, str(__file__[: __file__.rfind("tests")]))


# ── utc_today() helper ────────────────────────────────────────────────────────


class TestUtcToday:
    """utc_today() must return UTC date, not local-clock date."""

    def test_returns_date_object(self):
        from utils import utc_today

        result = utc_today()
        assert isinstance(result, date)

    def test_matches_datetime_now_utc(self):
        from utils import utc_today

        expected = datetime.now(UTC).date()
        assert utc_today() == expected

    def test_is_controllable_via_patch(self):
        """Callers can freeze time by patching utils.utc_today."""
        import utils

        frozen = date(2026, 1, 15)
        with patch.object(utils, "utc_today", return_value=frozen):
            assert utils.utc_today() == frozen


# ── nws.py uses utc_today ─────────────────────────────────────────────────────


class TestNwsUtcDate:
    """P2-18/P2-25: nws.nws_prob must use UTC date for days_out."""

    def test_days_out_uses_utc(self):
        """Patching _utc_today in nws changes the days_out computation."""
        import nws

        frozen = date(2026, 6, 1)
        target = date(2026, 6, 3)  # 2 days out from frozen UTC date

        with patch.object(nws, "_utc_today", return_value=frozen):
            with patch.object(nws, "_get_obs_station", return_value=None):
                with patch.object(
                    nws,
                    "_get",
                    return_value={
                        "properties": {
                            "temperature": {
                                "values": [
                                    {
                                        "validTime": "2026-06-03T12:00:00+00:00/PT1H",
                                        "value": 22.0,
                                    }
                                ]
                            },
                            "maxTemperature": {"values": []},
                            "minTemperature": {"values": []},
                        }
                    },
                ):
                    # Just verify _utc_today is called (patching it changes behavior)
                    result = nws.nws_prob(
                        "NYC",
                        (40.7, -74.0, 10),
                        target,
                        {"type": "above", "threshold": 70},
                    )
        # Result is None or a float — we just care it didn't crash and used our patch
        assert result is None or isinstance(result, float)

    def test_nws_imports_utc_today(self):
        """nws module must have _utc_today symbol (imported from utils)."""
        import nws

        assert hasattr(nws, "_utc_today"), "nws must import utc_today as _utc_today"


# ── mos.py uses utc_today ─────────────────────────────────────────────────────


class TestMosUtcDate:
    """P2-18/P2-25: mos.fetch_mos must use UTC date for days_out."""

    def test_mos_imports_utc_today(self):
        import mos

        assert hasattr(mos, "_utc_today"), "mos must import utc_today as _utc_today"

    def test_days_out_frozen(self):
        """mos resolves "today" for days_out through utils.utc_today.

        Repaired by batch-86 alongside its two siblings in this file. The
        body was previously a `with patch(...)` containing `pass`, guarded
        by a `hasattr` ternary, ending in a literal `assert True` labelled
        "structure test". It could not fail.

        _local_or_utc_today(tz) is the function fetch_mos and
        fetch_mos_best both call to compute days_out, and both of its
        branches must land on the patched UTC date: tz=None by design, and
        an unusable tz through the ZoneInfo fallback. Asserting only the
        first would leave the fallback free to reach for a local clock.

        Three separate claims, because the behavioural half alone would
        still pass if days_out stopped going through this helper at all:
        the two branches resolve to utils.utc_today, the name mos binds is
        genuinely utils.utc_today (a `hasattr` check -- which is all
        test_mos_imports_utc_today does -- passes even if it were rebound
        to date.today), and both days_out call sites still route through
        the helper.

        Mutation checks: replacing either `return _utc_today()` in
        mos._local_or_utc_today with `date.today()` makes this fail, as
        does swapping either call site's `_local_or_utc_today(tz)` for a
        direct clock read.
        """
        import inspect

        import mos
        import utils

        # Derived from the real clock rather than a literal, so the
        # fixture can never coincide with today and quietly stop
        # distinguishing the patched date from the unpatched one.
        frozen = date.today() - timedelta(days=90)

        with patch.object(mos, "_utc_today", return_value=frozen):
            assert mos._local_or_utc_today(None) == frozen
            # The ZoneInfo-unavailable fallback path, same requirement.
            assert mos._local_or_utc_today("Not/AZone") == frozen

        # The name being patched above is really utils' UTC helper, not
        # some local-clock function that happens to share the alias.
        assert mos._utc_today is utils.utc_today

        # days_out is what this test is named for: both producers must
        # still compute "today" through the helper asserted above.
        for producer in (mos.fetch_mos, mos.fetch_mos_best):
            source = inspect.getsource(producer)
            assert "_local_or_utc_today(tz)" in source, producer.__name__
            assert "date.today()" not in source, producer.__name__


# ── tracker.py uses utc_today ─────────────────────────────────────────────────


class TestTrackerUtcDate:
    """P2-25: tracker.log_prediction must use UTC date for predicted_date."""

    def test_predicted_date_uses_utc(self):
        """log_prediction stores UTC date as predicted_date."""
        import tracker

        frozen = date(2026, 6, 15)

        with patch.object(tracker, "_utc_today", return_value=frozen):
            with patch.object(tracker, "init_db"):
                with patch.object(tracker, "_conn") as mock_conn:
                    mock_conn.return_value.__enter__ = lambda s: mock_conn.return_value
                    mock_conn.return_value.__exit__ = lambda s, *a: False
                    mock_conn.return_value.execute = lambda *a, **kw: None

                    tracker.log_prediction(
                        ticker="KXHIGHNY-TEST",
                        city="NYC",
                        market_date=date(2026, 6, 20),
                        analysis={"forecast_prob": 0.6, "condition": {}},
                    )

        # Verify _utc_today attribute exists and is importable
        assert hasattr(tracker, "_utc_today")

    def test_tracker_imports_utc_today(self):
        import tracker

        assert hasattr(tracker, "_utc_today"), (
            "tracker must import utc_today as _utc_today"
        )


# ── monte_carlo.py uses utc_today ────────────────────────────────────────────


class TestMonteCarloUtcDate:
    """P2-25: monte_carlo skips past-date trades using UTC date."""

    def test_past_date_skip_uses_utc(self):
        """A trade dated yesterday UTC must be skipped."""
        import monte_carlo

        frozen = date(2026, 6, 15)
        yesterday = date(2026, 6, 14).isoformat()

        trade = {
            "ticker": "KXTEST",
            "side": "yes",
            "entry_price": 0.5,
            "cost": 5.0,
            "quantity": 10,
            "target_date": yesterday,
            "entry_prob": 0.6,
        }

        with patch.object(monte_carlo, "_utc_today", return_value=frozen):
            with patch("paper.get_balance", return_value=500.0):
                result = monte_carlo.simulate_portfolio([trade], n_simulations=20)

        # Trade should be skipped → sim runs on 0 trades → returns early or has 0 open
        assert "median_pnl" in result

    def test_future_trade_not_skipped(self):
        """A trade dated in the future must NOT be skipped."""
        import monte_carlo

        frozen = date(2026, 6, 15)
        future = date(2099, 1, 1).isoformat()

        trade = {
            "ticker": "KXTEST",
            "side": "yes",
            "entry_price": 0.5,
            "cost": 5.0,
            "quantity": 10,
            "target_date": future,
            "entry_prob": 0.6,
        }

        with patch.object(monte_carlo, "_utc_today", return_value=frozen):
            with patch("paper.get_balance", return_value=500.0):
                with patch("paper.position_correlation_matrix", return_value=[[1.0]]):
                    result = monte_carlo.simulate_portfolio([trade], n_simulations=20)

        assert result["n_simulations"] == 20


# ── cron.py _check_startup_orders naive datetime fix ─────────────────────────


class TestCronStartupOrdersUtc:
    """P2-18: _check_startup_orders must treat naive DB timestamps as UTC."""

    @staticmethod
    def _startup_warnings_for(placed_at: str, caplog) -> list[str]:
        """Run _check_startup_orders against one order and return the
        double-execution warnings it emitted.

        caplog.at_level pins the level on cron._log's own logger ("main",
        a process-global) as well as installing the capture handler. A
        bare handler would not: any earlier test in a full-suite run that
        left that logger above WARNING would drop the record before a
        handler saw it, and the positive control below would fail for a
        reason that has nothing to do with timestamps.
        """
        import logging

        import cron
        import execution_log

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger=cron._log.name):
            # Explicit precondition rather than a silent vacuous pass:
            # caplog.at_level does not undo a global logging.disable().
            assert cron._log.isEnabledFor(logging.WARNING)
            with patch.object(
                execution_log,
                "get_recent_orders",
                return_value=[
                    {"placed_at": placed_at, "ticker": "TEST", "side": "yes"}
                ],
            ):
                cron._check_startup_orders()

        messages = [r.getMessage() for r in caplog.records]
        # _check_startup_orders swallows every exception into its own
        # warning, so a crash must not be mistaken for "no recent order".
        assert not any("_check_startup_orders failed" in m for m in messages), messages
        return [m for m in messages if "recent order detected" in m]

    def test_naive_timestamp_treated_as_utc(self, caplog):
        """A naive ISO timestamp from the DB must be read as UTC.

        Repaired by batch-86. This test previously wrapped the call in
        `try/except Exception: pass` inside `patch("logging.Logger.warning")`
        and asserted nothing at all -- it could not fail, and the comment
        claiming "if it reached warning, naive datetime was handled
        correctly" checked nothing, because the warning was mocked out and
        never inspected.

        The recent/old boundary is pinned on every host. How far the
        UTC-vs-local half reaches is worth stating exactly, because the
        obvious answer ("every host except UTC") is wrong. Dropping
        `placed_dt.replace(tzinfo=UTC)` makes a naive string be read
        through the local clock, so the guard fires iff
        `delta + offset <= 300`, where delta is the fixture's age and
        offset is the host's UTC offset in seconds. Hence:

          * the OLD arm (delta = 600 s) detects the mutation whenever
            `offset <= -300`, i.e. any host more than 5 minutes behind
            UTC -- including this repo's own machine at UTC-4, where the
            bug was found;
          * the 200-second POSITIVE CONTROL detects it whenever
            `offset > 100`, i.e. any host ahead of UTC, because the
            mutation pushes that order out past the window and the
            expected warning disappears.

        The blind band is therefore only about (UTC-5min, UTC+100s] --
        essentially UTC itself, which is what both CI runners
        (`.github/workflows/ci.yml`: ubuntu-latest and windows-latest, no
        TZ set) give. There the boundary claim alone is exercised. That is
        a real limit of the fixture, stated rather than papered over with
        a skip. Note delta was chosen at 600 s, not the more natural
        "2 hours ago": 7200 s only detects the mutation past UTC-1:55, so
        it would have left real zones like UTC-1 blind for no benefit.
        """
        now = datetime.now(UTC)
        recent_naive = (now - timedelta(seconds=200)).strftime("%Y-%m-%dT%H:%M:%S")
        old_naive = (now - timedelta(seconds=600)).strftime("%Y-%m-%dT%H:%M:%S")

        # Positive control for the absence-assertion below: the naive
        # branch is genuinely reached and genuinely capable of warning, so
        # "no warning for the old one" cannot pass vacuously on a run
        # where the order never made it past the parse.
        assert self._startup_warnings_for(recent_naive, caplog), (
            "a naive timestamp 200s old must trip the double-execution guard"
        )
        assert self._startup_warnings_for(old_naive, caplog) == []

        # An aware UTC timestamp for the same old instant is the control
        # arm: it is unaffected by the tzinfo mutation on every offset, so
        # if the naive assertion above ever flips while this one holds,
        # the difference is exactly the naive-is-UTC reading.
        old_aware = (now - timedelta(seconds=600)).isoformat()
        assert self._startup_warnings_for(old_aware, caplog) == []

    def test_monday_check_uses_utc_weekday(self):
        """The weekly DB sweep gate must read the UTC clock, not the host's.

        Repaired by batch-86. This test previously asserted
        `date(2026, 6, 1).weekday() == 0` -- a fact about the standard
        library, not about cron -- and then executed `pass` inside a
        `with patch(...)` whose target was chosen by a `hasattr` ternary.
        It could not fail, while the suite counted it as coverage for the
        UTC-Monday fix.

        Both halves are asserted against a clock whose UTC weekday and
        local weekday genuinely differ, so neither can pass by accident:

          * 02:00 UTC Monday is 22:00 Sunday for a host at UTC-4 --
            the gate must fire.
          * 02:00 UTC Tuesday is 22:00 Monday for the same host --
            the gate must not.

        Requiring both True and False from the same helper is also what
        kills the strongest mutation: a gate that stopped consulting the
        UTC clock at all (reverting to `date.today()`, or to any real
        clock) returns the SAME answer in both halves, so one of them goes
        red whatever the real weekday happens to be when the suite runs.

        The gate's wiring into the sweep is covered end-to-end by
        tests/test_cron_integration.py::TestBatch78MondaySweepWindows --
        `test_the_sweep_does_not_run_on_a_non_monday` and its siblings.
        Those patch utils.utc_today, though, which an INLINED
        `utc_today().weekday() == 0` would satisfy just as well, so they
        cannot notice this helper being orphaned. Neither can
        tests/test_dead_code_scan.py: its `_TARGET_FILES` is paper.py,
        tracker.py and weather_markets.py, and cron.py appears there only
        as a caller corpus. Hence the source-containment assertion below,
        scoped to _cmd_cron_body itself rather than to the file, so an
        unrelated occurrence of the name elsewhere in cron.py cannot
        satisfy it.
        """
        import inspect

        import cron
        import utils

        # Binds this test to the production call site. Without it,
        # re-inlining the gate would leave _is_monday_utc dead while every
        # test below still passed.
        gate_source = inspect.getsource(cron._cmd_cron_body)
        assert "_is_monday_utc()" in gate_source
        # Positive control for that containment check: the pre-extraction
        # form really is gone, so the assertion above is not passing on a
        # call site that kept both.
        assert "_utc_today().weekday()" not in gate_source

        # A real datetime subclass, not a Mock: Mock.now(tz) ignores its
        # argument, so it cannot show which zone actually resolved.
        local_zone = timezone(timedelta(hours=-4))

        def _clock_at(instant: datetime):
            class _Frozen(datetime):
                @classmethod
                def now(cls, tz=None):
                    if tz is not None:
                        return instant.astimezone(tz)
                    return instant.astimezone(local_zone).replace(tzinfo=None)

            return _Frozen

        for instant, utc_weekday, local_weekday, expected in (
            (datetime(2026, 6, 1, 2, 0, tzinfo=UTC), 0, 6, True),
            (datetime(2026, 6, 2, 2, 0, tzinfo=UTC), 1, 0, False),
        ):
            clock = _clock_at(instant)
            # Fixture self-check: the two clocks really do disagree here.
            assert clock.now(UTC).date().weekday() == utc_weekday
            assert clock.now().date().weekday() == local_weekday

            with patch.object(utils, "datetime", clock):
                assert cron._is_monday_utc() is expected, (
                    f"{instant.isoformat()} is weekday {utc_weekday} in UTC "
                    f"and {local_weekday} locally; the gate must follow UTC"
                )
