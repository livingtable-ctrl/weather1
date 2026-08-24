"""Tests for web_app.py dashboard API endpoints."""

from datetime import date
from unittest.mock import patch

import pytest

import utils


@pytest.fixture(autouse=True)
def _force_demo_env(monkeypatch):
    """Set DASHBOARD_UNPROTECTED=true so _build_app doesn't require DASHBOARD_PASSWORD.

    utils.DASHBOARD_PASSWORD is cached at import time (conftest.py imports
    main, transitively importing utils, before any test runs) — deleting the
    env var doesn't reach that cached module attribute, so it must be patched
    directly (matches test_web_auth.py's established convention). Without
    this, .env's real DASHBOARD_PASSWORD leaks into every test's _check_auth
    enforcement and every endpoint 401s.
    """
    monkeypatch.setenv("DASHBOARD_UNPROTECTED", "true")
    monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DASHBOARD_UNPROTECTED", "true")
    monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "")
    from web_app import _build_app

    app = _build_app(object())  # dummy client
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def client_and_kalshi_mock(monkeypatch):
    """Like `client`, but the Kalshi client _build_app is closed over is a
    MagicMock (real get_markets attribute) instead of a plain object() --
    for tests that need to control what /api/trades' live quote batch-fetch
    returns. The plain `client` fixture's object() dummy already fails
    closed safely on client.get_markets(...) (AttributeError, caught by the
    route's own broad except) without needing any mock at all -- this
    fixture exists only for tests that want the live path to actually run."""
    monkeypatch.setenv("DASHBOARD_UNPROTECTED", "true")
    monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "")
    from unittest.mock import MagicMock

    from web_app import _build_app

    mock_kalshi = MagicMock()
    app = _build_app(mock_kalshi)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, mock_kalshi


class TestDashboardPasswordStartupGuard:
    """AUD-0018: .env.example's DASHBOARD_PASSWORD comment used to claim
    'leave empty to disable auth' -- the real behavior (this guard) refuses
    to start instead unless DASHBOARD_UNPROTECTED=true is also set. No
    existing test actually exercised the RuntimeError branch itself (every
    other test in this file uses the autouse _force_demo_env fixture to
    bypass it) -- these two do, overriding that fixture's env within the
    test body."""

    def test_raises_when_password_unset_and_unprotected_not_set(self, monkeypatch):
        monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
        monkeypatch.delenv("DASHBOARD_UNPROTECTED", raising=False)
        from web_app import _build_app

        with pytest.raises(RuntimeError, match="DASHBOARD_PASSWORD must be set"):
            _build_app(object())

    def test_starts_when_unprotected_explicitly_set(self, monkeypatch):
        """Positive control: the documented escape hatch must still work."""
        monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
        monkeypatch.setenv("DASHBOARD_UNPROTECTED", "true")
        from web_app import _build_app

        _build_app(object())  # must not raise


def test_balance_history_default_50(client):
    """Default returns at most 50 points."""
    history = [
        {"ts": f"2024-01-{d:02d}T00:00:00", "balance": 900 + d, "event": "T"}
        for d in range(1, 92)
    ]
    last_bal = history[-1]["balance"]
    # Patch get_balance to match the last history point so the live-tail
    # synthetic append (added for open-trade cost tracking) is skipped.
    with (
        patch("paper.get_balance_history", return_value=history),
        patch("paper.get_balance", return_value=last_bal),
    ):
        r = client.get("/api/balance_history")
        data = r.get_json()
        assert len(data["labels"]) <= 50


def test_balance_history_range_all(client):
    """?range=all returns all points."""
    history = [
        {"ts": f"2024-01-{d:02d}T00:00:00", "balance": 900 + d, "event": "T"}
        for d in range(1, 92)
    ]
    last_bal = history[-1]["balance"]
    with (
        patch("paper.get_balance_history", return_value=history),
        patch("paper.get_balance", return_value=last_bal),
    ):
        r = client.get("/api/balance_history?range=all")
        data = r.get_json()
        assert len(data["labels"]) == 91


def test_balance_history_invalid_range_default(client):
    """Invalid range falls back to default 50 points."""
    history = [
        {"ts": f"2024-01-{d:02d}T00:00:00", "balance": 900 + d, "event": "T"}
        for d in range(1, 92)
    ]
    last_bal = history[-1]["balance"]
    with (
        patch("paper.get_balance_history", return_value=history),
        patch("paper.get_balance", return_value=last_bal),
    ):
        r = client.get("/api/balance_history?range=bogus")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["labels"]) <= 50


def test_get_live_market_snapshot_returns_list():
    """_get_live_market_snapshot returns list even with no data."""
    from web_app import _get_live_market_snapshot

    result = _get_live_market_snapshot()
    assert isinstance(result, list)


def test_build_stream_data_has_markets_key():
    """_build_stream_data includes markets key."""
    from web_app import _build_stream_data

    with (
        patch("paper.get_balance", return_value=1000.0),
        patch("paper.get_open_trades", return_value=[]),
        patch("tracker.brier_score", return_value=0.20),
    ):
        data = _build_stream_data()
        assert "markets" in data
        assert isinstance(data["markets"], list)


def test_balance_history_range_1mo(client):
    """?range=1mo returns only points from the last 30 days."""
    from datetime import UTC, datetime, timedelta

    now = datetime(2025, 9, 1, tzinfo=UTC)
    history = [
        {"ts": (now - timedelta(days=d)).isoformat(), "balance": 1000, "event": "T"}
        for d in range(60)  # 60 days of data
    ]
    with patch("paper.get_balance_history", return_value=history):
        with patch("web_app._now_utc", return_value=now):
            r = client.get("/api/balance_history?range=1mo")
            data = r.get_json()
            # With 60 days of data and a 30-day window, we should get at most 31 labels
            assert len(data["labels"]) <= 31


def test_balance_history_range_3mo(client):
    """?range=3mo returns only points from the last 90 days."""
    from datetime import UTC, datetime, timedelta

    now = datetime(2025, 9, 1, tzinfo=UTC)
    history = [
        {"ts": (now - timedelta(days=d)).isoformat(), "balance": 1000, "event": "T"}
        for d in range(200)
    ]
    with patch("paper.get_balance_history", return_value=history):
        with patch("web_app._now_utc", return_value=now):
            r = client.get("/api/balance_history?range=3mo")
            data = r.get_json()
            # With 200 days of data and a 90-day window, we should get at most 91 labels
            assert len(data["labels"]) <= 91


def test_dashboard_route_returns_200_with_title(client):
    """Dashboard page returns 200 and contains 'Dashboard'."""
    r = client.get("/")
    assert r.status_code == 200
    assert b"Dashboard" in r.data


def test_analytics_route_returns_200_with_title(client):
    """Analytics page returns 200 and contains 'Analytics'."""
    r = client.get("/analytics")
    assert r.status_code == 200
    assert b"Analytics" in r.data


class TestDashboardAuth:
    def test_no_auth_required_when_password_unset(self, client, monkeypatch):
        """Dashboard is open when DASHBOARD_PASSWORD is empty."""
        import utils

        monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "")
        resp = client.get("/")
        assert resp.status_code != 401

    def test_401_when_password_set_and_no_credentials(self, client, monkeypatch):
        """Dashboard returns 401 when password is set and no Authorization header sent."""
        import utils

        monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "secret")
        resp = client.get("/")
        assert resp.status_code == 401

    def test_200_with_correct_credentials(self, client, monkeypatch):
        """Dashboard returns 200 with correct Basic Auth credentials."""
        import base64

        import utils

        monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "secret")
        creds = base64.b64encode(b"kalshi:secret").decode()
        resp = client.get("/", headers={"Authorization": f"Basic {creds}"})
        assert resp.status_code == 200


def test_api_graduation_returns_correct_shape(client):
    """/api/graduation returns trades_done, win_rate, ready, fear_greed_score, fear_greed_label."""
    with (
        patch(
            "paper.get_performance",
            return_value={
                "settled": 10,
                "win_rate": 0.5,
                "total_pnl": -20.0,
                "roi": -0.02,
            },
        ),
        patch("paper.graduation_check", return_value=None),
        patch("paper.fear_greed_index", return_value=(55, "Neutral")),
    ):
        r = client.get("/api/graduation")
        assert r.status_code == 200
        d = r.get_json()
        assert d["trades_done"] == 10
        assert d["win_rate"] == 0.5
        assert d["ready"] is False
        assert d["fear_greed_score"] == 55
        assert d["fear_greed_label"] == "Neutral"


def test_api_brier_history_returns_list(client):
    """/api/brier_history returns a JSON list of {week, brier} dicts."""
    with patch(
        "tracker.get_brier_over_time",
        return_value=[{"week": "2025-W40", "brier": 0.21}],
    ):
        r = client.get("/api/brier_history")
        assert r.status_code == 200
        d = r.get_json()
        assert isinstance(d, list)
        assert d[0]["week"] == "2025-W40"
        assert d[0]["brier"] == 0.21


def test_risk_route_returns_200_with_title(client):
    """Risk page returns 200 and contains 'Risk'."""
    r = client.get("/risk")
    assert r.status_code == 200
    assert b"Risk" in r.data


def test_api_risk_returns_correct_shape(client):
    """/api/risk returns city_exposure, directional, expiry_clustering, total_exposure."""
    with (
        patch(
            "paper.get_open_trades",
            return_value=[
                {
                    "city": "NYC",
                    "side": "yes",
                    "cost": 10.0,
                    "target_date": "2025-12-01",
                    "ticker": "X",
                },
            ],
        ),
        patch("paper.get_total_exposure", return_value=0.1),
        patch("paper.check_aged_positions", return_value=[]),
        patch("paper.check_correlated_event_exposure", return_value=[]),
        patch("paper.get_expiry_date_clustering", return_value=[]),
    ):
        r = client.get("/api/risk")
        assert r.status_code == 200
        d = r.get_json()
        assert "city_exposure" in d
        assert "directional" in d
        assert "expiry_clustering" in d
        assert "total_exposure" in d
        assert d["directional"]["yes"] == 10.0
        assert d["directional"]["no"] == 0.0


def test_api_config_includes_both_fee_rates(client):
    """/api/config must surface both kalshi_fee_rate (taker, reference) and
    kalshi_maker_fee_rate (the rate this bot's own trades actually pay) —
    the Settings tab must not show only the stale taker-only rate.
    """
    r = client.get("/api/config")
    assert r.status_code == 200
    d = r.get_json()
    assert "kalshi_fee_rate" in d
    assert "kalshi_maker_fee_rate" in d
    assert d["kalshi_maker_fee_rate"] == pytest.approx(0.0)


def test_trades_route_returns_200_with_title(client):
    """Trades page returns 200 and contains 'Trades'."""
    r = client.get("/trades")
    assert r.status_code == 200
    assert b"Trades" in r.data


