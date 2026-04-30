"""Tests for cmd_simulate status parameter."""


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


class TestFetchSettledMarkets:
    def test_pagination_follows_cursor(self, monkeypatch):
        """_fetch_settled_markets must follow the cursor until exhausted."""
        from unittest.mock import MagicMock

        import backtest

        fake_client = MagicMock()
        page1 = {"markets": [{"ticker": "T1"}], "cursor": "abc123"}
        page2 = {"markets": [{"ticker": "T2"}], "cursor": None}
        fake_client._get.side_effect = [page1, page2]

        result = backtest._fetch_settled_markets(fake_client, max_pages=5)

        assert len(result) == 2
        assert fake_client._get.call_count == 2
        second_call_params = fake_client._get.call_args_list[1][1]["params"]
        assert second_call_params.get("cursor") == "abc123"

    def test_api_error_raises_with_clear_message(self, monkeypatch):
        """_fetch_settled_markets must raise on 400 errors."""
        from unittest.mock import MagicMock

        import requests

        import backtest

        fake_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 400
        resp.text = "Bad Request"
        fake_client._get.side_effect = requests.HTTPError(response=resp)

        import pytest

        with pytest.raises((requests.HTTPError, RuntimeError)):
            backtest._fetch_settled_markets(fake_client, max_pages=5)


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
        "weather_markets.enrich_with_forecast", lambda m: m
    )  # no _date key

    client = MagicMock()
    main.cmd_backtest(client, ["--days", "90"])

    out = capsys.readouterr().out
    assert "fetched" in out.lower(), f"Should show 'Fetched' count, got:\n{out}"
    assert "10" in out, f"Should show fetched count of 10, got:\n{out}"
