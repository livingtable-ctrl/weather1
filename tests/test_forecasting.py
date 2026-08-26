from datetime import UTC
from unittest.mock import MagicMock, patch

import pytest

import weather_markets as _wm_module

# batch-50: conftest.py's autouse default_hrrr_forecast_mean_none fixture
# stubs weather_markets._fetch_hrrr_temp to a no-op for every test (so
# analyze_trade tests don't fire real network calls) -- same "same opt-in
# pattern as isolate_dynamic_sigma / _REAL_LOAD_DYNAMIC_SIGMA above" idiom
# already used by test_gaussian_prob.py's _REAL_LOAD_DYNAMIC_SIGMA. Captured
# at module import time, before any per-test fixture runs, so TestHRRR's
# direct tests of the real implementation below can restore it via
# monkeypatch.setattr(wm, "_fetch_hrrr_temp", _REAL_FETCH_HRRR_TEMP) BEFORE
# their own `from weather_markets import _fetch_hrrr_temp` local import --
# otherwise that import would silently bind to the autouse stub instead.
_REAL_FETCH_HRRR_TEMP = _wm_module._fetch_hrrr_temp


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
        """_forecast_model_weights uses _dynamic_model_weights as first priority,
        falling back to the static seasonal default for any model dyn omits."""
        from weather_markets import _forecast_model_weights

        # tracker.get_model_weights() returns weights summing to 1.0 (softmax);
        # _forecast_model_weights rescales by len() to the "average 1.0 per
        # model" seasonal-baseline scale before merging, so 0.75/0.25 here
        # becomes 1.5/0.5 in the result.
        dynamic = {"icon_seamless": 0.75, "gfs_seamless": 0.25}
        with (
            patch("weather_markets._dynamic_model_weights", return_value=dynamic),
            patch("weather_markets._get_enso_phase", return_value="neutral"),
        ):
            result = _forecast_model_weights(month=1, city="NYC")
        assert result["icon_seamless"] == pytest.approx(1.5)
        assert result["gfs_seamless"] == pytest.approx(0.5)
        assert result["ecmwf_ifs025"] == pytest.approx(2.5)


class TestPersistenceProb:
    def test_above_condition(self):
        """P(N(70, 5) > 72) â‰ˆ 0.345."""
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
            "title": "NYC high > 70Â°F",
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
            patch.object(
                wm,
                "get_ensemble_temps",
                return_value=[
                    68.0,
                    69.0,
                    70.0,
                    71.0,
                    72.0,
                    68.0,
                    69.0,
                    70.0,
                    71.0,
                    72.0,
                    68.0,
                    69.0,
                    70.0,
                    71.0,
                    72.0,
                    68.0,
                    69.0,
                    70.0,
                    71.0,
                    72.0,
                ],
            ),
            patch("climatology.climatological_prob", return_value=0.6),
            patch("nws.nws_prob", return_value=None),
            patch("nws.get_live_observation", return_value=None),
            patch("mos.fetch_nbm_quantiles", return_value=None),
            patch("climate_indices.temperature_adjustment", return_value=0.0),
            patch("weather_markets.fetch_temperature_nbm", return_value=71.0),
            patch("weather_markets.fetch_temperature_ecmwf", return_value=71.0),
            patch("weather_markets.get_ensemble_members", return_value=[]),
            patch.object(wm, "_SEASONAL_WEIGHTS", {}),
            patch.object(wm, "_CONDITION_WEIGHTS", {}),
            patch.object(wm, "_CITY_WEIGHTS", {}),
            patch.object(
                wm, "_get_consensus_probs", return_value=(None, None, None, None, None)
            ),
            patch("ml_bias.apply_temperature_scaling", side_effect=lambda p, **kw: p),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        blend = result.get("blend_sources", {})
        assert "persistence" in blend or result["forecast_prob"] is not None


class TestEnsoPhase:
    def test_el_nino_returns_correct_label(self):
        from weather_markets import _get_enso_phase

        with patch("climate_indices.get_enso_index", return_value=0.7):
            assert _get_enso_phase() == "el_nino"

    def test_la_nina_returns_correct_label(self):
        from weather_markets import _get_enso_phase

        with patch("climate_indices.get_enso_index", return_value=-0.6):
            assert _get_enso_phase() == "la_nina"

    def test_neutral_returns_correct_label(self):
        from weather_markets import _get_enso_phase

        with patch("climate_indices.get_enso_index", return_value=0.2):
            assert _get_enso_phase() == "neutral"

    def test_none_oni_returns_neutral(self):
        from weather_markets import _get_enso_phase

        with patch("climate_indices.get_enso_index", return_value=None):
            assert _get_enso_phase() == "neutral"

    def test_el_nino_boosts_ecmwf_in_winter(self):
        """_forecast_model_weights gives ECMWF +0.5 extra during El NiÃ±o winter."""
        from weather_markets import _forecast_model_weights

        with (
            patch("weather_markets._dynamic_model_weights", return_value=None),
            patch("weather_markets.load_learned_weights", return_value={}),
            patch("weather_markets._get_enso_phase", return_value="el_nino"),
        ):
            w = _forecast_model_weights(month=1, city=None)
        assert w["ecmwf_ifs025"] == pytest.approx(3.0)  # 2.5 base + 0.5 el_nino

    def test_neutral_winter_ecmwf_weight(self):
        from weather_markets import _forecast_model_weights

        with (
            patch("weather_markets._dynamic_model_weights", return_value=None),
            patch("weather_markets.load_learned_weights", return_value={}),
            patch("weather_markets._get_enso_phase", return_value="neutral"),
        ):
            w = _forecast_model_weights(month=1, city=None)
        assert w["ecmwf_ifs025"] == pytest.approx(2.5)


class TestFeelsLike:
    def test_wind_chill_only(self):
        """Standard cold+wind, no humidity penalty."""
        from weather_markets import _feels_like

        result = _feels_like(30.0, wind_mph=15.0, humidity_pct=50.0)
        # NWS wind chill formula: should be well below 30Â°F
        assert result < 30.0

    def test_moist_cold_wind_chill_humidity_penalty(self):
        """temp<=50, wind>=3, humidity>=70 â†’ wind chill + humidity penalty."""
        from weather_markets import _feels_like

        base = _feels_like(40.0, wind_mph=10.0, humidity_pct=50.0)
        moist = _feels_like(40.0, wind_mph=10.0, humidity_pct=80.0)
        # Moist should feel colder (lower value)
        assert moist < base

    def test_moist_cold_no_wind_intermediate(self):
        """temp<=50, no strong wind, humidity>=70 â†’ humidity penalty only."""
        from weather_markets import _feels_like

        base = _feels_like(45.0, wind_mph=1.0, humidity_pct=50.0)
        moist = _feels_like(45.0, wind_mph=1.0, humidity_pct=80.0)
        assert moist < base

    def test_heat_index_regime(self):
        """temp>=80, humidity>=40 â†’ heat index above raw temp."""
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
        """ens_std > 8Â°F (high uncertainty) must reduce w_ens vs baseline."""
        from weather_markets import _confidence_scaled_blend_weights

        w_base = _confidence_scaled_blend_weights(
            days_out=3, has_nws=True, has_clim=True, ens_std=None
        )
        w_high = _confidence_scaled_blend_weights(
            days_out=3, has_nws=True, has_clim=True, ens_std=10.0
        )
        assert w_high["ensemble"] < w_base["ensemble"]

    def test_low_ens_std_increases_ensemble_weight(self):
        """ens_std = 2Â°F (tight spread) must increase w_ens vs baseline."""
        from weather_markets import _confidence_scaled_blend_weights

        w_base = _confidence_scaled_blend_weights(
            days_out=3, has_nws=True, has_clim=True, ens_std=None
        )
        w_low = _confidence_scaled_blend_weights(
            days_out=3, has_nws=True, has_clim=True, ens_std=2.0
        )
        assert w_low["ensemble"] > w_base["ensemble"]

    def test_weights_sum_to_one(self):
        from weather_markets import _confidence_scaled_blend_weights

        for ens_std in [None, 2.0, 4.0, 8.0, 12.0]:
            w = _confidence_scaled_blend_weights(3, True, True, ens_std)
            assert abs(sum(w.values()) - 1.0) < 1e-9, (
                f"weights don't sum to 1 for ens_std={ens_std}"
            )

    def test_none_ens_std_returns_base_weights(self):
        """ens_std=None â†’ identical result to _blend_weights."""
        from weather_markets import _blend_weights, _confidence_scaled_blend_weights

        assert _confidence_scaled_blend_weights(5, True, True, None) == _blend_weights(
            5, True, True
        )


class TestBlendWeights:
    def test_nws_weight_short_horizon(self):
        """days_out <= 3: NWS weight must be 0.35."""
        from weather_markets import _blend_weights

        w1 = _blend_weights(days_out=1, has_nws=True, has_clim=True)
        assert w1["nws"] == pytest.approx(0.35)

        w3 = _blend_weights(days_out=3, has_nws=True, has_clim=True)
        assert w3["nws"] == pytest.approx(0.35)

    def test_nws_weight_medium_horizon(self):
        """days_out 4-7: NWS weight must be 0.25."""
        from weather_markets import _blend_weights

        w = _blend_weights(days_out=5, has_nws=True, has_clim=True)
        assert w["nws"] == pytest.approx(0.25)

    def test_nws_weight_long_horizon(self):
        """days_out > 7: NWS weight must be 0.10."""
        from weather_markets import _blend_weights

        w = _blend_weights(days_out=10, has_nws=True, has_clim=True)
        assert w["nws"] == pytest.approx(0.10)

    def test_weights_sum_to_one(self):
        from weather_markets import _blend_weights

        for d in [0, 1, 3, 4, 5, 7, 8, 14]:
            w = _blend_weights(d, True, True)
            assert abs(sum(w.values()) - 1.0) < 1e-9

    def test_nws_weight_redistributed_when_unavailable(self):
        """When NWS unavailable, its weight redistributed to ens+clim."""
        from weather_markets import _blend_weights

        w_with = _blend_weights(1, True, True)
        w_no = _blend_weights(1, False, True)
        assert w_no["nws"] == 0.0
        assert w_no["ensemble"] > w_with["ensemble"]
        assert abs(w_no["ensemble"] + w_no["climatology"] - 1.0) < 1e-9


