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

    def test_apply_ml_bias_falls_back_when_no_model(self):
        """apply_ml_bias returns forecast unchanged if no trained model exists."""
        from unittest.mock import patch

        import ml_bias

        with patch.object(ml_bias, "_load_models", return_value={}):
            result = ml_bias.apply_ml_bias("NYC", 72.0, month=4, days_out=3)
        assert result == pytest.approx(72.0)

    def test_apply_ml_bias_adjusts_temperature(self, tmp_path, monkeypatch):
        """apply_ml_bias returns adjusted temp when model is available."""
        from unittest.mock import MagicMock, patch

        import ml_bias

        fake_model = MagicMock()
        fake_model.predict.return_value = [2.0]

        with patch.object(ml_bias, "_load_models", return_value={"NYC": fake_model}):
            result = ml_bias.apply_ml_bias("NYC", 70.0, month=4, days_out=3)

        # Corrected: 70.0 - 2.0 = 68.0 (subtract predicted error)
        assert result == pytest.approx(68.0, abs=0.1)
