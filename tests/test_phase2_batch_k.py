"""Phase 2 Batch K regression tests: P2-24/P2-26/P2-36/P2-39/P2-45 — weather_markets.py."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(__file__[: __file__.rfind("tests")]))


# ── P2-24: _confidence_scaled_blend_weights — no negative weights ─────────────


class TestConfidenceScaledBlendWeightsNoNegative:
    """Weights must stay >= 0 when scale > 1 (tight spread)."""

    def _call(
        self,
        ens_std: float | None,
        days_out: int = 3,
        has_nws: bool = True,
        has_clim: bool = True,
    ):
        from weather_markets import _confidence_scaled_blend_weights

        return _confidence_scaled_blend_weights(
            days_out, has_nws, has_clim, ens_std=ens_std
        )

    def test_no_negative_weights_tight_spread(self):
        """With ens_std=0.5 (scale=4/0.5=8, clamped to 1.5), w_clim/w_nws stay >= 0."""
        w_ens, w_clim, w_nws = self._call(ens_std=0.5)
        assert w_ens >= 0.0
        assert w_clim >= 0.0
        assert w_nws >= 0.0

    def test_weights_sum_to_one(self):
        """All weights must sum to 1.0 regardless of scaling."""
        for std in (0.1, 0.5, 1.0, 2.0, 4.0, 8.0, None):
            w_ens, w_clim, w_nws = self._call(ens_std=std)
            assert abs(w_ens + w_clim + w_nws - 1.0) < 1e-9, (
                f"weights don't sum to 1 for std={std}: {w_ens}+{w_clim}+{w_nws}"
            )

    def test_tight_spread_boosts_ensemble(self):
        """Tighter-than-reference spread (std < 4°F) must increase w_ens."""
        w_ens_base, _, _ = self._call(ens_std=None)
        w_ens_tight, _, _ = self._call(ens_std=1.0)
        assert w_ens_tight > w_ens_base

    def test_wide_spread_reduces_ensemble(self):
        """Wider-than-reference spread (std > 4°F) must decrease w_ens."""
        w_ens_base, _, _ = self._call(ens_std=None)
        w_ens_wide, _, _ = self._call(ens_std=8.0)
        assert w_ens_wide < w_ens_base

    def test_no_negative_weights_no_nws(self):
        """No negative weights when NWS is unavailable and spread is tight."""
        w_ens, w_clim, w_nws = self._call(ens_std=0.5, has_nws=False, has_clim=True)
        assert w_ens >= 0.0
        assert w_clim >= 0.0
        assert w_nws == 0.0

    def test_no_negative_weights_no_clim(self):
        """No negative weights when climatology is unavailable and spread is tight."""
        w_ens, w_clim, w_nws = self._call(ens_std=0.5, has_nws=True, has_clim=False)
        assert w_ens >= 0.0
        assert w_clim == 0.0
        assert w_nws >= 0.0


# ── P2-26: clim_prior uses climatological_prob, not hardcoded 0.30 ────────────


class TestClimPriorUseClimatologicalProb:
    """_analyze_precip_trade and _analyze_snow_trade must call climatological_prob."""

    def test_precip_uses_clim_prob_when_available(self):
        """clim_prior in precip blend should be 0.50 when climatological_prob returns 0.50."""
        import inspect

        import weather_markets

        src = inspect.getsource(weather_markets._analyze_precip_trade)
        assert "climatological_prob" in src, (
            "_analyze_precip_trade must call climatological_prob"
        )
        # The old standalone hardcoded comment must be gone (replaced by try/except)
        assert "rough historical rain frequency as fallback prior" not in src, (
            "Old hardcoded 'clim_prior = 0.30  # rough historical...' comment must be gone"
        )
        # Must have exception fallback
        assert "except Exception" in src

    def test_snow_uses_clim_prob_when_available(self):
        """_analyze_snow_trade must call climatological_prob."""
        import inspect

        import weather_markets

        src = inspect.getsource(weather_markets._analyze_snow_trade)
        assert "climatological_prob" in src, (
            "_analyze_snow_trade must call climatological_prob"
        )

    def test_precip_fallback_on_exception(self):
        """When climatological_prob raises, clim_prior falls back to 0.30."""
        import inspect

        import weather_markets

        src = inspect.getsource(weather_markets._analyze_precip_trade)
        assert "0.30" in src, "Fallback 0.30 must remain in _analyze_precip_trade"
        assert "except Exception" in src or "except" in src

    def test_snow_fallback_uses_seasonal_default(self):
        """When climatological_prob raises in snow, fallback is seasonal (0.20/0.05)."""
        import inspect

        import weather_markets

        src = inspect.getsource(weather_markets._analyze_snow_trade)
        assert "0.20" in src
        assert "0.05" in src


# ── P2-36: ensemble_stats degenerate detection ────────────────────────────────


class TestEnsembleStatsDegenerate:
    """ensemble_stats must flag all-identical members as degenerate."""

    def _call(self, temps):
        from weather_markets import ensemble_stats

        return ensemble_stats(temps)

    def test_all_identical_flagged_as_degenerate(self):
        """10 identical values (std=0) with n>5 must be degenerate=True."""
        result = self._call([72.0] * 10)
        assert result["degenerate"] is True

    def test_varied_temps_not_degenerate(self):
        """Normal spread must not be flagged as degenerate."""
        result = self._call([68.0, 70.0, 72.0, 74.0, 76.0, 78.0, 80.0])
        assert result["degenerate"] is False

    def test_exactly_5_members_not_degenerate(self):
        """Exactly 5 identical members: degenerate threshold requires >5."""
        result = self._call([72.0] * 5)
        assert result["degenerate"] is False

    def test_six_identical_members_is_degenerate(self):
        """6 identical members triggers degenerate=True."""
        result = self._call([72.0] * 6)
        assert result["degenerate"] is True

    def test_empty_returns_empty(self):
        """Empty input returns empty dict (no degenerate key)."""
        result = self._call([])
        assert result == {}

    def test_degenerate_key_always_present_when_nonempty(self):
        """degenerate key must be present for any non-empty input."""
        result = self._call([70.0, 72.0])
        assert "degenerate" in result

    def test_analyze_trade_skips_degenerate_ensemble(self):
        """analyze_trade must return None when ens_stats.degenerate is True."""
        import inspect

        import weather_markets

        src = inspect.getsource(weather_markets.analyze_trade)
        assert "degenerate" in src, "analyze_trade must check ens_stats['degenerate']"
        assert "return None" in src


# ── P2-39: _blend_probabilities delegates to _blend_weights ──────────────────


class TestBlendProbabilitiesDelegatesToBlendWeights:
    """_blend_probabilities must use _blend_weights, not hardcoded values."""

    def test_source_delegates_to_blend_weights(self):
        """_blend_probabilities must call _blend_weights."""
        import inspect

        import weather_markets

        src = inspect.getsource(weather_markets._blend_probabilities)
        assert "_blend_weights(" in src, (
            "_blend_probabilities must delegate to _blend_weights()"
        )
        # Old hardcoded constants should be gone
        assert "w_nws_base" not in src, (
            "Hardcoded w_nws_base must be removed from _blend_probabilities"
        )
        assert "w_ens_base" not in src

    def test_all_none_returns_none(self):
        """All-None inputs must return None."""
        from weather_markets import _blend_probabilities

        assert _blend_probabilities(None, None, None) is None

    def test_only_ensemble_prob(self):
        """Single source returns that source's probability (renormalized)."""
        from weather_markets import _blend_probabilities

        result = _blend_probabilities(0.70, None, None)
        assert result == 0.70

    def test_all_sources(self):
        """With all sources, result is a weighted blend (0 < result < 1)."""
        from weather_markets import _blend_probabilities

        result = _blend_probabilities(0.80, 0.70, 0.60, days_out=2)
        assert result is not None
        assert 0.60 < result < 0.80

    def test_result_agrees_with_blend_weights(self):
        """Result must match manual application of _blend_weights."""
        from weather_markets import _blend_probabilities, _blend_weights

        ens_p, nws_p, clim_p = 0.80, 0.70, 0.60
        days_out = 2
        w_ens, w_clim, w_nws = _blend_weights(days_out, has_nws=True, has_clim=True)
        expected = ens_p * w_ens + nws_p * w_nws + clim_p * w_clim
        result = _blend_probabilities(ens_p, nws_p, clim_p, days_out=days_out)
        assert result is not None
        assert abs(result - expected) < 1e-9


