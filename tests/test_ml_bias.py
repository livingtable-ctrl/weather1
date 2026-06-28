"""Tests for ML-based bias correction."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
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

    def test_apply_ml_prob_correction_falls_back_when_no_model(self):
        """apply_ml_prob_correction returns our_prob unchanged if no trained model exists."""
        from unittest.mock import patch

        import ml_bias

        with patch.object(ml_bias, "_load_models", return_value={}):
            result = ml_bias.apply_ml_prob_correction("NYC", 0.72, month=4, days_out=3)
        assert result == pytest.approx(0.72)

    def test_apply_ml_prob_correction_adjusts_probability(self, tmp_path, monkeypatch):
        """apply_ml_prob_correction returns adjusted prob when model is available."""
        from unittest.mock import MagicMock, patch

        import ml_bias

        # Fake model that always predicts +0.05 correction (actual was higher than predicted)
        fake_model = MagicMock()
        fake_model.predict.return_value = [0.05]

        with patch.object(ml_bias, "_load_models", return_value={"NYC": fake_model}):
            result = ml_bias.apply_ml_prob_correction("NYC", 0.60, month=4, days_out=3)

        # Corrected: 0.60 + 0.05 = 0.65
        assert result == pytest.approx(0.65, abs=0.01)


# ── Phase 2: per-city Platt scaling ──────────────────────────────────────────


def test_train_platt_per_city_returns_coefficients():
    """train_platt_per_city returns {city: (A, B)} for cities with >=200 samples."""
    import random

    import ml_bias

    random.seed(42)
    rows = []
    for _ in range(250):
        p = random.uniform(0.3, 0.8)
        rows.append(
            {
                "city": "NYC",
                "our_prob": p,
                "settled_yes": 1 if random.random() < p else 0,
            }
        )
    for _ in range(50):
        rows.append({"city": "Chicago", "our_prob": 0.6, "settled_yes": 1})

    models = ml_bias.train_platt_per_city(rows, min_samples=200)

    assert "NYC" in models, "NYC (250 samples) must be trained"
    assert "Chicago" not in models, "Chicago (<200) must be skipped"
    a, b = models["NYC"]
    assert isinstance(a, float) and isinstance(b, float)


def test_apply_platt_per_city_unknown_city_unchanged():
    """Unknown city returns raw prob unchanged."""
    import ml_bias

    p = ml_bias.apply_platt_per_city("Dallas", 0.65, {})
    assert p == pytest.approx(0.65)


def test_apply_platt_identity_calibration():
    """A=1.0, B=0.0 (identity) returns approximately the input probability."""
    import ml_bias

    models = {"NYC": (1.0, 0.0)}
    p = ml_bias.apply_platt_per_city("NYC", 0.70, models)
    assert 0.60 <= p <= 0.80


def test_apply_platt_per_city_monotonicity():
    """P2-I: apply_platt_per_city must preserve monotonic ordering.

    If raw_p1 < raw_p2 then calibrated_p1 <= calibrated_p2.
    Platt scaling (sigmoid of a linear transform) is monotone when A > 0,
    so this invariant must hold for any valid trained model.
    """
    import ml_bias

    # Use a non-trivial but positive-slope model (A=2.0, B=-0.5)
    models = {"NYC": (2.0, -0.5)}

    raw_probs = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]
    calibrated = [ml_bias.apply_platt_per_city("NYC", p, models) for p in raw_probs]

    for i in range(len(calibrated) - 1):
        assert calibrated[i] <= calibrated[i + 1], (
            f"Monotonicity violated at index {i}: "
            f"apply_platt({raw_probs[i]})={calibrated[i]:.4f} > "
            f"apply_platt({raw_probs[i + 1]})={calibrated[i + 1]:.4f}"
        )


# ── Temperature scaling (apply_temperature_scaling) ──────────────────────────


class TestApplyTemperatureScaling:
    """Tests for apply_temperature_scaling — the per-condition calibration step.

    Each test patches _TEMP_PATH and clears _TEMP_CACHE so the loader always
    reads from the tmp file rather than the real data/temperature_scale.json.
    Cross-test cache pollution is prevented by resetting _TEMP_CACHE to None
    both before and after each test via a helper.
    """

    def _load_table(self, tmp_path, monkeypatch, content: dict):
        """Write content to a temp file and wire ml_bias to read it."""
        import json

        import ml_bias

        ts_file = tmp_path / "temperature_scale.json"
        ts_file.write_text(json.dumps(content))
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", ts_file)
        ml_bias._TEMP_CACHE = None  # force fresh load from tmp file

    def test_no_file_returns_prob_unchanged(self, tmp_path, monkeypatch):
        """Returns prob unchanged when temperature_scale.json does not exist."""
        import ml_bias

        monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "nonexistent.json")
        ml_bias._TEMP_CACHE = None
        result = ml_bias.apply_temperature_scaling(0.75)
        ml_bias._TEMP_CACHE = None  # teardown — don't bleed into next test
        assert result == pytest.approx(0.75)

    def test_global_T_compresses_toward_0p5(self, tmp_path, monkeypatch):
        """With a global T > 1, output is compressed toward 0.5 from both sides."""
        self._load_table(tmp_path, monkeypatch, {"global": {"T": 2.0, "n": 50}})
        import ml_bias

        result = ml_bias.apply_temperature_scaling(0.80)
        result_low = ml_bias.apply_temperature_scaling(0.20)
        ml_bias._TEMP_CACHE = None
        assert 0.5 < result < 0.80, f"Expected compression toward 0.5, got {result}"
        assert 0.20 < result_low < 0.5, (
            f"Expected compression toward 0.5, got {result_low}"
        )

    def test_per_condition_T_used_when_available(self, tmp_path, monkeypatch):
        """condition_type='between' uses the between T, not the global T."""
        self._load_table(
            tmp_path,
            monkeypatch,
            {
                "global": {"T": 2.0, "n": 50},
                "between": {"T": 8.0, "n": 25},
            },
        )
        import ml_bias

        result_between = ml_bias.apply_temperature_scaling(
            0.80, condition_type="between"
        )
        result_global = ml_bias.apply_temperature_scaling(0.80, condition_type="above")
        ml_bias._TEMP_CACHE = None
        # Higher T = more compression toward 0.5, so between result < global result
        assert result_between < result_global, (
            f"between T=8 should compress more than global T=2: "
            f"between={result_between:.4f}, global={result_global:.4f}"
        )

    def test_falls_back_to_global_when_condition_absent(self, tmp_path, monkeypatch):
        """Falls back to global T when condition_type is not in the table."""
        self._load_table(tmp_path, monkeypatch, {"global": {"T": 2.0, "n": 50}})
        import ml_bias

        # condition_type="above" not in table — must use global T (not no-op)
        result = ml_bias.apply_temperature_scaling(0.80, condition_type="above")
        ml_bias._TEMP_CACHE = None
        assert 0.5 < result < 0.80, (
            f"Expected global T fallback (compression), got {result} — "
            "no-op would return 0.80"
        )

    def test_sameday_uses_sameday_T(self, tmp_path, monkeypatch):
        """days_out=0 uses 'sameday' T, not the global T."""
        self._load_table(
            tmp_path,
            monkeypatch,
            {"global": {"T": 3.0, "n": 51}, "sameday": {"T": 1.5, "n": 25}},
        )
        import ml_bias

        result_sameday = ml_bias.apply_temperature_scaling(0.90, days_out=0)
        result_global = ml_bias.apply_temperature_scaling(0.90)
        ml_bias._TEMP_CACHE = None

        # sameday T=1.5 compresses less toward 0.5 than global T=3.0,
        # so sameday result should be closer to 0.90
        assert result_sameday > result_global, (
            f"sameday T=1.5 should compress less than global T=3.0: "
            f"sameday={result_sameday:.4f}, global={result_global:.4f}"
        )
        assert result_sameday < 0.90, "sameday T=1.5 should still compress somewhat"

    def test_sameday_no_fallback_to_global(self, tmp_path, monkeypatch):
        """days_out=0 returns prob unchanged when 'sameday' key absent — no global fallback.

        METAR-derived probabilities are sharp (near 0/1); applying multi-day T=3+
        would wrongly compress them toward 0.5.  Until 20 same-day trades settle,
        the identity scaling (T=1.0 no-op) is safer than the wrong multi-day T.
        """
        self._load_table(
            tmp_path,
            monkeypatch,
            {"global": {"T": 3.0, "n": 51}},  # global exists, sameday does not
        )
        import ml_bias

        result = ml_bias.apply_temperature_scaling(0.85, days_out=0)
        ml_bias._TEMP_CACHE = None

        assert result == pytest.approx(0.85), (
            f"days_out=0 with no sameday T should return prob unchanged, got {result}"
        )

    def test_multiday_unaffected_by_sameday_key(self, tmp_path, monkeypatch):
        """days_out=1 still uses per-condition/global T even when sameday key is present."""
        self._load_table(
            tmp_path,
            monkeypatch,
            {"global": {"T": 3.0, "n": 51}, "sameday": {"T": 1.5, "n": 25}},
        )
        import ml_bias

        result = ml_bias.apply_temperature_scaling(
            0.80, condition_type="above", days_out=1
        )
        ml_bias._TEMP_CACHE = None

        # 'above' not in table, so falls back to global T=3.0 — strong compression
        assert 0.5 < result < 0.80, (
            f"days_out=1 should use global T=3.0 (compression), got {result}"
        )


class TestEmos:
    def test_fit_emos_returns_four_floats(self):
        from ml_bias import fit_emos

        ens_mean = np.array([65.0, 72.0, 58.0, 80.0, 67.0, 71.0, 63.0, 75.0])
        ens_var = np.array([4.0, 9.0, 2.25, 16.0, 3.0, 6.0, 1.0, 12.0])
        obs = np.array([67.0, 70.0, 60.0, 82.0, 69.0, 73.0, 62.0, 77.0])
        a, b, c, d = fit_emos(ens_mean, ens_var, obs)
        assert isinstance(a, float)
        assert isinstance(b, float)
        assert c >= 0.0, f"c={c} must be non-negative"
        assert d >= 0.0, f"d={d} must be non-negative"

    def test_emos_exceedance_prob_in_bounds(self):
        from ml_bias import emos_exceedance_prob

        params = (0.5, 0.95, 1.5, 0.10)
        prob = emos_exceedance_prob(params, ens_mean=65.0, ens_var=4.0, threshold=70.0)
        assert 0.0 <= prob <= 1.0

    def test_emos_exceedance_prob_monotone(self):
        """Higher threshold → lower exceedance probability."""
        from ml_bias import emos_exceedance_prob

        params = (0.5, 0.95, 1.5, 0.10)
        p_low = emos_exceedance_prob(params, 70.0, 4.0, threshold=65.0)
        p_high = emos_exceedance_prob(params, 70.0, 4.0, threshold=80.0)
        assert p_low > p_high

    def test_emos_interval_prob_in_bounds(self):
        from ml_bias import emos_interval_prob

        params = (0.5, 0.95, 1.5, 0.10)
        prob = emos_interval_prob(
            params, ens_mean=68.0, ens_var=4.0, low=65.0, high=71.0
        )
        assert 0.0 <= prob <= 1.0

    def test_emos_interval_and_exceedance_consistent(self):
        """P(T>threshold) + P(low<T<threshold) should equal P(T>low)."""
        from ml_bias import emos_exceedance_prob, emos_interval_prob

        params = (0.5, 0.95, 1.5, 0.10)
        p_above_65 = emos_exceedance_prob(params, 70.0, 4.0, threshold=65.0)
        p_interval = emos_interval_prob(params, 70.0, 4.0, low=65.0, high=70.0)
        p_above_70 = emos_exceedance_prob(params, 70.0, 4.0, threshold=70.0)
        assert abs(p_above_65 - (p_interval + p_above_70)) < 0.001

    def test_load_emos_params_returns_none_when_file_missing(
        self, tmp_path, monkeypatch
    ):
        import ml_bias
        from ml_bias import _load_emos_params

        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", tmp_path / "emos_params.json")
        monkeypatch.setattr(ml_bias, "_EMOS_CACHE", None)
        assert _load_emos_params() is None

    def test_save_and_reload_emos_params(self, tmp_path, monkeypatch):
        import ml_bias
        from ml_bias import _load_emos_params, save_emos_params

        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", tmp_path / "emos_params.json")
        monkeypatch.setattr(ml_bias, "_EMOS_CACHE", None)
        save_emos_params(1.23, 0.94, 2.1, 0.18, n=79, mean_crps=0.42)
        monkeypatch.setattr(ml_bias, "_EMOS_CACHE", None)  # force reload
        params = _load_emos_params()
        assert params is not None
        a, b, c, d = params
        assert abs(a - 1.23) < 0.001
        assert abs(b - 0.94) < 0.001

    def test_get_emos_training_data_excludes_null_ens_mean(self, tmp_path, monkeypatch):
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
        tracker._db_initialized = False
        tracker.init_db()

        with tracker._conn() as con:
            # Row 1: has ens_mean + settled_temp_f → should appear
            con.execute(
                "INSERT INTO predictions (ticker, our_prob, market_prob, predicted_at, days_out, ens_mean, ens_var) "
                "VALUES ('KXHIGH-T70', 0.6, 0.55, '2026-06-01', 1, 72.3, 4.5)"
            )
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes, settled_at, settled_temp_f) "
                "VALUES ('KXHIGH-T70', 1, '2026-06-01', 73.0)"
            )
            # Row 2: ens_mean IS NULL → must be excluded
            con.execute(
                "INSERT INTO predictions (ticker, our_prob, market_prob, predicted_at, days_out) "
                "VALUES ('KXHIGH-T72', 0.5, 0.48, '2026-06-02', 1)"
            )
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes, settled_at, settled_temp_f) "
                "VALUES ('KXHIGH-T72', 0, '2026-06-02', 70.0)"
            )

        rows = tracker.get_emos_training_data()
        assert len(rows) == 1
        assert abs(rows[0]["ens_mean"] - 72.3) < 0.01
        assert abs(rows[0]["settled_temp_f"] - 73.0) < 0.01
        assert rows[0]["ens_var"] == pytest.approx(4.5, abs=0.01)

    def test_emos_exceedance_prob_called_via_load_emos_params(
        self, monkeypatch, tmp_path
    ):
        """_load_emos_params must return the cache when _EMOS_CACHE is populated."""
        import json

        import ml_bias

        params = {"a": 0.0, "b": 1.0, "c": 1.0, "d": 0.0, "n": 79}
        params_path = tmp_path / "emos_params.json"
        params_path.write_text(json.dumps(params))

        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", params_path)
        monkeypatch.setattr(ml_bias, "_EMOS_CACHE", None)

        loaded = ml_bias._load_emos_params()
        assert loaded is not None, "_load_emos_params returned None — file not read"
        a, b, c, d = loaded
        assert b == pytest.approx(1.0), "b param should be 1.0"

        # With a=0, b=1, c=1, d=0: mu=ens_mean=70, sigma=sqrt(1.0)=1.
        # P(T > 72 | N(70,1)) < 0.5
        prob = ml_bias.emos_exceedance_prob(loaded, 70.0, 4.0, threshold=72.0)
        assert 0.0 < prob < 0.5, (
            f"Expected prob < 0.5 when threshold > mean; got {prob}"
        )
