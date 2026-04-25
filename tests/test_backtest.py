"""Tests for cmd_simulate status parameter."""


class TestCmdSimulateStatusParam:
    def test_simulate_calls_get_markets_with_settled_not_finalized(self, monkeypatch):
        """cmd_simulate must use status='settled', not 'finalized'."""
        from unittest.mock import MagicMock, patch

        import main

        fake_client = MagicMock()
        fake_client.get_markets.return_value = []  # empty → "no markets" exit

        with patch("main.build_client", return_value=fake_client):
            try:
                main.cmd_simulate(fake_client)
            except SystemExit:
                pass

        call_kwargs = fake_client.get_markets.call_args
        assert call_kwargs is not None, "get_markets was never called"
        # Accept keyword or positional
        all_kwargs = {**dict(enumerate(call_kwargs.args)), **call_kwargs.kwargs}
        assert "settled" in str(all_kwargs), (
            f"Expected status='settled', got: {all_kwargs}"
        )
        assert "finalized" not in str(all_kwargs), (
            "status='finalized' is rejected by the Kalshi API with a 400"
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
