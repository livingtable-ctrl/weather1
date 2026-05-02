"""Tests for ML-based bias correction."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestMLBias:
    def test_train_bias_model_returns_dict(self, tmp_path, monkeypatch):
        """train_bias_model returns a dict with per-city models."""
        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        monkeypatch.setattr(ml_bias, "_MODEL_PATH", tmp_path / "bias_models.pkl")
        tracker.init_db()

        result = ml_bias.train_bias_model(min_samples=50)
        assert isinstance(result, dict)

    def test_apply_ml_prob_correction_falls_back_when_no_model(self):
        """apply_ml_prob_correction returns our_prob unchanged if no trained model exists."""
        from unittest.mock import patch

        import ml_bias

        with patch.object(ml_bias, "_load_models", return_value={}):
            result = ml_bias.apply_ml_prob_correction("NYC", 0.72, month=4, days_out=3)
        assert result == pytest.approx(0.72)

    def test_apply_ml_prob_correction_adjusts_probability(self, tmp_path, monkeypatch):
        """apply_ml_prob_correction returns adjusted prob when model is available."""
        from unittest.mock import MagicMock, patch

        import ml_bias

        # Fake model that always predicts +0.05 correction (actual was higher than predicted)
        fake_model = MagicMock()
        fake_model.predict.return_value = [0.05]

        with patch.object(ml_bias, "_load_models", return_value={"NYC": fake_model}):
            result = ml_bias.apply_ml_prob_correction("NYC", 0.60, month=4, days_out=3)

        # Corrected: 0.60 + 0.05 = 0.65
        assert result == pytest.approx(0.65, abs=0.01)


# ── Phase 2: per-city Platt scaling ──────────────────────────────────────────

def test_train_platt_per_city_returns_coefficients():
    """train_platt_per_city returns {city: (A, B)} for cities with >=200 samples."""
    import random

    import ml_bias

    random.seed(42)
    rows = []
    for _ in range(250):
        p = random.uniform(0.3, 0.8)
        rows.append({"city": "NYC", "our_prob": p,
                     "settled_yes": 1 if random.random() < p else 0})
    for _ in range(50):
        rows.append({"city": "Chicago", "our_prob": 0.6, "settled_yes": 1})

    models = ml_bias.train_platt_per_city(rows, min_samples=200)

    assert "NYC" in models, "NYC (250 samples) must be trained"
    assert "Chicago" not in models, "Chicago (<200) must be skipped"
    a, b = models["NYC"]
    assert isinstance(a, float) and isinstance(b, float)


def test_apply_platt_per_city_unknown_city_unchanged():
    """Unknown city returns raw prob unchanged."""
    import ml_bias

    p = ml_bias.apply_platt_per_city("Dallas", 0.65, {})
    assert p == pytest.approx(0.65)


def test_apply_platt_identity_calibration():
    """A=1.0, B=0.0 (identity) returns approximately the input probability."""
    import ml_bias

    models = {"NYC": (1.0, 0.0)}
    p = ml_bias.apply_platt_per_city("NYC", 0.70, models)
    assert 0.60 <= p <= 0.80
