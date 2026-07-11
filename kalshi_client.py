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

# Separate circuit breakers so read failures don't block order placement.
_kalshi_cb_read = CircuitBreaker(
    name="kalshi_api_read", failure_threshold=5, recovery_timeout=60
)
_kalshi_cb_write = CircuitBreaker(
    name="kalshi_api_write", failure_threshold=5, recovery_timeout=60
)


def _check_key_permissions(key_path) -> None:
    """Warn if the private key file is readable by group/others (Unix) or
    by accounts other than the current user (Windows via icacls)."""
    import platform
    import stat as _stat

    system = platform.system()
    if system == "Windows":
        # P2-G: restrict key file to current user only using icacls.
        # icacls is available on all modern Windows versions (Vista+).
        import subprocess

        try:
            # Remove inherited permissions, grant current user Full Control only.
            # Bare username (no COMPUTERNAME\ prefix): icacls resolves an
            # unqualified name against the running account correctly whether
            # it's a local or domain account. A hardcoded computer-name prefix
            # is wrong for a domain-joined machine (needs DOMAIN\user, not
            # COMPUTERNAME\user) and would silently fail the grant after
            # /inheritance:r has already stripped the inherited ACEs.
            subprocess.run(
                [
                    "icacls",
                    str(key_path),
                    "/inheritance:r",  # remove inherited entries
                    "/grant:r",
                    f"{__import__('os').getlogin()}:(F)",
                ],
                check=True,
                capture_output=True,
                timeout=10,
            )
        except FileNotFoundError:
            pass  # icacls not available (e.g. wine/WSL) — skip silently
        except Exception as _exc:
            _log.warning(
                "Could not restrict key file permissions via icacls (%s): %s. "
                "Ensure %s is readable only by your user account.",
                key_path,
                _exc,
                key_path,
            )
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
        # P2-F: 504 added — consistent with _RETRY_STATUSES which already included it
        status_forcelist={429, 500, 502, 503, 504},
        allowed_methods={"GET", "DELETE"},  # POST excluded — orders must not auto-retry
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_SESSION = _build_session()


def _request_with_retry(
    method: str, url: str, *, check_error_body: bool = False, **kwargs
) -> requests.Response:
    """
    Call _SESSION.request with automatic retry via HTTPAdapter (#67).
    Falls back to latency logging for slow responses (#108).
    Guarded by per-type circuit breakers: read failures don't block writes.

    check_error_body: if True, a 200 response whose JSON body is a dict with a
    top-level "error" key counts as a circuit-breaker failure too (Kalshi's own
    convention -- see KalshiClient._check_error_body). Must be decided here,
    before record_success()/record_failure() runs -- record_success() zeroes
    the failure count, so a caller that re-checks the body afterward and calls
    record_failure() itself can never accumulate past 1 failure, and the
    breaker would never trip on a persistent 200-with-error-body degradation.
    Off by default so other callers of this shared helper (e.g.
    weather_markets.py's Pirate Weather fetch, which has its own separate
    breaker) are unaffected.
    """
    # Apply default timeout if caller didn't specify one
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)

    _cb = (
        _kalshi_cb_write
        if method.upper() in ("POST", "PUT", "PATCH", "DELETE")
        else _kalshi_cb_read
    )
    if _cb.is_open():
        raise CircuitOpenError(_cb.name)

    _t0 = time.perf_counter()
    try:
        resp = _SESSION.request(method, url, **kwargs)
    except Exception as _exc:
        _cb.record_failure()
        raise
    # 5xx = infrastructure failure → trip the breaker.
    # 4xx = client/auth error → not an infra failure, don't penalise the breaker.
    _is_failure = resp.status_code >= 500
    if not _is_failure and check_error_body:
        try:
            _body = resp.json()
        except ValueError:
            _body = None
        if isinstance(_body, dict) and "error" in _body:
            _is_failure = True
    if _is_failure:
        _cb.record_failure()
    else:
        _cb.record_success()
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
    # P2-F: raise for any HTTP error so callers that omit raise_for_status()
    # never accidentally receive a silent 4xx/5xx response object.
    resp.raise_for_status()
    return resp


PROD_BASE = "https://api.elections.kalshi.com/trade-api/v2"
DEMO_BASE = "https://demo-api.kalshi.co/trade-api/v2"


