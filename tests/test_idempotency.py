"""P0-4: place_order idempotency key and POST retry exclusion."""

from unittest.mock import MagicMock


class TestPostRetryExcluded:
    def test_post_not_in_allowed_methods(self):
        """_build_session must not include POST in allowed_methods."""
        from kalshi_client import _build_session

        session = _build_session()
        adapter = session.get_adapter("https://")
        allowed = adapter.max_retries.allowed_methods
        assert "POST" not in allowed, (
            f"POST must not be retried; got allowed_methods={allowed}"
        )

    def test_get_still_retried(self):
        """GET must remain in allowed_methods."""
        from kalshi_client import _build_session

        session = _build_session()
        adapter = session.get_adapter("https://")
        allowed = adapter.max_retries.allowed_methods
        assert "GET" in allowed


class TestClientOrderId:
    def _make_client(self):
        from kalshi_client import KalshiClient

        client = KalshiClient.__new__(KalshiClient)
        # place_order()'s success path now fetches the full order via
        # get_order() (V2's create-order response has no status field) --
        # mock it so tests don't need a real network call.
        client.get_order = lambda order_id: {"order_id": order_id, "status": "resting"}
        return client

    def test_client_order_id_is_deterministic(self):
        """Same inputs + same cycle → same client_order_id."""
        client = self._make_client()
        captured = []

        def fake_post(path, body):
            captured.append(body.get("client_order_id"))
            return {"order_id": "ord_1"}

        client._post = fake_post

        for _ in range(2):
            client.place_order(
                ticker="KXTEST-25JUN01-T70",
                side="yes",
                action="buy",
                count=3,
                price=0.55,
                cycle="12z",
            )

        assert captured[0] == captured[1], (
            "Same inputs must produce same client_order_id"
        )
        assert len(captured[0]) == 32

    def test_client_order_id_differs_across_cycles(self):
        """Different cycle → different client_order_id."""
        client = self._make_client()
        ids = []

        def fake_post(path, body):
            ids.append(body.get("client_order_id"))
            return {"order_id": "ord_x"}

        client._post = fake_post

        client.place_order("KXTEST", "yes", "buy", 3, 0.55, cycle="06z")
        client.place_order("KXTEST", "yes", "buy", 3, 0.55, cycle="12z")

        assert ids[0] != ids[1]

    def test_client_order_id_in_request_body(self):
        """client_order_id must appear in the POST body."""
        client = self._make_client()
        sent_body = {}

        def fake_post(path, body):
            sent_body.update(body)
            return {"order_id": "ord_2"}

        client._post = fake_post
        client.place_order("KXTEST", "no", "buy", 2, 0.40, cycle="18z")

        assert "client_order_id" in sent_body
        assert len(sent_body["client_order_id"]) == 32

    def test_no_cycle_uses_random_id(self):
        """Omitting cycle produces a random (non-deterministic) client_order_id."""
        client = self._make_client()
        ids = []

        def fake_post(path, body):
            ids.append(body.get("client_order_id"))
            return {"order_id": "ord_3"}

        client._post = fake_post
        client.place_order("KXTEST", "yes", "buy", 1, 0.60)
        client.place_order("KXTEST", "yes", "buy", 1, 0.60)

        assert ids[0] != ids[1], "Without cycle, each call must use a unique random id"