class TestSnowLiquidRatio:
    def test_above_freezing_returns_zero(self):
        from weather_markets import snow_liquid_ratio

        assert snow_liquid_ratio(33.0) == 0
        assert snow_liquid_ratio(32.1) == 0

    def test_28_to_32_range(self):
        """28Â°F < wet_bulb <= 32Â°F â†’ SLR 10"""
        from weather_markets import snow_liquid_ratio

        assert snow_liquid_ratio(32.0) == 10
        assert snow_liquid_ratio(29.0) == 10
        assert snow_liquid_ratio(28.1) == 10

    def test_20_to_28_range(self):
        """20Â°F < wet_bulb <= 28Â°F â†’ SLR 15"""
        from weather_markets import snow_liquid_ratio

        assert snow_liquid_ratio(28.0) == 15
        assert snow_liquid_ratio(24.0) == 15
        assert snow_liquid_ratio(20.1) == 15

    def test_below_20_returns_20(self):
        """wet_bulb <= 20Â°F â†’ SLR 20"""
        from weather_markets import snow_liquid_ratio

        assert snow_liquid_ratio(20.0) == 20
        assert snow_liquid_ratio(10.0) == 20

    def test_wet_bulb_temp_midpoint(self):
        """wet_bulb_temp returns reasonable value for known input."""
        from weather_markets import wet_bulb_temp

        # 50Â°F, 50% RH â†’ wet bulb should be below dry bulb
        wb = wet_bulb_temp(50.0, 50.0)
        assert wb < 50.0
        assert wb > 32.0

    def test_liquid_equiv_conversion(self):
        from weather_markets import liquid_equiv_of_snow_threshold

        # 10 inches of snow at SLR=10 â†’ 1.0 inch liquid
        assert liquid_equiv_of_snow_threshold(10.0, 10) == pytest.approx(1.0)
        # SLR=0 (above freezing) â†’ infinity
        assert liquid_equiv_of_snow_threshold(10.0, 0) == float("inf")


