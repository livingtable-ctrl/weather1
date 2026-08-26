"""Tests for kalshi_client.py."""

from unittest.mock import MagicMock, patch

import pytest
import requests


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
            return_value=(None, False)
        )  # simulates a lagged read finding nothing, reconciliation NOT uncertain
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


class TestComputeClientOrderId:
    """Batch-22 item 2: compute_client_order_id() is the standalone helper
    place_order() now routes its own deterministic-key derivation through
    (instead of an inline formula) -- exposed so order_executor.py/main.py's
    live pre-log call sites can precompute the SAME id before ever calling
    place_order, so a crash between the pre-log and the real API response
    still leaves a row _recover_pending_orders can reconcile against Kalshi.
    See kalshi_client.place_order's own client_order_id line, which now
    calls this same function."""

    def _make_client(self):
        from unittest.mock import patch

        import kalshi_client

        with patch("kalshi_client.KalshiClient.__init__", return_value=None):
            client = kalshi_client.KalshiClient.__new__(kalshi_client.KalshiClient)
        client.get_order = lambda order_id: {"order_id": order_id, "status": "resting"}
        return client

    def test_matches_place_orders_own_internal_derivation(self):
        """The core contract: a caller that pre-computes the id via this
        function and later calls place_order with the identical inputs must
        get byte-identical results -- otherwise a pre-logged client_order_id
        would never actually match what Kalshi received."""
        import kalshi_client

        precomputed = kalshi_client.compute_client_order_id(
            "KXHIGH-26APR25-T72", "yes", "buy", 5, 0.45, "good_till_canceled", "12z"
        )

        client = self._make_client()
        mock_post = MagicMock(return_value={"order_id": "ord_test"})
        client._post = mock_post
        client.place_order(
            "KXHIGH-26APR25-T72",
            "yes",
            "buy",
            5,
            0.45,
            time_in_force="good_till_canceled",
            cycle="12z",
        )
        actual = mock_post.call_args.args[1]["client_order_id"]

        assert actual == precomputed

    def test_deterministic_for_identical_inputs(self):
        import kalshi_client

        id1 = kalshi_client.compute_client_order_id(
            "KXHIGH-26APR25-T72", "yes", "buy", 5, 0.45, "good_till_canceled", "12z"
        )
        id2 = kalshi_client.compute_client_order_id(
            "KXHIGH-26APR25-T72", "yes", "buy", 5, 0.45, "good_till_canceled", "12z"
        )
        assert id1 == id2

    def test_differs_when_action_differs(self):
        """A buy and a sell for the same ticker/side/qty/price/cycle (e.g.
        an entry and a same-cycle exit) must not collide on the same id --
        distinct real orders on the exchange."""
        import kalshi_client

        buy_id = kalshi_client.compute_client_order_id(
            "KXHIGH-26APR25-T72", "yes", "buy", 5, 0.45, "good_till_canceled", "12z"
        )
        sell_id = kalshi_client.compute_client_order_id(
            "KXHIGH-26APR25-T72", "yes", "sell", 5, 0.45, "good_till_canceled", "12z"
        )
        assert buy_id != sell_id

    def test_differs_when_price_differs(self):
        import kalshi_client

        id1 = kalshi_client.compute_client_order_id(
            "KXHIGH-26APR25-T72", "yes", "buy", 5, 0.45, "good_till_canceled", "12z"
        )
        id2 = kalshi_client.compute_client_order_id(
            "KXHIGH-26APR25-T72", "yes", "buy", 5, 0.46, "good_till_canceled", "12z"
        )
        assert id1 != id2

    def test_differs_when_time_in_force_differs(self):
        """AUD batch-23 #1: a GTC entry and a later IOC taker-cross
        replacement of it (order_executor._replace_live_order) round to the
        identical ticker+side+action+count+price+cycle -- without
        time_in_force in the key, the taker-cross would silently dedupe
        against the earlier GTC attempt and become a no-op that logs
        success while the position never actually re-enters. Mutation-
        tested: dropping time_in_force from compute_client_order_id's own
        idempotency_input f-string makes this fail."""
        import kalshi_client

        gtc_id = kalshi_client.compute_client_order_id(
            "KXHIGH-26APR25-T72", "yes", "buy", 5, 0.45, "good_till_canceled", "12z"
        )
        ioc_id = kalshi_client.compute_client_order_id(
            "KXHIGH-26APR25-T72", "yes", "buy", 5, 0.45, "immediate_or_cancel", "12z"
        )
        assert gtc_id != ioc_id


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

    def test_default_limit_applied_when_caller_omits_it(self):
        """AUD batch-23 #2: weather_markets.py's own series-wide scan calls
        get_markets(series_ticker=series) with no limit at all -- must
        default to 1000 (Kalshi's max page size) rather than relying on
        Kalshi's own unstated server-side default."""
        import kalshi_client

        client = self._make_client()
        client._get = MagicMock(return_value={"markets": []})
        client._validate = MagicMock()

        with patch.object(kalshi_client, "validate_market"):
            client.get_markets(series_ticker="KXHIGHNY")

        params = client._get.call_args[1]["params"]
        assert params["limit"] == 1000
        assert params["series_ticker"] == "KXHIGHNY"

    def test_caller_supplied_limit_is_not_overridden(self):
        import kalshi_client

        client = self._make_client()
        client._get = MagicMock(return_value={"markets": []})
        client._validate = MagicMock()

        with patch.object(kalshi_client, "validate_market"):
            client.get_markets(limit=50)

        params = client._get.call_args[1]["params"]
        assert params["limit"] == 50

    def test_stops_on_empty_page_with_nonempty_cursor(self):
        """AUD batch-23 #2: lifts get_trades' 3-guard shape -- Kalshi can
        return a non-empty cursor on what turns out to be the LAST page
        (confirmed live, see get_trades' docstring); an empty `markets` list
        on the NEXT call is what actually signals done, not cursor absence
        alone. Uses a DIFFERENT cursor on the empty final page so this
        isolates the `not page` check from the separate repeated-cursor
        guard."""
        import kalshi_client

        client = self._make_client()
        page1 = [{"ticker": "MKT-1", "yes_bid": 50, "yes_ask": 55, "volume": 100}]
        client._get = MagicMock(
            side_effect=[
                {"markets": page1, "cursor": "abc123"},
                {"markets": [], "cursor": "different-cursor"},
            ]
        )
        client._validate = MagicMock()

        with patch.object(kalshi_client, "validate_market"):
            result = client.get_markets()

        assert result == page1
        assert client._get.call_count == 2

    def test_repeated_cursor_stops_pagination(self):
        """A cursor identical to one already seen must stop the loop rather
        than spin forever."""
        import kalshi_client

        client = self._make_client()
        client._get = MagicMock(
            return_value={
                "markets": [
                    {"ticker": "MKT-1", "yes_bid": 50, "yes_ask": 55, "volume": 100}
                ],
                "cursor": "same-cursor",
            }
        )
        client._validate = MagicMock()

        with patch.object(kalshi_client, "validate_market"):
            result = client.get_markets()

        assert client._get.call_count == 2
        assert len(result) == 2

    # ── AUD-0060 / backlog L23905: validate_market()'s return value ─────────

    def test_structurally_unusable_markets_are_dropped(self, caplog):
        """Entries no consumer could read at all must not reach the caller.

        Mutation check: replacing the `_is_structurally_usable(market)` guard
        with a bare `validate_market(market, ...)` statement (the pre-batch-62
        code) makes this fail -- all four entries come back instead of two.
        """
        import logging

        client = self._make_client()
        good_legacy = {
            "ticker": "KXHIGHNY-26JUN15-T75",
            "yes_bid": 0.50,
            "yes_ask": 0.55,
            "volume": 100,
        }
        good_current = {
            "ticker": "KXLOWTSFO-26MAY26-B51.5",
            "yes_bid_dollars": 0.20,
            "yes_ask_dollars": 0.25,
            "volume_fp": 10,
        }
        no_ticker = {"yes_bid": 0.50, "yes_ask": 0.55, "volume": 100}
        no_volume_under_either_name = {
            "ticker": "KXHIGHCHI-26JUN02-T81",
            "yes_bid": 0.50,
            "yes_ask": 0.55,
        }
        client._get = MagicMock(
            return_value={
                "markets": [
                    good_legacy,
                    no_ticker,
                    good_current,
                    no_volume_under_either_name,
                ]
            }
        )
        client._validate = MagicMock()

        with caplog.at_level(logging.ERROR, logger="kalshi_client"):
            result = client.get_markets()

        assert [m["ticker"] for m in result] == [
            "KXHIGHNY-26JUN15-T75",
            "KXLOWTSFO-26MAY26-B51.5",
        ]
        # Dropped entries are recoverable from the log -- get_markets also
        # feeds settlement sync, where a silent drop is a lost settlement.
        assert "KXHIGHCHI-26JUN02-T81" in caplog.text
        assert "<no ticker>" in caplog.text

    def test_economically_odd_but_real_markets_are_kept(self, caplog):
        """The point of the structural/economic split (opus-review-caught).

        A locked book (bid == ask) and a settled market (100/100) both fail
        schema_validator.validate_market's inverted-spread check, but they are
        real states -- and get_markets feeds settlement sync and the hourly
        ladder proxy, where dropping one yields a silently WRONG number. They
        must survive, with validate_market's warning still emitted.

        Mutation check: gating the append on `validate_market(...)`'s bool
        instead of `_is_structurally_usable(...)` makes this fail.
        """
        import logging

        client = self._make_client()
        locked = {
            "ticker": "KXHIGHNY-26JUN15-T75",
            "yes_bid": 52,
            "yes_ask": 52,
            "volume": 100,
        }
        settled_yes = {
            "ticker": "KXLOWTSEA-26AUG23-T59",
            "yes_bid": 100,
            "yes_ask": 100,
            "volume": 40,
        }
        illiquid_no_quote = {
            "ticker": "KXHIGHTPHX-26JUL04-B99.5",
            "yes_bid": 0,
            "yes_ask": 0,
            "volume": 0,
        }
        client._get = MagicMock(
            return_value={"markets": [locked, settled_yes, illiquid_no_quote]}
        )
        client._validate = MagicMock()

        with caplog.at_level(logging.WARNING):
            result = client.get_markets()

        assert len(result) == 3
        # Positive control: validate_market really did object to two of them,
        # so "kept anyway" is the deliberate behaviour and not a case of the
        # validator silently passing them.
        assert "inverted spread" in caplog.text

    def test_all_unusable_page_fails_open_instead_of_returning_empty(self, caplog):
        """A page where EVERY entry is unusable is treated as an API schema
        change, not as N bad markets.

        Returning [] would be indistinguishable from "this series has no open
        markets", and weather_markets._fetch_series only sets its `degraded`
        flag on an exception -- so the empty list would be cached as healthy
        for the full 60s TTL.
        """
        import logging

        client = self._make_client()
        # Plausible shape after a hypothetical Kalshi rename of every price key.
        renamed = [
            {"ticker": "KXHIGHNY-26JUN15-T75", "bid_cents": 50, "ask_cents": 55},
            {"ticker": "KXLOWTSFO-26MAY26-B51.5", "bid_cents": 20, "ask_cents": 25},
        ]
        client._get = MagicMock(return_value={"markets": renamed})
        client._validate = MagicMock()

        with caplog.at_level(logging.ERROR, logger="kalshi_client"):
            result = client.get_markets()

        assert len(result) == 2, "must not collapse to an empty (healthy) list"
        assert "API schema change" in caplog.text

    def test_get_market_singular_stays_warn_only(self, caplog):
        """The singular getter deliberately still returns the dict it got,
        warning rather than filtering -- 15+ call sites depend on a dict
        always coming back. See get_market's own docstring."""
        import logging

        client = self._make_client()
        malformed = {
            "ticker": "KXHIGHNY-26JUN15-T75",
            "yes_bid": -0.50,
            "yes_ask": 0.55,
            "volume": 100,
        }
        client._get = MagicMock(return_value={"market": malformed})
        client._validate = MagicMock()

        with caplog.at_level(logging.WARNING, logger="schema_validator"):
            result = client.get_market("KXHIGHNY-26JUN15-T75")

        assert result == malformed, "get_market must not start filtering"
        assert "out of range" in caplog.text, (
            "positive control: validate_market really did reject this market, "
            "so 'returned anyway' is the deliberate behaviour and not a case "
            "of the validator silently passing it"
        )

    def test_page_cap_stops_at_50_pages(self):
        """A server that keeps minting fresh (never-repeated) cursors must
        not hang this synchronous scan indefinitely."""
        import kalshi_client

        client = self._make_client()
        call_count = {"n": 0}

        def _fake_get(path, params=None, auth=False):
            call_count["n"] += 1
            return {
                "markets": [
                    {
                        "ticker": f"MKT-{call_count['n']}",
                        "yes_bid": 50,
                        "yes_ask": 55,
                        "volume": 100,
                    }
                ],
                "cursor": f"cursor-{call_count['n']}",
            }

        client._get = MagicMock(side_effect=_fake_get)
        client._validate = MagicMock()

        with patch.object(kalshi_client, "validate_market"):
            result = client.get_markets()

        assert client._get.call_count == 50
        assert len(result) == 50


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


