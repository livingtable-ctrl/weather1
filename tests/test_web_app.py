"""Tests for web_app.py dashboard API endpoints."""

from unittest.mock import patch

import pytest


@pytest.fixture
def client():
    from web_app import _build_app

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
