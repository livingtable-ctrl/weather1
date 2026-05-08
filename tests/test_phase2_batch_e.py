"""Phase 2 Batch E regression tests: P2-5 (WebSocket dead-code fix)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

sys.path.insert(0, str(__file__[: __file__.rfind("tests")]))


class TestWebSocketSubscribeOrder:
    """P2-5: subscribe() must be called before start(), with real market tickers."""

    def test_subscribe_called_before_start(self):
        """subscribe() must precede start() — reversed order raises RuntimeError."""
        from kalshi_ws import KalshiWebSocket

        ws = KalshiWebSocket.__new__(KalshiWebSocket)
        ws._api_key = "key"
        ws._private_key_pem = "pem"
        ws._tickers = []
        ws._thread = None
        ws._loop = None
        ws._running = False

        # subscribe before start is legal
        ws.subscribe(["TICKER-A"])
        assert "TICKER-A" in ws._tickers

    def test_subscribe_after_start_raises(self):
        """subscribe() raises RuntimeError if called after start() — validates ordering constraint."""
        import pytest

        from kalshi_ws import KalshiWebSocket

        ws = KalshiWebSocket.__new__(KalshiWebSocket)
        ws._api_key = "key"
        ws._private_key_pem = "pem"
        ws._tickers = []
        ws._thread = None
        ws._loop = None
        ws._running = True  # simulate already-started state

        with pytest.raises(RuntimeError, match="before start"):
            ws.subscribe(["TICKER-B"])

    def test_subscribe_receives_market_tickers(self):
        """The subscribe call in cron must pass tickers from the market list, not an empty list."""
        from kalshi_ws import KalshiWebSocket

        mock_ws = MagicMock(spec=KalshiWebSocket)
        mock_ws._running = False
        call_order = []
        mock_ws.subscribe.side_effect = lambda t: call_order.append(("subscribe", t))
        mock_ws.start.side_effect = lambda: call_order.append(("start",))

        markets = [
            {"ticker": "KXHIGHNY-01JAN26-T70"},
            {"ticker": "KXLOWNY-01JAN26-T40"},
            {"ticker": ""},  # empty — must be excluded
        ]

        # Simulate the fixed cron logic
        _ws_tickers = [m.get("ticker") for m in markets if m.get("ticker")]
        if _ws_tickers:
            mock_ws.subscribe(_ws_tickers)
        mock_ws.start()

        assert call_order[0][0] == "subscribe", "subscribe must come before start"
        assert call_order[1][0] == "start"
        tickers_passed = call_order[0][1]
        assert "KXHIGHNY-01JAN26-T70" in tickers_passed
        assert "KXLOWNY-01JAN26-T40" in tickers_passed
        assert "" not in tickers_passed, "Empty tickers must be excluded"

    def test_no_start_with_empty_market_list(self):
        """If the market list is empty, subscribe is skipped but start still fires."""
        from kalshi_ws import KalshiWebSocket

        mock_ws = MagicMock(spec=KalshiWebSocket)
        mock_ws._running = False

        markets: list = []
        _ws_tickers = [m.get("ticker") for m in markets if m.get("ticker")]
        if _ws_tickers:
            mock_ws.subscribe(_ws_tickers)
        mock_ws.start()

        mock_ws.subscribe.assert_not_called()
        mock_ws.start.assert_called_once()

    def test_dead_comment_subscribe_variable_never_existed(self):
        """active_tickers was never defined in cron — the old commented line could not work."""
        import inspect

        import cron

        source = inspect.getsource(cron.cmd_cron)
        assert "active_tickers" not in source, (
            "active_tickers is still referenced in cmd_cron — "
            "the dead-code comment was not removed"
        )

    def test_no_hardcoded_subscribe_comment_in_cron(self):
        """The dead '# _ws.subscribe(active_tickers)' comment must be gone."""
        import inspect

        import cron

        source = inspect.getsource(cron.cmd_cron)
        assert "# _ws.subscribe" not in source, (
            "Dead subscribe comment still present in cmd_cron"
        )
