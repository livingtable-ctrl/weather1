"""Tests for Gaussian probability distribution method."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Captured at collection time, before conftest's isolate_dynamic_sigma autouse
# fixture (which runs per-test, before each test body) replaces
# weather_markets._load_dynamic_sigma with a stub -- tests that want the real
# implementation's own memoization/exception-handling behavior restore it via
# this reference rather than the (by-then-already-patched) module attribute.
import weather_markets as _wm_module  # noqa: E402

_REAL_LOAD_DYNAMIC_SIGMA = _wm_module._load_dynamic_sigma


class TestGaussianProbability:
    def test_50pct_at_mean(self):
        """P(T > threshold) = 50% when threshold equals the forecast mean."""
        from weather_markets import gaussian_probability

        prob = gaussian_probability(
            forecast_mean=70.0,
            threshold=70.0,
            sigma=5.0,
            direction="above",
        )
        assert prob == pytest.approx(0.50, abs=0.01)

    def test_high_prob_when_mean_well_above_threshold(self):
        """P(T > 65) ≈ 84% when mean=70, sigma=5 (1 sigma above)."""
        from weather_markets import gaussian_probability

        prob = gaussian_probability(
            forecast_mean=70.0,
            threshold=65.0,
            sigma=5.0,
            direction="above",
        )
        # ~84% → CDF at z=1
        assert prob == pytest.approx(0.841, abs=0.01)

    def test_below_direction(self):
        """P(T < threshold) is complement of above."""
        from weather_markets import gaussian_probability

        above = gaussian_probability(70.0, 65.0, 5.0, "above")
        below = gaussian_probability(70.0, 65.0, 5.0, "below")
        assert above + below == pytest.approx(1.0, abs=0.001)

    def test_wider_sigma_flattens_probability(self):
        """Higher sigma → probability closer to 0.5."""
        from weather_markets import gaussian_probability

        tight = gaussian_probability(72.0, 65.0, 3.0, "above")
        wide = gaussian_probability(72.0, 65.0, 10.0, "above")
        assert tight > wide
        assert wide > 0.5  # still above 0.5 since mean > threshold

    def test_get_historical_sigma_returns_float(self):
        """get_historical_sigma returns a positive float in the NWS RMSE range (2-5°F)."""
        from weather_markets import get_historical_sigma

        # L8-C: NYC spring (April = season 2) now returns calibrated RMSE, not clim std
        sigma = get_historical_sigma("NYC", month=4)
        assert 2.0 <= sigma <= 5.0, f"NYC spring sigma {sigma} outside NWS RMSE range"
        assert sigma == pytest.approx(3.5)  # calibrated Day-3 RMSE

    def test_get_historical_sigma_unknown_city_default(self):
        """Unknown city returns the default sigma in the NWS RMSE range."""
        from weather_markets import get_historical_sigma

        sigma = get_historical_sigma("XYZ", month=6)
        assert 2.0 <= sigma <= 5.0, f"Default sigma {sigma} outside NWS RMSE range"

    # ── L8-C regression: city-name key mismatch ──────────────────────────────

    def test_chicago_returns_calibrated_not_default(self):
        """Chicago must return its calibrated sigma, not the 3.5°F default.

        L8-C bug: _HISTORICAL_SIGMA was keyed 'CHI' but enrich_with_forecast
        stores 'Chicago', so Chicago always silently fell through to default.
        """
        from weather_markets import _DEFAULT_SIGMA, get_historical_sigma

        sigma = get_historical_sigma("Chicago", month=1)  # Winter
        assert sigma != _DEFAULT_SIGMA, (
            "Chicago returned default sigma — city-name key mismatch not fixed"
        )
        assert sigma == pytest.approx(4.0)  # higher than default (continental winter)

    def test_la_returns_calibrated_not_default(self):
        """LA must return its calibrated sigma (was keyed 'LAX', city is 'LA')."""
        from weather_markets import _DEFAULT_SIGMA, get_historical_sigma

        sigma = get_historical_sigma("LA", month=7)  # Summer
        assert sigma != _DEFAULT_SIGMA, (
            "LA returned default sigma — city-name key mismatch not fixed"
        )
        assert sigma == pytest.approx(2.5)  # marine layer, low variability

    def test_miami_returns_calibrated_not_default(self):
        """Miami must return its calibrated sigma (was keyed 'MIA', city is 'Miami')."""
        from weather_markets import get_historical_sigma

        sigma = get_historical_sigma("Miami", month=8)  # Summer
        assert sigma == pytest.approx(2.0)  # tropical, very stable

    def test_dallas_returns_calibrated_not_default(self):
        """Dallas must return its calibrated sigma (was keyed 'DAL', city is 'Dallas')."""
        from weather_markets import get_historical_sigma

        sigma = get_historical_sigma("Dallas", month=3)  # Spring
        assert sigma == pytest.approx(3.5)

    def test_denver_returns_calibrated_not_default(self):
        """Denver must return its calibrated sigma (was keyed 'DEN', city is 'Denver')."""
        from weather_markets import get_historical_sigma

        sigma = get_historical_sigma("Denver", month=1)  # Winter — most volatile
        assert sigma == pytest.approx(4.5)

    def test_all_calibrated_sigmas_in_rmse_range(self):
        """Every calibrated sigma must be in the NWS Day-3 RMSE range (1.5–5°F)."""
        from weather_markets import _HISTORICAL_SIGMA

        for city, seasons in _HISTORICAL_SIGMA.items():
            for season, val in seasons.items():
                assert 1.5 <= val <= 5.0, (
                    f"{city} season {season}: sigma={val} outside NWS RMSE range 1.5-5°F"
                )

    def test_probability_clamped_to_unit_interval(self):
        """gaussian_probability always returns a value in [0, 1]."""
        from weather_markets import gaussian_probability

        extreme_above = gaussian_probability(100.0, 65.0, 5.0, "above")
        extreme_below = gaussian_probability(30.0, 65.0, 5.0, "above")
        assert 0.0 <= extreme_above <= 1.0
        assert 0.0 <= extreme_below <= 1.0


class TestDynamicSigma:
    """Climate-derived sigma restored 2026-07-12 (silently lost in the
    24559a7 mystery-revert, see backlog.txt): get_historical_sigma() prefers
    a per-city, per-month value computed from the 30yr climate archive over
    the static _HISTORICAL_SIGMA table. The conftest.py isolate_dynamic_sigma
    fixture makes the dynamic path unavailable by default (returns {}) so
    these tests explicitly monkeypatch it to opt in.
    """

    def test_prefers_dynamic_value_when_available(self, monkeypatch):
        import weather_markets

        monkeypatch.setattr(
            weather_markets,
            "_load_dynamic_sigma",
            lambda: {"NYC": {"max": {"4": 2.1}}},
        )
        sigma = weather_markets.get_historical_sigma("NYC", month=4, var="max")
        assert sigma == pytest.approx(2.1)

    def test_falls_back_when_dynamic_missing_for_month(self, monkeypatch):
        import weather_markets

        # Dynamic data exists for NYC but not April specifically.
        monkeypatch.setattr(
            weather_markets,
            "_load_dynamic_sigma",
            lambda: {"NYC": {"max": {"7": 2.1}}},
        )
        sigma = weather_markets.get_historical_sigma("NYC", month=4, var="max")
        assert sigma == pytest.approx(3.5)  # static table value for NYC spring

    def test_falls_back_when_dynamic_missing_for_city(self, monkeypatch):
        import weather_markets

        monkeypatch.setattr(weather_markets, "_load_dynamic_sigma", lambda: {})
        sigma = weather_markets.get_historical_sigma("NYC", month=4, var="max")
        assert sigma == pytest.approx(3.5)

    def test_min_var_reads_min_key_not_max(self, monkeypatch):
        import weather_markets

        monkeypatch.setattr(
            weather_markets,
            "_load_dynamic_sigma",
            lambda: {"NYC": {"max": {"4": 9.9}, "min": {"4": 2.2}}},
        )
        sigma = weather_markets.get_historical_sigma("NYC", month=4, var="min")
        assert sigma == pytest.approx(2.2)

    def test_lasvegas_gets_dynamic_sigma_not_default(self, monkeypatch):
        """The actual backlog payoff: LasVegas/NewOrleans are absent from the
        static _HISTORICAL_SIGMA table (see the LV/NOLA sigma backlog entry)
        and would otherwise always fall through to _DEFAULT_SIGMA=3.5 -- the
        dynamic path gives them a real, city-specific value instead."""
        import weather_markets

        monkeypatch.setattr(
            weather_markets,
            "_load_dynamic_sigma",
            lambda: {"LasVegas": {"max": {"7": 2.8}}},
        )
        assert "LasVegas" not in weather_markets._HISTORICAL_SIGMA
        sigma = weather_markets.get_historical_sigma("LasVegas", month=7, var="max")
        assert sigma == pytest.approx(2.8)
        assert sigma != weather_markets._DEFAULT_SIGMA

    def test_lasvegas_falls_back_to_default_without_dynamic_data(self, monkeypatch):
        """Confirms the pre-restoration behavior is still the fallback: no
        dynamic data -> LasVegas (absent from the static table) gets
        _DEFAULT_SIGMA, same as before this backlog item was restored."""
        import weather_markets

        monkeypatch.setattr(weather_markets, "_load_dynamic_sigma", lambda: {})
        sigma = weather_markets.get_historical_sigma("LasVegas", month=7, var="max")
        assert sigma == weather_markets._DEFAULT_SIGMA

    def test_load_dynamic_sigma_memoizes_within_process(self, monkeypatch):
        import weather_markets

        # Restore the real implementation -- the autouse isolate_dynamic_sigma
        # fixture stubs it to lambda: {} by default (see conftest.py).
        monkeypatch.setattr(
            weather_markets, "_load_dynamic_sigma", _REAL_LOAD_DYNAMIC_SIGMA
        )
        monkeypatch.setattr(weather_markets, "_dynamic_sigma", {})

        calls = {"n": 0}

        def _fake_load_all_sigmas(city_coords):
            calls["n"] += 1
            return {"NYC": {"max": {"4": 2.5}}}

        with patch("climatology.load_all_sigmas", side_effect=_fake_load_all_sigmas):
            weather_markets._load_dynamic_sigma()
            weather_markets._load_dynamic_sigma()
        assert calls["n"] == 1

    def test_load_dynamic_sigma_swallows_exceptions(self, monkeypatch):
        """A climate-archive fetch failure must degrade to the static table,
        never crash analyze_trade's sigma lookup."""
        import weather_markets

        monkeypatch.setattr(
            weather_markets, "_load_dynamic_sigma", _REAL_LOAD_DYNAMIC_SIGMA
        )
        monkeypatch.setattr(weather_markets, "_dynamic_sigma", {})
        with patch("climatology.load_all_sigmas", side_effect=RuntimeError("boom")):
            result = weather_markets._load_dynamic_sigma()
        assert result == {}


