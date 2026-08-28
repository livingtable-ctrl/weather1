"""Tests for ML-based bias correction."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

_requires_properscoring = pytest.mark.skipif(
    importlib.util.find_spec("properscoring") is None,
    reason="properscoring not installed (production degrades gracefully via main.py's own guard)",
)


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


# ── METAR lock-in beta calibration ───────────────────────────────────────────


def _metar_rows(n_yes: int, yes_hit_rate: float, n_no: int, no_hit_rate: float, seed=7):
    """Synthesize {our_prob, settled_yes} rows shaped like real METAR lock-in
    data: high-confidence YES-locks (prob clustered high) and high-confidence
    NO-locks (prob clustered low), each with their own real hit rate."""
    import random

    rng = random.Random(seed)
    rows = []
    for _ in range(n_yes):
        p = rng.uniform(0.75, 0.97)
        rows.append(
            {"our_prob": p, "settled_yes": 1 if rng.random() < yes_hit_rate else 0}
        )
    for _ in range(n_no):
        p = rng.uniform(0.03, 0.15)
        rows.append(
            {"our_prob": p, "settled_yes": 1 if rng.random() < (1 - no_hit_rate) else 0}
        )
    return rows


def test_fit_metar_calibration_below_epv_floor_returns_none():
    """Floor is on the MINORITY class count (EPV -- events per predictor
    variable), not raw row count. n_no=5 is the minority class here and is
    below METAR_CALIBRATION_MIN_EPV_PER_PREDICTOR (10) even though the
    total row count (25) might otherwise look plausible."""
    import ml_bias

    rows = _metar_rows(n_yes=20, yes_hit_rate=0.7, n_no=5, no_hit_rate=0.9)
    n_pos = sum(r["settled_yes"] for r in rows)
    n_neg = len(rows) - n_pos
    assert min(n_pos, n_neg) < ml_bias.METAR_CALIBRATION_MIN_EPV_PER_PREDICTOR
    assert ml_bias.fit_metar_calibration(rows) is None


def test_fit_metar_calibration_at_epv_floor_succeeds():
    """The mirror case: minority class exactly at/above the floor must
    succeed -- positive control for the test above, so a floor check that's
    silently always-true (e.g. comparing the wrong count) wouldn't pass both."""
    import ml_bias

    rows = _metar_rows(n_yes=20, yes_hit_rate=0.7, n_no=15, no_hit_rate=0.9)
    n_pos = sum(r["settled_yes"] for r in rows)
    n_neg = len(rows) - n_pos
    assert min(n_pos, n_neg) >= ml_bias.METAR_CALIBRATION_MIN_EPV_PER_PREDICTOR
    assert ml_bias.fit_metar_calibration(rows) is not None


def test_fit_metar_calibration_rejects_non_binary_labels():
    """A corrupted settled_yes value (anything other than exactly 0 or 1)
    must refuse to fit rather than silently distort the result."""
    import ml_bias

    rows = _metar_rows(n_yes=20, yes_hit_rate=0.7, n_no=15, no_hit_rate=0.9)
    rows[0]["settled_yes"] = 2
    assert ml_bias.fit_metar_calibration(rows) is None


def test_fit_metar_calibration_on_real_repo_data():
    """Regression test for this repo's real production data (2026-08-16):
    27 YES-locks / 6 NO-locks, both overconfident. Confirms the simplified
    Platt-only fit (see fit_metar_calibration's docstring for why an
    earlier 2-parameter beta-calibration attempt with a degenerate-fit
    fallback was replaced by fitting Platt directly) reproduces the exact
    coefficients two independent opus reviews verified against this same
    dataset (a=b=0.2262, c=0.4001)."""
    import ml_bias

    real_pred_actual_pairs = [
        (0.030, 1),
        (0.030, 1),
        (0.030, 0),
        (0.053, 1),
        (0.130, 0),
        (0.149, 0),
        (0.756, 0),
        (0.757, 1),
        (0.768, 0),
        (0.808, 0),
        (0.809, 1),
        (0.827, 0),
        (0.839, 1),
        (0.843, 1),
        (0.881, 0),
        (0.899, 1),
        (0.899, 1),
        (0.923, 1),
        (0.923, 0),
        (0.923, 0),
        (0.928, 0),
        (0.933, 1),
        (0.934, 1),
        (0.934, 1),
        (0.935, 1),
        (0.935, 1),
        (0.942, 1),
        (0.958, 1),
        (0.958, 1),
        (0.970, 1),
        (0.970, 1),
        (0.970, 1),
        (0.970, 1),
    ]
    rows = [{"our_prob": p, "settled_yes": y} for p, y in real_pred_actual_pairs]
    assert len(rows) == 33

    fit = ml_bias.fit_metar_calibration(rows)
    assert fit is not None
    a, b, c = fit
    assert a > 0 and b == pytest.approx(a), "must always be the a==b Platt form"
    assert a == pytest.approx(0.2262, abs=1e-3)
    assert c == pytest.approx(0.4001, abs=1e-3)


def test_apply_metar_calibration_matches_hand_computed_value():
    import math

    import ml_bias

    params = (0.5, 0.8, 0.1)
    raw = 0.7
    expected = 1.0 / (
        1.0 + math.exp(-(0.5 * math.log(0.7) - 0.8 * math.log(0.3) + 0.1))
    )
    assert ml_bias.apply_metar_calibration(raw, params) == pytest.approx(expected)


def test_apply_metar_calibration_platt_special_case_matches_apply_platt():
    """When a==b (fit_metar_calibration's Platt-only result is always this
    form), apply_metar_calibration must equal ordinary Platt scaling on
    logit(s) -- the mathematical identity this whole design relies on to
    reuse apply_metar_calibration's existing (a,b,c) signature unchanged."""
    import ml_bias

    a = 0.226
    c = 0.400
    for raw in (0.05, 0.3, 0.5, 0.7, 0.95):
        beta_result = ml_bias.apply_metar_calibration(raw, (a, a, c))
        platt_result = ml_bias.apply_platt_per_city("X", raw, {"X": (a, c)})
        assert beta_result == pytest.approx(platt_result, abs=1e-9)


def test_sigmoid_does_not_overflow_on_extreme_input():
    """_sigmoid must not raise OverflowError for a large-magnitude logit --
    reachable from apply_metar_calibration given an adversarial/corrupted
    coefficient set that somehow bypasses the loader's bounds (defense in
    depth, not assuming the loader is the only caller). Plain
    1/(1+exp(-x)) raises for x <~ -745; verified this reproduces on the
    unfixed implementation before writing the numerically-stable version."""
    import ml_bias

    assert ml_bias._sigmoid(-800.0) == pytest.approx(0.0, abs=1e-9)
    assert ml_bias._sigmoid(800.0) == pytest.approx(1.0, abs=1e-9)
    assert ml_bias._sigmoid(0.0) == pytest.approx(0.5)


def test_get_metar_lockout_calibration_data_scopes_correctly(tmp_path, monkeypatch):
    """Must include only days_out=0, method='metar_lockout', non-excluded
    condition_type rows -- everything else (ensemble sameday, multi-day
    metar_lockout-labeled rows [shouldn't exist but guard anyway], between)
    must be excluded."""
    import tracker

    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
    tracker._db_initialized = False
    tracker.init_db()

    with tracker._conn() as con:
        # Row 1: real target population -> must appear
        con.execute(
            "INSERT INTO predictions (ticker, our_prob, market_prob, predicted_at, days_out, method, condition_type) "
            "VALUES ('KXHIGH-M1', 0.90, 0.85, '2026-06-01', 0, 'metar_lockout', 'above')"
        )
        con.execute(
            "INSERT INTO outcomes (ticker, settled_yes, settled_at) VALUES ('KXHIGH-M1', 1, '2026-06-01')"
        )
        # Row 2: same-day but method='ensemble', not metar_lockout -> excluded
        con.execute(
            "INSERT INTO predictions (ticker, our_prob, market_prob, predicted_at, days_out, method, condition_type) "
            "VALUES ('KXHIGH-M2', 0.60, 0.55, '2026-06-02', 0, 'ensemble', 'above')"
        )
        con.execute(
            "INSERT INTO outcomes (ticker, settled_yes, settled_at) VALUES ('KXHIGH-M2', 1, '2026-06-02')"
        )
        # Row 3: metar_lockout but multi-day (days_out=1) -> excluded (shouldn't
        # exist in practice, but the query must not silently include it)
        con.execute(
            "INSERT INTO predictions (ticker, our_prob, market_prob, predicted_at, days_out, method, condition_type) "
            "VALUES ('KXHIGH-M3', 0.90, 0.85, '2026-06-03', 1, 'metar_lockout', 'above')"
        )
        con.execute(
            "INSERT INTO outcomes (ticker, settled_yes, settled_at) VALUES ('KXHIGH-M3', 1, '2026-06-03')"
        )
        # Row 4: metar_lockout, same-day, but condition_type='between' -> excluded
        con.execute(
            "INSERT INTO predictions (ticker, our_prob, market_prob, predicted_at, days_out, method, condition_type) "
            "VALUES ('KXHIGH-M4', 0.90, 0.85, '2026-06-04', 0, 'metar_lockout', 'between')"
        )
        con.execute(
            "INSERT INTO outcomes (ticker, settled_yes, settled_at) VALUES ('KXHIGH-M4', 1, '2026-06-04')"
        )

    rows = tracker.get_metar_lockout_calibration_data()
    assert len(rows) == 1
    assert rows[0]["our_prob"] == pytest.approx(0.90)
    assert rows[0]["settled_yes"] == 1


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

    # ── backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step 2 handoff
    # item 4: pool="hourly" -- days_out=0 alone can't distinguish an hourly
    # trade from an ordinary sameday one, so callers must pass pool="hourly"
    # explicitly, and it must behave with the same "no fallback" shape as
    # 'sameday'. ──────────────────────────────────────────────────────────

    def test_hourly_pool_uses_hourly_T(self, tmp_path, monkeypatch):
        self._load_table(
            tmp_path,
            monkeypatch,
            {
                "global": {"T": 3.0, "n": 51},
                "sameday": {"T": 1.5, "n": 25},
                "hourly": {"T": 2.0, "n": 20},
            },
        )
        import ml_bias

        result_hourly = ml_bias.apply_temperature_scaling(0.90, pool="hourly")
        result_sameday = ml_bias.apply_temperature_scaling(0.90, days_out=0)
        ml_bias._TEMP_CACHE = None

        assert result_hourly != result_sameday, (
            "pool='hourly' must use its own T (2.0), not silently reuse sameday's (1.5)"
        )

    def test_hourly_pool_no_fallback_to_sameday_or_global(self, tmp_path, monkeypatch):
        """No 'hourly' key yet (fewer than 20 settled hourly predictions) must
        return prob unchanged -- never fall back to sameday's or global's T,
        which are fitted on structurally different probability distributions."""
        self._load_table(
            tmp_path,
            monkeypatch,
            {"global": {"T": 3.0, "n": 51}, "sameday": {"T": 1.5, "n": 25}},
        )
        import ml_bias

        result = ml_bias.apply_temperature_scaling(0.85, pool="hourly")
        ml_bias._TEMP_CACHE = None

        assert result == pytest.approx(0.85), (
            f"pool='hourly' with no hourly T should return prob unchanged, got {result}"
        )

    def test_hourly_pool_ignored_when_days_out_passed_alongside(
        self, tmp_path, monkeypatch
    ):
        """pool='hourly' must win over days_out=0's sameday branch -- callers
        pass both, and pool is the more specific signal."""
        self._load_table(
            tmp_path,
            monkeypatch,
            {"sameday": {"T": 1.5, "n": 25}, "hourly": {"T": 4.0, "n": 20}},
        )
        import ml_bias

        result = ml_bias.apply_temperature_scaling(0.90, days_out=0, pool="hourly")
        ml_bias._TEMP_CACHE = None

        # T=4.0 compresses much harder than T=1.5 -- confirms hourly's T was
        # actually used, not sameday's.
        assert result < 0.75, (
            f"expected strong T=4.0 compression (hourly), got {result} "
            "-- looks like sameday's T=1.5 was used instead"
        )

    def test_ordinary_sameday_call_unaffected_by_hourly_key_presence(
        self, tmp_path, monkeypatch
    ):
        """Existing callers (no pool arg) must be completely unaffected by an
        'hourly' key existing in the table -- confirms the two pools are
        genuinely independent, not accidentally cross-wired."""
        self._load_table(
            tmp_path,
            monkeypatch,
            {"sameday": {"T": 1.5, "n": 25}, "hourly": {"T": 4.0, "n": 20}},
        )
        import ml_bias

        result_with_hourly = ml_bias.apply_temperature_scaling(0.90, days_out=0)
        ml_bias._TEMP_CACHE = None
        self._load_table(tmp_path, monkeypatch, {"sameday": {"T": 1.5, "n": 25}})
        result_without_hourly = ml_bias.apply_temperature_scaling(0.90, days_out=0)
        ml_bias._TEMP_CACHE = None

        assert result_with_hourly == pytest.approx(result_without_hourly)


class TestTrainAllTemperatureScalingRainExclusion:
    """backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2 handoff item
    (ml_bias.py defensive exclusion): monthly-rain rows (condition_type=
    'precip_month_total', days_out typically >=1) must not leak into the
    main multi-day 'global' pool, which is tuned for °F-shaped
    temperature probabilities. No dedicated rain pool is created this
    pass -- this is purely a leak-prevention check."""

    def _seed(
        self, tracker, ticker, city, market_date, our_prob, settled_yes, condition_type
    ):
        analysis = {
            "condition": {"type": condition_type, "threshold": 7.0},
            "forecast_prob": our_prob,
            "market_prob": 0.5,
            "edge": 0.1,
            "method": "ensemble",
        }
        tracker.log_prediction(ticker, city, market_date, analysis)
        tracker.log_outcome(ticker, settled_yes)

    def test_rain_rows_excluded_from_global_pool(self, tmp_path, monkeypatch):
        from datetime import date

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale.json")
        tracker.init_db()

        probs = [0.9] * 10 + [0.1] * 10
        labels = [1] * 7 + [0] * 3 + [0] * 7 + [1] * 3
        # 20 ordinary daily (multi-day, days_out=~11 from log_prediction's
        # own market_date-vs-today derivation) temperature rows.
        for i in range(20):
            self._seed(
                tracker,
                f"KXHIGHNY-26AUG{i:02d}-T75",
                "NYC",
                date.today() + __import__("datetime").timedelta(days=11),
                probs[i],
                labels[i],
                "above",
            )
        # 20 monthly-rain rows -- close_time-derived target_date, real
        # days_out, condition_type="precip_month_total".
        for i in range(20):
            self._seed(
                tracker,
                f"KXRAINDENM-26AUG-{i % 7 + 1}",
                "Denver",
                date.today() + __import__("datetime").timedelta(days=11),
                probs[i],
                labels[i],
                "precip_month_total",
            )

        ml_bias.train_all_temperature_scaling(
            min_samples_global=1, min_samples_condition=1
        )

        with open(tmp_path / "temperature_scale.json") as f:
            import json

            saved = json.load(f)

        assert saved["global"]["n"] == 20, (
            f"global pool must contain only the 20 daily rows, not the rain "
            f"ones too, got n={saved['global']['n']}"
        )
        assert "precip_month_total" not in saved

    def test_snow_rows_excluded_from_global_pool(self, tmp_path, monkeypatch):
        """backlog.txt Snow Step 2: the identical leak-prevention check,
        mirrored for 'snow_month_total' -- the same landmine rain's own
        Step 2 closed for this exact query."""
        from datetime import date

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale.json")
        tracker.init_db()

        probs = [0.9] * 10 + [0.1] * 10
        labels = [1] * 7 + [0] * 3 + [0] * 7 + [1] * 3
        for i in range(20):
            self._seed(
                tracker,
                f"KXHIGHNY-26AUG{i:02d}-T75",
                "NYC",
                date.today() + __import__("datetime").timedelta(days=11),
                probs[i],
                labels[i],
                "above",
            )
        for i in range(20):
            self._seed(
                tracker,
                f"KXDENSNOWM-26DEC-{i % 7 + 1}",
                "Denver",
                date.today() + __import__("datetime").timedelta(days=11),
                probs[i],
                labels[i],
                "snow_month_total",
            )

        ml_bias.train_all_temperature_scaling(
            min_samples_global=1, min_samples_condition=1
        )

        with open(tmp_path / "temperature_scale.json") as f:
            import json

            saved = json.load(f)

        assert saved["global"]["n"] == 20, (
            f"global pool must contain only the 20 daily rows, not the snow "
            f"ones too, got n={saved['global']['n']}"
        )
        assert "snow_month_total" not in saved

    def test_hurricane_rows_excluded_from_global_pool(self, tmp_path, monkeypatch):
        """Opus-review-caught (2026-08-07): this exclusion list was never
        extended for 'hurricane_count' (shipped 2026-08-03) or
        'hurricane_next_event' (same session) -- both always carry a real,
        large days_out (>=1, these markets open months ahead), so unlike
        rain/snow's own "confirmed reachable" caveat below, this leak was
        NOT merely theoretical: without the fix, a settled hurricane row
        would unconditionally land in the °F-tuned global temperature-
        scaling pool. 'storm_order' (this session) is added up front for the
        same reason rather than discovered as a gap later. Only the
        global-pool query is exercised here -- the sameday pool
        (days_out=0) is structurally unreachable for this family
        (HURRICANE_MAX_DAYS_OUT alone rules out days_out=0), unlike snow's
        own sameday leak below, which was confirmed reachable."""
        from datetime import date

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale.json")
        tracker.init_db()

        probs = [0.9] * 10 + [0.1] * 10
        labels = [1] * 7 + [0] * 3 + [0] * 7 + [1] * 3
        for i in range(20):
            self._seed(
                tracker,
                f"KXHIGHNY-26AUG{i:02d}-T75",
                "NYC",
                date.today() + __import__("datetime").timedelta(days=11),
                probs[i],
                labels[i],
                "above",
            )
        for i in range(10):
            self._seed(
                tracker,
                f"KXHURCTOT-26DEC01-T{i}",
                "HUR_ATL",
                date.today() + __import__("datetime").timedelta(days=100),
                probs[i],
                labels[i],
                "hurricane_count",
            )
        for i in range(10):
            self._seed(
                tracker,
                f"KXNEXTHURDATE-26DEC01-26SEP{i:02d}",
                "HUR_ATL",
                date.today() + __import__("datetime").timedelta(days=39),
                probs[i],
                labels[i],
                "hurricane_next_event",
            )
        for i in range(10):
            self._seed(
                tracker,
                f"KXFIRSTHURRICANE-26DEC01ATL-N{i:02d}",
                "HUR_ATL",
                date.today() + __import__("datetime").timedelta(days=116),
                probs[i],
                labels[i],
                "storm_order",
            )

        ml_bias.train_all_temperature_scaling(
            min_samples_global=1, min_samples_condition=1
        )

        with open(tmp_path / "temperature_scale.json") as f:
            import json

            saved = json.load(f)

        assert saved["global"]["n"] == 20, (
            f"global pool must contain only the 20 daily rows, not the "
            f"hurricane ones too, got n={saved['global']['n']}"
        )
        assert "hurricane_count" not in saved
        assert "hurricane_next_event" not in saved
        assert "storm_order" not in saved

    def test_snow_rows_excluded_from_sameday_pool(self, tmp_path, monkeypatch):
        """Opus-review-caught gap: the global pool's exclusion above (line
        ~604 in ml_bias.py) is a separate SQL query from the 'sameday'
        pool's own exclusion (~line 626, days_out=0) -- mutating just the
        sameday site's exclusion passed the entire scoped suite with zero
        failures, since every other test seeds days_out>=1 rows only. A
        monthly-snow ticker settled on its own close date genuinely can
        carry days_out=0 (test_get_sameday_calibration_cli_excludes_snow in
        test_tracker.py already proves this is reachable, not
        hypothetical) -- if it leaked in here, it would shift T_sameday,
        which apply_temperature_scaling(days_out=0) then applies to every
        METAR-locked same-day temperature trade."""
        import ml_bias
        import tracker
        from utils import utc_today

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale.json")
        tracker.init_db()

        probs = [0.9] * 10 + [0.1] * 10
        labels = [1] * 7 + [0] * 3 + [0] * 7 + [1] * 3
        today = utc_today()
        for i in range(20):
            self._seed(
                tracker,
                f"KXHIGHNY-26AUG{i:02d}-T75",
                "NYC",
                today,
                probs[i],
                labels[i],
                "above",
            )
        for i in range(20):
            self._seed(
                tracker,
                f"KXDENSNOWM-26DEC-{i % 7 + 1}-{i}",
                "Denver",
                today,
                probs[i],
                labels[i],
                "snow_month_total",
            )

        ml_bias.train_all_temperature_scaling(
            min_samples_global=1, min_samples_condition=1
        )

        with open(tmp_path / "temperature_scale.json") as f:
            import json

            saved = json.load(f)

        assert saved["sameday"]["n"] == 20, (
            f"sameday pool must contain only the 20 daily rows, not the "
            f"snow ones too, got n={saved['sameday']['n']}"
        )