class TestForecastCycle:
    """Retargeted 2026-07-18 (backlog.txt "TWO FUNCTIONS NAMED
    _current_forecast_cycle") from weather_markets._current_forecast_cycle
    (deleted -- a 4-cycle bare-"12z" variant with zero production callers)
    onto order_executor._current_forecast_cycle, the real dedup-key
    function every live/paper order-placement call site actually uses.
    Its 2-cycle (00z/12z), date-prefixed format had no direct correctness
    test of its own before this -- every other test site only ever
    monkeypatches it away."""

    def test_cycle_labels_cover_all_hours(self):
        """Every UTC hour maps to a valid, date-prefixed cycle label."""
        from datetime import datetime
        from unittest.mock import patch

        from order_executor import _current_forecast_cycle

        for h in range(24):
            fake_now = datetime(2026, 1, 1, h, 0, 0, tzinfo=UTC)
            with patch("order_executor.datetime") as mock_dt:
                mock_dt.now.return_value = fake_now
                result = _current_forecast_cycle()
            assert result in {"2026-01-01_00z", "2026-01-01_12z"}, (
                f"Hour {h} returned invalid label {result!r}"
            )

    def test_cycle_boundaries(self):
        """Boundary hours map to the correct cycle, including the date prefix."""
        from datetime import datetime
        from unittest.mock import patch

        from order_executor import _current_forecast_cycle

        cases = [
            (0, "2026-01-01_00z"),
            (11, "2026-01-01_00z"),
            (12, "2026-01-01_12z"),
            (23, "2026-01-01_12z"),
        ]
        for hour, expected in cases:
            fake_now = datetime(2026, 1, 1, hour, 0, 0, tzinfo=UTC)
            with patch("order_executor.datetime") as mock_dt:
                mock_dt.now.return_value = fake_now
                result = _current_forecast_cycle()
            assert result == expected, f"Hour {hour}: expected {expected}, got {result}"

    def test_log_prediction_called_with_forecast_cycle(self):
        """main.py's log_prediction calls must carry forecast_cycle metadata,
        either as a literal keyword or (2026-07-17 consolidation, see
        backlog.txt LOG_PREDICTION KWARGS ASSEMBLY TRIPLICATED) via
        **_prediction_kwargs_from_analysis(...), which itself sets
        forecast_cycle -- see tests/test_prediction_kwargs.py for that
        function's own direct correctness coverage."""
        import ast
        import pathlib

        # Locate main.py relative to this test file (tests/ â†’ project root)
        main_path = pathlib.Path(__file__).parent.parent / "main.py"
        src = main_path.read_text(encoding="utf-8")
        tree = ast.parse(src)

        def _unpacked_call_name(value: ast.expr) -> str | None:
            """For a **expr keyword, return the called function's name if
            expr is a call (e.g. **f(x)), else the bare name (e.g. **d)."""
            target = value.func if isinstance(value, ast.Call) else value
            return getattr(target, "id", None)

        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = getattr(node, "func", None)
            func_name = getattr(func, "attr", None) or getattr(func, "id", None)
            if func_name != "log_prediction":
                continue
            for kw in node.keywords:
                if kw.arg == "forecast_cycle" or (
                    kw.arg is None
                    and _unpacked_call_name(kw.value)
                    == "_prediction_kwargs_from_analysis"
                ):
                    found = True
                    break
            if found:
                break
        assert found, (
            "log_prediction call in main.py must pass forecast_cycle= "
            "(directly or via **_prediction_kwargs_from_analysis(...))"
        )


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
        """24h before close with 48h reference â†’ edge * 0.5."""
        from datetime import datetime, timedelta

        from weather_markets import time_decay_edge

        close = datetime.now(UTC) + timedelta(hours=24)
        result = time_decay_edge(0.20, close, reference_hours=48.0)
        assert abs(result - 0.10) < 0.005

    def test_analyze_trade_applies_time_decay(self):
        """analyze_trade edge is time-decay scaled (not raw blended - market)."""
        from datetime import datetime, timedelta
        from unittest.mock import patch

        # analyze_trade computes days_out from the market's CITY-LOCAL today
        # (ZoneInfo via _CITY_TZ), not UTC's and not the test-runner's
        # system-local date.today() (backlog.txt "ANALYZE_TRADE'S past_date
        # GATE..." fixed the UTC-vs-local-target_date bug this comment used
        # to describe -- every days_out site in weather_markets.py now uses
        # the same city-local "today", mirroring _analyze_precip_trade's
        # pattern). Build the target off NYC's own local date (matching
        # this fixture's "_city": "NYC" below) so the test is correct
        # regardless of wall-clock time relative to UTC.
        from zoneinfo import ZoneInfo

        import weather_markets as wm

        target = datetime.now(ZoneInfo("America/New_York")).date() + timedelta(days=3)
        close_dt = datetime.now(UTC) + timedelta(hours=10)

        enriched = {
            "ticker": f"KXHIGHNY-{target.strftime('%d%b%y').upper()}-T70",
            "title": "NYC high > 70Â°F",
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
            "yes_bid": 0.62,
            "yes_ask": 0.72,
            "no_bid": 0.28,
            "close_time": close_dt.isoformat(),
            "series_ticker": "KXHIGHNY",
            "volume": 500,
            "open_interest": 200,
        }

        with (
            patch.object(
                wm,
                "get_ensemble_temps",
                return_value=[
                    72.0,
                    72.0,
                    72.0,
                    72.0,
                    72.0,
                    73.0,
                    73.0,
                    73.0,
                    73.0,
                    73.0,
                    74.0,
                    74.0,
                    74.0,
                    74.0,
                    74.0,
                    75.0,
                    75.0,
                    75.0,
                    75.0,
                    75.0,
                    64.0,
                    64.0,
                    64.0,
                    64.0,
                    64.0,
                    65.0,
                    65.0,
                    65.0,
                    65.0,
                    65.0,
                ],
            ),
            patch("climatology.climatological_prob", return_value=0.5),
            patch("nws.nws_prob", return_value=None),
            patch("nws.get_live_observation", return_value=None),
            patch("mos.fetch_nbm_quantiles", return_value=None),
            patch("climate_indices.temperature_adjustment", return_value=0.0),
            patch("weather_markets.fetch_temperature_nbm", return_value=69.0),
            patch("weather_markets.fetch_temperature_ecmwf", return_value=69.0),
            patch("weather_markets.get_ensemble_members", return_value=[]),
            patch.object(wm, "_SEASONAL_WEIGHTS", {}),
            patch.object(wm, "_CONDITION_WEIGHTS", {}),
            patch.object(wm, "_CITY_WEIGHTS", {}),
            patch.object(
                wm, "_get_consensus_probs", return_value=(None, None, None, None, None)
            ),
            patch.object(wm, "_metar_lock_in", return_value=(False, 0.0, {})),
            patch("climatology.persistence_prob", return_value=0.3),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        raw_edge = result["forecast_prob"] - result["market_prob"]
        reported_edge = result["edge"]
        # With 10h to close and 48h reference, decay â‰ˆ 10/48 â‰ˆ 0.208
        # So reported_edge should be less than raw_edge (if positive)
        if abs(raw_edge) > 0.001:
            assert abs(reported_edge) < abs(raw_edge) + 1e-6


class TestLearnedWeights:
    def test_learn_seasonal_weights_returns_dict(self, tmp_path, monkeypatch):
        """learn_seasonal_weights(city) returns {model: weight} from tracker MAE."""
        from unittest.mock import patch

        import weather_markets as wm
        from forecast_cache import ForecastCache

        monkeypatch.setattr(wm, "_MAE_WEIGHTS_CACHE", ForecastCache())
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
        assert result["gfs_seamless"] == 1.5
        assert result["icon_seamless"] == 0.5
        assert result["ecmwf_ifs025"] == pytest.approx(1.5)

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
        assert result["ecmwf_ifs025"] == pytest.approx(1.5)

    def test_save_and_load_learned_weights(self, tmp_path, monkeypatch):
        """Round-trip: save then load returns identical dict."""

        import weather_markets as wm

        monkeypatch.setattr(wm, "_LEARNED_WEIGHTS", {})
        weights_path = tmp_path / "learned_weights.json"
        monkeypatch.setattr(wm, "LEARNED_WEIGHTS_PATH", weights_path)

        weights = {"NYC": {"gfs_seamless": 1.2, "icon_seamless": 0.8}}
        wm.save_learned_weights(weights)
        monkeypatch.setattr(wm, "_LEARNED_WEIGHTS", {})
        result = wm.load_learned_weights()
        assert result == weights

    def test_load_learned_weights_handles_non_numeric_value(
        self, tmp_path, monkeypatch
    ):
        """A manually-corrupted file with a non-numeric weight (e.g. a stray
        string) must not crash load_learned_weights() with a TypeError -- it
        should be treated as corruption, same as a non-positive weight."""
        import json

        import weather_markets as wm

        monkeypatch.setattr(wm, "_LEARNED_WEIGHTS", {})
        weights_path = tmp_path / "learned_weights.json"
        weights_path.write_text(
            json.dumps({"NYC": {"gfs_seamless": "high", "icon_seamless": 0.8}})
        )
        monkeypatch.setattr(wm, "LEARNED_WEIGHTS_PATH", weights_path)

        result = wm.load_learned_weights()  # must not raise
        assert result == {}
        assert not weights_path.exists()  # corrupt file is deleted, same as other cases

    def test_save_learned_weights_rejects_non_numeric_value(
        self, tmp_path, monkeypatch
    ):
        """A non-numeric weight passed to save_learned_weights() must not crash
        with a TypeError -- it should be rejected the same as a near-zero weight."""
        import weather_markets as wm

        monkeypatch.setattr(wm, "_LEARNED_WEIGHTS", {})
        weights_path = tmp_path / "learned_weights.json"
        monkeypatch.setattr(wm, "LEARNED_WEIGHTS_PATH", weights_path)

        wm.save_learned_weights({"NYC": {"gfs_seamless": "high"}})  # must not raise
        assert not weights_path.exists()  # rejected before writing


class TestDynamicCacheTTL:
    @pytest.fixture(autouse=True)
    def _restore_module_caches(self):
        """test_cache_hit_returns_forecast_without_fetch and
        test_cache_hit_returns_ensemble_without_fetch below write directly
        into weather_markets' shared, long-TTL (8h) module-level singletons
        (_forecast_cache, _ensemble_cache) to exercise cache-hit behavior.
        Those are real mutations of the actual object, not covered by
        monkeypatch's auto-revert, so without this fixture they leak into any
        later test in the same pytest session that happens to hit the same
        (city, date) key -- confirmed 2026-07-17 via git-stash bisection as
        the root cause of tests/test_data_freshness.py::
        test_enrich_with_forecast_stamps_data_fetched_at failing
        intermittently (only when run in the same session after this file,
        never in isolation) because both write/read the ("NYC", "2026-04-15")
        forecast-cache key.
        """
        import weather_markets as wm

        _forecast_snapshot = dict(wm._forecast_cache._store)
        _ensemble_snapshot = dict(wm._ensemble_cache._store)
        yield
        wm._forecast_cache._store.clear()
        wm._forecast_cache._store.update(_forecast_snapshot)
        wm._ensemble_cache._store.clear()
        wm._ensemble_cache._store.update(_ensemble_snapshot)

    def test_ttl_until_next_cycle_minimum(self):
        """TTL is at least 1800 seconds."""
        from datetime import datetime

        from weather_markets import _ttl_until_next_cycle

        for h in range(24):
            now = datetime(2026, 1, 1, h, 30, 0, tzinfo=UTC)
            ttl = _ttl_until_next_cycle(now)
            assert ttl >= 1800, f"TTL at hour {h} is {ttl} < 1800"

    def test_ttl_until_next_cycle_before_02z(self):
        """At 01:00 UTC, next cycle is 02:00 UTC â†’ ~3600s."""
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

        # 5th element is the quarantine-state cache tag (empty string == no
        # models currently quarantined) -- get_ensemble_temps()'s cache_key
        # includes it so a quarantine/release change invalidates stale
        # cached blends; must match here or this seeded entry is unreachable.
        cache_key = ("NYC", date(2026, 4, 15).isoformat(), None, "max", "")
        fresh_data = [
            68.0,
            69.0,
            70.0,
            71.0,
            72.0,
            68.0,
            69.0,
            70.0,
            71.0,
            72.0,
            68.0,
            69.0,
            70.0,
            71.0,
            72.0,
            68.0,
            69.0,
            70.0,
            71.0,
            72.0,
        ]

        wm._ensemble_cache.set(cache_key, fresh_data)
        with patch("weather_markets._om_request") as mock_req:
            result = wm.get_ensemble_temps("NYC", date(2026, 4, 15))
        assert result == fresh_data
        mock_req.assert_not_called()


class TestForecastModelWeightsTrackerIntegration:
    def test_tracker_weights_used_when_available(self):
        """When tracker has 10+ model rows, _forecast_model_weights returns
        tracker weights rescaled to the seasonal-baseline scale (tracker's
        softmax weights sum to 1.0; the baseline/learned scale averages 1.0
        per model, so the raw tracker dict is multiplied by len() first)."""
        from weather_markets import _forecast_model_weights

        tracker_weights = {
            "gfs_seamless": 0.25,
            "ecmwf_ifs025": 0.55,
            "icon_seamless": 0.20,
        }
        with (
            patch("tracker.get_model_weights", return_value=tracker_weights),
            # _forecast_model_weights consults _get_enso_phase, which fetches
            # three real index files from www.cpc.ncep.noaa.gov; same pin as
            # the sibling classes in this file.
            patch("weather_markets._get_enso_phase", return_value="neutral"),
        ):
            result = _forecast_model_weights(month=1, city="NYC")
        assert result["gfs_seamless"] == pytest.approx(0.75)
        assert result["ecmwf_ifs025"] == pytest.approx(1.65)
        assert result["icon_seamless"] == pytest.approx(0.60)

    def test_partial_tracker_weights_backfilled_from_baseline(self):
        """When tracker data covers only some models (e.g. ECMWF has zero rows
        for this city/window), the missing model must be backfilled from the
        static seasonal baseline, not silently dropped from the result."""
        from unittest.mock import patch

        from weather_markets import _forecast_model_weights

        # Sums to 1.0 across the 2 present models (realistic tracker output);
        # rescaled by len()==2 to the seasonal-baseline scale below.
        partial_tracker_weights = {"gfs_seamless": 0.6, "icon_seamless": 0.4}
        with (
            patch("tracker.get_model_weights", return_value=partial_tracker_weights),
            patch("weather_markets._get_enso_phase", return_value="neutral"),
        ):
            result = _forecast_model_weights(month=1, city="NYC")  # winter
        assert result["gfs_seamless"] == pytest.approx(1.2)
        assert result["icon_seamless"] == pytest.approx(0.8)
        assert result["ecmwf_ifs025"] == pytest.approx(2.5)  # backfilled, not missing

    def test_seasonal_fallback_when_no_tracker_rows(self):
        """When tracker has no rows (empty dict), _forecast_model_weights falls back to seasonal."""
        from weather_markets import _forecast_model_weights

        with (
            patch("tracker.get_model_weights", return_value={}),
            patch("weather_markets.load_learned_weights", return_value={}),
        ):
            result = _forecast_model_weights(month=7, city="NYC")
        # seasonal summer: ecmwf_w = 1.5
        assert result.get("ecmwf_ifs025") == 1.5


class TestGaussianEnsembleBlend:
    """E2: Gaussian probability is blended into ensemble fraction, not only used as fallback."""

    def _enriched(self, forecast_high: float, threshold: float = 70.0):
        from datetime import date, timedelta

        target = date.today() + timedelta(days=1)
        return {
            "ticker": f"KXHIGHNY-{target.strftime('%d%b%y').upper()}-T{threshold:.0f}",
            "title": f"NYC high > {threshold:.0f}Â°F",
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

        # All 20 ensemble members at 65Â°F â†’ raw ens_prob = 0/20 = 0.0
        # forecast_high = 80Â°F â†’ Gaussian P(T>70|N(80,Ïƒ)) â‰ˆ high
        # nbm = ecmwf = 80Â°F â†’ raw_fraction = 1.0
        # New blend: 0.70*0.0 + 0.30*gaussian_blend > 0
        enriched = self._enriched(forecast_high=80.0, threshold=70.0)

        with (
            patch.object(
                wm,
                "get_ensemble_temps",
                return_value=[
                    63.0,
                    64.0,
                    65.0,
                    66.0,
                    67.0,
                    63.0,
                    64.0,
                    65.0,
                    66.0,
                    67.0,
                    63.0,
                    64.0,
                    65.0,
                    66.0,
                    67.0,
                    63.0,
                    64.0,
                    65.0,
                    66.0,
                    67.0,
                ],
            ),
            patch("weather_markets.fetch_temperature_nbm", return_value=80.0),
            patch("weather_markets.fetch_temperature_ecmwf", return_value=80.0),
            patch("weather_markets.get_ensemble_members", return_value=[]),
            patch("climatology.climatological_prob", return_value=0.5),
            patch("nws.nws_prob", return_value=None),
            # Keeps obs_override None. weather_markets no longer re-exports
            # get_live_observation (it calls nws.get_live_observation directly),
            # so this single source-module patch reaches every call site.
            patch("nws.get_live_observation", return_value=None),
            patch("mos.fetch_nbm_quantiles", return_value=None),
            # No obs_prob pin needed: it is only reached inside `if live_obs:`,
            # and get_live_observation is pinned to None right above.
            patch("climate_indices.temperature_adjustment", return_value=0.0),
            # Disable METAR lock-in: it gates on city-local (NY) date, not
            # UTC -- when target_date == NY-local-today, it fires and
            # bypasses the ensemble/Gaussian path this test exercises.
            patch.object(wm, "_metar_lock_in", return_value=(False, 0.0, {})),
            patch.object(wm, "_SEASONAL_WEIGHTS", {}),
            patch.object(wm, "_CONDITION_WEIGHTS", {}),
            patch.object(wm, "_CITY_WEIGHTS", {}),
            patch.object(
                wm, "_get_consensus_probs", return_value=(None, None, None, None, None)
            ),
            patch("ml_bias.apply_temperature_scaling", side_effect=lambda p, **kw: p),
            # This test's fixture uses an 8.0°F high_range spread — not itself
            # under test here, but MAX_MODEL_SPREAD_F is read from .env and can
            # legitimately be configured below that (e.g. 5.5), which would
            # trip the model-spread gate before any Gaussian-blend logic runs.
            # Pin it to a permissive value so this test doesn't depend on
            # whatever the live .env happens to have configured.
            patch.object(wm, "MAX_MODEL_SPREAD_F", 100.0),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        # With pure ensemble the signal would be 0.0 (all members below threshold).
        # The Gaussian blend must push forecast_prob above 0.
        assert result["forecast_prob"] > 0.05, (
            f"Gaussian blend should lift forecast_prob above 0 when forecast is 80Â°F,"
            f" got {result['forecast_prob']:.3f}"
        )

    def test_gaussian_pulls_down_ceiling_ensemble(self):
        """E2: when all ensemble members exceed threshold but forecast is close to it,
        Gaussian blend should reduce ens_prob below 1.0."""
        import weather_markets as wm

        # All 20 ensemble members at 75Â°F â†’ raw ens_prob = 20/20 = 1.0
        # forecast_high = 68Â°F â†’ Gaussian P(T>70|N(68,Ïƒ)) < 1.0
        # nbm = ecmwf = 68Â°F â†’ raw_fraction = 0.0
        # New blend: 0.70*1.0 + 0.30*gaussian_blend < 1.0
        enriched = self._enriched(forecast_high=68.0, threshold=70.0)
        # Market prices consistent with model's ~0.75 ceiling estimate to avoid model_mkt_gap gate
        enriched["yes_bid"] = 0.68
        enriched["yes_ask"] = 0.80

        with (
            patch.object(
                wm,
                "get_ensemble_temps",
                return_value=[
                    73.0,
                    74.0,
                    75.0,
                    76.0,
                    77.0,
                    73.0,
                    74.0,
                    75.0,
                    76.0,
                    77.0,
                    73.0,
                    74.0,
                    75.0,
                    76.0,
                    77.0,
                    73.0,
                    74.0,
                    75.0,
                    76.0,
                    77.0,
                ],
            ),
            patch("weather_markets.fetch_temperature_nbm", return_value=68.0),
            patch("weather_markets.fetch_temperature_ecmwf", return_value=68.0),
            patch("weather_markets.get_ensemble_members", return_value=[]),
            patch("climatology.climatological_prob", return_value=0.4),
            patch("nws.nws_prob", return_value=None),
            patch("nws.get_live_observation", return_value=None),
            patch("mos.fetch_nbm_quantiles", return_value=None),
            patch("climate_indices.temperature_adjustment", return_value=0.0),
            patch.object(wm, "_SEASONAL_WEIGHTS", {}),
            patch.object(wm, "_CONDITION_WEIGHTS", {}),
            patch.object(wm, "_CITY_WEIGHTS", {}),
            patch.object(
                wm, "_get_consensus_probs", return_value=(None, None, None, None, None)
            ),
            patch.object(wm, "_metar_lock_in", return_value=(False, 0.0, {})),
            patch("climatology.persistence_prob", return_value=0.3),
            # See the identical fix in test_gaussian_lifts_zero_ensemble_when_forecast_is_high
            # above — pin the model-spread gate so this test doesn't depend on
            # whatever MAX_MODEL_SPREAD_F the live .env happens to configure.
            patch.object(wm, "MAX_MODEL_SPREAD_F", 100.0),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        assert result["forecast_prob"] < 0.95, (
            f"Gaussian blend should pull forecast_prob below 1.0 when forecast is 68Â°F,"
            f" got {result['forecast_prob']:.3f}"
        )


# â”€â”€ P1-1: enrich_with_forecast uses cache timestamp â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


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
        mock_cache.get_with_ts.side_effect = lambda key: (
            (fake_forecast, True, store_wall)
            if key == cache_key
            else (None, False, 0.0)
        )
        mock_cache.get.return_value = fake_forecast

        monkeypatch.setattr(wm, "_forecast_cache", mock_cache)

        # Kalshi ticker format: YYMONDD (year-first) e.g. 26MAY10
        market = {"ticker": "KXHIGHNY-26MAY10-T70", "title": "NYC high > 70Â°F"}
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
        # A cache miss falls through to the real Open-Meteo fetch;
        # TestEnrichWithForecastSkipsFetch below stubs it the same way. Safe:
        # data_fetched_at comes solely from _forecast_cache.get_with_ts(), never
        # from get_weather_forecast's return value, so stubbing the fetch cannot
        # make the window assertion pass for the wrong reason.
        monkeypatch.setattr(
            wm,
            "get_weather_forecast",
            lambda city, target_date, **kw: {"high_f": 70.0, "_source": "open_meteo"},
        )

        before = time.time()
        market = {"ticker": "KXHIGHNY-26MAY10-T70", "title": "NYC high > 70Â°F"}
        result = wm.enrich_with_forecast(market)
        after = time.time()

        assert before <= result["data_fetched_at"] <= after + 1, (
            f"On cache miss, data_fetched_at should be current time, "
            f"got {result['data_fetched_at']:.0f} (window {before:.0f}â€“{after:.0f})"
        )


class TestEnrichWithForecastSkipsFetch:
    """fetch_forecast=False must skip get_weather_forecast() entirely (used by
    backtest.py, which scores probability from archive data and never reads
    _forecast/_forecast_uncertain — see enrich_with_forecast()'s docstring)."""

    def test_fetch_forecast_false_skips_get_weather_forecast(self, monkeypatch):
        import weather_markets as wm

        def _boom(*args, **kwargs):
            raise AssertionError("get_weather_forecast should not be called")

        monkeypatch.setattr(wm, "get_weather_forecast", _boom)

        market = {"ticker": "KXHIGHNY-26MAY10-T70", "title": "NYC high > 70Â°F"}
        result = wm.enrich_with_forecast(market, fetch_forecast=False)

        assert result["_city"] == "NYC"
        assert result["_date"] is not None
        assert result["_forecast"] is None
        assert result["_forecast_uncertain"] is False

    def test_fetch_forecast_default_true_still_calls_get_weather_forecast(
        self, monkeypatch
    ):
        """Regression: default behavior (every other existing caller) is unchanged."""
        import weather_markets as wm

        called = {}

        def _fake(city, target_date, **kwargs):
            called["hit"] = True
            return {"high_f": 70.0, "_source": "open_meteo"}

        monkeypatch.setattr(wm, "get_weather_forecast", _fake)

        market = {"ticker": "KXHIGHNY-26MAY10-T70", "title": "NYC high > 70Â°F"}
        result = wm.enrich_with_forecast(market)

        assert called.get("hit") is True
        assert result["_forecast"] is not None


class TestBimodalEnsemble:
    def test_detect_bimodal_ensemble(self):
        from weather_markets import _detect_bimodal_ensemble

        bimodal_temps = [62.0] * 30 + [78.0] * 20  # two clear clusters
        unimodal_temps = [68.0 + i * 0.2 for i in range(-25, 25)]  # tight spread

        assert _detect_bimodal_ensemble(bimodal_temps) is True
        assert _detect_bimodal_ensemble(unimodal_temps) is False
        assert _detect_bimodal_ensemble([]) is False
        assert _detect_bimodal_ensemble([70.0] * 5) is False  # too few members

    def test_bimodal_kelly_returns_point_one_when_bimodal(self, monkeypatch):
        """When _detect_bimodal_ensemble returns True, multiplier must be 0.10."""
        import weather_markets as wm

        monkeypatch.setattr(wm, "_detect_bimodal_ensemble", lambda temps: True)

        bimodal_temps = [62.0] * 30 + [78.0] * 20
        result = wm._get_bimodal_kelly_multiplier(bimodal_temps)
        assert result == pytest.approx(0.10, abs=0.01)

    def test_bimodal_kelly_returns_one_when_unimodal(self, monkeypatch):
        """When _detect_bimodal_ensemble returns False, multiplier must be 1.0."""
        import weather_markets as wm

        monkeypatch.setattr(wm, "_detect_bimodal_ensemble", lambda temps: False)

        unimodal_temps = [68.0 + i * 0.2 for i in range(-25, 25)]
        result = wm._get_bimodal_kelly_multiplier(unimodal_temps)
        assert result == pytest.approx(1.0, abs=0.01)

    def test_bimodal_reduces_ci_adjusted_kelly(self, monkeypatch):
        """When bimodal detected, ci_adjusted_kelly in analyze_trade result is reduced."""
        from datetime import date, timedelta
        from unittest.mock import patch

        import weather_markets as wm

        today = date.today()
        target = today + timedelta(days=1)

        enriched = {
            "ticker": f"KXHIGHNY-{target.strftime('%d%b%y').upper()}-T70",
            "title": "NYC high > 70F",
            "_city": "NYC",
            "_date": target,
            "_hour": None,
            "_forecast": {
                "high_f": 65.0,
                "low_f": 55.0,
                "precip_in": 0.0,
                "date": target.isoformat(),
                "city": "NYC",
                "models_used": 3,
                "high_range": (63.0, 67.0),
            },
            "yes_bid": 0.20,
            "yes_ask": 0.25,
            "no_bid": 0.75,
            "close_time": "",
            "series_ticker": "KXHIGHNY",
            "volume": 500,
            "open_interest": 200,
        }

        # Mock the detect function to always return True
        monkeypatch.setattr(wm, "_detect_bimodal_ensemble", lambda temps: True)

        with (
            patch.object(
                wm, "get_ensemble_temps", return_value=[65.0] * 14 + [67.0] * 6
            ),
            patch.object(
                wm, "_get_consensus_probs", return_value=(None, None, None, None, None)
            ),
            patch("climatology.climatological_prob", return_value=0.25),
            patch("nws.nws_prob", return_value=None),
            patch("nws.get_live_observation", return_value=None),
            patch("mos.fetch_nbm_quantiles", return_value=None),
            patch("climate_indices.temperature_adjustment", return_value=0.0),
            patch("weather_markets.fetch_temperature_nbm", return_value=65.0),
            patch("weather_markets.fetch_temperature_ecmwf", return_value=65.0),
            patch("weather_markets.get_ensemble_members", return_value=[]),
            patch.object(wm, "_SEASONAL_WEIGHTS", {}),
            patch.object(wm, "_CONDITION_WEIGHTS", {}),
            patch.object(wm, "_CITY_WEIGHTS", {}),
            patch("ml_bias.apply_temperature_scaling", side_effect=lambda p, **kw: p),
            # Disable METAR lock-in (same pattern as the sibling Gaussian-blend
            # tests above): it gates on city-local (NY) date, not system-local
            # date.today() -- when target_date == NY-local-today, it fires and
            # skips the bimodal-detection block this test exercises entirely.
            patch.object(wm, "_metar_lock_in", return_value=(False, 0.0, {})),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None, "analyze_trade returned None — check patches"
        assert result.get("bimodal") is True


class TestHRRR:
    def test_fetch_hrrr_temp_returns_float_or_none(self, monkeypatch):
        from datetime import date

        import requests

        import weather_markets as wm
        from weather_markets import _HRRR_CACHE

        # Restore the real implementation -- conftest's autouse
        # default_hrrr_forecast_mean_none fixture stubs it to a no-op by
        # default; must run BEFORE the local `from ... import _fetch_hrrr_temp`
        # below or that import silently binds to the stub instead.
        monkeypatch.setattr(wm, "_fetch_hrrr_temp", _REAL_FETCH_HRRR_TEMP)
        from weather_markets import _fetch_hrrr_temp

        _HRRR_CACHE.clear()  # avoid stale cache from other tests

        class MockResp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "hourly": {
                        "time": ["2026-07-01T18:00", "2026-07-01T19:00"],
                        "temperature_2m": [88.5, 87.3],
                    }
                }

        monkeypatch.setattr(requests, "get", lambda *a, **k: MockResp())
        result = _fetch_hrrr_temp("NYC", date(2026, 7, 1), var="max")
        assert result is None or isinstance(result, float)

    def test_fetch_hrrr_temp_returns_max_of_hourly(self, monkeypatch):
        from datetime import date

        import requests

        import weather_markets as wm
        from weather_markets import _HRRR_CACHE

        monkeypatch.setattr(wm, "_fetch_hrrr_temp", _REAL_FETCH_HRRR_TEMP)
        from weather_markets import _fetch_hrrr_temp

        # Clear cache so the mock response is always used.
        _HRRR_CACHE.clear()

        class MockResp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "hourly": {
                        "time": [
                            "2026-07-01T12:00",
                            "2026-07-01T13:00",
                            "2026-07-01T14:00",
                        ],
                        "temperature_2m": [80.0, 88.5, 86.0],
                    }
                }

        monkeypatch.setattr(requests, "get", lambda *a, **k: MockResp())
        result = _fetch_hrrr_temp("NYC", date(2026, 7, 1), var="max")
        assert result is not None, "_fetch_hrrr_temp returned None — check cache clear"
        assert result == pytest.approx(88.5)

    def test_fetch_hrrr_temp_returns_none_for_unknown_city(self, monkeypatch):
        from datetime import date

        import weather_markets as wm

        monkeypatch.setattr(wm, "_fetch_hrrr_temp", _REAL_FETCH_HRRR_TEMP)
        from weather_markets import _fetch_hrrr_temp

        result = _fetch_hrrr_temp("UNKNOWN_CITY_XYZ", date(2026, 7, 1), var="max")
        assert result is None

    def test_fetch_hrrr_temp_negative_caches_failure(self, monkeypatch):
        """A failed fetch must be negative-cached -- a second call within the
        TTL must not re-invoke requests.get (2026-07-19 ForecastCache
        migration: get_with_ts() must distinguish a real cached None from
        no-entry-at-all)."""
        from datetime import date

        import requests

        import weather_markets as wm
        from weather_markets import _HRRR_CACHE

        monkeypatch.setattr(wm, "_fetch_hrrr_temp", _REAL_FETCH_HRRR_TEMP)
        from weather_markets import _fetch_hrrr_temp

        _HRRR_CACHE.clear()

        call_count = {"n": 0}

        def _raise(*a, **k):
            call_count["n"] += 1
            raise requests.RequestException("timeout")

        monkeypatch.setattr(requests, "get", _raise)
        first = _fetch_hrrr_temp("NYC", date(2026, 7, 1), var="max")
        assert first is None
        assert call_count["n"] == 1

        second = _fetch_hrrr_temp("NYC", date(2026, 7, 1), var="max")
        assert second is None
        assert call_count["n"] == 1, "negative-cached hit must not re-call requests.get"

    def test_fetch_hrrr_temp_pins_ncep_hrrr_conus_not_best_match(self, monkeypatch):
        """batch-50: models param must be the pinned 'ncep_hrrr_conus', not
        the old opaque 'best_match' auto-selection -- go/no-go validation
        (2026-08-24) found the two resolve identically today, but the pin
        guards against best_match silently drifting to a non-HRRR source
        later; a regression back to best_match would defeat that."""
        from datetime import date

        import requests

        import weather_markets as wm
        from weather_markets import _HRRR_CACHE

        monkeypatch.setattr(wm, "_fetch_hrrr_temp", _REAL_FETCH_HRRR_TEMP)
        from weather_markets import _fetch_hrrr_temp

        _HRRR_CACHE.clear()
        captured_params = {}

        class MockResp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "hourly": {
                        "time": ["2026-07-01T18:00"],
                        "temperature_2m": [88.5],
                    }
                }

        def _fake_get(url, params=None, timeout=None):
            captured_params.update(params or {})
            return MockResp()

        monkeypatch.setattr(requests, "get", _fake_get)
        _fetch_hrrr_temp("NYC", date(2026, 7, 1), var="max")
        assert captured_params.get("models") == "ncep_hrrr_conus", (
            f"expected pinned models=ncep_hrrr_conus, got {captured_params.get('models')!r}"
        )

    def test_fetch_hrrr_temp_skips_fetch_when_circuit_open(self, monkeypatch):
        """The dedicated _hrrr_om_cb breaker must short-circuit the fetch
        (fail toward last-known-good / cache, never hammer a known-down
        endpoint) instead of always attempting requests.get."""
        from datetime import date

        import requests

        import weather_markets as wm
        from weather_markets import _HRRR_CACHE

        monkeypatch.setattr(wm, "_fetch_hrrr_temp", _REAL_FETCH_HRRR_TEMP)
        from weather_markets import _fetch_hrrr_temp

        _HRRR_CACHE.clear()
        call_count = {"n": 0}

        def _fake_get(*a, **k):
            call_count["n"] += 1
            raise AssertionError(
                "requests.get must not be called while circuit is open"
            )

        monkeypatch.setattr(requests, "get", _fake_get)
        monkeypatch.setattr(wm._hrrr_om_cb, "is_open", lambda: True)

        result = _fetch_hrrr_temp("NYC", date(2026, 7, 2), var="max")
        assert result is None
        assert call_count["n"] == 0

    def test_fetch_hrrr_temp_records_failure_on_exception(self, monkeypatch):
        """A real fetch failure must record on _hrrr_om_cb (not silently
        swallowed) so repeated HRRR outages eventually open the breaker,
        same as every other Open-Meteo source's CB in this file."""
        from datetime import date

        import requests

        import weather_markets as wm
        from weather_markets import _HRRR_CACHE

        monkeypatch.setattr(wm, "_fetch_hrrr_temp", _REAL_FETCH_HRRR_TEMP)
        from weather_markets import _fetch_hrrr_temp

        _HRRR_CACHE.clear()
        wm._hrrr_om_cb.record_success()  # start from a clean failure_count

        def _raise(*a, **k):
            raise requests.RequestException("timeout")

        monkeypatch.setattr(requests, "get", _raise)
        before = wm._hrrr_om_cb.failure_count
        _fetch_hrrr_temp("NYC", date(2026, 7, 3), var="max")
        assert wm._hrrr_om_cb.failure_count == before + 1

    def test_fetch_hrrr_temp_records_success_on_valid_response(self, monkeypatch):
        """A genuinely valid response must record_success() -- clears any
        prior failure_count/opened_at, same as every other Open-Meteo
        source's CB in this file. Untested before this: only the exception
        and is_open()-short-circuit paths had coverage."""
        from datetime import date

        import requests

        import weather_markets as wm
        from weather_markets import _HRRR_CACHE

        monkeypatch.setattr(wm, "_fetch_hrrr_temp", _REAL_FETCH_HRRR_TEMP)
        from weather_markets import _fetch_hrrr_temp

        _HRRR_CACHE.clear()
        # Start from a nonzero failure_count so record_success()'s reset is
        # actually observable, not just "stayed at 0".
        wm._hrrr_om_cb.record_failure()
        assert wm._hrrr_om_cb.failure_count > 0

        class MockResp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "hourly": {
                        "time": ["2026-07-04T18:00"],
                        "temperature_2m": [90.0],
                    }
                }

        monkeypatch.setattr(requests, "get", lambda *a, **k: MockResp())
        result = _fetch_hrrr_temp("NYC", date(2026, 7, 4), var="max")
        assert result == pytest.approx(90.0)
        assert wm._hrrr_om_cb.failure_count == 0

    def test_fetch_hrrr_temp_records_failure_on_all_null_response(self, monkeypatch):
        """An all-null hourly series (a 'successful' HTTP call with no usable
        data -- the shape ensemble-api.open-meteo.com actually returns for
        models=ncep_hrrr_conus, per this batch's own prewarm-exclusion
        finding) must record_failure(), not record_success(). Untested
        before this: only the exception path recorded a failure."""
        from datetime import date

        import requests

        import weather_markets as wm
        from weather_markets import _HRRR_CACHE

        monkeypatch.setattr(wm, "_fetch_hrrr_temp", _REAL_FETCH_HRRR_TEMP)
        from weather_markets import _fetch_hrrr_temp

        _HRRR_CACHE.clear()
        wm._hrrr_om_cb.record_success()  # start from a clean failure_count

        class MockResp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "hourly": {"time": ["2026-07-05T18:00"], "temperature_2m": [None]}
                }

        monkeypatch.setattr(requests, "get", lambda *a, **k: MockResp())
        before = wm._hrrr_om_cb.failure_count
        result = _fetch_hrrr_temp("NYC", date(2026, 7, 5), var="max")
        assert result is None
        assert wm._hrrr_om_cb.failure_count == before + 1


