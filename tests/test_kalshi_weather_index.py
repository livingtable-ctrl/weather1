"""Tests for kalshi_weather_index.py (batch-52 item 3) -- the Kalshi
Weather Index live-data feed module backing KXTEMPMIAH's observation
source. Covers: TTL caching, the dedicated circuit breaker, config_version
drift detection/alerting, and the two public reading functions' fail-closed
contract.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import kalshi_weather_index as kwi


def _raw(config_version="miami-temperature-v1.0-cal-20260824", points=None):
    if points is None:
        points = [
            {"t": 1787610000000, "v": 86.0, "contributors": 5, "status": "normal"}
        ]
    return {"city": "miami", "config_version": config_version, "timeseries": points}


def _client(raw=None, raises=None):
    client = MagicMock()
    if raises is not None:
        client.get_live_weather_index.side_effect = raises
    else:
        client.get_live_weather_index.return_value = raw if raw is not None else _raw()
    return client


class TestFetchMiamiIndexRaw:
    def test_caches_successful_fetch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        client = _client()

        first = kwi.fetch_miami_index_raw(client)
        second = kwi.fetch_miami_index_raw(client)

        assert first == _raw()
        assert second == _raw()
        # opus review L-5: the original form here was a bare tuple literal
        # (a stray comma turned an intended `assert x, "msg"` into a no-op
        # expression statement) -- it happened to still work only because
        # assert_called_once() raises on its own on failure, but the "msg"
        # half was always dead. Split into two real statements instead.
        client.get_live_weather_index.assert_called_once()
        assert client.get_live_weather_index.call_count == 1, (
            "second call must be a cache hit, not a second real fetch"
        )

    def test_returns_none_and_negative_caches_on_exception(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        client = _client(raises=RuntimeError("network down"))

        result = kwi.fetch_miami_index_raw(client)
        assert result is None
        # Negative-cached: a second call within the TTL must not re-fetch.
        kwi.fetch_miami_index_raw(client)
        assert client.get_live_weather_index.call_count == 1

    def test_returns_none_when_client_method_returns_none(self, tmp_path, monkeypatch):
        """KalshiClient.get_live_weather_index() itself returns None on a
        malformed/shape-drifted response -- must propagate as None, not
        crash on .get() of a None."""
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        client = _client(raw=None)
        client.get_live_weather_index.return_value = None

        assert kwi.fetch_miami_index_raw(client) is None

    def test_circuit_open_skips_fetch_entirely(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        client = _client()

        with patch.object(kwi._index_cb, "is_open", return_value=True):
            result = kwi.fetch_miami_index_raw(client)

        assert result is None
        client.get_live_weather_index.assert_not_called()

    def test_real_consecutive_failures_actually_open_the_breaker(
        self, tmp_path, monkeypatch
    ):
        """opus review M-5: the only prior breaker test mocked is_open()
        directly and never exercised the real breaker at all -- confirmed
        live that BOTH of these mutations survived the full suite
        unnoticed: failure_threshold=3 -> 99, and deleting
        _index_cb.record_failure() from the fetch-exception path entirely.
        This test drives real consecutive failures through the real
        breaker (module-level singleton, reset by conftest's autouse
        reset_open_meteo_circuit_breaker fixture) and proves it actually
        opens after exactly failure_threshold failures, AND that once
        open, the client is never even called again -- the real end-to-end
        guarantee, not a mocked stand-in for it."""
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        assert kwi._index_cb.is_open() is False, "test setup: must start closed"
        client = _client(raises=RuntimeError("down"))

        for i in range(kwi._index_cb.failure_threshold):
            # Each real fetch is negative-cached only briefly (L-3's
            # _NEGATIVE_CACHE_TTL) but that's still long enough to absorb
            # a same-call re-fetch -- clear it so each loop iteration is a
            # genuine new call reaching the breaker, not a cache hit.
            kwi._INDEX_CACHE.clear()
            result = kwi.fetch_miami_index_raw(client)
            assert result is None
            if i < kwi._index_cb.failure_threshold - 1:
                assert kwi._index_cb.is_open() is False, (
                    f"must not open before the {kwi._index_cb.failure_threshold}th failure"
                )

        assert kwi._index_cb.is_open() is True, (
            "breaker must be open after exactly failure_threshold consecutive failures"
        )
        assert (
            client.get_live_weather_index.call_count == kwi._index_cb.failure_threshold
        )

        # And once open, a fresh call must not even reach the client again.
        kwi._INDEX_CACHE.clear()
        client2 = _client()
        result = kwi.fetch_miami_index_raw(client2)
        assert result is None
        client2.get_live_weather_index.assert_not_called()

    def test_never_raises_on_unexpected_client_exception(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        client = _client(raises=ValueError("boom"))

        kwi.fetch_miami_index_raw(client)  # must not raise


class TestConfigVersionDrift:
    def test_first_observation_records_but_does_not_alert(self, tmp_path, monkeypatch):
        state_path = tmp_path / "state.json"
        monkeypatch.setattr(kwi, "_STATE_PATH", state_path)
        kwi._INDEX_CACHE.clear()
        client = _client(raw=_raw(config_version="v1.0-a"))

        with patch("notify.send_system_alert") as _alert:
            kwi.fetch_miami_index_raw(client)

        _alert.assert_not_called()
        assert json.loads(state_path.read_text())["config_version"] == "v1.0-a"

    def test_version_change_alerts_loudly_and_updates_state(
        self, tmp_path, monkeypatch
    ):
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"config_version": "v1.0-a"}))
        monkeypatch.setattr(kwi, "_STATE_PATH", state_path)
        kwi._INDEX_CACHE.clear()
        client = _client(raw=_raw(config_version="v1.0-b"))

        with patch("notify.send_system_alert") as _alert:
            kwi.fetch_miami_index_raw(client)

        _alert.assert_called_once()
        args, kwargs = _alert.call_args
        assert "v1.0-a" in args[1] and "v1.0-b" in args[1]
        assert kwargs.get("cooldown_key") == "miami_index_config_version"
        assert kwargs.get("discord_color") == 0xF85149
        assert json.loads(state_path.read_text())["config_version"] == "v1.0-b"

    def test_unchanged_version_does_not_alert(self, tmp_path, monkeypatch):
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"config_version": "v1.0-a"}))
        monkeypatch.setattr(kwi, "_STATE_PATH", state_path)
        kwi._INDEX_CACHE.clear()
        client = _client(raw=_raw(config_version="v1.0-a"))

        with patch("notify.send_system_alert") as _alert:
            kwi.fetch_miami_index_raw(client)

        _alert.assert_not_called()

    def test_cache_hit_does_not_re_run_drift_check(self, tmp_path, monkeypatch):
        """A cache hit must not re-run the version comparison -- only a
        REAL fetch does (module docstring's own stated contract)."""
        state_path = tmp_path / "state.json"
        monkeypatch.setattr(kwi, "_STATE_PATH", state_path)
        kwi._INDEX_CACHE.clear()
        client = _client(raw=_raw(config_version="v1.0-a"))
        kwi.fetch_miami_index_raw(client)  # real fetch, records state

        with patch.object(kwi, "_check_config_version_drift") as _check:
            kwi.fetch_miami_index_raw(client)  # cache hit

        _check.assert_not_called()

    def test_alert_failure_does_not_raise(self, tmp_path, monkeypatch):
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"config_version": "v1.0-a"}))
        monkeypatch.setattr(kwi, "_STATE_PATH", state_path)
        kwi._INDEX_CACHE.clear()
        client = _client(raw=_raw(config_version="v1.0-b"))

        with patch(
            "notify.send_system_alert", side_effect=RuntimeError("discord down")
        ):
            kwi.fetch_miami_index_raw(client)  # must not raise

    def test_alert_raising_does_not_advance_stored_version(self, tmp_path, monkeypatch):
        """opus review H-1: if send_system_alert() ITSELF raises, delivery
        obviously didn't succeed -- state must not advance, or the next
        cycle would silently believe this version change was already
        handled. Same guarantee as the returns-False case below, via the
        other failure path."""
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"config_version": "v1.0-a"}))
        monkeypatch.setattr(kwi, "_STATE_PATH", state_path)
        kwi._INDEX_CACHE.clear()
        client = _client(raw=_raw(config_version="v1.0-b"))

        with patch(
            "notify.send_system_alert", side_effect=RuntimeError("discord down")
        ):
            kwi.fetch_miami_index_raw(client)

        assert json.loads(state_path.read_text())["config_version"] == "v1.0-a", (
            "must stay at the OLD version so the next real fetch retries the alert"
        )

    def test_alert_delivery_returning_false_does_not_advance_stored_version(
        self, tmp_path, monkeypatch
    ):
        """opus review H-1: send_system_alert() returning False means every
        configured channel failed to deliver (notify.py's own documented
        contract) -- the config_version drift alert is exactly the kind of
        alert this module's own docstring says must surface LOUDLY, not
        get silently lost. Concrete failure this guards: Discord is down
        for one cycle when the version actually changes; without this fix
        the state file would record the new version anyway and every
        later cycle would see prev == current and never alert again."""
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"config_version": "v1.0-a"}))
        monkeypatch.setattr(kwi, "_STATE_PATH", state_path)
        kwi._INDEX_CACHE.clear()
        client = _client(raw=_raw(config_version="v1.0-b"))

        with patch("notify.send_system_alert", return_value=False) as _alert:
            kwi.fetch_miami_index_raw(client)

        _alert.assert_called_once()
        assert json.loads(state_path.read_text())["config_version"] == "v1.0-a", (
            "delivery failed on every channel -- must not advance, so the "
            "next real fetch re-detects the change and retries the alert"
        )

    def test_alert_delivery_succeeding_advances_stored_version(
        self, tmp_path, monkeypatch
    ):
        """The positive control for the two tests above: when delivery DOES
        succeed, state must advance normally -- otherwise every subsequent
        fetch would re-alert forever for an already-handled change."""
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"config_version": "v1.0-a"}))
        monkeypatch.setattr(kwi, "_STATE_PATH", state_path)
        kwi._INDEX_CACHE.clear()
        client = _client(raw=_raw(config_version="v1.0-b"))

        with patch("notify.send_system_alert", return_value=True) as _alert:
            kwi.fetch_miami_index_raw(client)

        _alert.assert_called_once()
        assert json.loads(state_path.read_text())["config_version"] == "v1.0-b"

    def test_corrupt_state_file_alerts_since_a_real_change_could_be_lost(
        self, tmp_path, monkeypatch
    ):
        """opus review M-6: a corrupt/unreadable state file is NOT the
        same as a genuinely absent one -- it's exactly the condition under
        which a real version change is most likely to have already been
        missed (crash/corruption mid-write), so it must alert too rather
        than silently being treated as "first time seeing this"."""
        state_path = tmp_path / "state.json"
        state_path.write_text("{not valid json")
        monkeypatch.setattr(kwi, "_STATE_PATH", state_path)
        kwi._INDEX_CACHE.clear()
        client = _client(raw=_raw(config_version="v1.0-a"))

        with patch("notify.send_system_alert", return_value=True) as _alert:
            kwi.fetch_miami_index_raw(client)  # must not raise

        _alert.assert_called_once()
        assert json.loads(state_path.read_text())["config_version"] == "v1.0-a"

    def test_genuinely_absent_state_file_does_not_alert(self, tmp_path, monkeypatch):
        """The other half of M-6's distinction: a file that never existed
        at all (first run) is a real "never seen this before" case and
        must NOT alert -- only a corrupt/unreadable EXISTING file should."""
        state_path = tmp_path / "state.json"
        assert not state_path.exists()
        monkeypatch.setattr(kwi, "_STATE_PATH", state_path)
        kwi._INDEX_CACHE.clear()
        client = _client(raw=_raw(config_version="v1.0-a"))

        with patch("notify.send_system_alert") as _alert:
            kwi.fetch_miami_index_raw(client)  # must not raise

        _alert.assert_not_called()
        assert json.loads(state_path.read_text())["config_version"] == "v1.0-a"


