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
