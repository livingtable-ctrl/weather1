"""Tests for cmd_simulate status parameter."""


class TestSaveWalkForwardParams:
    def test_writes_via_atomic_helper(self, tmp_path, monkeypatch):
        """save_walk_forward_params must use safe_io's atomic write, not a plain
        write_text — a plain write leaves a window where a concurrent reader
        (e.g. web_app.py, a separate process) can see a partially-written file
        under the mtime config.py's cache keys on."""
        from unittest.mock import MagicMock

        import backtest

        mock_atomic_write = MagicMock()
        monkeypatch.setattr("safe_io.atomic_write_json", mock_atomic_write)

        out_path = tmp_path / "walk_forward_params.json"
        backtest.save_walk_forward_params(
            {
                "mean_brier": 0.2,
                "std_brier": 0.01,
                "n_folds": 5,
                "optimal_min_edge": 0.06,
            },
            path=out_path,
        )

        mock_atomic_write.assert_called_once()
        written_data, written_path = mock_atomic_write.call_args[0]
        assert written_path == out_path
        assert written_data["optimal_min_edge"] == 0.06

    def test_survives_write_failure(self, tmp_path, monkeypatch):
        """A failed write (e.g. AtomicWriteError) must be caught, not propagate —
        this runs from the weekly cron cycle and must not crash trade settlement."""
        import backtest

        def _raise(*a, **kw):
            raise OSError("disk full")

        monkeypatch.setattr("safe_io.atomic_write_json", _raise)

        # Must not raise.
        backtest.save_walk_forward_params(
            {"optimal_min_edge": 0.06}, path=tmp_path / "walk_forward_params.json"
        )


class TestCmdSimulateStatusParam:
    def test_simulate_uses_series_fetch_not_get_markets(self, monkeypatch):
        """cmd_simulate must use _fetch_settled_markets (series-based), not get_markets."""
        from unittest.mock import MagicMock

        import main

        fetch_called = {"n": 0}

        def _fake_fetch(client, **kw):
            fetch_called["n"] += 1
            return []  # empty → "no markets" exit

        monkeypatch.setattr("backtest._fetch_settled_markets", _fake_fetch)

        fake_client = MagicMock()
        main.cmd_simulate(fake_client)

        assert fetch_called["n"] == 1, "_fetch_settled_markets must be called"
        assert fake_client.get_markets.call_count == 0, (
            "get_markets must NOT be called — use _fetch_settled_markets instead"
        )

    def test_model_pnl_uses_maker_fee_not_taker_fee(self, monkeypatch, capsys):
        """The 'Model:' P&L must match what analyze_trade() itself assumes
        (maker fee, $0 on this bot's markets) -- not the taker rate. Before
        this fix, the sandbox recomputed the model's hypothetical P&L with
        KALSHI_FEE_RATE (0.07) even though analyze_trade()'s own Kelly/EV
        math already used KALSHI_MAKER_FEE_RATE (0.0), silently understating
        the displayed model edge by ~7%.
        """
        import builtins
        from unittest.mock import MagicMock

        import main

        market = {
            "ticker": "KXHIGHNY-26APR09-T70",
            "title": "NYC high > 70F",
            "result": "yes",
            "close_time": "2026-04-09T23:00:00Z",
            "yes_bid": 0.50,
            "yes_ask": 0.50,
        }

        def _fake_fetch(client, **kw):
            return [market]

        monkeypatch.setattr("backtest._fetch_settled_markets", _fake_fetch)
        monkeypatch.setattr("weather_markets.enrich_with_forecast", lambda m: m)
        monkeypatch.setattr(
            "weather_markets.analyze_trade",
            lambda enriched: {
                "recommended_side": "yes",
                "forecast_prob": 0.70,
            },
        )

        # "s" (skip) short-circuits past the model-evaluation block entirely
        # (a bare `continue`), so the user must actually answer to reach it.
        # The user's own P&L math is unrelated to this fix; any valid
        # side+amount works here.
        responses = iter(["n", "1"])
        monkeypatch.setattr(builtins, "input", lambda *a: next(responses))

        fake_client = MagicMock()
        main.cmd_simulate(fake_client)

        out = capsys.readouterr().out
        # entry_price=0.50, model wins, $10 stake:
        # mw = (1 - 0.50) * (1 - KALSHI_MAKER_FEE_RATE) = 0.50 * 1.0 = 0.50
        # mpnl = 10 / 0.50 * 0.50 = 10.00 (not 9.30, which is the stale taker-fee value)
        assert "Model: BUY YES" in out
        assert "+$10.00" in out
        assert "+$9.30" not in out