class TestPaginatedPortfolioAndPublicListEndpoints:
    """AUD batch-23 #3: get_positions()/get_events()/get_series_list()
    previously returned only a single unpaginated page each, unlike every
    other list endpoint in this file -- an account/catalog exceeding one
    page silently truncated with no log. All three now route through the
    shared _paginate_get helper."""

    def _make_client(self):
        with patch("kalshi_client.KalshiClient.__init__", return_value=None):
            import kalshi_client

            client = kalshi_client.KalshiClient.__new__(kalshi_client.KalshiClient)
        return client

    def test_get_positions_single_page(self):
        client = self._make_client()
        positions = [{"ticker": "MKT-1"}, {"ticker": "MKT-2"}]
        client._get = MagicMock(return_value={"market_positions": positions})
        client._validate = MagicMock()

        result = client.get_positions()

        assert result == positions
        client._get.assert_called_once()
        assert client._get.call_args[0][0] == "/portfolio/positions"
        assert client._get.call_args[1]["auth"] is True

    def test_get_positions_paginates_across_pages(self):
        client = self._make_client()
        page1 = [{"ticker": "MKT-1"}]
        page2 = [{"ticker": "MKT-2"}]
        client._get = MagicMock(
            side_effect=[
                {"market_positions": page1, "cursor": "c1"},
                {"market_positions": page2},
            ]
        )
        client._validate = MagicMock()

        result = client.get_positions()

        assert len(result) == 2
        assert client._get.call_count == 2
        second_params = client._get.call_args_list[1][1]["params"]
        assert second_params.get("cursor") == "c1"

    def test_get_positions_stops_on_empty_page_with_nonempty_cursor(self):
        client = self._make_client()
        page1 = [{"ticker": "MKT-1"}]
        client._get = MagicMock(
            side_effect=[
                {"market_positions": page1, "cursor": "c1"},
                {"market_positions": [], "cursor": "c2"},
            ]
        )
        client._validate = MagicMock()

        result = client.get_positions()

        assert result == page1
        assert client._get.call_count == 2

    def test_get_positions_repeated_cursor_stops_pagination(self):
        client = self._make_client()
        client._get = MagicMock(
            return_value={
                "market_positions": [{"ticker": "MKT-1"}],
                "cursor": "same-cursor",
            }
        )
        client._validate = MagicMock()

        result = client.get_positions()

        assert client._get.call_count == 2
        assert len(result) == 2

    def test_get_events_paginates_and_preserves_filter_params(self):
        client = self._make_client()
        page1 = [{"event_ticker": "EV-1"}]
        page2 = [{"event_ticker": "EV-2"}]
        client._get = MagicMock(
            side_effect=[
                {"events": page1, "cursor": "c1"},
                {"events": page2},
            ]
        )
        client._validate = MagicMock()

        result = client.get_events(status="open")

        assert len(result) == 2
        assert client._get.call_args_list[0][0][0] == "/events"
        first_params = client._get.call_args_list[0][1]["params"]
        assert first_params["status"] == "open"
        # AUD batch-23 #3 opus follow-up: /events documents a max of 200,
        # NOT 1000 (get_markets/get_trades/get_positions' max) -- an
        # out-of-range limit risks a 400 where the endpoint previously
        # returned data at all.
        assert first_params["limit"] == 200

    def test_get_series_list_paginates_and_preserves_filter_params(self):
        client = self._make_client()
        page1 = [{"ticker": "SER-1"}]
        page2 = [{"ticker": "SER-2"}]
        client._get = MagicMock(
            side_effect=[
                {"series": page1, "cursor": "c1"},
                {"series": page2},
            ]
        )
        client._validate = MagicMock()

        result = client.get_series_list(category="Climate and Weather")

        assert len(result) == 2
        assert client._get.call_args_list[0][0][0] == "/series"
        first_params = client._get.call_args_list[0][1]["params"]
        assert first_params["category"] == "Climate and Weather"
        # AUD batch-23 #3 opus follow-up: /series documents no limit/cursor
        # support at all -- unlike /events and /portfolio/positions, no
        # limit param must ever be sent here (an unrecognized query param
        # risks rejection on a strict server).
        assert "limit" not in first_params

    def test_page_cap_stops_at_50_pages(self):
        """Runaway-loop backstop shared across all three via _paginate_get --
        exercised once here (get_series_list) rather than duplicated 3x,
        since it's the same helper underneath."""
        client = self._make_client()
        call_count = {"n": 0}

        def _fake_get(path, params=None, auth=False):
            call_count["n"] += 1
            return {
                "series": [{"ticker": f"SER-{call_count['n']}"}],
                "cursor": f"cursor-{call_count['n']}",
            }

        client._get = MagicMock(side_effect=_fake_get)
        client._validate = MagicMock()

        result = client.get_series_list()

        assert client._get.call_count == 50
        assert len(result) == 50


class TestGetFills:
    """Batch-49 item 1: get_fills() -- go/no-go gate confirmed live 2026-08-24
    (and via docs.kalshi.com's OpenAPI-derived Fill schema) that the fee
    field is `fee_cost` (string, fixed-point dollars) and the endpoint
    paginates the same way as get_trades/get_positions/etc."""

    def _make_client(self):
        with patch("kalshi_client.KalshiClient.__init__", return_value=None):
            import kalshi_client

            client = kalshi_client.KalshiClient.__new__(kalshi_client.KalshiClient)
        return client

    def test_single_page_returns_fee_cost_field(self):
        client = self._make_client()
        fills = [
            {
                "fill_id": "f1",
                "ticker": "KXHIGHNY-26AUG24-T80",
                "is_taker": False,
                "fee_cost": "0.0000",
            }
        ]
        client._get = MagicMock(return_value={"fills": fills})
        client._validate = MagicMock()

        result = client.get_fills()

        assert result == fills
        assert client._get.call_args[0][0] == "/portfolio/fills"
        assert client._get.call_args[1]["auth"] is True

    def test_paginates_across_pages(self):
        client = self._make_client()
        page1 = [{"fill_id": "f1"}]
        page2 = [{"fill_id": "f2"}]
        client._get = MagicMock(
            side_effect=[
                {"fills": page1, "cursor": "c1"},
                {"fills": page2},
            ]
        )
        client._validate = MagicMock()

        result = client.get_fills()

        assert len(result) == 2
        assert client._get.call_count == 2

    def test_passes_through_filter_params(self):
        """ticker/order_id/min_ts/max_ts are documented optional filters --
        must reach the API call unmodified (same passthrough convention as
        get_markets/get_events)."""
        client = self._make_client()
        client._get = MagicMock(return_value={"fills": []})
        client._validate = MagicMock()

        client.get_fills(ticker="KXHIGHNY-26AUG24-T80", min_ts=1000, max_ts=2000)

        params = client._get.call_args[1]["params"]
        assert params["ticker"] == "KXHIGHNY-26AUG24-T80"
        assert params["min_ts"] == 1000
        assert params["max_ts"] == 2000
        assert params["limit"] == 1000  # default max page size

    def test_empty_fill_set_returns_empty_list(self):
        """Go/no-go spec explicitly allows this: 'if the account has zero
        real fills, assert against an empty set and note it' -- confirmed
        live 2026-08-24 (this account currently has zero fills)."""
        client = self._make_client()
        client._get = MagicMock(return_value={"fills": []})
        client._validate = MagicMock()

        assert client.get_fills() == []


