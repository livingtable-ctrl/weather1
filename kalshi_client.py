"""
Kalshi API client with RSA-PSS authentication.
"""

import base64
import logging
import re
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


def compute_client_order_id(
    ticker: str,
    side: str,
    action: str,
    count: float,
    price: float,
    time_in_force: str,
    cycle: str,
) -> str:
    """The same deterministic idempotency key place_order() derives
    internally when a real (non-None) cycle is given -- exposed as a
    standalone function so a caller can pre-compute it BEFORE calling
    place_order() and persist it immediately, rather than only learning it
    after a successful/failed placement response.

    AUD batch-23 #1: time_in_force is part of the key (not just an inert
    field on the request body) because two calls with everything else equal
    -- notably ticker+side+action+count+cycle -- but different
    time_in_force are NOT the same order attempt: a GTC entry and a later
    IOC taker-cross replacement of it (order_executor._replace_live_order)
    can otherwise round to the identical price and silently dedupe against
    each other, which would make the taker-cross a no-op that logs success
    while the position never re-enters.

    Batch-22 item 2: every live pre-log call site (order_executor.py's
    _place_live_order/_exit_live_position/_replace_live_order/micro-live,
    and main.cmd_order) now stashes this in execution_log's pre-placement
    row (response={"client_order_id": ...}) before calling place_order() at
    all. If the process crashes between that pre-log write and
    log_order_result() recording the real outcome, the row is left with no
    order_id -- previously written to status='sent' and never re-checked
    against Kalshi again (a real filled position could go permanently
    untracked). order_executor._recover_pending_orders now has this id
    already on hand for exactly that row and can fold it into the same
    client._find_order_by_client_id reconciliation 'unknown' rows already
    get, instead of a dead end.

    Requires a real (non-None/non-empty) cycle -- place_order() falls back
    to a random UUID when cycle is omitted specifically so a caller-less
    retry won't dedup server-side; that fallback is deliberately
    unreproducible from outside place_order() (it depends on call-time
    randomness), so pre-computing only makes sense when the caller already
    has a deterministic cycle string, which every current live call site
    does.
    """
    # Opus review follow-up (F6): a falsy cycle here would silently produce
    # an id that place_order() itself can never reproduce (its own
    # `cycle or uuid.uuid4()` fallback is random and call-time-only) --
    # the row would then be pre-logged with a client_order_id that doesn't
    # match anything on the exchange, and _recover_pending_orders'
    # client_order_id lookup would confidently report "not found," resolving
    # a possibly-real order to 'failed' and unblocking a duplicate
    # placement. Fail loudly here instead of producing a silently-wrong id.
    if not cycle:
        raise ValueError(
            "compute_client_order_id requires a real, non-empty cycle -- "
            "every current live call site has one; if a new caller doesn't, "
            "it must not pre-compute this id at all (let place_order's own "
            "random-UUID fallback apply instead)"
        )
    idempotency_input = (
        f"{ticker}:{side}:{action}:{count:.2f}:{price:.4f}:{time_in_force}:{cycle}"
    )
    import hashlib

    return hashlib.sha256(idempotency_input.encode()).hexdigest()[:32]


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