class TestFetchSettledMarkets:
    def test_pagination_follows_cursor_within_series(self, monkeypatch):
        """_fetch_settled_markets follows cursor pages within a single series."""
        from unittest.mock import MagicMock

        import backtest

        # Stub _WEATHER_SERIES to a single series so call count is predictable
        monkeypatch.setattr(backtest, "_WEATHER_SERIES", ["KXHIGHNY"])

        fake_client = MagicMock()
        page1 = {"markets": [{"ticker": "T1"}], "cursor": "abc123"}
        page2 = {"markets": [{"ticker": "T2"}], "cursor": None}
        fake_client._get.side_effect = [page1, page2]

        result = backtest._fetch_settled_markets(fake_client, max_pages=5)

        assert len(result) == 2
        assert fake_client._get.call_count == 2
        second_call_params = fake_client._get.call_args_list[1][1]["params"]
        assert second_call_params.get("cursor") == "abc123"

    def test_min_close_time_forwarded_to_api(self, monkeypatch):
        """_fetch_settled_markets must pass min_close_time to every API call.

        Root cause: without this filter the Kalshi API returns markets sorted
        oldest-first when authenticated, so max_pages=20 only surfaces 2022-2024
        markets — all outside the 90-day window — scoring zero.
        """
        from unittest.mock import MagicMock

        import backtest

        monkeypatch.setattr(backtest, "_WEATHER_SERIES", ["KXHIGHNY"])
        fake_client = MagicMock()
        fake_client._get.return_value = {"markets": [], "cursor": None}

        backtest._fetch_settled_markets(
            fake_client,
            max_pages=1,
            min_close_time="2026-01-30T00:00:00+00:00",
        )

        called_params = fake_client._get.call_args_list[0][1]["params"]
        assert called_params.get("min_close_time") == "2026-01-30T00:00:00+00:00", (
            f"min_close_time must be forwarded to the API; got params={called_params}"
        )

    def test_min_close_time_omitted_when_none(self, monkeypatch):
        """When min_close_time is None the param must not appear in the API call."""
        from unittest.mock import MagicMock

        import backtest

        monkeypatch.setattr(backtest, "_WEATHER_SERIES", ["KXHIGHNY"])
        fake_client = MagicMock()
        fake_client._get.return_value = {"markets": [], "cursor": None}

        backtest._fetch_settled_markets(fake_client, max_pages=1, min_close_time=None)

        called_params = fake_client._get.call_args_list[0][1]["params"]
        assert "min_close_time" not in called_params, (
            f"min_close_time must not appear when None; got params={called_params}"
        )

    def test_api_error_skips_series_and_continues(self, monkeypatch):
        """_fetch_settled_markets silently skips a series that errors and continues."""
        from unittest.mock import MagicMock

        import requests

        import backtest

        # Two series: first errors, second succeeds
        monkeypatch.setattr(backtest, "_WEATHER_SERIES", ["KXHIGHNY", "KXLOWNY"])

        fake_client = MagicMock()
        ok_page = {"markets": [{"ticker": "KXLOWNY-25APR30-T40"}], "cursor": None}
        fake_client._get.side_effect = [
            requests.HTTPError(response=MagicMock(status_code=400, text="Bad Request")),
            ok_page,
        ]

        result = backtest._fetch_settled_markets(fake_client, max_pages=5)

        assert len(result) == 1, "Should return markets from the successful series"
        assert result[0]["ticker"] == "KXLOWNY-25APR30-T40"