class TestTrainBiasModelRainExclusion:
    """backlog.txt "RAIN / SNOW / HURRICANE MARKETS" Step 2 (review-caught
    gap): train_bias_model() reads the same multiday_predictions view via
    its own separate query -- must exclude 'precip_month_total' the same
    way train_all_temperature_scaling() does, or a city's per-city
    GradientBoosting bias-correction model gets trained partly on
    inches-scale rain residuals."""

    def _seed(
        self, tracker, ticker, city, market_date, our_prob, settled_yes, condition_type
    ):
        analysis = {
            "condition": {"type": condition_type, "threshold": 7.0},
            "forecast_prob": our_prob,
            "market_prob": 0.5,
            "edge": 0.1,
            "method": "ensemble",
        }
        tracker.log_prediction(ticker, city, market_date, analysis)
        tracker.log_outcome(ticker, settled_yes)

    def test_only_daily_rows_reach_the_fit_call(self, tmp_path, monkeypatch):
        """Directly inspects what train_bias_model() actually fits on --
        decoupled from whether GradientBoostingRegressor's own holdout
        check happens to accept or reject the city, which made an earlier
        version of this test pass vacuously even against the unfixed query
        (10 synthetic rain rows didn't beat the MSE-vs-baseline check
        either way, so "no model produced" wasn't proof the exclusion
        worked). Seeds 8 daily rows (city_data should end up with exactly
        8 samples) plus 10 rain rows for the SAME city -- the fit() call's
        training-set size directly proves whether the rain rows leaked in."""
        from datetime import timedelta
        from unittest.mock import MagicMock, patch

        import ml_bias
        import tracker
        from utils import utc_today

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        tracker.init_db()

        # log_prediction computes days_out via utils.utc_today() -- i=0 gives
        # a +1-day market_date, and a local-behind-UTC sandbox timezone would
        # collapse that to days_out=0, silently dropping the row from the
        # "daily" (days_out>=1) pool this test's fit_calls assertion counts.
        for i in range(8):
            self._seed(
                tracker,
                f"KXHIGHNY-26AUG{i:02d}-T75",
                "MixedCity",
                utc_today() + timedelta(days=i % 20 + 1),
                0.5 + (i % 2) * 0.3,
                i % 2,
                "above",
            )
        for i in range(10):
            self._seed(
                tracker,
                f"KXRAINDENM-26AUG-{i % 7 + 1}-{i}",
                "MixedCity",
                utc_today() + timedelta(days=i % 20 + 1),
                0.5 + (i % 2) * 0.3,
                i % 2,
                "precip_month_total",
            )

        fit_calls = []

        def _fake_regressor(*a, **k):
            m = MagicMock()

            def _fit(X, y):
                fit_calls.append(len(X))

            m.fit.side_effect = _fit
            m.predict.return_value = [0.0] * 100  # oversized, sliced by zip anyway
            return m

        with patch(
            "sklearn.ensemble.GradientBoostingRegressor", side_effect=_fake_regressor
        ):
            ml_bias.train_bias_model(min_samples=5)

        assert fit_calls, "MixedCity should have reached the fit() call at all"
        # 8 daily rows, 80/20 split -> X_train has int(8*0.8)=6 rows.
        # If the 10 rain rows leaked in (18 total), X_train would be
        # int(18*0.8)=14 instead.
        assert fit_calls[0] == 6, (
            f"expected fit() on exactly the 6 daily training rows "
            f"(8 daily * 0.8 split), got {fit_calls[0]} -- rain rows leaked in "
            f"if this is higher"
        )

    def test_only_daily_rows_reach_the_fit_call_snow(self, tmp_path, monkeypatch):
        """backlog.txt Snow Step 2: mirrors the rain test above exactly for
        'snow_month_total' -- the identical landmine, closed the same way."""
        from datetime import timedelta
        from unittest.mock import MagicMock, patch

        import ml_bias
        import tracker
        from utils import utc_today

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        tracker.init_db()

        for i in range(8):
            self._seed(
                tracker,
                f"KXHIGHNY-26AUG{i:02d}-T75",
                "SnowMixedCity",
                utc_today() + timedelta(days=i % 20 + 1),
                0.5 + (i % 2) * 0.3,
                i % 2,
                "above",
            )
        for i in range(10):
            self._seed(
                tracker,
                f"KXDENSNOWM-26DEC-{i % 7 + 1}-{i}",
                "SnowMixedCity",
                utc_today() + timedelta(days=i % 20 + 1),
                0.5 + (i % 2) * 0.3,
                i % 2,
                "snow_month_total",
            )

        fit_calls = []

        def _fake_regressor(*a, **k):
            m = MagicMock()

            def _fit(X, y):
                fit_calls.append(len(X))

            m.fit.side_effect = _fit
            m.predict.return_value = [0.0] * 100
            return m

        with patch(
            "sklearn.ensemble.GradientBoostingRegressor", side_effect=_fake_regressor
        ):
            ml_bias.train_bias_model(min_samples=5)

        assert fit_calls, "SnowMixedCity should have reached the fit() call at all"
        assert fit_calls[0] == 6, (
            f"expected fit() on exactly the 6 daily training rows "
            f"(8 daily * 0.8 split), got {fit_calls[0]} -- snow rows leaked "
            f"in if this is higher"
        )


class TestTrainAllTemperatureScalingHourlyPool:
    """backlog.txt "HOURLY-DIRECTIONAL TEMPERATURE MARKETS" Step 2 handoff
    item 4: train_all_temperature_scaling() must isolate hourly (KXTEMPxxxH,
    days_out=0) rows into their own 'hourly' pool -- separate from 'sameday'
    (ordinary days_out=0 daily trades) even though both share days_out=0,
    since only the ticker prefix distinguishes them."""

    def _seed(self, tracker, ticker, city, market_date, our_prob, settled_yes):
        analysis = {
            "condition": {"type": "above", "threshold": 70.0},
            "forecast_prob": our_prob,
            "market_prob": 0.5,
            "edge": 0.1,
            "method": "ensemble",
        }
        tracker.log_prediction(ticker, city, market_date, analysis)
        tracker.log_outcome(ticker, settled_yes)
        # Force days_out=0 regardless of market_date's relation to "today"
        # (log_prediction derives it from market_date - utc_today()).
        with tracker._conn() as con:
            con.execute(
                "UPDATE predictions SET days_out = 0 WHERE ticker = ?", (ticker,)
            )

    def test_hourly_rows_excluded_from_sameday_pool(self, tmp_path, monkeypatch):
        from datetime import date

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale.json")
        tracker.init_db()

        # Genuinely overconfident (fixable by T-scaling) synthetic pattern:
        # predicts sharp 90/10, actual rate is a milder 70/30 in each group.
        # mean_pred == mean_actual == 0.5 by symmetry, so this is a confidence
        # problem (T > 1 helps), not a directional-bias one (which _fit_T
        # correctly refuses to "fix" via T-scaling and returns None for).
        probs = [0.9] * 10 + [0.1] * 10
        labels = [1] * 7 + [0] * 3 + [0] * 7 + [1] * 3
        for i in range(20):
            self._seed(
                tracker,
                f"KXTEMPNYCH-26JUL20{i:02d}-T75.99",
                "NYC",
                date(2026, 7, 20),
                probs[i],
                labels[i],
            )
        for i in range(20):
            self._seed(
                tracker,
                f"KXHIGHNY-26JUL{i:02d}-T75",
                "NYC",
                date(2026, 7, 20),
                probs[i],
                labels[i],
            )

        ml_bias.train_all_temperature_scaling(
            min_samples_global=1, min_samples_condition=1
        )

        with open(tmp_path / "temperature_scale.json") as f:
            import json

            saved = json.load(f)

        assert "hourly" in saved, "hourly pool must be trained once >=20 samples exist"
        assert saved["hourly"]["n"] == 20, (
            f"hourly pool should have exactly the 20 hourly rows, got n={saved['hourly']['n']}"
        )
        assert saved.get("sameday", {}).get("n", 0) == 20, (
            "sameday pool should have exactly the 20 daily rows, not include hourly ones"
        )

    def test_sql_paren_regression_multiday_hourly_row_excluded_from_sameday(
        self, tmp_path, monkeypatch
    ):
        """Targets the exact SQL operator-precedence risk directly: SQL's AND
        binds tighter than OR, so "days_out=0 AND NOT (ticker LIKE p1 OR
        ticker LIKE p2 OR ...)" without the parens would collapse to "NOT
        ticker LIKE p1 OR ticker LIKE p2 OR ..." -- a *multi-day* (days_out=1)
        row whose ticker matches a NON-FIRST prefix (KXTEMPDCH, last in
        _KXTEMP_HOURLY_CITY's iteration order) would then satisfy the
        standalone "OR ticker LIKE p_last" disjunct regardless of days_out,
        silently leaking into the 'sameday' pool. The other regression test
        above only seeds days_out=0 rows on a single (first) prefix, which a
        missing-parens mutation would NOT actually fail on -- this test
        specifically would.
        """
        import json
        from datetime import date

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale.json")
        tracker.init_db()

        from weather_markets import _KXTEMP_HOURLY_CITY

        # batch-52: KXTEMPMIAH (Miami) is now the last-inserted entry, not
        # KXTEMPDCH (Washington) -- derive both dynamically rather than
        # hardcoding either, so this test doesn't silently mismatch ticker
        # prefix vs. city again the next time a 7th hourly city is added.
        last_prefix = list(_KXTEMP_HOURLY_CITY)[-1]
        last_city = _KXTEMP_HOURLY_CITY[last_prefix]

        probs = [0.9] * 10 + [0.1] * 10
        labels = [1] * 7 + [0] * 3 + [0] * 7 + [1] * 3
        # 20 genuine sameday (non-hourly) rows.
        for i in range(20):
            self._seed(
                tracker,
                f"KXHIGHNY-26JUL{i:02d}-T75",
                "NYC",
                date(2026, 7, 20),
                probs[i],
                labels[i],
            )
        # One multi-day (days_out=1) row on the LAST hourly prefix -- must
        # never be counted in 'sameday', regardless of SQL paren correctness.
        multiday_ticker = f"{last_prefix}-26JUL2114-T75.99"
        analysis = {
            "condition": {"type": "above", "threshold": 70.0},
            "forecast_prob": 0.9,
            "market_prob": 0.5,
            "edge": 0.1,
            "method": "ensemble",
        }
        tracker.log_prediction(multiday_ticker, last_city, date(2026, 7, 21), analysis)
        tracker.log_outcome(multiday_ticker, True)
        with tracker._conn() as con:
            con.execute(
                "UPDATE predictions SET days_out = 1 WHERE ticker = ?",
                (multiday_ticker,),
            )

        ml_bias.train_all_temperature_scaling(
            min_samples_global=1, min_samples_condition=1
        )

        saved = json.loads((tmp_path / "temperature_scale.json").read_text())
        assert saved.get("sameday", {}).get("n", 0) == 20, (
            f"sameday pool must be exactly the 20 genuine sameday rows -- a "
            f"missing-parens SQL bug would leak the multi-day hourly row in, "
            f"got n={saved.get('sameday', {}).get('n')}"
        )

    def test_hourly_pool_below_min_samples_not_trained(self, tmp_path, monkeypatch):
        from datetime import date

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale.json")
        tracker.init_db()

        for i in range(10):  # below the 20-sample gate
            self._seed(
                tracker,
                f"KXTEMPNYCH-26JUL20{i:02d}-T75.99",
                "NYC",
                date(2026, 7, 20),
                0.6,
                i % 2,
            )

        ml_bias.train_all_temperature_scaling(
            min_samples_global=1, min_samples_condition=1
        )

        temp_path = tmp_path / "temperature_scale.json"
        if temp_path.exists():
            import json

            saved = json.loads(temp_path.read_text())
            assert "hourly" not in saved, (
                "hourly pool must not be trained below its 20-sample gate"
            )