def test_api_trades_returns_correct_shape(client):
    """/api/trades returns open and closed keys as lists."""
    with patch(
        "paper.get_all_trades",
        return_value=[
            {
                "id": 1,
                "ticker": "T1",
                "settled": False,
                "city": "NYC",
                "side": "yes",
            },
            {
                "id": 2,
                "ticker": "T2",
                "settled": True,
                "pnl": 5.0,
                "city": "LA",
                "side": "no",
                "outcome": "no",
            },
        ],
    ):
        # The `client` fixture's underlying Kalshi client is a plain
        # object() with no get_markets -- /api/trades' live batch-fetch
        # hits AttributeError, caught by its own broad except, and falls
        # back to the (empty) SSE snapshot cache. No real network call is
        # possible here; nothing needs mocking for that reason. This test
        # stays scoped to response shape, not quote enrichment (see
        # TestApiTradesLiveQuoteEnrichment below, which uses
        # client_and_kalshi_mock to actually exercise the live path).
        r = client.get("/api/trades")
        assert r.status_code == 200
        d = r.get_json()
        assert "open" in d
        assert "closed" in d
        assert len(d["open"]) == 1
        assert len(d["closed"]) == 1
        assert d["closed"][0]["ticker"] == "T2"


def test_api_trades_loads_the_paper_ledger_only_once(client):
    """AUD-0053: api_trades() used to call both paper.get_open_trades() and
    paper.get_all_trades() -- each independently doing a full read+parse+
    SHA-256-checksum of paper_trades.json with no caching, so one HTTP
    request cost two full ledger loads. Must derive open trades from the
    single get_all_trades() call instead of a second _load()."""
    with (
        patch(
            "paper.get_all_trades",
            return_value=[
                {"id": 1, "ticker": "T1", "settled": False, "city": "NYC"},
                {"id": 2, "ticker": "T2", "settled": True, "city": "LA"},
            ],
        ) as mock_all,
        patch("paper.get_open_trades") as mock_open,
    ):
        r = client.get("/api/trades")
        assert r.status_code == 200
        mock_all.assert_called_once()
        mock_open.assert_not_called()


class TestApiTradesLiveQuoteEnrichment:
    """L18015: /api/trades' live-quote enrichment used to depend solely on
    the opportunistic top-10-positive-edge SSE snapshot cache, which drops a
    position the moment its own edge decays past zero -- normal, expected
    behavior for an already-held position, not something that should cost it
    its live quote. Now batch-fetches every open position's own ticker in
    one live GET /markets?tickers=... call (reusing the same `client` this
    route's closure already has, not a freshly-constructed one), falling
    back to the SSE cache only if the live call fails or a specific ticker
    isn't in the batch.

    Uses client_and_kalshi_mock (a MagicMock client) rather than the plain
    `client` fixture, since these tests need to control what the live batch
    call returns."""

    def _open_trade(self, ticker="T1"):
        return {
            "id": 1,
            "ticker": ticker,
            "city": "NYC",
            "side": "yes",
            "entry_price": 0.6,
            "cost": 10.0,
            "target_date": "2025-12-01",
        }

    def test_live_batch_fetch_is_used_when_it_succeeds(self, client_and_kalshi_mock):
        """A ticker the SSE cache never saw (e.g. its edge already decayed
        below zero, so /analyze's opps filter dropped it) still gets a live
        quote via the batched call -- the actual bug this entry describes."""
        c, mock_kalshi = client_and_kalshi_mock
        with (
            patch("paper.get_all_trades", return_value=[self._open_trade("T1")]),
            patch(
                "web_app._get_live_market_snapshot", return_value=[]
            ),  # empty SSE cache
        ):
            mock_kalshi.get_markets.return_value = [
                {"ticker": "T1", "yes_bid": 62, "yes_ask": 65}
            ]
            r = c.get("/api/trades")
            d = r.get_json()
            assert d["open"][0]["current_yes_bid"] == pytest.approx(0.62)
            assert d["open"][0]["current_yes_ask"] == pytest.approx(0.65)
            # Positive control: confirm the batch was actually called with
            # this exact ticker, not just that a plausible-looking number
            # happened to appear.
            mock_kalshi.get_markets.assert_called_once_with(tickers="T1", limit=1)

    def test_live_quote_takes_precedence_over_a_different_sse_value_for_the_same_ticker(
        self, client_and_kalshi_mock
    ):
        """When BOTH sources have data for the same ticker (not just when one
        is empty), the live value must win -- the SSE cache can be stale by
        up to however long since the operator last loaded /analyze."""
        c, mock_kalshi = client_and_kalshi_mock
        with (
            patch("paper.get_all_trades", return_value=[self._open_trade("T1")]),
            patch(
                "web_app._get_live_market_snapshot",
                return_value=[{"ticker": "T1", "yes_bid": 0.10, "yes_ask": 0.12}],
            ),
        ):
            mock_kalshi.get_markets.return_value = [
                {"ticker": "T1", "yes_bid": 62, "yes_ask": 65}
            ]
            r = c.get("/api/trades")
            d = r.get_json()
            assert d["open"][0]["current_yes_bid"] == pytest.approx(0.62)
            assert d["open"][0]["current_yes_ask"] == pytest.approx(0.65)

    def test_falls_back_to_sse_cache_when_live_fetch_raises(
        self, client_and_kalshi_mock
    ):
        """A network/auth failure on the live batch call must not break
        /api/trades -- fall back to whatever the SSE cache has."""
        c, mock_kalshi = client_and_kalshi_mock
        with (
            patch("paper.get_all_trades", return_value=[self._open_trade("T1")]),
            patch(
                "web_app._get_live_market_snapshot",
                return_value=[{"ticker": "T1", "yes_bid": 0.40, "yes_ask": 0.44}],
            ),
        ):
            mock_kalshi.get_markets.side_effect = RuntimeError("network error")
            r = c.get("/api/trades")
            assert r.status_code == 200  # must not 500
            d = r.get_json()
            assert d["open"][0]["current_yes_bid"] == pytest.approx(0.40)
            assert d["open"][0]["current_yes_ask"] == pytest.approx(0.44)

    def test_ticker_missing_from_live_batch_falls_back_to_sse_cache(
        self, client_and_kalshi_mock
    ):
        """A ticker requested in the batch but not returned (e.g. delisted)
        falls back per-ticker to the SSE cache, not to no-quote at all."""
        c, mock_kalshi = client_and_kalshi_mock
        with (
            patch(
                "paper.get_all_trades",
                return_value=[self._open_trade("T1"), self._open_trade("T2")],
            ),
            patch(
                "web_app._get_live_market_snapshot",
                return_value=[{"ticker": "T2", "yes_bid": 0.10, "yes_ask": 0.15}],
            ),
        ):
            # Batch only returns T1 -- T2 is missing from the live response.
            mock_kalshi.get_markets.return_value = [
                {"ticker": "T1", "yes_bid": 62, "yes_ask": 65}
            ]
            r = c.get("/api/trades")
            d = r.get_json()
            by_ticker = {t["ticker"]: t for t in d["open"]}
            assert by_ticker["T1"]["current_yes_bid"] == pytest.approx(0.62)
            assert by_ticker["T2"]["current_yes_bid"] == pytest.approx(0.10)

    def test_no_open_positions_skips_the_live_call_entirely(
        self, client_and_kalshi_mock
    ):
        """No open positions -> no tickers to batch -> get_markets is never
        even called (no wasted API call)."""
        c, mock_kalshi = client_and_kalshi_mock
        with patch("paper.get_all_trades", return_value=[]):
            r = c.get("/api/trades")
            assert r.status_code == 200
            mock_kalshi.get_markets.assert_not_called()

    def test_multiple_open_positions_batch_into_one_call(self, client_and_kalshi_mock):
        """N open positions -> ONE get_markets(tickers=...) call, not N --
        the entire point of using the batched endpoint over per-ticker
        get_market() calls."""
        c, mock_kalshi = client_and_kalshi_mock
        with patch(
            "paper.get_all_trades",
            return_value=[self._open_trade("T1"), self._open_trade("T2")],
        ):
            mock_kalshi.get_markets.return_value = []
            c.get("/api/trades")
            assert mock_kalshi.get_markets.call_count == 1
            _, kwargs = mock_kalshi.get_markets.call_args
            assert set(kwargs["tickers"].split(",")) == {"T1", "T2"}
            assert kwargs["limit"] == 2

    def test_malformed_live_price_degrades_to_no_quote_not_a_crash(
        self, client_and_kalshi_mock
    ):
        """A live market with an unparseable price field must not 500 the
        whole endpoint -- degrades that one field via _safe_market_price to
        0 (="no quote"), which then falls back to the (here, empty) snapshot
        cache rather than being reported as a misleading real price of 0."""
        c, mock_kalshi = client_and_kalshi_mock
        with (
            patch("paper.get_all_trades", return_value=[self._open_trade("T1")]),
            patch("web_app._get_live_market_snapshot", return_value=[]),
        ):
            mock_kalshi.get_markets.return_value = [
                {"ticker": "T1", "yes_bid": "not-a-number", "yes_ask": 65}
            ]
            r = c.get("/api/trades")
            assert r.status_code == 200
            d = r.get_json()
            assert d["open"][0]["current_yes_bid"] is None
            assert d["open"][0]["current_yes_ask"] == pytest.approx(0.65)

    def test_degraded_live_price_falls_back_to_snapshot_cache(
        self, client_and_kalshi_mock
    ):
        """batch-34 item 7f: a live quote field degraded to 0 (the
        _safe_market_price "no quote" sentinel) must fall back to the SSE
        snapshot cache for that field, the same as if the ticker were
        missing from the batch response entirely -- not pass the misleading
        0 straight through, contradicting this endpoint's own fallback
        comment."""
        c, mock_kalshi = client_and_kalshi_mock
        with (
            patch("paper.get_all_trades", return_value=[self._open_trade("T1")]),
            patch(
                "web_app._get_live_market_snapshot",
                return_value=[{"ticker": "T1", "yes_bid": 0.42, "yes_ask": 0.47}],
            ),
        ):
            mock_kalshi.get_markets.return_value = [
                {"ticker": "T1", "yes_bid": "not-a-number", "yes_ask": 65}
            ]
            r = c.get("/api/trades")
            assert r.status_code == 200
            d = r.get_json()
            assert d["open"][0]["current_yes_bid"] == pytest.approx(0.42), (
                "degraded live yes_bid (0) must fall back to the snapshot "
                "cache's real value, not be reported as a literal 0 price"
            )
            assert d["open"][0]["current_yes_ask"] == pytest.approx(0.65), (
                "a genuinely present live yes_ask must NOT be overridden by "
                "the snapshot cache"
            )


def test_signals_route_returns_200_with_title(client):
    """Signals page returns 200 and contains 'Signals'."""
    r = client.get("/signals")
    assert r.status_code == 200
    assert b"Signals" in r.data


