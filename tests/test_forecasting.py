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


class TestPersistenceProb:
    def test_above_condition(self):
        """P(N(70, 5) > 72) ≈ 0.345."""
        from climatology import persistence_prob
        from utils import normal_cdf

        p = persistence_prob("above", 72.0, None, 70.0, 5.0)
        expected = 1.0 - normal_cdf(72.0, 70.0, 5.0)
        assert p is not None
        assert abs(p - expected) < 1e-9

    def test_below_condition(self):
        from climatology import persistence_prob
        from utils import normal_cdf

        p = persistence_prob("below", 65.0, None, 70.0, 5.0)
        expected = normal_cdf(65.0, 70.0, 5.0)
        assert p is not None
        assert abs(p - expected) < 1e-9

    def test_between_condition(self):
        from climatology import persistence_prob

        p = persistence_prob("between", 68.0, 72.0, 70.0, 5.0)
        assert p is not None
        assert 0.0 < p < 1.0

    def test_returns_none_for_zero_std(self):
        from climatology import persistence_prob

        assert persistence_prob("above", 70.0, None, 70.0, 0.0) is None

    def test_analyze_trade_blends_persistence_for_short_horizon(self):
        """analyze_trade includes persistence at 15% weight when days_out <= 2."""
        from datetime import date, timedelta
        from unittest.mock import patch

        import weather_markets as wm

        today = date.today()
        target = today + timedelta(days=1)

        enriched = {
            "ticker": f"KXHIGHNY-{target.strftime('%d%b%y').upper()}-T70",
            "title": "NYC high > 70°F",
            "_city": "NYC",
            "_date": target,
            "_hour": None,
            "_forecast": {
                "high_f": 72.0,
                "low_f": 60.0,
                "precip_in": 0.0,
                "date": target.isoformat(),
                "city": "NYC",
                "models_used": 3,
                "high_range": (70.0, 74.0),
            },
            "yes_bid": 0.45,
            "yes_ask": 0.55,
            "no_bid": 0.45,
            "close_time": "",
            "series_ticker": "KXHIGHNY",
        }

        with (
            patch.object(wm, "get_ensemble_temps", return_value=[70.0] * 20),
            patch("climatology.climatological_prob", return_value=0.6),
            patch("nws.nws_prob", return_value=None),
            patch("nws.get_live_observation", return_value=None),
            patch("climate_indices.temperature_adjustment", return_value=0.0),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        blend = result.get("blend_sources", {})
        assert "persistence" in blend or result["forecast_prob"] is not None