class TestWeatherSeriesDerivation:
    def test_derived_from_known_weather_series_not_a_second_copy(self):
        """_WEATHER_SERIES must be weather_markets.KNOWN_WEATHER_SERIES itself,
        not an independent hand-typed copy -- a second copy already went stale
        once (KXLOWLAX -> KXLOWTLAX, confirmed live 2026-07-05), silently
        excluding LA markets from every backtest run with no test catching it
        until a live audit found it."""
        import backtest
        import weather_markets as wm

        assert backtest._WEATHER_SERIES is wm.KNOWN_WEATHER_SERIES
        assert "KXLOWTLAX" in backtest._WEATHER_SERIES
        assert "KXLOWLAX" not in backtest._WEATHER_SERIES

    def test_stale_known_weather_series_raises_at_import(self, monkeypatch):
        """Aliasing to KNOWN_WEATHER_SERIES only fixed the one already-known
        LA incident -- if a DIFFERENT city's ticker is ever renamed/retired
        without KNOWN_WEATHER_SERIES being updated to match, backtest.py's
        per-city import-time guard must fail loudly with a clear
        AssertionError rather than silently reproducing the same
        'city missing from every backtest run' bug for a new city (found via
        a deep code review, 2026-07-08 -- mirrors settlement_monitor.py's
        identical pattern for its own KXHIGH*-only guard)."""
        import importlib

        import pytest

        import backtest
        import weather_markets as wm

        importlib.reload(backtest)  # clean baseline, regardless of run order

        stale_series = [t for t in wm.KNOWN_WEATHER_SERIES if t != "KXHIGHNY"]
        monkeypatch.setattr(wm, "KNOWN_WEATHER_SERIES", stale_series)

        try:
            with pytest.raises(AssertionError, match="NYC"):
                importlib.reload(backtest)
        finally:
            monkeypatch.undo()
            importlib.reload(backtest)


class TestCmdBacktestErrorHandling:
    def test_api_error_prints_message_not_traceback(self, monkeypatch, capsys):
        """cmd_backtest must catch API errors and print a readable message."""
        from unittest.mock import MagicMock, patch

        import requests

        import main

        fake_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 400
        http_err = requests.HTTPError("400 Bad Request", response=resp)

        with patch("backtest.run_backtest", side_effect=http_err):
            main.cmd_backtest(fake_client, [])

        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert (
            "400" in output or "Bad Request" in output or "error" in output.lower()
        ), "Expected a readable error message, got nothing"


def test_backtest_reports_funnel_breakdown_when_empty(monkeypatch, capsys):
    """When backtest finds no scoreable markets, cmd_backtest prints a funnel explaining why."""
    from unittest.mock import MagicMock

    import main

    # 10 markets with valid result, but enrich_with_forecast returns no _date
    # so they fail at the "Parsed" gate — n_fetched=10, n_result_ok=10, n_parsed=0
    markets = [
        {
            "ticker": f"KXHIGHNY-25APR{i:02d}-T65",
            "result": "yes",
            "title": f"High temp NYC {i}",
        }
        for i in range(1, 11)
    ]
    monkeypatch.setattr("backtest._fetch_settled_markets", lambda *a, **kw: markets)
    monkeypatch.setattr(
        "weather_markets.enrich_with_forecast", lambda m, **kw: m
    )  # no _date key

    client = MagicMock()
    main.cmd_backtest(client, ["--days", "90"])

    out = capsys.readouterr().out
    assert "fetched" in out.lower(), f"Should show 'Fetched' count, got:\n{out}"
    assert "10" in out, f"Should show fetched count of 10, got:\n{out}"


class TestFetchPreviousRunEnsemble:
    def test_returns_list_of_floats(self, monkeypatch):
        """Previous Runs API call must return a list of floats."""
        from datetime import date

        from backtest import fetch_previous_run_ensemble

        class MockResp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "daily": {
                        "time": ["2026-06-20"],
                        "temperature_2m_max_previous_day1_icon_seamless": [88.5],
                        "temperature_2m_max_previous_day1_gfs_seamless": [89.2],
                        "temperature_2m_max_previous_day1_ecmwf_aifs025_single": [87.8],
                    }
                }

        monkeypatch.setattr("backtest.requests.get", lambda *a, **k: MockResp())
        temps = fetch_previous_run_ensemble(
            "NYC", date(2026, 6, 20), days_out=1, var="max"
        )
        assert isinstance(temps, list)
        assert len(temps) > 0
        assert all(isinstance(t, float) for t in temps)

    def test_returns_empty_for_unknown_city(self):
        """Unknown city must return empty list (no crash)."""
        from datetime import date

        from backtest import fetch_previous_run_ensemble

        result = fetch_previous_run_ensemble("Atlantis", date(2026, 6, 20), days_out=1)
        assert result == []

    def test_returns_empty_on_api_error(self, monkeypatch):
        """API errors must return empty list, never raise."""
        from datetime import date

        import requests

        from backtest import fetch_previous_run_ensemble

        def _raise(*a, **k):
            raise requests.RequestException("timeout")

        monkeypatch.setattr("backtest.requests.get", _raise)
        result = fetch_previous_run_ensemble("NYC", date(2026, 6, 20), days_out=1)
        assert result == []

    def test_run_backtest_accepts_use_previous_runs_flag(self):
        """run_backtest() must accept use_previous_runs keyword without raising TypeError."""
        import inspect

        from backtest import run_backtest

        sig = inspect.signature(run_backtest)
        assert "use_previous_runs" in sig.parameters


