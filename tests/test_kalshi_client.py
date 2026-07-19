"""Tests for kalshi_client.py."""

from unittest.mock import MagicMock, patch

import pytest


class TestToV2SidePrice:
    """V2 order-endpoint migration: Kalshi's legacy POST /portfolio/orders
    (side: yes/no + action: buy/sell + separate yes_price_dollars/
    no_price_dollars) is deprecated in favor of POST /portfolio/events/orders
    (side: bid/ask + a single price field, quoted from the YES side only).
    _to_v2_side_price() maps the old model to the new one; L1-A's original
    invariant (a NO buy must never be confused with a YES sell) now shows up
    as: (no, buy) and (yes, sell) must map to DIFFERENT V2 (side, price)
    pairs whenever the prices aren't complementary.
    """

    def test_yes_buy_maps_to_bid_at_same_price(self):
        from kalshi_client import _to_v2_side_price

        assert _to_v2_side_price("yes", "buy", 0.65) == ("bid", 0.65)

    def test_yes_sell_maps_to_ask_at_same_price(self):
        from kalshi_client import _to_v2_side_price

        assert _to_v2_side_price("yes", "sell", 0.65) == ("ask", 0.65)

    def test_no_buy_maps_to_ask_at_complementary_price(self):
        """Buying NO at $0.35 is economically equivalent to selling YES at
        $0.65 (1 - 0.35) -- Kalshi's V2 docs state this explicitly."""
        from kalshi_client import _to_v2_side_price

        assert _to_v2_side_price("no", "buy", 0.35) == ("ask", pytest.approx(0.65))

    def test_no_sell_maps_to_bid_at_complementary_price(self):
        from kalshi_client import _to_v2_side_price

        assert _to_v2_side_price("no", "sell", 0.35) == ("bid", pytest.approx(0.65))

    def test_no_buy_and_yes_sell_are_never_confused(self):
        """L1-A's original invariant, restated for the V2 mapping: a NO buy
        and a YES sell at the same nominal price must produce DIFFERENT V2
        orders (different price, since NO's price is complementary) -- they
        must never collapse to the same (side, price) pair."""
        from kalshi_client import _to_v2_side_price

        no_buy = _to_v2_side_price("no", "buy", 0.35)
        yes_sell = _to_v2_side_price("yes", "sell", 0.35)
        assert no_buy != yes_sell


class TestPlaceOrderApiSemantics:
    """L1-A: Verify side='no' action='buy' API semantics are correct via the
    full place_order() body construction (V2 shape: side=bid/ask, single
    price field, no action field at all)."""

    def _make_client(self):
        """Return a KalshiClient with no auth (we only test body construction)."""
        from unittest.mock import patch

        with patch("kalshi_client.KalshiClient.__init__", return_value=None):
            import kalshi_client

            client = kalshi_client.KalshiClient.__new__(kalshi_client.KalshiClient)
        # place_order()'s success path fetches the full order via get_order()
        # afterward (V2's create-order response has no status field) -- mock
        # it so these body-construction tests don't need a real network call.
        client.get_order = lambda order_id: {"order_id": order_id, "status": "resting"}
        return client

    def test_no_side_buy_maps_to_ask_at_complementary_price(self):
        """side='no' action='buy' must send V2 side='ask' at price=1-price."""
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
        assert "action" not in body, "V2 body must not include the legacy action field"
        assert "yes_price_dollars" not in body and "no_price_dollars" not in body, (
            "V2 body must use a single price field, not yes/no_price_dollars"
        )
        assert body["side"] == "ask"
        assert float(body["price"]) == pytest.approx(0.65)

    def test_yes_side_buy_maps_to_bid_at_same_price(self):
        """side='yes' action='buy' must send V2 side='bid' at the same price."""
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
        assert body["side"] == "bid"
        assert float(body["price"]) == pytest.approx(0.65)

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