class TestQueuePosition:
    """Batch-49 item 2: get_order_queue_position()/get_bulk_queue_positions().
    Field names (queue_position_fp, market_tickers/event_ticker query
    params) and the "need market_tickers or event_ticker" 400 confirmed
    live 2026-08-24 and via docs.kalshi.com."""

    def _make_client(self):
        with patch("kalshi_client.KalshiClient.__init__", return_value=None):
            import kalshi_client

            client = kalshi_client.KalshiClient.__new__(kalshi_client.KalshiClient)
        return client

    def test_get_order_queue_position_parses_fixed_point_string(self):
        client = self._make_client()
        client._get = MagicMock(return_value={"queue_position_fp": "10.00"})

        result = client.get_order_queue_position("ORD-1")

        assert result == 10.0
        assert client._get.call_args[0][0] == "/portfolio/orders/ORD-1/queue_position"
        assert client._get.call_args[1]["auth"] is True

    def test_get_order_queue_position_missing_field_returns_none(self):
        """Response-shape drift must warn, not crash -- same fail-soft
        convention as _validate elsewhere in this file, since this is
        read-only instrumentation, not a trading-critical read."""
        client = self._make_client()
        client._get = MagicMock(return_value={"unexpected": "shape"})

        assert client.get_order_queue_position("ORD-1") is None

    def test_get_order_queue_position_unparseable_returns_none(self):
        client = self._make_client()
        client._get = MagicMock(return_value={"queue_position_fp": "not-a-number"})

        assert client.get_order_queue_position("ORD-1") is None

    def test_get_order_queue_position_non_dict_response_returns_none(self):
        """Opus review follow-up: a non-dict response (e.g. a raw string/
        list on a degraded API) must warn and return None, not raise
        AttributeError from data.get(...)."""
        client = self._make_client()
        client._get = MagicMock(return_value=["unexpected", "shape"])

        assert client.get_order_queue_position("ORD-1") is None

    def test_bulk_empty_list_market_tickers_raises(self):
        """Opus review follow-up: market_tickers=[] is falsy, same as None
        -- must hit the same fail-fast ValueError, not silently send an
        empty market_tickers param."""
        client = self._make_client()
        client._get = MagicMock()

        with pytest.raises(ValueError, match="market_tickers or event_ticker"):
            client.get_bulk_queue_positions(market_tickers=[])

        client._get.assert_not_called()

    def test_bulk_requires_market_tickers_or_event_ticker(self):
        """Confirmed live 2026-08-24: the endpoint 400s with 'Need to
        specify market_tickers or event_ticker' when both are omitted --
        fail fast client-side instead of making a request guaranteed to
        error."""
        client = self._make_client()
        client._get = MagicMock()

        with pytest.raises(ValueError, match="market_tickers or event_ticker"):
            client.get_bulk_queue_positions()

        client._get.assert_not_called()

    def test_bulk_joins_ticker_list_into_comma_separated_param(self):
        client = self._make_client()
        client._get = MagicMock(return_value={"queue_positions": []})

        client.get_bulk_queue_positions(market_tickers=["MKT-1", "MKT-2"])

        params = client._get.call_args[1]["params"]
        assert params["market_tickers"] == "MKT-1,MKT-2"

    def test_bulk_accepts_event_ticker(self):
        client = self._make_client()
        client._get = MagicMock(return_value={"queue_positions": []})

        client.get_bulk_queue_positions(event_ticker="EV-1")

        params = client._get.call_args[1]["params"]
        assert params["event_ticker"] == "EV-1"
        assert "market_tickers" not in params

    def test_bulk_normalizes_null_queue_positions_to_empty_list(self):
        """Confirmed live 2026-08-24: `queue_positions` can be JSON null
        when nothing matches the filter (not an empty list) -- callers must
        never need a None-check."""
        client = self._make_client()
        client._get = MagicMock(return_value={"queue_positions": None})

        assert client.get_bulk_queue_positions(market_tickers="MKT-1") == []

    def test_bulk_returns_raw_entries(self):
        client = self._make_client()
        entries = [
            {"order_id": "ORD-1", "market_ticker": "MKT-1", "queue_position_fp": "5.00"}
        ]
        client._get = MagicMock(return_value={"queue_positions": entries})

        assert client.get_bulk_queue_positions(market_tickers="MKT-1") == entries


class TestGetLiveWeatherIndex:
    """Batch-52 item 3: get_live_weather_index() -- the Kalshi Weather
    Index live-data feed, KXTEMPMIAH's real settlement source. Public
    (auth=False), unlike every _paginate_get-based endpoint above which
    sends auth headers unconditionally."""

    def _make_client(self):
        with patch("kalshi_client.KalshiClient.__init__", return_value=None):
            import kalshi_client

            client = kalshi_client.KalshiClient.__new__(kalshi_client.KalshiClient)
        return client

    def test_returns_raw_response_and_lowercases_city_and_uses_no_auth(self):
        client = self._make_client()
        raw = {
            "city": "miami",
            "config_version": "miami-temperature-v1.0-cal-20260824",
            "timeseries": [{"t": 1, "v": 86.0, "contributors": 5, "status": "normal"}],
        }
        client._get = MagicMock(return_value=raw)

        result = client.get_live_weather_index("Miami")

        assert result == raw
        assert client._get.call_args[0][0] == "/live_data/weather/miami"
        assert client._get.call_args[1]["auth"] is False

    def test_missing_timeseries_key_returns_none(self):
        """Response-shape drift must warn, not crash -- same fail-soft
        convention as get_order_queue_position."""
        client = self._make_client()
        client._get = MagicMock(return_value={"city": "miami", "unexpected": "shape"})

        assert client.get_live_weather_index("miami") is None

    def test_non_dict_response_returns_none(self):
        client = self._make_client()
        client._get = MagicMock(return_value=["unexpected", "shape"])

        assert client.get_live_weather_index("miami") is None

    def test_rejects_invalid_city_path_segment(self):
        """opus review L-1: defense in depth against path-segment
        manipulation, mirroring _validate_ticker_format's role for every
        other path-interpolated method in this file -- this was the one
        method with no equivalent guard."""
        client = self._make_client()
        client._get = MagicMock()

        with pytest.raises(ValueError, match="invalid city"):
            client.get_live_weather_index("../etc/passwd")

        client._get.assert_not_called()

    def test_rejects_non_string_city(self):
        client = self._make_client()
        client._get = MagicMock()

        with pytest.raises(ValueError, match="invalid city"):
            client.get_live_weather_index(None)

        client._get.assert_not_called()

    def test_accepts_plain_lowercase_city(self):
        client = self._make_client()
        client._get = MagicMock(return_value={"timeseries": []})

        client.get_live_weather_index("miami")

        client._get.assert_called_once()


class TestEnvFilePermissions:
    """AUD batch-23 #5: .env can carry KALSHI_PRIVATE_KEY_PEM -- the entire
    private key in plaintext -- when the WebSocket feed is enabled, but was
    never permission-checked the way the .pem file already is.

    Deliberately WARN-ONLY (never mutates ACLs/chmod) -- opus review caught
    that reusing _check_key_permissions' destructive Windows icacls path
    (strips ALL inherited ACEs, including SYSTEM/Administrators) on a
    general config file like .env risks silently locking out a future
    service-account/SYSTEM deployment, a worse failure mode (every
    authenticated call fails closed) than the plaintext-exposure risk being
    warned about."""

    def test_noop_when_env_file_not_found(self):
        import kalshi_client

        with (
            patch("dotenv.find_dotenv", return_value=""),
            patch("subprocess.run") as mock_run,
        ):
            kalshi_client._check_env_file_permissions()

        mock_run.assert_not_called()

    def test_noop_when_found_env_is_outside_this_repos_directory(self, tmp_path):
        """find_dotenv()'s upward filesystem walk could land on an
        unrelated .env in a parent/home directory if none exists in the
        repo -- must never act on that file."""
        import kalshi_client

        outside_dir = tmp_path / "unrelated"
        outside_dir.mkdir()
        outside_env = outside_dir / ".env"
        outside_env.write_text("SOME_OTHER_APPS_SECRET=xyz\n")

        with (
            patch("dotenv.find_dotenv", return_value=str(outside_env)),
            patch("subprocess.run") as mock_run,
        ):
            kalshi_client._check_env_file_permissions()

        mock_run.assert_not_called()

    def _fake_repo_env(self, monkeypatch, tmp_path):
        """Point kalshi_client's own __file__ at a throwaway directory so
        the scope check (env must live in kalshi_client.py's own directory)
        passes for a tmp_path .env -- WITHOUT ever touching this repo's
        real .env file. Returns the fake .env path (not yet created)."""
        import kalshi_client

        monkeypatch.setattr(
            kalshi_client, "__file__", str(tmp_path / "kalshi_client.py")
        )
        return tmp_path / ".env"

    def test_windows_icacls_call_is_read_only(self, monkeypatch, tmp_path):
        """The Windows branch must NEVER pass /inheritance:r or /grant:r --
        those are what makes _check_key_permissions' .pem-file treatment
        destructive; .env must only ever be inspected, never mutated."""
        import subprocess as _subprocess

        import kalshi_client

        env_file = self._fake_repo_env(monkeypatch, tmp_path)
        env_file.write_text("KALSHI_KEY_ID=abc\n")
        monkeypatch.setattr("platform.system", lambda: "Windows")

        mock_run = MagicMock(
            return_value=_subprocess.CompletedProcess(
                args=[], returncode=0, stdout="SRTGSTG\\thesa:(F)\n", stderr=""
            )
        )
        with (
            patch("dotenv.find_dotenv", return_value=str(env_file)),
            patch("subprocess.run", mock_run),
        ):
            kalshi_client._check_env_file_permissions()

        mock_run.assert_called_once()
        argv = mock_run.call_args[0][0]
        assert argv[0] == "icacls"
        assert "/inheritance:r" not in argv
        assert "/grant:r" not in argv

    def test_windows_warns_on_broad_grant(self, monkeypatch, tmp_path, caplog):
        import logging
        import subprocess as _subprocess

        import kalshi_client

        env_file = self._fake_repo_env(monkeypatch, tmp_path)
        env_file.write_text("KALSHI_KEY_ID=abc\n")
        monkeypatch.setattr("platform.system", lambda: "Windows")

        mock_run = MagicMock(
            return_value=_subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="BUILTIN\\Users:(F)\nSRTGSTG\\thesa:(F)\n",
                stderr="",
            )
        )
        with (
            patch("dotenv.find_dotenv", return_value=str(env_file)),
            patch("subprocess.run", mock_run),
            caplog.at_level(logging.WARNING, logger="kalshi_client"),
        ):
            kalshi_client._check_env_file_permissions()

        assert "readable by more than the current user" in caplog.text

    def test_windows_no_warning_on_narrow_grant(self, monkeypatch, tmp_path, caplog):
        import logging
        import subprocess as _subprocess

        import kalshi_client

        env_file = self._fake_repo_env(monkeypatch, tmp_path)
        env_file.write_text("KALSHI_KEY_ID=abc\n")
        monkeypatch.setattr("platform.system", lambda: "Windows")

        mock_run = MagicMock(
            return_value=_subprocess.CompletedProcess(
                args=[], returncode=0, stdout="SRTGSTG\\thesa:(F)\n", stderr=""
            )
        )
        with (
            patch("dotenv.find_dotenv", return_value=str(env_file)),
            patch("subprocess.run", mock_run),
            caplog.at_level(logging.WARNING, logger="kalshi_client"),
        ):
            kalshi_client._check_env_file_permissions()

        assert caplog.text == ""

    def test_warns_on_world_readable_env_file(self, monkeypatch, tmp_path, caplog):
        """Unix: mirrors _check_key_permissions' own chmod-based check. Uses
        a throwaway tmp_path .env (never the real repo .env)."""
        import logging
        import platform

        import kalshi_client

        if platform.system() == "Windows":
            pytest.skip("Permission checks not applicable on Windows")

        env_file = self._fake_repo_env(monkeypatch, tmp_path)
        env_file.write_text("KALSHI_KEY_ID=abc\n")
        env_file.chmod(0o644)

        with (
            patch("dotenv.find_dotenv", return_value=str(env_file)),
            caplog.at_level(logging.WARNING, logger="kalshi_client"),
        ):
            kalshi_client._check_env_file_permissions()
        assert "readable by group/others" in caplog.text

    def test_no_warning_on_private_env_file(self, monkeypatch, tmp_path, caplog):
        """Unix: 0600 permissions must not warn."""
        import logging
        import platform

        import kalshi_client

        if platform.system() == "Windows":
            pytest.skip("Permission checks not applicable on Windows")

        env_file = self._fake_repo_env(monkeypatch, tmp_path)
        env_file.write_text("KALSHI_KEY_ID=abc\n")
        env_file.chmod(0o600)

        with (
            patch("dotenv.find_dotenv", return_value=str(env_file)),
            caplog.at_level(logging.WARNING, logger="kalshi_client"),
        ):
            kalshi_client._check_env_file_permissions()
        assert caplog.text == ""

    def test_client_init_checks_env_file(self):
        """Every KalshiClient() construction checks .env, unconditionally --
        not gated on whether KALSHI_PRIVATE_KEY_PEM happens to be set this
        run."""
        import kalshi_client

        with patch("kalshi_client._check_env_file_permissions") as mock_check_env:
            kalshi_client.KalshiClient(key_id="k", private_key_path=None, env="demo")

        mock_check_env.assert_called_once()


