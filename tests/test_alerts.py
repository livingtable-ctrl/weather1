"""Correctness tests for alerts.py — add/remove/get/check/mark_triggered.

alerts.py had zero correctness tests despite live use (price-alert CRUD +
check_alerts' above/below trigger logic + get_alerts' cooldown re-arm math).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


@pytest.fixture(autouse=True)
def isolate_alerts_data(tmp_path, monkeypatch):
    """Redirect alerts._DATA_PATH to a per-test temp file so tests never
    touch the real data/alerts.json."""
    import alerts

    monkeypatch.setattr(alerts, "_DATA_PATH", tmp_path / "alerts.json")


class TestAddAlert:
    def test_add_alert_returns_expected_fields(self):
        from alerts import add_alert

        alert = add_alert(
            "kxhighny-26apr09-t72", 0.35, direction="below", cooldown_minutes=30
        )
        assert alert["id"] == 1
        assert alert["ticker"] == "KXHIGHNY-26APR09-T72"  # uppercased
        assert alert["target_price"] == 0.35
        assert alert["direction"] == "below"
        assert alert["cooldown_minutes"] == 30
        assert alert["triggered"] is False
        assert alert["triggered_at"] is None
        assert "created_at" in alert

    def test_add_alert_persists_and_increments_id(self):
        from alerts import add_alert, get_alerts

        add_alert("TICK-A", 0.40)
        add_alert("TICK-B", 0.60, direction="above")
        alerts_list = get_alerts()
        assert [a["ticker"] for a in alerts_list] == ["TICK-A", "TICK-B"]
        assert [a["id"] for a in alerts_list] == [1, 2]

    def test_add_alert_defaults_direction_below_cooldown_60(self):
        from alerts import add_alert

        alert = add_alert("TICK-C", 0.50)
        assert alert["direction"] == "below"
        assert alert["cooldown_minutes"] == 60

    def test_add_alert_invalid_direction_raises(self):
        from alerts import add_alert

        with pytest.raises(ValueError, match="direction"):
            add_alert("TICK-D", 0.50, direction="sideways")

    @pytest.mark.parametrize("bad_price", [0.0, 1.0, -0.1, 1.5])
    def test_add_alert_invalid_target_price_raises(self, bad_price):
        from alerts import add_alert

        with pytest.raises(ValueError, match="target_price"):
            add_alert("TICK-E", bad_price)


class TestRemoveAlert:
    def test_remove_existing_alert_returns_true_and_removes(self):
        from alerts import add_alert, get_alerts, remove_alert

        a1 = add_alert("TICK-A", 0.40)
        add_alert("TICK-B", 0.60)
        assert remove_alert(a1["id"]) is True
        remaining = get_alerts()
        assert [a["ticker"] for a in remaining] == ["TICK-B"]

    def test_remove_nonexistent_alert_returns_false(self):
        from alerts import add_alert, get_alerts, remove_alert

        add_alert("TICK-A", 0.40)
        assert remove_alert(9999) is False
        assert len(get_alerts()) == 1


class TestGetAlertsCooldownRearm:
    def test_untriggered_alert_is_active(self):
        from alerts import add_alert, get_alerts

        add_alert("TICK-A", 0.40)
        active = get_alerts()
        assert len(active) == 1
        assert active[0]["triggered"] is False

    def test_triggered_alert_within_cooldown_is_excluded(self):
        """A triggered alert whose cooldown has NOT yet elapsed must not
        reappear in the active list."""
        import alerts

        alert = alerts.add_alert("TICK-A", 0.40, cooldown_minutes=60)
        alerts.mark_triggered(alert["id"])
        active = alerts.get_alerts()
        assert active == []

    def test_triggered_alert_after_cooldown_elapses_is_rearmed(self):
        """P#91: once the cooldown period has passed, the alert must be
        reset to triggered=False and reappear as active."""
        import alerts

        alert = alerts.add_alert("TICK-A", 0.40, cooldown_minutes=10)
        alerts.mark_triggered(alert["id"])

        # Manually back-date triggered_at to 11 minutes ago (> 10 min cooldown).
        data = alerts._load()
        past = (datetime.now(UTC) - timedelta(minutes=11)).isoformat()
        data["alerts"][0]["triggered_at"] = past
        alerts._save(data)

        active = alerts.get_alerts()
        assert len(active) == 1
        assert active[0]["triggered"] is False
        assert active[0]["triggered_at"] is None

    def test_triggered_alert_with_zero_cooldown_never_rearms(self):
        """cooldown_minutes=0 means never re-arm — must stay excluded even
        long after triggering."""
        import alerts

        alert = alerts.add_alert("TICK-A", 0.40, cooldown_minutes=0)
        alerts.mark_triggered(alert["id"])

        data = alerts._load()
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        data["alerts"][0]["triggered_at"] = past
        alerts._save(data)

        active = alerts.get_alerts()
        assert active == []


class TestMarkTriggered:
    def test_mark_triggered_sets_flag_and_timestamp(self):
        import alerts

        alert = alerts.add_alert("TICK-A", 0.40)
        alerts.mark_triggered(alert["id"])
        data = alerts._load()
        stored = data["alerts"][0]
        assert stored["triggered"] is True
        assert stored["triggered_at"] is not None
        # Must be a parseable ISO timestamp.
        datetime.fromisoformat(stored["triggered_at"])

    def test_mark_triggered_only_affects_matching_id(self):
        import alerts

        a1 = alerts.add_alert("TICK-A", 0.40)
        a2 = alerts.add_alert("TICK-B", 0.60)
        alerts.mark_triggered(a1["id"])
        data = alerts._load()
        by_id = {a["id"]: a for a in data["alerts"]}
        assert by_id[a1["id"]]["triggered"] is True
        assert by_id[a2["id"]]["triggered"] is False

    def test_mark_triggered_unknown_id_does_not_raise(self):
        import alerts

        alerts.add_alert("TICK-A", 0.40)
        alerts.mark_triggered(9999)  # must not raise
        data = alerts._load()
        assert data["alerts"][0]["triggered"] is False


class _FakeClient:
    def __init__(self, market: dict):
        self._market = market

    def get_market(self, ticker):
        return self._market


class TestCheckAlerts:
    def test_below_direction_fires_when_price_at_or_under_target(self):
        from alerts import add_alert, check_alerts

        add_alert("TICK-A", 0.30, direction="below")
        client = _FakeClient({"yes_bid": 0.30, "yes_ask": 0.30})  # mid == 0.30
        triggered = check_alerts(client)
        assert len(triggered) == 1
        assert triggered[0]["current_price"] == pytest.approx(0.30)

    def test_below_direction_does_not_fire_when_price_above_target(self):
        from alerts import add_alert, check_alerts

        add_alert("TICK-A", 0.30, direction="below")
        client = _FakeClient({"yes_bid": 0.40, "yes_ask": 0.40})  # mid == 0.40
        triggered = check_alerts(client)
        assert triggered == []

    def test_above_direction_fires_when_price_at_or_over_target(self):
        from alerts import add_alert, check_alerts

        add_alert("TICK-A", 0.70, direction="above")
        client = _FakeClient({"yes_bid": 0.70, "yes_ask": 0.70})  # mid == 0.70
        triggered = check_alerts(client)
        assert len(triggered) == 1
        assert triggered[0]["current_price"] == pytest.approx(0.70)

    def test_above_direction_does_not_fire_when_price_below_target(self):
        from alerts import add_alert, check_alerts

        add_alert("TICK-A", 0.70, direction="above")
        client = _FakeClient({"yes_bid": 0.60, "yes_ask": 0.60})  # mid == 0.60
        triggered = check_alerts(client)
        assert triggered == []

    def test_no_active_alerts_returns_empty_without_fetching(self):
        from alerts import check_alerts

        client = _FakeClient({"yes_bid": 0.50, "yes_ask": 0.50})
        assert check_alerts(client) == []