def test_api_signals_returns_correct_shape(client):
    """/api/signals returns log and alerts keys."""
    import json
    from unittest.mock import mock_open

    fake_lines = "\n".join(
        [
            json.dumps(
                {
                    "ts": "2025-01-01T00:00:00",
                    "ticker": "X",
                    "signal": "BUY",
                    "net_edge": 0.05,
                }
            ),
            json.dumps(
                {
                    "ts": "2025-01-02T00:00:00",
                    "signal": "ALERT",
                    "level": "WARNING",
                    "message": "loss streak",
                }
            ),
        ]
    )
    with patch("builtins.open", mock_open(read_data=fake_lines)):
        with patch("pathlib.Path.exists", return_value=True):
            r = client.get("/api/signals")
            assert r.status_code == 200
            d = r.get_json()
            assert "log" in d
            assert "alerts" in d
            assert isinstance(d["log"], list)
            assert isinstance(d["alerts"], list)


def test_today_forecasts_uses_city_local_today(client):
    """AUD-0046 (2026-08-18 max-depth forensic audit): /api/today_forecasts
    used to label every city's forecast with a single shared utils.utc_today()
    date. Fixed to compute each city's own local today via ZoneInfo.

    At 2026-07-10 05:00 UTC: NYC (EDT, UTC-4) has already rolled to its local
    07-10, but LA (PDT, UTC-7) is still 07-09. If both cities were still
    getting the same shared date, this fix would be a no-op -- asserting the
    two cities' first-requested dates DIFFER, and each matches its own real
    local calendar date, proves a genuine per-city ZoneInfo lookup."""
    from datetime import UTC, datetime

    fixed_instant = datetime(2026, 7, 10, 5, 0, tzinfo=UTC)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_instant.replace(tzinfo=None)
            return fixed_instant.astimezone(tz)

    requested = {}

    def _fake_gwf(city, d):
        requested.setdefault(city, []).append(d.isoformat())
        return None

    # Opus-review-noted: patches the stdlib datetime.datetime class itself,
    # not "web_app.datetime" -- web_app's endpoints do `from datetime import
    # datetime` as a LOCAL import inside the function body, executed fresh at
    # request time, so patching a module-level "web_app.datetime" attribute
    # (this file's other tests' usual pattern, e.g. test_cmd_forecast.py's
    # patch.object(main, "datetime", ...)) would never be seen by that local
    # import. This is the broadest-blast-radius option in this test suite
    # (any code anywhere doing datetime.datetime.now() during this request
    # gets the fixed instant) but is the only one that actually reaches a
    # function-local import; see tests/test_paper.py's identical pattern.
    #
    # GOTCHA (opus-review round 2): this does NOT reach utils.utc_today() --
    # utils.py binds its own `datetime` name via `from datetime import
    # datetime` at utils' own import time (long before this patch runs), so
    # utils.utc_today()'s datetime.now(UTC) call still sees the real clock.
    # Harmless here since neither test below exercises a ZoneInfo-failure
    # fallback branch or asserts on a value computed via utils.utc_today(),
    # but a future test that does either of those needs its own explicit
    # patch("utils.utc_today", return_value=...) too (see
    # TestPaperOrderDaysOutUsesCityLocalToday's test in this file for that
    # pattern) -- this patch alone will not control it.
    with (
        patch("datetime.datetime", _FixedDatetime),
        patch("weather_markets.get_weather_forecast", side_effect=_fake_gwf),
    ):
        r = client.get("/api/today_forecasts")
    assert r.status_code == 200
    assert requested["NYC"][0] == "2026-07-10"
    assert requested["LA"][0] == "2026-07-09"
    assert requested["NYC"][0] != requested["LA"][0]


def test_today_forecasts_each_city_carries_its_own_date(client):
    """Opus-review-caught (round 2, batch-07): /api/today_forecasts never
    carried a per-city date -- harmless while every city shared one implicit
    UTC date, but once "today"/"tomorrow" became genuinely per-city
    (AUD-0046) a client had no way to tell WHICH calendar date a given
    city's "today" meant. Fixed by adding "date" inside each city's dict,
    matching /api/forecast's identical fix."""
    from datetime import UTC, datetime

    fixed_instant = datetime(2026, 7, 10, 5, 0, tzinfo=UTC)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_instant.replace(tzinfo=None)
            return fixed_instant.astimezone(tz)

    def _fake_gwf(city, d):
        return {
            "date": d.isoformat(),
            "high_f": 75.0,
            "low_f": 55.0,
            "precip_in": 0.0,
            "models_used": 1,
        }

    with (
        patch("datetime.datetime", _FixedDatetime),
        patch("weather_markets.get_weather_forecast", side_effect=_fake_gwf),
    ):
        r = client.get("/api/today_forecasts")
    data = r.get_json()
    assert data["today"]["NYC"]["date"] == "2026-07-10"
    assert data["today"]["LA"]["date"] == "2026-07-09"
    assert data["tomorrow"]["NYC"]["date"] == "2026-07-11"
    assert data["tomorrow"]["LA"]["date"] == "2026-07-10"


def test_forecast_endpoint_uses_city_local_today(client):
    """AUD-0046: /api/forecast?day=0 used to anchor every city's date on a
    single shared utils.utc_today() value -- same fix and regression case as
    /api/today_forecasts above, for this sibling endpoint."""
    from datetime import UTC, datetime

    fixed_instant = datetime(2026, 7, 10, 5, 0, tzinfo=UTC)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_instant.replace(tzinfo=None)
            return fixed_instant.astimezone(tz)

    requested = {}

    def _fake_gwf(city, d):
        requested.setdefault(city, []).append(d.isoformat())
        return None

    # Patches stdlib datetime.datetime, not "web_app.datetime" -- see
    # test_today_forecasts_uses_city_local_today's comment above for why.
    with (
        patch("datetime.datetime", _FixedDatetime),
        patch("weather_markets.get_weather_forecast", side_effect=_fake_gwf),
    ):
        r = client.get("/api/forecast?day=0")
    assert r.status_code == 200
    assert requested["NYC"][0] == "2026-07-10"
    assert requested["LA"][0] == "2026-07-09"


def test_forecast_endpoint_each_city_carries_its_own_date(client):
    """Opus-review-caught (batch-07): once `target` was hoisted into the
    per-city loop for AUD-0046, the top-level `jsonify({"date": target...})`
    kept reading whatever `target` the loop last left behind -- alphabetically
    the last city in sorted(CITY_COORDS) -- silently mislabeling every OTHER
    city's forecast with that city's date instead of its own. Fixed by
    putting "date" inside each city's own dict. This test would have failed
    against the pre-fix code: LA's response would have carried whichever
    city sorts last alphabetically's date, not LA's real 07-09."""
    from datetime import UTC, datetime

    fixed_instant = datetime(2026, 7, 10, 5, 0, tzinfo=UTC)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_instant.replace(tzinfo=None)
            return fixed_instant.astimezone(tz)

    def _fake_gwf(city, d):
        return {
            "date": d.isoformat(),
            "high_f": 75.0,
            "low_f": 55.0,
            "precip_in": 0.0,
            "models_used": 1,
        }

    # Patches stdlib datetime.datetime, not "web_app.datetime" -- see
    # test_today_forecasts_uses_city_local_today's comment above for why.
    with (
        patch("datetime.datetime", _FixedDatetime),
        patch("weather_markets.get_weather_forecast", side_effect=_fake_gwf),
    ):
        r = client.get("/api/forecast?day=0")
    data = r.get_json()
    assert data["cities"]["NYC"]["date"] == "2026-07-10"
    assert data["cities"]["LA"]["date"] == "2026-07-09"
    assert data["cities"]["NYC"]["date"] != data["cities"]["LA"]["date"]


def test_forecast_route_returns_200_with_title(client):
    """Forecast page returns 200 and contains 'Forecast'."""
    r = client.get("/forecast")
    assert r.status_code == 200
    assert b"Forecast" in r.data


def test_api_forecast_quality_returns_correct_shape(client):
    """/api/forecast_quality returns city_heatmap and source_reliability keys."""
    with (
        patch(
            "tracker.get_calibration_by_city",
            return_value={
                "NYC": {"n": 10, "brier": 0.22, "bias": 0.01},
            },
        ),
        patch(
            "tracker.get_ensemble_member_accuracy",
            return_value={
                "NYC": {"GFS": {"mae": 2.1, "n": 5}, "NAM": {"mae": 1.8, "n": 5}},
            },
        ),
    ):
        r = client.get("/api/forecast_quality")
        assert r.status_code == 200
        d = r.get_json()
        assert "city_heatmap" in d
        assert "source_reliability" in d
        assert "NYC" in d["city_heatmap"]
        assert "NYC" in d["source_reliability"]


# ── #81 balance-history range parameter ──────────────────────────────────────


def test_balance_history_range_3mo_longer_than_default(tmp_path, monkeypatch):
    """?range=3mo returns a different (longer) slice than the default 50-point cap."""
    import json
    from datetime import UTC, datetime, timedelta

    import paper
    import web_app

    # Synthesise 100 history points spanning 120 days
    now = datetime.now(UTC)
    fake_history = [
        {"ts": (now - timedelta(days=120 - i)).isoformat(), "balance": 1000.0 + i}
        for i in range(100)
    ]
    last_bal = fake_history[-1]["balance"]
    monkeypatch.setattr(paper, "get_balance_history", lambda: fake_history)
    monkeypatch.setattr(web_app, "_now_utc", lambda: now)
    # Patch get_balance to match the last history point so the live-tail
    # synthetic append is skipped — this test is checking slicing, not the tail.
    monkeypatch.setattr(paper, "get_balance", lambda: last_bal)

    app = web_app._build_app(client=None)
    client = app.test_client()

    default_resp = client.get("/api/balance_history")
    range_resp = client.get("/api/balance_history?range=3mo")

    default_data = json.loads(default_resp.data)
    range_data = json.loads(range_resp.data)

    # default is capped at 50; 3mo should include more points (≥ 75 of the 100)
    assert default_resp.status_code == 200
    assert range_resp.status_code == 200
    assert len(default_data["values"]) == 50
    assert len(range_data["values"]) > 50


# ── #84 model attribution endpoint ───────────────────────────────────────────


def test_model_attribution_endpoint_returns_city_keys(monkeypatch):
    """GET /api/model-attribution returns JSON with at least one city key,
    each city mapping to a dict of source weights."""
    import json

    import web_app

    fake_attribution = {
        "Chicago": {"ensemble": 0.6, "nws": 0.25, "climatology": 0.15},
        "Dallas": {"ensemble": 0.5, "nws": 0.35, "climatology": 0.15},
    }

    import tracker

    monkeypatch.setattr(
        tracker, "get_model_attribution_by_city", lambda: fake_attribution
    )

    app = web_app._build_app(client=None)
    client = app.test_client()

    resp = client.get("/api/model-attribution")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert isinstance(data, dict)
    assert len(data) >= 1
    first_city = next(iter(data.values()))
    assert isinstance(first_city, dict)
    assert "ensemble" in first_city


# ── #85 per-market SSE stream ─────────────────────────────────────────────────


def test_stream_markets_content_type(monkeypatch):
    """GET /api/stream/markets returns Content-Type: text/event-stream."""
    import time

    import web_app

    # Patch sleep so the generator yields once then stops
    monkeypatch.setattr(time, "sleep", lambda _: (_ for _ in ()).throw(StopIteration()))

    app = web_app._build_app(client=None)
    client = app.test_client()

    resp = client.get("/api/stream/markets")
    assert "text/event-stream" in resp.content_type


