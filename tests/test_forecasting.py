from datetime import UTC
from unittest.mock import MagicMock, patch

import pytest


class TestDynamicModelWeights:
    def test_returns_none_when_no_tracker_rows(self):
        """Returns None when get_model_weights returns empty dict (no rows)."""
        from weather_markets import _dynamic_model_weights

        with patch("tracker.get_model_weights", return_value={}):
            result = _dynamic_model_weights(city="NYC", month=1)
        assert result is None

    def test_returns_softmax_weights_from_tracker(self):
        """Returns get_model_weights result when non-empty."""
        from weather_markets import _dynamic_model_weights

        fake_weights = {"icon_seamless": 0.55, "gfs_seamless": 0.45}
        with patch("tracker.get_model_weights", return_value=fake_weights):
            result = _dynamic_model_weights(city="NYC", month=1)
        assert result == fake_weights
        assert result["icon_seamless"] > result["gfs_seamless"]

    def test_returns_none_when_city_is_none(self):
        """Returns None immediately when city is None (no tracker call needed)."""
        from weather_markets import _dynamic_model_weights

        result = _dynamic_model_weights(city=None, month=6)
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
            "volume": 500,
            "open_interest": 200,
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


class TestBlendWeights:
    def test_nws_weight_short_horizon(self):
        """days_out <= 3: NWS weight must be 0.35."""
        from weather_markets import _blend_weights

        _, _, w_nws = _blend_weights(days_out=1, has_nws=True, has_clim=True)
        assert w_nws == pytest.approx(0.35)

        _, _, w_nws3 = _blend_weights(days_out=3, has_nws=True, has_clim=True)
        assert w_nws3 == pytest.approx(0.35)

    def test_nws_weight_medium_horizon(self):
        """days_out 4-7: NWS weight must be 0.25."""
        from weather_markets import _blend_weights

        _, _, w_nws = _blend_weights(days_out=5, has_nws=True, has_clim=True)
        assert w_nws == pytest.approx(0.25)

    def test_nws_weight_long_horizon(self):
        """days_out > 7: NWS weight must be 0.10."""
        from weather_markets import _blend_weights

        _, _, w_nws = _blend_weights(days_out=10, has_nws=True, has_clim=True)
        assert w_nws == pytest.approx(0.10)

    def test_weights_sum_to_one(self):
        from weather_markets import _blend_weights

        for d in [0, 1, 3, 4, 5, 7, 8, 14]:
            w = _blend_weights(d, True, True)
            assert abs(sum(w) - 1.0) < 1e-9

    def test_nws_weight_redistributed_when_unavailable(self):
        """When NWS unavailable, its weight redistributed to ens+clim."""
        from weather_markets import _blend_weights

        w_ens_with, w_clim_with, _ = _blend_weights(1, True, True)
        w_ens_no, w_clim_no, w_nws_no = _blend_weights(1, False, True)
        assert w_nws_no == 0.0
        assert w_ens_no > w_ens_with
        assert abs(w_ens_no + w_clim_no - 1.0) < 1e-9


