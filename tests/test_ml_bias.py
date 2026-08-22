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

        last_prefix = list(_KXTEMP_HOURLY_CITY)[-1]  # "KXTEMPDCH"

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
        tracker.log_prediction(
            multiday_ticker, "Washington", date(2026, 7, 21), analysis
        )
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
        assert get_emos_status() == {"active": False}

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

        was_active = deactivate_emos()

        assert was_active is True
        assert not (isolated_temp_paths / "emos_params.json").exists()

    def test_deactivate_emos_noop_when_already_inactive(self, isolated_temp_paths):
        from ml_bias import deactivate_emos

        was_active = deactivate_emos()

        assert was_active is False

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
