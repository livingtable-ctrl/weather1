"""Phase 2 Batch L regression tests: P2-17/P2-19/P2-34/P2-43 — API/client/safety."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(__file__[: __file__.rfind("tests")]))


# ── P2-17: schema_validator price range validation ────────────────────────────


class TestValidateMarketPriceRange:
    """validate_market must reject out-of-range and inverted prices."""

    def _call(self, data, source="kalshi"):
        from schema_validator import validate_market

        return validate_market(data, source)

    def _valid(self, yes_bid=40, yes_ask=60):
        return {
            "ticker": "KXHIGHNY-T80",
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "volume": 100,
        }

    # ── presence checks (existing behaviour preserved) ──────────────────────

    def test_missing_ticker_invalid(self):
        assert self._call({"yes_bid": 40, "yes_ask": 60, "volume": 0}) is False

    def test_missing_yes_bid_invalid(self):
        assert self._call({"ticker": "T", "yes_ask": 60, "volume": 0}) is False

    def test_valid_market_passes(self):
        assert self._call(self._valid()) is True

    # ── price range validation ───────────────────────────────────────────────

    def test_bid_zero_rejected(self):
        """yes_bid=0 (0¢) is at boundary — reject."""
        assert self._call(self._valid(yes_bid=0, yes_ask=60)) is False

    def test_ask_100_cents_rejected(self):
        """yes_ask=100 (= 1.0) is at boundary — reject."""
        assert self._call(self._valid(yes_bid=40, yes_ask=100)) is False

    def test_ask_above_100_cents_rejected(self):
        """yes_ask=150 normalizes to 1.5 — out of range."""
        assert self._call(self._valid(yes_bid=40, yes_ask=150)) is False

    def test_inverted_spread_rejected(self):
        """bid >= ask must be rejected."""
        assert self._call(self._valid(yes_bid=70, yes_ask=60)) is False

    def test_equal_bid_ask_rejected(self):
        """bid == ask is an inverted spread."""
        assert self._call(self._valid(yes_bid=50, yes_ask=50)) is False

    def test_decimal_prices_valid(self):
        """Prices already in decimal (0–1) must pass."""
        assert (
            self._call({"ticker": "T", "yes_bid": 0.40, "yes_ask": 0.60, "volume": 0})
            is True
        )

    def test_cent_integer_prices_valid(self):
        """Integer cent prices (1–99) must pass after normalisation."""
        assert self._call(self._valid(yes_bid=35, yes_ask=65)) is True

    def test_alias_field_names_validated(self):
        """yes_bid_dollars / yes_ask_dollars alias names are also validated."""
        assert (
            self._call(
                {
                    "ticker": "T",
                    "yes_bid_dollars": 0.0,  # out of range
                    "yes_ask_dollars": 0.60,
                    "volume_fp": 0.0,
                }
            )
            is False
        )

    def test_price_to_decimal_helper(self):
        """_price_to_decimal normalises int cents and float dollars correctly."""
        from schema_validator import _price_to_decimal

        assert _price_to_decimal(40) == 0.40
        assert _price_to_decimal(0.40) == 0.40
        assert _price_to_decimal("0.55") == 0.55
        assert _price_to_decimal("bad") is None
        assert _price_to_decimal(None) is None


# ── P2-19: run_anomaly_check returns (alerts, should_halt) ───────────────────


class TestRunAnomalyCheckReturnsTuple:
    """run_anomaly_check must return (list[str], bool) and halt selectively."""

    def test_return_type_is_tuple(self):
        with patch("paper.load_paper_trades", return_value=[]):
            from alerts import run_anomaly_check

            result = run_anomaly_check()
        assert isinstance(result, tuple)
        assert len(result) == 2
        msgs, should_halt = result
        assert isinstance(msgs, list)
        assert isinstance(should_halt, bool)

    def test_no_anomalies_no_halt(self):
        with patch("paper.load_paper_trades", return_value=[]):
            from alerts import run_anomaly_check

            msgs, should_halt = run_anomaly_check()
        assert msgs == []
        assert should_halt is False

    def test_halt_thresholds_exported(self):
        from alerts import ALERT_HALT_THRESHOLDS

        assert "WIN_RATE_COLLAPSE" in ALERT_HALT_THRESHOLDS
        assert "CONSECUTIVE_LOSSES" in ALERT_HALT_THRESHOLDS
        assert "EDGE_DECAY" in ALERT_HALT_THRESHOLDS

    def test_is_halt_level_win_rate_below_threshold(self):
        from alerts import _is_halt_level

        # 20% win rate → below 25% halt threshold
        assert _is_halt_level("WIN RATE COLLAPSE: 20% in last 8 settled trades") is True

    def test_is_halt_level_win_rate_above_threshold(self):
        from alerts import _is_halt_level

        # 28% win rate → below 30% warning but above 25% halt threshold
        assert (
            _is_halt_level("WIN RATE COLLAPSE: 28% in last 8 settled trades") is False
        )

    def test_is_halt_level_consecutive_losses_at_threshold(self):
        from alerts import _is_halt_level

        # 6 consecutive → halt
        assert _is_halt_level("CONSECUTIVE LOSSES: 6 losses in a row") is True

    def test_is_halt_level_consecutive_losses_below_threshold(self):
        from alerts import _is_halt_level

        # 5 consecutive → warning only
        assert _is_halt_level("CONSECUTIVE LOSSES: 5 losses in a row") is False

    def test_is_halt_level_edge_decay_halt(self):
        from alerts import _is_halt_level

        # -15% edge → below -10% halt threshold
        assert (
            _is_halt_level("EDGE DECAY: average edge -15.0% in last 8 trades") is True
        )

    def test_is_halt_level_edge_decay_no_halt(self):
        from alerts import _is_halt_level

        # -5% edge → soft warning
        assert (
            _is_halt_level("EDGE DECAY: average edge -5.0% in last 8 trades") is False
        )

    def test_exception_returns_empty_no_halt(self):
        """On exception, return ([], False) — never crash cron."""
        with patch("paper.load_paper_trades", side_effect=RuntimeError("db error")):
            from alerts import run_anomaly_check

            msgs, should_halt = run_anomaly_check()
        assert msgs == []
        assert should_halt is False


class TestCronUsesAnomalyTuple:
    """cron._cmd_cron_body must unpack (msgs, should_halt) from run_anomaly_check."""

    def test_cron_source_unpacks_tuple(self):
        import inspect

        import cron

        src = inspect.getsource(cron._cmd_cron_body)
        assert "_should_halt" in src, (
            "_cmd_cron_body must unpack should_halt from run_anomaly_check"
        )
        assert "if _should_halt" in src

    def test_cron_halts_only_on_should_halt_true(self):
        """Soft anomaly (should_halt=False) must NOT stop the cron cycle."""
        import inspect

        import cron

        src = inspect.getsource(cron._cmd_cron_body)
        # Must have a branch for soft warnings
        assert "soft anomaly" in src.lower() or "_detected_anomalies" in src


# ── P2-34: kalshi_client rejects HTTP 200 with error body ────────────────────


class TestKalshiClientErrorBody:
    """_get/_post/_delete must raise ValueError on 200-with-error responses."""

    def _make_client(self):
        from kalshi_client import KalshiClient

        client = KalshiClient.__new__(KalshiClient)
        client.base_url = "https://demo.kalshi.co"
        # Stub signing so tests don't need real credentials
        client._sign_headers = lambda *a, **kw: {}
        client._full_path = lambda path: path
        return client

    def test_check_error_body_raises_on_error_field(self):
        client = self._make_client()
        import pytest

        with pytest.raises(ValueError, match="market_closed"):
            client._check_error_body({"error": "market_closed"}, "/portfolio/orders")

    def test_check_error_body_passes_on_clean_response(self):
        client = self._make_client()
        client._check_error_body({"order": {"order_id": "abc"}}, "/portfolio/orders")

    def test_check_error_body_passes_on_non_dict(self):
        """Non-dict body (e.g. list) should not raise."""
        client = self._make_client()
        client._check_error_body([1, 2, 3], "/some/path")

    def test_get_raises_on_error_body(self):
        """_get must raise ValueError when response JSON has an error field."""
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"error": "unauthorized"}

        import pytest

        with patch("kalshi_client._request_with_retry", return_value=mock_resp):
            with pytest.raises(ValueError, match="unauthorized"):
                client._get("/markets")

    def test_post_raises_on_error_body(self):
        """_post must raise ValueError when response JSON has an error field."""
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"error": "market_closed"}

        import pytest

        with patch("kalshi_client._request_with_retry", return_value=mock_resp):
            with pytest.raises(ValueError, match="market_closed"):
                client._post("/portfolio/orders", {})

    def test_post_succeeds_on_clean_response(self):
        """_post must return data normally when no error field."""
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"order": {"order_id": "abc123"}}

        with patch("kalshi_client._request_with_retry", return_value=mock_resp):
            result = client._post("/portfolio/orders", {})
        assert result == {"order": {"order_id": "abc123"}}


# ── P2-43: KALSHI_ENV read fresh after cmd_settings reload ───────────────────


class TestKalshiEnvLiveRead:
    """_kalshi_env() and _market_base_url() must read os.getenv each call."""

    def test_kalshi_env_function_exists(self):
        import main

        assert callable(main._kalshi_env)

    def test_market_base_url_function_exists(self):
        import main

        assert callable(main._market_base_url)

    def test_kalshi_env_reads_fresh(self):
        """_kalshi_env() reflects env changes without re-import."""
        import os

        import main

        original = os.environ.get("KALSHI_ENV")
        try:
            os.environ["KALSHI_ENV"] = "prod"
            assert main._kalshi_env() == "prod"
            os.environ["KALSHI_ENV"] = "demo"
            assert main._kalshi_env() == "demo"
        finally:
            if original is None:
                os.environ.pop("KALSHI_ENV", None)
            else:
                os.environ["KALSHI_ENV"] = original

    def test_market_base_url_switches_with_env(self):
        """_market_base_url() returns correct URL for current env."""
        import os

        import main

        original = os.environ.get("KALSHI_ENV")
        try:
            os.environ["KALSHI_ENV"] = "prod"
            assert "kalshi.com" in main._market_base_url()
            assert "demo" not in main._market_base_url()
            os.environ["KALSHI_ENV"] = "demo"
            assert "demo" in main._market_base_url()
        finally:
            if original is None:
                os.environ.pop("KALSHI_ENV", None)
            else:
                os.environ["KALSHI_ENV"] = original

    def test_build_client_reads_env_at_call_time(self):
        """build_client uses os.getenv at call time, not the stale module constant."""
        import inspect

        import main

        src = inspect.getsource(main.build_client)
        assert 'os.getenv("KALSHI_ENV"' in src or "os.getenv('KALSHI_ENV'" in src, (
            "build_client must call os.getenv('KALSHI_ENV') directly"
        )