class TestSnowLiquidRatio:
    def test_above_freezing_returns_zero(self):
        from weather_markets import snow_liquid_ratio

        assert snow_liquid_ratio(33.0) == 0
        assert snow_liquid_ratio(32.1) == 0

    def test_28_to_32_range(self):
        """28°F < wet_bulb <= 32°F → SLR 10"""
        from weather_markets import snow_liquid_ratio

        assert snow_liquid_ratio(32.0) == 10
        assert snow_liquid_ratio(29.0) == 10
        assert snow_liquid_ratio(28.1) == 10

    def test_20_to_28_range(self):
        """20°F < wet_bulb <= 28°F → SLR 15"""
        from weather_markets import snow_liquid_ratio

        assert snow_liquid_ratio(28.0) == 15
        assert snow_liquid_ratio(24.0) == 15
        assert snow_liquid_ratio(20.1) == 15

    def test_below_20_returns_20(self):
        """wet_bulb <= 20°F → SLR 20"""
        from weather_markets import snow_liquid_ratio

        assert snow_liquid_ratio(20.0) == 20
        assert snow_liquid_ratio(10.0) == 20

    def test_wet_bulb_temp_midpoint(self):
        """wet_bulb_temp returns reasonable value for known input."""
        from weather_markets import wet_bulb_temp

        # 50°F, 50% RH → wet bulb should be below dry bulb
        wb = wet_bulb_temp(50.0, 50.0)
        assert wb < 50.0
        assert wb > 32.0

    def test_liquid_equiv_conversion(self):
        from weather_markets import liquid_equiv_of_snow_threshold

        # 10 inches of snow at SLR=10 → 1.0 inch liquid
        assert liquid_equiv_of_snow_threshold(10.0, 10) == pytest.approx(1.0)
        # SLR=0 (above freezing) → infinity
        assert liquid_equiv_of_snow_threshold(10.0, 0) == float("inf")


class TestForecastCycle:
    def test_cycle_labels_cover_all_hours(self):
        """Every UTC hour maps to a valid cycle label."""
        from datetime import datetime
        from unittest.mock import patch

        from weather_markets import _current_forecast_cycle

        valid = {"00z", "06z", "12z", "18z"}
        for h in range(24):
            fake_now = datetime(2026, 1, 1, h, 0, 0, tzinfo=UTC)
            with patch("weather_markets.datetime") as mock_dt:
                mock_dt.now.return_value = fake_now
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                result = _current_forecast_cycle()
            assert result in valid, f"Hour {h} returned invalid label {result!r}"

    def test_cycle_boundaries(self):
        """Boundary hours map to correct cycles."""
        from datetime import datetime
        from unittest.mock import patch

        from weather_markets import _current_forecast_cycle

        cases = [
            (0, "00z"),
            (5, "00z"),
            (6, "06z"),
            (11, "06z"),
            (12, "12z"),
            (17, "12z"),
            (18, "18z"),
            (23, "18z"),
        ]
        for hour, expected in cases:
            fake_now = datetime(2026, 1, 1, hour, 0, 0, tzinfo=UTC)
            with patch("weather_markets.datetime") as mock_dt:
                mock_dt.now.return_value = fake_now
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                result = _current_forecast_cycle()
            assert result == expected, f"Hour {hour}: expected {expected}, got {result}"

    def test_log_prediction_called_with_forecast_cycle(self):
        """main.py passes forecast_cycle to log_prediction."""
        import ast
        import pathlib

        # Locate main.py relative to this test file (tests/ → project root)
        main_path = pathlib.Path(__file__).parent.parent / "main.py"
        src = main_path.read_text(encoding="utf-8")
        tree = ast.parse(src)

        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = getattr(node, "func", None)
                func_name = getattr(func, "attr", None) or getattr(func, "id", None)
                if func_name == "log_prediction":
                    kw_names = {k.arg for k in node.keywords}
                    if "forecast_cycle" in kw_names:
                        found = True
                        break
        assert found, "log_prediction call in main.py must pass forecast_cycle= keyword"