class TestOrderIdPathValidation:
    """Batch-58 item 1 (backlog L25336): order_id flowed unvalidated into four
    REST path segments (get_order_queue_position, get_order, cancel_order,
    amend_order), the same path-manipulation exposure AUD-0076 closed for
    ticker/series_ticker. main.py's cmd_cancel is the raw-CLI path into
    cancel_order."""

    def _make_client(self):
        from unittest.mock import patch

        with patch("kalshi_client.KalshiClient.__init__", return_value=None):
            import kalshi_client

            return kalshi_client.KalshiClient.__new__(kalshi_client.KalshiClient)

    def test_accepts_a_canonical_kalshi_uuid(self):
        """The charset must admit a real order_id. Kalshi documents order_id
        as a UUID, so a lowercase-hex UUID with dashes is the shape that
        absolutely must not be rejected -- reusing the uppercase-only
        _TICKER_RE would have rejected every real id."""
        from kalshi_client import _validate_order_id_format

        _validate_order_id_format("order_id", "5f3a8b2c-1d4e-4f6a-9b8c-0e1f2a3b4c5d")

    def test_accepts_other_plausible_opaque_exchange_ids(self):
        """Deliberately not a canonical-UUID regex: nothing in this repo can
        confirm the exchange's real id shape (zero live rows have ever been
        stored), and a too-tight regex would make cancel_order raise on a
        real id -- i.e. a live position that cannot be closed."""
        from kalshi_client import _validate_order_id_format

        for value in (
            "ord_1",
            "ORD-1",
            "abc123",
            "a",
            "A1_b2-c3",
            "0" * 64,
            # Opus review (batch-58, L4): a dot INSIDE a segment is admitted.
            # Kalshi's own identifiers already use one -- _TICKER_RE had to
            # be widened for KXHIGHAUS-26JUN06-B88.5 (119 of 364 distinct
            # real tickers) -- so excluding it would have been the likeliest
            # way to reject a real order_id on a cancel path.
            "a.b",
            "KXHIGHAUS-26JUN06-B88.5",
        ):
            _validate_order_id_format("order_id", value)

    @pytest.mark.parametrize(
        "bad",
        [
            "../../portfolio/positions",  # path traversal
            "a/b",  # bare separator
            "..",  # traversal segment, no slash needed
            ".",  # the other traversal segment
            "a\\b",  # backslash (Windows-style separator)
            "a?x=1",  # query injection
            "a#frag",  # fragment
            "a%2fb",  # percent-encoding
            "a b",  # space
            "abc\n",  # trailing newline -- \Z anchor, not $
            "\nabc",
            "",  # empty segment
            "0" * 65,  # over the length cap
        ],
    )
    def test_rejects_path_manipulating_and_oversized_ids(self, bad):
        from kalshi_client import _validate_order_id_format

        with pytest.raises(ValueError):
            _validate_order_id_format("order_id", bad)

    def test_rejects_non_string(self):
        from kalshi_client import _validate_order_id_format

        for bad in (None, 12345, ["a"], {"a": 1}):
            with pytest.raises(ValueError):
                _validate_order_id_format("order_id", bad)

    def test_get_order_rejects_before_any_http_call(self):
        """Absence assertion (`_get` never called) paired with its positive
        control: the SAME mock IS called for a valid id, so this cannot pass
        by the request path being broken for an unrelated reason."""
        from unittest.mock import MagicMock

        client = self._make_client()
        client._get = MagicMock(return_value={"order": {"status": "resting"}})

        for bad in ("../../portfolio/positions", "..", "."):
            with pytest.raises(ValueError):
                client.get_order(bad)
        client._get.assert_not_called()

        client.get_order("5f3a8b2c-1d4e-4f6a-9b8c-0e1f2a3b4c5d")
        assert client._get.call_count == 1

    def test_cancel_order_rejects_before_any_http_call(self):
        from unittest.mock import MagicMock

        client = self._make_client()
        client._delete = MagicMock(return_value={"order_id": "x"})

        with pytest.raises(ValueError):
            client.cancel_order("a/b")
        client._delete.assert_not_called()

        client.cancel_order("5f3a8b2c-1d4e-4f6a-9b8c-0e1f2a3b4c5d")
        assert client._delete.call_count == 1

    def test_amend_order_rejects_before_any_http_call(self):
        from unittest.mock import MagicMock

        client = self._make_client()
        client._post = MagicMock(return_value={"order_id": "x"})

        with pytest.raises(ValueError):
            client.amend_order(
                order_id="a?x=1",
                ticker="KXHIGH-26APR25-T72",
                side="yes",
                action="buy",
                count=5,
                price=0.55,
            )
        client._post.assert_not_called()

        client.amend_order(
            order_id="5f3a8b2c-1d4e-4f6a-9b8c-0e1f2a3b4c5d",
            ticker="KXHIGH-26APR25-T72",
            side="yes",
            action="buy",
            count=5,
            price=0.55,
        )
        assert client._post.call_count == 1

    def test_amend_order_also_validates_its_ticker(self):
        """amend_order interpolates order_id into the path but ALSO passes
        ticker straight into the request body -- the same
        _validate_ticker_format guard every other ticker-taking method has."""
        from unittest.mock import MagicMock

        client = self._make_client()
        client._post = MagicMock(return_value={"order_id": "x"})

        with pytest.raises(ValueError):
            client.amend_order(
                order_id="5f3a8b2c-1d4e-4f6a-9b8c-0e1f2a3b4c5d",
                ticker="../../markets",
                side="yes",
                action="buy",
                count=5,
                price=0.55,
            )
        client._post.assert_not_called()

    def test_get_order_queue_position_rejects_before_any_http_call(self):
        from unittest.mock import MagicMock

        client = self._make_client()
        client._get = MagicMock(return_value={"queue_position_fp": "3.0"})

        with pytest.raises(ValueError):
            client.get_order_queue_position("a#frag")
        client._get.assert_not_called()

        assert client.get_order_queue_position("ORD-1") == pytest.approx(3.0)
        assert client._get.call_count == 1

    def test_every_path_interpolating_method_validates_its_segment(self):
        """Opus review (batch-58, M4): item 1 exists partly BECAUSE a
        docstring asserted "this is the one path-interpolating method with no
        guard" and silently went false. The fix replaces it with a new
        absolute -- "every path-interpolating method in this file validates
        its own segment" -- so that claim needs a drift guard of its own, in
        the same shape as TestLiveOrderPathsGuard's call-site counter.

        Source-counts the f-string path interpolations. If this fails, a new
        one was added: check it validates its segment, then update the count.
        """
        import inspect
        import re

        import kalshi_client

        src = inspect.getsource(kalshi_client)
        interpolations = re.findall(r"self\._(?:get|post|delete|put)\(\s*f\"", src)
        assert len(interpolations) == 7, (
            f"path-interpolating call count changed to {len(interpolations)} "
            "(was 7: get_market, get_orderbook, get_live_weather_index, "
            "get_order_queue_position, get_order, cancel_order, amend_order). "
            "Verify the new one validates its own path segment before "
            "updating this number."
        )

        # Positive control: the guards are actually present, so the count
        # above cannot pass while the validation was deleted.
        assert src.count('_validate_order_id_format("order_id"') == 4
        assert src.count('_validate_ticker_format("ticker"') >= 3

    def test_cmd_cancel_strips_and_reports_a_bad_id_without_raising(self):
        """main.cmd_cancel is the one raw-CLI path in. A trailing newline on
        a pasted id must still work; anything genuinely malformed must print
        an error rather than surface a traceback to the operator."""
        from unittest.mock import MagicMock

        import main

        client = MagicMock()
        client.cancel_order.return_value = {"order_id": "ord_x"}

        main.cmd_cancel(client, "  5f3a8b2c-1d4e-4f6a-9b8c-0e1f2a3b4c5d\n")
        client.cancel_order.assert_called_once_with(
            "5f3a8b2c-1d4e-4f6a-9b8c-0e1f2a3b4c5d"
        )

    def test_cmd_cancel_reports_a_malformed_id_and_places_no_call(self, capsys):
        """L1: the previous version of this test called cmd_cancel and
        asserted nothing, so replacing the error print with a bare `pass`
        survived it -- the operator would get zero feedback and the suite
        would stay green."""
        from unittest.mock import MagicMock

        import main

        client = MagicMock()
        main.cmd_cancel(client, "../../positions")

        out = capsys.readouterr().out
        assert "Invalid order_id" in out
        assert "Cancelled:" not in out
        client.cancel_order.assert_not_called()

    def test_cmd_cancel_does_not_swallow_a_non_format_valueerror(self):
        """Opus review (batch-58, M1): cancel_order raises ValueError for
        three reasons that are NOT a malformed id -- _check_error_body's
        200-with-error-body convention, a requests JSONDecodeError (a
        ValueError subclass) on an HTML gateway body, and _sign_headers'
        missing-credentials check. Catching ValueError around the network
        call reported "Invalid order_id: Expecting value: line 1 column 1"
        for a 502 on the operator's emergency-cancel path, and returned
        cleanly so a wrapper script saw success. Those must stay loud."""
        from unittest.mock import MagicMock

        import main

        client = MagicMock()
        client.cancel_order.side_effect = ValueError(
            "Kalshi API returned 200 with error body"
        )
        with pytest.raises(ValueError, match="200 with error body"):
            main.cmd_cancel(client, "5f3a8b2c-1d4e-4f6a-9b8c-0e1f2a3b4c5d")