class TestEmos:
    @_requires_properscoring
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

    @_requires_properscoring
    def test_fit_emos_raises_on_optimizer_non_convergence(self, monkeypatch):
        """Audit batch-28 item 3: fit_emos must not silently return an
        unconverged fit -- mirrors _fit_platt's own res.success check.
        Mutation-tested via monkeypatching scipy.optimize.minimize directly
        (forcing real non-convergence on well-behaved synthetic data is
        unreliable), asserting the specific exception this fix adds."""
        import scipy.optimize

        import ml_bias

        class _FakeResult:
            success = False
            message = "fake non-convergence"
            x = np.array([0.0, 1.0, 1.0, 0.1])

        monkeypatch.setattr(scipy.optimize, "minimize", lambda *a, **kw: _FakeResult())

        ens_mean = np.array([65.0, 72.0, 58.0])
        ens_var = np.array([4.0, 9.0, 2.25])
        obs = np.array([67.0, 70.0, 60.0])
        with pytest.raises(ValueError, match="did not converge"):
            ml_bias.fit_emos(ens_mean, ens_var, obs)

    def test_emos_exceedance_prob_clamps_degenerate_fit_to_bounds(self):
        """Audit batch-28 item 3: a degenerate fit whose Gaussian is
        extremely tight and far from the threshold must not return an
        unclamped near-0/near-1 probability -- every sibling calibration
        applier in this file clamps to [0.01, 0.99]."""
        from ml_bias import EMOS_SIGMA_VAR_FLOOR, emos_exceedance_prob

        # c=d=0 -> sigma floors at EMOS_SIGMA_VAR_FLOOR regardless of ens_var,
        # and the threshold is far below the mean -> raw exceedance ~1.0.
        params = (0.0, 1.0, 0.0, 0.0)
        prob = emos_exceedance_prob(params, ens_mean=90.0, ens_var=0.0, threshold=50.0)
        assert prob == pytest.approx(0.99)

        # Positive control: EMOS_SIGMA_VAR_FLOOR is really what's used, not
        # a residual reference to the old 1e-6 floor -- a threshold just
        # inside +/-1 sigma of that floor produces a non-extreme probability.
        near_prob = emos_exceedance_prob(
            params,
            ens_mean=90.0,
            ens_var=0.0,
            threshold=90.0 - EMOS_SIGMA_VAR_FLOOR**0.5,
        )
        assert 0.7 < near_prob < 0.9

    def test_emos_interval_prob_clamps_degenerate_fit_to_bounds(self):
        from ml_bias import emos_interval_prob

        params = (0.0, 1.0, 0.0, 0.0)
        # Interval far from the (degenerate, near-point-mass) distribution
        # -> raw probability ~0.0, must clamp up to 0.01, not return ~0.
        prob = emos_interval_prob(
            params, ens_mean=90.0, ens_var=0.0, low=10.0, high=20.0
        )
        assert prob == pytest.approx(0.01)

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

    def test_count_emos_variance_ready_predictions_requires_ens_var(
        self, tmp_path, monkeypatch
    ):
        """The stricter count (what actually gates EMOS's c/d variance fit)
        must exclude backfill rows that have ens_mean but no ens_var --
        count_emos_ready_predictions() (mean-only) does NOT exclude them,
        which is exactly why the two counts can diverge and the looser one
        can't be trusted alone as an EMOS-readiness signal."""
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
        tracker._db_initialized = False
        tracker.init_db()

        with tracker._conn() as con:
            # Row 1: ens_mean + ens_var + settled_temp_f all populated -> counted
            con.execute(
                "INSERT INTO predictions (ticker, our_prob, market_prob, predicted_at, days_out, ens_mean, ens_var) "
                "VALUES ('KXHIGH-T70', 0.6, 0.55, '2026-06-01', 1, 72.3, 4.5)"
            )
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes, settled_at, settled_temp_f) "
                "VALUES ('KXHIGH-T70', 1, '2026-06-01', 73.0)"
            )
            # Row 2: ens_mean + settled_temp_f present but ens_var NULL
            # (backfill row) -> must be excluded from the strict count
            con.execute(
                "INSERT INTO predictions (ticker, our_prob, market_prob, predicted_at, days_out, ens_mean) "
                "VALUES ('KXHIGH-T72', 0.5, 0.48, '2026-06-02', 1, 71.0)"
            )
            con.execute(
                "INSERT INTO outcomes (ticker, settled_yes, settled_at, settled_temp_f) "
                "VALUES ('KXHIGH-T72', 0, '2026-06-02', 70.0)"
            )

        assert tracker.count_emos_variance_ready_predictions() == 1
        # Positive control: the looser mean-only count must be 2, proving row 2
        # really was inserted and reachable -- so the strict count above is
        # actually filtering it on ens_var, not silently seeing zero rows total.
        assert tracker.count_emos_ready_predictions() == 2

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

    def test_get_emos_status_inactive_when_file_missing(self, tmp_path, monkeypatch):
        import ml_bias
        from ml_bias import get_emos_status

        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", tmp_path / "emos_params.json")
        # batch-37 item 4: t_pinned is now computed even in the inactive
        # case -- isolate _TEMP_PATH so this doesn't read the real machine's
        # data/temperature_scale.json.
        monkeypatch.setattr(
            ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale_dne.json"
        )
        assert get_emos_status() == {"active": False, "t_pinned": False}

    def test_get_emos_status_surfaces_t_pinned_when_inactive_after_failed_restore(
        self, tmp_path, monkeypatch
    ):
        """batch-37 item 4: the exact post-deactivate-with-failed-restore
        state -- emos_params.json is gone (active correctly False) but
        temperature_scale.json's reset_for_emos placeholders were never
        restored (t_pinned still True). A prior version's early return for
        the inactive case never computed t_pinned at all, hiding this from
        any caller checking status right after deactivation.

        Mutation-tested: reverting to the early `return {"active": False}`
        (before t_pinned is computed) makes this fail with a KeyError on
        status["t_pinned"] -- confirmed via Edit revert.
        """
        import json

        import ml_bias
        from ml_bias import get_emos_status

        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", tmp_path / "emos_params.json")
        temp_path = tmp_path / "temperature_scale.json"
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", temp_path)
        temp_path.write_text(
            json.dumps(
                {
                    key: {"T": 1.0, "n": 10, "reset_for_emos": True}
                    for key in ml_bias.EMOS_COVERED_CONDITION_KEYS
                }
            )
        )

        status = get_emos_status()

        assert status["active"] is False
        assert status["t_pinned"] is True

    def test_get_emos_status_active_returns_all_fields(self, tmp_path, monkeypatch):
        import ml_bias
        from ml_bias import get_emos_status, save_emos_params

        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", tmp_path / "emos_params.json")
        monkeypatch.setattr(ml_bias, "_EMOS_CACHE", None)
        save_emos_params(1.1, 0.9, 2.2, 0.15, n=55, mean_crps=0.28)

        status = get_emos_status()
        assert status["active"] is True
        assert status["a"] == pytest.approx(1.1)
        assert status["n"] == 55
        assert status["mean_crps"] == pytest.approx(0.28)
        assert status["fitted_at"]

    def test_get_emos_status_genuinely_corrupt_file_reports_corrupt(
        self, tmp_path, monkeypatch
    ):
        """Positive control for the TOCTOU-race test below: a file that
        exists but is genuinely unparseable must still come back tagged
        corrupt=True, not silently reclassified as "just a race". Also
        patches _TEMP_PATH to a definitely-absent path (audit batch-28
        item 3 follow-up: t_pinned is now computed and included even in
        the corrupt branch) so the expected t_pinned=False is deterministic
        rather than depending on whatever real temperature_scale.json
        happens to exist on the machine running this test."""
        import ml_bias
        from ml_bias import get_emos_status

        path = tmp_path / "emos_params.json"
        path.write_text("not valid json{")
        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", path)
        monkeypatch.setattr(
            ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale_dne.json"
        )

        status = get_emos_status()
        assert status == {
            "active": False,
            "corrupt": True,
            "error": status.get("error"),
            "t_pinned": False,
        }
        assert status["error"]

    def test_get_emos_status_toctou_delete_race_is_not_reported_as_corrupt(
        self, tmp_path, monkeypatch
    ):
        """AUD-0073: a concurrent deactivate_emos() unlinking the file
        between this function's exists() check and its read() must report
        the same {"active": False} shape as "never existed" -- not
        {"corrupt": True}, which would incorrectly tell an operator the
        params file is damaged when it's simply gone.

        Mutation-tested: removing the FileNotFoundError-specific except
        clause (letting it fall into the broad `except Exception`) makes
        this fail with {"active": False, "corrupt": True, "error": ...}
        instead -- confirmed by temporarily reverting the fix via Edit.
        """
        import ml_bias
        from ml_bias import get_emos_status

        class _RacyPath:
            def exists(self):
                return True

            def read_text(self):
                raise FileNotFoundError(
                    "[Errno 2] No such file or directory: 'emos_params.json'"
                )

        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", _RacyPath())
        # batch-37 item 4: t_pinned is now computed unconditionally (before
        # the exists() check even runs) -- isolate _TEMP_PATH so this
        # doesn't read the real machine's data/temperature_scale.json.
        monkeypatch.setattr(
            ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale_dne.json"
        )

        status = get_emos_status()
        assert status == {"active": False, "t_pinned": False}
        assert "corrupt" not in status

    def test_get_emos_status_other_read_errors_still_report_corrupt(self, monkeypatch):
        """Regression guard (opus-review-caught during batch-14): the
        FileNotFoundError-specific except above must not accidentally
        narrow the surrounding coverage so a DIFFERENT read-time exception
        (PermissionError, IsADirectoryError, UnicodeDecodeError, ...)
        propagates uncaught instead of degrading to corrupt=True like it
        did before this fix. cmd_emos_status/cmd_emos_deactivate in main.py
        call get_emos_status() with no surrounding try/except, so an
        uncaught exception here would crash those CLI commands outright.

        Mutation-tested: replacing the single shared try/except chain with
        two separate try blocks (one narrowly catching only
        FileNotFoundError around the read, a second around the parse) makes
        this fail with an unhandled PermissionError -- confirmed via Edit
        revert to that exact shape during review.
        """
        import ml_bias
        from ml_bias import get_emos_status

        class _UnreadablePath:
            def exists(self):
                return True

            def read_text(self):
                raise PermissionError("[Errno 13] Permission denied")

        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", _UnreadablePath())

        status = get_emos_status()
        assert status["active"] is False
        assert status["corrupt"] is True
        assert status["error"]

    def test_get_emos_status_t_pinned_true_when_all_keys_reset(
        self, tmp_path, monkeypatch
    ):
        """Audit batch-28 item 3: t_pinned cross-checks 'active per params
        file' against 'T actually reset in temperature_scale.json'."""
        import json

        import ml_bias
        from ml_bias import get_emos_status, save_emos_params

        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", tmp_path / "emos_params.json")
        monkeypatch.setattr(ml_bias, "_EMOS_CACHE", None)
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale.json")
        save_emos_params(1.1, 0.9, 2.2, 0.15, n=55)
        (tmp_path / "temperature_scale.json").write_text(
            json.dumps(
                {
                    key: {"T": 1.0, "n": 10, "reset_for_emos": True}
                    for key in ml_bias.EMOS_COVERED_CONDITION_KEYS
                }
            )
        )

        assert get_emos_status()["t_pinned"] is True

    def test_get_emos_status_t_pinned_false_when_diverged(self, tmp_path, monkeypatch):
        """Positive control for the test above: a temperature_scale.json
        that's missing the reset markers (state drift, or T-scaling refit
        over EMOS's placeholder out-of-band) must report t_pinned=False, not
        silently claim the pin is intact."""
        import json

        import ml_bias
        from ml_bias import get_emos_status, save_emos_params

        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", tmp_path / "emos_params.json")
        monkeypatch.setattr(ml_bias, "_EMOS_CACHE", None)
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale.json")
        save_emos_params(1.1, 0.9, 2.2, 0.15, n=55)
        # 'above' carries a real fitted T, not the reset placeholder -- exactly
        # the divergence t_pinned exists to catch.
        (tmp_path / "temperature_scale.json").write_text(
            json.dumps(
                {
                    "global": {"T": 1.0, "n": 10, "reset_for_emos": True},
                    "above": {"T": 4.1, "n": 20},
                    "below": {"T": 1.0, "n": 10, "reset_for_emos": True},
                    "between": {"T": 1.0, "n": 10, "reset_for_emos": True},
                }
            )
        )

        assert get_emos_status()["t_pinned"] is False

    def test_get_emos_status_t_pinned_false_when_temp_scale_file_missing(
        self, tmp_path, monkeypatch
    ):
        import ml_bias
        from ml_bias import get_emos_status, save_emos_params

        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", tmp_path / "emos_params.json")
        monkeypatch.setattr(ml_bias, "_EMOS_CACHE", None)
        monkeypatch.setattr(
            ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale_dne.json"
        )
        save_emos_params(1.1, 0.9, 2.2, 0.15, n=55)

        assert get_emos_status()["t_pinned"] is False

    @pytest.fixture()
    def isolated_temp_paths(self, tmp_path, monkeypatch):
        """Shared isolation for reset/deactivate tests -- patches every
        module-level path/cache global these functions touch, including the
        pre-EMOS snapshot path and the two mtime-invalidation caches added
        alongside the opus-review fixes."""
        import ml_bias

        monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale.json")
        monkeypatch.setattr(ml_bias, "_TEMP_CACHE", None)
        monkeypatch.setattr(ml_bias, "_TEMP_CACHE_MTIME", None)
        monkeypatch.setattr(
            ml_bias,
            "_TEMP_PRE_EMOS_SNAPSHOT_PATH",
            tmp_path / "temperature_scale_pre_emos.json",
        )
        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", tmp_path / "emos_params.json")
        monkeypatch.setattr(ml_bias, "_EMOS_CACHE", None)
        monkeypatch.setattr(ml_bias, "_EMOS_CACHE_MTIME", None)
        return tmp_path

    def test_reset_temperature_scale_sets_identity_preserves_sameday(
        self, isolated_temp_paths
    ):
        """global/above/below/between all reset to T=1.0 (EMOS covers all
        4 -- 'between' included, since weather_markets.py calls
        emos_interval_prob for it) preserving their prior n; only 'sameday'
        (METAR-derived, EMOS never touches it) stays untouched."""
        import json

        from ml_bias import reset_temperature_scale_for_emos

        temp_path = isolated_temp_paths / "temperature_scale.json"
        temp_path.write_text(
            json.dumps(
                {
                    "global": {"T": 5.2, "n": 40},
                    "above": {"T": 4.1, "n": 20},
                    "below": {"T": 3.9, "n": 18},
                    "between": {"T": 6.8, "n": 23},
                    "sameday": {"T": 2.1, "n": 60},
                }
            )
        )

        reset_temperature_scale_for_emos()

        result = json.loads(temp_path.read_text())
        for key, prior_n in (
            ("global", 40),
            ("above", 20),
            ("below", 18),
            ("between", 23),
        ):
            assert result[key]["T"] == 1.0
            assert result[key]["n"] == prior_n
            assert result[key]["reset_for_emos"] is True
            assert result[key]["reset_at"]
        assert result["sameday"] == {"T": 2.1, "n": 60}

    def test_reset_temperature_scale_handles_missing_file(self, isolated_temp_paths):
        import json

        from ml_bias import reset_temperature_scale_for_emos

        reset_temperature_scale_for_emos()  # must not raise

        result = json.loads(
            (isolated_temp_paths / "temperature_scale.json").read_text()
        )
        assert result["global"]["T"] == 1.0
        assert result["above"]["T"] == 1.0
        assert result["below"]["T"] == 1.0
        assert result["between"]["T"] == 1.0

    def test_reset_temperature_scale_migrates_old_single_value_format(
        self, isolated_temp_paths
    ):
        """Old format is {"T": x, "n_samples": y} -- NOT {"T": x, "n": y}.
        Must match train_all_temperature_scaling's own migration convention
        (ml_bias.py's global-fit block), not silently zero the sample count."""
        import json

        from ml_bias import reset_temperature_scale_for_emos

        temp_path = isolated_temp_paths / "temperature_scale.json"
        temp_path.write_text(json.dumps({"T": 5.2, "n_samples": 40}))

        reset_temperature_scale_for_emos()

        result = json.loads(temp_path.read_text())
        assert result["global"]["T"] == 1.0
        assert result["global"]["n"] == 40

    def test_reset_temperature_scale_snapshots_prior_values(self, isolated_temp_paths):
        import json

        from ml_bias import reset_temperature_scale_for_emos

        temp_path = isolated_temp_paths / "temperature_scale.json"
        temp_path.write_text(json.dumps({"global": {"T": 5.2, "n": 40}}))

        reset_temperature_scale_for_emos()

        snapshot_path = isolated_temp_paths / "temperature_scale_pre_emos.json"
        assert snapshot_path.exists()
        snapshot = json.loads(snapshot_path.read_text())
        assert snapshot["global"] == {"T": 5.2, "n": 40}

    def test_reset_called_twice_preserves_original_snapshot_not_placeholder(
        self, isolated_temp_paths
    ):
        """Audit batch-28 item 2 core regression: calling
        reset_temperature_scale_for_emos() a SECOND time (simulating a
        retrain of an already-active EMOS, main.py's --activate flow with
        no separate retrain path) must NOT overwrite the real pre-EMOS
        snapshot with the 1.0 placeholders the first call itself wrote --
        that would permanently lose the only recoverable copy of the true T
        values, reproducing the zero-calibration incident as deactivate's
        normal outcome after any retrain."""
        import json

        from ml_bias import reset_temperature_scale_for_emos

        temp_path = isolated_temp_paths / "temperature_scale.json"
        temp_path.write_text(json.dumps({"global": {"T": 5.2, "n": 40}}))
        snapshot_path = isolated_temp_paths / "temperature_scale_pre_emos.json"

        reset_temperature_scale_for_emos()  # first activation
        snapshot_after_first = json.loads(snapshot_path.read_text())
        assert snapshot_after_first["global"] == {"T": 5.2, "n": 40}

        reset_temperature_scale_for_emos()  # retrain -- must be a no-op on the snapshot

        snapshot_after_second = json.loads(snapshot_path.read_text())
        assert snapshot_after_second["global"] == {"T": 5.2, "n": 40}, (
            f"snapshot must still hold the ORIGINAL real T=5.2, got "
            f"{snapshot_after_second['global']} -- the second reset call "
            "must have overwritten it with the 1.0 placeholder"
        )

    def test_activate_deactivate_activate_deactivate_survives_absent_covered_key(
        self, isolated_temp_paths
    ):
        """Independent-review finding (audit batch-28 item 2 follow-up, H1):
        'between' is a covered key but absent from temperature_scale.json at
        first activation (e.g. below its own min-samples floor). The first
        reset still writes it as a reset_for_emos=True placeholder (all 4
        covered keys always get one); restore only restores keys that WERE
        in the snapshot, so 'between' would otherwise be left behind as a
        permanent placeholder after deactivate -- and a same-key check on
        the SECOND reset would then see that stale marker and wrongly skip
        snapshotting the REAL global/above/below values, permanently losing
        them. Full two-cycle round trip: both deactivates must restore the
        SAME real global/above/below values, and 'between' must not survive
        either deactivate as a lingering placeholder."""
        import json

        from ml_bias import (
            reset_temperature_scale_for_emos,
            restore_temperature_scale_from_emos_snapshot,
        )

        temp_path = isolated_temp_paths / "temperature_scale.json"
        temp_path.write_text(
            json.dumps(
                {
                    "global": {"T": 2.62, "n": 40},
                    "above": {"T": 1.29, "n": 20},
                    "below": {"T": 3.9, "n": 18},
                    # 'between' deliberately absent -- below its own floor
                }
            )
        )

        reset_temperature_scale_for_emos()  # activation #1
        restored_1 = restore_temperature_scale_from_emos_snapshot()  # deactivate #1
        assert restored_1 is True
        state_after_1 = json.loads(temp_path.read_text())
        assert state_after_1["global"] == {"T": 2.62, "n": 40}
        assert state_after_1["above"] == {"T": 1.29, "n": 20}
        assert state_after_1["below"] == {"T": 3.9, "n": 18}
        assert "between" not in state_after_1, (
            "a covered key absent before activation must not survive "
            "deactivate as a leftover reset_for_emos placeholder"
        )

        reset_temperature_scale_for_emos()  # activation #2 (retrain-shaped)
        restored_2 = restore_temperature_scale_from_emos_snapshot()  # deactivate #2
        assert restored_2 is True, (
            "second deactivate must actually restore something -- if the "
            "second reset wrongly skipped snapshotting (H1), there would be "
            "no real snapshot for restore to consume"
        )
        state_after_2 = json.loads(temp_path.read_text())
        assert state_after_2["global"] == {"T": 2.62, "n": 40}, (
            f"global must still be the ORIGINAL real T=2.62 after the SECOND "
            f"deactivate too, got {state_after_2['global']} -- the stale "
            "'between' placeholder must not have blocked the second snapshot"
        )
        assert state_after_2["above"] == {"T": 1.29, "n": 20}
        assert state_after_2["below"] == {"T": 3.9, "n": 18}

    def test_restore_from_emos_snapshot_noop_when_no_snapshot(
        self, isolated_temp_paths
    ):
        from ml_bias import restore_temperature_scale_from_emos_snapshot

        assert restore_temperature_scale_from_emos_snapshot() is False

    def test_restore_from_emos_snapshot_restores_and_consumes_it(
        self, isolated_temp_paths
    ):
        import json

        from ml_bias import (
            reset_temperature_scale_for_emos,
            restore_temperature_scale_from_emos_snapshot,
        )

        temp_path = isolated_temp_paths / "temperature_scale.json"
        temp_path.write_text(json.dumps({"global": {"T": 5.2, "n": 40}}))
        reset_temperature_scale_for_emos()
        assert json.loads(temp_path.read_text())["global"]["T"] == 1.0

        restored = restore_temperature_scale_from_emos_snapshot()

        assert restored is True
        result = json.loads(temp_path.read_text())
        assert result["global"] == {"T": 5.2, "n": 40}
        assert not (isolated_temp_paths / "temperature_scale_pre_emos.json").exists()

    def test_deactivate_emos_removes_file_and_returns_true_when_active(
        self, isolated_temp_paths
    ):
        from ml_bias import deactivate_emos, save_emos_params

        save_emos_params(1.0, 1.0, 1.0, 0.1, n=50)

        was_active, _restored = deactivate_emos()

        assert was_active is True
        assert not (isolated_temp_paths / "emos_params.json").exists()

    def test_deactivate_emos_noop_when_already_inactive(self, isolated_temp_paths):
        from ml_bias import deactivate_emos

        was_active, restored = deactivate_emos()

        assert was_active is False
        assert restored is False  # no snapshot to restore -- benign no-op

    def test_deactivate_emos_archives_to_history_before_unlink(
        self, isolated_temp_paths
    ):
        """First-ever activation's params must survive deactivation --
        atomic_write_json_with_history only snapshots on overwrite, so a
        bare unlink on a file that's never been overwritten would lose the
        only copy."""
        from ml_bias import deactivate_emos, save_emos_params

        save_emos_params(1.23, 0.94, 2.1, 0.18, n=79, mean_crps=0.42)

        deactivate_emos()

        history_dir = isolated_temp_paths / ".history"
        archived = list(history_dir.glob("emos_params_*.json"))
        assert len(archived) == 1
        import json

        assert json.loads(archived[0].read_text())["a"] == pytest.approx(1.23)

    def test_deactivate_emos_propagates_successful_restore(self, isolated_temp_paths):
        """batch-37 item 4: deactivate_emos() must propagate the restore
        result, not just was_active -- positive control (restored=True) for
        the noop test above's restored=False. A prior version discarded
        restore_temperature_scale_from_emos_snapshot()'s return entirely,
        so cmd_emos_deactivate's CLI print always claimed success even when
        the restore silently failed.

        Mutation-tested: reverting deactivate_emos() to `return was_active`
        (dropping the restored element) makes this fail with a TypeError on
        unpack -- confirmed via Edit revert.
        """
        import json

        from ml_bias import (
            deactivate_emos,
            reset_temperature_scale_for_emos,
            save_emos_params,
        )

        temp_path = isolated_temp_paths / "temperature_scale.json"
        temp_path.write_text(json.dumps({"global": {"T": 5.2, "n": 40}}))
        save_emos_params(1.0, 1.0, 1.0, 0.1, n=50)
        reset_temperature_scale_for_emos()
        assert json.loads(temp_path.read_text())["global"]["T"] == 1.0

        was_active, restored = deactivate_emos()

        assert was_active is True
        assert restored is True
        assert json.loads(temp_path.read_text())["global"] == {"T": 5.2, "n": 40}

    def test_load_emos_params_picks_up_change_without_process_restart(
        self, isolated_temp_paths
    ):
        """A long-running process (loop/watch) must see a save/deactivate
        made by a separate CLI invocation on its NEXT call, not only at
        first load -- the mtime check is what makes this possible instead
        of a cache that's permanent once populated."""
        import time

        from ml_bias import _load_emos_params, deactivate_emos, save_emos_params

        assert _load_emos_params() is None

        save_emos_params(1.0, 2.0, 3.0, 0.1, n=50)
        loaded = _load_emos_params()
        assert loaded is not None
        assert loaded[0] == pytest.approx(1.0)

        # Force a distinct mtime (some filesystems have 1-2s mtime resolution)
        time.sleep(1.1)
        save_emos_params(9.0, 9.0, 9.0, 0.9, n=99)
        reloaded = _load_emos_params()
        assert reloaded is not None
        assert reloaded[0] == pytest.approx(9.0), (
            "stale cache returned instead of re-reading the changed file"
        )

        deactivate_emos()
        assert _load_emos_params() is None, (
            "deactivation must be visible on the very next call in this "
            "same process, without a restart"
        )