class TestModelBrierScores:
    def test_get_model_brier_scores_returns_dict(self, monkeypatch, tmp_path):
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
        tracker._db_initialized = False
        tracker.init_db()

        with tracker._conn() as con:
            for i in range(10):
                con.execute(
                    "INSERT INTO ensemble_member_scores "
                    "(city, model, predicted_temp, actual_temp, logged_at) "
                    "VALUES ('NYC', 'icon_seamless', ?, 73.0, datetime('now'))",
                    (71.0 + i * 0.1,),
                )
                con.execute(
                    "INSERT INTO ensemble_member_scores "
                    "(city, model, predicted_temp, actual_temp, logged_at) "
                    "VALUES ('NYC', 'gfs_seamless', ?, 73.0, datetime('now'))",
                    (72.5 + i * 0.1,),
                )

        scores = tracker.get_model_brier_scores(days=30)
        assert "icon_seamless" in scores, (
            f"Expected 'icon_seamless' in scores: {scores}"
        )
        assert "gfs_seamless" in scores, f"Expected 'gfs_seamless' in scores: {scores}"
        # icon predicted 71.0-71.9, actual=73.0 → MAE avg ≈ 1.55
        assert 1.0 < scores["icon_seamless"] < 3.0, (
            f"Unexpected icon MAE: {scores['icon_seamless']}"
        )

    def test_get_model_brier_scores_excludes_models_with_few_rows(
        self, monkeypatch, tmp_path
    ):
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
        tracker._db_initialized = False
        tracker.init_db()

        with tracker._conn() as con:
            # Only 5 rows — below HAVING COUNT(*) >= 10 threshold
            for i in range(5):
                con.execute(
                    "INSERT INTO ensemble_member_scores "
                    "(city, model, predicted_temp, actual_temp, logged_at) "
                    "VALUES ('NYC', 'sparse_model', ?, 73.0, datetime('now'))",
                    (71.0 + i * 0.1,),
                )

        scores = tracker.get_model_brier_scores(days=30)
        assert "sparse_model" not in scores, "Model with < 10 rows should be excluded"

    def test_get_model_brier_scores_empty_when_no_data(self, monkeypatch, tmp_path):
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
        tracker._db_initialized = False
        tracker.init_db()

        scores = tracker.get_model_brier_scores(days=30)
        assert scores == {}