class TestBatchedClientOrderIdLookup:
    """Batch-58 item 6 (backlog L24499): one walk of each status bucket per
    recovery pass instead of three walks per unknown row."""

    def _make_client(self):
        from unittest.mock import patch

        with patch("kalshi_client.KalshiClient.__init__", return_value=None):
            import kalshi_client

            return kalshi_client.KalshiClient.__new__(kalshi_client.KalshiClient)

    def test_one_walk_of_each_bucket_regardless_of_id_count(self):
        """The whole point of the hoist: 10 ids must still cost exactly 3
        fetches (resting + executed + canceled), not 30."""
        from unittest.mock import MagicMock

        client = self._make_client()
        client.get_open_orders = MagicMock(return_value=[])
        client._get_orders_by_status = MagicMock(return_value=[])

        matches, uncertain = client._find_orders_by_client_ids(
            {f"coid_{i}" for i in range(10)}
        )

        assert matches == {}
        assert uncertain is False
        assert client.get_open_orders.call_count == 1
        assert client._get_orders_by_status.call_count == 2

    def test_matches_each_id_to_its_own_order(self):
        from unittest.mock import MagicMock

        client = self._make_client()
        client.get_open_orders = MagicMock(
            return_value=[{"client_order_id": "coid_a", "status": "resting"}]
        )

        def _by_status(status):
            if status == "executed":
                return [{"client_order_id": "coid_b", "status": "executed"}]
            return []

        client._get_orders_by_status = MagicMock(side_effect=_by_status)

        matches, uncertain = client._find_orders_by_client_ids(
            {"coid_a", "coid_b", "coid_missing"}
        )

        assert matches["coid_a"]["status"] == "resting"
        assert matches["coid_b"]["status"] == "executed"
        assert "coid_missing" not in matches
        assert uncertain is False

    def test_canceled_with_zero_fill_is_not_a_match(self):
        """Same judgement the single-id form applies: a canceled order with
        zero fill genuinely never landed, so the caller may safely retry. A
        canceled order with a partial fill DID land."""
        from unittest.mock import MagicMock

        client = self._make_client()
        client.get_open_orders = MagicMock(return_value=[])

        def _by_status(status):
            if status == "canceled":
                return [
                    {"client_order_id": "coid_zero", "fill_count_fp": "0.00"},
                    {"client_order_id": "coid_part", "fill_count_fp": "3.00"},
                    {"client_order_id": "coid_bad", "fill_count_fp": "not-a-number"},
                ]
            return []

        client._get_orders_by_status = MagicMock(side_effect=_by_status)

        matches, _ = client._find_orders_by_client_ids(
            {"coid_zero", "coid_part", "coid_bad"}
        )

        assert "coid_zero" not in matches
        assert "coid_part" in matches
        # Unparseable fill count -> treated as LANDED, so the caller can't
        # retry into a duplicate real order.
        assert "coid_bad" in matches

    def test_a_failed_walk_marks_the_whole_pass_uncertain(self):
        """uncertain=True is what stops a caller confirming "never landed"
        and unblocking a retry. A failed bucket could be hiding any id's
        real match, so it is pass-level, not per-id."""
        from unittest.mock import MagicMock

        client = self._make_client()
        client.get_open_orders = MagicMock(side_effect=ConnectionError("boom"))
        client._get_orders_by_status = MagicMock(return_value=[])

        matches, uncertain = client._find_orders_by_client_ids({"coid_a"})
        assert matches == {}
        assert uncertain is True

        # Positive control: with the same buckets all healthy, the identical
        # call reports uncertain=False.
        client.get_open_orders = MagicMock(return_value=[])
        _, uncertain_ok = client._find_orders_by_client_ids({"coid_a"})
        assert uncertain_ok is False

    def test_resting_takes_precedence_over_later_buckets(self):
        """Mirrors the single-id form's resting -> executed -> canceled
        precedence, so the two cannot disagree about the same id."""
        from unittest.mock import MagicMock

        client = self._make_client()
        client.get_open_orders = MagicMock(
            return_value=[{"client_order_id": "coid_a", "status": "resting"}]
        )
        client._get_orders_by_status = MagicMock(
            return_value=[{"client_order_id": "coid_a", "status": "executed"}]
        )

        matches, _ = client._find_orders_by_client_ids({"coid_a"})
        assert matches["coid_a"]["status"] == "resting"

    def test_empty_id_set_makes_no_api_calls_at_all(self):
        from unittest.mock import MagicMock

        client = self._make_client()
        client.get_open_orders = MagicMock(return_value=[])
        client._get_orders_by_status = MagicMock(return_value=[])

        matches, uncertain = client._find_orders_by_client_ids(set())

        assert matches == {}
        assert uncertain is False
        client.get_open_orders.assert_not_called()
        client._get_orders_by_status.assert_not_called()

    def test_single_id_form_still_short_circuits_on_the_first_bucket(self):
        """_find_order_by_client_id is deliberately NOT reimplemented on top
        of the batched form: its hot caller is place_order's exception
        handler on a live-order error path, and routing it through the batch
        version would turn one paginated fetch into three."""
        from unittest.mock import MagicMock

        client = self._make_client()
        client.get_open_orders = MagicMock(
            return_value=[{"client_order_id": "coid_a", "status": "resting"}]
        )
        client._get_orders_by_status = MagicMock(return_value=[])

        found, uncertain = client._find_order_by_client_id("coid_a")

        assert found["status"] == "resting"
        assert uncertain is False
        client._get_orders_by_status.assert_not_called()


# ── batch-77: breaker scoping, 4xx handling, clock skew ──────────────────────


def _cb_resp(status, body=None, headers=None):
    """A requests.Response double with the attributes _request_with_retry
    actually reads."""
    import requests

    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    resp.headers = headers or {}
    if body is None:
        resp.json.side_effect = ValueError("no json")
    else:
        resp.json.return_value = body
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(str(status))
    else:
        resp.raise_for_status.return_value = None
    return resp


@pytest.fixture
def fresh_breakers(monkeypatch):
    """Replace all three module breakers with non-persisting instances.

    persist=False matters for the READ half specifically: these singletons are
    constructed at import and _load_state() the real main-clone
    data/.cb_state.json at that moment, before any fixture runs, so without
    fresh instances a test inherits whatever a previous production run left
    open. The write half is already covered elsewhere -- conftest's
    isolate_circuit_breaker_state monkeypatches circuit_breaker._CB_STATE_PATH
    and _save_state reads that global at call time, so saves land in tmp_path
    either way.
    """
    import kalshi_client as kc
    from circuit_breaker import CircuitBreaker

    made = {}
    for attr, name in (
        ("_kalshi_cb_read", "test_public_read"),
        ("_kalshi_cb_private_read", "test_private_read"),
        ("_kalshi_cb_write", "test_write"),
    ):
        cb = CircuitBreaker(
            name=name, failure_threshold=5, recovery_timeout=60, persist=False
        )
        monkeypatch.setattr(kc, attr, cb)
        made[attr] = cb
    return made


_PUB_URL = "https://api.elections.kalshi.com/trade-api/v2/markets/KXHIGHNY-26AUG26-T87"
_PRIV_URL = "https://api.elections.kalshi.com/trade-api/v2/portfolio/balance"


class TestBreakerSelection:
    """batch-77: /portfolio/* must not share a breaker with market data."""

    def test_public_market_path_selects_public_read_breaker(self, fresh_breakers):
        import kalshi_client as kc

        assert kc._select_breaker("GET", _PUB_URL) is fresh_breakers["_kalshi_cb_read"]

    def test_portfolio_path_selects_private_read_breaker(self, fresh_breakers):
        import kalshi_client as kc

        assert (
            kc._select_breaker("GET", _PRIV_URL)
            is fresh_breakers["_kalshi_cb_private_read"]
        )

    def test_write_method_selects_write_breaker_even_on_a_public_path(
        self, fresh_breakers
    ):
        """The method check runs first, so a write to a non-/portfolio/ path
        still gets the write breaker -- writes must never share with reads
        regardless of path."""
        import kalshi_client as kc

        assert (
            kc._select_breaker("POST", _PUB_URL) is fresh_breakers["_kalshi_cb_write"]
        )

    def test_demo_host_is_also_guarded(self, fresh_breakers):
        import kalshi_client as kc

        assert (
            kc._select_breaker("GET", "https://demo-api.kalshi.co/trade-api/v2/markets")
            is fresh_breakers["_kalshi_cb_read"]
        )

    def test_non_kalshi_host_is_unguarded(self, fresh_breakers):
        """weather_markets' Pirate Weather fetch imports this helper and has
        its own _pirate_cb; routing it through a Kalshi breaker
        cross-contaminated both directions."""
        import kalshi_client as kc

        assert (
            kc._select_breaker(
                "GET", "https://api.pirateweather.net/forecast/KEY/40.7,-74.0"
            )
            is None
        )

    def test_kalshi_hosts_derived_from_the_base_urls(self):
        """Asserts the DERIVATION, not a copy of its output -- re-listing the
        two literals here would reintroduce exactly the hardcoded second copy
        that _kalshi_hosts() exists to avoid, and would still pass if the
        function were replaced by a frozen literal that later went stale."""
        from urllib.parse import urlparse

        import kalshi_client as kc

        assert kc._kalshi_hosts() == {
            urlparse(kc.PROD_BASE).hostname,
            urlparse(kc.DEMO_BASE).hostname,
        }
        # _KALSHI_HOSTS is bound at import, so pin that it matches too.
        assert kc._KALSHI_HOSTS == kc._kalshi_hosts()
        assert "api.elections.kalshi.com" in kc._KALSHI_HOSTS