def _check_env_file_permissions() -> None:
    """Warn (never mutate) if .env is readable more broadly than intended
    (AUD batch-23 #5). .env can carry KALSHI_PRIVATE_KEY_PEM -- the entire
    private key as a plaintext env value -- whenever the WebSocket feed is
    enabled (see kalshi_ws.KalshiWebSocket / cron.py's KALSHI_PRIVATE_KEY_PEM
    read); .env also always carries KALSHI_KEY_ID.

    Deliberately WARN-ONLY, never an active fix like _check_key_permissions'
    Windows branch (icacls /inheritance:r, which strips ALL inherited ACEs
    including SYSTEM/Administrators). Opus review (2026-08-22) caught that
    reusing that destructive path on .env -- a general config file, not a
    single-purpose secret like the .pem -- would silently lock out any
    account other than whichever one first constructs a KalshiClient(),
    including SYSTEM/a service account under a future scheduled-task or
    VM-hosted deployment (already planned for this project). That account
    losing read access to .env means every authenticated call fails closed
    in _sign_headers with no order ever attempted -- a worse, harder-to-
    diagnose outcome than the plaintext-exposure risk being warned about
    here. The icacls call below is read-only (no /inheritance:r, no
    /grant:r) for exactly this reason.

    Only checks a .env that lives in THIS repo's own directory -- not
    wherever find_dotenv()'s upward filesystem walk happens to land if no
    .env exists here (e.g. a stray .env in a parent or home directory that
    has nothing to do with this bot).
    """
    import platform

    try:
        from dotenv import find_dotenv

        env_path_str = find_dotenv()
    except Exception as exc:
        _log.debug("_check_env_file_permissions: could not locate .env: %s", exc)
        return
    if not env_path_str:
        return
    env_path = Path(env_path_str)
    try:
        if env_path.parent.resolve() != Path(__file__).resolve().parent:
            return
    except OSError:
        return

    if platform.system() == "Windows":
        import subprocess

        try:
            result = subprocess.run(
                ["icacls", str(env_path)],
                check=True,
                capture_output=True,
                timeout=10,
                text=True,
            )
            _broad_principals = ("Everyone", "BUILTIN\\Users", "Authenticated Users")
            if any(p in result.stdout for p in _broad_principals):
                _log.warning(
                    ".env at %s appears readable by more than the current "
                    "user (icacls shows a broad grant) and may carry "
                    "KALSHI_PRIVATE_KEY_PEM in plaintext. Consider "
                    "restricting it to your own account only:\n%s",
                    env_path,
                    result.stdout,
                )
        except FileNotFoundError:
            pass  # icacls not available (e.g. wine/WSL) — skip silently
        except Exception as exc:
            _log.debug("_check_env_file_permissions: icacls read failed: %s", exc)
        return

    try:
        import stat as _stat

        mode = env_path.stat().st_mode
        if mode & (_stat.S_IRGRP | _stat.S_IROTH):
            _log.warning(
                ".env at %s is readable by group/others (mode %o) and may "
                "carry KALSHI_PRIVATE_KEY_PEM in plaintext. Run: chmod 600 %s",
                env_path,
                mode & 0o777,
                env_path,
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

# AUD-0076: ticker/series_ticker strings get interpolated straight into REST
# path segments (get_market, get_orderbook, get_candlesticks). No SSRF risk
# (PROD_BASE/DEMO_BASE are fixed, never derived from ticker content) and no
# privilege escalation (same authenticated client either way), but reject
# anything outside Kalshi's own real ticker charset as cheap defense-in-depth
# against path-segment manipulation (e.g. a "../" in a client-supplied ticker
# reaching a different route on the same host) rather than relying solely on
# the HTTP layer to neutralize it. Real tickers look like "KXHIGHNY",
# "KXHIGHNY-26APR09-T72" -- but also, for between-bucket/hourly-directional
# markets, a decimal threshold segment like "KXHIGHAUS-26JUN06-B88.5" or
# "KXTEMPNYCH-26AUG1414-T83.99" (confirmed live in data/predictions.db: 119
# of 364 distinct tickers there use a "."). An earlier version of this regex
# (uppercase/digit/dash only, no ".") rejected every one of those -- caught
# by opus review before push, verified against every ticker string in
# data/*.db (only the synthetic TK_* test rows correctly still reject).
# Segment-based (each dash/dot-delimited chunk is alnum, `\Z` not `$` so a
# trailing newline can't sneak past the anchor). Longest real ticker seen
# is ~28 chars; the 64 cap (round-2 review, F3: the first-pass regex had
# one, the fix dropped it) is generous headroom, not a tight fit.
_TICKER_RE = re.compile(r"[A-Z0-9]+(?:[.-][A-Z0-9]+)*\Z")
_TICKER_MAX_LEN = 64


def _validate_ticker_format(name: str, value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) > _TICKER_MAX_LEN
        or not _TICKER_RE.match(value)
    ):
        # Round-2 review, F1: every call site wraps this in except-Exception,
        # so a rejection is otherwise silent everywhere -- if a future real
        # Kalshi ticker ever uses a character outside this charset, this log
        # line is the only trace that settlement auditing/outcome sync/exit
        # checks silently stopped working for it.
        _log.warning("%s rejected as malformed ticker: %r", name, value)
        raise ValueError(f"{name} has an invalid format: {value!r}")