class TestTrainAllTemperatureScalingSkipLogging:
    """Regression test: _fit_T's callers used to log a generic "T fit no
    better than T=1.0 — skipping" whenever _fit_T returned None, even when
    the real reason was hitting the T upper bound (directional bias) —
    misattributing the skip reason. The upper-bound warning itself also had
    no label, so a real cron run couldn't tell which pool (global/above/
    below/sameday/hourly) it was even about."""

    def _seed(
        self,
        tracker,
        ticker,
        city,
        market_date,
        our_prob,
        settled_yes,
        condition_type="above",
    ):
        analysis = {
            "condition": {"type": condition_type, "threshold": 70.0},
            "forecast_prob": our_prob,
            "market_prob": 0.5,
            "edge": 0.1,
            "method": "ensemble",
        }
        tracker.log_prediction(ticker, city, market_date, analysis)
        tracker.log_outcome(ticker, settled_yes)

    def test_directional_bias_warning_labels_global_and_condition(
        self, tmp_path, monkeypatch, caplog
    ):
        """24 rows all predicting 0.4 while the actual settle rate is 0.75 --
        unfixable by T-scaling (which can only push a prediction toward 0.5,
        never past it) -- so both the 'global' and 'above' fits are expected
        to hit the T upper bound."""
        from datetime import date, timedelta

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale.json")
        tracker.init_db()

        market_date = date.today() + timedelta(days=11)
        for i in range(24):
            self._seed(
                tracker,
                f"KXHIGHNY-26AUG{i:02d}-T75",
                "NYC",
                market_date,
                0.4,
                1 if i < 18 else 0,  # 18/24 = 0.75 actual settle rate
                "above",
            )

        with caplog.at_level("INFO", logger="ml_bias"):
            ml_bias.train_all_temperature_scaling(
                min_samples_global=1, min_samples_condition=1
            )

        warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        infos = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]

        for label in ("global", "above"):
            assert any(
                f"{label} T=" in m and "hit upper bound" in m for m in warnings
            ), f"expected a labeled upper-bound warning for '{label}', got: {warnings}"
            assert not any(f"{label} T fit no better than T=1.0" in m for m in infos), (
                f"'{label}' skip must not ALSO log the misattributed "
                f"'no better than T=1.0' message, got: {infos}"
            )

        # Neither fit produced a T (both hit the bound and returned None),
        # so nothing should have been written to disk.
        assert not (tmp_path / "temperature_scale.json").exists()

    def test_skips_emos_covered_keys_while_emos_is_active(self, tmp_path, monkeypatch):
        """While EMOS is live, global/above/below/between must not be
        refit -- overwriting the 1.0 reset placeholder with a real T would
        silently double-calibrate on top of EMOS's own fit within one
        retrain cycle (see reset_temperature_scale_for_emos's docstring)."""
        import json
        from datetime import date, timedelta

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale.json")
        monkeypatch.setattr(ml_bias, "_TEMP_CACHE", None)
        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", tmp_path / "emos_params.json")
        tracker.init_db()

        market_date = date.today() + timedelta(days=11)
        # Overconfident-but-correct-direction (0.9 predicted vs ~0.58 actual)
        # -- fittable by T-scaling (compresses toward 0.5), unlike the
        # directional-bias case above which hits the upper bound and
        # returns None regardless of whether EMOS is active.
        for i in range(24):
            self._seed(
                tracker,
                f"KXHIGHNY-26AUG{i:02d}-T75",
                "NYC",
                market_date,
                0.9,
                1 if i < 14 else 0,
                "above",
            )

        # Baseline: without EMOS active, the fit runs and writes normally.
        trained = ml_bias.train_all_temperature_scaling(
            min_samples_global=1, min_samples_condition=1
        )
        assert "global" in trained
        assert "above" in trained

        # Simulate an EMOS activation having reset these keys to the 1.0
        # placeholder, then retrain again with the same fittable data.
        (tmp_path / "temperature_scale.json").write_text(
            json.dumps(
                {
                    "global": {"T": 1.0, "n": 0, "reset_for_emos": True},
                    "above": {"T": 1.0, "n": 0, "reset_for_emos": True},
                }
            )
        )
        monkeypatch.setattr(ml_bias, "_TEMP_CACHE", None)
        (tmp_path / "emos_params.json").write_text(
            json.dumps({"a": 1.0, "b": 1.0, "c": 1.0, "d": 0.1})
        )

        trained_while_active = ml_bias.train_all_temperature_scaling(
            min_samples_global=1, min_samples_condition=1
        )

        assert "global" not in trained_while_active
        assert "above" not in trained_while_active
        result = json.loads((tmp_path / "temperature_scale.json").read_text())
        assert result["global"]["T"] == 1.0
        assert result["above"]["T"] == 1.0

    def test_directional_bias_warning_labels_sameday_and_hourly(
        self, tmp_path, monkeypatch, caplog
    ):
        """Same directional-bias shape as above, seeded into the sameday and
        hourly pools (both days_out=0, distinguished only by ticker prefix)
        -- these are two more independent _fit_T call sites that had the
        same unlabeled-warning / misattributed-skip bug."""
        from datetime import date

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale.json")
        tracker.init_db()

        def _seed_days_out_0(ticker, settled_yes):
            self._seed(tracker, ticker, "NYC", date.today(), 0.4, settled_yes, "above")
            with tracker._conn() as con:
                con.execute(
                    "UPDATE predictions SET days_out = 0 WHERE ticker = ?", (ticker,)
                )

        for i in range(24):
            settled = 1 if i < 18 else 0  # 18/24 = 0.75 actual settle rate
            _seed_days_out_0(f"KXHIGHNY-26AUG{i:02d}-T75", settled)
            _seed_days_out_0(f"KXTEMPNYCH-26JUL20{i:02d}-T75.99", settled)

        with caplog.at_level("INFO", logger="ml_bias"):
            ml_bias.train_all_temperature_scaling(
                min_samples_global=1, min_samples_condition=1
            )

        warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        infos = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]

        for label in ("sameday", "hourly"):
            assert any(
                f"{label} T=" in m and "hit upper bound" in m for m in warnings
            ), f"expected a labeled upper-bound warning for '{label}', got: {warnings}"
            assert not any(f"{label} T fit no better than T=1.0" in m for m in infos), (
                f"'{label}' skip must not ALSO log the misattributed "
                f"'no better than T=1.0' message, got: {infos}"
            )

    def test_sameday_fit_excludes_metar_lockout_rows(self, tmp_path, monkeypatch):
        """train_all_temperature_scaling's sameday T fit must not train on
        method='metar_lockout' rows -- analyze_trade's METAR-locked branch
        never calls apply_temperature_scaling (bypasses it entirely), so
        including them in the fit population was a train/serve mismatch:
        the fitted T would partly reflect data it's never actually applied
        to. Positive control: with metar_lockout rows removed, the fit must
        still run cleanly on the remaining (non-metar) sameday rows."""
        from datetime import date

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale.json")
        tracker.init_db()

        # 20 ordinary sameday (ensemble) rows: overconfident-but-correct-
        # direction (predict 0.9, ~65% actual hit rate) -- a real, FIXABLE
        # miscalibration T-scaling can compress toward. Using a flat 0.5
        # prediction here (an earlier version of this test did) is a trap:
        # logit(0.5)=0, so T-scaling can't move a 0.5 prediction at ANY T,
        # and _fit_T degenerates to "hit the upper bound" with no real
        # signal either way -- silently vacuous regardless of the exclusion.
        import random as _random

        _rng = _random.Random(5)
        for i in range(20):
            settled = 1 if _rng.random() < 0.65 else 0
            self._seed(
                tracker, f"KXHIGHNY-26JUL{i:02d}-T75", "NYC", date.today(), 0.9, settled
            )
            with tracker._conn() as con:
                con.execute(
                    "UPDATE predictions SET days_out = 0 WHERE ticker = ?",
                    (f"KXHIGHNY-26JUL{i:02d}-T75",),
                )

        # 20 severely-miscalibrated metar_lockout rows (predict 0.95, ALWAYS
        # actual=0 -- directional bias T-scaling can never fix) -- if pooled
        # in, _fit_T hits the upper bound and returns None for the whole
        # sameday key (verified directly: pooling these with the 20 rows
        # above makes trained=={} entirely). Must be invisible to this fit.
        for i in range(20):
            self._seed(
                tracker, f"KXHIGHNY-26JUL{i:02d}-LOCK", "NYC", date.today(), 0.95, 0
            )
            with tracker._conn() as con:
                con.execute(
                    "UPDATE predictions SET days_out = 0, method = 'metar_lockout' "
                    "WHERE ticker = ?",
                    (f"KXHIGHNY-26JUL{i:02d}-LOCK",),
                )

        with tracker._conn() as con:
            all_sameday = con.execute(
                "SELECT COUNT(*) FROM predictions WHERE days_out = 0"
            ).fetchone()[0]
            non_lockout_sameday = con.execute(
                "SELECT COUNT(*) FROM predictions WHERE days_out = 0 "
                "AND (method IS NULL OR method != 'metar_lockout')"
            ).fetchone()[0]
        assert all_sameday == 40
        # Positive control: confirms the 20 metar_lockout rows are really
        # present and reachable, so a passing fit below is the query
        # filtering them out, not them never having existed.
        assert non_lockout_sameday == 20

        trained = ml_bias.train_all_temperature_scaling(
            min_samples_global=1, min_samples_condition=1
        )

        # If the metar_lockout rows leaked into this fit, "sameday" would be
        # ABSENT from trained entirely (directional-bias detection discards
        # the whole fit) -- so this must be an unconditional membership
        # assertion, not a conditional check on the value, to actually catch
        # that failure mode.
        assert "sameday" in trained, (
            "sameday T fit is missing entirely -- metar_lockout rows likely "
            "leaked into the training population and triggered the "
            "directional-bias upper-bound discard"
        )
        assert trained["sameday"] < 8.0, (
            f"sameday T={trained['sameday']:.2f} hit the upper bound -- "
            f"metar_lockout rows likely leaked into the training population"
        )