class TestAmendOrder:
    """AMEND ORDER (V2): kalshi_client.amend_order() -- POST
    /portfolio/events/orders/{order_id}/amend, replacing cancel+verify+
    place_order in the reprice loop's price-only branch."""

    def _make_client(self):
        from unittest.mock import patch

        with patch("kalshi_client.KalshiClient.__init__", return_value=None):
            import kalshi_client

            client = kalshi_client.KalshiClient.__new__(kalshi_client.KalshiClient)
        return client

    def test_posts_to_amend_path_with_order_id(self):
        from unittest.mock import MagicMock

        client = self._make_client()
        mock_post = MagicMock(return_value={"order_id": "ord_1"})
        client._post = mock_post

        client.amend_order(
            order_id="ord_1",
            ticker="KXHIGH-26APR25-T72",
            side="yes",
            action="buy",
            count=5,
            price=0.55,
        )

        assert mock_post.called
        path, body = mock_post.call_args.args
        assert path == "/portfolio/events/orders/ord_1/amend"
        assert body["ticker"] == "KXHIGH-26APR25-T72"
        assert body["side"] == "bid"
        assert float(body["price"]) == pytest.approx(0.55)
        assert float(body["count"]) == pytest.approx(5.00)

    def test_no_side_buy_maps_to_ask_at_complementary_price(self):
        """Same V2 side/price mapping as place_order -- a NO buy amend must
        be expressed as an ask at 1-price, never confused with a YES sell."""
        from unittest.mock import MagicMock

        client = self._make_client()
        mock_post = MagicMock(return_value={"order_id": "ord_1"})
        client._post = mock_post

        client.amend_order(
            order_id="ord_1",
            ticker="KXHIGH-26APR25-T72",
            side="no",
            action="buy",
            count=5,
            price=0.35,
        )

        _, body = mock_post.call_args.args
        assert body["side"] == "ask"
        assert float(body["price"]) == pytest.approx(0.65)

    def test_client_order_id_omitted_when_not_provided(self):
        from unittest.mock import MagicMock

        client = self._make_client()
        mock_post = MagicMock(return_value={"order_id": "ord_1"})
        client._post = mock_post

        client.amend_order(
            order_id="ord_1",
            ticker="KXHIGH-26APR25-T72",
            side="yes",
            action="buy",
            count=5,
            price=0.55,
        )

        _, body = mock_post.call_args.args
        assert "client_order_id" not in body

    def test_client_order_id_included_when_provided(self):
        from unittest.mock import MagicMock

        client = self._make_client()
        mock_post = MagicMock(return_value={"order_id": "ord_1"})
        client._post = mock_post

        client.amend_order(
            order_id="ord_1",
            ticker="KXHIGH-26APR25-T72",
            side="yes",
            action="buy",
            count=5,
            price=0.55,
            client_order_id="orig_coid_123",
        )

        _, body = mock_post.call_args.args
        assert body["client_order_id"] == "orig_coid_123"

    def test_updated_client_order_id_always_present_and_deterministic(self):
        """Same (order_id, side, count, price, cycle) -> same
        updated_client_order_id, so a retry dedups server-side rather than
        double-amending -- mirrors place_order's idempotency pattern."""
        from unittest.mock import MagicMock

        client = self._make_client()
        client._post = MagicMock(return_value={"order_id": "ord_1"})

        client.amend_order(
            order_id="ord_1",
            ticker="KXHIGH-26APR25-T72",
            side="yes",
            action="buy",
            count=5,
            price=0.55,
            cycle="12z",
        )
        first_id = client._post.call_args.args[1]["updated_client_order_id"]

        client.amend_order(
            order_id="ord_1",
            ticker="KXHIGH-26APR25-T72",
            side="yes",
            action="buy",
            count=5,
            price=0.55,
            cycle="12z",
        )
        second_id = client._post.call_args.args[1]["updated_client_order_id"]

        assert first_id == second_id
        assert first_id  # non-empty

    def test_updated_client_order_id_differs_for_different_price(self):
        from unittest.mock import MagicMock

        client = self._make_client()
        client._post = MagicMock(return_value={"order_id": "ord_1"})

        client.amend_order(
            order_id="ord_1",
            ticker="KXHIGH-26APR25-T72",
            side="yes",
            action="buy",
            count=5,
            price=0.55,
            cycle="12z",
        )
        first_id = client._post.call_args.args[1]["updated_client_order_id"]

        client.amend_order(
            order_id="ord_1",
            ticker="KXHIGH-26APR25-T72",
            side="yes",
            action="buy",
            count=5,
            price=0.60,
            cycle="12z",
        )
        second_id = client._post.call_args.args[1]["updated_client_order_id"]

        assert first_id != second_id

    def test_returns_raw_post_response_unchanged(self):
        """No get_order() follow-up (unlike place_order) -- the amend
        response already carries everything callers need (remaining_count/
        fill_count/average_fill_price/ts_ms), same minimal-processing
        convention as cancel_order()."""
        from unittest.mock import MagicMock

        client = self._make_client()
        raw_response = {
            "order_id": "ord_1",
            "remaining_count": "3.00",
            "fill_count": "2.00",
            "average_fill_price": "0.5500",
            "ts_ms": 1234567890,
        }
        client._post = MagicMock(return_value=raw_response)

        result = client.amend_order(
            order_id="ord_1",
            ticker="KXHIGH-26APR25-T72",
            side="yes",
            action="buy",
            count=5,
            price=0.55,
        )

        assert result == raw_response


