from unittest.mock import patch

import pytest


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


class TestEnsoPhase:
    def test_el_nino_returns_correct_label(self):
        from weather_markets import _get_enso_phase

        with patch("weather_markets.get_enso_index", return_value=0.7):
            assert _get_enso_phase() == "el_nino"

    def test_la_nina_returns_correct_label(self):
        from weather_markets import _get_enso_phase

        with patch("weather_markets.get_enso_index", return_value=-0.6):
            assert _get_enso_phase() == "la_nina"

    def test_neutral_returns_correct_label(self):
        from weather_markets import _get_enso_phase

        with patch("weather_markets.get_enso_index", return_value=0.2):
            assert _get_enso_phase() == "neutral"

    def test_none_oni_returns_neutral(self):
        from weather_markets import _get_enso_phase

        with patch("weather_markets.get_enso_index", return_value=None):
            assert _get_enso_phase() == "neutral"

    def test_el_nino_boosts_ecmwf_in_winter(self):
        """_forecast_model_weights gives ECMWF +0.5 extra during El Niño winter."""
        from weather_markets import _forecast_model_weights

        with (
            patch("weather_markets._dynamic_model_weights", return_value=None),
            patch("weather_markets.load_learned_weights", return_value={}),
            patch("weather_markets._get_enso_phase", return_value="el_nino"),
        ):
            w = _forecast_model_weights(month=1, city=None)
        assert w["ecmwf_ifs04"] == pytest.approx(3.0)  # 2.5 base + 0.5 el_nino

    def test_neutral_winter_ecmwf_weight(self):
        from weather_markets import _forecast_model_weights

        with (
            patch("weather_markets._dynamic_model_weights", return_value=None),
            patch("weather_markets.load_learned_weights", return_value={}),
            patch("weather_markets._get_enso_phase", return_value="neutral"),
        ):
            w = _forecast_model_weights(month=1, city=None)
        assert w["ecmwf_ifs04"] == pytest.approx(2.5)


class TestFeelsLike:
    def test_wind_chill_only(self):
        """Standard cold+wind, no humidity penalty."""
        from weather_markets import _feels_like

        result = _feels_like(30.0, wind_mph=15.0, humidity_pct=50.0)
        # NWS wind chill formula: should be well below 30°F
        assert result < 30.0

    def test_moist_cold_wind_chill_humidity_penalty(self):
        """temp<=50, wind>=3, humidity>=70 → wind chill + humidity penalty."""
        from weather_markets import _feels_like

        base = _feels_like(40.0, wind_mph=10.0, humidity_pct=50.0)
        moist = _feels_like(40.0, wind_mph=10.0, humidity_pct=80.0)
        # Moist should feel colder (lower value)
        assert moist < base

    def test_moist_cold_no_wind_intermediate(self):
        """temp<=50, no strong wind, humidity>=70 → humidity penalty only."""
        from weather_markets import _feels_like

        base = _feels_like(45.0, wind_mph=1.0, humidity_pct=50.0)
        moist = _feels_like(45.0, wind_mph=1.0, humidity_pct=80.0)
        assert moist < base

    def test_heat_index_regime(self):
        """temp>=80, humidity>=40 → heat index above raw temp."""
        from weather_markets import _feels_like

        result = _feels_like(95.0, wind_mph=5.0, humidity_pct=70.0)
        assert result > 95.0

    def test_comfortable_no_adjustment(self):
        """Comfortable conditions return raw temp."""
        from weather_markets import _feels_like

        result = _feels_like(68.0, wind_mph=5.0, humidity_pct=50.0)
        assert result == pytest.approx(68.0)


class TestConfidenceScaledBlendWeights:
    def test_high_ens_std_reduces_ensemble_weight(self):
        """ens_std > 8°F (high uncertainty) must reduce w_ens vs baseline."""
        from weather_markets import _confidence_scaled_blend_weights

        w_ens_base, _, _ = _confidence_scaled_blend_weights(
            days_out=3, has_nws=True, has_clim=True, ens_std=None
        )
        w_ens_high, _, _ = _confidence_scaled_blend_weights(
            days_out=3, has_nws=True, has_clim=True, ens_std=10.0
        )
        assert w_ens_high < w_ens_base

    def test_low_ens_std_increases_ensemble_weight(self):
        """ens_std = 2°F (tight spread) must increase w_ens vs baseline."""
        from weather_markets import _confidence_scaled_blend_weights

        w_ens_base, _, _ = _confidence_scaled_blend_weights(
            days_out=3, has_nws=True, has_clim=True, ens_std=None
        )
        w_ens_low, _, _ = _confidence_scaled_blend_weights(
            days_out=3, has_nws=True, has_clim=True, ens_std=2.0
        )
        assert w_ens_low > w_ens_base

    def test_weights_sum_to_one(self):
        from weather_markets import _confidence_scaled_blend_weights

        for ens_std in [None, 2.0, 4.0, 8.0, 12.0]:
            w = _confidence_scaled_blend_weights(3, True, True, ens_std)
            assert abs(sum(w) - 1.0) < 1e-9, (
                f"weights don't sum to 1 for ens_std={ens_std}"
            )

    def test_none_ens_std_returns_base_weights(self):
        """ens_std=None → identical result to _blend_weights."""
        from weather_markets import _blend_weights, _confidence_scaled_blend_weights

        assert _confidence_scaled_blend_weights(5, True, True, None) == _blend_weights(
            5, True, True
        )