class TestPrivateFaultDoesNotDisableMarketData:
    """The batch-77 regression, end to end: the observed failure was six 401s
    on /portfolio/* taking out every public market-data read for a full cron
    cycle."""

    def test_open_private_breaker_still_allows_a_public_get(self, fresh_breakers):
        import kalshi_client as kc
        from circuit_breaker import CircuitOpenError

        priv = fresh_breakers["_kalshi_cb_private_read"]
        for _ in range(5):
            priv.record_failure()
        assert priv.is_open()

        # Positive control: the private breaker really is refusing calls, so
        # the public success below is not just "nothing was ever blocked".
        with patch.object(kc._SESSION, "request") as blocked:
            with pytest.raises(CircuitOpenError):
                kc._request_with_retry("GET", _PRIV_URL, check_error_body=True)
        blocked.assert_not_called()

        with patch.object(
            kc._SESSION, "request", return_value=_cb_resp(200, {"market": {}})
        ) as allowed:
            resp = kc._request_with_retry("GET", _PUB_URL, check_error_body=True)
        assert resp.status_code == 200
        allowed.assert_called_once()
        assert not fresh_breakers["_kalshi_cb_read"].is_open()

    def test_get_market_survives_an_open_private_breaker(self, fresh_breakers):
        """The exact call paper.check_paper_position_exits makes per open
        position. Pre-fix this raised CircuitOpenError and every position went
        unpriced.

        Opens whatever breaker the selector ACTUALLY routes /portfolio/ to,
        rather than _kalshi_cb_private_read by name. Naming it directly made
        the test vacuous under the pre-fix single-breaker arrangement: a
        _select_breaker that ignores the path leaves the private instance
        unused, so opening it blocks nothing and get_market would have
        'survived' for the wrong reason."""
        import kalshi_client as kc

        priv = kc._select_breaker("GET", _PRIV_URL)
        for _ in range(5):
            priv.record_failure()
        assert priv.is_open()

        client = kc.KalshiClient.__new__(kc.KalshiClient)
        client.base_url = kc.PROD_BASE
        client.key_id = "k"
        client._private_key = object()
        client._sign_headers = lambda *a, **kw: {}

        market = {"ticker": "KXHIGHNY-26AUG26-T87", "yes_bid": 40, "yes_ask": 42}
        with patch.object(
            kc._SESSION, "request", return_value=_cb_resp(200, {"market": market})
        ):
            got = client.get_market("KXHIGHNY-26AUG26-T87")
        assert got["yes_bid"] == 40


class TestFourXXDoesNotTouchTheBreaker:
    """batch-77: a 401 body carries a top-level "error" key, which is the only
    path by which the observed 401s reached record_failure() -- the
    status-code branch already exempted 4xx."""

    # The exact body Kalshi returns, captured live 2026-08-26 by sending
    # GET /trade-api/v2/portfolio/balance with a deliberately stale
    # KALSHI-ACCESS-TIMESTAMP (no real credentials involved):
    #   HTTP 401
    #   {"error":{"code":"header_timestamp_expired",
    #             "message":"header timestamp expired"}}
    # The top-level "error" key is the whole mechanism -- not a plausible
    # shape invented for the test.
    _KALSHI_401 = {
        "error": {
            "code": "header_timestamp_expired",
            "message": "header timestamp expired",
        }
    }

    def test_401s_on_portfolio_never_touch_the_public_breaker(self, fresh_breakers):
        """THE batch-77 regression. Six 401s from a clock skew opened the one
        shared read breaker and took every market-data read down with it,
        blinding stop-loss on all 8 open positions.

        The 401s DO trip the private breaker (a deliberate later decision:
        backing off cannot fix a credential fault, but it stops
        _resolve_live_balance emitting ~60 futile calls per cycle). What must
        never happen again is that reaching the PUBLIC breaker."""
        import kalshi_client as kc
        from circuit_breaker import CircuitOpenError

        priv = fresh_breakers["_kalshi_cb_private_read"]
        pub = fresh_breakers["_kalshi_cb_read"]
        with patch.object(
            kc._SESSION, "request", return_value=_cb_resp(401, self._KALSHI_401)
        ) as sess:
            for _ in range(5):
                with pytest.raises(requests.HTTPError):
                    kc._request_with_retry("GET", _PRIV_URL, check_error_body=True)
            # The 6th is SHED rather than sent -- exactly the load-shedding
            # this rule exists for. On the real 2026-08-26 run the same six
            # calls all went out and took market data down with them.
            with pytest.raises(CircuitOpenError):
                kc._request_with_retry("GET", _PRIV_URL, check_error_body=True)
        assert sess.call_count == 5

        # Positive control: the calls really happened and really were auth
        # failures -- so the public breaker's zero is not a vacuous "nothing
        # ran".
        assert priv.is_open()
        assert pub.failure_count == 0
        assert not pub.is_open()

        # And the consequence that matters: a market-data read still works.
        with patch.object(
            kc._SESSION, "request", return_value=_cb_resp(200, {"market": {}})
        ) as allowed:
            assert (
                kc._request_with_retry(
                    "GET", _PUB_URL, check_error_body=True
                ).status_code
                == 200
            )
        allowed.assert_called_once()

    def test_a_401_on_a_market_path_does_not_trip_the_public_breaker(
        self, fresh_breakers
    ):
        """The auth-failure rule is scoped to the private breaker by the
        BREAKER, not by the status code. A 401 arriving on a market-data path
        is still just a client error there."""
        import kalshi_client as kc

        pub = fresh_breakers["_kalshi_cb_read"]
        with patch.object(
            kc._SESSION, "request", return_value=_cb_resp(401, self._KALSHI_401)
        ):
            for _ in range(6):
                with pytest.raises(requests.HTTPError):
                    kc._request_with_retry("GET", _PUB_URL, check_error_body=True)
        assert pub.failure_count == 0
        assert not pub.is_open()

    def test_a_2xx_error_body_still_trips(self, fresh_breakers):
        """Positive control for the test above: check_error_body is still
        live, just scoped to 2xx. Without this, deleting the whole
        check_error_body block would leave the previous test green."""
        import kalshi_client as kc

        pub = fresh_breakers["_kalshi_cb_read"]
        with patch.object(
            kc._SESSION,
            "request",
            return_value=_cb_resp(200, {"error": "internal_degraded"}),
        ):
            for _ in range(5):
                kc._request_with_retry("GET", _PUB_URL, check_error_body=True)
        assert pub.failure_count == 5
        assert pub.is_open()

    def test_5xx_still_trips(self, fresh_breakers):
        """Positive control: the breaker still opens for the condition it
        exists for."""
        import kalshi_client as kc

        pub = fresh_breakers["_kalshi_cb_read"]
        with patch.object(kc._SESSION, "request", return_value=_cb_resp(503, None)):
            for _ in range(5):
                with pytest.raises(requests.HTTPError):
                    kc._request_with_retry("GET", _PUB_URL, check_error_body=True)
        assert pub.is_open()

    def test_401_does_not_reset_an_in_progress_failure_streak(self, fresh_breakers):
        """The second half of the fix: a 4xx records NEITHER outcome. It used
        to call record_success(), which zeroes failure_count -- so a real 5xx
        outage interleaved with auth errors could never reach the threshold."""
        import kalshi_client as kc

        pub = fresh_breakers["_kalshi_cb_read"]
        with patch.object(kc._SESSION, "request", return_value=_cb_resp(503, None)):
            for _ in range(4):
                with pytest.raises(requests.HTTPError):
                    kc._request_with_retry("GET", _PUB_URL, check_error_body=True)
        assert pub.failure_count == 4

        with patch.object(kc._SESSION, "request", return_value=_cb_resp(404, None)):
            with pytest.raises(requests.HTTPError):
                kc._request_with_retry("GET", _PUB_URL, check_error_body=True)
        assert pub.failure_count == 4, "a 4xx must not zero the failure count"

        with patch.object(kc._SESSION, "request", return_value=_cb_resp(503, None)):
            with pytest.raises(requests.HTTPError):
                kc._request_with_retry("GET", _PUB_URL, check_error_body=True)
        assert pub.is_open()

    def test_a_real_200_still_resets_the_streak(self, fresh_breakers):
        """Positive control for the test above -- record_success() must still
        fire on a genuine success, or that assertion proves only that
        record_success() was deleted outright."""
        import kalshi_client as kc

        pub = fresh_breakers["_kalshi_cb_read"]
        with patch.object(kc._SESSION, "request", return_value=_cb_resp(503, None)):
            for _ in range(4):
                with pytest.raises(requests.HTTPError):
                    kc._request_with_retry("GET", _PUB_URL, check_error_body=True)
        assert pub.failure_count == 4

        with patch.object(
            kc._SESSION, "request", return_value=_cb_resp(200, {"market": {}})
        ):
            kc._request_with_retry("GET", _PUB_URL, check_error_body=True)
        assert pub.failure_count == 0


