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
