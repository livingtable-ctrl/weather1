"""Tests for weather_markets.is_sameday_market() and the `cron --sameday-only`
CLI wiring (backlog.txt "CITY-LOCAL AFTERNOON SAME-DAY SWEEP").

run_trade_cycle(sameday_only=True)'s own filtering behavior is covered
separately in tests/test_trade_cycle_engine.py's TestSamedayOnly (it needs
that file's engine_env fixture); this file covers the two pieces on either
side of it: the pure ticker/timezone predicate, and CLI-flag -> kwarg wiring.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from weather_markets import is_sameday_market


def _fixed_datetime(instant):
    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return instant.replace(tzinfo=None)
            return instant.astimezone(tz)

    return _FixedDatetime


class TestIsSamedayMarket:
    def test_today_local_ticker_is_sameday(self):
        # 2026-08-22 18:00 UTC == 2026-08-22 14:00 America/New_York (EDT).
        fixed_instant = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)
        with patch("weather_markets.datetime", _fixed_datetime(fixed_instant)):
            assert is_sameday_market({"ticker": "KXHIGHNY-26AUG22-T80"}) is True

    def test_future_dated_ticker_is_not_sameday(self):
        fixed_instant = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)
        with patch("weather_markets.datetime", _fixed_datetime(fixed_instant)):
            assert is_sameday_market({"ticker": "KXHIGHNY-26AUG25-T80"}) is False

    def test_past_dated_ticker_is_not_sameday(self):
        fixed_instant = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)
        with patch("weather_markets.datetime", _fixed_datetime(fixed_instant)):
            assert is_sameday_market({"ticker": "KXHIGHNY-26AUG20-T80"}) is False

    def test_hourly_sameday_ticker_is_sameday(self):
        """Hourly tickers (KXTEMPxxxH-yyMONdd hh) still carry a day-level
        date via the hourly regex branch -- must be included the same as
        daily tickers, not silently excluded."""
        fixed_instant = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)
        with patch("weather_markets.datetime", _fixed_datetime(fixed_instant)):
            assert is_sameday_market({"ticker": "KXTEMPNYCH-26AUG2214-T80.5"}) is True

    def test_ticker_with_no_parseable_date_is_not_sameday(self):
        """Rain tickers are month-only (no day-level date segment) by
        parse_city_date's own documented design -- target_date stays None,
        so same-day-ness can't be determined this cheaply and must be
        excluded, not default to True."""
        fixed_instant = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)
        with patch("weather_markets.datetime", _fixed_datetime(fixed_instant)):
            assert is_sameday_market({"ticker": "KXRAINDENM-26JUL-7"}) is False

    def test_cross_city_timezone_rollover_uses_real_per_city_zone(self):
        """Regression-shaped proof this is a REAL per-city ZoneInfo lookup,
        not a single shared clock: at 2026-08-22 05:00 UTC, NYC (EDT,
        UTC-4) has already rolled over to Aug 22 local, but LA (PDT, UTC-7)
        is still Aug 21 local. A LA-ticker dated Aug 21 must read as
        same-day (proves LA's own zone is used, not NYC's/the fallback's
        already-rolled-over date); the identical ticker dated Aug 22 must
        NOT (proves the comparison isn't vacuously always-True)."""
        fixed_instant = datetime(2026, 8, 22, 5, 0, tzinfo=UTC)
        with patch("weather_markets.datetime", _fixed_datetime(fixed_instant)):
            assert is_sameday_market({"ticker": "KXHIGHLAX-26AUG21-T80"}) is True
            assert is_sameday_market({"ticker": "KXHIGHLAX-26AUG22-T80"}) is False
            # NYC, same instant, already rolled to Aug 22 -- opposite result
            # for the *same* calendar dates, proving the two cities are
            # genuinely evaluated against their own separate local "today".
            assert is_sameday_market({"ticker": "KXHIGHNY-26AUG22-T80"}) is True
            assert is_sameday_market({"ticker": "KXHIGHNY-26AUG21-T80"}) is False


class TestCronSamedayOnlyCliWiring:
    """--sameday-only on the `cron` CLI command must thread through to
    main.cmd_cron's sameday_only kwarg. Mirrors this codebase's existing
    --edge CLI-parsing shape (no dedicated prior test for that one either --
    tested end-to-end via main.main() + mocked heavy dependencies, matching
    tests/test_phase2_batch_g.py's TestProdStartupWarning.test_main_logs_prod_warning)."""

    @pytest.fixture()
    def _mocked_main_deps(self, monkeypatch):
        import main

        # KALSHI_ENV must be neutralised or these tests pass only by ordering
        # luck. The real .env sets KALSHI_ENV=prod, and conftest imports `main`
        # at collection time so load_dotenv() puts that into os.environ --
        # while conftest's own autouse _clear_ws_credentials deletes
        # KALSHI_KEY_ID and KALSHI_PRIVATE_KEY_PATH. main.main() then reaches
        # _validate_config(), sees prod with no credentials, and raises
        # SystemExit(1) before cmd_cron is ever called.
        #
        # Run alone, this module never triggers the collection-time import that
        # loads .env, so KALSHI_ENV falls back to its "demo" default and the
        # tests pass. Run after almost any other module, they fail. Found
        # 2026-08-30 when a widened scoped-test set put this module in the same
        # run as tests/test_exit_rule_shadow_log.py; verified pre-existing by
        # reproducing it with origin/master's own cron.py and tracker.py.
        monkeypatch.setenv("KALSHI_ENV", "demo")

        monkeypatch.setattr(main, "validate_env", lambda: True)
        monkeypatch.setattr(main, "init_db", lambda: None)
        monkeypatch.setattr(main, "cleanup_data_dir", lambda: None)
        monkeypatch.setattr(main, "build_client", lambda: object())
        monkeypatch.setattr(main, "auto_backup", lambda: None)
        return main

    def test_sameday_only_flag_threads_through_to_cmd_cron(
        self, monkeypatch, _mocked_main_deps
    ):
        main = _mocked_main_deps
        calls = []
        monkeypatch.setattr(
            main,
            "cmd_cron",
            lambda client, min_edge=None, sameday_only=False: calls.append(
                (min_edge, sameday_only)
            ),
        )
        monkeypatch.setattr("sys.argv", ["main.py", "cron", "--sameday-only"])

        main.main()

        assert calls == [(None, True)]

    def test_no_flag_defaults_sameday_only_false(self, monkeypatch, _mocked_main_deps):
        main = _mocked_main_deps
        calls = []
        monkeypatch.setattr(
            main,
            "cmd_cron",
            lambda client, min_edge=None, sameday_only=False: calls.append(
                (min_edge, sameday_only)
            ),
        )
        monkeypatch.setattr("sys.argv", ["main.py", "cron"])

        main.main()

        assert calls == [(None, False)]

    def test_sameday_only_combines_with_edge_flag(self, monkeypatch, _mocked_main_deps):
        main = _mocked_main_deps
        calls = []
        monkeypatch.setattr(
            main,
            "cmd_cron",
            lambda client, min_edge=None, sameday_only=False: calls.append(
                (min_edge, sameday_only)
            ),
        )
        monkeypatch.setattr(
            "sys.argv", ["main.py", "cron", "--edge", "12", "--sameday-only"]
        )

        main.main()

        assert calls == [(0.12, True)]


class TestCheckCronStalenessFullScan:
    """opus review (2026-08-22): main._check_cron_staleness()'s new
    full-scan-staleness warning -- the CLI-banner-time half of the
    masking-risk fix (cron.py's in-process alert, tested in
    tests/test_cron_integration.py's TestSamedayOnlyFullScanStaleness, is
    the other half). CRON_HEARTBEAT_PATH is already redirected to a
    per-test tmp_path by conftest.py's autouse isolate_cron_generated_files
    fixture."""

    def _write_heartbeat(self, main, payload):
        import json

        main.CRON_HEARTBEAT_PATH.write_text(json.dumps(payload))

    def test_warns_when_last_full_scan_stale(self, capsys):
        import main

        stale_iso = "2020-01-01T00:00:00+00:00"
        self._write_heartbeat(
            main,
            {"last_run": stale_iso, "cycle_count": 1, "last_full_scan": stale_iso},
        )

        main._check_cron_staleness()

        out = capsys.readouterr().out
        assert "Last FULL cron scan" in out

    def test_no_warning_when_last_full_scan_recent(self, capsys):
        from datetime import UTC, datetime

        import main

        recent_iso = datetime.now(UTC).isoformat()
        self._write_heartbeat(
            main,
            {"last_run": recent_iso, "cycle_count": 1, "last_full_scan": recent_iso},
        )

        main._check_cron_staleness()

        out = capsys.readouterr().out
        assert "Last FULL cron scan" not in out

    def test_legacy_heartbeat_without_last_full_scan_key_falls_back_to_last_run(
        self, capsys
    ):
        """A heartbeat file written before --sameday-only existed has no
        "last_full_scan" key -- every run it recorded WAS a full scan, so
        falling back to "last_run" for staleness purposes is correct, not a
        guess. Stale last_run here must still warn via the fallback."""
        import main

        stale_iso = "2020-01-01T00:00:00+00:00"
        self._write_heartbeat(main, {"last_run": stale_iso, "cycle_count": 1})

        main._check_cron_staleness()

        out = capsys.readouterr().out
        assert "Last FULL cron scan" in out

    def test_legacy_heartbeat_with_recent_last_run_does_not_warn(self, capsys):
        from datetime import UTC, datetime

        import main

        recent_iso = datetime.now(UTC).isoformat()
        self._write_heartbeat(main, {"last_run": recent_iso, "cycle_count": 1})

        main._check_cron_staleness()

        out = capsys.readouterr().out
        assert "Last FULL cron scan" not in out