class TestFitAndSaveMetarCalibration:
    """Direct unit tests for ml_bias.fit_and_save_metar_calibration() -- the
    single shared fit+persist+cache-invalidate implementation used by both
    `py main.py calibrate` and cron.py's weekly D5 auto-retrain block (added
    2026-08-16 so the two callers can't drift, mirroring calibration.py's
    calibrate_and_save() for seasonal/city blend weights)."""

    def _seed_rows(self, tracker, n=35, seed=17):
        import random
        from datetime import date, timedelta

        rng = random.Random(seed)
        for i in range(n):
            p = rng.uniform(0.75, 0.97)
            settled = 1 if rng.random() < 0.7 else 0
            analysis = {
                "condition": {"type": "above", "threshold": 70.0},
                "forecast_prob": p,
                "market_prob": 0.5,
                "edge": 0.1,
                "method": "metar_lockout",
            }
            ticker = f"KXHIGHNY-26JUL{i:03d}-FSMC"
            tracker.log_prediction(
                ticker, "NYC", date.today() - timedelta(days=i % 5), analysis
            )
            tracker.log_outcome(ticker, settled)
            with tracker._conn() as con:
                con.execute(
                    "UPDATE predictions SET days_out = 0 WHERE ticker = ?", (ticker,)
                )

    def test_writes_file_with_history_backup_and_invalidates_cache(
        self, tmp_path, monkeypatch
    ):
        import json

        import ml_bias
        import tracker
        import weather_markets as wm

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        cal_path = tmp_path / "metar_lockout_calibration.json"
        monkeypatch.setattr(ml_bias, "_METAR_CALIBRATION_PATH", cal_path)
        monkeypatch.setattr(wm, "_METAR_CAL", ("stale", "cache", "value"))
        monkeypatch.setattr(wm, "_METAR_CAL_MTIME", 12345.0)
        tracker.init_db()
        self._seed_rows(tracker, n=35)

        # Pre-seed an existing file so the write has something to back up.
        cal_path.write_text(json.dumps({"a": 0.0, "b": 0.0, "c": 0.0, "n": 0}))

        result = ml_bias.fit_and_save_metar_calibration()

        assert result is not None
        a, b, c = result
        assert a == b  # Platt-equivalent shape (see fit_metar_calibration docstring)

        assert cal_path.exists()
        data = json.loads(cal_path.read_text())
        assert data["a"] == a
        assert data["b"] == b
        assert data["c"] == c
        assert data["n"] == 35
        assert "fitted_at" in data

        # atomic_write_json_with_history must have backed up the pre-existing
        # file -- this is the fix for issue #8 from the risk review (no
        # history preservation on a weekly-unattended retrain).
        history_dir = tmp_path / ".history"
        assert history_dir.exists()
        backups = list(history_dir.glob("metar_lockout_calibration_*.json"))
        assert backups, "expected a .history/ backup of the pre-existing file"
        backed_up = json.loads(backups[0].read_text())
        assert backed_up == {"a": 0.0, "b": 0.0, "c": 0.0, "n": 0}

        # cache must be invalidated so a running loop/watch process reloads
        assert wm._METAR_CAL is None

    def test_autouse_fixture_isolates_write_from_production_path(
        self, tmp_path, monkeypatch
    ):
        """AUD-0058: proves tests/conftest.py's autouse
        isolate_metar_calibration_path fixture actually redirects
        ml_bias._METAR_CALIBRATION_PATH away from the real production file
        BY ITSELF -- deliberately does NOT monkeypatch
        ml_bias._METAR_CALIBRATION_PATH in this test (every other test in
        this class does, which would mask a broken/removed fixture). This
        is the mutation-test proof for that fixture: disabling it must make
        this test fail, not just rely on every test author remembering
        their own direct patch.

        Opus review (2026-08-22): the redirection is asserted BEFORE calling
        fit_and_save_metar_calibration(), not after -- if the autouse fixture
        is ever broken/removed, this guard must fail closed (test error, no
        write attempted) rather than proceed to actually write synthetic
        coefficients into the real production
        data/metar_lockout_calibration.json file, which is exactly the
        5d9b6c56 incident AUD-0058 exists to prevent. Asserting only after
        the write (the original version of this test) would have reproduced
        that incident instead of guarding against it, the moment the fixture
        ever regressed."""
        import ml_bias
        import paths
        import tracker
        import weather_markets as wm

        assert ml_bias._METAR_CALIBRATION_PATH != paths.METAR_CALIBRATION_PATH
        assert ml_bias._METAR_CALIBRATION_PATH.parent == tmp_path

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        monkeypatch.setattr(wm, "_METAR_CAL", None)
        tracker.init_db()
        self._seed_rows(tracker, n=35)

        result = ml_bias.fit_and_save_metar_calibration()

        assert result is not None
        assert ml_bias._METAR_CALIBRATION_PATH.exists()

    def test_returns_none_and_writes_nothing_below_floor(self, tmp_path, monkeypatch):
        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        cal_path = tmp_path / "metar_lockout_calibration.json"
        monkeypatch.setattr(ml_bias, "_METAR_CALIBRATION_PATH", cal_path)
        tracker.init_db()
        self._seed_rows(tracker, n=10)  # below the EPV floor (min(n_pos,n_neg)>=10)

        result = ml_bias.fit_and_save_metar_calibration()

        assert result is None
        assert not cal_path.exists()

    def test_warns_when_calibrated_ceiling_crosses_force_close_threshold(
        self, tmp_path, monkeypatch, caplog
    ):
        """AUD-0038: a future retrain whose fit pushes the calibrated output
        range past cron.py's >=0.80 force-close gate must log a WARNING
        (not fail silently). fit=(0.13, 0.13, 0.94) is a tight boundary
        case (independent-review-strengthened, replacing an earlier
        a=b=5.0 test that drove both ceilings to ~1.0 simultaneously and so
        couldn't isolate which one -- or the >=0.80 comparison itself --
        actually triggered the warning): it yields a YES-lock ceiling of
        ~0.8009 (just over the gate) while the NO-lock ceiling (~0.3803)
        stays well clear and neither direction trips the correction-cap
        bypass, so only the YES ceiling crossing >=0.80 can explain the
        warning firing."""
        import logging

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        cal_path = tmp_path / "metar_lockout_calibration.json"
        monkeypatch.setattr(ml_bias, "_METAR_CALIBRATION_PATH", cal_path)
        monkeypatch.setattr(tracker, "get_metar_lockout_calibration_data", lambda: [])
        monkeypatch.setattr(
            ml_bias, "fit_metar_calibration", lambda rows: (0.13, 0.13, 0.94)
        )

        with caplog.at_level(logging.WARNING, logger="ml_bias"):
            result = ml_bias.fit_and_save_metar_calibration()

        assert result == (0.13, 0.13, 0.94)
        assert any("force-close gate" in r.message for r in caplog.records), (
            "expected a WARNING naming the crossed force-close gate"
        )

    def test_no_warning_when_calibrated_ceiling_stays_just_below_threshold(
        self, tmp_path, monkeypatch, caplog
    ):
        """Tight positive control for the above: fit=(0.12, 0.12, 0.94)
        differs from the warning test's fit by only 0.01 in `a`/`b` and
        yields a YES-lock ceiling of ~0.7953 -- just under the gate, with
        the NO-lock ceiling and bypass logic unchanged from the warning
        case. A mutant that flips >= to >, or changes the 0.80 constant,
        would pass the previous test but is caught here (or vice versa)."""
        import logging

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        cal_path = tmp_path / "metar_lockout_calibration.json"
        monkeypatch.setattr(ml_bias, "_METAR_CALIBRATION_PATH", cal_path)
        monkeypatch.setattr(tracker, "get_metar_lockout_calibration_data", lambda: [])
        monkeypatch.setattr(
            ml_bias, "fit_metar_calibration", lambda rows: (0.12, 0.12, 0.94)
        )

        with caplog.at_level(logging.WARNING, logger="ml_bias"):
            result = ml_bias.fit_and_save_metar_calibration()

        assert result == (0.12, 0.12, 0.94)
        assert not any("force-close gate" in r.message for r in caplog.records)

    def test_no_warning_missed_production_coefficients_stay_dormant(
        self, tmp_path, monkeypatch, caplog
    ):
        """The real currently-fitted production coefficients (a=b=0.2262,
        c=0.4001, verified dormant by AUD-0035/AUD-0038) must not emit the
        warning -- a real-world sanity check distinct from the synthetic
        boundary cases above."""
        import logging

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        cal_path = tmp_path / "metar_lockout_calibration.json"
        monkeypatch.setattr(ml_bias, "_METAR_CALIBRATION_PATH", cal_path)
        monkeypatch.setattr(tracker, "get_metar_lockout_calibration_data", lambda: [])
        monkeypatch.setattr(
            ml_bias,
            "fit_metar_calibration",
            lambda rows: (0.22619580826228397, 0.22619580826228397, 0.4000758536385143),
        )

        with caplog.at_level(logging.WARNING, logger="ml_bias"):
            result = ml_bias.fit_and_save_metar_calibration()

        assert result is not None
        assert not any("force-close gate" in r.message for r in caplog.records)

    def test_warns_via_correction_cap_bypass_even_when_naive_ceiling_is_low(
        self, tmp_path, monkeypatch, caplog
    ):
        """Independent-review regression guard (F3): a naive ceiling model
        that ignores settlement_monitor._calibrate_metar_settlement_
        confidence's own correction-cap bypass (returns the RAW,
        uncalibrated confidence whenever the correction delta exceeds
        _METAR_CORRECTION_LIMIT=0.60) is INVERTED from the actual risk. A
        fit that pushes the calibrated value down hard produces a LOW
        naive ceiling (no warning) while being MORE likely to trip the
        0.60 cap and let the raw 0.97 confidence reach cron.py uncapped.
        fit=(0.1, 0.1, 1.0) calibrates to ~0.79/~0.34 (both under 0.80 --
        a naive model would stay silent), but its NO-direction correction
        delta is ~0.63 > 0.60, so the bypass fires and the EFFECTIVE
        NO-lock confidence cron.py actually receives is the raw 0.97 --
        the fix must warn on this fit."""
        import logging

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        cal_path = tmp_path / "metar_lockout_calibration.json"
        monkeypatch.setattr(ml_bias, "_METAR_CALIBRATION_PATH", cal_path)
        monkeypatch.setattr(tracker, "get_metar_lockout_calibration_data", lambda: [])
        monkeypatch.setattr(
            ml_bias, "fit_metar_calibration", lambda rows: (0.1, 0.1, 1.0)
        )

        with caplog.at_level(logging.WARNING, logger="ml_bias"):
            result = ml_bias.fit_and_save_metar_calibration()

        assert result == (0.1, 0.1, 1.0)
        assert any("force-close gate" in r.message for r in caplog.records), (
            "expected the correction-cap bypass to be caught by the ceiling model"
        )

    def test_threshold_literals_match_their_source_of_truth(self):
        """Independent-review finding (F5): fit_and_save_metar_calibration's
        _CRON_FORCE_CLOSE_THRESHOLD and _METAR_CORRECTION_LIMIT are
        hand-copied literals with no structural link to cron.py's actual
        force-close gate or settlement_monitor.py's actual correction cap
        -- only a comment ties them together. This doesn't make them
        structurally coupled, but it does catch drift: if either source
        value is ever changed without updating this literal, this test
        fails immediately instead of the ceiling model silently watching
        the wrong number."""
        import re
        from pathlib import Path

        # Deliberately resolved relative to THIS test file, not via paths.py
        # -- paths.py's project-root resolution always points at the main
        # clone regardless of which worktree is running, which would make
        # this test check the wrong checkout's source when run from a
        # worktree.
        repo_root = Path(__file__).resolve().parent.parent

        cron_src = (repo_root / "cron.py").read_text(encoding="utf-8")
        assert re.search(r"_sig_conf\s*>=\s*0\.80", cron_src) is not None, (
            "cron.py's settlement force-close threshold literal appears to have changed"
        )

        settlement_src = (repo_root / "settlement_monitor.py").read_text(
            encoding="utf-8"
        )
        # Anchored to the actual assignment (start-of-line, end-of-line) --
        # review finding: an unanchored version of this regex also matched
        # the docstring prose a few lines above the real assignment
        # ("Uses its own correction cap (_METAR_CORRECTION_LIMIT = 0.60)"),
        # which would keep passing even if the real assignment's value
        # drifted, since the docstring wasn't updated in lockstep.
        assert (
            re.search(r"^\s*_METAR_CORRECTION_LIMIT = 0\.60\s*$", settlement_src, re.M)
            is not None
        ), "settlement_monitor.py's correction-cap literal appears to have changed"

        # Round-3 review finding (F8): the checks above only catch the
        # SOURCE files drifting -- editing ml_bias.py's own local copies of
        # these literals (inside fit_and_save_metar_calibration itself)
        # would leave this test green, since neither prior assertion reads
        # ml_bias.py's own source. Check those too.
        ml_bias_src = (repo_root / "ml_bias.py").read_text(encoding="utf-8")
        assert (
            re.search(r"^\s*_CRON_FORCE_CLOSE_THRESHOLD = 0\.80\b", ml_bias_src, re.M)
            is not None
        ), "ml_bias.py's own _CRON_FORCE_CLOSE_THRESHOLD copy appears to have changed"
        assert (
            re.search(r"^\s*_METAR_CORRECTION_LIMIT = 0\.60\b", ml_bias_src, re.M)
            is not None
        ), "ml_bias.py's own _METAR_CORRECTION_LIMIT copy appears to have changed"


class TestCmdCalibrateMetarBlock:
    """cmd_calibrate()'s new METAR lock-in beta-calibration block, mirroring
    the existing Platt block's own wiring pattern (data_dir override,
    atomic_write_json, cache invalidation)."""

    def _seed_metar_rows(self, tracker, n=35, seed=9):
        import random
        from datetime import date, timedelta

        rng = random.Random(seed)
        for i in range(n):
            p = rng.uniform(0.75, 0.97)
            settled = 1 if rng.random() < 0.7 else 0
            analysis = {
                "condition": {"type": "above", "threshold": 70.0},
                "forecast_prob": p,
                "market_prob": 0.5,
                "edge": 0.1,
                "method": "metar_lockout",
            }
            ticker = f"KXHIGHNY-26JUL{i:03d}-LOCK"
            tracker.log_prediction(
                ticker, "NYC", date.today() - timedelta(days=i % 5), analysis
            )
            tracker.log_outcome(ticker, settled)
            with tracker._conn() as con:
                con.execute(
                    "UPDATE predictions SET days_out = 0 WHERE ticker = ?", (ticker,)
                )

    def test_writes_calibration_file_when_enough_data(self, tmp_path, monkeypatch):
        import json

        import main
        import ml_bias
        import tracker
        import weather_markets as wm

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        monkeypatch.setattr(main, "_CALIBRATE_DATA_DIR", tmp_path)
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale.json")
        monkeypatch.setattr(
            wm, "METAR_CALIBRATION_PATH", tmp_path / "metar_lockout_calibration.json"
        )
        # fit_and_save_metar_calibration() writes via ml_bias's own imported
        # copy of the path constant, not weather_markets's -- both must be
        # patched or the fit silently writes to real production data.
        monkeypatch.setattr(
            ml_bias,
            "_METAR_CALIBRATION_PATH",
            tmp_path / "metar_lockout_calibration.json",
        )
        # main.py's own imported copy is only used for the printed "Written
        # to:" message -- patch it too so test output isn't misleading.
        monkeypatch.setattr(
            main, "METAR_CALIBRATION_PATH", tmp_path / "metar_lockout_calibration.json"
        )
        monkeypatch.setattr(wm, "_METAR_CAL", ("stale", "cache", "value"))
        monkeypatch.setattr(wm, "_METAR_CAL_MTIME", 12345.0)
        tracker.init_db()

        self._seed_metar_rows(tracker, n=35)

        main.cmd_calibrate()

        cal_path = tmp_path / "metar_lockout_calibration.json"
        assert cal_path.exists()
        data = json.loads(cal_path.read_text())
        assert data["a"] > 0 and data["b"] > 0
        assert data["n"] == 35
        # cache must be invalidated so a running process picks up the fresh fit
        assert wm._METAR_CAL is None

    def test_no_file_written_below_floor(self, tmp_path, monkeypatch):
        import main
        import ml_bias
        import tracker
        import weather_markets as wm

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        monkeypatch.setattr(main, "_CALIBRATE_DATA_DIR", tmp_path)
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", tmp_path / "temperature_scale.json")
        monkeypatch.setattr(
            wm, "METAR_CALIBRATION_PATH", tmp_path / "metar_lockout_calibration.json"
        )
        monkeypatch.setattr(
            ml_bias,
            "_METAR_CALIBRATION_PATH",
            tmp_path / "metar_lockout_calibration.json",
        )
        monkeypatch.setattr(
            main, "METAR_CALIBRATION_PATH", tmp_path / "metar_lockout_calibration.json"
        )
        tracker.init_db()

        self._seed_metar_rows(
            tracker, n=10
        )  # below the EPV floor (min(n_pos,n_neg)>=10)

        main.cmd_calibrate()

        assert not (tmp_path / "metar_lockout_calibration.json").exists()


class _PicklableConstantRegressor:
    """Stand-in for GradientBoostingRegressor in the model-write test.

    A MagicMock cannot be used here: train_bias_model pickles the trained
    models, and pickling a MagicMock raises PicklingError before the write
    under test is ever reached. Predicts the training mean, which scores MSE
    0.0 on a constant-residual dataset and so clears the holdout gate.
    """

    def __init__(self, *args, **kwargs):
        self.mean = 0.0

    def fit(self, X, y):
        self.mean = sum(y) / len(y) if y else 0.0

    def predict(self, X):
        return [self.mean] * len(X)


class TestModelWriteRoutesThroughAtomicWriteBytes:
    """backlog L24249 (batch-62): train_bias_model's .pkl write must go
    through safe_io.atomic_write_bytes, not a bare Path.write_bytes().

    An earlier version of this coverage lived in tests/test_safe_io.py and was
    vacuous (opus-review-caught): it monkeypatched ml_bias._MODEL_PATH and then
    called safe_io.atomic_write_bytes DIRECTLY, never invoking any ml_bias code
    -- `--cov=ml_bias` showed the entire `if models:` save block unexecuted, so
    reverting the call site would have left it green. This drives the real
    function, mirroring tests/test_hmac_bias.py's
    test_write_hmac_uses_atomic_write.
    """

    def _seed(
        self, tracker, ticker, city, market_date, our_prob, settled_yes, condition_type
    ):
        analysis = {
            "condition": {"type": condition_type, "threshold": 7.0},
            "forecast_prob": our_prob,
            "market_prob": 0.5,
            "edge": 0.1,
            "method": "ensemble",
        }
        tracker.log_prediction(ticker, city, market_date, analysis)
        tracker.log_outcome(ticker, settled_yes)

    def test_train_bias_model_uses_atomic_write_bytes(self, tmp_path, monkeypatch):
        from datetime import timedelta
        from unittest.mock import patch

        import ml_bias
        import safe_io
        import tracker
        from utils import utc_today

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        monkeypatch.setattr(ml_bias, "_MODEL_PATH", tmp_path / "bias_models.pkl")
        monkeypatch.setattr(ml_bias, "_HMAC_PATH", tmp_path / "bias_models.pkl.hmac")
        tracker.init_db()

        # Constant residual by construction: our_prob 0.5 with settled_yes=1
        # gives y = actual - our_prob = +0.5 for every row, so a model that
        # predicts the training mean scores MSE 0.0 against a baseline of 0.25
        # and clears train_bias_model's holdout gate (_model_mse < _baseline_mse).
        for i in range(10):
            self._seed(
                tracker,
                f"KXHIGHNY-26JUN{i + 1:02d}-T75",
                "NYC",
                utc_today() + timedelta(days=i % 20 + 1),
                0.5,
                1,
                "above",
            )

        calls = []

        def _recording_atomic_write_bytes(data, path, **kwargs):
            calls.append({"data": data, "path": path, "kwargs": kwargs})
            path.write_bytes(data)

        monkeypatch.setattr(
            safe_io, "atomic_write_bytes", _recording_atomic_write_bytes
        )

        with patch(
            "sklearn.ensemble.GradientBoostingRegressor",
            _PicklableConstantRegressor,
        ):
            models = ml_bias.train_bias_model(min_samples=5)

        # Positive control: training really did reach the save block. Without
        # this, "atomic_write_bytes was called once" could pass vacuously if a
        # future change made the whole function return early.
        assert models, "training produced no models -- the save block never ran"

        assert len(calls) == 1, (
            f"expected exactly one atomic_write_bytes call, got {len(calls)}"
        )
        assert calls[0]["path"] == ml_bias._MODEL_PATH
        assert calls[0]["data"].startswith(b"\x80"), "payload is not a pickle"
        # emergency_copy=False is deliberate -- the copy would be a lone .pkl
        # with no matching .hmac, and restoring it silently disables bias
        # correction. See the call site's comment.
        assert calls[0]["kwargs"].get("emergency_copy") is False


