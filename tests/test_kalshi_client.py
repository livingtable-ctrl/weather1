"""Tests for kalshi_client.py."""

from unittest.mock import MagicMock, patch

import pytest


class TestPlaceOrderApiSemantics:
    """L1-A: Verify side='no' action='buy' API semantics are correct.

    Kalshi's REST API treats `side` and `action` as independent orthogonal fields.
    Buying NO contracts requires side='no' action='buy' with no_price_dollars.
    Using side='yes' action='sell' would close an existing YES position — NOT open NO.
    """

    def _make_client(self):
        """Return a KalshiClient with no auth (we only test body construction)."""
        from unittest.mock import patch

        with patch("kalshi_client.KalshiClient.__init__", return_value=None):
            import kalshi_client

            client = kalshi_client.KalshiClient.__new__(kalshi_client.KalshiClient)
        return client

    def test_no_side_buy_sends_no_price_dollars(self):
        """side='no' action='buy' must include no_price_dollars in the request body."""
        from unittest.mock import MagicMock

        client = self._make_client()
        mock_post = MagicMock(return_value={"order_id": "ord_test"})
        client._post = mock_post

        client.place_order(
            ticker="KXHIGH-26APR25-T72",
            side="no",
            action="buy",
            count=3,
            price=0.35,
        )

        assert mock_post.called, "place_order must call _post"
        _, body = mock_post.call_args.args
        # L1-A invariant: NO buy must carry no_price_dollars, never yes_price_dollars
        assert "no_price_dollars" in body, (
            "side='no' order body must include no_price_dollars"
        )
        assert "yes_price_dollars" not in body, (
            "side='no' order body must NOT include yes_price_dollars"
        )
        assert body["side"] == "no"
        assert body["action"] == "buy"

    def test_yes_side_buy_sends_yes_price_dollars(self):
        """side='yes' action='buy' must include yes_price_dollars — not no_price_dollars."""
        from unittest.mock import MagicMock

        client = self._make_client()
        mock_post = MagicMock(return_value={"order_id": "ord_test"})
        client._post = mock_post

        client.place_order(
            ticker="KXHIGH-26APR25-T72",
            side="yes",
            action="buy",
            count=3,
            price=0.65,
        )

        _, body = mock_post.call_args.args
        assert "yes_price_dollars" in body
        assert "no_price_dollars" not in body
        assert body["side"] == "yes"
        assert body["action"] == "buy"

    def test_no_side_place_live_order_calls_buy_not_sell_yes(self):
        """_place_live_order with side='no' must call client.place_order(side='no', action='buy').

        L1-A: the wrong pattern is side='yes', action='sell' (closes a YES position).
        The correct pattern for opening a NO position is side='no', action='buy'.
        """
        from unittest.mock import MagicMock, patch

        import main

        mock_client = MagicMock()
        mock_client.place_order.return_value = {
            "order_id": "ord_no_test",
            "status": "resting",
        }

        config = {
            "max_trade_dollars": 100,
            "daily_loss_limit": 500,
            "max_open_positions": 10,
            "gtc_cancel_hours": 24,
        }
        analysis = {
            "kelly_quantity": 2,
            "implied_prob": 0.65,
            "market": {"yes_bid": 30, "yes_ask": 40},
            "edge": 0.20,
        }

        with (
            patch("trading_gates.LiveTradingGate.check", return_value=(True, "ok")),
            patch("execution_log.was_ordered_this_cycle", return_value=False),
            patch("execution_log.log_order", return_value=1),
            patch.object(main, "_count_open_live_orders", return_value=0),
            patch("execution_log.get_today_live_loss", return_value=0.0),
        ):
            placed, _ = main._place_live_order(
                ticker="KXHIGH-26APR25-T72",
                side="no",
                analysis=analysis,
                config=config,
                client=mock_client,
                cycle="12z",
            )

        assert placed is True
        assert mock_client.place_order.called, (
            "place_order must be called for live NO order"
        )
        call_kwargs = mock_client.place_order.call_args.kwargs
        # L1-A: must be side='no' action='buy', NOT side='yes' action='sell'
        assert call_kwargs.get("side") == "no", (
            f"Expected side='no', got side='{call_kwargs.get('side')}'"
        )
        assert call_kwargs.get("action") == "buy", (
            f"Expected action='buy', got action='{call_kwargs.get('action')}'"
        )


