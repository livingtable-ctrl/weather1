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

        return KalshiClient.__new__(KalshiClient)

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
        """If _post raises but the order exists on exchange, return it without re-raising."""
        client = self._make_client()

        existing_order = {"order_id": "ord_landed", "client_order_id": "abc123"}

        def fake_post(path, body):
            raise ConnectionError("timeout")

        client._post = fake_post
        client._find_order_by_client_id = MagicMock(return_value=existing_order)

        result = client.place_order("KXTEST", "yes", "buy", 1, 0.55, cycle="12z")

        assert result == existing_order
        client._find_order_by_client_id.assert_called_once()

    def test_reraises_when_post_fails_and_order_not_found(self):
        """If _post raises and no matching order exists, the exception must propagate."""
        import pytest

        client = self._make_client()

        def fake_post(path, body):
            raise ConnectionError("timeout")

        client._post = fake_post
        client._find_order_by_client_id = MagicMock(return_value=None)

        with pytest.raises(ConnectionError):
            client.place_order("KXTEST", "yes", "buy", 1, 0.55, cycle="12z")

    def test_find_order_by_client_id_returns_none_on_api_error(self):
        """_find_order_by_client_id must swallow exceptions and return None."""
        client = self._make_client()

        def bad_get(path, params=None, auth=False):
            raise RuntimeError("api down")

        client._get = bad_get

        result = client._find_order_by_client_id("some-id")
        assert result is None