class TestPlaceOrderSurvivesGetOrderFailure:
    """A successful POST already confirms the order is live on the exchange --
    if the get_order() follow-up (needed only to backfill the V2 response's
    missing status field) then fails, place_order() must not lose the known
    order_id by falling through to _find_order_by_client_id() and re-raising.
    A lagged/failed read here previously caused a live order to be recorded
    status='failed', orphaned from all downstream lifecycle handling."""

    def _make_client(self):
        from unittest.mock import MagicMock, patch

        with patch("kalshi_client.KalshiClient.__init__", return_value=None):
            import kalshi_client

            client = kalshi_client.KalshiClient.__new__(kalshi_client.KalshiClient)
        client._find_order_by_client_id = MagicMock(
            return_value=None
        )  # simulates a lagged read finding nothing
        return client

    def test_returns_raw_create_response_when_get_order_fails(self):
        from unittest.mock import MagicMock

        client = self._make_client()
        client._post = MagicMock(
            return_value={"order_id": "ord_landed", "fill_count": "0.00"}
        )
        client.get_order = MagicMock(side_effect=ConnectionError("read lag"))

        result = client.place_order(
            ticker="KXTEST", side="yes", action="buy", count=1, price=0.55, cycle="12z"
        )

        assert result == {"order_id": "ord_landed", "fill_count": "0.00"}
        client._find_order_by_client_id.assert_not_called()

    def test_raises_and_checks_recovery_only_when_post_itself_fails(self):
        """The get_order-failure fallback must not mask a genuine POST failure --
        that path still goes through _find_order_by_client_id as before."""
        from unittest.mock import MagicMock

        import pytest

        client = self._make_client()
        client._post = MagicMock(side_effect=ConnectionError("timeout"))

        with pytest.raises(ConnectionError):
            client.place_order(
                ticker="KXTEST",
                side="yes",
                action="buy",
                count=1,
                price=0.55,
                cycle="12z",
            )

        client._find_order_by_client_id.assert_called_once()