# ── #65 price-improvement endpoint ───────────────────────────────────────────


def test_price_improvement_endpoint_returns_valid_json(monkeypatch):
    """GET /api/price-improvement returns JSON with avg_improvement_cents and total_trades."""
    import json

    import tracker
    import web_app

    monkeypatch.setattr(
        tracker,
        "get_price_improvement_stats",
        lambda: {"mean": 0.02, "median": 0.015, "count": 12, "positive_pct": 0.75},
    )

    app = web_app._build_app(client=None)
    client = app.test_client()

    resp = client.get("/api/price-improvement")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "avg_improvement_cents" in data
    assert "total_trades" in data
    assert isinstance(data["total_trades"], int)


# ── Phase 3: kill-switch API endpoints ───────────────────────────────────────


class TestKillSwitchAPI:
    def test_halt_creates_kill_switch_file(self, tmp_path, monkeypatch):
        """POST /api/halt writes the kill-switch file with reason and timestamp."""
        import json as _json

        import web_app

        ks_path = tmp_path / ".kill_switch"
        monkeypatch.setattr(web_app, "_KS_PATH", ks_path)

        app = web_app._build_app(client=None)
        app.config["TESTING"] = True

        with app.test_client() as c:
            resp = c.post(
                "/api/halt",
                json={"reason": "test halt"},
                content_type="application/json",
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["halted"] is True
        assert data["reason"] == "test halt"
        assert ks_path.exists()
        payload = _json.loads(ks_path.read_text())
        assert payload["reason"] == "test halt"
        assert "halted_at" in payload

    def test_halt_no_leftover_tmp_file(self, tmp_path, monkeypatch):
        """P1-16: atomic write must not leave a .tmp file after successful halt."""
        import web_app

        ks_path = tmp_path / ".kill_switch"
        monkeypatch.setattr(web_app, "_KS_PATH", ks_path)

        app = web_app._build_app(client=None)
        app.config["TESTING"] = True

        with app.test_client() as c:
            c.post(
                "/api/halt",
                json={"reason": "atomic test"},
                content_type="application/json",
            )

        tmp_file = ks_path.with_suffix(".tmp")
        assert not tmp_file.exists(), "Atomic write must not leave a .tmp file behind"
        assert ks_path.exists(), "Kill switch file must exist after halt"

    def test_halt_no_leftover_temp_files_at_all(self, tmp_path, monkeypatch):
        """AUD batch-25 item 4: after switching to safe_io.atomic_write_json,
        confirm no stray temp file of ANY name (its own pid/thread/attempt-
        keyed scheme, not just the old `.kill_switch.tmp`) is left behind
        in the kill-switch file's directory."""
        import web_app

        ks_path = tmp_path / ".kill_switch"
        monkeypatch.setattr(web_app, "_KS_PATH", ks_path)

        app = web_app._build_app(client=None)
        app.config["TESTING"] = True

        with app.test_client() as c:
            c.post(
                "/api/halt",
                json={"reason": "atomic test"},
                content_type="application/json",
            )

        # Other autouse fixtures share this same tmp_path for unrelated
        # state (circuit breaker, tracker db) -- scope the check to files
        # that look like a temp artifact of *this* write (anything besides
        # the final .kill_switch file whose name starts with a dot and
        # mentions "kill_switch" or ends in .tmp).
        leftover = [
            p
            for p in tmp_path.iterdir()
            if p != ks_path and ("kill_switch" in p.name or p.suffix == ".tmp")
        ]
        assert leftover == [], f"stray temp file(s) left behind: {leftover}"

    def test_halt_retries_transient_permission_error_then_succeeds(
        self, tmp_path, monkeypatch
    ):
        """AUD batch-25 item 4: api_halt's write used to be a bare
        Path.replace() with no retry -- a transient Windows sharing
        violation (any concurrent reader of .kill_switch, which this
        codebase guarantees: cron/watch/this dashboard's own /health and
        /api/status polling) would raise straight through to an unhandled
        500 while the kill switch was NOT actually installed. Routing
        through safe_io.atomic_write_json gets the same bounded retry
        every other atomic write in this codebase gets.

        Mutation check: reverting api_halt to `_tmp.replace(_KS_PATH)`
        makes this test fail -- a bare Path.replace() doesn't retry, so
        the first simulated PermissionError would propagate as an
        unhandled 500 instead of the halt succeeding after retry.
        """
        import os

        import web_app

        ks_path = tmp_path / ".kill_switch"
        monkeypatch.setattr(web_app, "_KS_PATH", ks_path)

        real_replace = os.replace
        call_count = {"n": 0}

        def _flaky_replace(src, dst):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise PermissionError(
                    "[WinError 5] Access is denied (simulated concurrent reader)"
                )
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", _flaky_replace)

        app = web_app._build_app(client=None)
        app.config["TESTING"] = True

        with app.test_client() as c:
            resp = c.post(
                "/api/halt",
                json={"reason": "retry test"},
                content_type="application/json",
            )

        assert resp.status_code == 200
        assert resp.get_json()["halted"] is True
        assert call_count["n"] == 2, (
            "expected exactly one retry after the transient failure"
        )
        assert ks_path.exists()

    def test_halt_returns_500_json_when_write_totally_fails(
        self, tmp_path, monkeypatch
    ):
        """AUD batch-25 item 4: when every retry is exhausted, api_halt must
        return a JSON 500 (matching every other error-handling route in
        this file), not an unhandled exception / Flask's raw HTML 500
        page."""
        import os
        import time

        import safe_io
        import web_app

        ks_path = tmp_path / ".kill_switch"
        monkeypatch.setattr(web_app, "_KS_PATH", ks_path)
        # project_root() default emergency-copy fallback would otherwise
        # try to write into this repo's real data/.emergency/ -- isolate it.
        monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)
        monkeypatch.setattr(time, "sleep", lambda _secs: None)

        def _always_fail(src, dst):
            raise OSError("simulated persistent disk error")

        monkeypatch.setattr(os, "replace", _always_fail)

        app = web_app._build_app(client=None)
        app.config["TESTING"] = True

        with app.test_client() as c:
            resp = c.post(
                "/api/halt",
                json={"reason": "total failure test"},
                content_type="application/json",
            )

        assert resp.status_code == 500
        assert "error" in resp.get_json()
        assert not ks_path.exists()

    def test_halt_does_not_collide_with_cron_override_parked_kill_switch(
        self, tmp_path, monkeypatch
    ):
        """AUD batch-25 item 4: main.py's cmd_cron manual-override flow
        parks the ACTIVE kill switch at the literal filename
        `.kill_switch.tmp` for the duration of a one-shot override (see
        main.py's `_kill_tmp = _kill_path.with_name(".kill_switch.tmp")`).
        The old `_KS_PATH.with_suffix(".tmp")` write in api_halt produced
        that exact same filename, so a halt request arriving mid-override
        could overwrite the parked state. atomic_write_json's temp names
        are pid/thread/attempt-keyed (never a fixed name), so this can't
        happen anymore -- verified by pre-creating that exact filename
        (simulating an in-progress override) and confirming api_halt
        leaves it untouched.
        """
        import web_app

        ks_path = tmp_path / ".kill_switch"
        monkeypatch.setattr(web_app, "_KS_PATH", ks_path)

        parked_override_file = ks_path.with_name(".kill_switch.tmp")
        parked_override_file.write_text('{"reason": "parked by cron override"}')

        app = web_app._build_app(client=None)
        app.config["TESTING"] = True

        with app.test_client() as c:
            resp = c.post(
                "/api/halt",
                json={"reason": "halt during override window"},
                content_type="application/json",
            )

        assert resp.status_code == 200
        # The parked override file must be untouched -- still exists with
        # its original content, not overwritten or consumed by the halt.
        assert parked_override_file.exists()
        assert (
            parked_override_file.read_text() == '{"reason": "parked by cron override"}'
        )
        assert ks_path.exists()

    def test_resume_removes_kill_switch_file(self, tmp_path, monkeypatch):
        """POST /api/resume removes the kill-switch file."""
        import web_app

        ks_path = tmp_path / ".kill_switch"
        ks_path.write_text('{"reason":"test"}')
        monkeypatch.setattr(web_app, "_KS_PATH", ks_path)

        app = web_app._build_app(client=None)
        app.config["TESTING"] = True

        with app.test_client() as c:
            resp = c.post("/api/resume")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["resumed"] is True
        assert data["was_halted"] is True
        assert not ks_path.exists()

    def test_resume_also_clears_override_parked_kill_switch(
        self, tmp_path, monkeypatch
    ):
        """AUD batch-25 opus-review M5: during a main.py cmd_cron manual
        override window, the kill switch is parked at `.kill_switch.tmp`
        (not `.kill_switch` itself). /api/resume must clear that parked
        copy too -- otherwise resuming mid-override looks like a no-op
        (was_halted reads False) and the kill switch silently re-arms
        itself the moment the in-flight override finishes.

        Mutation check: reverting api_resume to only check/unlink
        `_KS_PATH` makes this test fail -- the parked file survives and
        `was_halted` incorrectly reads False.
        """
        import web_app

        ks_path = tmp_path / ".kill_switch"
        monkeypatch.setattr(web_app, "_KS_PATH", ks_path)
        # .kill_switch itself does NOT exist -- it's parked mid-override.
        parked = tmp_path / ".kill_switch.tmp"
        parked.write_text('{"reason": "parked by cron override"}')

        app = web_app._build_app(client=None)
        app.config["TESTING"] = True

        with app.test_client() as c:
            resp = c.post("/api/resume")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["resumed"] is True
        assert data["was_halted"] is True
        assert not parked.exists(), (
            "the parked override copy must be cleared, or the kill switch "
            "re-arms itself when the override cycle finishes"
        )

    def test_resume_survives_kill_switch_removed_between_exists_and_unlink(
        self, tmp_path, monkeypatch
    ):
        """batch-34 item 2 (M-7): if the kill-switch file disappears between
        api_resume's `exists()` check and its `unlink()` call -- e.g.
        main.py's cmd_cron manual-override flow parking (renaming away) the
        file mid-request -- the bare unlink() used to raise an unhandled
        FileNotFoundError, crashing the request BEFORE the parked-copy
        cleanup below ran. That let the kill switch silently re-arm once
        the override window ended even though the operator explicitly
        resumed -- reopening exactly the race batch-25's own M5 fix (the
        parked-unlink 15 lines below, which already has missing_ok=True)
        was written to prevent.

        Simulates the race with a fake Path whose exists() always reports
        True (matching the check having already passed) while unlink()
        raises FileNotFoundError unless missing_ok=True -- deterministic,
        without depending on real filesystem timing.

        Mutation check: reverting api_resume's unlink() to drop
        missing_ok=True makes this test fail (an unhandled FileNotFoundError
        propagates instead of a clean 200).
        """
        import web_app

        real_ks_path = tmp_path / ".kill_switch"

        class _RaceSimPath:
            name = real_ks_path.name

            def exists(self):
                return True

            def unlink(self, missing_ok=False):
                if not missing_ok:
                    raise FileNotFoundError(
                        "simulated race: file removed before unlink()"
                    )

            def with_name(self, name):
                # The parked-copy path genuinely doesn't exist in this test
                # -- only the primary kill-switch unlink is under test here.
                return real_ks_path.with_name(name)

        monkeypatch.setattr(web_app, "_KS_PATH", _RaceSimPath())

        app = web_app._build_app(client=None)
        app.config["TESTING"] = True

        with app.test_client() as c:
            resp = c.post("/api/resume")

        assert resp.status_code == 200, (
            f"unlink() race must not crash the request: {resp.status_code} "
            f"{resp.get_data(as_text=True)[:300]}"
        )
        data = resp.get_json()
        assert data["resumed"] is True
        assert data["was_halted"] is True

    def test_status_includes_kill_switch_active(self, tmp_path, monkeypatch):
        """GET /api/status includes kill_switch_active field (False when no file)."""
        import web_app

        ks_path = tmp_path / ".kill_switch"
        monkeypatch.setattr(web_app, "_KS_PATH", ks_path)

        app = web_app._build_app(client=None)
        app.config["TESTING"] = True

        with app.test_client() as c:
            with (
                patch("paper.get_balance", return_value=1000.0),
                patch("paper.get_open_trades", return_value=[]),
                patch("tracker.brier_score", return_value=0.10),
                patch("paper.fear_greed_index", return_value=(50, "Neutral")),
            ):
                resp = c.get("/api/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "kill_switch_active" in data
        assert data["kill_switch_active"] is False


class TestManualOverrideAPIWriteReliability:
    """AUD batch-25 item 4: api_override_set() had the identical bare
    Path.replace() reliability gap as api_halt above."""

    def test_override_set_retries_transient_permission_error(
        self, tmp_path, monkeypatch
    ):
        """Mutation check: reverting api_override_set to
        `_tmp.replace(_ov_path)` makes this test fail -- a bare
        Path.replace() doesn't retry a transient PermissionError."""
        import os

        import paths
        import web_app

        ov_path = tmp_path / "manual_override.json"
        monkeypatch.setattr(paths, "MANUAL_OVERRIDE_PATH", ov_path)

        real_replace = os.replace
        call_count = {"n": 0}

        def _flaky_replace(src, dst):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise PermissionError("[WinError 5] simulated concurrent reader")
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", _flaky_replace)

        app = web_app._build_app(client=None)
        app.config["TESTING"] = True

        with app.test_client() as c:
            resp = c.post(
                "/api/override",
                json={"reason": "retry test", "duration_minutes": 30},
                content_type="application/json",
            )

        assert resp.status_code == 200
        assert resp.get_json()["set"] is True
        assert call_count["n"] == 2
        assert ov_path.exists()

    def test_override_set_returns_500_json_when_write_totally_fails(
        self, tmp_path, monkeypatch
    ):
        import os
        import time

        import paths
        import safe_io
        import web_app

        ov_path = tmp_path / "manual_override.json"
        monkeypatch.setattr(paths, "MANUAL_OVERRIDE_PATH", ov_path)
        monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)
        monkeypatch.setattr(time, "sleep", lambda _secs: None)

        def _always_fail(src, dst):
            raise OSError("simulated persistent disk error")

        monkeypatch.setattr(os, "replace", _always_fail)

        app = web_app._build_app(client=None)
        app.config["TESTING"] = True

        with app.test_client() as c:
            resp = c.post(
                "/api/override",
                json={"reason": "total failure test", "duration_minutes": 30},
                content_type="application/json",
            )

        assert resp.status_code == 500
        assert "error" in resp.get_json()
        assert not ov_path.exists()