class TestClockSkew:
    """batch-77: the root cause of the observed cascade was a 41.4s local
    clock offset that made every signed request 401 with
    header_timestamp_expired. Measured once per process against the server's
    own Date header."""

    @staticmethod
    def _date_hdr(epoch: float) -> str:
        from email.utils import formatdate

        return formatdate(epoch, usegmt=True)

    @staticmethod
    def _reset(monkeypatch):
        """Forget that the once-per-process probe already ran.

        conftest's autouse suppress_startup_clock_skew_probe pins
        _clock_skew_checked True for every test; these are the ones that want
        the real thing. _clock_skew_attempts must be reset too or an earlier
        test in the same session could have exhausted the attempt budget.
        """
        import kalshi_client as kc

        monkeypatch.setattr(kc, "_clock_skew_checked", False)
        monkeypatch.setattr(kc, "_clock_skew_attempts", 0)

    def _probe(self, monkeypatch, server_epoch, local_epoch, extra_headers=None):
        """Drive measure_clock_skew with a pinned local clock and a Date
        header for `server_epoch`.

        The clock is injected via the `now=` parameter rather than patched
        onto kc.time -- `kc.time is time`, so patching there replaces
        time.time process-wide for the test, freezing circuit_breaker's
        burst-window logic and every log record's timestamp along with it.
        """
        import kalshi_client as kc

        headers = {"Date": self._date_hdr(server_epoch)}
        headers.update(extra_headers or {})
        resp = MagicMock()
        resp.headers = headers
        monkeypatch.setattr(kc._SKEW_SESSION, "get", lambda *a, **kw: resp)
        return kc.measure_clock_skew(kc.PROD_BASE, now=lambda: local_epoch)

    def test_synced_clock_reports_zero(self, monkeypatch):
        assert self._probe(monkeypatch, 1_800_000_000, 1_800_000_000.4) == 0.0

    def test_local_clock_ahead_is_positive(self, monkeypatch):
        """41.4s ahead -- the observed 2026-08-26 offset. The 1s of
        whole-second Date slack is subtracted, so 41.4 measures as 40.4."""
        skew = self._probe(monkeypatch, 1_800_000_000, 1_800_000_041.4)
        assert skew == pytest.approx(40.4)

    def test_local_clock_behind_is_negative(self, monkeypatch):
        skew = self._probe(monkeypatch, 1_800_000_030, 1_800_000_000)
        assert skew == pytest.approx(-30.0)

    def test_cloudfront_age_is_added_back(self, monkeypatch):
        """Defensive, not observed: checked live 2026-08-26, a CloudFront hit
        on /exchange/status returned a REFRESHED Date and no Age header at
        all. This pins the compensation for a cache that DOES preserve an
        origin Date alongside an Age. Age=1 rather than 20 because
        /exchange/status sends Cache-Control: max-age=1 -- 20 is a value the
        real endpoint cannot produce."""
        skew = self._probe(
            monkeypatch,
            1_800_000_000,
            1_800_000_002.0,
            extra_headers={"Age": "1"},
        )
        assert skew == 0.0

    def test_missing_date_header_is_unmeasurable(self, monkeypatch):
        import kalshi_client as kc

        resp = MagicMock()
        resp.headers = {}
        monkeypatch.setattr(kc._SKEW_SESSION, "get", lambda *a, **kw: resp)
        assert kc.measure_clock_skew(kc.PROD_BASE) is None

    def test_probe_failure_returns_none_and_never_raises(self, monkeypatch):
        import kalshi_client as kc

        def _boom(*a, **kw):
            raise OSError("no network")

        monkeypatch.setattr(kc._SKEW_SESSION, "get", _boom)
        assert kc.measure_clock_skew(kc.PROD_BASE) is None

    def test_probe_bypasses_request_with_retry(self, monkeypatch):
        """A failed skew probe must not record against any circuit breaker --
        it goes straight to _SKEW_SESSION.get, never through the guarded
        _request_with_retry wrapper (which is where breaker accounting
        lives)."""
        import kalshi_client as kc

        called = []
        monkeypatch.setattr(
            kc,
            "_request_with_retry",
            lambda *a, **kw: called.append(a) or MagicMock(),
        )
        resp = MagicMock()
        resp.headers = {"Date": self._date_hdr(1_800_000_000)}
        session_calls = []

        def _get(*a, **kw):
            session_calls.append(a)
            return resp

        monkeypatch.setattr(kc._SKEW_SESSION, "get", _get)

        kc.measure_clock_skew(kc.PROD_BASE, now=lambda: 1_800_000_000.0)

        # Positive control: the probe really did issue a request.
        assert len(session_calls) == 1
        assert called == []

    def test_large_skew_logs_error_and_alerts(self, monkeypatch, caplog):
        import logging

        import kalshi_client as kc

        self._reset(monkeypatch)
        monkeypatch.setattr(kc, "measure_clock_skew", lambda *a, **kw: 41.4)
        sent = []
        monkeypatch.setitem(
            __import__("sys").modules,
            "notify",
            MagicMock(send_system_alert=lambda *a, **kw: sent.append((a, kw))),
        )

        with caplog.at_level(logging.ERROR, logger="kalshi_client"):
            assert kc.check_clock_skew_once(kc.PROD_BASE) == 41.4

        assert any("CLOCK SKEW" in r.message for r in caplog.records)
        assert len(sent) == 1
        assert sent[0][1]["cooldown_key"] == "clock_skew"

    def test_small_skew_does_not_alert(self, monkeypatch):
        """Positive control pairing: the alert above is conditional, not
        unconditional."""
        import kalshi_client as kc

        self._reset(monkeypatch)
        monkeypatch.setattr(kc, "measure_clock_skew", lambda *a, **kw: 2.0)
        sent = []
        monkeypatch.setitem(
            __import__("sys").modules,
            "notify",
            MagicMock(send_system_alert=lambda *a, **kw: sent.append((a, kw))),
        )

        assert kc.check_clock_skew_once(kc.PROD_BASE) == 2.0
        assert sent == []

    def test_runs_at_most_once_per_process(self, monkeypatch):
        import kalshi_client as kc

        self._reset(monkeypatch)
        calls = []
        monkeypatch.setattr(
            kc, "measure_clock_skew", lambda *a, **kw: calls.append(a) or 1.0
        )

        assert kc.check_clock_skew_once(kc.PROD_BASE) == 1.0
        assert kc.check_clock_skew_once(kc.PROD_BASE) is None
        assert len(calls) == 1

    def test_never_raises_when_measurement_blows_up(self, monkeypatch):
        """A client must stay constructible with no network."""
        import kalshi_client as kc

        self._reset(monkeypatch)

        def _boom(*a, **kw):
            raise OSError("no network")

        monkeypatch.setattr(kc._SKEW_SESSION, "get", _boom)
        assert kc.check_clock_skew_once(kc.PROD_BASE) is None

    def test_keyless_client_never_probes(self, monkeypatch, tmp_path):
        """__init__ gates the probe on a loaded private key: a client that
        cannot sign has no timestamp to be rejected."""
        import kalshi_client as kc

        calls = []
        monkeypatch.setattr(
            kc, "check_clock_skew_once", lambda *a, **kw: calls.append(a)
        )
        monkeypatch.setattr(kc, "_check_env_file_permissions", lambda: None)

        kc.KalshiClient(key_id=None, private_key_path=None, env="demo")
        assert calls == []

    def test_client_with_a_key_probes_once(self, monkeypatch, tmp_path):
        """Positive control for the test above."""
        import kalshi_client as kc

        key_file = tmp_path / "key.pem"
        key_file.write_bytes(b"unused-mocked-out")
        calls = []
        monkeypatch.setattr(
            kc, "check_clock_skew_once", lambda *a, **kw: calls.append(a)
        )
        monkeypatch.setattr(kc, "_check_env_file_permissions", lambda: None)
        monkeypatch.setattr(kc, "_check_key_permissions", lambda p: None)
        monkeypatch.setattr(
            kc.serialization, "load_pem_private_key", lambda *a, **kw: object()
        )

        kc.KalshiClient(key_id="k", private_key_path=str(key_file), env="demo")
        assert calls == [(kc.DEMO_BASE,)]


class TestFourXXDoesNotStrandTheProbe:
    """Round-2 review, H-1. `_half_open` is cleared ONLY inside
    record_failure()/record_success()/record_reachable(), and is_open()'s
    `if self._half_open: return True` has no other exit. So the first draft of
    batch-77's "a 4xx records nothing" rule left a 4xx probe stranding the
    circuit OPEN FOREVER -- the same market-data blackout this batch exists to
    remove, reached through a different door. Invisible in the one-shot `cron`
    process (nothing persists `_half_open`) and permanent in `main.py loop`
    and web_app.py.
    """

    @staticmethod
    def _open_then_half_open(cb):
        """Trip `cb`, then zero its recovery window so the next is_open()
        designates a probe.

        Zeroes the timeout rather than waiting for it -- a real 60s sleep in a
        unit test is not worth it. Note the caller must NOT then assert on
        is_open() to "check": is_open() is itself the mutator that designates
        the probe caller, so reading it here consumes the probe and the
        request under test would get CircuitOpenError instead."""
        for _ in range(5):
            cb.record_failure()
        assert cb.is_open()
        cb.recovery_timeout = 0
        cb._current_timeout = 0

    def test_a_4xx_probe_does_not_wedge_the_circuit(self, fresh_breakers):
        import requests

        import kalshi_client as kc

        pub = fresh_breakers["_kalshi_cb_read"]
        self._open_then_half_open(pub)

        # The probe gets a 404 -- routine here, e.g. a settled ticker.
        with patch.object(kc._SESSION, "request", return_value=_cb_resp(404, None)):
            with pytest.raises(requests.HTTPError):
                kc._request_with_retry("GET", _PUB_URL, check_error_body=True)

        # A 4xx answered at the application layer, so the source is reachable
        # and the circuit must be usable again.
        with patch.object(
            kc._SESSION, "request", return_value=_cb_resp(200, {"market": {}})
        ) as after:
            resp = kc._request_with_retry("GET", _PUB_URL, check_error_body=True)
        assert resp.status_code == 200
        # Positive control: the request actually went out. Without it, a
        # CircuitOpenError raised before _SESSION.request would have to be
        # caught to fail this test, and a wedged circuit would look like a
        # missing assertion rather than a failure.
        after.assert_called_once()
        assert not pub.is_open()

    def test_a_5xx_probe_still_reopens(self, fresh_breakers):
        """Positive control: record_reachable must not have turned every
        failed probe into a recovery."""
        import requests

        import kalshi_client as kc
        from circuit_breaker import CircuitOpenError

        pub = fresh_breakers["_kalshi_cb_read"]
        self._open_then_half_open(pub)

        with patch.object(kc._SESSION, "request", return_value=_cb_resp(503, None)):
            with pytest.raises(requests.HTTPError):
                kc._request_with_retry("GET", _PUB_URL, check_error_body=True)

        # record_failure() re-armed the circuit using _current_timeout, which
        # the setup above zeroed to force the probe. Restore a real window so
        # the next call is a normal blocked caller rather than another probe.
        pub._current_timeout = 60
        assert pub.is_open()
        with patch.object(kc._SESSION, "request") as blocked:
            with pytest.raises(CircuitOpenError):
                kc._request_with_retry("GET", _PUB_URL, check_error_body=True)
        blocked.assert_not_called()

    def test_a_4xx_on_a_closed_circuit_still_records_nothing(self, fresh_breakers):
        """record_reachable's other half: while CLOSED it must be a no-op, or
        it would re-introduce the streak-zeroing this batch removed."""
        import requests

        import kalshi_client as kc

        pub = fresh_breakers["_kalshi_cb_read"]
        with patch.object(kc._SESSION, "request", return_value=_cb_resp(503, None)):
            for _ in range(4):
                with pytest.raises(requests.HTTPError):
                    kc._request_with_retry("GET", _PUB_URL, check_error_body=True)
        assert pub.failure_count == 4
        assert not pub.is_open()

        with patch.object(kc._SESSION, "request", return_value=_cb_resp(403, None)):
            with pytest.raises(requests.HTTPError):
                kc._request_with_retry("GET", _PUB_URL, check_error_body=True)
        assert pub.failure_count == 4


class TestBreakerIsolationIsSymmetric:
    """Round-2 review, L-6: only private -> public was pinned. The guarantee
    is meant to hold both ways."""

    def test_open_public_breaker_still_allows_a_private_get(self, fresh_breakers):
        import kalshi_client as kc
        from circuit_breaker import CircuitOpenError

        pub = kc._select_breaker("GET", _PUB_URL)
        for _ in range(5):
            pub.record_failure()
        assert pub.is_open()

        # Positive control: the public breaker really is refusing calls.
        with patch.object(kc._SESSION, "request") as blocked:
            with pytest.raises(CircuitOpenError):
                kc._request_with_retry("GET", _PUB_URL, check_error_body=True)
        blocked.assert_not_called()

        with patch.object(
            kc._SESSION, "request", return_value=_cb_resp(200, {"balance": 1000})
        ) as allowed:
            resp = kc._request_with_retry("GET", _PRIV_URL, check_error_body=True)
        assert resp.status_code == 200
        allowed.assert_called_once()