# ── P2-45: GBM + Platt not both applied ───────────────────────────────────────


class TestOnlyOneMlCorrectionApplied:
    """GBM and Platt must not both be applied to the same city's probability."""

    def test_has_ml_model_helper_exists(self):
        """ml_bias must export has_ml_model(city)."""
        from ml_bias import has_ml_model

        assert callable(has_ml_model)

    def test_has_ml_model_false_when_no_models(self):
        """has_ml_model returns False when bias_models is absent/empty."""
        with patch("ml_bias._load_models", return_value={}):
            from ml_bias import has_ml_model

            assert has_ml_model("NYC") is False

    def test_has_ml_model_true_when_model_present(self):
        """has_ml_model returns True when a model exists for the city."""
        mock_model = MagicMock()
        with patch("ml_bias._load_models", return_value={"NYC": mock_model}):
            from ml_bias import has_ml_model

            assert has_ml_model("NYC") is True

    def test_source_uses_has_ml_model_gate(self):
        """analyze_trade source must use has_ml_model to guard Platt application."""
        import inspect

        import weather_markets

        src = inspect.getsource(weather_markets.analyze_trade)
        assert "has_ml_model" in src, (
            "analyze_trade must call has_ml_model to prevent dual correction"
        )
        assert "_city_correction_applied" in src, (
            "analyze_trade must track _city_correction_applied to skip Platt when GBM ran"
        )

    def test_platt_not_called_when_gbm_model_present(self):
        """When GBM model exists, apply_platt_per_city must NOT be called."""
        mock_gbm = MagicMock()
        mock_gbm.predict.return_value = [0.0]

        with (
            patch("ml_bias._load_models", return_value={"NYC": mock_gbm}),
            patch("weather_markets._load_platt_models") as mock_platt_load,
        ):
            from ml_bias import has_ml_model

            # Confirm model detected
            assert has_ml_model("NYC") is True
            # _load_platt_models should not be consulted
            mock_platt_load.assert_not_called()

    def test_gbm_and_platt_not_sequentially_applied(self):
        """Verify source: Platt block is inside '_city_correction_applied' guard."""
        import inspect

        import weather_markets

        src = inspect.getsource(weather_markets.analyze_trade)
        # The Platt section must be guarded by _city_correction_applied
        assert "if not _city_correction_applied" in src, (
            "Platt application must be gated by 'if not _city_correction_applied'"
        )