class TestKeyPermissions:
    def test_warns_on_world_readable_key(self, tmp_path, caplog):
        """Loading a key file with group/other read bits set emits a warning (Unix only)."""
        import logging
        import platform

        import kalshi_client

        if platform.system() == "Windows":
            pytest.skip("Permission checks not applicable on Windows")

        key_file = tmp_path / "private.pem"
        key_file.write_text("fake-key")
        key_file.chmod(0o644)

        with caplog.at_level(logging.WARNING, logger="kalshi_client"):
            kalshi_client._check_key_permissions(key_file)
        assert "permission" in caplog.text.lower() or "readable" in caplog.text.lower()

    def test_no_warning_on_private_key(self, tmp_path, caplog):
        """Loading a key file with 0600 permissions emits no warning (Unix only)."""
        import logging
        import platform

        import kalshi_client

        if platform.system() == "Windows":
            pytest.skip("Permission checks not applicable on Windows")

        key_file = tmp_path / "private.pem"
        key_file.write_text("fake-key")
        key_file.chmod(0o600)

        with caplog.at_level(logging.WARNING, logger="kalshi_client"):
            kalshi_client._check_key_permissions(key_file)
        assert caplog.text == ""


class TestGetMarketsPagination:
    """P1-19: get_markets must follow cursor pagination until exhausted."""

    def _make_client(self):
        with patch("kalshi_client.KalshiClient.__init__", return_value=None):
            import kalshi_client

            client = kalshi_client.KalshiClient.__new__(kalshi_client.KalshiClient)
        return client

    def test_single_page_returns_all_markets(self):
        """No cursor in response → single call, all markets returned."""
        import kalshi_client

        client = self._make_client()
        page1 = [
            {"ticker": f"MKT-{i}", "yes_bid": 50, "yes_ask": 55, "volume": 100}
            for i in range(3)
        ]
        client._get = MagicMock(return_value={"markets": page1})
        client._validate = MagicMock()

        with patch.object(kalshi_client, "validate_market"):
            result = client.get_markets(status="open")

        assert len(result) == 3
        assert client._get.call_count == 1

    def test_two_page_pagination_combines_results(self):
        """Cursor on first page → second call made, both pages combined."""
        import kalshi_client

        client = self._make_client()
        page1 = [{"ticker": "MKT-1", "yes_bid": 50, "yes_ask": 55, "volume": 100}]
        page2 = [{"ticker": "MKT-2", "yes_bid": 50, "yes_ask": 55, "volume": 100}]

        client._get = MagicMock(
            side_effect=[
                {"markets": page1, "cursor": "abc123"},
                {"markets": page2},
            ]
        )
        client._validate = MagicMock()

        with patch.object(kalshi_client, "validate_market"):
            result = client.get_markets()

        assert len(result) == 2
        assert client._get.call_count == 2
        assert result[0]["ticker"] == "MKT-1"
        assert result[1]["ticker"] == "MKT-2"

    def test_cursor_passed_on_second_call(self):
        """The cursor value from page 1 is passed as a param on the page 2 call."""
        import kalshi_client

        client = self._make_client()
        client._get = MagicMock(
            side_effect=[
                {
                    "markets": [
                        {"ticker": "MKT-1", "yes_bid": 50, "yes_ask": 55, "volume": 100}
                    ],
                    "cursor": "cur42",
                },
                {"markets": []},
            ]
        )
        client._validate = MagicMock()

        with patch.object(kalshi_client, "validate_market"):
            client.get_markets(status="open")

        second_call_kwargs = client._get.call_args_list[1]
        params_passed = second_call_kwargs[1].get("params") or second_call_kwargs[0][1]
        assert params_passed.get("cursor") == "cur42"

    def test_three_pages_returns_all(self):
        """Three pages with cursors → all 3 pages combined."""
        import kalshi_client

        client = self._make_client()
        client._get = MagicMock(
            side_effect=[
                {
                    "markets": [
                        {"ticker": "A", "yes_bid": 50, "yes_ask": 55, "volume": 100}
                    ],
                    "cursor": "c1",
                },
                {
                    "markets": [
                        {"ticker": "B", "yes_bid": 50, "yes_ask": 55, "volume": 100}
                    ],
                    "cursor": "c2",
                },
                {
                    "markets": [
                        {"ticker": "C", "yes_bid": 50, "yes_ask": 55, "volume": 100}
                    ]
                },
            ]
        )
        client._validate = MagicMock()

        with patch.object(kalshi_client, "validate_market"):
            result = client.get_markets()

        assert len(result) == 3
        assert client._get.call_count == 3