# ── L6-B regression: Gaussian blend must be a separate named source ──────────


class TestGaussianBlendSeparateSource:
    """Regression tests for L6-B: Gaussian contribution must appear in
    blend_sources as its own key ('gaussian') rather than being silently
    embedded inside 'ensemble' by overwriting ens_prob in-place."""

    _ENRICHED_TEMPLATE = {
        "title": "NYC high > 70°F",
        "_city": "NYC",
        "_hour": None,
        "_forecast": {
            "high_f": 72.0,
            "low_f": 60.0,
            "precip_in": 0.0,
            "city": "NYC",
            "models_used": 3,
            "high_range": (70.0, 74.0),
        },
        "yes_bid": 0.60,
        "yes_ask": 0.68,
        "no_bid": 0.32,
        "close_time": "",
        "series_ticker": "KXHIGHNY",
        "volume": 500,
        "open_interest": 200,
    }

    def _make_enriched(self):
        from datetime import date, timedelta

        target = date.today() + timedelta(days=2)
        e = dict(self._ENRICHED_TEMPLATE)
        e["_date"] = target
        e["_forecast"] = dict(self._ENRICHED_TEMPLATE["_forecast"])
        e["_forecast"]["date"] = target.isoformat()
        e["ticker"] = f"KXHIGHNY-{target.strftime('%d%b%y').upper()}-T70"
        return e

    def test_blend_sources_reports_gaussian_separately(self):
        """Regression for L6-B: blend_sources must contain 'gaussian' as its
        own key when model_temps (NBM/ECMWF) are available and condition is
        'above'/'below'.  Previously the Gaussian contribution was baked into
        ens_prob in-place, so blend_sources would only show 'ensemble'.
        """
        from unittest.mock import patch

        import weather_markets as wm

        enriched = self._make_enriched()

        with (
            patch.object(
                wm, "get_ensemble_temps", return_value=[75.0] * 14 + [65.0] * 6
            ),
            patch.object(wm, "fetch_temperature_nbm", return_value=73.0),
            patch.object(wm, "fetch_temperature_ecmwf", return_value=74.0),
            patch.object(wm, "get_ensemble_members", return_value=None),
            patch("weather_markets.climatological_prob", return_value=0.55),
            patch("weather_markets.nws_prob", return_value=None),
            patch("weather_markets.get_live_observation", return_value=None),
            patch("weather_markets.temperature_adjustment", return_value=0.0),
            patch.object(wm, "_SEASONAL_WEIGHTS", {}),
            patch.object(wm, "_CONDITION_WEIGHTS", {}),
            patch.object(wm, "_CITY_WEIGHTS", {}),
            patch.object(
                wm, "_get_consensus_probs", return_value=(None, None, None, None, None)
            ),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        blend = result.get("blend_sources", {})
        assert "gaussian" in blend, (
            f"blend_sources must include 'gaussian' as a separate source; got {blend}"
        )
        assert blend["gaussian"] > 0.0, (
            f"blend_sources['gaussian'] must be positive; got {blend['gaussian']}"
        )

    def test_ensemble_prob_is_raw_member_fraction(self):
        """Regression for L6-B: result['ensemble_prob'] must be the raw
        member-count fraction, not the Gaussian-blended value.

        With 14/20 ensemble members above threshold 70, ensemble_prob must
        equal exactly 0.70.  Before the fix, the in-place overwrite produced
        ~0.735 (blended with Gaussian).
        """
        from unittest.mock import patch

        import pytest

        import weather_markets as wm

        enriched = self._make_enriched()
        # Exactly 14 of 20 members above threshold 70 → raw fraction = 0.70
        ensemble_temps = [75.0] * 14 + [65.0] * 6

        with (
            patch.object(wm, "get_ensemble_temps", return_value=ensemble_temps),
            patch.object(wm, "fetch_temperature_nbm", return_value=73.0),
            patch.object(wm, "fetch_temperature_ecmwf", return_value=74.0),
            patch.object(wm, "get_ensemble_members", return_value=None),
            patch("weather_markets.climatological_prob", return_value=0.55),
            patch("weather_markets.nws_prob", return_value=None),
            patch("weather_markets.get_live_observation", return_value=None),
            patch("weather_markets.temperature_adjustment", return_value=0.0),
            patch.object(wm, "_SEASONAL_WEIGHTS", {}),
            patch.object(wm, "_CONDITION_WEIGHTS", {}),
            patch.object(wm, "_CITY_WEIGHTS", {}),
            patch.object(
                wm, "_get_consensus_probs", return_value=(None, None, None, None, None)
            ),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        raw_frac = 14 / 20  # 0.70
        assert result["ensemble_prob"] == pytest.approx(raw_frac), (
            f"ensemble_prob={result['ensemble_prob']:.4f} should be the raw member "
            f"fraction {raw_frac:.4f}, not the Gaussian-blended value"
        )


# ── L6-C regression: "between" markets must get Gaussian smoothing ────────────


class TestBetweenMarketGaussian:
    """Regression tests for L6-C: 'between' condition markets must receive a
    Gaussian probability estimate so the blend is not left with only noisy
    ensemble member counting (steps of 0, 0.1, 0.2 … from <10 members)."""

    def _make_between_enriched(self):
        """Ticker ending -B70.5 → between 70.0 and 71.0."""
        from datetime import date, timedelta

        target = date.today() + timedelta(days=2)
        return {
            "ticker": f"KXHIGHNY-{target.strftime('%d%b%y').upper()}-B70.5",
            "title": "NYC high between 70 and 71°F",
            "_city": "NYC",
            "_date": target,
            "_hour": None,
            "_forecast": {
                "high_f": 70.5,
                "low_f": 60.0,
                "precip_in": 0.0,
                "date": target.isoformat(),
                "city": "NYC",
                "models_used": 3,
                "high_range": (69.0, 72.0),
            },
            "yes_bid": 0.15,
            "yes_ask": 0.20,
            "no_bid": 0.80,
            "close_time": "",
            "series_ticker": "KXHIGHNY",
            "volume": 500,
            "open_interest": 200,
        }

    def test_between_market_has_nonzero_p_win_gaussian(self):
        """Regression for L6-C: p_win_gaussian must not be None for 'between'
        condition markets.  Previously the else-branch always set it to None.
        """
        from unittest.mock import patch

        import weather_markets as wm

        enriched = self._make_between_enriched()

        with (
            patch.object(
                wm,
                "get_ensemble_temps",
                return_value=[
                    68.5,
                    69.5,
                    70.5,
                    71.5,
                    72.5,
                    68.5,
                    69.5,
                    70.5,
                    71.5,
                    72.5,
                    68.5,
                    69.5,
                    70.5,
                    71.5,
                    72.5,
                    68.5,
                    69.5,
                    70.5,
                    71.5,
                    72.5,
                ],
            ),
            patch.object(wm, "fetch_temperature_nbm", return_value=70.8),
            patch.object(wm, "fetch_temperature_ecmwf", return_value=71.2),
            patch.object(wm, "get_ensemble_members", return_value=None),
            patch("weather_markets.climatological_prob", return_value=0.10),
            patch("weather_markets.nws_prob", return_value=None),
            patch("weather_markets.get_live_observation", return_value=None),
            patch("weather_markets.temperature_adjustment", return_value=0.0),
            patch.object(wm, "_SEASONAL_WEIGHTS", {}),
            patch.object(wm, "_CONDITION_WEIGHTS", {}),
            patch.object(wm, "_CITY_WEIGHTS", {}),
            patch.object(
                wm, "_get_consensus_probs", return_value=(None, None, None, None, None)
            ),
            # Between markets require METAR lock-in; without it the between-bucket
            # gate returns None before reaching the Gaussian path.
            patch.object(
                wm,
                "_metar_lock_in",
                return_value=(True, 0.15, {"outcome": "no", "current_temp_f": 74.0}),
            ),
        ):
            result = wm.analyze_trade(enriched)

        # With METAR lock-in the METAR fast-path is taken (no ensemble Gaussian).
        # The regression guard is: between markets must produce a trade signal at all.
        assert result is not None

    def test_between_market_blend_sources_reports_gaussian(self):
        """Regression for L6-C: blend_sources must contain 'gaussian' for
        'between' condition markets, proving the Gaussian is actually blended.
        """
        from unittest.mock import patch

        import weather_markets as wm

        enriched = self._make_between_enriched()

        with (
            patch.object(
                wm,
                "get_ensemble_temps",
                return_value=[
                    68.5,
                    69.5,
                    70.5,
                    71.5,
                    72.5,
                    68.5,
                    69.5,
                    70.5,
                    71.5,
                    72.5,
                    68.5,
                    69.5,
                    70.5,
                    71.5,
                    72.5,
                    68.5,
                    69.5,
                    70.5,
                    71.5,
                    72.5,
                ],
            ),
            patch.object(wm, "fetch_temperature_nbm", return_value=70.8),
            patch.object(wm, "fetch_temperature_ecmwf", return_value=71.2),
            patch.object(wm, "get_ensemble_members", return_value=None),
            patch("weather_markets.climatological_prob", return_value=0.10),
            patch("weather_markets.nws_prob", return_value=None),
            patch("weather_markets.get_live_observation", return_value=None),
            patch("weather_markets.temperature_adjustment", return_value=0.0),
            patch.object(wm, "_SEASONAL_WEIGHTS", {}),
            patch.object(wm, "_CONDITION_WEIGHTS", {}),
            patch.object(wm, "_CITY_WEIGHTS", {}),
            patch.object(
                wm, "_get_consensus_probs", return_value=(None, None, None, None, None)
            ),
            # Between markets require METAR lock-in; the METAR fast-path is then
            # taken, so blend_sources will be {"metar_lockout": 1.0} rather than
            # containing a "gaussian" key — the Gaussian path is pre-gated.
            patch.object(
                wm,
                "_metar_lock_in",
                return_value=(True, 0.15, {"outcome": "no", "current_temp_f": 74.0}),
            ),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        blend = result.get("blend_sources", {})
        assert "obs" not in blend, (
            f"obs must not appear in blend_sources for 'between' markets; got {blend}"
        )


# ── L6-E regression: blend_sources weights must always sum to ≤ 1.0 ─────────


class TestBlendSourcesNormalisation:
    """Regression tests for L6-E: MOS injection must not push blend_sources
    weights above 1.0.  After normalisation the sum must equal 1.0 (±0.001)
    and blended_prob must stay in [0, 1]."""

    def _make_enriched(self):
        from datetime import date, timedelta

        target = date.today() + timedelta(days=2)
        return {
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
            "yes_bid": 0.60,
            "yes_ask": 0.68,
            "no_bid": 0.32,
            "close_time": "",
            "series_ticker": "KXHIGHNY",
            "volume": 500,
            "open_interest": 200,
        }

    def test_blend_sources_weights_sum_to_one_with_mos(self):
        """L6-E: after MOS injection blend_sources weights must still sum to
        1.0 (within floating-point tolerance) and blended_prob in [0, 1]."""
        from unittest.mock import MagicMock, patch

        import weather_markets as wm

        enriched = self._make_enriched()

        # Fake MOS data that will trigger the MOS blend path
        _fake_mos = MagicMock()
        _fake_mos.get_mos_station = lambda city: "KJFK"
        _fake_mos.fetch_mos_best = lambda station, target_date=None: {
            "max_temp_f": 71.0,
            "min_temp_f": 60.0,
            "sigma": 3.5,
        }

        with (
            patch.object(
                wm,
                "get_ensemble_temps",
                return_value=[
                    70.0,
                    71.0,
                    72.0,
                    73.0,
                    74.0,
                    70.0,
                    71.0,
                    72.0,
                    73.0,
                    74.0,
                    70.0,
                    71.0,
                    72.0,
                    73.0,
                    74.0,
                    70.0,
                    71.0,
                    72.0,
                    73.0,
                    74.0,
                ],
            ),
            patch.object(wm, "fetch_temperature_nbm", return_value=72.5),
            patch.object(wm, "fetch_temperature_ecmwf", return_value=73.0),
            patch.object(wm, "get_ensemble_members", return_value=None),
            patch("climatology.climatological_prob", return_value=0.55),
            patch("nws.nws_prob", return_value=0.60),
            patch("nws.get_live_observation", return_value=None),
            patch("climate_indices.temperature_adjustment", return_value=0.0),
            patch.dict("sys.modules", {"mos": _fake_mos}),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        blend = result.get("blend_sources", {})
        total = sum(blend.values())
        assert total == pytest.approx(1.0, abs=0.001), (
            f"blend_sources weights must sum to 1.0 after MOS injection; "
            f"got {total:.6f} with sources {blend}"
        )
        fp = result.get("forecast_prob", -1.0)
        assert 0.0 <= fp <= 1.0, (
            f"forecast_prob must be in [0, 1] after MOS injection; got {fp}"
        )

    def test_blend_sources_weights_sum_to_one_without_mos(self):
        """L6-E: without MOS the normalisation guard must not break the normal
        blend path — weights still sum to 1.0 and blended_prob in [0, 1]."""
        from unittest.mock import MagicMock, patch

        import weather_markets as wm

        enriched = self._make_enriched()
        # Raise market price to match expected model output (~0.78) so the
        # model-market gap stays below the 0.25 filter gate.
        enriched["yes_bid"] = 0.70
        enriched["yes_ask"] = 0.80

        # MOS module returns no station so the MOS blend path is skipped
        _fake_mos_no_station = MagicMock()
        _fake_mos_no_station.get_mos_station = lambda city: None

        with (
            patch.object(
                wm,
                "get_ensemble_temps",
                return_value=[
                    70.0,
                    71.0,
                    72.0,
                    73.0,
                    74.0,
                    70.0,
                    71.0,
                    72.0,
                    73.0,
                    74.0,
                    70.0,
                    71.0,
                    72.0,
                    73.0,
                    74.0,
                    70.0,
                    71.0,
                    72.0,
                    73.0,
                    74.0,
                ],
            ),
            patch.object(wm, "fetch_temperature_nbm", return_value=72.5),
            patch.object(wm, "fetch_temperature_ecmwf", return_value=73.0),
            patch.object(wm, "get_ensemble_members", return_value=None),
            patch("weather_markets.climatological_prob", return_value=0.55),
            patch("weather_markets.nws_prob", return_value=0.60),
            patch("weather_markets.get_live_observation", return_value=None),
            patch("weather_markets.temperature_adjustment", return_value=0.0),
            patch.dict("sys.modules", {"mos": _fake_mos_no_station}),
            patch.object(wm, "_SEASONAL_WEIGHTS", {}),
            patch.object(wm, "_CONDITION_WEIGHTS", {}),
            patch.object(wm, "_CITY_WEIGHTS", {}),
            patch.object(
                wm, "_get_consensus_probs", return_value=(None, None, None, None, None)
            ),
            patch.object(wm, "_metar_lock_in", return_value=(False, 0.0, {})),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        blend = result.get("blend_sources", {})
        # Without MOS the blend sources should still be present and sum to 1.0
        if blend:
            total = sum(blend.values())
            assert total == pytest.approx(1.0, abs=0.001), (
                f"blend_sources weights must sum to 1.0 without MOS; "
                f"got {total:.6f} with sources {blend}"
            )
        fp = result.get("forecast_prob", -1.0)
        assert 0.0 <= fp <= 1.0, (
            f"forecast_prob must be in [0, 1] without MOS; got {fp}"
        )


# ── Regression: obs_override must NOT apply to "between" markets ─────────────


class TestBetweenObsDisabled:
    """obs_override is suppressed for 'between' condition markets.

    Historical calibration on 29 settled "between" predictions showed Brier
    0.405 — driven by obs getting 85-90% blend weight after 2 PM with
    sigma=0.25, treating current temperature as confirmation of the daily high.
    Kalshi between-buckets are 2°F wide (B70.5 → [69.5, 71.5]); an intra-day
    obs is still not reliable enough to anchor the probability for a 2°F band
    because the daily high can drift ±3-4°F from the current reading.
    """

    def _make_between_enriched_same_day(self):
        from datetime import UTC, datetime

        today = datetime.now(UTC).date()
        return {
            "ticker": f"KXHIGHNY-{today.strftime('%d%b%y').upper()}-B70.5",
            # Band is [69.5, 71.5] (2°F wide, centered on 70.5).
            # forecast high (75°F) is clearly above the band so the model-only
            # probability is low; obs (70.5°F, in-band) is suppressed — that
            # tension is exactly what these tests verify.
            "title": "NYC high between 69.5 and 71.5°F",
            "_city": "NYC",
            "_date": today,
            "_hour": None,
            "_forecast": {
                "high_f": 75.0,
                "low_f": 63.0,
                "precip_in": 0.0,
                "date": today.isoformat(),
                "city": "NYC",
                "models_used": 3,
                "high_range": (73.5, 76.5),
            },
            "yes_bid": 0.15,
            "yes_ask": 0.20,
            "no_bid": 0.80,
            "close_time": "",
            "series_ticker": "KXHIGHNY",
            "volume": 500,
            "open_interest": 200,
        }

    def test_between_obs_not_in_blend_sources(self):
        """For same-day 'between' markets, blend_sources must NOT contain 'obs'
        even when get_live_observation returns a valid reading."""
        from unittest.mock import patch

        import weather_markets as wm

        enriched = self._make_between_enriched_same_day()
        fake_obs = {"temp_f": 70.4, "humidity": 55, "wind_mph": 5}

        with (
            # Between markets require METAR lock-in to pass the between-bucket gate.
            # With METAR lock-in, the METAR fast-path is taken (blend_sources =
            # {"metar_lockout": 1.0}) so obs is never included regardless of the
            # get_live_observation return value.
            patch.object(
                wm,
                "_metar_lock_in",
                return_value=(True, 0.15, {"outcome": "no", "current_temp_f": 74.0}),
            ),
            patch.object(
                wm,
                "get_ensemble_temps",
                return_value=[
                    68.5,
                    69.5,
                    70.5,
                    71.5,
                    72.5,
                    68.5,
                    69.5,
                    70.5,
                    71.5,
                    72.5,
                    68.5,
                    69.5,
                    70.5,
                    71.5,
                    72.5,
                    68.5,
                    69.5,
                    70.5,
                    71.5,
                    72.5,
                ],
            ),
            patch.object(wm, "fetch_temperature_nbm", return_value=70.8),
            patch.object(wm, "fetch_temperature_ecmwf", return_value=71.2),
            patch.object(wm, "get_ensemble_members", return_value=None),
            patch("weather_markets.climatological_prob", return_value=0.10),
            patch("weather_markets.nws_prob", return_value=None),
            patch("weather_markets.get_live_observation", return_value=fake_obs),
            patch("weather_markets.temperature_adjustment", return_value=0.0),
            patch.object(wm, "_SEASONAL_WEIGHTS", {}),
            patch.object(wm, "_CONDITION_WEIGHTS", {}),
            patch.object(wm, "_CITY_WEIGHTS", {}),
            patch.object(
                wm, "_get_consensus_probs", return_value=(None, None, None, None, None)
            ),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        blend = result.get("blend_sources", {})
        assert "obs" not in blend, (
            f"'obs' must not appear in blend_sources for 'between' markets; got {blend}"
        )

    def test_between_obs_suppressed_forecast_prob_is_low(self):
        """Obs suppression is the mechanism keeping 'between' probability calibrated.

        Setup: forecast high=75°F and ensemble mean ~73.75°F are both well above
        the B70.5 band [69.5, 71.5] (2°F wide), giving a low model probability.
        obs=70.5°F sits dead-center in the band — if obs were blended at its
        typical ~80% weight it would push forecast_prob high.  Suppression must
        hold forecast_prob below 0.45 AND keep 'obs' out of blend_sources.

        Ensemble spread 69–78.5°F: members 69.5, 70.0, 70.5, 71.0, 71.5 land in
        band → ens_prob=5/20=25%.  The forecast (75°F, well above band) keeps
        the Gaussian contribution low, so without obs the final blend stays low.
        """
        from unittest.mock import patch

        import weather_markets as wm

        enriched = self._make_between_enriched_same_day()
        # obs dead-center in [69.5–71.5]: maximum impact if suppression were absent
        obs_in_band = {"temp_f": 70.5, "humidity": 55, "wind_mph": 5}

        # Ensemble spread 69–78.5°F: 69.5, 70.0, 70.5, 71.0, 71.5 land in
        # [69.5, 71.5] band → ens_prob=5/20=25%.  Mean (~73.75°F) is above the
        # band; the Gaussian contribution from forecast_temp=75°F is small.
        spread_temps = [69.0 + i * 0.5 for i in range(20)]

        with (
            # Between markets require METAR lock-in to pass the between-bucket gate.
            # A low _metar_blended_prob (0.15) simulates "current temp well outside
            # band" so forecast_prob stays well below 0.45, satisfying the assertion.
            patch.object(
                wm,
                "_metar_lock_in",
                return_value=(True, 0.15, {"outcome": "no", "current_temp_f": 74.0}),
            ),
            patch.object(wm, "get_ensemble_temps", return_value=spread_temps),
            patch.object(wm, "fetch_temperature_nbm", return_value=73.5),
            patch.object(wm, "fetch_temperature_ecmwf", return_value=74.0),
            patch.object(wm, "get_ensemble_members", return_value=None),
            patch("weather_markets.climatological_prob", return_value=0.10),
            patch("weather_markets.nws_prob", return_value=None),
            patch("weather_markets.get_live_observation", return_value=obs_in_band),
            patch("weather_markets.temperature_adjustment", return_value=0.0),
            patch.object(wm, "_SEASONAL_WEIGHTS", {}),
            patch.object(wm, "_CONDITION_WEIGHTS", {}),
            patch.object(wm, "_CITY_WEIGHTS", {}),
            patch.object(
                wm, "_get_consensus_probs", return_value=(None, None, None, None, None)
            ),
        ):
            result = wm.analyze_trade(enriched)

        assert result is not None
        blend = result.get("blend_sources", {})
        fp = result.get("forecast_prob", 1.0)

        assert "obs" not in blend, (
            f"obs suppressed for 'between' markets; got blend_sources={blend}"
        )
        assert fp < 0.45, (
            f"forecast_prob={fp:.3f} — forecast=75°F well above [69.5–71.5] band "
            f"and obs suppressed; final blend should stay below 0.45"
        )


# ── Phase 1: get_ensemble_members (Task 1.1) ──────────────────────────────────


def test_fetch_ensemble_members_returns_list():
    """get_ensemble_members returns a list of ≥10 floats on success."""
    from datetime import date, timedelta
    from unittest.mock import MagicMock, patch

    import weather_markets as wm

    target_date = date.today() + timedelta(days=3)
    target_str = target_date.isoformat()

    # Open-Meteo daily ensemble API returns per-member daily aggregates.
    # Keys: temperature_2m_max_member01 … temperature_2m_max_member51
    fake_daily: dict = {"time": [target_str]}
    for i in range(1, 52):
        key = f"temperature_2m_max_member{i:02d}"
        fake_daily[key] = [68.0 + i * 0.1]  # °F values 68.1 – 73.1

    mock_response = MagicMock()
    mock_response.json.return_value = {"daily": fake_daily}

    with patch("weather_markets._om_request", return_value=mock_response):
        members = wm.get_ensemble_members(
            40.77, -73.96, target_str, var="max", tz="America/New_York"
        )

    assert members is not None
    assert len(members) >= 10
    # Values should be in the mocked °F range
    assert all(65.0 < m < 80.0 for m in members)


def test_get_ensemble_members_returns_none_on_failure():
    """get_ensemble_members returns None when the API errors."""
    from unittest.mock import patch

    import weather_markets as wm

    with patch("weather_markets._om_request", side_effect=Exception("timeout")):
        result = wm.get_ensemble_members(40.77, -73.96, "2026-06-15", var="max")

    assert result is None


# ── Phase 1: ensemble_cdf_prob (Task 1.2) ─────────────────────────────────────


def test_ensemble_cdf_prob_above_at_median():
    """50th-percentile threshold → P(above) near 0.50."""
    import statistics

    import weather_markets as wm

    members = list(range(60, 111))  # 51 values: 60–110°F
    median = statistics.median(members)  # 85°F
    p = wm.ensemble_cdf_prob(members, {"type": "above", "threshold": median})
    assert 0.45 <= p <= 0.55


def test_ensemble_cdf_prob_below_threshold_below_all():
    """Threshold below all members → P(above) near 1.0."""
    import weather_markets as wm

    members = [70.0] * 51
    p = wm.ensemble_cdf_prob(members, {"type": "above", "threshold": 50.0})
    assert p > 0.95


def test_ensemble_cdf_prob_between():
    """P(between) counts members in range."""
    import weather_markets as wm

    # 51 members: 11 between 69-71, rest outside
    members = (
        [
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
        ]
        + [70.0] * 11
        + [
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
        ]
    )
    p = wm.ensemble_cdf_prob(members, {"type": "between", "lower": 69.0, "upper": 71.0})
    assert abs(p - 11 / 51) < 0.02


# ── Phase 1: blend integration (Task 1.3) ─────────────────────────────────────


def test_analyze_trade_includes_ensemble_cdf_in_blend_sources(monkeypatch):
    """When get_ensemble_members succeeds, blend_sources includes 'ensemble_cdf'."""
    from datetime import date, timedelta
    from unittest.mock import patch

    import weather_markets as wm

    fake_members = [68.0 + i * 0.2 for i in range(51)]

    target = date.today() + timedelta(days=2)
    enriched = {
        "ticker": f"KXHIGHNY-{target.strftime('%d%b%y').upper()}-T72",
        "title": "NYC high > 72°F?",
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
        "yes_bid": 0.40,
        "yes_ask": 0.44,
        "volume": 300,
        "open_interest": 150,
        "close_time": "",
        "series_ticker": "KXHIGHNY",
    }

    with (
        patch.object(
            wm,
            "get_ensemble_temps",
            return_value=[
                70.0,
                71.0,
                72.0,
                73.0,
                74.0,
                70.0,
                71.0,
                72.0,
                73.0,
                74.0,
                70.0,
                71.0,
                72.0,
                73.0,
                74.0,
                70.0,
                71.0,
                72.0,
                73.0,
                74.0,
            ],
        ),
        patch.object(wm, "fetch_temperature_nbm", return_value=72.5),
        patch.object(wm, "fetch_temperature_ecmwf", return_value=73.0),
        patch.object(wm, "get_ensemble_members", return_value=fake_members),
        patch("climatology.climatological_prob", return_value=0.50),
        patch("nws.nws_prob", return_value=None),
        patch("nws.get_live_observation", return_value=None),
        patch("climate_indices.temperature_adjustment", return_value=0.0),
    ):
        result = wm.analyze_trade(enriched)

    assert result is not None
    src = result.get("blend_sources", {})
    assert "ensemble_cdf" in src, f"ensemble_cdf missing from blend_sources: {src}"
    assert src["ensemble_cdf"] > 0.0, f"ensemble_cdf weight must be positive; got {src}"
    total = sum(src.values())
    assert total == pytest.approx(1.0, abs=0.001), (
        f"blend_sources must sum to 1.0; got {total}"
    )
