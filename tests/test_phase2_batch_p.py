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
            days_out INTEGER,
            -- batch-82: calibrate_and_save now also runs the SAME-DAY
            -- calibrators, whose query excludes metar_lockout rows by method
            -- (see calibration._SAMEDAY_METAR_EXCLUSION). This fixture drives
            -- calibrate_and_save, so it needs the column the real schema has.
            method TEXT
        )"""
    )
    con.execute(
        """CREATE TABLE outcomes (
            ticker TEXT PRIMARY KEY,
            settled_yes INTEGER,
            disputed INTEGER DEFAULT 0
        )"""
    )
    con.execute(
        """CREATE VIEW outcomes_valid AS
            SELECT * FROM outcomes WHERE disputed IS NULL OR disputed = 0"""
    )
    for ctype, n in (("above", n_above), ("below", n_below), ("between", n_between)):
        for i in range(n):
            ticker = f"{ctype}_{i:03d}"
            con.execute(
                "INSERT INTO predictions VALUES (?,?,?,?,?,?,?,?)",
                (ticker, ctype, "2026-06-01", 0.45, 0.55, 0.40, 1, "ensemble"),
            )
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes) VALUES (?,?)",
                (ticker, i % 2),
            )
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


def test_preserve_does_not_resurrect_a_key_absent_from_a_complete_condition_result(
    tmp_path,
):
    """Regression guard for the _preserve_hand_tuned_weights refactor: unlike
    city (calibrate_city_weights legitimately omits a below-floor city
    entirely), calibrate_condition_weights' result is meant to be the full
    canonical key set (above/below/between, always present via the _neutral
    prefill) -- a key on disk but ABSENT from a fresh result (e.g. a shadow
    condition type that leaked in before the M-13(c) exclusion fix shipped)
    must NOT be silently resurrected into the written file, or the M-13(c)
    exclusion fix would be defeated forever by any pre-existing
    contamination.

    Mutation-tested: passing allow_missing=True for the condition call site
    (matching city's) makes this fail (the stray key comes back) --
    confirmed via Edit revert.
    """
    import calibration

    db = tmp_path / "pred.db"
    _make_db(db, n_above=5, n_below=5, n_between=5)

    existing = {
        "above": {"ensemble": 0.6, "climatology": 0.05, "nws": 0.35},
        "hurricane_count": {"ensemble": 0.5, "climatology": 0.3, "nws": 0.2},
    }
    cond_path = tmp_path / "condition_weights.json"
    cond_path.write_text(json.dumps(existing))

    # calibrate_condition_weights' real return never includes a shadow type
    # key at all (M-13(c) excludes it at the query level) -- simulate that
    # exact shape directly rather than depending on the DB fixture.
    fresh_condition = {
        "above": {"ensemble": 0.6, "climatology": 0.05, "nws": 0.35},
        "below": {
            "ensemble": 0.333,
            "climatology": 0.333,
            "nws": 0.333,
            "_uncalibrated": True,
        },
        "between": {"ensemble": 0.09, "climatology": 0.004, "nws": 0.906},
    }
    with (
        patch("calibration.calibrate_seasonal_weights", return_value={}),
        patch("calibration.calibrate_city_weights", return_value={}),
        patch("calibration.calibrate_condition_weights", return_value=fresh_condition),
    ):
        calibration.calibrate_and_save(db_path=db, data_dir=tmp_path)

    result = json.loads(cond_path.read_text())
    assert "hurricane_count" not in result, (
        "a key absent from a complete calibrate_condition_weights result "
        "must not be resurrected from disk"
    )


def test_preserve_hand_tuned_city_dropped_below_floor(tmp_path):
    """M-13(b): calibrate_city_weights OMITS a city key entirely (not a
    neutral placeholder like seasonal/condition) when it doesn't clear
    _CITY_MIN -- without preservation, a hand-tuned city below the floor
    would be silently dropped from the file, not just overwritten."""
    import calibration

    db = tmp_path / "pred.db"
    _make_db(db, n_above=5, n_below=5, n_between=5)  # all below _CITY_MIN

    existing_city = {
        "NYC": {"ensemble": 0.10, "climatology": 0.70, "nws": 0.20},
    }
    city_path = tmp_path / "city_weights.json"
    city_path.write_text(json.dumps(existing_city))

    with (
        patch("calibration.calibrate_seasonal_weights", return_value={}),
        patch("calibration.calibrate_city_weights", return_value={}),
    ):
        calibration.calibrate_and_save(db_path=db, data_dir=tmp_path)

    result = json.loads(city_path.read_text())
    assert "NYC" in result, "hand-tuned city was dropped, not preserved"
    assert result["NYC"]["climatology"] == pytest.approx(0.70)


def test_preserve_hand_tuned_seasonal_when_uncalibrated(tmp_path):
    """M-13(b): seasonal preservation must mirror condition's existing
    pattern -- a hand-tuned season overwritten by a fresh _uncalibrated
    (insufficient-data) result is restored."""
    import calibration

    db = tmp_path / "pred.db"
    _make_db(db, n_above=5, n_below=5, n_between=5)

    existing_seasonal = {
        "summer": {"ensemble": 0.88, "climatology": 0.002, "nws": 0.118},
    }
    seasonal_path = tmp_path / "seasonal_weights.json"
    seasonal_path.write_text(json.dumps(existing_seasonal))

    fresh_seasonal = {
        "summer": {
            "ensemble": 0.333,
            "climatology": 0.333,
            "nws": 0.333,
            "_uncalibrated": True,
        }
    }
    with (
        patch("calibration.calibrate_seasonal_weights", return_value=fresh_seasonal),
        patch("calibration.calibrate_city_weights", return_value={}),
    ):
        calibration.calibrate_and_save(db_path=db, data_dir=tmp_path)

    result = json.loads(seasonal_path.read_text())
    assert result["summer"]["ensemble"] == pytest.approx(0.88)
    assert "_uncalibrated" not in result["summer"]


def test_calibrate_blend_weights_flags_brier_gate_rejection_uncalibrated(tmp_path):
    """M-13(a): the improvement-gate rejection path (val_baseline -
    val_calibrated <= _BRIER_IMPROVEMENT_GATE) must carry _uncalibrated,
    same as the _MIN_VAL_ROWS path -- otherwise _blend_weights treats
    coincidentally-equal weights as a real fit and never falls through to
    the hardcoded days-out schedule.

    Mutation-tested: reverting the fix (dropping the "_uncalibrated": True
    key from that return) makes this fail -- confirmed via Edit revert.
    """
    import calibration

    db = tmp_path / "pred.db"
    # Random/uncorrelated ep/cp/np vs y (same shape as
    # test_calibrate_condition_weights_returns_per_type_dict) -- val Brier
    # improvement never clears the 0.005 gate.
    import random

    random.seed(1)
    con = sqlite3.connect(str(db))
    con.execute(
        """CREATE TABLE multiday_predictions (
            ticker TEXT PRIMARY KEY, city TEXT, market_date TEXT,
            condition_type TEXT, ensemble_prob REAL, nws_prob REAL,
            clim_prob REAL
        )"""
    )
    con.execute(
        """CREATE TABLE outcomes (
            ticker TEXT PRIMARY KEY, settled_yes INTEGER, disputed INTEGER DEFAULT 0
        )"""
    )
    con.execute(
        """CREATE VIEW outcomes_valid AS
            SELECT * FROM outcomes WHERE disputed IS NULL OR disputed = 0"""
    )
    for i in range(60):
        ticker = f"t{i:03d}"
        month = (i % 12) + 1
        date_str = f"2025-{month:02d}-{(i % 28) + 1:02d}"
        con.execute(
            "INSERT INTO multiday_predictions VALUES (?,?,?,?,?,?,?)",
            (
                ticker,
                "NYC",
                date_str,
                "above",
                random.uniform(0.3, 0.8),
                random.uniform(0.3, 0.7),
                random.uniform(0.3, 0.7),
            ),
        )
        con.execute(
            "INSERT INTO outcomes (ticker, settled_yes) VALUES (?,?)",
            (ticker, random.randint(0, 1)),
        )
    con.commit()
    con.close()

    weights = calibration.calibrate_city_weights(db)
    assert "NYC" in weights
    assert weights["NYC"].get("_uncalibrated") is True, (
        "brier-improvement-gate rejection must flag _uncalibrated"
    )


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
    w_ens, w_clim = w["ensemble"], w["climatology"]

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
    w_ens, w_clim = w["ensemble"], w["climatology"]

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
    w_ens, w_clim = w["ensemble"], w["climatology"]

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
