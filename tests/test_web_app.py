"""Tests for web_app.py dashboard API endpoints."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _force_demo_env():
    """Ensure KALSHI_ENV=demo so _build_app doesn't require DASHBOARD_PASSWORD."""
    with patch("main.KALSHI_ENV", "demo"):
        yield


@pytest.fixture
def client():
    from web_app import _build_app

    with patch("main.KALSHI_ENV", "demo"):
        app = _build_app(object())  # dummy client
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_balance_history_default_50(client):
    """Default returns at most 50 points."""
    history = [
        {"ts": f"2024-01-{d:02d}T00:00:00", "balance": 900 + d, "event": "T"}
        for d in range(1, 92)
    ]
    with patch("paper.get_balance_history", return_value=history):
        r = client.get("/api/balance_history")
        data = r.get_json()
        assert len(data["labels"]) <= 50


def test_balance_history_range_all(client):
    """?range=all returns all points."""
    history = [
        {"ts": f"2024-01-{d:02d}T00:00:00", "balance": 900 + d, "event": "T"}
        for d in range(1, 92)
    ]
    with patch("paper.get_balance_history", return_value=history):
        r = client.get("/api/balance_history?range=all")
        data = r.get_json()
        assert len(data["labels"]) == 91


def test_balance_history_invalid_range_default(client):
    """Invalid range falls back to default 50 points."""
    history = [
        {"ts": f"2024-01-{d:02d}T00:00:00", "balance": 900 + d, "event": "T"}
        for d in range(1, 92)
    ]
    with patch("paper.get_balance_history", return_value=history):
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


def test_trades_route_returns_200_with_title(client):
    """Trades page returns 200 and contains 'Trades'."""
    r = client.get("/trades")
    assert r.status_code == 200
    assert b"Trades" in r.data


def test_api_trades_returns_correct_shape(client):
    """/api/trades returns open and closed keys as lists."""
    with (
        patch(
            "paper.get_open_trades",
            return_value=[
                {
                    "id": 1,
                    "ticker": "T1",
                    "city": "NYC",
                    "side": "yes",
                    "entry_price": 0.6,
                    "cost": 10.0,
                    "target_date": "2025-12-01",
                }
            ],
        ),
        patch(
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
        ),
    ):
        r = client.get("/api/trades")
        assert r.status_code == 200
        d = r.get_json()
        assert "open" in d
        assert "closed" in d
        assert len(d["open"]) == 1
        assert len(d["closed"]) == 1
        assert d["closed"][0]["ticker"] == "T2"


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
    monkeypatch.setattr(paper, "get_balance_history", lambda: fake_history)
    monkeypatch.setattr(web_app, "_now_utc", lambda: now)

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