class TestBetweenMarketProbabilityClamp:
    """A narrow 'between' bracket scored against a small discrete archive sample
    very often lands 0/N in-bracket — kelly_fraction() zeroes the stake whenever
    probability is exactly 0 or 1, so an unclamped our_prob silently sizes these
    trades to $0 regardless of whether the call was right or wrong. run_backtest()
    must clamp our_prob to [0.01, 0.99] once, before Brier scoring AND Kelly
    sizing, matching analyze_trade()'s live convention."""

    def test_zero_in_bracket_probability_is_clamped_not_zero(self, monkeypatch):
        from datetime import date
        from unittest.mock import MagicMock

        import backtest

        market = {
            "ticker": "KXHIGHNY-26JUN16-B75.5",
            "title": "NYC high temp",
            "result": "no",
            "yes_bid": 4,
            "yes_ask": 6,
            "open_time": "2026-06-15T00:00:00Z",
        }
        monkeypatch.setattr(
            "backtest._fetch_settled_markets", lambda *a, **kw: [market]
        )
        monkeypatch.setattr(
            "weather_markets.enrich_with_forecast",
            lambda m, **kw: {**m, "_city": "NYC", "_date": date(2026, 6, 16)},
        )
        # All samples well above the 74.5-76.5 bracket -> 0/N in-bracket, the
        # exact scenario that used to produce our_prob == 0.0 unclamped.
        monkeypatch.setattr(
            "backtest.fetch_archive_temps", lambda *a, **kw: [85.0] * 10
        )

        result = backtest.run_backtest(MagicMock(), days_back=365, holdout_fraction=0)

        assert result["n_markets"] == 1
        row = result["rows"][0]
        assert row["our_prob"] == 0.01, (
            f"Expected our_prob clamped to 0.01 (not raw 0.0), got {row['our_prob']}"
        )
        # rec_side="no" (0.01 < market_prob), actual="no" -> won, real stake -> real pnl.
        assert row["pnl"] != 0.0, (
            "A won trade at a clamped probability must have a nonzero stake/pnl, "
            "not the $0.00 that an unclamped our_prob==0.0 would have produced"
        )
        assert row["won"] is True


class TestPrevRunModelsMatchTracker:
    def test_all_models_present_in_tracker_map_values(self):
        """backtest._PREV_RUN_MODELS and tracker._PREVIOUS_RUN_MODEL_MAP both
        hardcode Previous-Runs-API model names independently (flat list vs a
        live-name -> deterministic-name dict), with no shared source. Guard
        against them silently diverging (e.g. a model rename in one but not
        the other) by asserting every name in the flat list is one of the
        map's *values* (the deterministic Previous-Runs equivalents that
        _PREV_RUN_MODELS itself lists)."""
        import backtest
        import tracker

        prev_run_models = set(backtest._PREV_RUN_MODELS)
        map_values = set(tracker._PREVIOUS_RUN_MODEL_MAP.values())

        missing = prev_run_models - map_values
        assert not missing, (
            f"backtest._PREV_RUN_MODELS has model(s) not present as a value in "
            f"tracker._PREVIOUS_RUN_MODEL_MAP: {missing}. These two structures "
            f"encode the same Previous-Runs-API model names and must stay in "
            f"sync — update tracker._PREVIOUS_RUN_MODEL_MAP (or backtest."
            f"_PREV_RUN_MODELS) to match."
        )