class TestPlaceMakerOrderIdempotency:
    """2026-07-09: place_maker_order never forwarded a cycle to place_order,
    so every call got a fresh random UUID baked into its idempotency key --
    a caller retrying after a lost response (timeout, network blip) would
    generate a different key than the original attempt even if it actually
    landed, and Kalshi would accept it as a genuinely new, distinct order."""

    def _make_client(self):
        from unittest.mock import patch

        with patch("kalshi_client.KalshiClient.__init__", return_value=None):
            import kalshi_client

            client = kalshi_client.KalshiClient.__new__(kalshi_client.KalshiClient)
        # place_order()'s success path fetches the full order via get_order()
        # afterward (V2's create-order response has no status field) -- mock
        # it so these idempotency-key tests don't need a real network call.
        client.get_order = lambda order_id: {"order_id": order_id, "status": "resting"}
        return client

    def test_same_cycle_produces_the_same_idempotency_key(self):
        client = self._make_client()
        mock_post = MagicMock(return_value={"order_id": "ord_test"})
        client._post = mock_post

        client.place_maker_order("KXHIGH-26APR25-T72", "yes", 0.45, 5, cycle="12z")
        first_id = mock_post.call_args.args[1]["client_order_id"]

        client.place_maker_order("KXHIGH-26APR25-T72", "yes", 0.45, 5, cycle="12z")
        second_id = mock_post.call_args.args[1]["client_order_id"]

        assert first_id == second_id, (
            "Same ticker/side/price/qty/cycle must produce the same "
            "client_order_id so a retry dedups server-side"
        )

    def test_without_cycle_each_call_gets_a_different_key(self):
        """Documents the pre-existing (and still correct for a genuinely
        distinct manual order) fallback behavior when no cycle is passed."""
        client = self._make_client()
        mock_post = MagicMock(return_value={"order_id": "ord_test"})
        client._post = mock_post

        client.place_maker_order("KXHIGH-26APR25-T72", "yes", 0.45, 5)
        first_id = mock_post.call_args.args[1]["client_order_id"]

        client.place_maker_order("KXHIGH-26APR25-T72", "yes", 0.45, 5)
        second_id = mock_post.call_args.args[1]["client_order_id"]

        assert first_id != second_id


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


class TestGetCandlesticks:
    """price_history backlog item — OHLC candlestick fetch."""

    def _make_client(self):
        with patch("kalshi_client.KalshiClient.__init__", return_value=None):
            import kalshi_client

            client = kalshi_client.KalshiClient.__new__(kalshi_client.KalshiClient)
        return client

    def test_calls_correct_path_and_params(self):
        client = self._make_client()
        client._get = MagicMock(return_value={"ticker": "TK", "candlesticks": []})
        client._validate = MagicMock()

        client.get_candlesticks("KXHIGHNY", "KXHIGHNY-26APR09-T70", 1000, 2000, 60)

        client._get.assert_called_once()
        path_arg = client._get.call_args[0][0]
        assert path_arg == "/series/KXHIGHNY/markets/KXHIGHNY-26APR09-T70/candlesticks"
        kwargs = client._get.call_args[1]
        assert kwargs["params"] == {
            "start_ts": 1000,
            "end_ts": 2000,
            "period_interval": 60,
        }
        assert kwargs["auth"] is True

    def test_defaults_period_interval_to_one_minute(self):
        client = self._make_client()
        client._get = MagicMock(return_value={"ticker": "TK", "candlesticks": []})
        client._validate = MagicMock()

        client.get_candlesticks("KXHIGHNY", "TK", 1000, 2000)

        assert client._get.call_args[1]["params"]["period_interval"] == 1

    def test_returns_candlesticks_list(self):
        client = self._make_client()
        candles = [{"end_period_ts": 1500, "volume_fp": "10.00"}]
        client._get = MagicMock(return_value={"ticker": "TK", "candlesticks": candles})
        client._validate = MagicMock()

        result = client.get_candlesticks("KXHIGHNY", "TK", 1000, 2000)

        assert result == candles

    def test_missing_candlesticks_key_returns_empty_list(self):
        client = self._make_client()
        client._get = MagicMock(return_value={"ticker": "TK"})
        client._validate = MagicMock()

        result = client.get_candlesticks("KXHIGHNY", "TK", 1000, 2000)

        assert result == []


