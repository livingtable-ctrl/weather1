"""Tests for order_executor._prediction_kwargs_from_analysis -- the single
shared derivation of tracker.log_prediction()'s metadata kwargs (ens_mean/
ens_var, run_trend, forecast_cycle, etc.), used by the real post-placement
log_prediction call, shadow logging, AND (after the 2026-07-17 consolidation)
both of main.py's direct log_prediction call sites (cmd_market, cmd_order).
Before that consolidation each of those three call sites hand-copied this
same assembly, and one copy had already silently drifted (main.py's
cmd_market call was missing model_consensus) -- these tests exist so that
kind of drift can't happen again without a test failing."""

import order_executor


def _make_analysis(**overrides):
    base = {
        "ensemble_prob": 0.62,
        "nws_prob": 0.58,
        "clim_prob": 0.55,
        "method": "ensemble",
        "blend_sources": {"ensemble": 0.6, "nws": 0.3, "clim": 0.1},
        "model_consensus": True,
        "ensemble_stats": {"mean": 72.5, "std": 2.0},
        # city/days_out/target_date deliberately omitted so
        # get_forecast_run_trend_from_analysis short-circuits to None
        # without making a live network call (see its own docstring).
    }
    base.update(overrides)
    return base


class TestPredictionKwargsFromAnalysis:
    def test_derives_all_fields_correctly(self):
        analysis = _make_analysis()
        kwargs = order_executor._prediction_kwargs_from_analysis(analysis)

        assert kwargs["ensemble_prob"] == 0.62
        assert kwargs["nws_prob"] == 0.58
        assert kwargs["clim_prob"] == 0.55
        assert kwargs["signal_source"] == "ensemble"
        assert kwargs["blend_sources"] == {"ensemble": 0.6, "nws": 0.3, "clim": 0.1}
        assert kwargs["model_consensus"] is True
        assert kwargs["ens_mean"] == 72.5
        # CRITICAL (per ml_bias.emos_exceedance_prob's own docstring warning):
        # ens_var must be std**2 (variance), NOT std itself.
        assert kwargs["ens_var"] == 4.0
        # No city/days_out/target_date in the analysis dict -> run_trend must
        # short-circuit to None (get_forecast_run_trend_from_analysis's own
        # documented contract), not attempt a live fetch.
        assert kwargs["run_trend"] is None
        # forecast_cycle/edge_calc_version are live/derived, not passed
        # through -- just confirm they're populated with the right shape.
        assert kwargs["forecast_cycle"] == order_executor._current_forecast_cycle()
        from weather_markets import EDGE_CALC_VERSION

        assert kwargs["edge_calc_version"] == EDGE_CALC_VERSION

    def test_ens_var_is_variance_not_std(self):
        # Mutation-proof: if ens_var regressed to passing std directly
        # instead of std**2, this would catch it (2.0 != 4.0).
        analysis = _make_analysis(ensemble_stats={"mean": 70.0, "std": 3.0})
        kwargs = order_executor._prediction_kwargs_from_analysis(analysis)
        assert kwargs["ens_var"] == 9.0

    def test_missing_ensemble_stats_gives_none_mean_and_var(self):
        analysis = _make_analysis(ensemble_stats=None)
        kwargs = order_executor._prediction_kwargs_from_analysis(analysis)
        assert kwargs["ens_mean"] is None
        assert kwargs["ens_var"] is None

    def test_missing_std_gives_none_var_not_typeerror(self):
        analysis = _make_analysis(ensemble_stats={"mean": 70.0})
        kwargs = order_executor._prediction_kwargs_from_analysis(analysis)
        assert kwargs["ens_mean"] == 70.0
        assert kwargs["ens_var"] is None


class TestMainPyUsesSharedHelper:
    """2026-07-17: main.py's cmd_market and cmd_order log_prediction call
    sites were consolidated to call order_executor._prediction_kwargs_from_analysis
    instead of hand-copying the same field assembly (which had already drifted
    once -- see backlog.txt's LOG_PREDICTION KWARGS ASSEMBLY TRIPLICATED entry).
    This just confirms the wiring: main.py imports the real function object,
    not a stale copy or a name that happens to resolve to something else."""

    def test_main_imports_the_real_shared_function(self):
        import main

        assert main._prediction_kwargs_from_analysis is (
            order_executor._prediction_kwargs_from_analysis
        )