# ─────────────────────────────────────────────────────────────────────────────
# batch-87: final-stage calibration fitted on the UNBIASED population
# (analysis_attempts), and the temperature-scale freeze it gates.
#
# Every test here relies on conftest's autouse isolate_analysis_calibration_path
# fixture having already redirected ml_bias._ANALYSIS_CAL_PATH at a per-test
# tmp file that does NOT exist -- that absent state is the "no fit" baseline
# several of these assert against.
# ─────────────────────────────────────────────────────────────────────────────


# batch-87: apply_analysis_calibration is scoped to the fit's own population
# (daily-temperature tickers, non-excluded condition types), so a test that
# wants to exercise the TRANSFORM has to pass a ticker inside that population
# -- otherwise it silently measures a scope guard instead. Named rather than
# inlined so the scope tests below can point at the same value and be
# obviously testing the guard, not a typo.
_IN_SCOPE_TICKER = "KXHIGHNY-26AUG26-T80"


def _apply(ml_bias, prob, days_out=1, ticker=_IN_SCOPE_TICKER, condition_type="above"):
    """apply_analysis_calibration with in-population defaults."""
    return ml_bias.apply_analysis_calibration(
        prob, days_out=days_out, ticker=ticker, condition_type=condition_type
    )


def _write_analysis_cal(ml_bias, entry: dict) -> None:
    """Write a multiday entry to the (already isolated) path and drop the cache."""
    import json

    ml_bias._ANALYSIS_CAL_PATH.write_text(json.dumps({"multiday": entry}))
    ml_bias._ANALYSIS_CAL_CACHE = None
    ml_bias._ANALYSIS_CAL_MTIME = None


class TestAnalysisCalibrationUncalibratedFlag:
    """The `_uncalibrated` sentinel must defeat an otherwise-valid entry.

    Referenced by seeds/README.md. This is the batch-79 failure mode
    (seeds/seasonal_weights.json's summer entry lost the flag and
    _blend_weights read uniform weights as a real fit) transplanted onto the
    new object.
    """

    def test_flagged_identity_entry_is_not_a_usable_fit(self):
        import ml_bias

        _write_analysis_cal(
            ml_bias, {"a": 1.0, "b": 0.0, "n": 0, "_uncalibrated": True}
        )
        assert (
            ml_bias._usable_analysis_cal_entry(
                ml_bias._load_analysis_calibration(), "multiday"
            )
            is None
        )
        assert ml_bias.analysis_calibration_is_active() is False

    def test_unflagged_identity_entry_is_a_usable_fit(self):
        """Positive control for the test above.

        Without this, that test would still pass if _usable_analysis_cal_entry
        rejected EVERY entry -- e.g. because the file never loaded at all, or
        because a later refactor broke the a/b lookup. The two entries differ
        by exactly one key, so the flag is provably the discriminator.
        """
        import ml_bias

        _write_analysis_cal(ml_bias, {"a": 1.0, "b": 0.0, "n": 0})
        assert ml_bias._usable_analysis_cal_entry(
            ml_bias._load_analysis_calibration(), "multiday"
        ) == (1.0, 0.0)
        assert ml_bias.analysis_calibration_is_active() is True

    def test_flagged_entry_declines_even_with_non_identity_coefficients(self):
        """A flagged entry declines regardless of what its coefficients say.

        Originally named for, and documented as, an ORDERING claim (that the
        flag is read before a/b). An opus reviewer showed that claim is
        semantically inert -- both orders return None for every possible
        input, so moving the check past the a/b validation left every test
        green. The real, testable property is the one now in the name: the
        flag alone is sufficient to decline, independent of the coefficients
        beside it.
        """
        import ml_bias

        _write_analysis_cal(ml_bias, {"a": 3.0, "b": -1.5, "_uncalibrated": True})
        assert (
            ml_bias._usable_analysis_cal_entry(
                ml_bias._load_analysis_calibration(), "multiday"
            )
            is None
        )
        # Positive control: the SAME coefficients unflagged are accepted, so
        # the rejection above is the flag's doing and not a bounds check on
        # a=3.0 / b=-1.5.
        _write_analysis_cal(ml_bias, {"a": 3.0, "b": -1.5})
        assert ml_bias._usable_analysis_cal_entry(
            ml_bias._load_analysis_calibration(), "multiday"
        ) == (3.0, -1.5)

    @pytest.mark.parametrize(
        "entry",
        [
            {"b": 0.0},
            {"a": 1.0},
            {"a": "1.0", "b": 0.0},
            {"a": True, "b": 0.0},
            {"a": float("nan"), "b": 0.0},
            {"a": float("inf"), "b": 0.0},
        ],
        ids=["no-a", "no-b", "a-is-str", "a-is-bool", "a-is-nan", "a-is-inf"],
    )
    def test_malformed_entries_decline(self, entry):
        import ml_bias

        _write_analysis_cal(ml_bias, entry)
        assert (
            ml_bias._usable_analysis_cal_entry(
                ml_bias._load_analysis_calibration(), "multiday"
            )
            is None
        )

    def test_non_dict_entry_and_non_dict_table_decline(self):
        import json

        import ml_bias

        ml_bias._ANALYSIS_CAL_PATH.write_text(json.dumps({"multiday": [1, 2]}))
        ml_bias._ANALYSIS_CAL_CACHE = None
        ml_bias._ANALYSIS_CAL_MTIME = None
        assert ml_bias.analysis_calibration_is_active() is False

        ml_bias._ANALYSIS_CAL_PATH.write_text(json.dumps([1, 2, 3]))
        ml_bias._ANALYSIS_CAL_CACHE = None
        ml_bias._ANALYSIS_CAL_MTIME = None
        assert ml_bias._load_analysis_calibration() is None

    def test_shipped_seed_carries_the_flag(self):
        """The seed itself, not a fixture -- seeds/README.md promises this."""
        import json

        seed = Path(__file__).parent.parent / "seeds" / "analysis_calibration.json"
        data = json.loads(seed.read_text())
        assert data["multiday"]["_uncalibrated"] is True
        # Positive control: the entry is otherwise complete, so the flag is
        # doing the work rather than the entry being empty or malformed.
        assert data["multiday"]["a"] == 1.0
        assert data["multiday"]["b"] == 0.0


class TestApplyAnalysisCalibration:
    def test_no_op_when_no_file_exists(self):
        import ml_bias

        assert not ml_bias._ANALYSIS_CAL_PATH.exists()  # the fixture's baseline
        assert _apply(ml_bias, 0.7, days_out=1) == 0.7

    def test_no_op_when_declined(self):
        import ml_bias

        _write_analysis_cal(ml_bias, {"a": 2.0, "b": 0.0, "_uncalibrated": True})
        assert _apply(ml_bias, 0.7, days_out=1) == 0.7
        # Positive control: the identical fit WITHOUT the flag does move it,
        # so the no-op above is the decline and not the horizon or the value.
        _write_analysis_cal(ml_bias, {"a": 2.0, "b": 0.0})
        assert _apply(ml_bias, 0.7, days_out=1) != 0.7

    @pytest.mark.parametrize("days_out", [0, None])
    def test_no_op_off_the_multiday_horizon(self, days_out):
        """days_out=0 and days_out=None must both no-op.

        Same-day was measured and deliberately excluded (t=-1.46 held-out, not
        significant); None reaches this from call paths that never resolved a
        horizon, and defaulting those to the multi-day fit would apply a
        correction measured on a population they are not in.
        """
        import ml_bias

        _write_analysis_cal(ml_bias, {"a": 2.0, "b": 0.0})
        assert _apply(ml_bias, 0.7, days_out=days_out) == 0.7
        # Positive control: the same fit and the same probability at d=1 DO
        # move, so the no-ops above are the horizon gate and not a dead fit.
        assert _apply(ml_bias, 0.7, days_out=1) != 0.7

    def test_matches_the_closed_form_at_a_equals_2(self):
        """sigmoid(2*logit(p)) == p^2 / (p^2 + (1-p)^2), derived independently
        of the implementation. p=0.7 -> 0.49 / (0.49 + 0.09) = 0.8448275862."""
        import ml_bias

        _write_analysis_cal(ml_bias, {"a": 2.0, "b": 0.0})
        got = _apply(ml_bias, 0.7, days_out=1)
        assert got == pytest.approx(0.49 / (0.49 + 0.09), abs=1e-9)
        assert got == pytest.approx(0.8448275862, abs=1e-9)

    def test_identity_fit_leaves_the_probability_alone(self):
        import ml_bias

        _write_analysis_cal(ml_bias, {"a": 1.0, "b": 0.0})
        for p in (0.05, 0.25, 0.5, 0.75, 0.95):
            assert _apply(ml_bias, p, days_out=1) == pytest.approx(p, abs=1e-9)

    def test_real_fit_sharpens_rather_than_compresses(self):
        """The measured 2026-08-26 fit (a=2.8613, b=-0.3384) must push AWAY
        from 0.5, which is the opposite of what the existing temperature scale
        (global T=4.601, a compression) does. If this ever reverses, the two
        stages are fighting rather than composing."""
        import ml_bias

        _write_analysis_cal(ml_bias, {"a": 2.8613, "b": -0.3384})
        assert _apply(ml_bias, 0.80, days_out=1) > 0.80
        assert _apply(ml_bias, 0.20, days_out=1) < 0.20

    def test_extreme_inputs_do_not_raise(self):
        """_logit self-clips to [1e-6, 1-1e-6] and _sigmoid is the stable
        branch-on-sign form, so 0.0/1.0 must return a finite probability
        rather than raising or producing inf."""
        import math

        import ml_bias

        _write_analysis_cal(ml_bias, {"a": 5.0, "b": 5.0})
        for p in (0.0, 1.0, 1e-12, 1 - 1e-12):
            got = _apply(ml_bias, p, days_out=1)
            assert math.isfinite(got)
            assert 0.0 <= got <= 1.0


class TestFitAnalysisCalibration:
    @staticmethod
    def _rows(n_pos, n_neg, seed=11):
        """Rows whose forecast_prob is informative but OVERLAPPING.

        The two ranges deliberately overlap on [0.30, 0.70]. An earlier
        version drew positives from [0.50, 0.80] and negatives from
        [0.20, 0.50], which is perfectly separable -- the Platt MLE then
        diverges (measured: A=414.4) and _fit_platt's own |A|<=5 guard
        rejects it, so every "this should fit" assertion failed for a reason
        that had nothing to do with what it was testing. Real settled data is
        never separable; a fixture that is will silently exercise only the
        blowup guard.
        """
        import random

        rng = random.Random(seed)
        rows = []
        for _ in range(n_pos):
            rows.append({"forecast_prob": rng.uniform(0.30, 0.95), "outcome": 1})
        for _ in range(n_neg):
            rows.append({"forecast_prob": rng.uniform(0.05, 0.70), "outcome": 0})
        return rows

    def test_declines_below_the_minority_floor(self):
        import ml_bias

        floor = ml_bias.ANALYSIS_CALIBRATION_MIN_MINORITY
        assert ml_bias.fit_analysis_calibration(self._rows(floor - 1, 200)) is None
        # Positive control: one more minority row and the SAME shape fits, so
        # the decline is the floor and not the data being unfittable.
        assert ml_bias.fit_analysis_calibration(self._rows(floor, 200)) is not None

    def test_floor_is_on_the_minority_class_not_the_row_count(self):
        """191 rows with only 19 positives must decline. This is the actual
        2026-08-26 shape (191 rows, 29 positives) minus ten positives -- the
        row count alone would look like plenty and would not be."""
        import ml_bias

        rows = self._rows(19, 172)
        assert len(rows) == 191
        assert ml_bias.fit_analysis_calibration(rows) is None

    def test_refuses_corrupted_labels(self):
        import ml_bias

        rows = self._rows(40, 200)
        rows[0]["outcome"] = 2
        assert ml_bias.fit_analysis_calibration(rows) is None
        # Positive control: the same rows with the label repaired do fit.
        rows[0]["outcome"] = 1
        assert ml_bias.fit_analysis_calibration(rows) is not None

    def test_skips_rows_with_missing_fields(self):
        import ml_bias

        rows = self._rows(40, 200)
        rows.append({"forecast_prob": None, "outcome": 1})
        rows.append({"forecast_prob": 0.6, "outcome": None})
        assert ml_bias.fit_analysis_calibration(rows) is not None

    def test_declines_when_fit_platt_rejects_the_coefficients(self, monkeypatch):
        """_fit_platt raises on a<=0 / |a|>5 / |b|>5; that must surface as a
        decline, not an exception escaping to the caller."""
        import ml_bias

        def _boom(xs, ys):
            raise ValueError("Platt fit produced invalid coefficients A=-1.0")

        monkeypatch.setattr(ml_bias, "_fit_platt", _boom)
        assert ml_bias.fit_analysis_calibration(self._rows(40, 200)) is None

    def test_recovers_a_known_platt_transform(self):
        """Generate labels from a KNOWN miscalibration and check the fit finds
        it. Outcomes are drawn at sigmoid(2*logit(p)) while the stored
        forecast_prob stays p, so a correct fitter recovers a ~= 2, b ~= 0."""
        import random

        import ml_bias

        rng = random.Random(5)
        rows = []
        for _ in range(4000):
            p = rng.uniform(0.05, 0.95)
            true_p = p**2 / (p**2 + (1 - p) ** 2)  # == sigmoid(2*logit(p))
            rows.append(
                {"forecast_prob": p, "outcome": 1 if rng.random() < true_p else 0}
            )
        fit = ml_bias.fit_analysis_calibration(rows)
        assert fit is not None
        a, b = fit
        assert a == pytest.approx(2.0, abs=0.25)
        assert b == pytest.approx(0.0, abs=0.25)


class TestFitAndSaveAnalysisCalibration:
    def _seed_attempts(self, tracker, n_pos=40, n_neg=200, days_out=1, seed=3):
        import random
        from datetime import date, timedelta

        rng = random.Random(seed)
        batch, outcomes = [], []
        for i in range(n_pos + n_neg):
            pos = i < n_pos
            # Overlapping ranges — see TestFitAnalysisCalibration._rows for
            # why a separable fixture only ever exercises the blowup guard.
            p = rng.uniform(0.30, 0.95) if pos else rng.uniform(0.05, 0.70)
            td = date(2026, 8, 1) + timedelta(days=i % 20)
            ticker = f"KXHIGHNY-26AUG{i:04d}-T70"
            batch.append(
                {
                    "ticker": ticker,
                    "city": "NYC",
                    "condition": "{'type': 'above'}",
                    "target_date": td,
                    "forecast_prob": p,
                    "market_prob": 0.5,
                    "days_out": days_out,
                    "was_traded": False,
                }
            )
            outcomes.append((ticker, td, 1 if pos else 0))
        tracker.batch_log_analysis_attempts(batch)
        for ticker, td, outcome in outcomes:
            tracker.settle_analysis_attempt(ticker, td, outcome)

    def test_writes_a_real_fit_and_invalidates_the_cache(self, tmp_path, monkeypatch):
        import json

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        tracker.init_db()
        self._seed_attempts(tracker)

        # Prime the cache with a stale value so the invalidation is observable.
        ml_bias._ANALYSIS_CAL_CACHE = {"multiday": {"a": 99.0, "b": 99.0}}
        ml_bias._ANALYSIS_CAL_MTIME = 12345.0

        fit = ml_bias.fit_and_save_analysis_calibration()

        assert fit is not None
        a, b = fit
        assert ml_bias._ANALYSIS_CAL_PATH.exists()
        entry = json.loads(ml_bias._ANALYSIS_CAL_PATH.read_text())["multiday"]
        assert entry["a"] == a
        assert entry["b"] == b
        assert entry["n"] == 240
        assert entry["n_pos"] == 40
        assert entry["source"] == "analysis_attempts"
        assert entry["days_out"] == ">=1"
        assert "_uncalibrated" not in entry
        assert "fitted_at" in entry
        # The stale cache must be gone, not returned.
        assert ml_bias._usable_analysis_cal_entry(
            ml_bias._load_analysis_calibration(), "multiday"
        ) == (a, b)
        assert ml_bias.analysis_calibration_is_active() is True

    def test_genuine_shortfall_writes_the_uncalibrated_placeholder(
        self, tmp_path, monkeypatch
    ):
        """A real data shortfall -- and no working fit being discarded -- does
        write the placeholder, which turns 9c into a no-op and lifts the
        temperature-scale freeze together.

        The prior entry here records n=53, NOT a larger n: with a larger one
        the shrink guard fires first and refuses to write at all, which is a
        different (and separately tested) behaviour. An earlier version of
        this test seeded n=191 against 53 rows and so was silently exercising
        the shrink guard instead of the decline path it names.
        """
        import json

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        tracker.init_db()
        _write_analysis_cal(ml_bias, {"a": 2.8613, "b": -0.3384, "n": 53})
        assert ml_bias.analysis_calibration_is_active() is True

        self._seed_attempts(tracker, n_pos=3, n_neg=50)  # below the floor
        assert ml_bias.fit_and_save_analysis_calibration() is None

        entry = json.loads(ml_bias._ANALYSIS_CAL_PATH.read_text())["multiday"]
        assert entry["_uncalibrated"] is True
        assert entry["a"] == 1.0
        assert entry["b"] == 0.0
        assert entry["n"] == 53
        assert entry["decline_reason"] == "insufficient_data"
        assert ml_bias.analysis_calibration_is_active() is False

    def test_drops_the_cache_it_just_warmed(self, tmp_path, monkeypatch):
        """The explicit cache-null is NOT redundant with the mtime check.

        fit_and_save reads the existing table (warming the cache with the
        PRE-write contents) and then writes microseconds later. On a
        filesystem with coarse mtime resolution both land in the same tick,
        _ANALYSIS_CAL_MTIME already equals the new file's mtime, and the
        loader short-circuits onto the stale table forever. Asserting the
        cache is None straight after the call pins the mechanism without
        needing to induce the race -- removing the two null assignments
        leaves the stale table sitting in _ANALYSIS_CAL_CACHE, which this
        catches and a mtime-dependent test does not (measured: it did not).
        """
        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        tracker.init_db()
        # A real prior fit on disk, then warm the cache from it.
        _write_analysis_cal(ml_bias, {"a": 9.9, "b": 9.9, "n": 1})
        assert ml_bias._load_analysis_calibration() is not None
        assert ml_bias._ANALYSIS_CAL_CACHE is not None  # positive control
        stale = ml_bias._ANALYSIS_CAL_CACHE

        self._seed_attempts(tracker)
        assert ml_bias.fit_and_save_analysis_calibration() is not None

        assert ml_bias._ANALYSIS_CAL_CACHE is None, (
            f"stale table survived the write: {ml_bias._ANALYSIS_CAL_CACHE}"
        )
        assert ml_bias._ANALYSIS_CAL_MTIME is None
        # And the next read genuinely returns the new coefficients, not the
        # ones the cache was warmed with.
        assert (
            ml_bias._load_analysis_calibration()["multiday"]["a"]
            != (stale["multiday"]["a"])
        )

    def test_preserves_other_horizon_keys(self, tmp_path, monkeypatch):
        """A multi-day-only retrain must not erase a key added later."""
        import json

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        tracker.init_db()
        ml_bias._ANALYSIS_CAL_PATH.write_text(
            json.dumps(
                {
                    "multiday": {"a": 1.0, "b": 0.0, "_uncalibrated": True},
                    "sameday": {"a": 1.2, "b": 0.3, "n": 77},
                }
            )
        )
        ml_bias._ANALYSIS_CAL_CACHE = None
        ml_bias._ANALYSIS_CAL_MTIME = None
        self._seed_attempts(tracker)

        assert ml_bias.fit_and_save_analysis_calibration() is not None
        data = json.loads(ml_bias._ANALYSIS_CAL_PATH.read_text())
        assert data["sameday"] == {"a": 1.2, "b": 0.3, "n": 77}

    def test_same_day_rows_are_not_in_the_population(self, tmp_path, monkeypatch):
        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        tracker.init_db()
        self._seed_attempts(tracker, days_out=0)
        assert tracker.get_analysis_calibration_data() == []
        assert ml_bias.fit_and_save_analysis_calibration() is None
        # Positive control: the SAME rows at days_out=1 do reach the fit, so
        # the emptiness above is the horizon filter and not the seeding
        # helper silently writing nothing.
        self._seed_attempts(tracker, days_out=1, seed=4)
        assert len(tracker.get_analysis_calibration_data()) == 240