class TestRateLimitTripsTheBreaker:
    """Round-2 review, M-2. 429 is the one 4xx that is a real infrastructure
    signal. Getting it wrong failed BOTH ways: 50 consecutive 429s never
    tripped the breaker, and one 429 landing on the HALF-OPEN probe CLOSED a
    breaker a genuine 5xx outage had opened."""

    def test_persistent_429s_trip_the_breaker(self, fresh_breakers):
        import kalshi_client as kc

        pub = fresh_breakers["_kalshi_cb_read"]
        with patch.object(kc._SESSION, "request", return_value=_cb_resp(429, None)):
            for _ in range(5):
                with pytest.raises(requests.HTTPError):
                    kc._request_with_retry("GET", _PUB_URL, check_error_body=True)
        assert pub.failure_count == 5
        assert pub.is_open()

    def test_a_429_probe_does_not_close_an_open_circuit(self, fresh_breakers):
        """The dangerous half: a recovering bot being rate-limited must not
        read the throttle as 'the source is back'."""
        import kalshi_client as kc
        from circuit_breaker import CircuitOpenError

        pub = fresh_breakers["_kalshi_cb_read"]
        for _ in range(5):
            pub.record_failure()
        pub.recovery_timeout = 0
        pub._current_timeout = 0
        # Deliberately NOT calling is_open() to "check" first: is_open() is the
        # mutator that designates the probe caller, so asserting on it here
        # would consume the probe and the request below would just get
        # CircuitOpenError. The request under test must BE the probe.

        with patch.object(kc._SESSION, "request", return_value=_cb_resp(429, None)):
            with pytest.raises(requests.HTTPError):
                kc._request_with_retry("GET", _PUB_URL, check_error_body=True)

        pub._current_timeout = 60
        assert pub.is_open()
        with patch.object(kc._SESSION, "request") as blocked:
            with pytest.raises(CircuitOpenError):
                kc._request_with_retry("GET", _PUB_URL, check_error_body=True)
        blocked.assert_not_called()

    def test_a_404_probe_still_closes(self, fresh_breakers):
        """Discriminating control: the 429 and auth-failure rules must be
        specific, not have turned every 4xx back into a failure.
        record_reachable's whole purpose is that an ordinary 4xx probe -- a
        404 on a settled ticker is routine here -- still releases the
        circuit."""
        import kalshi_client as kc

        pub = fresh_breakers["_kalshi_cb_read"]
        for _ in range(5):
            pub.record_failure()
        pub.recovery_timeout = 0
        pub._current_timeout = 0

        with patch.object(kc._SESSION, "request", return_value=_cb_resp(404, None)):
            with pytest.raises(requests.HTTPError):
                kc._request_with_retry("GET", _PUB_URL, check_error_body=True)

        pub._current_timeout = 60
        assert not pub.is_open()

    def test_persistent_401s_trip_the_private_breaker(self, fresh_breakers):
        """The deliberate later decision, pinned on its own: five consecutive
        auth failures shed load on /portfolio/*. Without this the exposure is
        ~60 futile 401s per cycle, because
        order_executor._resolve_live_balance caches only successes."""
        import kalshi_client as kc

        priv = fresh_breakers["_kalshi_cb_private_read"]
        with patch.object(kc._SESSION, "request", return_value=_cb_resp(403, None)):
            for _ in range(5):
                with pytest.raises(requests.HTTPError):
                    kc._request_with_retry("GET", _PRIV_URL, check_error_body=True)
        assert priv.failure_count == 5
        assert priv.is_open()


class TestBreakerRoutingEdgeCases:
    """Round-2 review, M-5: three mutations survived because the stated safety
    properties had no regression pin -- the trailing slash, the use of
    parsed.path rather than the raw URL, and the host-before-method ordering.
    """

    def test_a_city_literally_named_portfolio_stays_on_the_public_breaker(
        self, fresh_breakers
    ):
        """_PRIVATE_PATH_MARKER's trailing slash IS the safety argument.
        get_live_weather_index validates `city` with [a-zA-Z]{1,32}, which --
        unlike the uppercase-only _TICKER_RE -- can spell "portfolio". It is
        safe only because the segment is terminal, so there is no trailing
        slash to match. Dropping the slash from the marker misroutes it."""
        import kalshi_client as kc

        url = kc.PROD_BASE + "/live_data/weather/portfolio"
        assert kc._select_breaker("GET", url) is fresh_breakers["_kalshi_cb_read"]

    def test_portfolio_in_a_query_string_does_not_misroute(self, fresh_breakers):
        """_select_breaker reads parsed.path, not the raw URL. requests passes
        params separately so a query cannot normally reach it, but matching
        against the whole URL would make that a latent misroute."""
        import kalshi_client as kc

        url = kc.PROD_BASE + "/markets?series_ticker=/portfolio/x"
        assert kc._select_breaker("GET", url) is fresh_breakers["_kalshi_cb_read"]

    def test_a_post_to_a_non_kalshi_host_is_also_unguarded(self, fresh_breakers):
        """The docstring claims the host check comes first so no non-Kalshi
        request is guarded 'on any method'. Only the GET case was pinned, so
        moving the host check after the method check survived."""
        import kalshi_client as kc

        assert (
            kc._select_breaker("POST", "https://api.pirateweather.net/forecast/K/1,2")
            is None
        )

    def test_a_portfolio_path_on_a_non_kalshi_host_is_unguarded(self, fresh_breakers):
        import kalshi_client as kc

        assert (
            kc._select_breaker("GET", "https://evil.example/portfolio/balance") is None
        )


class TestClockSkewStateMachine:
    """Round-2 review, M-4/L-1/L-2: the retry bound, the
    do-not-consume-the-flag-on-failure rule, the no-retry session, the 5s
    timeout and the naive-datetime guard were all free parameters."""

    def test_a_failed_probe_does_not_consume_the_once_flag(self, monkeypatch):
        import kalshi_client as kc

        TestClockSkew._reset(monkeypatch)
        results = [None, 2.0]
        calls = []

        def _measure(*a, **kw):
            calls.append(a)
            return results.pop(0)

        monkeypatch.setattr(kc, "measure_clock_skew", _measure)

        assert kc.check_clock_skew_once(kc.PROD_BASE) is None  # unmeasurable
        # The retry is the whole point: a cold start after a long shutdown is
        # both when skew is largest and when the NIC may not be up yet.
        assert kc.check_clock_skew_once(kc.PROD_BASE) == 2.0
        assert len(calls) == 2
        # Now it IS consumed.
        assert kc.check_clock_skew_once(kc.PROD_BASE) is None
        assert len(calls) == 2

    def test_repeated_failures_stop_at_the_attempt_cap(self, monkeypatch):
        import kalshi_client as kc

        TestClockSkew._reset(monkeypatch)
        calls = []
        monkeypatch.setattr(
            kc, "measure_clock_skew", lambda *a, **kw: calls.append(a) or None
        )

        for _ in range(10):
            assert kc.check_clock_skew_once(kc.PROD_BASE) is None
        assert len(calls) == kc._CLOCK_SKEW_MAX_ATTEMPTS

    def test_skew_session_has_no_retry_budget(self):
        """_SESSION carries Retry(total=3, backoff_factor=1.0); inheriting it
        put up to ~46s of blocking inside KalshiClient.__init__."""
        import kalshi_client as kc

        retries = kc._SKEW_SESSION.get_adapter("https://x").max_retries
        assert retries.total == 0
        assert retries.connect == 0
        assert retries.read == 0
        # Positive control: the main session deliberately still HAS one, so
        # this asserts a difference rather than a global absence.
        assert kc._SESSION.get_adapter("https://x").max_retries.total > 0

    def test_probe_passes_the_short_timeout(self, monkeypatch):
        import kalshi_client as kc

        seen = {}

        def _get(url, **kw):
            seen.update(kw)
            resp = MagicMock()
            resp.headers = {"Date": TestClockSkew._date_hdr(1_800_000_000)}
            return resp

        monkeypatch.setattr(kc._SKEW_SESSION, "get", _get)
        kc.measure_clock_skew(kc.PROD_BASE, now=lambda: 1_800_000_000.0)
        assert seen["timeout"] == kc._CLOCK_SKEW_TIMEOUT
        assert kc._CLOCK_SKEW_TIMEOUT <= 10.0

    def test_an_obsolete_minus_zero_zone_is_read_as_utc(self, monkeypatch):
        """parsedate_to_datetime returns a NAIVE datetime for RFC 5322's
        obsolete "-0000", and .timestamp() would then read it as LOCAL time --
        a phantom skew of the machine's whole UTC offset, firing a false
        operator alert. formatdate(usegmt=True) always emits "GMT", so only a
        literal header reaches this branch."""
        import kalshi_client as kc

        resp = MagicMock()
        resp.headers = {"Date": "Tue, 26 Aug 2026 00:28:00 -0000"}
        monkeypatch.setattr(kc._SKEW_SESSION, "get", lambda *a, **kw: resp)

        import calendar
        import time as _t

        epoch = calendar.timegm(_t.strptime("2026-08-26 00:28:00", "%Y-%m-%d %H:%M:%S"))
        skew = kc.measure_clock_skew(kc.PROD_BASE, now=lambda: epoch + 0.5)
        assert skew == 0.0

    def test_an_absurd_age_header_is_ignored(self, monkeypatch):
        """Round-2 L-6: Age was added back unbounded. An intermediary that
        serves a REFRESHED Date *and* an Age double-counts, so Age=3600 would
        report the clock an hour behind and alert on it. /exchange/status
        sends Cache-Control: max-age=1, so any large Age is not a real
        staleness signal."""
        import kalshi_client as kc

        resp = MagicMock()
        resp.headers = {
            "Date": TestClockSkew._date_hdr(1_800_000_000),
            "Age": "3600",
        }
        monkeypatch.setattr(kc._SKEW_SESSION, "get", lambda *a, **kw: resp)
        skew = kc.measure_clock_skew(kc.PROD_BASE, now=lambda: 1_800_000_000.5)
        assert skew == 0.0


class TestRecordReachablePersists:
    """Round-2 review, L-3: dropping record_reachable's _save_state() left the
    tests green, but a 4xx-probe-closed circuit would then persist opened_at
    non-null and a restarted process would reload it as OPEN -- the same
    blackout, one restart later."""

    def test_closing_via_a_probe_is_persisted(self, tmp_path, monkeypatch):
        import json

        import circuit_breaker as cbmod
        from circuit_breaker import CircuitBreaker

        state_path = tmp_path / ".cb_state.json"
        monkeypatch.setattr(cbmod, "_CB_STATE_PATH", state_path)

        cb = CircuitBreaker(
            name="persist_probe", failure_threshold=5, recovery_timeout=0
        )
        for _ in range(5):
            cb.record_failure()
        # Positive control: the OPEN state really did reach disk, so the
        # cleared state below is a second write and not a missing file.
        assert json.loads(state_path.read_text())["persist_probe"]["opened_at"]

        assert not cb.is_open()  # designates this caller as the probe
        cb.record_reachable()

        saved = json.loads(state_path.read_text())["persist_probe"]
        assert saved["opened_at"] is None
        assert saved["failure_count"] == 0