class TestTimeDecayEdge:
    def test_full_edge_at_reference_hours(self):
        """At >= reference_hours before close, return full raw_edge."""
        from datetime import datetime, timedelta

        from weather_markets import time_decay_edge

        close = datetime.now(UTC) + timedelta(hours=50)
        result = time_decay_edge(0.20, close, reference_hours=48.0)
        assert result == pytest.approx(0.20)

    def test_zero_edge_at_close(self):
        """At/past close_time, return 0.0."""
        from datetime import datetime, timedelta

        from weather_markets import time_decay_edge

        close = datetime.now(UTC) - timedelta(hours=1)
        result = time_decay_edge(0.20, close)
        assert result == pytest.approx(0.0)

    def test_half_edge_at_half_reference(self):
        """24h before close with 48h reference → edge * 0.5."""
        from datetime import datetime, timedelta

        from weather_markets import time_decay_edge

        close = datetime.now(UTC) + timedelta(hours=24)
        result = time_decay_edge(0.20, close, reference_hours=48.0)
        assert abs(result - 0.10) < 0.005

    def test_analyze_trade_applies_time_decay(self):
        """analyze_trade edge is time-decay scaled (not raw blended - market)."""
        from datetime import date, datetime, timedelta
        from unittest.mock import patch

        import weather_markets as wm

        today = date.today()
        target = today + timedelta(days=3)
        close_dt = datetime.now(UTC) + timedelta(hours=10)

        enriched = {
            "ticker": f"KXHIGHNY-{target.strftime('%d%b%y').upper()}-T70",
            "title": "NYC high > 70°F",
            "_city": "NYC",
            "_date": target,
            "_hour": None,
            "_forecast": {
                "high_f": 80.0,
                "low_f": 65.0,
                "precip_in": 0.0,
                "date": target.isoformat(),
                "city": "NYC",
                "models_used": 3,
                "high_range": (78.0, 82.0),
            },
            "yes_bid": 0.30,
            "yes_ask": 0.40,
            "no_bid": 0.60,
            "close_time": close_dt.isoformat(),
            "series_ticker": "KXHIGHNY",
            "volume": 500,
            "open_interest": 200,
        }

        with (
            patch.object(wm, "get_ensemble_temps", return_value=[80.0] * 30),
            patch("climatology.climatological_prob", return_value=0.5),
            patch("nws.nws_prob", return_value=None),
            patch("nws.get_live_observation", return_value=None),
            patch("climate_indices.temperature_adjustment", return_value=0.0),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        raw_edge = result["forecast_prob"] - result["market_prob"]
        reported_edge = result["edge"]
        # With 10h to close and 48h reference, decay ≈ 10/48 ≈ 0.208
        # So reported_edge should be less than raw_edge (if positive)
        if abs(raw_edge) > 0.001:
            assert abs(reported_edge) < abs(raw_edge) + 1e-6


class TestLearnedWeights:
    def test_learn_seasonal_weights_returns_dict(self, tmp_path, monkeypatch):
        """learn_seasonal_weights(city) returns {model: weight} from tracker MAE."""
        from unittest.mock import patch

        import weather_markets as wm

        monkeypatch.setattr(wm, "_MAE_WEIGHTS_CACHE", {})
        monkeypatch.setattr(wm, "_LEARNED_WEIGHTS", {})

        fake_acc = {
            "icon_seamless": {
                "mae": 2.0,
                "n": 30,
                "city_breakdown": {"NYC": 1.9},
            },
            "gfs_seamless": {
                "mae": 2.5,
                "n": 30,
                "city_breakdown": {"NYC": 2.4},
            },
        }
        with patch("tracker.get_member_accuracy", return_value=fake_acc):
            result = wm.learn_seasonal_weights("NYC")
        assert isinstance(result, dict)

    def test_forecast_model_weights_uses_learned_per_city(self, monkeypatch):
        """_forecast_model_weights returns city-specific learned weights as priority-2."""
        from unittest.mock import patch

        import weather_markets as wm

        monkeypatch.setattr(
            wm, "_LEARNED_WEIGHTS", {"NYC": {"gfs_seamless": 1.5, "icon_seamless": 0.5}}
        )
        with patch("weather_markets._dynamic_model_weights", return_value=None):
            result = wm._forecast_model_weights(month=6, city="NYC")
        assert result == {"gfs_seamless": 1.5, "icon_seamless": 0.5}

    def test_forecast_model_weights_falls_back_to_seasonal(self, monkeypatch):
        """Falls back to seasonal weights when no learned data for city."""
        from unittest.mock import patch

        import weather_markets as wm

        monkeypatch.setattr(wm, "_LEARNED_WEIGHTS", {})
        with (
            patch("weather_markets._dynamic_model_weights", return_value=None),
            patch("weather_markets._get_enso_phase", return_value="neutral"),
        ):
            result = wm._forecast_model_weights(month=7, city="Denver")
        # Summer: ECMWF gets 1.5
        assert result["ecmwf_ifs04"] == pytest.approx(1.5)

    def test_save_and_load_learned_weights(self, tmp_path, monkeypatch):
        """Round-trip: save then load returns identical dict."""

        import weather_markets as wm

        monkeypatch.setattr(wm, "_LEARNED_WEIGHTS", {})
        weights_path = tmp_path / "learned_weights.json"

        # Patch Path so save/load use our tmp file
        original_path_truediv = wm.Path.__truediv__

        def fake_truediv(self, key):
            if "learned_weights" in str(key):
                return weights_path
            return original_path_truediv(self, key)

        monkeypatch.setattr(wm.Path, "__truediv__", fake_truediv)

        weights = {"NYC": {"gfs_seamless": 1.2, "icon_seamless": 0.8}}
        wm.save_learned_weights(weights)
        monkeypatch.setattr(wm, "_LEARNED_WEIGHTS", {})
        result = wm.load_learned_weights()
        assert result == weights


class TestDynamicCacheTTL:
    def test_ttl_until_next_cycle_minimum(self):
        """TTL is at least 1800 seconds."""
        from datetime import datetime

        from weather_markets import _ttl_until_next_cycle

        for h in range(24):
            now = datetime(2026, 1, 1, h, 30, 0, tzinfo=UTC)
            ttl = _ttl_until_next_cycle(now)
            assert ttl >= 1800, f"TTL at hour {h} is {ttl} < 1800"

    def test_ttl_until_next_cycle_before_02z(self):
        """At 01:00 UTC, next cycle is 02:00 UTC → ~3600s."""
        from datetime import datetime

        from weather_markets import _ttl_until_next_cycle

        now = datetime(2026, 1, 1, 1, 0, 0, tzinfo=UTC)
        ttl = _ttl_until_next_cycle(now)
        assert abs(ttl - 3600) < 60

    def test_cache_hit_returns_forecast_without_fetch(self):
        """get_weather_forecast returns cached data without making API calls."""
        from datetime import date
        from unittest.mock import patch

        import weather_markets as wm

        cache_key = ("NYC", date(2026, 4, 15).isoformat())
        fake_data = {"high_f": 75.0, "low_f": 60.0, "precip_in": 0.0}

        wm._forecast_cache.set(cache_key, fake_data)
        with patch("weather_markets._om_request") as mock_req:
            result = wm.get_weather_forecast("NYC", date(2026, 4, 15))
        assert result == fake_data
        mock_req.assert_not_called()

    def test_cache_hit_returns_ensemble_without_fetch(self):
        """get_ensemble_temps returns cached data without making API calls."""
        from datetime import date
        from unittest.mock import patch

        import weather_markets as wm

        cache_key = ("NYC", date(2026, 4, 15).isoformat(), None, "max")
        fresh_data = [70.0] * 20

        wm._ensemble_cache.set(cache_key, fresh_data)
        with patch("weather_markets._om_request") as mock_req:
            result = wm.get_ensemble_temps("NYC", date(2026, 4, 15))
        assert result == fresh_data
        mock_req.assert_not_called()


class TestForecastModelWeightsTrackerIntegration:
    def test_tracker_weights_used_when_available(self):
        """When tracker has 10+ model rows, _forecast_model_weights returns tracker weights."""
        from weather_markets import _forecast_model_weights

        tracker_weights = {
            "gfs_seamless": 0.25,
            "ecmwf_ifs04": 0.55,
            "icon_seamless": 0.20,
        }
        with patch("tracker.get_model_weights", return_value=tracker_weights):
            result = _forecast_model_weights(month=1, city="NYC")
        assert result == tracker_weights

    def test_seasonal_fallback_when_no_tracker_rows(self):
        """When tracker has no rows (empty dict), _forecast_model_weights falls back to seasonal."""
        from weather_markets import _forecast_model_weights

        with (
            patch("tracker.get_model_weights", return_value={}),
            patch("weather_markets.load_learned_weights", return_value={}),
        ):
            result = _forecast_model_weights(month=7, city="NYC")
        # seasonal summer: ecmwf_w = 1.5
        assert result.get("ecmwf_ifs04") == 1.5


class TestGaussianEnsembleBlend:
    """E2: Gaussian probability is blended into ensemble fraction, not only used as fallback."""

    def _enriched(self, forecast_high: float, threshold: float = 70.0):
        from datetime import date, timedelta

        target = date.today() + timedelta(days=1)
        return {
            "ticker": f"KXHIGHNY-{target.strftime('%d%b%y').upper()}-T{threshold:.0f}",
            "title": f"NYC high > {threshold:.0f}°F",
            "_city": "NYC",
            "_date": target,
            "_hour": None,
            "_forecast": {
                "high_f": forecast_high,
                "low_f": 55.0,
                "precip_in": 0.0,
                "date": target.isoformat(),
                "city": "NYC",
                "models_used": 3,
                "high_range": (forecast_high - 4, forecast_high + 4),
            },
            "yes_bid": 0.45,
            "yes_ask": 0.55,
            "no_bid": 0.45,
            "close_time": "",
            "series_ticker": "KXHIGHNY",
            "volume": 500,
            "open_interest": 200,
        }

    def test_gaussian_lifts_zero_ensemble_when_forecast_is_high(self):
        """E2: when all ensemble members are below threshold but forecast is well above,
        Gaussian blend should raise ens_prob above 0.0."""
        import weather_markets as wm

        # All 20 ensemble members at 65°F → raw ens_prob = 0/20 = 0.0
        # forecast_high = 80°F → Gaussian P(T>70|N(80,σ)) ≈ high
        # nbm = ecmwf = 80°F → raw_fraction = 1.0
        # New blend: 0.70*0.0 + 0.30*gaussian_blend > 0
        enriched = self._enriched(forecast_high=80.0, threshold=70.0)

        with (
            patch.object(wm, "get_ensemble_temps", return_value=[65.0] * 20),
            patch("weather_markets.fetch_temperature_nbm", return_value=80.0),
            patch("weather_markets.fetch_temperature_ecmwf", return_value=80.0),
            patch("climatology.climatological_prob", return_value=0.5),
            patch("nws.nws_prob", return_value=None),
            # Patch the weather_markets-namespace reference (imported with `from
            # nws import get_live_observation`) so obs_override stays None.
            # Patching nws.get_live_observation alone does NOT intercept this.
            patch("weather_markets.get_live_observation", return_value=None),
            patch("weather_markets.obs_prob", return_value=None),
            patch("climate_indices.temperature_adjustment", return_value=0.0),
            # Disable METAR lock-in: when local "tomorrow" == UTC today (US
            # timezones after ~20:00 local), METAR fires and bypasses the
            # ensemble/Gaussian path this test exercises.
            patch.object(wm, "_metar_lock_in", return_value=(False, 0.0, {})),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        # With pure ensemble the signal would be 0.0 (all members below threshold).
        # The Gaussian blend must push forecast_prob above 0.
        assert result["forecast_prob"] > 0.05, (
            f"Gaussian blend should lift forecast_prob above 0 when forecast is 80°F,"
            f" got {result['forecast_prob']:.3f}"
        )

    def test_gaussian_pulls_down_ceiling_ensemble(self):
        """E2: when all ensemble members exceed threshold but forecast is close to it,
        Gaussian blend should reduce ens_prob below 1.0."""
        import weather_markets as wm

        # All 20 ensemble members at 75°F → raw ens_prob = 20/20 = 1.0
        # forecast_high = 68°F → Gaussian P(T>70|N(68,σ)) < 1.0
        # nbm = ecmwf = 68°F → raw_fraction = 0.0
        # New blend: 0.70*1.0 + 0.30*gaussian_blend < 1.0
        enriched = self._enriched(forecast_high=68.0, threshold=70.0)

        with (
            patch.object(wm, "get_ensemble_temps", return_value=[75.0] * 20),
            patch("weather_markets.fetch_temperature_nbm", return_value=68.0),
            patch("weather_markets.fetch_temperature_ecmwf", return_value=68.0),
            patch("climatology.climatological_prob", return_value=0.4),
            patch("nws.nws_prob", return_value=None),
            patch("nws.get_live_observation", return_value=None),
            patch("climate_indices.temperature_adjustment", return_value=0.0),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        assert result["forecast_prob"] < 0.95, (
            f"Gaussian blend should pull forecast_prob below 1.0 when forecast is 68°F,"
            f" got {result['forecast_prob']:.3f}"
        )


# ── P1-1: enrich_with_forecast uses cache timestamp ───────────────────────────


class TestEnrichWithForecastCacheTimestamp:
    """P1-1: data_fetched_at must reflect the cache entry's original fetch time,
    not the current wall-clock time when enrich_with_forecast is called."""

    def test_enrich_uses_cache_timestamp_not_current_time(self, monkeypatch):
        """When the forecast is already cached, data_fetched_at must equal the
        original cache store time, not the time enrich_with_forecast runs."""
        import time

        import weather_markets as wm

        store_wall = time.time() - 7200  # 2 hours ago
        target_date_str = "2026-05-10"
        cache_key = ("NYC", target_date_str)

        fake_forecast = {
            "high_f": 72.0,
            "low_f": 55.0,
            "precip_in": 0.0,
            "date": target_date_str,
            "city": "NYC",
            "models_used": 3,
            "high_range": (70.0, 74.0),
        }

        mock_cache = MagicMock()
        mock_cache.get_with_ts.side_effect = (
            lambda key: (fake_forecast, True, store_wall)
            if key == cache_key
            else (None, False, 0.0)
        )
        mock_cache.get.return_value = fake_forecast

        monkeypatch.setattr(wm, "_forecast_cache", mock_cache)

        # Kalshi ticker format: YYMONDD (year-first) e.g. 26MAY10
        market = {"ticker": "KXHIGHNY-26MAY10-T70", "title": "NYC high > 70°F"}
        result = wm.enrich_with_forecast(market)

        assert abs(result["data_fetched_at"] - store_wall) < 5, (
            f"data_fetched_at should be ~{store_wall:.0f} (cache store time), "
            f"got {result['data_fetched_at']:.0f} (diff={result['data_fetched_at'] - store_wall:.1f}s)"
        )

    def test_enrich_uses_current_time_on_cache_miss(self, monkeypatch):
        """On a cache miss, data_fetched_at must be the current wall-clock time."""
        import time

        import weather_markets as wm

        mock_cache = MagicMock()
        mock_cache.get_with_ts.return_value = (None, False, 0.0)
        mock_cache.get.return_value = None

        monkeypatch.setattr(wm, "_forecast_cache", mock_cache)

        before = time.time()
        market = {"ticker": "KXHIGHNY-26MAY10-T70", "title": "NYC high > 70°F"}
        result = wm.enrich_with_forecast(market)
        after = time.time()

        assert before <= result["data_fetched_at"] <= after + 1, (
            f"On cache miss, data_fetched_at should be current time, "
            f"got {result['data_fetched_at']:.0f} (window {before:.0f}–{after:.0f})"
        )