class TestOverrideClearRaceAndErrorHandling:
    """batch-34 item 2 (M-7): api_override_clear had the identical bare
    exists()/unlink() TOCTOU pattern as api_resume, racing cron's own
    expiry auto-clear of the same file (main.py's manual-override poll)."""

    def test_clear_survives_override_file_removed_between_exists_and_unlink(
        self, monkeypatch
    ):
        """If the manual-override file disappears between the exists()
        check and unlink() -- e.g. cron's own expiry auto-clear winning the
        race -- the request must still succeed, not raise an unhandled
        FileNotFoundError.

        Mutation check: reverting api_override_clear's unlink() to drop
        missing_ok=True makes this test fail (500, not 200)."""
        import paths
        import web_app

        class _RaceSimPath:
            def exists(self):
                return True

            def unlink(self, missing_ok=False):
                if not missing_ok:
                    raise FileNotFoundError(
                        "simulated race: file removed before unlink()"
                    )

        # api_override_clear does `from paths import MANUAL_OVERRIDE_PATH`
        # fresh on every call, so patching the paths module attribute (not
        # web_app) is what actually takes effect -- unlike _KS_PATH, which
        # web_app binds once at import time.
        monkeypatch.setattr(paths, "MANUAL_OVERRIDE_PATH", _RaceSimPath())

        app = web_app._build_app(client=None)
        app.config["TESTING"] = True

        with app.test_client() as c:
            resp = c.delete("/api/override")

        assert resp.status_code == 200, (
            f"unlink() race must not crash the request: {resp.status_code} "
            f"{resp.get_data(as_text=True)[:300]}"
        )
        data = resp.get_json()
        assert data["cleared"] is True
        assert data["was_active"] is True

    def test_clear_returns_json_500_on_unexpected_unlink_error(self, monkeypatch):
        """A non-race OSError (e.g. a permission failure) during unlink()
        must return this route's own JSON error shape, not propagate as
        Flask's raw HTML 500 page -- matches every other route in this
        file.

        Mutation check: reverting api_override_clear to a bare
        `_ov_path.unlink()` with no try/except makes this test fail (the
        response is Flask's default HTML error page, not JSON with an
        "error" key)."""
        import paths
        import web_app

        class _PermissionFailPath:
            def exists(self):
                return True

            def unlink(self, missing_ok=False):
                raise PermissionError("simulated permission denied")

        monkeypatch.setattr(paths, "MANUAL_OVERRIDE_PATH", _PermissionFailPath())

        app = web_app._build_app(client=None)
        app.config["TESTING"] = True

        with app.test_client() as c:
            resp = c.delete("/api/override")

        assert resp.status_code == 500
        assert "error" in resp.get_json()


def test_status_includes_brier_drift(tmp_path, monkeypatch):
    """GET /api/status includes brier_drift key with drifting field."""
    import web_app

    ks_path = tmp_path / ".kill_switch"
    monkeypatch.setattr(web_app, "_KS_PATH", ks_path)

    app = web_app._build_app(client=None)
    app.config["TESTING"] = True

    fake_drift = {"drifting": True, "message": "drift detected", "delta": 0.08}

    with app.test_client() as c:
        with (
            patch("paper.get_balance", return_value=1000.0),
            patch("paper.get_open_trades", return_value=[]),
            patch("tracker.brier_score", return_value=0.10),
            patch("paper.fear_greed_index", return_value=(50, "Neutral")),
            patch("tracker.detect_brier_drift", return_value=fake_drift),
        ):
            resp = c.get("/api/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "brier_drift" in data
    assert data["brier_drift"]["drifting"] is True


class TestPaperOrderCityDateServerDerived:
    """Deep-review followup: /api/paper-order used to take city/target_date
    straight from the client-supplied JSON body -- a request that omitted
    them (or a buggy/malicious client) bypassed the city/date, directional,
    and correlated exposure caps entirely, and the saved trade record got
    whatever the client sent. Both must now come from the ticker via a
    server-side market lookup instead."""

    def test_exposure_cap_still_enforced_when_body_omits_city_and_date(
        self, client, tmp_path, monkeypatch
    ):
        """Omitting city/target_date from the request body must NOT bypass
        the exposure caps -- they're derived server-side regardless."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch("kalshi_client.KalshiClient") as mock_kc_cls,
            patch(
                "weather_markets.enrich_with_forecast",
                # A future date -- batch-34 item 7d now rejects orders whose
                # server-derived target_date is already in the past, so this
                # (unrelated to days_out) test must stay clear of "today".
                return_value={"_city": "NYC", "_date": date(2099, 6, 1)},
            ),
            patch("paper.check_position_limits") as mock_cpl,
            patch("paper.place_paper_order") as mock_place,
        ):
            mock_kc_cls.return_value.get_market.return_value = {
                "close_time": "2099-01-01T00:00:00Z"
            }
            mock_cpl.return_value = {"ok": False, "reason": "city/date cap exceeded"}

            resp = client.post(
                "/api/paper-order",
                json={
                    "ticker": "KXHIGH-25JUN01-T70",
                    "side": "yes",
                    "quantity": 10,
                    "entry_price": 0.50,
                    # city/target_date deliberately omitted
                },
            )

        assert resp.status_code == 400
        mock_place.assert_not_called()
        assert mock_cpl.called, (
            "check_position_limits must still run -- server-derived city/date "
            "must not be skipped just because the request body omitted them"
        )
        _, cpl_kwargs = mock_cpl.call_args
        assert cpl_kwargs["city"] == "NYC"

    def test_client_supplied_city_is_ignored_server_value_used(
        self, client, tmp_path, monkeypatch
    ):
        """A client-supplied city/target_date that disagrees with the
        ticker's real city must be ignored, not trusted -- both the
        exposure check and the saved trade record must use the
        server-derived value."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch("kalshi_client.KalshiClient") as mock_kc_cls,
            patch(
                "weather_markets.enrich_with_forecast",
                # See the future-date comment on the sibling test above.
                return_value={"_city": "Chicago", "_date": date(2099, 6, 1)},
            ),
            patch("paper.check_position_limits", return_value={"ok": True}) as mock_cpl,
            patch("paper.place_paper_order") as mock_place,
        ):
            mock_kc_cls.return_value.get_market.return_value = {
                "close_time": "2099-01-01T00:00:00Z"
            }
            mock_place.return_value = {"id": 1}

            resp = client.post(
                "/api/paper-order",
                json={
                    "ticker": "KXHIGH-25JUN01-T70",
                    "side": "yes",
                    "quantity": 10,
                    "entry_price": 0.50,
                    "city": "NotARealCity",
                    "target_date": "2099-12-31",
                },
            )

        assert resp.status_code == 201
        _, cpl_kwargs = mock_cpl.call_args
        assert cpl_kwargs["city"] == "Chicago"
        _, place_kwargs = mock_place.call_args
        assert place_kwargs["city"] == "Chicago"