class TestPostFailureDedup:
    def _make_client(self):
        from kalshi_client import KalshiClient

        return KalshiClient.__new__(KalshiClient)

    def test_returns_existing_order_when_post_fails_but_order_landed(self):
        """If _post raises but the order exists on exchange, return it without re-raising.

        Returned unwrapped, matching get_order()'s own convention -- the
        success path now also returns get_order()'s flat shape (V2's
        create-order response has no status field, so place_order() fetches
        the full order via get_order() after a successful POST), so both
        paths are consistent with no {"order": ...} wrapper either way.
        """
        client = self._make_client()

        existing_order = {"order_id": "ord_landed", "client_order_id": "abc123"}

        def fake_post(path, body):
            raise ConnectionError("timeout")

        client._post = fake_post
        client._find_order_by_client_id = MagicMock(
            return_value=(existing_order, False)
        )

        result = client.place_order("KXTEST", "yes", "buy", 1, 0.55, cycle="12z")

        assert result == existing_order
        client._find_order_by_client_id.assert_called_once()

    def test_reraises_when_post_fails_and_order_confirmed_not_found(self):
        """If _post raises and reconciliation POSITIVELY confirms no matching
        order exists (uncertain=False), the original exception must propagate."""
        import pytest

        client = self._make_client()

        def fake_post(path, body):
            raise ConnectionError("timeout")

        client._post = fake_post
        client._find_order_by_client_id = MagicMock(return_value=(None, False))

        with pytest.raises(ConnectionError):
            client.place_order("KXTEST", "yes", "buy", 1, 0.55, cycle="12z")

    def test_raises_order_status_unknown_when_post_fails_and_reconciliation_uncertain(
        self,
    ):
        """AUD-0007: if _post raises AND reconciliation itself couldn't confirm
        either way (uncertain=True), the caller must get a distinct
        OrderStatusUnknownError, NOT the original exception -- callers key off
        this type to avoid marking a possibly-real order 'failed'."""
        import pytest

        from kalshi_client import OrderStatusUnknownError

        client = self._make_client()

        def fake_post(path, body):
            raise ConnectionError("timeout")

        client._post = fake_post
        client._find_order_by_client_id = MagicMock(return_value=(None, True))

        with pytest.raises(OrderStatusUnknownError) as exc_info:
            client.place_order("KXTEST", "yes", "buy", 1, 0.55, cycle="12z")

        assert isinstance(exc_info.value.original_exc, ConnectionError)
        assert exc_info.value.client_order_id

    def test_find_order_by_client_id_returns_none_uncertain_false_on_confirmed_absence(
        self,
    ):
        """When all 3 lookup passes genuinely complete and none match,
        _find_order_by_client_id must return (None, False) -- a confirmed
        negative, not an uncertain one."""
        client = self._make_client()

        client.get_open_orders = MagicMock(return_value=[])
        client._get = MagicMock(return_value={"orders": []})

        result, uncertain = client._find_order_by_client_id("some-id")
        assert result is None
        assert uncertain is False

    def test_find_order_by_client_id_returns_uncertain_true_on_api_error(self):
        """AUD-0007: a lookup pass that itself raises must be reported as
        uncertain=True, not silently collapsed into a confirmed 'not found' --
        a real matching order could be sitting in the bucket that failed to
        check."""
        client = self._make_client()

        client.get_open_orders = MagicMock(side_effect=RuntimeError("api down"))
        client._get = MagicMock(side_effect=RuntimeError("api down"))

        result, uncertain = client._find_order_by_client_id("some-id")
        assert result is None
        assert uncertain is True

    def test_find_order_by_client_id_uncertain_true_even_if_only_one_pass_fails(self):
        """AUD-0007: the chosen (conservative) design marks uncertain=True on
        ANY single failed pass, not only when all 3 fail -- a match could be
        hiding in the one pass that didn't complete, even if the other two
        genuinely ran clean."""
        client = self._make_client()

        client.get_open_orders = MagicMock(side_effect=RuntimeError("api down"))
        client._get = MagicMock(return_value={"orders": []})

        result, uncertain = client._find_order_by_client_id("some-id")
        assert result is None
        assert uncertain is True

    def test_find_order_by_client_id_finds_match_on_second_page_of_executed_orders(
        self,
    ):
        """Opus review follow-up (AUD-0007): the 3 reconciliation lookups
        previously fetched only the first page of order history. An account
        with more than one page of executed orders could have the order
        actually being reconciled sitting on a later page -- making a
        genuinely landed order look 'confirmed not found' purely because
        enough unrelated orders piled up afterward. This is the concrete
        failure scenario: the match is on page 2."""
        client = self._make_client()
        client.get_open_orders = MagicMock(return_value=[])  # resting: no match

        page1 = {
            "orders": [{"client_order_id": "other-id", "order_id": "ord_other"}],
            "cursor": "cursor-page-2",
        }
        page2 = {
            "orders": [{"client_order_id": "target-id", "order_id": "ord_target"}],
            "cursor": "",
        }
        client._get = MagicMock(side_effect=[page1, page2])

        result, uncertain = client._find_order_by_client_id("target-id")

        assert result == {"client_order_id": "target-id", "order_id": "ord_target"}
        assert uncertain is False
        assert client._get.call_count == 2
        # Second call must have carried the cursor forward, not re-fetched page 1.
        assert client._get.call_args_list[1].kwargs["params"]["cursor"] == (
            "cursor-page-2"
        )

    def test_find_order_by_client_id_treats_malformed_response_as_uncertain(self):
        """Opus review follow-up: a 200 response missing the expected
        'orders' key (a schema change or degraded payload) must be treated
        as a failed lookup (uncertain=True), not silently iterated as an
        empty page -- an empty-page read and a malformed-response read are
        NOT the same evidence quality, and only the former is a confirmed
        negative."""
        client = self._make_client()
        client.get_open_orders = MagicMock(return_value=[])
        client._get = MagicMock(return_value={"unexpected_key": []})

        result, uncertain = client._find_order_by_client_id("some-id")
        assert result is None
        assert uncertain is True

    def test_get_orders_by_status_paginates_and_stops_on_repeated_cursor(self):
        """Regression guard mirroring get_markets/get_trades' own infinite-
        loop protection -- a buggy/malicious repeated cursor must not hang
        pagination forever."""
        client = self._make_client()
        looping_page = {
            "orders": [{"client_order_id": "x", "order_id": "1"}],
            "cursor": "same-cursor",
        }
        client._get = MagicMock(return_value=looping_page)

        result = client._get_orders_by_status("executed")

        # Stops after the repeat is detected, not looping forever.
        assert client._get.call_count == 2
        assert len(result) == 2

    def test_get_orders_by_status_stops_on_empty_page_with_nonempty_cursor(self):
        """Opus review follow-up (round 2): Kalshi's own pagination
        convention (verified live per get_trades' docstring) can return a
        non-empty cursor on what turns out to be the LAST page -- an empty
        `orders` list on the NEXT call is what actually signals done, not
        cursor absence alone. Without this guard, a page that's empty but
        still carries a cursor would loop one extra (and, in a pathological
        case, unbounded) round-trip."""
        client = self._make_client()
        client._get = MagicMock(
            side_effect=[
                {
                    "orders": [{"client_order_id": "x", "order_id": "1"}],
                    "cursor": "cursor-2",
                },
                {"orders": [], "cursor": "cursor-3"},  # empty page, cursor persists
            ]
        )

        result = client._get_orders_by_status("executed")

        assert client._get.call_count == 2
        assert len(result) == 1

    def test_get_orders_by_status_stops_at_page_cap(self):
        """Opus review follow-up (round 2): a server that keeps minting
        fresh (never-repeated) cursors must not be able to hang this
        synchronous, in-the-hot-path lookup indefinitely -- mirrors
        get_trades' own 50-page runaway-loop backstop."""
        client = self._make_client()

        call_count = {"n": 0}

        def _fake_get(path, params=None, auth=False):
            call_count["n"] += 1
            return {
                "orders": [{"client_order_id": "x", "order_id": str(call_count["n"])}],
                "cursor": f"cursor-{call_count['n']}",  # always fresh, never repeats
            }

        client._get = MagicMock(side_effect=_fake_get)

        result = client._get_orders_by_status("executed")

        assert client._get.call_count == 50
        assert len(result) == 50

    def test_get_orders_by_status_raises_on_null_orders(self):
        """Opus review follow-up (round 2): {"orders": null} must raise the
        SAME descriptive ValueError as a missing "orders" key, not a bare
        TypeError from extend(None) that the caller's `except Exception`
        would still catch, but with a confusing/undocumented failure mode."""
        client = self._make_client()
        client._get = MagicMock(return_value={"orders": None})

        import pytest

        with pytest.raises(ValueError, match="no usable 'orders' list"):
            client._get_orders_by_status("executed")

    def test_find_order_by_client_id_canceled_pass_alone_sets_uncertain(self):
        """Opus review follow-up: the canceled (3rd) pass's OWN failure must
        set uncertain=True even when the first two passes both genuinely
        succeeded -- mutation-tested by the reviewer: deleting only the
        canceled pass's `_uncertain = True` line let 163 existing tests keep
        passing, because no prior test isolated this specific pass's
        contribution to the flag."""
        client = self._make_client()
        client.get_open_orders = MagicMock(return_value=[])  # pass 1: clean, no match
        client._get = MagicMock(
            side_effect=[
                {"orders": []},  # pass 2 (executed): clean, no match
                RuntimeError("canceled lookup api down"),  # pass 3: raises
            ]
        )

        result, uncertain = client._find_order_by_client_id("some-id")
        assert result is None
        assert uncertain is True

    def test_find_order_by_client_id_canceled_match_with_fill_resolves_found(self):
        """Opus review follow-up: a canceled-with-partial-fill match (real
        capital landed before the remainder was canceled) must resolve as
        FOUND, not as an uncertain non-match -- the third pass's own nested
        fill-count branch is a distinct code path from the other two passes'
        plain client_order_id equality check."""
        client = self._make_client()
        client.get_open_orders = MagicMock(return_value=[])
        client._get = MagicMock(
            side_effect=[
                {"orders": []},  # executed: no match
                {
                    "orders": [
                        {
                            "client_order_id": "target-id",
                            "order_id": "ord_partial",
                            "fill_count_fp": "2.00",
                        }
                    ]
                },  # canceled: match, nonzero fill
            ]
        )

        result, uncertain = client._find_order_by_client_id("target-id")
        assert result is not None
        assert result["order_id"] == "ord_partial"
        assert uncertain is False

    def test_find_order_by_client_id_canceled_zero_fill_after_earlier_failure_stays_uncertain(
        self,
    ):
        """Opus review follow-up: the design's stated conservative guarantee
        -- if an EARLIER pass failed, a canceled-zero-fill (genuinely
        not-landed-looking) match in the LAST pass must still report
        uncertain=True, not silently clear the flag just because the final
        pass itself completed cleanly."""
        client = self._make_client()
        client.get_open_orders = MagicMock(side_effect=RuntimeError("resting api down"))
        client._get = MagicMock(
            side_effect=[
                {"orders": []},  # executed: no match
                {
                    "orders": [
                        {
                            "client_order_id": "target-id",
                            "order_id": "ord_zero_fill",
                            "fill_count_fp": "0.00",
                        }
                    ]
                },  # canceled: match, zero fill -> "not landed" per this pass alone
            ]
        )

        result, uncertain = client._find_order_by_client_id("target-id")
        assert result is None
        assert uncertain is True

    def test_order_status_unknown_error_preserves_exception_chain(self):
        """The original exception must be reachable via both .original_exc
        AND Python's own __cause__ (via `raise ... from exc`) -- losing the
        chain would strip context from incident logs/tracebacks."""
        client = self._make_client()

        original = ConnectionError("timeout")

        def fake_post(path, body):
            raise original

        client._post = fake_post
        client._find_order_by_client_id = MagicMock(return_value=(None, True))

        try:
            client.place_order("KXTEST", "yes", "buy", 1, 0.55, cycle="12z")
            assert False, "expected OrderStatusUnknownError"
        except Exception as exc:
            assert exc.original_exc is original
            assert exc.__cause__ is original

    def test_order_status_unknown_error_is_picklable(self):
        """Opus review follow-up: Exception's default __reduce__ would
        reconstruct via type(self)(*self.args) -- a single positional arg
        (the formatted message), which doesn't match __init__'s required
        (client_order_id, original_exc) signature and raises TypeError on
        pickle/copy. The custom __reduce__ must keep this picklable."""
        import copy
        import pickle

        from kalshi_client import OrderStatusUnknownError

        original = ConnectionError("timeout")
        exc = OrderStatusUnknownError("coid_pickle_test", original)

        restored = pickle.loads(pickle.dumps(exc))
        assert restored.client_order_id == "coid_pickle_test"
        assert isinstance(restored.original_exc, ConnectionError)

        copied = copy.copy(exc)
        assert copied.client_order_id == "coid_pickle_test"

    def test_place_order_checks_found_before_uncertain(self):
        """A match found on a pass AFTER an earlier pass failed must still
        be returned as the landed order -- 'found' takes priority over
        'uncertain', proving the ordering isn't accidentally reversed."""
        client = self._make_client()
        existing = {"order_id": "ord_landed", "client_order_id": "abc123"}

        def fake_post(path, body):
            raise ConnectionError("timeout")

        client._post = fake_post
        # Simulates: an earlier pass failed (uncertain=True) but a LATER
        # pass still found the real match.
        client._find_order_by_client_id = MagicMock(return_value=(existing, True))

        result = client.place_order("KXTEST", "yes", "buy", 1, 0.55, cycle="12z")
        assert result == existing