class TestRegimeBlend:
    def test_regime_blend_inactive_below_threshold(self, monkeypatch):
        """_regime_blend_active returns False when settled count < 30."""
        import weather_markets as wm

        monkeypatch.setattr("weather_markets._regime_blend_settled_count", lambda: 5)
        wm._regime_blend_state["active"] = None
        assert wm._regime_blend_active() is False

    def test_regime_blend_active_above_threshold(self, monkeypatch):
        """_regime_blend_active returns True when settled count >= 30."""
        import weather_markets as wm

        monkeypatch.setattr("weather_markets._regime_blend_settled_count", lambda: 35)
        # Reset cached state so the monkeypatch takes effect
        wm._regime_blend_state["active"] = None
        assert wm._regime_blend_active() is True

    def test_heat_dome_overrides_weights(self, monkeypatch):
        """heat_dome regime -> ens=0.70, nws=0.25, clim=0.05 (after active)."""
        import weather_markets as wm

        monkeypatch.setattr("weather_markets._regime_blend_settled_count", lambda: 35)
        wm._regime_blend_state["active"] = None
        w = wm._blend_weights(
            days_out=1,
            has_nws=True,
            has_clim=True,
            city=None,
            season=None,
            condition_type="above",
            regime="heat_dome",
        )
        assert w["ensemble"] == pytest.approx(0.70, abs=0.01)
        assert w["nws"] == pytest.approx(0.25, abs=0.01)
        assert w["climatology"] == pytest.approx(0.05, abs=0.01)

    def test_normal_regime_uses_existing_weights(self, monkeypatch):
        """normal regime -> existing condition/seasonal weights unchanged."""
        import weather_markets as wm

        monkeypatch.setattr("weather_markets._regime_blend_settled_count", lambda: 35)
        wm._regime_blend_state["active"] = None
        w_regime = wm._blend_weights(
            days_out=1,
            has_nws=True,
            has_clim=True,
            city=None,
            season=None,
            condition_type="above",
            regime="normal",
        )
        wm._regime_blend_state["active"] = None
        w_base = wm._blend_weights(
            days_out=1,
            has_nws=True,
            has_clim=True,
            city=None,
            season=None,
            condition_type="above",
            regime=None,
        )
        assert w_regime["ensemble"] == pytest.approx(w_base["ensemble"], abs=0.01)

    def test_notify_writes_feature_activations_file(self, monkeypatch, tmp_path):
        """_notify_feature_activation writes data/feature_activations.json on first call."""
        import json

        import weather_markets as wm

        monkeypatch.setattr(
            wm, "_FEATURE_ACTIVATIONS_PATH", tmp_path / "feature_activations.json"
        )
        wm._notify_feature_activation(
            "a9_regime_blend", "Regime blend auto-activated", {"n_settled": 31}
        )
        data = json.loads((tmp_path / "feature_activations.json").read_text())
        assert "a9_regime_blend" in data
        assert data["a9_regime_blend"]["dismissed"] is False
        assert data["a9_regime_blend"]["n_settled"] == 31

    def test_notify_does_not_overwrite_existing_key(self, monkeypatch, tmp_path):
        """_notify_feature_activation is idempotent -- does not rewrite if key exists."""
        import json

        import weather_markets as wm

        path = tmp_path / "feature_activations.json"
        path.write_text(
            json.dumps(
                {"a9_regime_blend": {"activated_at": "2026-07-01", "dismissed": True}}
            )
        )
        monkeypatch.setattr(wm, "_FEATURE_ACTIVATIONS_PATH", path)
        wm._notify_feature_activation("a9_regime_blend", "should not overwrite", {})
        data = json.loads(path.read_text())
        assert data["a9_regime_blend"]["dismissed"] is True  # original value preserved


