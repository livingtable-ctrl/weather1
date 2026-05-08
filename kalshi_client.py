"""
Kalshi API client with RSA-PSS authentication.
"""

import base64
import logging
import time
from pathlib import Path

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from circuit_breaker import CircuitBreaker, CircuitOpenError
from schema_validator import validate_market

_log = logging.getLogger(__name__)

_kalshi_cb = CircuitBreaker(name="kalshi_api", failure_threshold=5, recovery_timeout=60)


def _check_key_permissions(key_path) -> None:
    """Warn if the private key file is readable by group or others (Unix only)."""
    import platform
    import stat as _stat

    if platform.system() == "Windows":
        return
    try:
        mode = key_path.stat().st_mode
        if mode & (_stat.S_IRGRP | _stat.S_IROTH):
            _log.warning(
                "Private key %s is readable by group/others (mode %o). "
                "Run: chmod 600 %s",
                key_path,
                mode & 0o777,
                key_path,
            )
    except OSError:
        pass


_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
# #7: centralized timeout — apply consistently across all API calls
DEFAULT_TIMEOUT = 15  # seconds


def _build_session() -> requests.Session:
    """Build a requests Session with automatic retry on transient errors."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist={429, 500, 502, 503},
        allowed_methods={"GET", "DELETE"},  # POST excluded — orders must not auto-retry
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_SESSION = _build_session()


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """
    Call _SESSION.request with automatic retry via HTTPAdapter (#67).
    Falls back to latency logging for slow responses (#108).
    Guarded by _kalshi_cb to avoid hammering a downed Kalshi API.
    """
    # Apply default timeout if caller didn't specify one
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)

    if _kalshi_cb.is_open():
        raise CircuitOpenError("kalshi_api")

    _t0 = time.perf_counter()
    try:
        resp = _SESSION.request(method, url, **kwargs)
        _kalshi_cb.record_success()
    except Exception as _exc:
        _kalshi_cb.record_failure()
        raise
    _elapsed = time.perf_counter() - _t0
    # #108: warn on slow API responses so latency issues are visible
    if _elapsed > 5:
        _log.warning("Kalshi API slow: %.1fs for %s %s", _elapsed, method, url)
    # #69: log every API call for audit trail and latency monitoring
    try:
        from urllib.parse import urlparse

        from tracker import log_api_request

        endpoint = urlparse(url).path
        elapsed_ms = _elapsed * 1000
        error_str = f"HTTP {resp.status_code}" if resp.status_code >= 400 else None
        log_api_request(method, endpoint, resp.status_code, elapsed_ms, error=error_str)
    except Exception as _e:
        _log.debug("_request_with_retry: log_api_request failed: %s", _e)
    return resp


PROD_BASE = "https://api.elections.kalshi.com/trade-api/v2"
DEMO_BASE = "https://demo-api.kalshi.co/trade-api/v2"


class KalshiClient:
    def __init__(
        self,
        key_id: str | None = None,
        private_key_path: str | None = None,
        env: str = "demo",
    ):
        self.base_url = DEMO_BASE if env == "demo" else PROD_BASE
        self.key_id = key_id
        self._private_key = None

        if private_key_path and Path(private_key_path).exists():
            _check_key_permissions(Path(private_key_path))
            with open(private_key_path, "rb") as f:
                self._private_key = serialization.load_pem_private_key(
                    f.read(), password=None
                )

    def _sign_headers(self, method: str, path: str) -> dict:
        """Build signed auth headers for authenticated endpoints."""
        if not self._private_key or not self.key_id:
            raise ValueError(
                "API key and private key required for authenticated requests"
            )

        timestamp_ms = str(int(time.time() * 1000))
        message = f"{timestamp_ms}{method.upper()}{path}".encode()
        signature = self._private_key.sign(  # type: ignore[call-arg,union-attr,arg-type]
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
            "Content-Type": "application/json",
        }

    def _full_path(self, path: str) -> str:
        """Return the full URL path (e.g. /trade-api/v2/markets) used in signing."""
        from urllib.parse import urlparse

        return urlparse(self.base_url).path + path

    def _get(self, path: str, params: dict = None, auth: bool = False) -> dict:
        url = self.base_url + path
        headers = self._sign_headers("GET", self._full_path(path)) if auth else {}
        resp = _request_with_retry(
            "GET", url, headers=headers, params=params, timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        url = self.base_url + path
        headers = self._sign_headers("POST", self._full_path(path))
        resp = _request_with_retry("POST", url, headers=headers, json=body, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> dict:
        url = self.base_url + path
        headers = self._sign_headers("DELETE", self._full_path(path))
        resp = _request_with_retry("DELETE", url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _validate(data: dict, expected_key: str, endpoint: str) -> None:
        """Warn (don't crash) if the API response shape has changed."""
        if not isinstance(data, dict) or expected_key not in data:
            import warnings

            actual = (
                list(data.keys()) if isinstance(data, dict) else type(data).__name__
            )
            warnings.warn(
                f"[Kalshi API] '{endpoint}' response missing '{expected_key}'. "
                f"Actual keys: {actual}. The API may have changed.",
                stacklevel=3,
            )

    # ── Public endpoints (no auth needed) ────────────────────────────────────

    def get_markets(self, **params) -> list[dict]:
        data = self._get("/markets", params=params or None, auth=True)
        self._validate(data, "markets", "/markets")
        markets = data.get("markets", [])
        for market in markets:
            validate_market(market, source="kalshi")
        return markets

    def get_market(self, ticker: str) -> dict:
        data = self._get(f"/markets/{ticker}", auth=True)
        self._validate(data, "market", f"/markets/{ticker}")
        market = data.get("market", {})
        validate_market(market, source="kalshi")
        return market

    def get_orderbook(self, ticker: str) -> dict:
        data = self._get(f"/markets/{ticker}/orderbook", auth=True)
        if "orderbook_fp" not in data and "orderbook" not in data:
            self._validate(data, "orderbook", f"/markets/{ticker}/orderbook")
        return data.get("orderbook_fp", data.get("orderbook", {}))

    def get_events(self, **params) -> list[dict]:
        data = self._get("/events", params=params or None, auth=True)
        self._validate(data, "events", "/events")
        return data.get("events", [])

    def get_series_list(self, **params) -> list[dict]:
        data = self._get("/series", params=params or None, auth=True)
        self._validate(data, "series", "/series")
        return data.get("series", [])

    # ── Authenticated endpoints ───────────────────────────────────────────────

    def get_balance(self) -> dict:
        return self._get("/portfolio/balance", auth=True)

    def get_positions(self) -> list[dict]:
        data = self._get("/portfolio/positions", auth=True)
        self._validate(data, "market_positions", "/portfolio/positions")
        return data.get("market_positions", [])

    def get_open_orders(self) -> list[dict]:
        data = self._get("/portfolio/orders", params={"status": "resting"}, auth=True)
        self._validate(data, "orders", "/portfolio/orders")
        return data.get("orders", [])

    def place_order(
        self,
        ticker: str,
        side: str,
        action: str,
        count: float,
        price: float,
        time_in_force: str = "good_till_canceled",
        cycle: str | None = None,
    ) -> dict:
        """
        Place a limit order with a deterministic idempotency key.

        Args:
            ticker:        Market ticker, e.g. "KXHIGHNY-26APR09-T72"
            side:          "yes" or "no"
            action:        "buy" or "sell"
            count:         Number of contracts
            price:         Price in dollars, e.g. 0.65 means $0.65 per contract
            time_in_force: "good_till_canceled", "fill_or_kill", "immediate_or_cancel"
            cycle:         Forecast cycle string (e.g. "12z") for deterministic dedup key.
                           If omitted, a random UUID is used so retries won't dedup.
        """
        import hashlib
        import uuid

        # Deterministic within a cycle: same ticker+side+count+price+cycle → same ID.
        # Kalshi deduplicates server-side when the same client_order_id is resubmitted.
        idempotency_input = (
            f"{ticker}:{side}:{action}:{count:.2f}:{price:.4f}:{cycle or uuid.uuid4()}"
        )
        client_order_id = hashlib.sha256(idempotency_input.encode()).hexdigest()[:32]

        body = {
            "ticker": ticker,
            "side": side,
            "action": action,
            "count_fp": f"{count:.2f}",
            "time_in_force": time_in_force,
            "client_order_id": client_order_id,
        }
        if side == "yes":
            body["yes_price_dollars"] = f"{price:.4f}"
        else:
            body["no_price_dollars"] = f"{price:.4f}"

        try:
            return self._post("/portfolio/orders", body)
        except Exception as exc:
            # POST was not retried automatically (see _build_session).
            # On any failure, check whether the order landed anyway before re-raising.
            existing = self._find_order_by_client_id(client_order_id)
            if existing:
                import logging

                logging.getLogger(__name__).warning(
                    "place_order: order landed despite exception; returning existing %s",
                    existing.get("order_id"),
                )
                return existing
            raise exc

    def _find_order_by_client_id(self, client_order_id: str) -> dict | None:
        """Return the open order matching client_order_id, or None if not found."""
        try:
            data = self._get(
                "/portfolio/orders", params={"status": "resting"}, auth=True
            )
            for order in data.get("orders", []):
                if order.get("client_order_id") == client_order_id:
                    return order
        except Exception:
            pass
        return None

    def get_order(self, order_id: str) -> dict:
        """Fetch a single order by ID from the Kalshi portfolio API.

        Returns the inner order dict with 'status' key: resting/filled/canceled/expired.
        """
        data = self._get(f"/portfolio/orders/{order_id}", auth=True)
        return data.get("order", data)

    def cancel_order(self, order_id: str) -> dict:
        return self._delete(f"/portfolio/orders/{order_id}")

    def place_maker_order(
        self,
        ticker: str,
        side: str,
        price: float,
        quantity: float,
    ) -> dict:
        """
        Place a passive limit (maker) order at the specified price.
        Uses good_till_canceled so the order rests in the book.

        Args:
            ticker:   Market ticker
            side:     "yes" or "no"
            price:    Limit price in dollars (e.g. 0.45)
            quantity: Number of contracts
        """
        return self.place_order(
            ticker=ticker,
            side=side,
            action="buy",
            count=quantity,
            price=price,
            time_in_force="good_till_canceled",
        )
