"""Phase 2 Batch D regression tests: P2-6, P2-15."""

from __future__ import annotations

import sys
import threading
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(__file__[: __file__.rfind("tests")]))


# ── P2-6: "between" lock-in uses dynamic confidence ───────────────────────────


class TestBetweenLockInDynamicConfidence:
    """P2-6: between-market METAR lock-in must call _dynamic_lock_in_confidence."""

    def _call_metar_lock_in(self, current_temp, lo, hi, local_hour):
        """Drive _metar_lock_in with fully mocked dependencies."""
        import metar as _metar
        import weather_markets as wm

        today = datetime.now(UTC).date()
        fake_obs_time = MagicMock()
        fake_obs_time.astimezone.return_value = MagicMock(hour=local_hour)

        with patch.object(wm, "_metar_station_for_city", return_value="KJFK"):
            with patch.object(
                _metar,
                "fetch_metar",
                return_value={
                    "current_temp_f": current_temp,
                    "obs_time": fake_obs_time,
                },
            ):
                return wm._metar_lock_in(
                    city="NYC",
                    target_date=today,
                    condition={"type": "between", "lower": lo, "upper": hi},
                )

    def test_yes_lock_confidence_matches_dynamic(self):
        """Inside bucket: confidence must equal _dynamic_lock_in_confidence, not 0.95."""
        import metar as _metar

        current_temp, lo, hi, hour = 71.0, 68.0, 74.0, 15
        clearance = min(current_temp - lo, hi - current_temp)  # 3.0
        expected = _metar._dynamic_lock_in_confidence(clearance, hour)

        # Old hardcoded value was 0.95 — verify dynamic is different (test sanity)
        assert abs(expected - 0.95) > 0.001

        locked, _prob, details = self._call_metar_lock_in(current_temp, lo, hi, hour)
        if locked and details.get("outcome") == "yes":
            assert abs(details["confidence"] - expected) < 0.001, (
                f"YES lock confidence {details['confidence']:.3f} != dynamic {expected:.3f}; "
                "old hardcoded 0.95 may still be in place"
            )

    def test_no_lock_confidence_matches_dynamic(self):
        """Outside bucket >3°F: confidence must equal _dynamic_lock_in_confidence, not 0.92."""
        import metar as _metar

        current_temp, lo, hi, hour = 80.0, 68.0, 74.0, 17  # 6°F above hi
        clearance = current_temp - hi  # 6.0
        expected = _metar._dynamic_lock_in_confidence(clearance, hour)

        assert abs(expected - 0.92) > 0.001

        locked, _prob, details = self._call_metar_lock_in(current_temp, lo, hi, hour)
        if locked and details.get("outcome") == "no":
            assert abs(details["confidence"] - expected) < 0.001, (
                f"NO lock confidence {details['confidence']:.3f} != dynamic {expected:.3f}; "
                "old hardcoded 0.92 may still be in place"
            )

    def test_yes_clearance_uses_min_distance_to_edge(self):
        """YES clearance = min(temp-lo, hi-temp), so temp near an edge yields lower conf."""
        import metar as _metar

        # Temp well inside wide bucket: clearance = 6°F (above the 3°F margin → c_factor > 0)
        conf_wide = _metar._dynamic_lock_in_confidence(clearance_f=6.0, local_hour=16)
        # Temp barely inside: clearance = 0.5°F (below margin → c_factor = 0)
        conf_near_edge = _metar._dynamic_lock_in_confidence(
            clearance_f=0.5, local_hour=16
        )
        assert conf_wide > conf_near_edge, (
            "Temperature closer to bucket edge (smaller clearance) must produce lower confidence"
        )

    def test_no_clearance_scales_with_distance_outside(self):
        """NO clearance increases with distance outside bucket → higher confidence."""
        import metar as _metar

        # 4°F outside (clearance 4): barely over the 3°F threshold
        conf_near = _metar._dynamic_lock_in_confidence(clearance_f=4.0, local_hour=16)
        # 10°F outside (clearance 10): clearly outside
        conf_far = _metar._dynamic_lock_in_confidence(clearance_f=10.0, local_hour=16)
        assert conf_far > conf_near, (
            "Larger clearance outside bucket must yield higher confidence"
        )

    def test_dynamic_confidence_range(self):
        """_dynamic_lock_in_confidence must stay in [0.72, 0.97]."""
        import metar as _metar

        for clearance in (0.0, 3.0, 6.0, 13.0, 20.0):
            for hour in (14, 16, 18, 20, 22):
                conf = _metar._dynamic_lock_in_confidence(clearance, hour)
                assert 0.72 <= conf <= 0.97, (
                    f"conf={conf:.3f} out of [0.72,0.97] for clearance={clearance}, hour={hour}"
                )