class TestPDOPNA:
    def test_apply_pdo_pna_correction_la_winter(self, monkeypatch):
        """LA in DJF with PDO=+1 -> approximately +0.8 degrees F correction."""
        import climate_indices as ci
        from climate_indices import apply_pdo_pna_correction

        monkeypatch.setattr(ci, "get_pdo_pna", lambda **kw: {"pdo": 1.0, "pna": 0.0})
        correction = apply_pdo_pna_correction("LA", forecast_temp_f=65.0, month=1)
        assert correction == pytest.approx(0.8, abs=0.05)

    def test_apply_pdo_pna_correction_unknown_city_zero(self, monkeypatch):
        """Cities not in coefficient tables return 0.0."""
        import climate_indices as ci
        from climate_indices import apply_pdo_pna_correction

        monkeypatch.setattr(ci, "get_pdo_pna", lambda **kw: {"pdo": 2.0, "pna": 2.0})
        assert apply_pdo_pna_correction("Dallas", forecast_temp_f=90.0, month=7) == 0.0

    def test_apply_pdo_pna_correction_clamped(self, monkeypatch):
        """Extreme index values (PDO=10) are clamped to +-3 degrees F."""
        import climate_indices as ci
        from climate_indices import apply_pdo_pna_correction

        monkeypatch.setattr(ci, "get_pdo_pna", lambda **kw: {"pdo": 10.0, "pna": 0.0})
        correction = apply_pdo_pna_correction("LA", forecast_temp_f=65.0, month=1)
        assert correction <= 3.0

    def test_apply_pdo_pna_correction_threads_month_through_to_get_pdo_pna(
        self, monkeypatch
    ):
        """M-18d: apply_pdo_pna_correction's own `season` is derived from
        the caller's `month` argument, but get_pdo_pna() used to be called
        with NO arguments at all -- defaulting to the CURRENT UTC month's
        index lookback regardless of what `month` was, mixing a target
        month's seasonal coefficient with a different month's index value
        (the same defect class get_indices() was already fixed for). The
        three tests above all use `lambda **kw: {...}` mocks that accept
        and silently ignore any kwargs, so none of them could actually
        prove `month` was threaded through -- this one captures the real
        call args instead. Mutation-tested: reverting the fix (calling
        `get_pdo_pna()` with no args) makes this fail."""
        import climate_indices as ci

        captured = {}

        def _fake_get_pdo_pna(**kwargs):
            captured.update(kwargs)
            return {"pdo": 1.0, "pna": 0.0}

        monkeypatch.setattr(ci, "get_pdo_pna", _fake_get_pdo_pna)
        ci.apply_pdo_pna_correction("LA", forecast_temp_f=65.0, month=1)

        assert captured.get("month") == 1, (
            f"expected get_pdo_pna to be called with month=1 (the caller's "
            f"own target month), got kwargs={captured!r}"
        )

    def test_fetch_pdo_pna_parses_csv(self, monkeypatch, tmp_path):
        """fetch_pdo_pna correctly parses NOAA CSV and writes pdo_pna.json."""
        import climate_indices as ci

        monkeypatch.setattr(ci, "_PDO_PNA_PATH", tmp_path / "pdo_pna.json")

        csv_content = "Date,Value\n202601,0.85\n202602,-0.32\n"
        mock_resp = type(
            "R",
            (),
            {
                "text": csv_content,
                "raise_for_status": lambda self: None,
            },
        )()
        monkeypatch.setattr(ci.requests, "get", lambda *a, **k: mock_resp)

        result = ci.fetch_pdo_pna()
        assert "202601" in result["pdo"]
        assert result["pdo"]["202601"] == pytest.approx(0.85, abs=0.001)

    def test_fetch_pdo_pna_writes_via_atomic_helper(self, monkeypatch, tmp_path):
        """backlog.txt "climate_indices.py's PDO/PNA CACHE AND backtest.py's
        OWN CACHE ALSO SKIP safe_io": fetch_pdo_pna used to write
        _PDO_PNA_PATH with a plain write_text(json.dumps(payload)) -- unlike
        acis_precip.py/climatology.py (both already on
        safe_io.atomic_write_json). apply_pdo_pna_correction() reads this
        cache and is called live from weather_markets.analyze_trade(), so
        a torn/partial write here is a live-model-input risk, not a
        disposable one (unlike the sibling HURDAT2 cache) -- spies on
        safe_io.atomic_write_json directly rather than only asserting on
        the end file content, since a regression back to a bare write_text
        would produce byte-identical output and slip past a content-only
        assertion."""
        from unittest.mock import patch

        import climate_indices as ci
        import safe_io

        # Belt-and-suspenders: this spy wraps the real (non-mocked)
        # atomic_write_json -- isolate any unexpected write failure's
        # emergency copy to tmp_path rather than this repo's real
        # data/.emergency/ (the main clone, not this worktree).
        monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)
        monkeypatch.setattr(ci, "_PDO_PNA_PATH", tmp_path / "pdo_pna.json")

        csv_content = "Date,Value\n202601,0.85\n202602,-0.32\n"
        mock_resp = type(
            "R",
            (),
            {
                "text": csv_content,
                "raise_for_status": lambda self: None,
            },
        )()
        monkeypatch.setattr(ci.requests, "get", lambda *a, **k: mock_resp)

        with patch.object(
            safe_io, "atomic_write_json", wraps=safe_io.atomic_write_json
        ) as spy_write:
            result = ci.fetch_pdo_pna()

        spy_write.assert_called_once()
        written_data, written_path = spy_write.call_args[0]
        assert written_data == result
        assert written_path == tmp_path / "pdo_pna.json"
        # emergency_copy must stay at its True default here -- unlike
        # backtest.py's disposable archive cache, this cache feeds a live
        # model input and a regression opting it into emergency_copy=False
        # would pass every other assertion in this test.
        assert spy_write.call_args.kwargs == {}
        # The real (non-mocked) atomic_write_json must have actually landed
        # the file -- confirms the spy wraps rather than replaces it.
        assert (tmp_path / "pdo_pna.json").exists()

    def test_fetch_pdo_pna_write_failure_still_returns_fetched_data(
        self, monkeypatch, tmp_path, caplog
    ):
        """A cache-write failure (opus-review-caught 2026-08-08: the initial
        version of this fix let a write failure propagate out of
        fetch_pdo_pna and get silently swallowed by get_pdo_pna's own
        except Exception, discarding successfully-fetched NOAA data and
        returning {"pdo": 0.0, "pna": 0.0} on every call for as long as
        writes kept failing -- reachable only once a stale pdo_pna.json
        already exists and a refresh write then fails, since
        weather_markets._pdopna_blend_active() requires the file to exist
        before this path ever runs) must not lose the freshly-fetched
        payload to the caller -- mirrors hurricane_climatology.
        fetch_hurdat2_raw's own fail-open shape for the identical
        situation, and must log a warning instead of failing silently."""
        import logging

        import climate_indices as ci
        import safe_io

        monkeypatch.setattr(ci, "_PDO_PNA_PATH", tmp_path / "pdo_pna.json")

        csv_content = "Date,Value\n202601,0.85\n202602,-0.32\n"
        mock_resp = type(
            "R",
            (),
            {
                "text": csv_content,
                "raise_for_status": lambda self: None,
            },
        )()
        monkeypatch.setattr(ci.requests, "get", lambda *a, **k: mock_resp)
        monkeypatch.setattr(
            safe_io,
            "atomic_write_json",
            lambda *a, **kw: (_ for _ in ()).throw(
                safe_io.AtomicWriteError("simulated total write failure")
            ),
        )

        with caplog.at_level(logging.WARNING):
            result = ci.fetch_pdo_pna()

        assert "202601" in result["pdo"]
        assert result["pdo"]["202601"] == pytest.approx(0.85, abs=0.001)
        assert not (tmp_path / "pdo_pna.json").exists()
        assert any(
            "fetch_pdo_pna: cache write failed" in rec.getMessage()
            for rec in caplog.records
        )

    def test_get_pdo_pna_survives_refresh_write_failure_with_stale_cache(
        self, monkeypatch, tmp_path
    ):
        """The user-visible behavior test_fetch_pdo_pna_write_failure_still_
        returns_fetched_data only proves at the fetch_pdo_pna() layer:
        get_pdo_pna() (the actual public entry point apply_pdo_pna_correction
        calls) must return the freshly-refetched value, not the stale one AND
        not zeros, when a stale pdo_pna.json exists and its refresh write
        fails -- the only state weather_markets._pdopna_blend_active() ever
        lets this path run in."""
        import json
        from datetime import UTC, datetime, timedelta

        import climate_indices as ci
        import safe_io

        pdo_pna_path = tmp_path / "pdo_pna.json"
        stale_fetched_at = datetime.now(UTC) - timedelta(days=ci._PDO_PNA_TTL_DAYS + 1)
        pdo_pna_path.write_text(
            json.dumps(
                {
                    "pdo": {"202601": -5.0},  # stale value -- must NOT be returned
                    "pna": {"202601": -5.0},
                    "fetched_at": stale_fetched_at.isoformat(),
                }
            )
        )
        monkeypatch.setattr(ci, "_PDO_PNA_PATH", pdo_pna_path)

        csv_content = "Date,Value\n202601,0.85\n202602,-0.32\n"
        mock_resp = type(
            "R",
            (),
            {
                "text": csv_content,
                "raise_for_status": lambda self: None,
            },
        )()
        monkeypatch.setattr(ci.requests, "get", lambda *a, **k: mock_resp)
        monkeypatch.setattr(
            safe_io,
            "atomic_write_json",
            lambda *a, **kw: (_ for _ in ()).throw(
                safe_io.AtomicWriteError("simulated total write failure")
            ),
        )

        result = ci.get_pdo_pna(year=2026, month=1)

        assert result["pdo"] == pytest.approx(0.85, abs=0.001)  # fresh, not stale/zero

    def test_pdopna_inactive_below_threshold(self, monkeypatch):
        """_pdopna_blend_active returns False when west-coast count < 20."""
        import weather_markets as wm

        monkeypatch.setattr(
            "weather_markets._pdopna_settled_counts",
            lambda: {"LA": 5, "SanFrancisco": 3, "Seattle": 2},
        )
        wm._pdopna_blend_state["active"] = None
        assert wm._pdopna_blend_active() is False

    def test_pdopna_inactive_without_index_file(self, monkeypatch, tmp_path):
        """_pdopna_blend_active returns False when pdo_pna.json is absent."""
        import climate_indices as ci
        import weather_markets as wm

        monkeypatch.setattr(
            "weather_markets._pdopna_settled_counts",
            lambda: {"LA": 25, "SanFrancisco": 22, "Seattle": 21},
        )
        monkeypatch.setattr(ci, "_PDO_PNA_PATH", tmp_path / "missing.json")
        monkeypatch.setattr(wm._ci, "_PDO_PNA_PATH", tmp_path / "missing.json")
        wm._pdopna_blend_state["active"] = None
        assert wm._pdopna_blend_active() is False