class TestPaperOrderDaysOutUsesCityLocalToday:
    """Opus-review-caught adjacency finding (AUD-0044/45/46, batch-07):
    /api/paper-order's server-derived days_out used utils.utc_today() against
    _tdate_dash -- the same CITY-LOCAL date weather_markets.enrich_with_forecast
    returns (analyze_trade's own value post-0100bffe) -- the identical
    UTC-vs-city-local mismatch this batch's other 4 fixes address, just not
    display-only: days_out feeds order_executor's multi-day slot cap directly.
    Fixed to compute city-local today via ZoneInfo, matching the rest of this
    fix chain."""

    def test_days_out_computed_from_city_local_today_not_utc(
        self, client, tmp_path, monkeypatch
    ):
        """At 2026-07-10 05:00 UTC, NYC (EDT) has already rolled to 07-10 but
        LA (PDT) is still 07-09. For an LA market with target_date 07-11:
        UTC-anchored days_out would be (07-11 - UTC-today 07-10).days = 1;
        the fixed, LA-local-anchored value is (07-11 - LA-local-today
        07-09).days = 2. A regression back to utc_today() would under-count
        days_out by 1 and let a multi-day LA trade masquerade as a 1-day-out
        trade in the multi-day slot cap's own bucketing.

        Opus-review-caught (round 2): utils.utc_today is also mocked here so
        the mutation-kill value is deterministic (1) regardless of the real
        system clock -- without it, the "UTC-anchored" mutation's actual
        wrong answer is whatever max(0, (07-11 - REAL_TODAY).days) clamps to,
        which is 0 on most days this test could run, not 1 as originally
        (incorrectly) documented here."""
        from datetime import UTC, date, datetime

        import web_app

        fixed_instant = datetime(2026, 7, 10, 5, 0, tzinfo=UTC)

        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return fixed_instant.replace(tzinfo=None)
                return fixed_instant.astimezone(tz)

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch("kalshi_client.KalshiClient") as mock_kc_cls,
            patch(
                "weather_markets.enrich_with_forecast",
                return_value={"_city": "LA", "_date": date(2026, 7, 11)},
            ),
            patch("paper.check_position_limits", return_value={"ok": True}),
            patch("paper.place_paper_order") as mock_place,
            patch("tracker.log_prediction") as mock_log_pred,
            patch("web_app.datetime", _FixedDatetime),
            patch("utils.utc_today", return_value=date(2026, 7, 10)),
        ):
            mock_kc_cls.return_value.get_market.return_value = {
                "close_time": "2099-01-01T00:00:00Z"
            }
            mock_place.return_value = {"id": 1}

            resp = client.post(
                "/api/paper-order",
                json={
                    "ticker": "KXHIGH-25JUL11-T70",
                    "side": "yes",
                    "quantity": 10,
                    "entry_price": 0.50,
                },
            )

        assert resp.status_code == 201
        _, place_kwargs = mock_place.call_args
        assert place_kwargs["days_out"] == 2

        # Opus-review-caught (round 2): log_prediction's analysis dict used
        # to omit "days_out" entirely, so tracker.log_prediction recomputed
        # its own value via market_date - utc_today() -- a fresh split-brain
        # against place_paper_order's city-local-anchored value above, for
        # the identical trade, in the identical evening window this batch's
        # other fixes exist to remove. Both must agree.
        log_pred_args, _ = mock_log_pred.call_args
        analysis_dict = log_pred_args[3]
        assert analysis_dict["days_out"] == place_kwargs["days_out"] == 2


class TestPaperOrderNoSideEndToEnd:
    """batch-26 item 1: the dashboard's Approve action (App.jsx's
    buildPaperOrderBody) sends entry_price flipped to side-space for a NO
    recommendation (1 - yes_bid) but entry_prob left in YES-space, matching
    web_app.py's WA-inversion comment's documented contract for entry_price
    ("the price PAID for the requested SIDE") while preserving entry_prob's
    existing YES-space storage convention (tracker Brier scoring,
    order_executor's model-reversal exit shift, paper.py's pnl_attribution
    all read it that way -- opus review caught an earlier draft of this fix
    flipping entry_prob too, which would have corrupted calibration data for
    every NO approval). Before the fix, the frontend sent the raw YES-space
    market_prob unconditionally for entry_price too: kelly_fraction(P_yes,
    yes_price) is exactly 0.0 for a genuine NO recommendation (P_yes <
    market_prob by construction whenever the model recommends NO), so the
    Kelly cap zeroed the quantity and the server rejected with a misleading
    "no edge" 400 for every NO approval -- real edge, wrong space. This
    proves the fixed payload shape now reaches place_paper_order end to
    end: not rejected, booked at the correct NO-side price, AND with
    entry_prob stored unflipped (YES-space)."""

    def test_no_side_signal_with_positive_edge_is_accepted_and_priced_correctly(
        self, client, tmp_path, monkeypatch
    ):
        """A NO signal with genuine edge, sent with the post-fix payload
        shape (entry_price side-flipped, entry_prob YES-space), must be
        accepted (not 400'd by the Kelly cap), reach place_paper_order at
        the NO-side price (1 - yes_bid, not the YES-side price), AND store
        entry_prob unflipped (YES-space) -- not the side-space value the
        Kelly-cap check internally derives from it."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch("kalshi_client.KalshiClient") as mock_kc_cls,
            patch(
                "weather_markets.enrich_with_forecast",
                # A future date -- batch-34 item 7d now rejects orders whose
                # server-derived target_date is already in the past.
                return_value={"_city": "NYC", "_date": date(2099, 8, 22)},
            ),
            patch("paper.check_position_limits", return_value={"ok": True}) as mock_cpl,
            patch("paper.place_paper_order") as mock_place,
            patch("tracker.log_prediction") as mock_log_pred,
        ):
            # Real market: yes_bid=54c, yes_ask=56c -> NO-side ask (no_ask)
            # = 1 - 0.54 = 0.46. weather_markets.parse_market_price (NOT
            # mocked) runs for real on this dict inside the route.
            mock_kc_cls.return_value.get_market.return_value = {
                "yes_bid": 54,
                "yes_ask": 56,
                "close_time": "2099-01-01T00:00:00Z",
            }
            mock_place.return_value = {"id": 1, "cost": 2.30}

            # Model thinks YES is only 30% likely (entry_prob stays
            # YES-space on the wire, per buildPaperOrderBody's post-review
            # contract) -> the route's own Kelly-cap check converts this to
            # NO-space internally (1 - 0.30 = 0.70), well above the 0.46 NO
            # price: real positive edge, exactly the buildPaperOrderBody
            # NO-branch output shape.
            resp = client.post(
                "/api/paper-order",
                json={
                    "ticker": "KXHIGH-26AUG22-T80",
                    "side": "no",
                    "quantity": 5,
                    "entry_price": 0.46,
                    "entry_prob": 0.30,
                    "net_edge": 0.25,
                },
            )

        assert resp.status_code == 201, (
            f"NO signal with real edge must be accepted, got {resp.status_code}: "
            f"{resp.get_json()}"
        )
        assert mock_cpl.called
        assert mock_place.called
        _, place_kwargs = mock_place.call_args
        assert place_kwargs["side"] == "no"
        # Booked at the NO-side price (1 - yes_bid), not the YES-side
        # market_prob/yes_ask -- the exact wrong-price failure mode this
        # test guards against.
        assert place_kwargs["entry_price"] == pytest.approx(0.46)
        assert place_kwargs["entry_price"] != pytest.approx(0.56)
        # entry_prob must be stored UNFLIPPED (YES-space, 0.30) -- not the
        # side-space value (0.70) the Kelly-cap check derives internally.
        # Storing the flipped value would corrupt tracker's Brier/
        # calibration scoring for every NO trade (opus-review-caught).
        assert place_kwargs["entry_prob"] == pytest.approx(0.30)
        assert place_kwargs["entry_prob"] != pytest.approx(0.70)
        # log_prediction's forecast_prob must match (same YES-space value,
        # not independently re-derived or re-flipped).
        assert mock_log_pred.called
        log_pred_args, _ = mock_log_pred.call_args
        assert log_pred_args[3]["forecast_prob"] == pytest.approx(0.30)
        # Quantity must not have been zeroed by the Kelly cap -- the
        # as-shipped bug's exact symptom (real edge computing kelly=0.0).
        # check_position_limits(ticker, quantity, entry_price, ...) --
        # quantity is the 2nd positional arg.
        cpl_call_quantity = mock_cpl.call_args.args[1]
        assert cpl_call_quantity > 0, (
            "quantity must not be clamped to 0 by the Kelly cap when the "
            "NO-space edge is genuinely positive"
        )

    def test_yes_space_payload_for_a_no_order_is_rejected_not_silently_mispriced(
        self, client, tmp_path, monkeypatch
    ):
        """Documents the pre-fix failure mode for contrast: if a client
        (a stale frontend build, a bug regression) sends the raw YES-space
        market_prob as entry_price for a NO order, the server's existing
        WA-security deviation guard must reject it rather than booking the
        wrong-side price -- this is the defense-in-depth this fix does NOT
        remove or weaken."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch("kalshi_client.KalshiClient") as mock_kc_cls,
            patch(
                "weather_markets.enrich_with_forecast",
                # A future date -- must be rejected by the price-deviation
                # guard this test targets, not batch-34 item 7d's separate
                # past-target_date guard.
                return_value={"_city": "NYC", "_date": date(2099, 8, 22)},
            ),
            patch("paper.place_paper_order") as mock_place,
        ):
            # A market further from 50/50 (yes_bid=75c/yes_ask=78c) so the
            # wrong-side price deviates well past the guard's 0.15
            # threshold: correct NO price is 1-0.75=0.25, but a stale/buggy
            # client sending the raw YES price (0.77) deviates by 0.52.
            # (A near-50/50 market's wrong-side price can coincidentally
            # fall within 0.15 of the correct side-space price and slip
            # past this guard -- a pre-existing, narrower residual gap in
            # the deviation guard's own tolerance, not something this
            # batch's fix introduces or is scoped to close.)
            mock_kc_cls.return_value.get_market.return_value = {
                "yes_bid": 75,
                "yes_ask": 78,
                "close_time": "2099-01-01T00:00:00Z",
            }

            resp = client.post(
                "/api/paper-order",
                json={
                    "ticker": "KXHIGH-26AUG22-T80",
                    "side": "no",
                    "quantity": 5,
                    # The as-shipped bug's exact payload: raw YES-space
                    # market_prob sent unconditionally as entry_price for a
                    # NO order.
                    "entry_price": 0.77,
                    "entry_prob": 0.20,
                },
            )

        assert resp.status_code == 400
        mock_place.assert_not_called()


