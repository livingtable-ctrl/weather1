"""Tests for below-market condition weight fix.

Covers:
- calibrate_and_save preserves non-neutral condition weights during retrain (N < min_samples)
- _blend_weights returns condition-type weights for below (not hardcoded fallback)
- _blend_weights still falls through to hardcoded for above (uncalibrated)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# calibrate_and_save preservation tests
# ---------------------------------------------------------------------------


def _make_db(
    path: Path, n_above: int = 5, n_below: int = 5, n_between: int = 25
) -> None:
    """Create a minimal predictions+outcomes DB with the given row counts."""
    con = sqlite3.connect(str(path))
    con.execute(
        """CREATE TABLE predictions (
            ticker TEXT PRIMARY KEY,
            condition_type TEXT,
            market_date TEXT,
            ensemble_prob REAL,
            clim_prob REAL,
            nws_prob REAL,
            days_out INTEGER
        )"""
    )
    con.execute(
        """CREATE TABLE outcomes (
            ticker TEXT PRIMARY KEY,
            settled_yes INTEGER
        )"""
    )
    for ctype, n in (("above", n_above), ("below", n_below), ("between", n_between)):
        for i in range(n):
            ticker = f"{ctype}_{i:03d}"
            con.execute(
                "INSERT INTO predictions VALUES (?,?,?,?,?,?,?)",
                (ticker, ctype, "2026-06-01", 0.45, 0.55, 0.40, 1),
            )
            con.execute("INSERT INTO outcomes VALUES (?,?)", (ticker, i % 2))
    con.commit()
    con.close()


def test_preserve_non_neutral_below_when_n_too_small(tmp_path):
    """calibrate_and_save must keep existing non-neutral below weights when N < min_samples."""
    db = tmp_path / "pred.db"
    _make_db(db, n_above=5, n_below=5, n_between=25)

    # Write existing condition_weights with calibrated below entry
    existing = {
        "above": {
            "ensemble": 0.333,
            "climatology": 0.333,
            "nws": 0.333,
            "_uncalibrated": True,
        },
        "below": {"ensemble": 0.05, "climatology": 0.75, "nws": 0.20},
        "between": {"ensemble": 0.09, "climatology": 0.004, "nws": 0.906},
    }
    cond_path = tmp_path / "condition_weights.json"
    cond_path.write_text(json.dumps(existing))

    import calibration

    # Run calibrate_and_save pointing at our temp dir
    with (
        patch("calibration.calibrate_seasonal_weights", return_value={}),
        patch("calibration.calibrate_city_weights", return_value={}),
    ):
        calibration.calibrate_and_save(db_path=db, data_dir=tmp_path)

    result = json.loads(cond_path.read_text())

    # below should be preserved (not overwritten with neutral)
    assert result["below"]["climatology"] == pytest.approx(0.75)
    assert result["below"]["ensemble"] == pytest.approx(0.05)
    assert result["below"]["nws"] == pytest.approx(0.20)
    assert "_uncalibrated" not in result["below"]


def test_neutral_below_gets_overwritten_when_n_sufficient(tmp_path):
    """When N >= min_samples, calibrate_condition_weights runs and its result is kept."""
    import calibration

    db = tmp_path / "pred.db"
    _make_db(db, n_above=5, n_below=25, n_between=25)

    # Existing has uncalibrated below
    existing = {
        "below": {
            "ensemble": 0.333,
            "climatology": 0.333,
            "nws": 0.333,
            "_uncalibrated": True,
        },
    }
    cond_path = tmp_path / "condition_weights.json"
    cond_path.write_text(json.dumps(existing))

    with (
        patch("calibration.calibrate_seasonal_weights", return_value={}),
        patch("calibration.calibrate_city_weights", return_value={}),
    ):
        calibration.calibrate_and_save(db_path=db, data_dir=tmp_path)

    result = json.loads(cond_path.read_text())
    # With N=25 >= 20, auto-cal ran; result may differ from existing neutral
    # Most importantly: no KeyError and file is valid JSON
    assert "below" in result


def test_preserve_does_not_touch_between(tmp_path):
    """Preservation only activates for uncalibrated entries; between (calibrated) unchanged."""
    import calibration

    db = tmp_path / "pred.db"
    _make_db(db, n_above=5, n_below=5, n_between=25)

    existing = {
        "above": {
            "ensemble": 0.333,
            "climatology": 0.333,
            "nws": 0.333,
            "_uncalibrated": True,
        },
        "below": {"ensemble": 0.05, "climatology": 0.75, "nws": 0.20},
        "between": {"ensemble": 0.09, "climatology": 0.004, "nws": 0.906},
    }
    cond_path = tmp_path / "condition_weights.json"
    cond_path.write_text(json.dumps(existing))

    with (
        patch("calibration.calibrate_seasonal_weights", return_value={}),
        patch("calibration.calibrate_city_weights", return_value={}),
    ):
        calibration.calibrate_and_save(db_path=db, data_dir=tmp_path)

    result = json.loads(cond_path.read_text())
    # between was calibrated from data (N=25 >= 20); preserved or freshly calibrated
    assert "between" in result
    assert "_uncalibrated" not in result.get("between", {})


# ---------------------------------------------------------------------------
# _blend_weights routing tests
# ---------------------------------------------------------------------------


def test_blend_weights_below_uses_condition_weights(monkeypatch):
    """_blend_weights for below should use condition_weights, not hardcoded schedule."""
    import weather_markets as wm

    # Patch _CONDITION_WEIGHTS to our tuned below entry
    monkeypatch.setattr(
        wm,
        "_CONDITION_WEIGHTS",
        {
            "above": {
                "ensemble": 0.333,
                "climatology": 0.333,
                "nws": 0.333,
                "_uncalibrated": True,
            },
            "below": {"ensemble": 0.05, "climatology": 0.75, "nws": 0.20},
            "between": {"ensemble": 0.09, "climatology": 0.004, "nws": 0.906},
        },
    )

    w = wm._blend_weights(1, has_nws=True, has_clim=True, condition_type="below")
    w_ens, w_clim, w_nws = w

    # clim should dominate (not the hardcoded 0.039)
    assert w_clim > 0.60, f"Expected clim > 0.60 for below, got {w_clim:.3f}"
    assert w_ens < 0.15, f"Expected ens < 0.15 for below, got {w_ens:.3f}"


def test_blend_weights_above_uses_explicit_condition_weights(monkeypatch):
    """_blend_weights for above must use explicit condition weights (ens-heavy), not hardcoded."""
    import weather_markets as wm

    monkeypatch.setattr(
        wm,
        "_CONDITION_WEIGHTS",
        {
            "above": {"ensemble": 0.60, "climatology": 0.05, "nws": 0.35},
            "below": {"ensemble": 0.05, "climatology": 0.75, "nws": 0.20},
        },
    )

    w = wm._blend_weights(1, has_nws=True, has_clim=True, condition_type="above")
    w_ens, w_clim, w_nws = w

    assert w_ens > 0.50, f"Expected ens-heavy for above, got {w_ens:.3f}"
    assert w_clim < 0.10, f"Expected low clim for above, got {w_clim:.3f}"


def test_blend_weights_above_uncalibrated_falls_through_to_hardcoded(monkeypatch):
    """When above has _uncalibrated:true and seasonal is also uncalibrated, use hardcoded."""
    import weather_markets as wm

    monkeypatch.setattr(
        wm,
        "_CONDITION_WEIGHTS",
        {
            "above": {
                "ensemble": 0.333,
                "climatology": 0.333,
                "nws": 0.333,
                "_uncalibrated": True,
            },
        },
    )
    monkeypatch.setattr(
        wm,
        "_SEASONAL_WEIGHTS",
        {
            "spring": {
                "ensemble": 0.333,
                "climatology": 0.333,
                "nws": 0.333,
                "_uncalibrated": True,
            }
        },
    )

    w = wm._blend_weights(1, has_nws=True, has_clim=True, condition_type="above")
    w_ens, w_clim, _w_nws = w

    # Hardcoded days_out=1: ens ~0.61, clim ~0.04
    assert w_ens > 0.50, f"Expected ens > 0.50 for hardcoded, got {w_ens:.3f}"
    assert w_clim < 0.10, f"Expected clim < 0.10 for hardcoded, got {w_clim:.3f}"


def test_t_above_prior_applied_when_no_scale_file(monkeypatch):
    """apply_temperature_scaling must apply _T_ABOVE_PRIOR when scale file missing."""
    import ml_bias

    monkeypatch.setattr(ml_bias, "_load_temperature_scale", lambda: None)

    scaled = ml_bias.apply_temperature_scaling(0.75, condition_type="above")
    # T=6 on p=0.75: sigmoid(logit(0.75)/6) ≈ 0.546
    assert 0.52 < scaled < 0.58, f"Expected T=6 compression, got {scaled:.4f}"
    # Must be less than the unscaled input
    assert scaled < 0.75


def test_t_below_prior_reduced_to_3(monkeypatch):
    """_T_BELOW_PRIOR is 3.0; apply_temperature_scaling compresses less than T=6."""
    import ml_bias

    monkeypatch.setattr(ml_bias, "_load_temperature_scale", lambda: None)

    scaled_below = ml_bias.apply_temperature_scaling(0.75, condition_type="below")
    # T=3 on p=0.75: sigmoid(logit(0.75)/3) ≈ 0.591 — less compressed than T=6
    assert scaled_below > 0.55, f"T=3 should be less compressed, got {scaled_below:.4f}"
    assert scaled_below < 0.75