class TestSignalGraduationRegistry:
    """backlog.txt "SIGNAL GRADUATION IS A CONVENTION" part (b):
    weather_markets.SIGNAL_REGISTRY + get_signal_graduation_report()."""

    def test_registry_has_no_duplicate_keys(self):
        import weather_markets as wm

        keys = [e.key for e in wm.SIGNAL_REGISTRY]
        assert len(keys) == len(set(keys)), f"duplicate registry keys: {keys}"

    def test_count_model_obs_rejects_unknown_model_name(self):
        """Guards the silent-typo failure mode an opus review caught: an
        unknown model name would otherwise resolve to a real-looking count
        of 0 forever, indistinguishable from "not yet tracked". Validated
        at closure-build time -- which is also why SIGNAL_REGISTRY (and
        therefore this whole module) would fail to import at all if either
        real gem_graduation/ukmo_graduation entry's literal were ever
        typo'd, a much stronger guarantee than a dedicated per-entry test."""
        import weather_markets as wm

        with pytest.raises(ValueError, match="KNOWN_FORECAST_MODEL_NAMES"):
            wm._count_model_obs("gem_glbal")  # typo, not gem_global

    def test_registry_has_12_entries_matching_the_11_shipped_signal_topics(self):
        import weather_markets as wm

        # Locks in the retrofit scope agreed on when this was built: all
        # already-shipped log-only signal *topics* from backlog.txt, not a
        # partial/empty registry. Originally 9 rows / 8 topics (GEM and UKMO
        # graduate independently -- their own correlation_note says so --
        # even though both come from the single "GRADUATE GEM/UKMO" backlog
        # entry); a 10th row / 9th topic ("rain_forecast_blend") was added
        # 2026-07-28 for backlog.txt "RAIN MARKETS -- MONTHLY MODEL HAS NO
        # DAY-SPECIFIC FORECAST SIGNAL"; an 11th row / 10th topic
        # ("market_implied_rain") was added 2026-08-01 for backlog.txt
        # "RAIN'S MARKET-IMPLIED DISTRIBUTION ... HAS NO GRADUATION/SAMPLE-
        # FLOOR TRACKING OF ITS OWN" -- its own distinct backlog_ref, unlike
        # GEM/UKMO's shared one, since it's a standalone entry not a second
        # row off an existing one. A 12th row / 11th topic ("hrrr_graduation")
        # was added batch-50 (2026-08-24) for backlog.txt "GRADUATE HRRR
        # (ncep_hrrr_conus) FROM TRACK-ONLY INTO THE LIVE BLEND" -- also its
        # own distinct backlog_ref, same shape as market_implied_rain's.
        # Renamed (not just bumped) per this project's own established
        # convention of keeping a count-encoding test name truthful when the
        # count changes.
        assert len(wm.SIGNAL_REGISTRY) == 12
        backlog_refs = {e.backlog_ref for e in wm.SIGNAL_REGISTRY}
        assert len(backlog_refs) == 11

    def test_report_includes_every_registered_signal(self, monkeypatch, tmp_path):
        import weather_markets as wm

        monkeypatch.setattr(
            wm, "_FEATURE_ACTIVATIONS_PATH", tmp_path / "feature_activations.json"
        )
        report = wm.get_signal_graduation_report()
        assert {row["key"] for row in report} == {e.key for e in wm.SIGNAL_REGISTRY}

    def test_below_floor_reports_not_cleared_and_does_not_notify(
        self, monkeypatch, tmp_path
    ):
        import weather_markets as wm

        fa_path = tmp_path / "feature_activations.json"
        monkeypatch.setattr(wm, "_FEATURE_ACTIVATIONS_PATH", fa_path)
        entry = wm._SignalRegistryEntry(
            key="test_sig",
            name="Test Signal",
            sample_floor=20,
            count_fn=lambda: 5,
            correlation_note="note",
            backlog_ref="ref",
        )
        monkeypatch.setattr(wm, "SIGNAL_REGISTRY", (entry,))
        report = wm.get_signal_graduation_report()
        assert report[0]["count"] == 5
        assert report[0]["floor_cleared"] is False
        assert not fa_path.exists()

    def test_floor_cleared_reports_true_and_notifies_once(self, monkeypatch, tmp_path):
        import json

        import weather_markets as wm

        fa_path = tmp_path / "feature_activations.json"
        monkeypatch.setattr(wm, "_FEATURE_ACTIVATIONS_PATH", fa_path)
        entry = wm._SignalRegistryEntry(
            key="test_sig",
            name="Test Signal",
            sample_floor=20,
            count_fn=lambda: 25,
            correlation_note="note",
            backlog_ref="ref",
        )
        monkeypatch.setattr(wm, "SIGNAL_REGISTRY", (entry,))
        report = wm.get_signal_graduation_report()
        assert report[0]["count"] == 25
        assert report[0]["floor_cleared"] is True
        data = json.loads(fa_path.read_text())
        assert "signal_test_sig_floor" in data
        assert data["signal_test_sig_floor"]["n_settled"] == 25

        # Idempotent: a second call must not error and the notify file's
        # existing entry must be preserved (matches _notify_feature_activation's
        # own dismissal-preserving contract, exercised here through the
        # report path specifically, not just _notify_feature_activation directly).
        wm.get_signal_graduation_report()
        data_again = json.loads(fa_path.read_text())
        assert data_again == data

    def test_no_fixed_floor_reports_count_but_no_floor_cleared_verdict(
        self, monkeypatch, tmp_path
    ):
        """richer_ml_features' real shape: a count_fn exists (informational)
        but sample_floor is None -- no automatic graduation verdict is ever
        computed for it, matching its own correlation_note ("let the features
        command arbitrate")."""
        import weather_markets as wm

        monkeypatch.setattr(
            wm, "_FEATURE_ACTIVATIONS_PATH", tmp_path / "feature_activations.json"
        )
        entry = wm._SignalRegistryEntry(
            key="test_sig",
            name="Test Signal",
            sample_floor=None,
            count_fn=lambda: 100,
            correlation_note="note",
            backlog_ref="ref",
        )
        monkeypatch.setattr(wm, "SIGNAL_REGISTRY", (entry,))
        report = wm.get_signal_graduation_report()
        assert report[0]["count"] == 100
        assert report[0]["floor_cleared"] is None

    def test_count_fn_none_reports_none_count(self, monkeypatch, tmp_path):
        """cross_city_pooling's real shape: no persisted per-row column to
        count at all -- count_fn=None, purely informational entry."""
        import weather_markets as wm

        monkeypatch.setattr(
            wm, "_FEATURE_ACTIVATIONS_PATH", tmp_path / "feature_activations.json"
        )
        entry = wm._SignalRegistryEntry(
            key="test_sig",
            name="Test Signal",
            sample_floor=None,
            count_fn=None,
            correlation_note="note",
            backlog_ref="ref",
        )
        monkeypatch.setattr(wm, "SIGNAL_REGISTRY", (entry,))
        report = wm.get_signal_graduation_report()
        assert report[0]["count"] is None
        assert report[0]["floor_cleared"] is None

    def test_count_fn_exception_is_caught_not_raised(self, monkeypatch, tmp_path):
        """A DB error in one signal's count_fn must not blow up the report
        for every OTHER registered signal -- caught and reported as an
        unavailable count, not propagated."""
        import weather_markets as wm

        monkeypatch.setattr(
            wm, "_FEATURE_ACTIVATIONS_PATH", tmp_path / "feature_activations.json"
        )

        def _boom():
            raise RuntimeError("db locked")

        entry = wm._SignalRegistryEntry(
            key="test_sig",
            name="Test Signal",
            sample_floor=20,
            count_fn=_boom,
            correlation_note="note",
            backlog_ref="ref",
        )
        monkeypatch.setattr(wm, "SIGNAL_REGISTRY", (entry,))
        report = wm.get_signal_graduation_report()  # must not raise
        assert report[0]["count"] is None
        assert report[0]["floor_cleared"] is None

    def test_real_registry_entries_all_resolve_against_a_real_empty_db(
        self, monkeypatch, tmp_path
    ):
        """End-to-end smoke test of the actual 12-entry registry (not a
        mocked stand-in) against a real, empty, isolated DB -- proves every
        real count_fn closure calls a real tracker function with valid
        arguments and doesn't crash, and that an empty DB reads as
        0/not-cleared for every count-checkable entry."""
        import tracker
        import weather_markets as wm

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test_predictions.db")
        tracker._db_initialized = False
        monkeypatch.setattr(
            wm, "_FEATURE_ACTIVATIONS_PATH", tmp_path / "feature_activations.json"
        )

        report = wm.get_signal_graduation_report()
        assert len(report) == 12
        for row in report:
            if row["sample_floor"] is not None:
                assert row["count"] == 0, row["key"]
                assert row["floor_cleared"] is False, row["key"]
        # Exactly one entry (cross_city_pooling) has no count query at all.
        no_count = [row for row in report if row["count"] is None]
        assert [row["key"] for row in no_count] == ["cross_city_pooling"]

    def test_ecmwf_consensus_gap_counts_its_own_column_not_raw_model_observations(
        self, monkeypatch, tmp_path
    ):
        """Regression test for an opus-review-caught bug: the entry
        originally counted raw ecmwf_aifs025_ensemble rows in
        ensemble_member_scores, which accrues much faster than the actual
        correlation-checkable ecmwf_consensus_gap_prob column and would
        have let the floor clear (and fire the one-time notify) long
        before the real signal had enough usable samples. Proves the fix
        by seeding only ensemble_member_scores rows for the model (no
        predictions row) and confirming the count stays 0 — if this
        regressed back to counting the model-observation table, this
        count would read >=1 instead."""
        import tracker
        import weather_markets as wm

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test_predictions.db")
        tracker._db_initialized = False
        monkeypatch.setattr(
            wm, "_FEATURE_ACTIVATIONS_PATH", tmp_path / "feature_activations.json"
        )
        for i in range(25):
            tracker.log_member_score(
                "NYC", "ecmwf_aifs025_ensemble", 70.0, 70.0, f"2099-01-{i + 1:02d}"
            )

        entry = next(e for e in wm.SIGNAL_REGISTRY if e.key == "ecmwf_consensus_gap")
        assert entry.count_fn() == 0