class TestPaperOrderWebSweepL17:
    """batch-34 item 7 (L-17): same-file low-severity sweep of
    /api/paper-order alongside items 2/7b-d's shared route."""

    def test_kill_switch_check_reads_the_unified_ks_path(
        self, client, tmp_path, monkeypatch
    ):
        """item 7b: was `from cron import KILL_SWITCH_PATH` while every
        sibling route reads the module-level _KS_PATH -- a monkeypatch
        blind spot (a test/tool patching one binding doesn't affect the
        other, even though both start out as the same underlying
        paths.KILL_SWITCH_PATH object). Engage the switch via _KS_PATH (the
        unified reference every other route already uses) and confirm this
        route actually honors it.

        Mutation check: reverting to `from cron import KILL_SWITCH_PATH`
        makes this test fail -- the route would instead check the real
        production kill-switch path (untouched by this test's monkeypatch,
        and normally absent in a test environment), so the order would
        proceed past the kill-switch check instead of getting a 503."""
        import web_app

        ks_path = tmp_path / ".kill_switch"
        ks_path.write_text('{"reason": "engaged"}')
        monkeypatch.setattr(web_app, "_KS_PATH", ks_path)

        resp = client.post(
            "/api/paper-order",
            json={
                "ticker": "KXHIGH-99JAN01-T70",
                "side": "yes",
                "quantity": 1,
                "entry_price": 0.50,
            },
        )
        assert resp.status_code == 503
        assert "kill switch" in resp.get_json()["error"].lower()

    def test_non_numeric_quantity_does_not_500(self, client, tmp_path, monkeypatch):
        """item 7a: `quantity = int(body.get("quantity", 1)) or 1` used to
        sit outside any try -- a non-numeric quantity raised an unhandled
        ValueError, returning Flask's raw HTML 500 page instead of this
        route's usual JSON error shape (matches the file's own
        WA-input-validation pattern, e.g. /history's ?n=abc coercion).

        Mutation check: reverting to the bare (un-try'd) int() cast makes
        this test fail -- Flask's TESTING mode propagates the unhandled
        ValueError instead of a clean response."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch("kalshi_client.KalshiClient") as mock_kc_cls,
            patch(
                "weather_markets.enrich_with_forecast",
                return_value={"_city": "NYC", "_date": date(2099, 1, 1)},
            ),
            patch("paper.check_position_limits", return_value={"ok": True}),
            patch("paper.place_paper_order") as mock_place,
        ):
            mock_kc_cls.return_value.get_market.return_value = {
                "close_time": "2099-01-01T00:00:00Z"
            }
            mock_place.return_value = {"id": 1}
            resp = client.post(
                "/api/paper-order",
                json={
                    "ticker": "KXHIGH-99JAN01-T70",
                    "side": "yes",
                    "quantity": "not-a-number",
                    "entry_price": 0.50,
                },
            )
        assert resp.status_code in (200, 201), (
            f"non-numeric quantity must not crash the request: "
            f"{resp.status_code} {resp.get_data(as_text=True)[:300]}"
        )
        # Falls back to the documented default (1), same as an omitted
        # quantity -- not silently dropped or left unbounded.
        _, place_kwargs = mock_place.call_args
        assert place_kwargs["quantity"] == 1

    def test_no_side_order_rejected_at_yes_bid_one_boundary(
        self, client, tmp_path, monkeypatch
    ):
        """item 7c: a NO order on a yes_bid==1.0 market has an expected
        NO-side price of exactly 0.0 (`max(0.0, round(1.0 - 1.0, 4))`) --
        the old `_expected_side_price > 0` guard skipped the deviation
        check entirely at this boundary, letting a NO order at ANY
        entry_price sail through unchecked (the guard was meant to skip a
        degraded/missing quote, but has_quote already gates on real quote
        data being present, so an expected price of exactly 0 here is a
        legitimate boundary, not missing data).

        Mutation check: restoring the `_expected_side_price > 0 and` guard
        makes this test fail (order accepted instead of rejected)."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch("kalshi_client.KalshiClient") as mock_kc_cls,
            patch(
                "weather_markets.enrich_with_forecast",
                return_value={"_city": "NYC", "_date": date(2099, 1, 1)},
            ),
            patch("paper.place_paper_order") as mock_place,
        ):
            # yes_bid=yes_ask=100c=$1.00 -> NO-side expected price
            # = 1 - 1.00 = 0.0 exactly.
            mock_kc_cls.return_value.get_market.return_value = {
                "yes_bid": 100,
                "yes_ask": 100,
                "close_time": "2099-01-01T00:00:00Z",
            }
            resp = client.post(
                "/api/paper-order",
                json={
                    "ticker": "KXHIGH-99JAN01-T70",
                    "side": "no",
                    "quantity": 1,
                    "entry_price": 0.99,
                },
            )
        assert resp.status_code == 400
        mock_place.assert_not_called()

    def test_past_target_date_rejected_not_clamped_to_same_day(
        self, client, tmp_path, monkeypatch
    ):
        """item 7d: a server-derived target_date already in the past (a
        stale/expired market, or a ticker-parse mismatch) used to have its
        negative raw days_out clamped to 0 via `max(0, ...)`, mislabeling a
        stale multi-day market as same-day and dodging the
        MAX_POSITIONS_PER_DATE multi-day slot cap this derivation feeds.
        Must reject instead.

        Mutation check: restoring `max(0, (_tdate_dash - _today_dash).days)`
        makes this test fail (order accepted with days_out=0 instead of
        rejected)."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch("kalshi_client.KalshiClient") as mock_kc_cls,
            patch(
                "weather_markets.enrich_with_forecast",
                # Far in the past relative to any plausible real clock.
                return_value={"_city": "NYC", "_date": date(2000, 1, 1)},
            ),
            patch("paper.check_position_limits", return_value={"ok": True}),
            patch("paper.place_paper_order") as mock_place,
        ):
            mock_kc_cls.return_value.get_market.return_value = {
                "close_time": "2099-01-01T00:00:00Z"
            }
            resp = client.post(
                "/api/paper-order",
                json={
                    "ticker": "KXHIGH-99JAN01-T70",
                    "side": "yes",
                    "quantity": 1,
                    "entry_price": 0.50,
                },
            )
        assert resp.status_code == 400
        assert "past" in resp.get_json()["error"].lower()
        mock_place.assert_not_called()


class TestPaperOrderPriceParseFailsClosedM10:
    """audit-M-10 (server half of C-1): parse_market_price used to share a
    try block with city/date derivation, with the price parse last -- a
    parse_market_price failure left city/target_date already bound (they're
    derived first), so the identity check below passed on their strength
    alone and the ±0.15 price deviation check was silently skipped instead
    of failing closed the same way the identity check already does."""

    def test_price_parse_failure_rejects_the_order(self, client, tmp_path, monkeypatch):
        """Mutation check: merging the price-parse try back into the
        city/date try (the pre-fix shape) makes this test fail -- the order
        would be accepted (201) instead of rejected (503), because city/
        target_date are already bound by the time parse_market_price raises
        so the `if not (city and target_date)` guard never fires."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch("kalshi_client.KalshiClient") as mock_kc_cls,
            patch(
                "weather_markets.enrich_with_forecast",
                return_value={"_city": "NYC", "_date": date(2099, 1, 1)},
            ),
            patch(
                "weather_markets.parse_market_price",
                side_effect=Exception("malformed market payload"),
            ),
            patch("paper.check_position_limits") as mock_cpl,
            patch("paper.place_paper_order") as mock_place,
        ):
            mock_kc_cls.return_value.get_market.return_value = {
                "close_time": "2099-01-01T00:00:00Z"
            }
            resp = client.post(
                "/api/paper-order",
                json={
                    "ticker": "KXHIGH-99JAN01-T70",
                    "side": "yes",
                    "quantity": 1,
                    "entry_price": 0.50,
                },
            )

        assert resp.status_code == 503
        assert "price" in resp.get_json()["error"].lower()
        mock_place.assert_not_called()
        mock_cpl.assert_not_called()

    def test_price_parse_success_still_places_normally(
        self, client, tmp_path, monkeypatch
    ):
        """Positive control: proves splitting the try block into two didn't
        break the ordinary successful path -- when parse_market_price
        succeeds, the order still proceeds exactly as before."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch("kalshi_client.KalshiClient") as mock_kc_cls,
            patch(
                "weather_markets.enrich_with_forecast",
                return_value={"_city": "NYC", "_date": date(2099, 1, 1)},
            ),
            patch("paper.check_position_limits", return_value={"ok": True}),
            patch("paper.place_paper_order") as mock_place,
        ):
            mock_kc_cls.return_value.get_market.return_value = {
                "yes_bid": 48,
                "yes_ask": 52,
                "close_time": "2099-01-01T00:00:00Z",
            }
            mock_place.return_value = {"id": 1}
            resp = client.post(
                "/api/paper-order",
                json={
                    "ticker": "KXHIGH-99JAN01-T70",
                    "side": "yes",
                    "quantity": 1,
                    "entry_price": 0.52,
                },
            )

        assert resp.status_code == 201
        mock_place.assert_called_once()

    def test_enrich_failure_still_rejects_via_identity_check_unchanged(
        self, client, tmp_path, monkeypatch
    ):
        """Regression guard: a failure in the FIRST try block (city/date
        derivation itself) must still be caught by the existing identity
        check, unchanged by splitting the price parse into its own block."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch("kalshi_client.KalshiClient") as mock_kc_cls,
            patch(
                "weather_markets.enrich_with_forecast",
                side_effect=Exception("market lookup failed"),
            ),
            patch("paper.place_paper_order") as mock_place,
        ):
            mock_kc_cls.return_value.get_market.return_value = {
                "close_time": "2099-01-01T00:00:00Z"
            }
            resp = client.post(
                "/api/paper-order",
                json={
                    "ticker": "KXHIGH-99JAN01-T70",
                    "side": "yes",
                    "quantity": 1,
                    "entry_price": 0.50,
                },
            )

        assert resp.status_code == 503
        assert "market data" in resp.get_json()["error"].lower()
        mock_place.assert_not_called()


class TestClosePositionGatesM9:
    """audit-M-9 (server half of C-2): /api/close-position lacked the
    kill-switch/TRADING_PAUSED gates its sibling /api/paper-order has.
    ee22c44c widened its reachability with an operator-typed manual exit
    price that feeds straight into proceeds/pnl/balance -> drawdown tier,
    peak_balance, and graduation total_pnl, all without checking either
    gate -- and the missing gates were not separately tracked anywhere."""

    def test_kill_switch_blocks_close(self, client, tmp_path, monkeypatch):
        """Mutation check: removing the kill-switch check makes this test
        fail -- close_paper_early would run (200) instead of the request
        being rejected (503)."""
        import web_app

        ks_path = tmp_path / ".kill_switch"
        ks_path.write_text('{"reason": "engaged"}')
        monkeypatch.setattr(web_app, "_KS_PATH", ks_path)

        with patch("paper.close_paper_early") as mock_close:
            resp = client.post(
                "/api/close-position",
                json={"trade_id": 1, "exit_price": 0.50, "manual": True},
            )

        assert resp.status_code == 503
        assert "kill switch" in resp.get_json()["error"].lower()
        mock_close.assert_not_called()

    def test_trading_paused_blocks_close(self, client, tmp_path, monkeypatch):
        """Mutation check: removing the TRADING_PAUSED check makes this
        test fail the same way as the kill-switch test above."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=True),
            patch("paper.close_paper_early") as mock_close,
        ):
            resp = client.post(
                "/api/close-position",
                json={"trade_id": 1, "exit_price": 0.50, "manual": True},
            )

        assert resp.status_code == 503
        assert "paused" in resp.get_json()["error"].lower()
        mock_close.assert_not_called()

    def test_close_proceeds_normally_when_neither_gate_engaged(
        self, client, tmp_path, monkeypatch
    ):
        """Positive control: proves the new gates don't block the ordinary
        successful path when neither the kill switch nor TRADING_PAUSED is
        active -- without this, the two tests above could pass vacuously if
        the route rejected every close unconditionally."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch("paper.get_open_trades", return_value=[]),
            patch("paper.close_paper_early", return_value={"pnl": 2.5}) as mock_close,
        ):
            resp = client.post(
                "/api/close-position",
                json={"trade_id": 1, "exit_price": 0.50, "manual": True},
            )

        assert resp.status_code == 200
        assert resp.get_json()["pnl"] == 2.5
        mock_close.assert_called_once()


