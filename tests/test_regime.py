"""Tests for regime.detect_regime() — RF6 gap closure."""

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