def _to_v2_side_price(side: str, action: str, price: float) -> tuple[str, float]:
    """Map this codebase's (side: yes/no, action: buy/sell, price) model to
    Kalshi's V2 order API (side: bid/ask, single price) model.

    V2 quotes every order from the YES side: side="bid" means buy YES,
    side="ask" means sell YES. Per Kalshi's own V2 docs: "Selling YES is
    economically equivalent to buying NO at 1 - price, but this endpoint
    quotes everything from the YES side." So a NO-side order is expressed as
    the equivalent YES-side trade at the complementary price, with buy/sell
    flipped accordingly:
        (yes, buy,  P) -> (bid, P)
        (yes, sell, P) -> (ask, P)
        (no,  buy,  P) -> (ask, 1-P)
        (no,  sell, P) -> (bid, 1-P)
    """
    if side == "yes":
        return ("bid" if action == "buy" else "ask"), price
    return ("ask" if action == "buy" else "bid"), 1.0 - price


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

    @staticmethod
    def _check_error_body(data: object, path: str) -> None:
        """Raise ValueError if a 200 response contains an error field."""
        if isinstance(data, dict) and "error" in data:
            raise ValueError(
                f"Kalshi API returned 200 with error body at {path!r}: {data['error']!r}"
            )

    def _get(self, path: str, params: dict = None, auth: bool = False) -> dict:
        url = self.base_url + path
        headers = self._sign_headers("GET", self._full_path(path)) if auth else {}
        resp = _request_with_retry(
            "GET", url, headers=headers, params=params, check_error_body=True
        )
        data = resp.json()
        self._check_error_body(data, path)
        return data

    def _post(self, path: str, body: dict) -> dict:
        url = self.base_url + path
        headers = self._sign_headers("POST", self._full_path(path))
        resp = _request_with_retry(
            "POST", url, headers=headers, json=body, check_error_body=True
        )
        data = resp.json()
        self._check_error_body(data, path)
        return data

    def _delete(self, path: str) -> dict:
        url = self.base_url + path
        headers = self._sign_headers("DELETE", self._full_path(path))
        resp = _request_with_retry(
            "DELETE", url, headers=headers, check_error_body=True
        )
        data = resp.json()
        self._check_error_body(data, path)
        return data

    @staticmethod
    def _validate(data: dict, expected_key: str, endpoint: str) -> None:
        """Warn (don't crash) if the API response shape has changed."""
        if not isinstance(data, dict) or expected_key not in data:
            actual = (
                list(data.keys()) if isinstance(data, dict) else type(data).__name__
            )
            _log.error(
                "[Kalshi API] '%s' response missing '%s'. Actual keys: %s. The API may have changed.",
                endpoint,
                expected_key,
                actual,
            )

    # ── Public endpoints (no auth needed) ────────────────────────────────────

    def get_markets(self, **params) -> list[dict]:
        all_markets: list[dict] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            p = dict(params)
            if cursor:
                p["cursor"] = cursor
            data = self._get("/markets", params=p or None, auth=True)
            self._validate(data, "markets", "/markets")
            page = data.get("markets", [])
            for market in page:
                validate_market(market, source="kalshi")
            all_markets.extend(page)
            cursor = data.get("cursor")
            if not cursor:
                break
            if cursor in seen_cursors:
                _log.error(
                    "get_markets: Kalshi returned a repeated cursor %r — stopping "
                    "pagination early instead of looping forever",
                    cursor,
                )
                break
            seen_cursors.add(cursor)
        return all_markets

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

        Uses Kalshi's V2 order-mutation endpoint (/portfolio/events/orders) --
        the legacy POST /portfolio/orders is deprecated and returns errors as
        of 2026-06-18. See _to_v2_side_price for the yes/no+buy/sell -> V2
        bid/ask+price mapping. The V2 create-order response has no `status`
        field (only order_id/fill_count/remaining_count/ts_ms), so this
        fetches the full order via get_order() afterward -- unchanged since
        GET /portfolio/orders/{id} is on the old, unaffected read path --
        so callers keep seeing the same status/fill_count_fp shape as before.

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

        v2_side, v2_price = _to_v2_side_price(side, action, price)
        body = {
            "ticker": ticker,
            "side": v2_side,
            "count": f"{count:.2f}",
            "price": f"{v2_price:.4f}",
            "time_in_force": time_in_force,
            "client_order_id": client_order_id,
            # No prior art in this codebase for this new-in-V2 required field
            # (the legacy endpoint had no equivalent) -- "taker_at_cross" is
            # the standard exchange-default convention: cancel the incoming
            # order rather than risk executing against our own resting order.
            "self_trade_prevention_type": "taker_at_cross",
        }

        try:
            resp = self._post("/portfolio/events/orders", body)
            order_id = resp.get("order_id")
            if not order_id:
                raise ValueError(
                    f"place_order: V2 response missing required order_id: {resp!r}"
                )
            return self.get_order(order_id)
        except Exception as exc:
            # POST was not retried automatically (see _build_session).
            # On any failure, check whether the order landed anyway before re-raising.
            existing = self._find_order_by_client_id(client_order_id)
            if existing:
                _log.warning(
                    "place_order: order landed despite exception; returning existing %s",
                    existing.get("order_id"),
                )
                return existing
            raise exc

    def _find_order_by_client_id(self, client_order_id: str) -> dict | None:
        """Return the order matching client_order_id, or None if not found.

        Checks resting orders first, then executed, then canceled — covers the
        taker-fill case where an order lands and fills immediately before the
        timeout retry fires, and the IOC/FOK case where an unfilled order is
        finalized as canceled rather than resting/executed.
        """
        try:
            for order in self.get_open_orders():
                if order.get("client_order_id") == client_order_id:
                    return order
        except Exception as _e:
            _log.warning(
                "_find_order_by_client_id: resting lookup failed (%s) — assuming not landed",
                _e,
            )
        # Second pass: check executed orders only if resting lookup found nothing.
        # 2026-07-09: was "filled" -- not a real Kalshi status value (the enum is
        # resting/canceled/executed), so this lookup silently matched nothing.
        try:
            data = self._get(
                "/portfolio/orders", params={"status": "executed"}, auth=True
            )
            for order in data.get("orders", []):
                if order.get("client_order_id") == client_order_id:
                    return order
        except Exception as _e:
            _log.warning(
                "_find_order_by_client_id: executed lookup failed (%s) — assuming not landed",
                _e,
            )
        # Third pass: an IOC/FOK order with no fill is finalized as canceled, not
        # resting/executed -- no live caller uses IOC/FOK today (all pass
        # good_till_canceled), but this keeps the lookup correct if that changes.
        # A canceled order with a nonzero fill still landed partially; a canceled
        # order with zero fill genuinely never landed, so report not-found (None)
        # so the caller can safely retry.
        try:
            data = self._get(
                "/portfolio/orders", params={"status": "canceled"}, auth=True
            )
            for order in data.get("orders", []):
                if order.get("client_order_id") == client_order_id:
                    fill_count_fp = order.get("fill_count_fp")
                    try:
                        _filled = fill_count_fp is not None and float(fill_count_fp) > 0
                    except (TypeError, ValueError):
                        # Unparseable fill count -- treat as landed rather than
                        # risk the caller retrying and double-placing a real order.
                        _filled = True
                    return order if _filled else None
        except Exception as _e:
            _log.warning(
                "_find_order_by_client_id: canceled lookup failed (%s) — assuming not landed",
                _e,
            )
        return None

    def get_order(self, order_id: str) -> dict:
        """Fetch a single order by ID from the Kalshi portfolio API.

        Returns the inner order dict with 'status' key: resting/canceled/executed
        (Kalshi's real enum -- there is no "filled" or "expired" status).
        """
        data = self._get(f"/portfolio/orders/{order_id}", auth=True)
        return data.get("order", data)

    def cancel_order(self, order_id: str) -> dict:
        """Cancel a resting order via Kalshi's V2 endpoint -- the legacy
        DELETE /portfolio/orders/{id} is deprecated (see place_order's
        docstring). Returns the raw V2 cancel response (order_id/reduced_by/
        ts_ms -- no status field); callers that need post-cancel status/fill
        info already call get_order() separately (order_executor._finalize_cancel).
        """
        return self._delete(f"/portfolio/events/orders/{order_id}")

    def place_maker_order(
        self,
        ticker: str,
        side: str,
        price: float,
        quantity: float,
        cycle: str | None = None,
    ) -> dict:
        """
        Place a passive limit (maker) order at the specified price.
        Uses good_till_canceled so the order rests in the book.

        Args:
            ticker:   Market ticker
            side:     "yes" or "no"
            price:    Limit price in dollars (e.g. 0.45)
            quantity: Number of contracts
            cycle:    Forecast cycle string for a deterministic idempotency
                      key (see place_order) -- if omitted, every call gets a
                      random UUID and a caller retry after a lost response
                      can silently double-place (2026-07-09).
        """
        return self.place_order(
            ticker=ticker,
            side=side,
            action="buy",
            count=quantity,
            price=price,
            time_in_force="good_till_canceled",
            cycle=cycle,
        )