class TestGetTrades:
    """PUBLIC TRADES REST BACKFILL backlog item -- GET /markets/trades fetch."""

    def _make_client(self):
        with patch("kalshi_client.KalshiClient.__init__", return_value=None):
            import kalshi_client

            client = kalshi_client.KalshiClient.__new__(kalshi_client.KalshiClient)
        return client

    def test_calls_correct_path_and_params(self):
        client = self._make_client()
        client._get = MagicMock(return_value={"trades": []})
        client._validate = MagicMock()

        client.get_trades("KXHIGHNY-26APR09-T70", min_ts=1000, max_ts=2000)

        client._get.assert_called_once()
        path_arg = client._get.call_args[0][0]
        assert path_arg == "/markets/trades"
        kwargs = client._get.call_args[1]
        assert kwargs["params"] == {
            "ticker": "KXHIGHNY-26APR09-T70",
            "limit": 1000,
            "min_ts": 1000,
            "max_ts": 2000,
        }
        assert kwargs["auth"] is True

    def test_min_ts_max_ts_omitted_when_not_provided(self):
        client = self._make_client()
        client._get = MagicMock(return_value={"trades": []})
        client._validate = MagicMock()

        client.get_trades("TK")

        params = client._get.call_args[1]["params"]
        assert "min_ts" not in params
        assert "max_ts" not in params

    def test_single_page_returns_all_trades_no_cursor(self):
        """No cursor in response -> single call, all trades returned."""
        client = self._make_client()
        trades = [{"trade_id": f"t{i}", "ticker": "TK"} for i in range(3)]
        client._get = MagicMock(return_value={"trades": trades})
        client._validate = MagicMock()

        result = client.get_trades("TK")

        assert result == trades
        assert client._get.call_count == 1

    def test_cursor_present_but_next_page_empty_stops_pagination(self):
        """Live-verified real Kalshi behavior (2026-07-19): a non-empty
        cursor can be returned even on what turns out to be the LAST page
        -- the next call returning an empty trades list is what actually
        signals "done", not cursor absence alone. Must check both.

        Uses a DIFFERENT cursor on the empty final page (not "abc123" again)
        so this test isolates the `not page` check from the separate
        repeated-cursor guard (test_repeated_cursor_stops_pagination) -- a
        mutation dropping `or not page` from the break condition would
        otherwise still accidentally pass this test via the repeated-cursor
        path if both pages happened to reuse the same cursor string."""
        client = self._make_client()
        page1 = [{"trade_id": "t1", "ticker": "TK"}]
        client._get = MagicMock(
            side_effect=[
                {"trades": page1, "cursor": "abc123"},
                {"trades": [], "cursor": "different-cursor"},  # empty, new cursor
            ]
        )
        client._validate = MagicMock()

        result = client.get_trades("TK")

        assert result == page1
        assert client._get.call_count == 2

    def test_two_page_pagination_combines_results(self):
        client = self._make_client()
        page1 = [{"trade_id": "t1", "ticker": "TK"}]
        page2 = [{"trade_id": "t2", "ticker": "TK"}]
        client._get = MagicMock(
            side_effect=[
                {"trades": page1, "cursor": "c1"},
                {"trades": page2},
            ]
        )
        client._validate = MagicMock()

        result = client.get_trades("TK")

        assert len(result) == 2
        assert result[0]["trade_id"] == "t1"
        assert result[1]["trade_id"] == "t2"

    def test_cursor_passed_on_second_call(self):
        client = self._make_client()
        client._get = MagicMock(
            side_effect=[
                {"trades": [{"trade_id": "t1"}], "cursor": "cur42"},
                {"trades": []},
            ]
        )
        client._validate = MagicMock()

        client.get_trades("TK")

        second_call_params = client._get.call_args_list[1][1]["params"]
        assert second_call_params.get("cursor") == "cur42"

    def test_repeated_cursor_stops_pagination(self):
        """A cursor identical to one already seen must stop the loop rather
        than spin forever -- same runaway-loop guard as get_markets."""
        client = self._make_client()
        client._get = MagicMock(
            return_value={"trades": [{"trade_id": "t1"}], "cursor": "same-cursor"}
        )
        client._validate = MagicMock()

        result = client.get_trades("TK")

        # First call returns page + "same-cursor"; second call (using that
        # cursor) returns the SAME cursor again -> must stop, not loop.
        assert client._get.call_count == 2
        assert len(result) == 2  # both pages' single trade each, still collected

    def test_missing_trades_key_returns_empty_list(self):
        client = self._make_client()
        client._get = MagicMock(return_value={})
        client._validate = MagicMock()

        result = client.get_trades("TK")

        assert result == []
