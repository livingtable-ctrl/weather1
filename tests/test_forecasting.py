from unittest.mock import patch


class TestDynamicModelWeights:
    def test_returns_none_when_insufficient_samples(self):
        """Returns None when any model has < 5 samples."""
        from weather_markets import _dynamic_model_weights

        fake_acc = {
            "icon_seamless": {"mae": 2.0, "count": 3},
            "gfs_seamless": {"mae": 2.5, "count": 10},
        }
        with patch("tracker.get_ensemble_member_accuracy", return_value=fake_acc):
            result = _dynamic_model_weights(city="NYC", month=1)
        assert result is None

    def test_returns_inverse_mae_weights(self):
        """Returns normalized inverse-MAE weights when all models have >= 5 samples."""
        from weather_markets import _dynamic_model_weights

        fake_acc = {
            "icon_seamless": {"mae": 2.0, "count": 10},
            "gfs_seamless": {"mae": 4.0, "count": 10},
        }
        with patch("tracker.get_ensemble_member_accuracy", return_value=fake_acc):
            result = _dynamic_model_weights(city="NYC", month=1)
        assert result is not None
        # icon has lower MAE → higher weight
        assert result["icon_seamless"] > result["gfs_seamless"]
        # weights normalised so they sum to number of models
        assert abs(sum(result.values()) - len(result)) < 1e-9

    def test_returns_none_when_tracker_empty(self):
        """Returns None when tracker returns None (no data)."""
        from weather_markets import _dynamic_model_weights

        with patch("tracker.get_ensemble_member_accuracy", return_value=None):
            result = _dynamic_model_weights(city="NYC", month=6)
        assert result is None

    def test_used_as_first_priority_in_forecast_model_weights(self):
        """_forecast_model_weights uses _dynamic_model_weights as first priority."""
        from weather_markets import _forecast_model_weights

        expected = {"icon_seamless": 1.5, "gfs_seamless": 0.5}
        with patch("weather_markets._dynamic_model_weights", return_value=expected):
            result = _forecast_model_weights(month=1, city="NYC")
        assert result == expected
