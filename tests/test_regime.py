"""Tests for regime.detect_regime() — RF6 gap closure."""

from datetime import date

from regime import detect_regime


def _stats(mean: float, std: float) -> dict:
    return {
        "mean": mean,
        "std": std,
        "min": mean - 2 * std,
        "max": mean + 2 * std,
        "n": 20,
    }


def test_heat_dome_detected():
    result = detect_regime("NYC", _stats(mean=100.0, std=2.0), days_out=1)
    assert result["regime"] == "heat_dome"
    assert result["confidence_boost"] > 1.0


def test_cold_snap_detected():
    result = detect_regime("Chicago", _stats(mean=20.0, std=2.0), days_out=1)
    assert result["regime"] == "cold_snap"
    assert result["confidence_boost"] > 1.0


def test_blocking_high_detected():
    result = detect_regime("Dallas", _stats(mean=60.0, std=2.0), days_out=1)
    assert result["regime"] == "blocking_high"
    assert result["confidence_boost"] > 1.0


def test_volatile_detected():
    result = detect_regime("Denver", _stats(mean=60.0, std=15.0), days_out=1)
    assert result["regime"] == "volatile"
    assert result["confidence_boost"] < 1.0


def test_normal_detected():
    result = detect_regime("Atlanta", _stats(mean=70.0, std=6.0), days_out=1)
    assert result["regime"] == "normal"
    assert result["confidence_boost"] == 1.0


def test_empty_ensemble_stats_returns_normal():
    result = detect_regime("NYC", {}, days_out=1)
    assert result["regime"] == "normal"
    assert result["confidence_boost"] == 1.0


def test_days_out_none_does_not_raise():
    result = detect_regime("NYC", _stats(mean=100.0, std=2.0), days_out=None)
    assert result["regime"] == "heat_dome"


def test_far_horizon_reduces_boost():
    """Confidence boost at days_out=15 should be lower than at days_out=1."""
    near = detect_regime("NYC", _stats(mean=100.0, std=2.0), days_out=1)
    far = detect_regime("NYC", _stats(mean=100.0, std=2.0), days_out=15)
    assert far["confidence_boost"] < near["confidence_boost"]
    assert far["confidence_boost"] >= 1.0  # boost scales down but never below 1.0


class TestClimatologicalConfirmation:
    """M-31(a): heat_dome/cold_snap must additionally require the ensemble
    mean to be climatologically anomalous (>= 1.5 std-devs from the city's
    own seasonal normal) when coords/target_date are supplied -- otherwise
    the absolute mean>95/mean<25 thresholds alone fire on ROUTINE days for
    hot/cold-normal cities (the audit's own Phoenix/Vegas summer example)."""

    _COORDS = (33.45, -112.07, "America/Phoenix")
    _DATE = date(2026, 7, 15)

    def test_heat_dome_confirmed_when_genuinely_anomalous(self, monkeypatch):
        import climatology

        # Phoenix July normal ~85F -- a 100F mean is a genuine +5 sigma anomaly.
        monkeypatch.setattr(
            climatology, "climatological_normal", lambda *a, **kw: (85.0, 3.0)
        )
        result = detect_regime(
            "Phoenix",
            _stats(mean=100.0, std=2.0),
            days_out=1,
            coords=self._COORDS,
            target_date=self._DATE,
            var="max",
        )
        assert result["regime"] == "heat_dome"
        assert result["confidence_boost"] > 1.0

    def test_heat_dome_not_confirmed_on_routine_phoenix_summer_day(self, monkeypatch):
        """The audit's own worked example: Phoenix/Vegas summer highs >95F
        are ROUTINE, not extreme -- mean=100 with a climatological normal
        of 98+-3 is well within normal variation (z=0.67 < 1.5) and must
        NOT fire heat_dome, even though it clears the absolute
        mean>95/std<5 thresholds."""
        import climatology

        monkeypatch.setattr(
            climatology, "climatological_normal", lambda *a, **kw: (98.0, 3.0)
        )
        result = detect_regime(
            "Phoenix",
            _stats(mean=100.0, std=2.0),
            days_out=1,
            coords=self._COORDS,
            target_date=self._DATE,
            var="max",
        )
        assert result["regime"] != "heat_dome"
        # std=2.0 < 3.0 still classifies as the narrower, ungated blocking_high.
        assert result["regime"] == "blocking_high"

    def test_cold_snap_confirmed_when_genuinely_anomalous(self, monkeypatch):
        import climatology

        monkeypatch.setattr(
            climatology, "climatological_normal", lambda *a, **kw: (40.0, 3.0)
        )
        result = detect_regime(
            "Chicago",
            _stats(mean=20.0, std=2.0),
            days_out=1,
            coords=(41.9, -87.6, "America/Chicago"),
            target_date=date(2026, 1, 15),
            var="min",
        )
        assert result["regime"] == "cold_snap"

    def test_cold_snap_not_confirmed_when_climatologically_routine(self, monkeypatch):
        import climatology

        monkeypatch.setattr(
            climatology, "climatological_normal", lambda *a, **kw: (22.0, 3.0)
        )
        result = detect_regime(
            "Chicago",
            _stats(mean=20.0, std=2.0),
            days_out=1,
            coords=(41.9, -87.6, "America/Chicago"),
            target_date=date(2026, 1, 15),
            var="min",
        )
        assert result["regime"] != "cold_snap"
        assert result["regime"] == "blocking_high"

    def test_no_coords_bypasses_climatology_check(self, monkeypatch):
        """Old behavior preserved when the caller can't supply climatology
        context: climatological_normal must not even be consulted."""
        import climatology

        def _boom(*a, **kw):
            raise AssertionError("climatological_normal must not be called")

        monkeypatch.setattr(climatology, "climatological_normal", _boom)
        result = detect_regime("Phoenix", _stats(mean=100.0, std=2.0), days_out=1)
        assert result["regime"] == "heat_dome"

    def test_climatology_lookup_failure_fails_closed(self, monkeypatch):
        """A lookup failure (insufficient data, fetch error) must NOT
        confirm the regime -- an unvalidated extreme-regime Kelly boost
        must not be granted just because climatology was unreachable."""
        import climatology

        monkeypatch.setattr(climatology, "climatological_normal", lambda *a, **kw: None)
        result = detect_regime(
            "Phoenix",
            _stats(mean=100.0, std=2.0),
            days_out=1,
            coords=self._COORDS,
            target_date=self._DATE,
            var="max",
        )
        assert result["regime"] != "heat_dome"

    def test_climatology_zero_std_fails_closed(self, monkeypatch):
        import climatology

        monkeypatch.setattr(
            climatology, "climatological_normal", lambda *a, **kw: (85.0, 0.0)
        )
        result = detect_regime(
            "Phoenix",
            _stats(mean=100.0, std=2.0),
            days_out=1,
            coords=self._COORDS,
            target_date=self._DATE,
            var="max",
        )
        assert result["regime"] != "heat_dome"