class TestGetMiamiIndexReading:
    def test_returns_latest_point(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        points = [
            {"t": 1000000, "v": 80.0, "contributors": 5, "status": "normal"},
            {"t": 2000000, "v": 82.0, "contributors": 5, "status": "normal"},
        ]
        client = _client(raw=_raw(points=points))

        reading = kwi.get_miami_index_reading(client)

        assert reading["temp_f"] == 82.0
        assert reading["obs_time"] == datetime.fromtimestamp(2000, UTC)
        assert reading["status"] == "normal"
        assert reading["contributors"] == 5
        assert reading["config_version"] == "miami-temperature-v1.0-cal-20260824"

    def test_status_passed_through_unfiltered(self, tmp_path, monkeypatch):
        """A 'degraded' point must still be RETURNED (not silently dropped)
        -- the caller is responsible for checking status, per this
        module's documented contract."""
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        points = [{"t": 1000000, "v": 80.0, "contributors": 3, "status": "degraded"}]
        client = _client(raw=_raw(points=points))

        reading = kwi.get_miami_index_reading(client)
        assert reading["status"] == "degraded"

    def test_empty_timeseries_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        client = _client(raw=_raw(points=[]))

        assert kwi.get_miami_index_reading(client) is None

    def test_fetch_failure_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        client = _client(raises=RuntimeError("down"))

        assert kwi.get_miami_index_reading(client) is None

    def test_malformed_point_missing_value_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        points = [{"t": 1000000, "contributors": 5, "status": "normal"}]  # no "v"
        client = _client(raw=_raw(points=points))

        assert kwi.get_miami_index_reading(client) is None

    def test_non_dict_element_in_timeseries_does_not_raise(self, tmp_path, monkeypatch):
        """opus review M-2: confirmed live this RAISED AttributeError before
        the fix (max()'s key function called .get() on a bare string). A
        shape-drifted API response (list-of-scalars, etc.) must fail closed
        (None), not crash -- KalshiClient.get_live_weather_index only
        validates the "timeseries" KEY exists, not each element's shape."""
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        client = _client(raw=_raw(points=["not-a-dict", 42, None]))

        assert kwi.get_miami_index_reading(client) is None

    def test_mix_of_valid_and_malformed_points_uses_the_valid_one(
        self, tmp_path, monkeypatch
    ):
        """The non-dict filter must not throw away good data alongside the
        bad -- a real point mixed in with malformed ones is still usable."""
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        points = [
            "not-a-dict",
            {"t": 2000000, "v": 82.0, "contributors": 5, "status": "normal"},
            None,
        ]
        client = _client(raw=_raw(points=points))

        reading = kwi.get_miami_index_reading(client)
        assert reading["temp_f"] == 82.0


class TestGetMiamiIndexReadingNear:
    def test_finds_nearest_within_tolerance(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        points = [
            {"t": 1_000_000_000, "v": 80.0, "contributors": 5, "status": "normal"},
            {"t": 1_000_060_000, "v": 81.0, "contributors": 5, "status": "normal"},
            {"t": 1_000_600_000, "v": 90.0, "contributors": 5, "status": "normal"},
        ]
        client = _client(raw=_raw(points=points))

        reading = kwi.get_miami_index_reading_near(
            client, target_epoch_s=1_000_050, tolerance_min=5.0
        )
        assert reading["temp_f"] == 81.0  # 1_000_060 is the nearest point

    def test_nothing_within_tolerance_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        points = [
            {"t": 1_000_000_000, "v": 80.0, "contributors": 5, "status": "normal"}
        ]
        client = _client(raw=_raw(points=points))

        reading = kwi.get_miami_index_reading_near(
            client, target_epoch_s=1_000_000 + 3600, tolerance_min=5.0
        )
        assert reading is None

    def test_non_dict_element_in_timeseries_does_not_raise(self, tmp_path, monkeypatch):
        """opus review M-2: same shape-drift guard as get_miami_index_
        reading's own test -- confirmed live this RAISED AttributeError
        before the fix."""
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        points = [
            "not-a-dict",
            {"t": 1_000_000_000, "v": 80.0, "contributors": 5, "status": "normal"},
        ]
        client = _client(raw=_raw(points=points))

        reading = kwi.get_miami_index_reading_near(
            client, target_epoch_s=1_000_000, tolerance_min=5.0
        )
        assert reading["temp_f"] == 80.0

    def test_empty_timeseries_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        client = _client(raw=_raw(points=[]))

        assert (
            kwi.get_miami_index_reading_near(client, target_epoch_s=1_000_000) is None
        )

    def test_fetch_failure_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        client = _client(raises=RuntimeError("down"))

        assert (
            kwi.get_miami_index_reading_near(client, target_epoch_s=1_000_000) is None
        )


class TestCheckMiamiIndexConfigVersion:
    def test_never_raises_on_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        client = _client(raises=RuntimeError("down"))

        kwi.check_miami_index_config_version(client)  # must not raise

    def test_calls_through_to_fetch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kwi, "_STATE_PATH", tmp_path / "state.json")
        kwi._INDEX_CACHE.clear()
        client = _client()

        kwi.check_miami_index_config_version(client)
        client.get_live_weather_index.assert_called_once()