class TestTemperatureScaleFreeze:
    """batch-87. train_all_temperature_scaling must stop moving the multi-day
    T keys once a real analysis calibration is stacked on top of them."""

    def _seed_multiday_predictions(self, tracker, n=60, seed=9):
        import random
        from datetime import date, timedelta

        rng = random.Random(seed)
        for i in range(n):
            ticker = f"KXHIGHNY-26JUL{i:04d}-TFRZ"
            analysis = {
                "condition": {"type": "above", "threshold": 70.0},
                "forecast_prob": rng.uniform(0.15, 0.85),
                "market_prob": 0.5,
                "edge": 0.2,
                "method": "ensemble",
            }
            tracker.log_prediction(
                ticker, "NYC", date(2026, 7, 1) + timedelta(days=i % 15), analysis
            )
            tracker.log_outcome(ticker, 1 if rng.random() < 0.35 else 0)
            with tracker._conn() as con:
                con.execute(
                    "UPDATE predictions SET days_out = 3 WHERE ticker = ?", (ticker,)
                )

    def _run(self, tmp_path, monkeypatch, cal_entry):
        import json

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        scale_path = tmp_path / "freeze_temperature_scale.json"
        scale_path.write_text(json.dumps({"global": {"T": 4.601, "n": 68}}))
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", scale_path)
        ml_bias._TEMP_CACHE = None
        ml_bias._TEMP_CACHE_MTIME = None
        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", tmp_path / "no_emos.json")
        tracker.init_db()
        self._seed_multiday_predictions(tracker)
        if cal_entry is not None:
            _write_analysis_cal(ml_bias, cal_entry)
        return ml_bias.train_all_temperature_scaling(), json.loads(
            scale_path.read_text()
        )

    def test_refits_when_no_analysis_calibration_exists(self, tmp_path, monkeypatch):
        """Positive control for the freeze tests below: with no stacked fit,
        the same data DOES produce a global/per-condition refit. Without this,
        a freeze test would pass just as happily if the seeded population were
        too small to fit at all."""
        trained, _ = self._run(tmp_path, monkeypatch, None)
        assert "global" in trained, trained

    def test_freezes_when_a_real_analysis_calibration_exists(
        self, tmp_path, monkeypatch
    ):
        trained, on_disk = self._run(
            tmp_path, monkeypatch, {"a": 2.8613, "b": -0.3384, "n": 191}
        )
        assert trained == {}
        # And the pre-existing T is left exactly as it was, not rewritten.
        assert on_disk["global"]["T"] == 4.601
        assert on_disk["global"]["n"] == 68

    def test_does_not_freeze_on_a_declined_analysis_calibration(
        self, tmp_path, monkeypatch
    ):
        """A declined fit means nothing is stacked, so the pre-batch-87
        behaviour is the correct fallback -- there is nothing to hold still."""
        trained, _ = self._run(
            tmp_path, monkeypatch, {"a": 1.0, "b": 0.0, "_uncalibrated": True}
        )
        assert "global" in trained, trained

    def _seed_sameday_predictions(self, tracker, n=60, seed=21):
        """Same-day rows the T fit will actually select AND be able to fit.

        Two traps, both hit while writing this:
          * days_out=0 with method='ensemble' and a KXHIGHNY-* ticker is
            required -- the sameday query excludes metar_lockout rows and the
            hourly KXTEMP*H prefixes.
          * labels must be drawn Bernoulli(forecast_prob), NOT at a flat base
            rate. With a flat rate the pool is directionally biased, _fit_T
            hits its 8.0 upper bound, returns None, and `trained` comes back
            empty -- so the test would pass while proving nothing.
        """
        import random
        from datetime import date, timedelta

        rng = random.Random(seed)
        for i in range(n):
            ticker = f"KXHIGHNY-26JUL{i:04d}-TSD"
            p = rng.uniform(0.15, 0.85)
            analysis = {
                "condition": {"type": "above", "threshold": 70.0},
                "forecast_prob": p,
                "market_prob": 0.5,
                "edge": 0.2,
                "method": "ensemble",
            }
            tracker.log_prediction(
                ticker, "NYC", date(2026, 7, 1) + timedelta(days=i % 15), analysis
            )
            tracker.log_outcome(ticker, 1 if rng.random() < p else 0)
            with tracker._conn() as con:
                con.execute(
                    "UPDATE predictions SET days_out = 0 WHERE ticker = ?", (ticker,)
                )

    def test_sameday_still_refits_while_multiday_is_frozen(self, tmp_path, monkeypatch):
        """The freeze is multi-day only -- BEHAVIOURALLY, not by name.

        Replaces a source-scanning assertion an opus reviewer showed was
        mutation-survivable: it asserted only that the identifier
        "_analysis_cal_active" did not appear in the same-day half of the
        function, so an implementation that froze same-day WITHOUT using that
        variable name passed. This asserts the two halves' actual outcomes in
        one run: multi-day held at its stored value, same-day refitted.
        """
        import json

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        scale_path = tmp_path / "freeze_temperature_scale.json"
        scale_path.write_text(json.dumps({"global": {"T": 4.601, "n": 68}}))
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", scale_path)
        ml_bias._TEMP_CACHE = None
        ml_bias._TEMP_CACHE_MTIME = None
        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", tmp_path / "no_emos.json")
        tracker.init_db()
        self._seed_multiday_predictions(tracker)
        self._seed_sameday_predictions(tracker)
        _write_analysis_cal(ml_bias, {"a": 2.8613, "b": -0.3384, "n": 191})

        trained = ml_bias.train_all_temperature_scaling()
        on_disk = json.loads(scale_path.read_text())

        # Same-day refit -- the positive control, and the half that would go
        # silently missing under the mutation this replaces.
        assert "sameday" in trained, trained
        assert on_disk["sameday"]["n"] == 60
        # Multi-day frozen at exactly what it held.
        assert "global" not in trained
        assert "above" not in trained
        assert on_disk["global"] == {"T": 4.601, "n": 68}

    def test_emos_and_analysis_cal_together_still_freeze_every_condition_key(
        self, tmp_path, monkeypatch
    ):
        """The combination that fell through BOTH guards.

        `if _analysis_cal_active and not _emos_active` meant that with EMOS
        active, a condition type outside EMOS_COVERED_CONDITION_KEYS matched
        neither branch and refit. Latent rather than live -- by_type holds
        only above/below today and both are EMOS-covered, which is exactly the
        shape where a test passes under either predicate -- so this seeds a
        condition type that is NOT covered.
        """
        import json

        import ml_bias
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        scale_path = tmp_path / "emos_combo_scale.json"
        scale_path.write_text(json.dumps({"global": {"T": 4.601, "n": 68}}))
        monkeypatch.setattr(ml_bias, "_TEMP_PATH", scale_path)
        ml_bias._TEMP_CACHE = None
        ml_bias._TEMP_CACHE_MTIME = None
        emos = tmp_path / "emos_params.json"
        emos.write_text("{}")
        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", emos)
        tracker.init_db()

        uncovered = "sunny_streak"
        assert uncovered not in ml_bias.EMOS_COVERED_CONDITION_KEYS
        assert uncovered not in tracker._ALWAYS_EXCLUDED_CONDITION_TYPES
        self._seed_multiday_predictions(tracker, n=60, seed=31)
        with tracker._conn() as con:
            con.execute(
                "UPDATE predictions SET condition_type = ? WHERE ticker LIKE ?",
                (uncovered, "KXHIGHNY-26JUL%-TFRZ"),
            )
        _write_analysis_cal(ml_bias, {"a": 2.8613, "b": -0.3384, "n": 191})

        trained = ml_bias.train_all_temperature_scaling()
        assert uncovered not in trained, (
            f"{uncovered} refit despite the analysis calibration being active "
            f"— it matched neither freeze branch"
        )
        assert json.loads(scale_path.read_text())["global"] == {"T": 4.601, "n": 68}


class TestApplyAnalysisCalibrationScope:
    """batch-87 opus review. The apply site's population must match the fit's.

    Every guard here mirrors a filter in
    tracker.get_analysis_calibration_data(); applying a correction to rows
    the fit never saw is the same error this batch exists to fix, pointed the
    other way.
    """

    def test_no_op_off_the_daily_temperature_families(self):
        """KXHOLIDAYTMAX/TMIN reach this function through analyze_trade's
        ordinary daily-temperature path but are NOT in the fit's
        KXHIGH*/KXLOWT* population. That family is shadow-only precisely so
        it can accumulate clean calibration data, so correcting it with a fit
        from a different family would land in the numbers its graduation
        decision gets made on."""
        import ml_bias

        _write_analysis_cal(ml_bias, {"a": 2.0, "b": 0.0})
        for tkr in (
            "KXHOLIDAYTMAX-260704100-NYC",
            "KXHOLIDAYTMIN-260704100-NYC",
            "KXRAINNYCM-26AUG-B2",
            "KXTEMPNYCH-26AUG26T14-T80",
        ):
            assert _apply(ml_bias, 0.7, ticker=tkr) == 0.7, tkr
        # Positive control: the same fit and probability on an in-population
        # ticker DOES move, so the no-ops above are the family guard.
        assert _apply(ml_bias, 0.7) != 0.7

    def test_no_op_when_the_ticker_is_missing(self):
        """Fail closed: without a ticker the family cannot be checked."""
        import ml_bias

        _write_analysis_cal(ml_bias, {"a": 2.0, "b": 0.0})
        assert _apply(ml_bias, 0.7, ticker=None) == 0.7
        assert _apply(ml_bias, 0.7, ticker="") == 0.7
        assert _apply(ml_bias, 0.7) != 0.7  # positive control

    def test_no_op_on_excluded_condition_types(self):
        """Mirrors _ALWAYS_EXCLUDED_CONDITION_TYPES, 'between' in particular
        -- structurally a different market whose probabilities cluster near
        0.75, and excluded from every sibling fit in the repo."""
        import ml_bias
        import tracker

        _write_analysis_cal(ml_bias, {"a": 2.0, "b": 0.0})
        # Derived from the registry, not hand-listed, so a type added there
        # is covered here automatically.
        assert "between" in tracker._ALWAYS_EXCLUDED_CONDITION_TYPES
        for ctype in tracker._ALWAYS_EXCLUDED_CONDITION_TYPES:
            assert _apply(ml_bias, 0.7, condition_type=ctype) == 0.7, ctype
        # Positive controls: an included type moves, and so does an unknown
        # one (unknown is deliberately NOT treated as excluded, matching the
        # fit side's own handling of an unparseable condition).
        assert _apply(ml_bias, 0.7, condition_type="above") != 0.7
        assert _apply(ml_bias, 0.7, condition_type=None) != 0.7

    def test_no_op_while_emos_is_active(self, tmp_path, monkeypatch):
        """EMOS replaces the ensemble probability with its own fitted Gaussian
        AND pins the multi-day T keys to 1.0 -- i.e. the base transform this
        fit was measured on top of is gone. Stacking on it over-sharpens an
        already-calibrated probability."""
        import ml_bias

        _write_analysis_cal(ml_bias, {"a": 2.0, "b": 0.0})
        assert _apply(ml_bias, 0.7) != 0.7  # positive control, EMOS absent

        emos = tmp_path / "emos_params.json"
        emos.write_text("{}")
        monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", emos)
        assert _apply(ml_bias, 0.7) == 0.7

    def test_magnitude_guard_skips_a_pathological_correction(self):
        """Section 9c was the only correction stage in analyze_trade with no
        magnitude cap; GBM/Platt use 0.30 and METAR 0.60. a=1.0/b=-5.0 is
        fully legal under _fit_platt and moves a probability by ~0.85."""
        import ml_bias

        _write_analysis_cal(ml_bias, {"a": 1.0, "b": -5.0})
        assert _apply(ml_bias, 0.9) == 0.9
        # Positive control: a fit inside the limit on the same probability is
        # applied, so the skip above is the magnitude guard and not the fit
        # being unusable or out of bounds.
        _write_analysis_cal(ml_bias, {"a": 1.0, "b": -0.5})
        assert _apply(ml_bias, 0.9) != 0.9

    def test_the_measured_production_fit_is_inside_the_limit(self):
        """The guard must not be silently skipping the real fit -- that is the
        failure METAR's own 0.30 limit produced (it skipped every NO-lock
        correction while applying every YES-lock one)."""
        import ml_bias

        _write_analysis_cal(ml_bias, {"a": 2.8613, "b": -0.3384})
        moved = 0
        for p in (0.05, 0.2, 0.35, 0.5, 0.65, 0.8, 0.95):
            out = _apply(ml_bias, p)
            assert abs(out - p) <= ml_bias._ANALYSIS_CORRECTION_LIMIT
            if abs(out - p) > 1e-9:
                moved += 1
        assert moved == 7, "the real fit should move every one of these"

    def test_non_finite_probability_is_returned_unchanged(self):
        """_logit clips rather than raises, so a NaN would otherwise become
        ~0.999999 -- silently converting 'unknown' into near-certainty on the
        pricing path."""
        import math

        import ml_bias

        _write_analysis_cal(ml_bias, {"a": 2.0, "b": 0.0})
        assert math.isnan(_apply(ml_bias, float("nan")))
        assert _apply(ml_bias, float("inf")) == float("inf")
        assert _apply(ml_bias, 0.7) != 0.7  # positive control

    def test_output_is_clamped_inside_the_function(self):
        """Clamped here, not only at the analyze_trade call site, so a second
        caller (backtest, dashboard) cannot receive an out-of-range value."""
        import ml_bias

        _write_analysis_cal(ml_bias, {"a": 4.0, "b": 0.0})
        assert _apply(ml_bias, 0.99) == pytest.approx(0.99, abs=1e-9)
        _write_analysis_cal(ml_bias, {"a": 4.0, "b": 0.0})
        assert _apply(ml_bias, 0.01) == pytest.approx(0.01, abs=1e-9)
        for p in (0.02, 0.5, 0.98):
            assert 0.01 <= _apply(ml_bias, p) <= 0.99


class TestAnalysisCalCoefficientBounds:
    """The READ path must enforce the same envelope _fit_platt does."""

    @pytest.mark.parametrize(
        "a,b",
        [(-2.5, 0.0), (0.0, 0.0), (5.5, 0.0), (2.0, 5.5), (2.0, -5.5)],
        ids=["a-negative", "a-zero", "a-too-big", "b-too-big", "b-too-negative"],
    )
    def test_out_of_bounds_coefficients_are_rejected(self, a, b):
        import ml_bias

        _write_analysis_cal(ml_bias, {"a": a, "b": b})
        assert ml_bias.analysis_calibration_is_active() is False
        assert _apply(ml_bias, 0.8) == 0.8

    def test_a_negative_would_have_inverted_every_multi_day_probability(self):
        """The concrete reason this guard exists. a=-2.5 maps a model
        probability of 0.80 to ~0.03 -- a direction inversion on every
        multi-day market, which flips rec_side on every one of them. The
        [0.01, 0.99] clamp does not help; an inverted value sits inside it."""
        import ml_bias

        # What the transform WOULD do if the bounds check were absent.
        raw = ml_bias._sigmoid(-2.5 * ml_bias._logit(0.80) + 0.0)
        assert raw < 0.05, raw
        assert 0.01 <= raw <= 0.99, "the clamp alone would not have caught it"
        # And what it actually does.
        _write_analysis_cal(ml_bias, {"a": -2.5, "b": 0.0})
        assert _apply(ml_bias, 0.80) == 0.80

    def test_in_bounds_coefficients_are_accepted(self):
        """Positive control for the parametrised rejections above."""
        import ml_bias

        for a, b in ((0.01, 0.0), (5.0, 5.0), (5.0, -5.0), (2.8613, -0.3384)):
            _write_analysis_cal(ml_bias, {"a": a, "b": b})
            assert ml_bias.analysis_calibration_is_active() is True, (a, b)