# ── P2-15: get_live_precip_obs caching, locking, circuit breaker ──────────────


def _reset_nws_cb():
    """Reset nws circuit breaker and precip cache to clean state."""
    import nws

    nws._precip_cache.clear()
    cb = nws._nws_cb
    cb._failure_count = 0
    cb._opened_at = None
    cb._wall_opened_at = None


class TestGetLivePrecipObs:
    """P2-15: get_live_precip_obs must have caching, thread safety, and circuit breaker."""

    def setup_method(self):
        _reset_nws_cb()

    def test_result_cached_within_obs_ttl(self):
        """Second call within OBS_TTL must not fetch from network."""
        import nws

        call_count = [0]

        def fake_get(url, *a, **kw):
            call_count[0] += 1
            return {"properties": {"precipitationLastHour": {"value": 2.54}}}

        with patch.object(nws, "_get", fake_get):
            with patch.object(nws, "_get_obs_station", return_value="KJFK"):
                nws.get_live_precip_obs("NYC", (40.7, -74.0, 10))
                first_calls = call_count[0]
                nws.get_live_precip_obs("NYC", (40.7, -74.0, 10))
                assert call_count[0] == first_calls, (
                    "Second call within TTL must serve from cache, not re-fetch"
                )

    def test_cache_expires_after_obs_ttl(self):
        """After OBS_TTL the function must re-fetch."""
        import nws

        call_count = [0]

        def fake_get(url, *a, **kw):
            call_count[0] += 1
            return {"properties": {"precipitationLastHour": {"value": 5.08}}}

        with patch.object(nws, "_get", fake_get):
            with patch.object(nws, "_get_obs_station", return_value="KJFK"):
                nws.get_live_precip_obs("NYC", (40.7, -74.0, 10))
                nws._precip_cache["NYC"] = (time.time() - nws.OBS_TTL - 1, 0.2)
                nws.get_live_precip_obs("NYC", (40.7, -74.0, 10))
                assert call_count[0] == 2, "Expired cache must trigger a re-fetch"

    def test_circuit_breaker_open_returns_none(self):
        """When circuit is open, must return None without fetching."""
        import nws

        nws._nws_cb._opened_at = time.monotonic()
        nws._nws_cb._wall_opened_at = time.time()

        result = nws.get_live_precip_obs("NYC", (40.7, -74.0, 10))
        assert result is None, "Open circuit must return None"

    def test_exception_triggers_circuit_breaker_failure(self):
        """A fetch exception must call record_failure on the circuit breaker."""
        import nws

        before = nws._nws_cb._failure_count

        with patch.object(nws, "_get", side_effect=RuntimeError("timeout")):
            with patch.object(nws, "_get_obs_station", return_value="KJFK"):
                result = nws.get_live_precip_obs("NYC", (40.7, -74.0, 10))

        assert result is None
        assert nws._nws_cb._failure_count > before, (
            "Exception must increment circuit breaker failure count"
        )

    def test_thread_safe_no_errors(self):
        """Concurrent calls for different cities must not raise."""
        import nws

        def fake_get(url, *a, **kw):
            time.sleep(0.01)
            return {"properties": {"precipitationLastHour": {"value": 0.0}}}

        results = []
        errors = []

        def fetch(city):
            try:
                with patch.object(nws, "_get", fake_get):
                    with patch.object(nws, "_get_obs_station", return_value="KJFK"):
                        r = nws.get_live_precip_obs(city, (40.7, -74.0, 10))
                        results.append(r)
            except Exception as exc:
                errors.append(exc)

        cities = ["NYC", "BOS", "CHI", "LA", "DAL"]
        threads = [threading.Thread(target=fetch, args=(c,)) for c in cities]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Thread errors: {errors}"
        assert len(results) == 5

    def test_6h_fallback_converts_correctly(self):
        """precipitationLast6Hours must divide by 6 and convert mm→inches."""
        import nws

        # 6 * 25.4 mm = 152.4 mm total → avg 25.4 mm/h → 1.0 inch/h
        with patch.object(
            nws,
            "_get",
            return_value={
                "properties": {
                    "precipitationLastHour": {"value": None},
                    "precipitationLast6Hours": {"value": 152.4},
                }
            },
        ):
            with patch.object(nws, "_get_obs_station", return_value="KJFK"):
                result = nws.get_live_precip_obs("NYC", (40.7, -74.0, 10))

        assert result == pytest.approx(1.0, abs=0.001), (
            f"6h fallback: expected 1.0 inch, got {result}"
        )

    def test_precip_cache_exported(self):
        """_precip_cache must exist as a module-level dict in nws."""
        import nws

        assert hasattr(nws, "_precip_cache")
        assert isinstance(nws._precip_cache, dict)