class OrderStatusUnknownError(Exception):
    """Raised by place_order() when the create-order POST failed AND at
    least one of the 3 reconciliation lookups (_find_order_by_client_id)
    also failed to execute -- so whether the order landed on the exchange
    genuinely cannot be determined right now (AUD-0007).

    Distinct from a plain re-raised POST exception, which means
    reconciliation positively confirmed no matching order exists. Callers
    must not treat this the same as a confirmed-failed placement: log it
    with a status that keeps dedup guards blocking a retry and that a
    recovery routine can periodically re-check via client_order_id (carried
    on this exception) once the API is healthy again.
    """

    def __init__(self, client_order_id: str, original_exc: BaseException):
        self.client_order_id = client_order_id
        self.original_exc = original_exc
        super().__init__(
            f"order outcome unknown for client_order_id={client_order_id}: {original_exc}"
        )

    def __reduce__(self):
        # Opus review follow-up: Exception's default __reduce__ reconstructs
        # via type(self)(*self.args), i.e. OrderStatusUnknownError(msg) --
        # one positional arg, which doesn't match __init__'s required
        # (client_order_id, original_exc) signature and raises TypeError on
        # pickle/copy. No exercised path crosses a process boundary today,
        # but this is cheap to get right rather than leave latent.
        return (self.__class__, (self.client_order_id, self.original_exc))


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
        # Whitelist the DANGEROUS value ('prod') and default everything else
        # (typos, case variants, whitespace, unrecognized strings) to DEMO --
        # AUD-0015: the old `DEMO_BASE if env == "demo" else PROD_BASE` did
        # the opposite, silently pointing any non-exact-'demo' string at PROD.
        self.base_url = PROD_BASE if env == "prod" else DEMO_BASE
        self.key_id = key_id
        self._private_key = None

        # AUD batch-23 #5: .env can carry the private key in plaintext
        # (KALSHI_PRIVATE_KEY_PEM) just as easily as private_key_path's file
        # does -- harden it unconditionally, not gated on whether that
        # specific env var happens to be set this run.
        _check_env_file_permissions()

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
        """Fetch every open market page via cursor pagination.

        AUD batch-23 #2: lifts get_trades'/_get_orders_by_status' full
        3-guard termination shape (not just cursor truthiness) -- Kalshi can
        return a non-empty cursor on what turns out to be the last page
        (confirmed live, see get_trades' docstring), so `not page` is also a
        stop condition, plus a repeated-cursor guard and a 50-page runaway-
        loop backstop. Also defaults limit=1000 (Kalshi's max page size)
        when the caller doesn't supply one -- weather_markets.py's own
        series-wide scan (30k+ markets on some series) previously relied on
        Kalshi's un-stated default page size with no cap at all.
        """
        all_markets: list[dict] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        page_count = 0
        while True:
            p = dict(params)
            p.setdefault("limit", 1000)
            if cursor:
                p["cursor"] = cursor
            data = self._get("/markets", params=p, auth=True)
            self._validate(data, "markets", "/markets")
            page = data.get("markets", [])
            for market in page:
                validate_market(market, source="kalshi")
            all_markets.extend(page)
            page_count += 1
            cursor = data.get("cursor")
            if not cursor or not page:
                break
            if cursor in seen_cursors:
                _log.error(
                    "get_markets: Kalshi returned a repeated cursor %r — stopping "
                    "pagination early instead of looping forever",
                    cursor,
                )
                break
            seen_cursors.add(cursor)
            if page_count >= 50:
                _log.error(
                    "get_markets: exceeded 50 pages (50,000+ markets) -- "
                    "stopping pagination early as a runaway-loop backstop"
                )
                break
        return all_markets

    def get_market(self, ticker: str) -> dict:
        _validate_ticker_format("ticker", ticker)
        data = self._get(f"/markets/{ticker}", auth=True)
        self._validate(data, "market", f"/markets/{ticker}")
        market = data.get("market", {})
        validate_market(market, source="kalshi")
        return market

    def get_orderbook(self, ticker: str) -> dict:
        _validate_ticker_format("ticker", ticker)
        data = self._get(f"/markets/{ticker}/orderbook", auth=True)
        if "orderbook_fp" not in data and "orderbook" not in data:
            self._validate(data, "orderbook", f"/markets/{ticker}/orderbook")
        return data.get("orderbook_fp", data.get("orderbook", {}))

    def get_candlesticks(
        self,
        series_ticker: str,
        ticker: str,
        start_ts: int,
        end_ts: int,
        period_interval: int = 1,
    ) -> list[dict]:
        """GET /series/{series_ticker}/markets/{ticker}/candlesticks -- OHLC price
        history. period_interval is in minutes; Kalshi only accepts 1, 60, or 1440.
        start_ts/end_ts are Unix timestamps (seconds)."""
        _validate_ticker_format("series_ticker", series_ticker)
        _validate_ticker_format("ticker", ticker)
        path = f"/series/{series_ticker}/markets/{ticker}/candlesticks"
        data = self._get(
            path,
            params={
                "start_ts": start_ts,
                "end_ts": end_ts,
                "period_interval": period_interval,
            },
            auth=True,
        )
        self._validate(data, "candlesticks", path)
        return data.get("candlesticks", [])

    def get_trades(
        self, ticker: str, min_ts: int | None = None, max_ts: int | None = None
    ) -> list[dict]:
        """GET /markets/trades -- public trade-flow history for a single market
        (public/unauthenticated endpoint per Kalshi's own docs, verified live
        2026-07-19; signed like every other call here anyway for consistency,
        same as get_markets/get_candlesticks). min_ts/max_ts are optional
        Unix-timestamp (seconds) bounds. Paginates via cursor until exhausted,
        same repeated-cursor guard as get_markets -- verified live that a
        non-empty cursor can still be returned on what turns out to be the
        last page (an empty `trades` list on the next call is what actually
        signals "done"), so this checks both conditions, not just cursor
        truthiness.

        Response fields per trade (current, non-deprecated shape -- Kalshi's
        docs mark `taker_side` deprecated in favor of `taker_outcome_side`/
        `taker_book_side`, verified live 2026-07-19): trade_id, ticker,
        count_fp, yes_price_dollars, no_price_dollars, taker_outcome_side
        ("yes"/"no"), taker_book_side ("bid"/"ask"), created_time,
        is_block_trade.
        """
        all_trades: list[dict] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        page_count = 0
        while True:
            params: dict = {"ticker": ticker, "limit": 1000}
            if min_ts is not None:
                params["min_ts"] = min_ts
            if max_ts is not None:
                params["max_ts"] = max_ts
            if cursor:
                params["cursor"] = cursor
            data = self._get("/markets/trades", params=params, auth=True)
            self._validate(data, "trades", "/markets/trades")
            page = data.get("trades", [])
            all_trades.extend(page)
            page_count += 1
            cursor = data.get("cursor")
            if not cursor or not page:
                break
            if cursor in seen_cursors:
                _log.error(
                    "get_trades: Kalshi returned a repeated cursor %r for %s -- "
                    "stopping pagination early instead of looping forever",
                    cursor,
                    ticker,
                )
                break
            seen_cursors.add(cursor)
            if page_count >= 50:
                _log.error(
                    "get_trades: %s exceeded 50 pages (50,000+ trades) -- "
                    "stopping pagination early as a runaway-loop backstop",
                    ticker,
                )
                break
        return all_trades

    def _paginate_get(
        self,
        path: str,
        list_key: str,
        params: dict | None = None,
        default_limit: int | None = 1000,
    ) -> list[dict]:
        """Fetch every page of a Kalshi cursor-paginated GET endpoint.

        AUD batch-23 #3: get_positions/get_events/get_series_list previously
        returned only a single unpaginated page each -- unlike every other
        list endpoint in this file. Shared here (rather than duplicating the
        3-guard shape a 4th/5th/6th time) since, unlike get_trades/
        _get_orders_by_status, none of these three has any endpoint-specific
        response handling to preserve. Same termination shape as
        get_trades/_get_orders_by_status/get_markets: stops on no cursor, an
        empty page (Kalshi can return a fresh cursor on an already-empty
        final page -- confirmed live, see get_trades' docstring), a repeated
        cursor, or a 50-page runaway-loop backstop.

        default_limit: applied via setdefault (never overrides a
        caller-supplied limit) only when not None. Opus review (2026-08-22)
        caught that 1000 -- Kalshi's documented max for /markets,
        /markets/trades, and /portfolio/positions -- is NOT universal:
        /events documents a max of 200 (get_events passes default_limit=200
        below), and /series documents no limit/cursor support at all
        (get_series_list passes default_limit=None so no limit param is
        ever sent there -- if the endpoint genuinely never returns a
        cursor, this loop just runs once and stops on `not cursor`,
        identical to the pre-pagination behavior). An out-of-range `limit`
        risks a 400 where the endpoint previously returned data at all.
        """
        all_items: list[dict] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        page_count = 0
        while True:
            p = dict(params or {})
            if default_limit is not None:
                p.setdefault("limit", default_limit)
            if cursor:
                p["cursor"] = cursor
            data = self._get(path, params=p, auth=True)
            self._validate(data, list_key, path)
            page = data.get(list_key, [])
            all_items.extend(page)
            page_count += 1
            cursor = data.get("cursor")
            if not cursor or not page:
                break
            if cursor in seen_cursors:
                _log.error(
                    "_paginate_get(%s): Kalshi returned a repeated cursor %r "
                    "— stopping pagination early instead of looping forever",
                    path,
                    cursor,
                )
                break
            seen_cursors.add(cursor)
            if page_count >= 50:
                _log.error(
                    "_paginate_get(%s): exceeded 50 pages (50,000+ items) -- "
                    "stopping pagination early as a runaway-loop backstop",
                    path,
                )
                break
        return all_items

    def get_events(self, **params) -> list[dict]:
        return self._paginate_get("/events", "events", params, default_limit=200)

    def get_series_list(self, **params) -> list[dict]:
        return self._paginate_get("/series", "series", params, default_limit=None)

    # ── Authenticated endpoints ───────────────────────────────────────────────

    def get_balance(self) -> dict:
        return self._get("/portfolio/balance", auth=True)

    def get_positions(self) -> list[dict]:
        # Opus review (2026-08-22): Kalshi's /portfolio/positions response
        # shape may return TWO parallel lists (event_positions and
        # market_positions) advanced by a single shared cursor -- if so, a
        # page with zero market_positions but a non-empty event_positions
        # and a valid cursor would make _paginate_get's `not page` guard
        # stop one page early, silently truncating (the same failure class
        # this fix exists to close). Unverified without live API access;
        # nothing in this repo references event_positions today, and the
        # current single production consumer (output_formatters.py) is
        # display-only, so this is strictly no worse than the prior
        # single-page behavior even in the worst case. Batch-31 L-12: the
        # DEMO_BASE smoke test flagged here has not been re-confirmed run,
        # and AUD-0025's live-position reconciliation
        # (order_executor._reconcile_live_positions) IS now built on top of
        # this -- see that function's own KNOWN LIMITATION docstring, which
        # this comment's risk assessment still applies to.
        return self._paginate_get("/portfolio/positions", "market_positions")

    def _get_orders_by_status(self, status: str) -> list[dict]:
        """Fetch every order with the given status, following Kalshi's cursor
        pagination (same pattern as get_markets/get_trades) instead of
        silently returning only the first page.

        AUD-0007 follow-on (opus review): the 3 reconciliation lookups in
        _find_order_by_client_id (and get_open_orders, which shares this
        helper) previously fetched a single unpaginated page. An account
        with more than one page of order history could have the order
        being reconciled sitting on a later page, making a genuinely
        landed order look "confirmed not found" once enough other orders
        (mostly unrelated) accumulated afterward -- the same class of bug
        AUD-0012 already fixed for execution_log's own local queries, just
        on the Kalshi-API side of the lookup instead.

        Raises (rather than silently treating a malformed page as empty) if
        a response is missing the expected "orders" key -- a degraded/
        reshaped payload must be treated as a failed lookup (uncertain=True
        in the caller), not as "this page had zero matching orders".

        Opus review follow-up (round 2): mirrors get_trades' full 3-guard
        termination shape (this originally only had the repeated-cursor
        guard) -- Kalshi's own pagination convention (confirmed live, see
        get_trades' docstring) can return a non-empty cursor on what turns
        out to be the LAST page, with an empty page on the next call being
        what actually signals "done"; without the `not page` check this
        loops one extra (harmless but wasteful) round-trip per call, and
        without a page-count backstop a server that keeps minting fresh
        cursors could loop indefinitely. This runs SYNCHRONOUSLY inside
        place_order's exception handler (a live-order placement's error
        path), so an unbounded loop here is a latency/availability risk,
        not just a resource one. limit=1000 (Kalshi's max page size, same
        as get_trades) minimizes round-trips for the common case.
        """
        all_orders: list[dict] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        page_count = 0
        while True:
            params: dict = {"status": status, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            data = self._get("/portfolio/orders", params=params, auth=True)
            page = data.get("orders")
            if not isinstance(page, list):
                # Covers both a missing key (page is None) and a present
                # but malformed value (e.g. {"orders": null} -- page is
                # also None -- or {"orders": {}}) with the same descriptive
                # ValueError instead of a bare TypeError from extend().
                raise ValueError(
                    f"_get_orders_by_status({status!r}): response has no "
                    f"usable 'orders' list: {data!r}"
                )
            all_orders.extend(page)
            page_count += 1
            cursor = data.get("cursor")
            if not cursor or not page:
                break
            if cursor in seen_cursors:
                _log.error(
                    "_get_orders_by_status(%r): Kalshi returned a repeated "
                    "cursor %r — stopping pagination early instead of "
                    "looping forever",
                    status,
                    cursor,
                )
                break
            seen_cursors.add(cursor)
            if page_count >= 50:
                _log.error(
                    "_get_orders_by_status(%r): exceeded 50 pages (50,000+ "
                    "orders) -- stopping pagination early as a runaway-loop "
                    "backstop",
                    status,
                )
                break
        return all_orders

    def get_open_orders(self) -> list[dict]:
        return self._get_orders_by_status("resting")

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
        import uuid

        # Deterministic within a cycle: same ticker+side+count+price+
        # time_in_force+cycle → same ID. Kalshi deduplicates server-side when
        # the same client_order_id is resubmitted. Routed through the shared
        # compute_client_order_id() (not computed inline) so a caller that
        # pre-computes this same id before calling place_order() -- see that
        # function's own docstring, batch-22 item 2 -- is guaranteed to get
        # byte-identical results, not two independent formulas that could
        # silently drift apart. AUD batch-23 #1: time_in_force is part of
        # the key (not just an inert field on the request body) because two
        # calls with everything else equal -- notably
        # ticker+side+action+count+cycle -- but different time_in_force are
        # NOT the same order attempt: a GTC entry and a later IOC
        # taker-cross replacement of it (order_executor._replace_live_order)
        # can otherwise round to the identical price and silently dedupe
        # against each other, which would make the taker-cross a no-op that
        # logs success while the position never re-enters. Callers that need
        # each real attempt (a reprice, an exit retry) to get its own key
        # regardless of price/time_in_force repetition fold a per-attempt
        # discriminator into the `cycle` string they pass in, rather than
        # this method dedup'ing across attempts it can't distinguish (see
        # order_executor._replace_live_order/_amend_live_order/
        # _exit_live_position).
        client_order_id = compute_client_order_id(
            ticker,
            side,
            action,
            count,
            price,
            time_in_force,
            cycle or str(uuid.uuid4()),
        )

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
        except Exception as exc:
            # POST was not retried automatically (see _build_session).
            # On any failure, check whether the order landed anyway before re-raising.
            existing, _uncertain = self._find_order_by_client_id(client_order_id)
            if existing:
                _log.warning(
                    "place_order: order landed despite exception; returning existing %s",
                    existing.get("order_id"),
                )
                return existing
            if _uncertain:
                # AUD-0007: at least one reconciliation lookup itself failed
                # to execute, so "not found" here is not a confirmed
                # negative -- a matching order could be sitting in whichever
                # pass didn't complete. Re-raising the original exception
                # would make the caller mark this 'failed', and every dedup
                # guard in execution_log.py excludes 'failed' rows, so a
                # real live position could go permanently untracked and be
                # re-orderable. Callers must catch this distinct type.
                raise OrderStatusUnknownError(client_order_id, exc) from exc
            raise exc

        # order_id is now confirmed live on the exchange -- a failure in this
        # follow-up GET must not make us lose track of it (and must not fall
        # into the block above, which would re-run _find_order_by_client_id
        # and, on a lagged/failed read, re-raise and strand a real order under
        # status="failed" with no poller ever picking it up again).
        try:
            return self.get_order(order_id)
        except Exception:
            _log.warning(
                "place_order: order %s created but get_order follow-up failed; "
                "returning raw create response",
                order_id,
            )
            return resp

    def _find_order_by_client_id(
        self, client_order_id: str
    ) -> tuple[dict | None, bool]:
        """Return (order matching client_order_id or None, reconciliation_uncertain).

        Checks resting orders first, then executed, then canceled — covers the
        taker-fill case where an order lands and fills immediately before the
        timeout retry fires, and the IOC/FOK case where an unfilled order is
        finalized as canceled rather than resting/executed.

        reconciliation_uncertain is True if ANY of the 3 lookup passes itself
        failed to execute (AUD-0007) -- a failed pass could be hiding the real
        match, so a None return alongside uncertain=True must NOT be treated
        as a confirmed "not found": the order may have landed in exactly the
        status bucket this call couldn't check. Only uncertain=False means
        all 3 passes genuinely completed and none matched.
        """
        _uncertain = False
        try:
            for order in self.get_open_orders():
                if order.get("client_order_id") == client_order_id:
                    return order, False
        except Exception as _e:
            _uncertain = True
            _log.warning(
                "_find_order_by_client_id: resting lookup failed (%s) — outcome uncertain",
                _e,
            )
        # Second pass: check executed orders only if resting lookup found nothing.
        # 2026-07-09: was "filled" -- not a real Kalshi status value (the enum is
        # resting/canceled/executed), so this lookup silently matched nothing.
        try:
            for order in self._get_orders_by_status("executed"):
                if order.get("client_order_id") == client_order_id:
                    return order, False
        except Exception as _e:
            _uncertain = True
            _log.warning(
                "_find_order_by_client_id: executed lookup failed (%s) — outcome uncertain",
                _e,
            )
        # Third pass: an IOC/FOK order with no fill is finalized as canceled, not
        # resting/executed -- this is a genuinely exercised path, not just a
        # forward-looking safeguard: order_executor._exit_live_position,
        # order_executor._replace_live_order (the watch --live taker-cross
        # reprice path), and main.py's cmd_order (live path) all pass
        # immediate_or_cancel.
        # A canceled order with a nonzero fill still landed partially; a canceled
        # order with zero fill genuinely never landed, so report not-found (None)
        # so the caller can safely retry.
        try:
            for order in self._get_orders_by_status("canceled"):
                if order.get("client_order_id") == client_order_id:
                    fill_count_fp = order.get("fill_count_fp")
                    try:
                        _filled = fill_count_fp is not None and float(fill_count_fp) > 0
                    except (TypeError, ValueError):
                        # Unparseable fill count -- treat as landed rather than
                        # risk the caller retrying and double-placing a real order.
                        _filled = True
                    return (order, False) if _filled else (None, _uncertain)
        except Exception as _e:
            _uncertain = True
            _log.warning(
                "_find_order_by_client_id: canceled lookup failed (%s) — outcome uncertain",
                _e,
            )
        return None, _uncertain

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

    def amend_order(
        self,
        order_id: str,
        ticker: str,
        side: str,
        action: str,
        count: float,
        price: float,
        client_order_id: str | None = None,
        cycle: str | None = None,
    ) -> dict:
        """
        Amend a resting order's price and/or size atomically via Kalshi's V2
        amend endpoint (POST /portfolio/events/orders/{order_id}/amend) --
        a single exchange-side operation with no client-side window where
        the order is gone-but-not-replaced or fills mid-sequence, unlike
        cancel + verify + place_order.

        Args:
            order_id: The exchange order_id being amended (unchanged by the
                       amend -- Kalshi mutates the existing order in place).
            ticker, side, action, price: same meaning as place_order.
            count: the order's TOTAL desired fillable count -- already-filled
                   contracts plus desired remaining resting count, matching
                   create-order's own count semantics, NOT just "how many
                   more to add." For a pure reprice at the same target
                   quantity, pass the same count used at original placement;
                   Kalshi computes the correct already-filled/still-resting
                   split internally.
            client_order_id: the ORIGINAL order's client_order_id, if known.
                              Optional per Kalshi's docs (order_id in the URL
                              already identifies the order); omitted from the
                              request body entirely when not supplied.
            cycle: forecast cycle string, used only to build a deterministic
                   updated_client_order_id (mirrors place_order's idempotency
                   pattern) so a retry with identical params dedupes
                   server-side rather than double-amending.

        Per Kalshi's docs: amending a resting order preserves queue position
        only when the amendment decreases size -- a price-only reprice (this
        bot's only caller today) always forfeits queue position and goes to
        the back of the book, same as a fresh cancel+replace would.

        Returns the raw V2 amend response: order_id, client_order_id,
        remaining_count (resting contracts post-amend, only present if a
        fill or size change occurred), fill_count (contracts filled by this
        amend crossing the book), average_fill_price, average_fee_paid,
        ts_ms. No `status` field -- same shape convention as cancel_order.
        """
        import hashlib
        import uuid

        v2_side, v2_price = _to_v2_side_price(side, action, price)

        idempotency_input = f"amend:{order_id}:{v2_side}:{count:.2f}:{v2_price:.4f}:{cycle or uuid.uuid4()}"
        updated_client_order_id = hashlib.sha256(
            idempotency_input.encode()
        ).hexdigest()[:32]

        body = {
            "ticker": ticker,
            "side": v2_side,
            "count": f"{count:.2f}",
            "price": f"{v2_price:.4f}",
            "updated_client_order_id": updated_client_order_id,
        }
        if client_order_id:
            body["client_order_id"] = client_order_id

        return self._post(f"/portfolio/events/orders/{order_id}/amend", body)

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