class TestAnalysisCalLoaderStates:
    """The loader's error branches, and the freeze's fail-closed policy."""

    def test_corrupt_file_is_a_no_op_for_apply_but_KEEPS_the_freeze(self):
        """A file that will not parse is not evidence that no calibration was
        fitted -- it is evidence we cannot see the one that was. Applying an
        unknown correction and holding a known base still are different
        risks, so these two deliberately diverge."""
        import ml_bias

        ml_bias._ANALYSIS_CAL_PATH.write_text("{not json")
        ml_bias._ANALYSIS_CAL_CACHE = None
        ml_bias._ANALYSIS_CAL_MTIME = None
        assert ml_bias._load_analysis_calibration() is None
        assert _apply(ml_bias, 0.7) == 0.7
        assert ml_bias.analysis_calibration_is_active() is True

    def test_absent_file_does_NOT_keep_the_freeze(self):
        """Positive control for the test above: absent and unreadable must not
        behave the same, or the fail-closed branch proves nothing."""
        import ml_bias

        assert not ml_bias._ANALYSIS_CAL_PATH.exists()
        assert ml_bias.analysis_calibration_is_active() is False

    def test_standing_bad_entry_warns_once_not_once_per_market(self, caplog):
        """apply_analysis_calibration runs on every market of every scan
        (~300), so an unconditional warning is ~300 identical lines per scan,
        indefinitely.

        Exercised through the COEFFICIENT-BOUNDS path, not the parse path.
        An earlier version of this test called _load_analysis_calibration in
        a loop -- but after the first call the mtime memo short-circuits
        before the warning is ever reached, so the dedup set was never
        touched and removing it left the test green (found by re-running the
        mutation). The bounds check has no such short-circuit: it runs on the
        CACHED table, once per market, which is exactly where the dedup earns
        its place.
        """
        import logging

        import ml_bias

        _write_analysis_cal(ml_bias, {"a": -2.5, "b": 0.0})
        ml_bias._ANALYSIS_CAL_WARNED.clear()
        with caplog.at_level(logging.WARNING, logger="ml_bias"):
            for _ in range(25):
                assert _apply(ml_bias, 0.7) == 0.7
        hits = [r for r in caplog.records if "out of bounds" in r.getMessage()]
        assert len(hits) == 1, f"warned {len(hits)} times across 25 markets"

    def test_a_rewritten_file_warns_again(self, caplog):
        """Positive control for the dedup: it must not silence a NEW problem.
        Without this, 'warns once' would be satisfied by 'never warns again'."""
        import logging
        import os

        import ml_bias

        _write_analysis_cal(ml_bias, {"a": -2.5, "b": 0.0})
        ml_bias._ANALYSIS_CAL_WARNED.clear()
        with caplog.at_level(logging.WARNING, logger="ml_bias"):
            _apply(ml_bias, 0.7)
            _apply(ml_bias, 0.7)
            # Rewrite with a DIFFERENT bad value and advance mtime, as a
            # separate process's retrain would.
            ml_bias._ANALYSIS_CAL_PATH.write_text('{"multiday": {"a": 9.9, "b": 0.0}}')
            st = ml_bias._ANALYSIS_CAL_PATH.stat()
            os.utime(ml_bias._ANALYSIS_CAL_PATH, (st.st_atime + 5, st.st_mtime + 5))
            _apply(ml_bias, 0.7)
        hits = [r for r in caplog.records if "out of bounds" in r.getMessage()]
        assert len(hits) == 2, (
            f"expected one warning per distinct bad file, got {len(hits)}"
        )

    def test_a_rewritten_file_is_re_read_via_mtime_alone(self, tmp_path):
        """The mtime path is the ONLY mechanism by which a long-running
        scanner picks up a file that `main.py calibrate` or cron rewrote in a
        different process. Every other test in this file drops the cache by
        hand, so without this the mtime compare is never exercised at all
        (opus review found the whole branch mutation-survivable)."""
        import json
        import os

        import ml_bias

        _write_analysis_cal(ml_bias, {"a": 2.0, "b": 0.0})
        assert ml_bias._load_analysis_calibration()["multiday"]["a"] == 2.0

        # Rewrite WITHOUT touching the cache, exactly as another process would.
        ml_bias._ANALYSIS_CAL_PATH.write_text(
            json.dumps({"multiday": {"a": 3.5, "b": 0.25}})
        )
        st = ml_bias._ANALYSIS_CAL_PATH.stat()
        os.utime(ml_bias._ANALYSIS_CAL_PATH, (st.st_atime + 5, st.st_mtime + 5))
        assert ml_bias._ANALYSIS_CAL_CACHE is not None  # still warm, on purpose

        assert ml_bias._load_analysis_calibration()["multiday"]["a"] == 3.5

    def test_stat_failure_returns_the_last_good_table(self, monkeypatch):
        """Transient stat failure keeps whatever was last read rather than
        inventing a state; self-healing on the next successful stat."""
        import json
        import os as _os

        import ml_bias

        _write_analysis_cal(ml_bias, {"a": 2.0, "b": 0.0})
        warm = ml_bias._load_analysis_calibration()
        assert warm is not None
        assert warm["multiday"]["a"] == 2.0

        # Rewrite the file with a DIFFERENT table and bump its mtime, so a
        # WORKING stat would see the change and return the new value. Without
        # this the test was vacuous: with the mtime unchanged, the loader's
        # `if _ANALYSIS_CAL_MTIME == mtime: return _ANALYSIS_CAL_CACHE` branch
        # returns the very same warm object the OSError branch returns, so
        # `is warm` held whether or not stat() ever raised. Mutation-tested --
        # making stat() succeed used to leave this test green.
        ml_bias._ANALYSIS_CAL_PATH.write_text(
            json.dumps({"multiday": {"a": 9.75, "b": 0.5}})
        )
        _st = ml_bias._ANALYSIS_CAL_PATH.stat()
        _os.utime(ml_bias._ANALYSIS_CAL_PATH, (_st.st_atime + 5, _st.st_mtime + 5))

        # Scoped to THIS path object, not to pathlib.Path as a class.
        #
        # The class-wide patch this replaces was version-dependent and failed
        # only on CI. _load_analysis_calibration calls _ANALYSIS_CAL_PATH
        # .exists() BEFORE the .stat() whose failure is under test, and on
        # Python 3.12 (what .github/workflows/ci.yml pins) Path.exists() is
        # implemented by calling self.stat() -- so the class patch fired
        # there first. An errno-less OSError is not in pathlib._ignore_error's
        # allowlist, so it propagated straight out of exists(), before the
        # loader's own try/except could ever see it. On 3.14 (this dev
        # machine) exists() is `os.path.exists(self)` and never touches
        # stat(), so the same test passed. Same 3.12-vs-3.14 split as the
        # Path.move test in tests/test_prod_data_guard.py.
        #
        # The intent was always "stat fails at the mtime check", never "stat
        # fails everywhere", so the narrower patch is also the more faithful
        # one -- and it is version-independent.
        real_path = ml_bias._ANALYSIS_CAL_PATH

        class _StatBoom:
            """Delegates everything to the real path except stat()."""

            def __getattr__(self, name):
                return getattr(real_path, name)

            def exists(self, *a, **kw):
                return True

            def stat(self, *a, **kw):
                raise OSError("transient")

        monkeypatch.setattr(ml_bias, "_ANALYSIS_CAL_PATH", _StatBoom())
        got = ml_bias._load_analysis_calibration()
        assert got is warm, "a failed stat must keep the last good table"
        assert got["multiday"]["a"] == 2.0, "returned the rewritten file, not the cache"

        # POSITIVE CONTROL: self-healing. Once stat works again the loader
        # must pick the rewritten table up -- which also proves the rewrite
        # above really landed, so the assertions above are about the OSError
        # branch rather than about a file that never changed.
        monkeypatch.setattr(ml_bias, "_ANALYSIS_CAL_PATH", real_path)
        healed = ml_bias._load_analysis_calibration()
        assert healed is not None
        assert healed["multiday"]["a"] == 9.75


class TestAnalysisCalDeclinePolicy:
    """batch-87 opus review. A decline is not one thing.

    Writing the `_uncalibrated` placeholder simultaneously turns section 9c
    into a no-op AND un-freezes the weekly multi-day T refit -- so which
    declines are allowed to write is a safety decision, not bookkeeping.
    """

    def _db(self, tmp_path, monkeypatch):
        import tracker

        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        tracker.init_db()
        return tracker

    def test_db_failure_writes_nothing_and_keeps_the_freeze(
        self, tmp_path, monkeypatch
    ):
        """This call is FIRST in cron's weekly D5 block, upstream of the T
        refit, the blend calibration, the weight push and the METAR fit -- and
        that block's `finally` touches its 6-day marker unconditionally. An
        escape here costs all four for another six days."""
        import ml_bias
        import tracker

        self._db(tmp_path, monkeypatch)
        _write_analysis_cal(ml_bias, {"a": 2.8613, "b": -0.3384, "n": 191})
        before = ml_bias._ANALYSIS_CAL_PATH.read_text()

        def _boom():
            raise RuntimeError("database is locked")

        monkeypatch.setattr(tracker, "get_analysis_calibration_data", _boom)

        assert ml_bias.fit_and_save_analysis_calibration() is None
        assert ml_bias.last_analysis_calibration_status() == "db_error"
        assert ml_bias._ANALYSIS_CAL_PATH.read_text() == before
        assert ml_bias.analysis_calibration_is_active() is True

    def test_shrink_guard_refuses_to_overwrite_a_working_fit(
        self, tmp_path, monkeypatch
    ):
        """Scored rows are never pruned (prune_old_analysis_attempts has
        `AND outcome IS NULL`), so the population is monotone by
        construction. An observed drop is a bug -- a series rename, a schema
        drift -- and must never be honoured by discarding a calibration."""
        import ml_bias

        self._db(tmp_path, monkeypatch)
        _write_analysis_cal(ml_bias, {"a": 2.8613, "b": -0.3384, "n": 191})
        before = ml_bias._ANALYSIS_CAL_PATH.read_text()

        # 0 rows in the DB, against a recorded n of 191.
        assert ml_bias.fit_and_save_analysis_calibration() is None
        assert ml_bias.last_analysis_calibration_status() == "shrink_guard"
        assert ml_bias._ANALYSIS_CAL_PATH.read_text() == before
        assert ml_bias.analysis_calibration_is_active() is True

    def test_shrink_guard_does_not_block_a_genuine_first_decline(
        self, tmp_path, monkeypatch
    ):
        """Positive control: with no prior REAL fit recorded, a genuine
        shortfall still writes the placeholder. Otherwise the guard above
        would be indistinguishable from 'never writes a decline'."""
        import json

        import ml_bias

        self._db(tmp_path, monkeypatch)
        _write_analysis_cal(ml_bias, {"a": 1.0, "b": 0.0, "_uncalibrated": True})

        assert ml_bias.fit_and_save_analysis_calibration() is None
        assert ml_bias.last_analysis_calibration_status() == "insufficient_data"
        entry = json.loads(ml_bias._ANALYSIS_CAL_PATH.read_text())["multiday"]
        assert entry["_uncalibrated"] is True
        assert entry["decline_reason"] == "insufficient_data"

    def test_corrupt_labels_are_reported_as_such_not_as_insufficient_data(
        self, tmp_path, monkeypatch
    ):
        """Two of the decline causes are integrity alarms. All three operator
        messages used to report every one of them as 'not enough data'."""
        import ml_bias
        import tracker

        self._db(tmp_path, monkeypatch)
        monkeypatch.setattr(
            tracker,
            "get_analysis_calibration_data",
            lambda: [{"forecast_prob": 0.5, "outcome": 7}] * 60,
        )
        assert ml_bias.fit_and_save_analysis_calibration() is None
        assert ml_bias.last_analysis_calibration_status() == "corrupt_labels"
        assert "REFUSED" in ml_bias.analysis_calibration_status_message()
        assert "not enough" not in ml_bias.analysis_calibration_status_message()

    def test_corrupt_FEATURE_is_caught_like_a_corrupt_label(
        self, tmp_path, monkeypatch
    ):
        """The label was validated and the feature was not. _logit clips, so a
        NaN forecast_prob would have been absorbed into the fit as ~0.999999."""
        import ml_bias
        import tracker

        self._db(tmp_path, monkeypatch)
        rows = [{"forecast_prob": 0.4, "outcome": i % 2} for i in range(120)]
        rows[0]["forecast_prob"] = float("nan")
        monkeypatch.setattr(tracker, "get_analysis_calibration_data", lambda: rows)
        assert ml_bias.fit_and_save_analysis_calibration() is None
        assert ml_bias.last_analysis_calibration_status() == "corrupt_labels"
        # Positive control: repair the one bad feature and it fits.
        rows[0]["forecast_prob"] = 0.4
        assert ml_bias.fit_and_save_analysis_calibration() is not None

    def test_fit_rejection_keeps_the_existing_calibration(self, tmp_path, monkeypatch):
        """Mirrors _fit_T's own convention -- return None, caller keeps the
        existing value. A coefficient just outside the envelope is not a
        reason to throw away a working fit AND un-freeze T."""
        import ml_bias
        import tracker

        self._db(tmp_path, monkeypatch)
        _write_analysis_cal(ml_bias, {"a": 2.8613, "b": -0.3384, "n": 60})
        before = ml_bias._ANALYSIS_CAL_PATH.read_text()
        monkeypatch.setattr(
            tracker,
            "get_analysis_calibration_data",
            lambda: [{"forecast_prob": 0.4, "outcome": i % 2} for i in range(120)],
        )

        def _reject(xs, ys):
            raise ValueError("Platt fit produced invalid coefficients A=5.3")

        monkeypatch.setattr(ml_bias, "_fit_platt", _reject)

        assert ml_bias.fit_and_save_analysis_calibration() is None
        assert ml_bias.last_analysis_calibration_status() == "fit_rejected"
        assert ml_bias._ANALYSIS_CAL_PATH.read_text() == before
        assert ml_bias.analysis_calibration_is_active() is True

    def test_every_status_has_a_distinct_operator_message(self):
        """The whole point of the map: no two causes may read the same."""
        import ml_bias

        msgs = ml_bias._ANALYSIS_CAL_STATUS_MESSAGES
        assert len(set(msgs.values())) == len(msgs)
        for status in (
            "ok",
            "unknown",
            "insufficient_data",
            "corrupt_labels",
            "fit_rejected",
            "db_error",
            "shrink_guard",
        ):
            assert status in msgs, status


class TestAnalysisCalMinorityFloor:
    def test_floor_is_pinned_from_both_sides(self):
        """The floor was only pinned from BELOW: raising it silently makes the
        fit decline, which disables the calibration AND un-freezes T -- one
        change, two regressions, neither visible."""
        import ml_bias

        assert ml_bias.ANALYSIS_CALIBRATION_MIN_MINORITY == 20
        assert (
            ml_bias.ANALYSIS_CALIBRATION_MIN_MINORITY
            == 2 * ml_bias.METAR_CALIBRATION_MIN_EPV_PER_PREDICTOR
        )

    def test_a_population_comfortably_above_the_floor_still_fits(self):
        """Kills the upward mutation: with the floor at 20, 25 minority rows
        must fit. At a mutated floor of 30 they would not."""
        import ml_bias

        rows = TestFitAnalysisCalibration._rows(25, 200)
        assert ml_bias.fit_analysis_calibration(rows) is not None


class TestAnalysisCalRetrainOrdering:
    """fit_and_save_analysis_calibration MUST run before
    train_all_temperature_scaling at every call site.

    The freeze is gated on the analysis fit's output, so if T is refit first
    the very first retrain after this landed moves T once more -- on the
    SELECTED population -- and only then freezes. Silent, and only visible in
    data/.history weeks later. There was no coverage of this at all.

    Asserted on the AST, bound to each enclosing function node rather than by
    a file-wide text scan, so an occurrence elsewhere in the module cannot
    satisfy it.
    """

    # cron's D5 block lives in _cmd_cron_body, not cmd_cron -- resolved by
    # walking the AST for the function that actually encloses the call, not
    # by guessing from the command name.
    CALL_SITES = [
        ("cron.py", "_cmd_cron_body"),
        ("main.py", "cmd_train_bias"),
        ("main.py", "cmd_calibrate"),
    ]

    @staticmethod
    def _called_names(node):
        """Every callable name invoked under `node`, in source order."""
        import ast

        out = []
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            f = sub.func
            name = getattr(f, "id", None) or getattr(f, "attr", None)
            if name:
                out.append((sub.lineno, name))
        return [n for _, n in sorted(out)]

    @staticmethod
    def _aliases(node, target):
        """Local aliases an `from ml_bias import X as Y` gave `target`."""
        import ast

        names = {target}
        for sub in ast.walk(node):
            if isinstance(sub, ast.ImportFrom) and sub.module == "ml_bias":
                for alias in sub.names:
                    if alias.name == target:
                        names.add(alias.asname or alias.name)
        return names

    @pytest.mark.parametrize(
        "filename,funcname",
        CALL_SITES,
        ids=[f"{f}:{n}" for f, n in CALL_SITES],
    )
    def test_analysis_fit_precedes_the_temperature_refit(self, filename, funcname):
        import ast

        src = (Path(__file__).parent.parent / filename).read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(
            (
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == funcname
            ),
            None,
        )
        assert fn is not None, f"{filename} has no {funcname}"

        fit_names = self._aliases(fn, "fit_and_save_analysis_calibration")
        ts_names = self._aliases(fn, "train_all_temperature_scaling")
        called = self._called_names(fn)

        fit_at = next((i for i, n in enumerate(called) if n in fit_names), None)
        ts_at = next((i for i, n in enumerate(called) if n in ts_names), None)
        # Positive control: BOTH are genuinely called here, so the ordering
        # assertion below is not comparing against a missing call.
        assert fit_at is not None, f"{filename}:{funcname} never fits the calibration"
        assert ts_at is not None, f"{filename}:{funcname} never refits T"
        assert fit_at < ts_at, (
            f"{filename}:{funcname} refits the temperature scale BEFORE fitting "
            f"the analysis calibration — the freeze would not yet be live, so "
            f"T moves once on the selected population first"
        )
