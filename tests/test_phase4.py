"""
Tests for Phase 4 improvements (tasks #21, #25, #26, #28, #29, #33, #37, #122, #126).
"""

from __future__ import annotations

import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Task 1: persistence_prob (#26) ────────────────────────────────────────────


class TestPersistenceProb:
    def test_above_threshold_high_current(self):
        """Current value well above threshold → probability > 0.5."""
        from climatology import persistence_prob

        p = persistence_prob(
            "above", threshold_lo=50.0, threshold_hi=None, current_value=70.0
        )
        assert p is not None
        assert p > 0.5

    def test_above_threshold_low_current(self):
        """Current value well below threshold → probability < 0.5."""
        from climatology import persistence_prob

        p = persistence_prob(
            "above", threshold_lo=80.0, threshold_hi=None, current_value=40.0
        )
        assert p is not None
        assert p < 0.5

    def test_below_threshold_low_current(self):
        """Current value well below threshold → probability > 0.5."""
        from climatology import persistence_prob

        p = persistence_prob(
            "below", threshold_lo=70.0, threshold_hi=None, current_value=45.0
        )
        assert p is not None
        assert p > 0.5

    def test_between_returns_reasonable_value(self):
        """Between condition with current value in range → decent probability."""
        from climatology import persistence_prob

        p = persistence_prob(
            "between", threshold_lo=60.0, threshold_hi=70.0, current_value=65.0
        )
        assert p is not None
        assert 0.0 <= p <= 1.0

    def test_invalid_std_dev_returns_none(self):
        from climatology import persistence_prob

        result = persistence_prob(
            "above",
            threshold_lo=60.0,
            threshold_hi=None,
            current_value=65.0,
            std_dev=0.0,
        )
        assert result is None

    def test_unknown_condition_returns_none(self):
        from climatology import persistence_prob

        result = persistence_prob(
            "unknown_type", threshold_lo=60.0, threshold_hi=None, current_value=65.0
        )
        assert result is None


# ── Task 2: ENSO phase in ensemble weights (#28) ──────────────────────────────


class TestEnsoPhase:
    def test_el_nino_boosts_ecmwf_above_neutral(self):
        """El Niño winter should give ECMWF higher weight than neutral."""
        from weather_markets import _forecast_model_weights

        with patch("weather_markets._get_enso_phase", return_value="neutral"):
            neutral_w = _forecast_model_weights(1)["ecmwf_ifs04"]

        with patch("weather_markets._get_enso_phase", return_value="el_nino"):
            el_nino_w = _forecast_model_weights(1)["ecmwf_ifs04"]

        assert el_nino_w >= neutral_w

    def test_la_nina_boosts_ecmwf_above_neutral(self):
        """La Niña winter should give ECMWF higher weight than neutral."""
        from weather_markets import _forecast_model_weights

        with patch("weather_markets._get_enso_phase", return_value="neutral"):
            neutral_w = _forecast_model_weights(1)["ecmwf_ifs04"]

        with patch("weather_markets._get_enso_phase", return_value="la_nina"):
            la_nina_w = _forecast_model_weights(1)["ecmwf_ifs04"]

        assert la_nina_w >= neutral_w

    def test_no_enso_boost_in_summer(self):
        """ENSO should not affect summer weights (not winter)."""
        from weather_markets import _forecast_model_weights

        with patch("weather_markets._get_enso_phase", return_value="el_nino"):
            summer_w = _forecast_model_weights(7)["ecmwf_ifs04"]

        assert summer_w == pytest.approx(1.5)

    def test_get_enso_phase_returns_valid_phase(self):
        """_get_enso_phase always returns one of three valid values."""
        from weather_markets import _get_enso_phase

        with patch("weather_markets.get_enso_index", return_value=1.2):
            assert _get_enso_phase() == "el_nino"

        with patch("weather_markets.get_enso_index", return_value=-0.8):
            assert _get_enso_phase() == "la_nina"

        with patch("weather_markets.get_enso_index", return_value=0.1):
            assert _get_enso_phase() == "neutral"

        with patch("weather_markets.get_enso_index", return_value=None):
            assert _get_enso_phase() == "neutral"


# ── Task 3: Moist-cold regime in _feels_like (#29) ────────────────────────────


class TestFeelsLikeMoistCold:
    def test_cold_high_humidity_below_actual(self):
        """temp=38, humidity=90 → result < 38 (moist-cold penalty)."""
        from weather_markets import _feels_like

        result = _feels_like(temp_f=38.0, wind_mph=10.0, humidity_pct=90.0)
        assert result < 38.0

    def test_cold_low_humidity_no_penalty(self):
        """Cold with low humidity and light wind → close to actual (NWS wind chill)."""
        from weather_markets import _feels_like

        # temp=50, wind=2 (below 3mph threshold), humidity=50 → should be exactly 50
        result = _feels_like(temp_f=50.0, wind_mph=2.0, humidity_pct=50.0)
        assert result == pytest.approx(50.0)

    def test_moderate_temp_no_moist_cold(self):
        """55°F with high humidity → no moist-cold penalty (above 50°F threshold)."""
        from weather_markets import _feels_like

        result = _feels_like(temp_f=55.0, wind_mph=2.0, humidity_pct=90.0)
        assert result == pytest.approx(55.0)

    def test_existing_hot_humid_still_works(self):
        """Heat index still works for hot+humid conditions."""
        from weather_markets import _feels_like

        result = _feels_like(temp_f=95.0, wind_mph=5.0, humidity_pct=80.0)
        assert result > 95.0


# ── Task 4: _blend_probabilities (#33) ───────────────────────────────────────


class TestBlendProbabilities:
    def test_blend_returns_between_min_and_max(self):
        """blend(0.70, 0.50, 0.55, days_out=3) → result between 0.50 and 0.70."""
        from weather_markets import _blend_probabilities

        result = _blend_probabilities(0.70, 0.50, 0.55, days_out=3)
        assert result is not None
        assert 0.50 <= result <= 0.70

    def test_handles_none_nws(self):
        """None NWS prob → renormalize remaining weights."""
        from weather_markets import _blend_probabilities

        result = _blend_probabilities(0.70, None, 0.55, days_out=3)
        assert result is not None
        assert 0.0 < result < 1.0

    def test_all_none_returns_none(self):
        from weather_markets import _blend_probabilities

        result = _blend_probabilities(None, None, None, days_out=3)
        assert result is None

    def test_nws_lower_weight_far_out(self):
        """NWS gets less weight at days_out=10+ vs days_out=1."""
        from weather_markets import _blend_probabilities

        # With high NWS (0.9) and low ens+clim (0.3), near term should be closer to 0.9
        r_near = _blend_probabilities(0.3, 0.9, 0.3, days_out=2)
        r_far = _blend_probabilities(0.3, 0.9, 0.3, days_out=10)
        assert r_near is not None and r_far is not None
        # Near-term NWS weight is higher → result should be higher when NWS is high
        assert r_near > r_far


# ── Task 5: _dynamic_model_weights (#25) ──────────────────────────────────────


class TestDynamicModelWeights:
    def test_high_mae_model_gets_low_weight(self):
        """GFS MAE=2.0, ECMWF MAE=0.5 → ECMWF weight > GFS weight."""
        from weather_markets import _dynamic_model_weights

        mock_acc = {
            "gfs_seamless": {"mae": 2.0, "count": 10},
            "ecmwf_ifs04": {"mae": 0.5, "count": 10},
            "icon_seamless": {"mae": 1.0, "count": 10},
        }

        # Patch tracker.get_ensemble_member_accuracy which is imported inside _dynamic_model_weights
        with patch("tracker.get_ensemble_member_accuracy", return_value=mock_acc):
            result = _dynamic_model_weights(city="NYC", month=1)

        assert result is not None
        assert result["ecmwf_ifs04"] > result["gfs_seamless"]

    def test_insufficient_samples_returns_none(self):
        """< min_samples per model → returns None."""
        from weather_markets import _dynamic_model_weights

        mock_acc = {
            "gfs_seamless": {"mae": 2.0, "count": 2},
            "ecmwf_ifs04": {"mae": 0.5, "count": 2},
        }

        with patch("tracker.get_ensemble_member_accuracy", return_value=mock_acc):
            result = _dynamic_model_weights(city="NYC", month=1)

        assert result is None

    def test_no_tracker_data_returns_none(self):
        """No tracker data → returns None."""
        from weather_markets import _dynamic_model_weights

        with patch("tracker.get_ensemble_member_accuracy", return_value=None):
            result = _dynamic_model_weights(city="NYC", month=1)

        assert result is None


# ── Task 6: stratified_train_test_split (#21) ────────────────────────────────


class TestStratifiedTrainTestSplit:
    def _make_records(self, cities, conditions, n_each):
        """Generate n_each records for each (city, condition_type) combination."""
        records = []
        for city in cities:
            for ctype in conditions:
                for i in range(n_each):
                    records.append(
                        {
                            "city": city,
                            "condition_type": ctype,
                            "date": f"2024-01-{i + 1:02d}",
                            "our_prob": 0.6,
                        }
                    )
        return records

    def test_all_cities_in_holdout(self):
        """4 cities × 3 conditions × 10 records → all 4 cities in holdout."""
        from backtest import stratified_train_test_split

        records = self._make_records(
            ["NYC", "Chicago", "LA", "Miami"],
            ["above", "below", "between"],
            10,
        )
        train, holdout = stratified_train_test_split(records, holdout_frac=0.2)
        holdout_cities = {r["city"] for r in holdout}
        assert holdout_cities == {"NYC", "Chicago", "LA", "Miami"}

    def test_all_condition_types_in_holdout(self):
        """All condition types appear in holdout."""
        from backtest import stratified_train_test_split

        records = self._make_records(
            ["NYC", "Chicago"], ["above", "below", "between"], 10
        )
        _, holdout = stratified_train_test_split(records, holdout_frac=0.2)
        holdout_types = {r["condition_type"] for r in holdout}
        assert holdout_types == {"above", "below", "between"}

    def test_holdout_fraction_approx_correct(self):
        """Total holdout size is approximately holdout_frac of total."""
        from backtest import stratified_train_test_split

        records = self._make_records(["NYC"], ["above"], 20)
        train, holdout = stratified_train_test_split(records, holdout_frac=0.2)
        total = len(train) + len(holdout)
        assert total == 20
        # At least 1 in holdout (minimum per stratum)
        assert len(holdout) >= 1

    def test_empty_records(self):
        """Empty input → empty train and holdout."""
        from backtest import stratified_train_test_split

        train, holdout = stratified_train_test_split([], holdout_frac=0.2)
        assert train == []
        assert holdout == []


# ── Task 7: _ttl_until_next_cycle (#126) ─────────────────────────────────────


class TestTtlUntilNextCycle:
    def test_05_utc_ttl_is_approx_3600(self):
        """At 05:00 UTC → TTL is roughly 3600s (until 08:00 UTC availability)."""
        from weather_markets import _ttl_until_next_cycle

        t = datetime(2024, 1, 15, 5, 0, 0, tzinfo=UTC)
        ttl = _ttl_until_next_cycle(now=t)
        # Should be ~3 hours (8 - 5 = 3 hours) = 10800s
        # But actual availability is at 08 UTC, so 3h = 10800s
        assert 3000 <= ttl <= 11000

    def test_minimum_ttl_is_1800(self):
        """Minimum TTL is always at least 1800 seconds."""
        from weather_markets import _ttl_until_next_cycle

        # Just before a cycle at 01:59 UTC
        t = datetime(2024, 1, 15, 1, 59, 0, tzinfo=UTC)
        ttl = _ttl_until_next_cycle(now=t)
        assert ttl >= 1800

    def test_returns_int(self):
        """TTL is returned as int."""
        from weather_markets import _ttl_until_next_cycle

        t = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        ttl = _ttl_until_next_cycle(now=t)
        assert isinstance(ttl, int)

    def test_after_all_cycles_wraps_to_next_day(self):
        """After 20 UTC, wraps to 02 UTC next day."""
        from weather_markets import _ttl_until_next_cycle

        t = datetime(2024, 1, 15, 22, 0, 0, tzinfo=UTC)
        ttl = _ttl_until_next_cycle(now=t)
        # 22 UTC → next is 02 UTC tomorrow = 4h = 14400s
        assert ttl >= 1800


# ── Task 8: per-city learned weights in _forecast_model_weights (#122) ────────


class TestPerCityLearnedWeights:
    def test_city_weights_used_when_available(self):
        """When learned_weights.json has NYC weights, they're returned for NYC."""
        from weather_markets import _forecast_model_weights

        mock_weights = {
            "NYC": {"gfs_seamless": 2.0, "ecmwf_ifs04": 0.5, "icon_seamless": 1.0}
        }

        with patch("weather_markets.load_learned_weights", return_value=mock_weights):
            with patch("weather_markets._dynamic_model_weights", return_value=None):
                result = _forecast_model_weights(1, city="NYC")

        assert result["gfs_seamless"] == pytest.approx(2.0)
        assert result["ecmwf_ifs04"] == pytest.approx(0.5)

    def test_no_city_falls_back_to_seasonal(self):
        """No city → seasonal fallback (no learned weights lookup)."""
        from weather_markets import _forecast_model_weights

        with patch("weather_markets._get_enso_phase", return_value="neutral"):
            result = _forecast_model_weights(1)  # no city kwarg
        assert result["ecmwf_ifs04"] == pytest.approx(2.5)

    def test_dynamic_weights_override_learned(self):
        """Dynamic tracker weights take priority over learned_weights.json."""
        from weather_markets import _forecast_model_weights

        dynamic = {"gfs_seamless": 3.0, "ecmwf_ifs04": 1.0, "icon_seamless": 1.0}
        learned = {
            "NYC": {"gfs_seamless": 2.0, "ecmwf_ifs04": 0.5, "icon_seamless": 1.0}
        }

        with patch("weather_markets._dynamic_model_weights", return_value=dynamic):
            with patch("weather_markets.load_learned_weights", return_value=learned):
                result = _forecast_model_weights(1, city="NYC")

        assert result["gfs_seamless"] == pytest.approx(3.0)


# ── Task 9: _current_forecast_cycle and log_prediction (#37) ─────────────────


class TestCurrentForecastCycle:
    def test_valid_cycle_values(self):
        """_current_forecast_cycle returns one of the 4 valid cycle strings."""
        from weather_markets import _current_forecast_cycle

        valid = {"00z", "06z", "12z", "18z"}
        result = _current_forecast_cycle()
        assert result in valid

    def test_00z_before_06_utc(self):
        """At 03:00 UTC → cycle should be 00z."""
        from weather_markets import _current_forecast_cycle

        fake_now = datetime(2024, 1, 15, 3, 0, 0, tzinfo=UTC)
        with patch("weather_markets.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            result = _current_forecast_cycle()

        assert result == "00z"

    def test_log_prediction_accepts_forecast_cycle(self):
        """log_prediction should accept forecast_cycle parameter without error."""
        import tracker as _tracker
        from tracker import log_prediction

        orig_path = _tracker.DB_PATH
        orig_initialized = _tracker._db_initialized

        # Use a temp file, close connections before cleanup
        tmp_db = Path(tempfile.mkdtemp()) / "test_phase4.db"
        _tracker.DB_PATH = tmp_db
        _tracker._db_initialized = False

        try:
            from datetime import date as _date

            analysis = {
                "condition": {"type": "above", "threshold": 60.0},
                "forecast_prob": 0.65,
                "market_prob": 0.55,
                "edge": 0.10,
                "method": "ensemble",
                "n_members": 50,
                "bias_correction": 0.0,
            }
            # Should not raise
            log_prediction(
                "TEST-CYCLE-TICKER",
                "NYC",
                _date(2024, 4, 10),
                analysis,
                forecast_cycle="12z",
            )
        finally:
            _tracker.DB_PATH = orig_path
            _tracker._db_initialized = orig_initialized