class TestClosePositionPriceCrossCheckM9:
    """audit-M-9 continued: exit_price cross-check against a live quote
    when one exists for the position's side. The check is deliberately
    priced with the EXIT-side (realizable-on-close) convention, not
    /api/paper-order's entry-side (buy) convention -- opus review caught
    the first draft of this copying paper-order's check verbatim (yes_ask
    for YES, 1-yes_bid for NO), which is the wrong side for a close: a YES
    holder can only realize yes_bid on close, a NO holder only 1-yes_ask
    (positions.liquidation_price()'s documented convention, matching
    useData.js's computeMark). Every fixture below uses a WIDE bid/ask
    spread specifically so the correct and the buggy (entry-side) formula
    disagree -- a narrow spread can't distinguish them, which is exactly
    how the entry-side bug shipped undetected the first time. The
    manual-entry path is legitimately for the no-quote (or one-sided-book)
    case and must stay open."""

    def test_correct_exit_side_price_accepted_entry_side_would_reject(
        self, client, tmp_path, monkeypatch
    ):
        """YES position, wide book (bid=0.20, ask=0.60). The realizable
        exit price is yes_bid=0.20 -- exactly what computeMark would send
        as `pos.mark`. Mutation check: reverting to the entry-side formula
        (yes_ask=0.60 as "expected") makes this test fail -- a real,
        correctly-priced close (0.20) would be rejected as deviating from
        0.60 by 0.40, way outside the ±0.15 tolerance."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch(
                "paper.get_open_trades",
                return_value=[{"id": 1, "ticker": "KXHIGH-99JAN01-T70", "side": "yes"}],
            ),
            patch("kalshi_client.KalshiClient") as mock_kc_cls,
            patch("paper.close_paper_early", return_value={"pnl": 1.0}) as mock_close,
        ):
            mock_kc_cls.return_value.get_market.return_value = {
                "yes_bid": 20,
                "yes_ask": 60,
            }
            resp = client.post(
                "/api/close-position",
                json={"trade_id": 1, "exit_price": 0.20, "manual": False},
            )

        assert resp.status_code == 200, resp.get_data(as_text=True)
        mock_close.assert_called_once()

    def test_no_side_correct_exit_price_accepted(self, client, tmp_path, monkeypatch):
        """NO position, same wide book (bid=0.20, ask=0.60). The
        realizable NO exit price is 1-yes_ask=0.40. Mutation check:
        reverting to the entry-side formula (1-yes_bid=0.80 as "expected")
        makes this test fail -- 0.40 deviates from 0.80 by 0.40, way
        outside tolerance, so a correct close would be wrongly rejected."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch(
                "paper.get_open_trades",
                return_value=[{"id": 1, "ticker": "KXHIGH-99JAN01-T70", "side": "no"}],
            ),
            patch("kalshi_client.KalshiClient") as mock_kc_cls,
            patch("paper.close_paper_early", return_value={"pnl": 1.0}) as mock_close,
        ):
            mock_kc_cls.return_value.get_market.return_value = {
                "yes_bid": 20,
                "yes_ask": 60,
            }
            resp = client.post(
                "/api/close-position",
                json={"trade_id": 1, "exit_price": 0.40, "manual": False},
            )

        assert resp.status_code == 200, resp.get_data(as_text=True)
        mock_close.assert_called_once()

    def test_stale_price_rejected_against_the_correct_exit_side_band(
        self, client, tmp_path, monkeypatch
    ):
        """YES position, live bid=0.20 (realizable exit ~0.20, tolerance
        band [0.05, 0.35]). A manually-typed 0.80 is genuinely stale/wrong
        under the CORRECT convention, not just under the buggy one.
        Mutation check: removing the cross-check entirely makes this test
        fail (200 instead of 400)."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch(
                "paper.get_open_trades",
                return_value=[{"id": 1, "ticker": "KXHIGH-99JAN01-T70", "side": "yes"}],
            ),
            patch("kalshi_client.KalshiClient") as mock_kc_cls,
            patch("paper.close_paper_early") as mock_close,
        ):
            mock_kc_cls.return_value.get_market.return_value = {
                "yes_bid": 20,
                "yes_ask": 60,
            }
            resp = client.post(
                "/api/close-position",
                json={"trade_id": 1, "exit_price": 0.80, "manual": True},
            )

        assert resp.status_code == 400
        assert "deviates" in resp.get_json()["error"].lower()
        mock_close.assert_not_called()

    def test_no_live_quote_manual_price_still_allowed(
        self, client, tmp_path, monkeypatch
    ):
        """The manual-entry path is legitimately for the no-quote case --
        when the market has no real quote at all (has_quote=False, both
        sides 0), the manual price must still be accepted regardless of
        its value."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch(
                "paper.get_open_trades",
                return_value=[{"id": 1, "ticker": "KXHIGH-99JAN01-T70", "side": "yes"}],
            ),
            patch("kalshi_client.KalshiClient") as mock_kc_cls,
            patch("paper.close_paper_early", return_value={"pnl": 1.0}) as mock_close,
        ):
            mock_kc_cls.return_value.get_market.return_value = {
                "yes_bid": 0,
                "yes_ask": 0,
            }
            resp = client.post(
                "/api/close-position",
                json={"trade_id": 1, "exit_price": 0.03, "manual": True},
            )

        assert resp.status_code == 200
        mock_close.assert_called_once()

    def test_one_sided_book_this_side_zero_skips_the_check_not_has_quote_alone(
        self, client, tmp_path, monkeypatch
    ):
        """opus review HIGH-2: has_quote is a PAIR-level flag (mid > 0
        across both sides) -- a one-sided/thin overnight book can have
        has_quote=True while the position's OWN side is still coalesced to
        0.0 by parse_market_price(). YES position, yes_bid=0 (no resting
        bids) / yes_ask=0.70 (real ask, so has_quote=True via mid=0.35).
        The realizable YES exit price doesn't exist here (bid=0) so the
        check must be skipped, not compare against 0.0 or 0.70.

        Mutation check: gating only on has_quote (not also checking
        yes_bid > 0 for the YES side) makes this test fail -- exit_price
        0.45 would be compared against an "expected" of either 0.0
        (wrongly rejected, deviates by 0.45) or misread as some other
        value, depending on which stale formula regressed in."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch(
                "paper.get_open_trades",
                return_value=[{"id": 1, "ticker": "KXHIGH-99JAN01-T70", "side": "yes"}],
            ),
            patch("kalshi_client.KalshiClient") as mock_kc_cls,
            patch("paper.close_paper_early", return_value={"pnl": 1.0}) as mock_close,
        ):
            mock_kc_cls.return_value.get_market.return_value = {
                "yes_bid": 0,
                "yes_ask": 70,
            }
            resp = client.post(
                "/api/close-position",
                json={"trade_id": 1, "exit_price": 0.45, "manual": True},
            )

        assert resp.status_code == 200, resp.get_data(as_text=True)
        mock_close.assert_called_once()

    def test_bulk_close_shape_manual_false_with_matching_live_price(
        self, client, tmp_path, monkeypatch
    ):
        """PositionsTab.jsx's bulk-close path always sends manual: false
        with exit_price=p.mark (the live-bid-derived value, matching
        computeMark's YES convention) -- distinct from every test above,
        which used manual: true (the single-close typed-price shape).
        Confirms the cross-check's exit-side convention agrees with what
        the real bulk-close caller actually sends."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch(
                "paper.get_open_trades",
                return_value=[{"id": 1, "ticker": "KXHIGH-99JAN01-T70", "side": "yes"}],
            ),
            patch("kalshi_client.KalshiClient") as mock_kc_cls,
            patch("paper.close_paper_early", return_value={"pnl": 1.0}) as mock_close,
        ):
            mock_kc_cls.return_value.get_market.return_value = {
                "yes_bid": 33,
                "yes_ask": 71,
            }
            resp = client.post(
                "/api/close-position",
                json={"trade_id": 1, "exit_price": 0.33, "manual": False},
            )

        assert resp.status_code == 200, resp.get_data(as_text=True)
        mock_close.assert_called_once()

    def test_quote_lookup_failure_still_does_not_block_the_close(
        self, client, tmp_path, monkeypatch
    ):
        """A lookup/API failure during the cross-check attempt must not
        block a close the operator explicitly confirmed -- fails open for
        the cross-check specifically (the kill-switch/TRADING_PAUSED gates
        tested separately still fail closed on their own, independent
        checks)."""
        import web_app

        monkeypatch.setattr(web_app, "_KS_PATH", tmp_path / ".kill_switch")
        with (
            patch("utils.is_trading_paused", return_value=False),
            patch("paper.get_open_trades", side_effect=RuntimeError("db locked")),
            patch("paper.close_paper_early", return_value={"pnl": 1.0}) as mock_close,
        ):
            resp = client.post(
                "/api/close-position",
                json={"trade_id": 1, "exit_price": 0.50, "manual": True},
            )

        assert resp.status_code == 200
        mock_close.assert_called_once()


class TestAnomalyStatusMatchesRealCheck:
    """Deep-review followup: /api/anomaly-status used to independently
    rebuild the win-rate window with a stale algorithm (sorted by
    placed_at, filtered to outcome in ("yes","no") which silently excludes
    early_exit trades) instead of sharing check_anomalies' own window --
    so the dashboard could show a different trade set than what actually
    drives a real halt."""

    def _trade(self, i, pnl, outcome="early_exit"):
        return {
            "ticker": f"T{i}",
            "settled": True,
            "settled_at": f"2026-01-01T00:{i:02d}:00Z",
            "entered_at": f"2026-01-01T00:{i:02d}:00Z",
            "outcome": outcome,
            "pnl": pnl,
            "days_out": 1,
        }

    def test_early_exit_trades_are_counted_in_the_window(self, client):
        """An early_exit trade (outcome not in yes/no) within the last-10-
        settled window must be counted -- the old code's outcome-based
        filter silently dropped it, undercounting n and mis-stating win_rate."""
        trades = [self._trade(i, 10.0 if i < 6 else -10.0) for i in range(10)]

        with (
            patch("paper.load_paper_trades", return_value=trades),
            patch("alerts.run_anomaly_check", return_value=([], False)),
        ):
            resp = client.get("/api/anomaly-status")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["n"] == 10, (
            "all 10 early_exit trades must be counted, not silently "
            f"excluded by an outcome in ('yes','no') filter: {data}"
        )
        assert data["wins"] == 6
        assert data["losses"] == 4
