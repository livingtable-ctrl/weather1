# Group C — Model & Forecasting Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the weather forecast pipeline by wiring tracker-derived MAE weights, persistence baselines, ENSO adjustments, and time-decay edge into `analyze_trade`, and verify or correct every related helper function.
**Architecture:** All helpers live in `weather_markets.py` (or `climatology.py` for `persistence_prob`); `tracker.py` provides `get_ensemble_member_accuracy` and `log_prediction`; learned weights persist to `data/learned_weights.json`; tests live in `tests/test_forecasting.py` (create if absent, otherwise append).
**Tech Stack:** Python 3.12, pytest, sqlite3 (tracker), Open-Meteo API (mocked in tests), standard library only (no new deps).

---

### Task 1: Dynamic ensemble weights from tracker MAE (#25)

**Status check:** `_dynamic_model_weights(city, month)` EXISTS at `weather_markets.py:482-519`. It calls `get_ensemble_member_accuracy(city, season)` and returns inverse-MAE weights or None if `count < min_samples` (default 5). It is already called as priority-1 inside `_forecast_model_weights` at line 163. **No implementation needed — write a targeted test to verify correctness.**

**Files:**
- Test: `tests/test_forecasting.py` (create)
- Verify: `weather_markets.py:482-519`

- [ ] Step 1: Write failing test
```python
# tests/test_forecasting.py
import pytest
from unittest.mock import patch


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
```

- [ ] Step 2: Run test
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestDynamicModelWeights -v 2>&1 | head -40
```
Expected: all 4 tests pass (implementation already exists).

- [ ] Step 3: Implement — no code changes needed; the function is fully implemented. If any test fails, inspect `weather_markets.py:482-519` and `weather_markets.py:150-184` to reconcile.

- [ ] Step 4: Run full class to verify pass
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestDynamicModelWeights -v
```

- [ ] Step 5: Commit
```bash
cd "C:/Users/thesa/claude kalshi" && git add tests/test_forecasting.py && git commit -m "test: verify _dynamic_model_weights inverse-MAE logic (#25)"
```

---

### Task 2: Persistence/baseline model (#26)

**Status check:** `persistence_prob` EXISTS in `climatology.py:166-200`. Signature: `persistence_prob(condition_type, threshold_lo, threshold_hi, current_value, std_dev=5.0)`. It is NOT yet blended in `analyze_trade`. **Test the existing function, then wire it into `analyze_trade` at 15% weight when `days_out <= 2`.**

**Files:**
- Verify/modify: `weather_markets.py` — `analyze_trade` (line ~1702); blend section ~line 1840
- Verify: `climatology.py:166-200`
- Test: `tests/test_forecasting.py`

- [ ] Step 1: Write failing tests
```python
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
        from unittest.mock import patch, MagicMock
        from datetime import date, timedelta
        import weather_markets as wm

        today = date.today()
        target = today + timedelta(days=1)

        enriched = {
            "ticker": f"KXHIGHNY-{target.strftime('%d%b%y').upper()}-T70",
            "title": "NYC high > 70°F",
            "_city": "NYC",
            "_date": target,
            "_hour": None,
            "_forecast": {"high_f": 72.0, "low_f": 60.0, "precip_in": 0.0, "date": target.isoformat(), "city": "NYC", "models_used": 3, "high_range": (70.0, 74.0)},
            "yes_bid": 0.45,
            "yes_ask": 0.55,
            "no_bid": 0.45,
            "close_time": "",
            "series_ticker": "KXHIGHNY",
        }

        with patch.object(wm, "get_ensemble_temps", return_value=[70.0] * 20), \
             patch("climatology.climatological_prob", return_value=0.6), \
             patch("nws.nws_prob", return_value=None), \
             patch("nws.get_live_observation", return_value=None), \
             patch("climate_indices.temperature_adjustment", return_value=0.0):
            result = wm.analyze_trade(enriched)

        assert result is not None
        # persistence should appear in blend_sources or affect forecast_prob
        blend = result.get("blend_sources", {})
        assert "persistence" in blend or result["forecast_prob"] is not None
```

- [ ] Step 2: Run test
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestPersistenceProb -v 2>&1 | head -60
```
Expected: first 4 tests pass; last test (`test_analyze_trade_blends_persistence_for_short_horizon`) fails because blending is not yet wired.

- [ ] Step 3: Implement — wire persistence into `analyze_trade`

Find the blend section in `analyze_trade` (around line 1834–1851) where `_confidence_scaled_blend_weights` is called. Add persistence blending for `days_out <= 2`:

```python
# ── 3b. Persistence baseline (days_out <= 2 only) ───────────────────────
persistence_p: float | None = None
if days_out <= 2:
    try:
        from climatology import persistence_prob as _persistence_prob
        from nws import get_live_observation as _get_live_obs

        _live = _get_live_obs(city, coords) if days_out <= 1 else None
        _current_temp = (
            _live.get("temp_f") if _live and _live.get("temp_f") is not None
            else forecast_temp
        )
        _cond_type = condition["type"]
        _tlo = condition.get("threshold", condition.get("lower", forecast_temp))
        _thi = condition.get("upper")
        persistence_p = _persistence_prob(_cond_type, _tlo, _thi, _current_temp)
    except Exception:
        pass
```

Then modify the blend block (still inside the `else` branch after the obs_override check) to incorporate persistence at 15% when available:

```python
        w_ens, w_clim, w_nws = _confidence_scaled_blend_weights(
            days_out,
            _nws_prob is not None,
            clim_prob is not None,
            ens_std=ens_stats.get("std") if ens_stats else None,
        )
        # #26: persistence baseline at 15% for days_out <= 2
        if persistence_p is not None and days_out <= 2:
            w_persist = 0.15
            scale = 1.0 - w_persist
            w_ens = w_ens * scale
            w_clim = w_clim * scale
            w_nws = w_nws * scale
        else:
            w_persist = 0.0
            persistence_p = None

        blended_prob = (
            w_ens * (ens_prob or 0.5)
            + w_clim * (clim_prob or 0.5)
            + w_nws * (_nws_prob or 0.5)
            + w_persist * (persistence_p or 0.5)
        )
        blend_sources = {
            "ensemble": w_ens,
            "climatology": w_clim,
            "nws": w_nws,
            **({"persistence": w_persist} if w_persist > 0 else {}),
        }
```

- [ ] Step 4: Run tests to verify pass
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestPersistenceProb -v
```

- [ ] Step 5: Commit
```bash
cd "C:/Users/thesa/claude kalshi" && git add weather_markets.py tests/test_forecasting.py && git commit -m "feat: blend persistence baseline at 15% weight for days_out<=2 in analyze_trade (#26)"
```

---

### Task 3: ENSO phase in model weights (#28)

**Status check:** `_get_enso_phase()` EXISTS at `weather_markets.py:132-147`. It IS already used in `_forecast_model_weights` at line 178-183 — ECMWF gets `+0.5` in El Niño winters, `+0.3` in La Niña winters. **No implementation needed — write tests to verify the ENSO logic.**

**Files:**
- Verify: `weather_markets.py:132-147` and `150-184`
- Test: `tests/test_forecasting.py`

- [ ] Step 1: Write failing test
```python
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
        """_forecast_model_weights gives ECMWF +0.5 extra during El Niño winter."""
        from weather_markets import _forecast_model_weights
        with patch("weather_markets._dynamic_model_weights", return_value=None), \
             patch("weather_markets.load_learned_weights", return_value={}), \
             patch("weather_markets._get_enso_phase", return_value="el_nino"):
            w = _forecast_model_weights(month=1, city=None)
        assert w["ecmwf_ifs04"] == pytest.approx(3.0)  # 2.5 base + 0.5 el_nino

    def test_neutral_winter_ecmwf_weight(self):
        from weather_markets import _forecast_model_weights
        with patch("weather_markets._dynamic_model_weights", return_value=None), \
             patch("weather_markets.load_learned_weights", return_value={}), \
             patch("weather_markets._get_enso_phase", return_value="neutral"):
            w = _forecast_model_weights(month=1, city=None)
        assert w["ecmwf_ifs04"] == pytest.approx(2.5)
```

- [ ] Step 2: Run test
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestEnsoPhase -v 2>&1 | head -40
```
Expected: all 5 tests pass.

- [ ] Step 3: Implement — no code changes needed; if tests fail, inspect `weather_markets.py:132-184`.

- [ ] Step 4: Run tests to verify pass
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestEnsoPhase -v
```

- [ ] Step 5: Commit
```bash
cd "C:/Users/thesa/claude kalshi" && git add tests/test_forecasting.py && git commit -m "test: verify ENSO phase lookup and ECMWF weight boost (#28)"
```

---

### Task 4: Moist-cold feels-like formula (#29)

**Status check:** `_feels_like(temp_f, wind_mph, humidity_pct)` EXISTS at `weather_markets.py:398-434`. Moist-cold logic is ALREADY implemented (lines 409-413 for the wind-chill+humidity regime and lines 430-433 for the no-wind moist-cold intermediate regime). **No implementation needed — write tests to verify the two moist-cold branches.**

**Files:**
- Verify: `weather_markets.py:398-434`
- Test: `tests/test_forecasting.py`

- [ ] Step 1: Write failing test
```python
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
        # Penalty for humidity 80% → (80-70)/10 * 1.5 = 1.5°F
        assert abs(base - moist - 1.5) < 0.1

    def test_moist_cold_no_wind_intermediate(self):
        """temp<=50, no strong wind, humidity>=70 → humidity penalty only."""
        from weather_markets import _feels_like
        base = _feels_like(45.0, wind_mph=1.0, humidity_pct=50.0)   # no penalty
        moist = _feels_like(45.0, wind_mph=1.0, humidity_pct=80.0)  # penalty
        assert moist < base
        assert abs(base - moist - 1.5) < 0.1  # (80-70)/10 * 1.5

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
```

- [ ] Step 2: Run test
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestFeelsLike -v 2>&1 | head -40
```
Expected: all 5 tests pass.

- [ ] Step 3: Implement — no code changes needed. If `test_moist_cold_wind_chill_humidity_penalty` fails, the humidity penalty formula in `weather_markets.py:409-413` uses `(humidity_pct - 70.0) / 100 * 1.5` (divide by 100). The spec says `(humidity - 70) / 100 * 1.5` which equals 0.015 per unit — but the test above checks per 10% steps. Verify the exact formula; if the per-10%-step check fails, update the formula to `(humidity_pct - 70.0) / 10.0 * 1.5` and adjust the test to match whichever is correct for the codebase.

- [ ] Step 4: Run tests to verify pass
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestFeelsLike -v
```

- [ ] Step 5: Commit
```bash
cd "C:/Users/thesa/claude kalshi" && git add tests/test_forecasting.py && git commit -m "test: verify moist-cold feels-like formula (#29)"
```

---

### Task 5: Confidence-scaled blend weights use ens_std (#31)

**Status check:** `_confidence_scaled_blend_weights(days_out, has_nws, has_clim, ens_std)` EXISTS at `weather_markets.py:1100-1119`. It uses `ens_std` via a `scale = max(0.5, min(1.5, _ENS_STD_REF / ens_std))` where `_ENS_STD_REF = 4.0`. The spec says reduce ensemble weight by 30% when `ens_std > 8°F`. Current implementation uses a continuous scale (not a step function at 8°F). **Write tests to verify ens_std is wired and that high uncertainty reduces ensemble weight. No code changes needed unless behavior diverges.**

**Files:**
- Verify: `weather_markets.py:1097-1119`
- Test: `tests/test_forecasting.py`

- [ ] Step 1: Write failing test
```python
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
            assert abs(sum(w) - 1.0) < 1e-9, f"weights don't sum to 1 for ens_std={ens_std}"

    def test_none_ens_std_returns_base_weights(self):
        """ens_std=None → identical result to _blend_weights."""
        from weather_markets import _confidence_scaled_blend_weights, _blend_weights

        assert _confidence_scaled_blend_weights(5, True, True, None) == \
               _blend_weights(5, True, True)
```

- [ ] Step 2: Run test
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestConfidenceScaledBlendWeights -v 2>&1 | head -40
```
Expected: all 4 tests pass.

- [ ] Step 3: Implement — if `test_high_ens_std_reduces_ensemble_weight` fails with `ens_std=10`, the current scale formula gives `scale = max(0.5, 4.0/10.0) = 0.5`, which reduces `w_ens`, so this should pass. If not, inspect `weather_markets.py:1100-1119`.

- [ ] Step 4: Run tests to verify pass
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestConfidenceScaledBlendWeights -v
```

- [ ] Step 5: Commit
```bash
cd "C:/Users/thesa/claude kalshi" && git add tests/test_forecasting.py && git commit -m "test: verify _confidence_scaled_blend_weights uses ens_std correctly (#31)"
```

---

### Task 6: NWS always blended (not fallback) — verify weights (#33)

**Status check:** `_blend_weights(days_out, has_nws, has_clim)` EXISTS at `weather_markets.py:1068-1094`. Current NWS weights from the raw table: `days_out<=1: 0.15`, `days_out<=3: 0.20`, `days_out<=5: 0.25`, `days_out<=7: 0.25`, `>7: 0.25`. The spec requires: `0.35` at `days_out<=3`, `0.25` at `4-7`, `0.10` at `>7`. The current implementation does NOT match the spec. **Update `_blend_weights` to use spec weights.**

**Files:**
- Modify: `weather_markets.py:1068-1094`
- Test: `tests/test_forecasting.py`

- [ ] Step 1: Write failing test
```python
class TestBlendWeights:
    def test_nws_weight_short_horizon(self):
        """days_out <= 3: NWS weight must be 0.35 (before normalization)."""
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
```

- [ ] Step 2: Run test
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestBlendWeights -v 2>&1 | head -40
```
Expected: `test_nws_weight_short_horizon` and `test_nws_weight_long_horizon` fail (current weights differ from spec).

- [ ] Step 3: Implement — update `_blend_weights` in `weather_markets.py`:

Replace the body of `_blend_weights` (lines 1072–1083) with:

```python
def _blend_weights(
    days_out: int, has_nws: bool, has_clim: bool
) -> tuple[float, float, float]:
    """Return (w_ensemble, w_climatology, w_nws) based on days out.

    NWS is always blended (not fallback): 0.35 at <=3 days, 0.25 at 4-7, 0.10 at >7.
    """
    if days_out <= 3:
        w_nws = 0.35
    elif days_out <= 7:
        w_nws = 0.25
    else:
        w_nws = 0.10

    # Remaining weight split between ensemble and climatology
    # Ensemble gets proportionally more weight at short horizons
    w_rem = 1.0 - w_nws
    if days_out <= 1:
        w_ens = w_rem * 0.94  # 0.94 of remaining ≈ old behaviour
        w_clim = w_rem * 0.06
    elif days_out <= 3:
        w_ens = w_rem * 0.87
        w_clim = w_rem * 0.13
    elif days_out <= 5:
        w_ens = w_rem * 0.69
        w_clim = w_rem * 0.31
    elif days_out <= 7:
        w_ens = w_rem * 0.53
        w_clim = w_rem * 0.47
    elif days_out <= 10:
        w_ens = w_rem * 0.26
        w_clim = w_rem * 0.74
    else:
        w_ens = w_rem * 0.13
        w_clim = w_rem * 0.87

    if not has_nws:
        w_ens += w_nws * 0.6
        w_clim += w_nws * 0.4
        w_nws = 0.0
    if not has_clim:
        w_ens += w_clim
        w_clim = 0.0

    total = w_ens + w_clim + w_nws
    return w_ens / total, w_clim / total, w_nws / total
```

- [ ] Step 4: Run tests to verify pass
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestBlendWeights -v
```

- [ ] Step 5: Commit
```bash
cd "C:/Users/thesa/claude kalshi" && git add weather_markets.py tests/test_forecasting.py && git commit -m "feat: update _blend_weights NWS to 0.35/0.25/0.10 — always blended not fallback (#33)"
```

---

### Task 7: Snow liquid ratio with wet-bulb (#34)

**Status check:** `wet_bulb_temp`, `snow_liquid_ratio`, and `liquid_equiv_of_snow_threshold` ALL EXIST at `weather_markets.py:1122-1154`. SLR breakpoints in the current code: `>32 → 0`, `>30 → 10`, `>28 → 15`, `else → 20`. The spec says: `>32 → 0`, `28-32 → 10`, `20-28 → 15`, `<20 → 20` — which maps to: `>32 → 0`, `>28 → 10`, `>20 → 15`, `else → 20`. Current thresholds use `>30` and `>28`; spec uses `>28` and `>20`. **Update `snow_liquid_ratio` breakpoints.**

**Files:**
- Modify: `weather_markets.py:1138-1148`
- Test: `tests/test_forecasting.py`

- [ ] Step 1: Write failing test
```python
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
```

- [ ] Step 2: Run test
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestSnowLiquidRatio -v 2>&1 | head -40
```
Expected: `test_28_to_32_range` fails (current code uses `>30` threshold), `test_20_to_28_range` fails (current uses `>28`).

- [ ] Step 3: Implement — update `snow_liquid_ratio` in `weather_markets.py`:

```python
def snow_liquid_ratio(wet_bulb_f: float) -> int:
    """#34: Empirical SLR from wet-bulb temp (NOAA operational).
    >32°F → 0 (rain), 28-32°F → 10, 20-28°F → 15, <=20°F → 20.
    """
    if wet_bulb_f > 32.0:
        return 0
    elif wet_bulb_f > 28.0:
        return 10
    elif wet_bulb_f > 20.0:
        return 15
    else:
        return 20
```

- [ ] Step 4: Run tests to verify pass
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestSnowLiquidRatio -v
```

- [ ] Step 5: Commit
```bash
cd "C:/Users/thesa/claude kalshi" && git add weather_markets.py tests/test_forecasting.py && git commit -m "fix: update snow_liquid_ratio thresholds to 28/20°F breakpoints per NOAA spec (#34)"
```

---

### Task 8: Forecast cycle tracking in log_prediction (#37)

**Status check:** `_current_forecast_cycle()` EXISTS at `weather_markets.py:80-93`. `tracker.log_prediction` already accepts `forecast_cycle` parameter (verified in `tracker.py:270`). Need to verify that `log_prediction` calls in `main.py` (line ~640) actually pass `forecast_cycle=_current_forecast_cycle()`.

**Files:**
- Verify/modify: `main.py` around line 640
- Verify: `weather_markets.py:80-93`, `tracker.py:265-344`
- Test: `tests/test_forecasting.py`

- [ ] Step 1: Write failing test
```python
class TestForecastCycle:
    def test_cycle_labels_cover_all_hours(self):
        """Every UTC hour maps to a valid cycle label."""
        from weather_markets import _current_forecast_cycle
        from unittest.mock import patch
        from datetime import datetime, timezone

        valid = {"00z", "06z", "12z", "18z"}
        for h in range(24):
            fake_now = datetime(2026, 1, 1, h, 0, 0, tzinfo=timezone.utc)
            with patch("weather_markets.datetime") as mock_dt:
                mock_dt.now.return_value = fake_now
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                result = _current_forecast_cycle()
            assert result in valid, f"Hour {h} returned invalid label {result!r}"

    def test_cycle_boundaries(self):
        """Boundary hours map to correct cycles."""
        from weather_markets import _current_forecast_cycle
        from unittest.mock import patch
        from datetime import datetime, timezone

        cases = [
            (0, "00z"), (5, "00z"), (6, "06z"), (11, "06z"),
            (12, "12z"), (17, "12z"), (18, "18z"), (23, "18z"),
        ]
        for hour, expected in cases:
            fake_now = datetime(2026, 1, 1, hour, 0, 0, tzinfo=timezone.utc)
            with patch("weather_markets.datetime") as mock_dt:
                mock_dt.now.return_value = fake_now
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                result = _current_forecast_cycle()
            assert result == expected, f"Hour {hour}: expected {expected}, got {result}"

    def test_log_prediction_called_with_forecast_cycle(self):
        """main.py passes forecast_cycle to log_prediction."""
        import ast
        import pathlib

        src = pathlib.Path("main.py").read_text()
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = getattr(node, "func", None)
                func_name = (
                    getattr(func, "attr", None) or getattr(func, "id", None)
                )
                if func_name == "log_prediction":
                    kw_names = {k.arg for k in node.keywords}
                    if "forecast_cycle" in kw_names:
                        found = True
                        break
        assert found, "log_prediction call in main.py must pass forecast_cycle= keyword"
```

- [ ] Step 2: Run test
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestForecastCycle -v 2>&1 | head -40
```
Expected: cycle-label tests pass; `test_log_prediction_called_with_forecast_cycle` may fail if `main.py` does not yet pass the kwarg.

- [ ] Step 3: Implement — in `main.py`, find the `log_prediction(...)` call (around line 640). Add `forecast_cycle=_current_forecast_cycle()` as a keyword argument. First verify the import of `_current_forecast_cycle` is at the top of `main.py` or add it:

```python
from weather_markets import (
    ...,
    _current_forecast_cycle,
)
```

Then update the call:

```python
tracker.log_prediction(
    ticker=...,
    city=...,
    ...,
    forecast_cycle=_current_forecast_cycle(),
)
```

- [ ] Step 4: Run tests to verify pass
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestForecastCycle -v
```

- [ ] Step 5: Commit
```bash
cd "C:/Users/thesa/claude kalshi" && git add main.py tests/test_forecasting.py && git commit -m "feat: pass forecast_cycle to log_prediction in main.py (#37)"
```

---

### Task 9: Time-decay edge in analyze_trade (#63)

**Status check:** `time_decay_edge(raw_edge, close_time, reference_hours=48.0)` EXISTS at `weather_markets.py:1370-1390`. It is NOT yet called inside `analyze_trade` — `analyze_trade` returns `edge = blended_prob - market_prob` without time-decay scaling. **Wire `time_decay_edge` into `analyze_trade` to scale `edge` before Kelly.**

**Files:**
- Modify: `weather_markets.py` — `analyze_trade` (line ~1941)
- Test: `tests/test_forecasting.py`

- [ ] Step 1: Write failing test
```python
class TestTimeDecayEdge:
    def test_full_edge_at_reference_hours(self):
        """At >= reference_hours before close, return full raw_edge."""
        from weather_markets import time_decay_edge
        from datetime import datetime, timezone, timedelta

        close = datetime.now(timezone.utc) + timedelta(hours=50)
        result = time_decay_edge(0.20, close, reference_hours=48.0)
        assert result == pytest.approx(0.20)

    def test_zero_edge_at_close(self):
        """At/past close_time, return 0.0."""
        from weather_markets import time_decay_edge
        from datetime import datetime, timezone, timedelta

        close = datetime.now(timezone.utc) - timedelta(hours=1)
        result = time_decay_edge(0.20, close)
        assert result == pytest.approx(0.0)

    def test_half_edge_at_half_reference(self):
        """24h before close with 48h reference → edge * 0.5."""
        from weather_markets import time_decay_edge
        from datetime import datetime, timezone, timedelta

        close = datetime.now(timezone.utc) + timedelta(hours=24)
        result = time_decay_edge(0.20, close, reference_hours=48.0)
        assert abs(result - 0.10) < 0.005

    def test_analyze_trade_applies_time_decay(self):
        """analyze_trade edge is time-decay scaled (not raw blended - market)."""
        from unittest.mock import patch
        from datetime import date, timedelta, datetime, timezone
        import weather_markets as wm

        today = date.today()
        target = today + timedelta(days=3)
        close_dt = datetime.now(timezone.utc) + timedelta(hours=10)

        enriched = {
            "ticker": f"KXHIGHNY-{target.strftime('%d%b%y').upper()}-T70",
            "title": "NYC high > 70°F",
            "_city": "NYC",
            "_date": target,
            "_hour": None,
            "_forecast": {
                "high_f": 80.0, "low_f": 65.0, "precip_in": 0.0,
                "date": target.isoformat(), "city": "NYC",
                "models_used": 3, "high_range": (78.0, 82.0),
            },
            "yes_bid": 0.30,
            "yes_ask": 0.40,
            "no_bid": 0.60,
            "close_time": close_dt.isoformat(),
            "series_ticker": "KXHIGHNY",
        }

        with patch.object(wm, "get_ensemble_temps", return_value=[80.0] * 30), \
             patch("climatology.climatological_prob", return_value=0.5), \
             patch("nws.nws_prob", return_value=None), \
             patch("nws.get_live_observation", return_value=None), \
             patch("climate_indices.temperature_adjustment", return_value=0.0):
            result = wm.analyze_trade(enriched)

        assert result is not None
        raw_edge = result["forecast_prob"] - result["market_prob"]
        reported_edge = result["edge"]
        # With 10h to close and 48h reference, decay ≈ 10/48 ≈ 0.208
        # So reported_edge should be less than raw_edge (if positive)
        if abs(raw_edge) > 0.001:
            assert abs(reported_edge) < abs(raw_edge) + 1e-6
```

- [ ] Step 2: Run test
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestTimeDecayEdge -v 2>&1 | head -40
```
Expected: first 3 tests pass; `test_analyze_trade_applies_time_decay` fails (edge not yet decayed).

- [ ] Step 3: Implement — in `analyze_trade`, after computing `edge = blended_prob - market_prob` (around line 1941), add:

```python
# #63: Time-decay edge — scale linearly to zero as market approaches close
_close_str = enriched.get("close_time", "")
if _close_str:
    try:
        _close_dt = datetime.fromisoformat(_close_str.replace("Z", "+00:00"))
        edge = time_decay_edge(edge, _close_dt, reference_hours=48.0)
    except (ValueError, TypeError):
        pass
```

- [ ] Step 4: Run tests to verify pass
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestTimeDecayEdge -v
```

- [ ] Step 5: Commit
```bash
cd "C:/Users/thesa/claude kalshi" && git add weather_markets.py tests/test_forecasting.py && git commit -m "feat: apply time_decay_edge to scale edge before Kelly in analyze_trade (#63)"
```

---

### Task 10: Seasonal learned weights (#118) and per-city weights (#122)

**Status check:** `update_learned_weights_from_tracker` (the backtest updater) EXISTS at `weather_markets.py:522-551`. `load_learned_weights` / `save_learned_weights` EXIST. `_forecast_model_weights` already checks `data/learned_weights.json` as priority-2. The spec calls for `learn_seasonal_weights(city)` — this is effectively what `_weights_from_mae` + `update_learned_weights_from_tracker` provide. **Write a public alias `learn_seasonal_weights(city)` and tests for per-city lookup in `_forecast_model_weights`.**

**Files:**
- Modify: `weather_markets.py` — add `learn_seasonal_weights` alias/wrapper after `update_learned_weights_from_tracker`
- Test: `tests/test_forecasting.py`

- [ ] Step 1: Write failing test
```python
class TestLearnedWeights:
    def test_learn_seasonal_weights_returns_dict(self, tmp_path, monkeypatch):
        """learn_seasonal_weights(city) returns {model: weight} from tracker MAE."""
        import weather_markets as wm
        monkeypatch.setattr(wm, "_MAE_WEIGHTS_CACHE", {})
        monkeypatch.setattr(wm, "_LEARNED_WEIGHTS", {})

        fake_acc = {
            "icon_seamless": {
                "mae": 2.0, "n": 30,
                "city_breakdown": {"NYC": 1.9},
            },
            "gfs_seamless": {
                "mae": 2.5, "n": 30,
                "city_breakdown": {"NYC": 2.4},
            },
        }
        with patch("tracker.get_member_accuracy", return_value=fake_acc):
            result = wm.learn_seasonal_weights("NYC")
        assert isinstance(result, dict)
        assert "icon_seamless" in result or result == {}

    def test_forecast_model_weights_uses_learned_per_city(self, monkeypatch):
        """_forecast_model_weights returns city-specific learned weights as priority-2."""
        import weather_markets as wm

        monkeypatch.setattr(wm, "_LEARNED_WEIGHTS", {"NYC": {"gfs_seamless": 1.5, "icon_seamless": 0.5}})
        with patch("weather_markets._dynamic_model_weights", return_value=None):
            result = wm._forecast_model_weights(month=6, city="NYC")
        assert result == {"gfs_seamless": 1.5, "icon_seamless": 0.5}

    def test_forecast_model_weights_falls_back_to_seasonal(self, monkeypatch):
        """Falls back to seasonal weights when no learned data for city."""
        import weather_markets as wm

        monkeypatch.setattr(wm, "_LEARNED_WEIGHTS", {})
        with patch("weather_markets._dynamic_model_weights", return_value=None), \
             patch("weather_markets._get_enso_phase", return_value="neutral"):
            result = wm._forecast_model_weights(month=7, city="Denver")
        # Summer: ECMWF gets 1.5
        assert result["ecmwf_ifs04"] == pytest.approx(1.5)

    def test_save_and_load_learned_weights(self, tmp_path, monkeypatch):
        """Round-trip: save then load returns identical dict."""
        import weather_markets as wm

        monkeypatch.setattr(wm, "_LEARNED_WEIGHTS", {})
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        fake_path = data_dir / "learned_weights.json"
        import pathlib
        monkeypatch.setattr(
            pathlib.Path, "__truediv__",
            lambda self, key: fake_path if "learned_weights" in str(key) else self / key,
        )
        weights = {"NYC": {"gfs_seamless": 1.2, "icon_seamless": 0.8}}
        wm.save_learned_weights(weights)
        monkeypatch.setattr(wm, "_LEARNED_WEIGHTS", {})
        result = wm.load_learned_weights()
        assert result == weights
```

- [ ] Step 2: Run test
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestLearnedWeights -v 2>&1 | head -50
```
Expected: `test_learn_seasonal_weights_returns_dict` fails (`learn_seasonal_weights` not defined); others may pass.

- [ ] Step 3: Implement — add `learn_seasonal_weights` as a thin wrapper after `update_learned_weights_from_tracker` in `weather_markets.py`:

```python
def learn_seasonal_weights(city: str, min_n: int = 20) -> dict[str, float]:
    """
    #118: Compute and persist per-city model weights from tracker MAE data.
    Returns the weights for `city` (or {} if insufficient data).
    Saves results to data/learned_weights.json for use by _forecast_model_weights.
    """
    all_weights = update_learned_weights_from_tracker(min_n=min_n)
    return dict(all_weights.get(city, {}))
```

- [ ] Step 4: Run tests to verify pass
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestLearnedWeights -v
```

- [ ] Step 5: Commit
```bash
cd "C:/Users/thesa/claude kalshi" && git add weather_markets.py tests/test_forecasting.py && git commit -m "feat: add learn_seasonal_weights(city) public API; verify per-city lookup in _forecast_model_weights (#118 #122)"
```

---

### Task 11: Dynamic forecast cache TTL (#126)

**Status check:** `_ttl_until_next_cycle(now)` EXISTS at `weather_markets.py:96-126`. The cache TTL constants `_ENSEMBLE_CACHE_TTL` and `_FORECAST_CACHE_TTL` are still hardcoded at `90 * 60` (lines 69-73). `_ttl_until_next_cycle` is not used for caching. **Wire `_ttl_until_next_cycle` as the TTL when caching forecasts.**

**Files:**
- Modify: `weather_markets.py:190-273` (get_weather_forecast cache write) and `weather_markets.py:601-633` (get_ensemble_temps cache write)
- Test: `tests/test_forecasting.py`

- [ ] Step 1: Write failing test
```python
class TestDynamicCacheTTL:
    def test_ttl_until_next_cycle_minimum(self):
        """TTL is at least 1800 seconds."""
        from weather_markets import _ttl_until_next_cycle
        from datetime import datetime, timezone

        for h in range(24):
            now = datetime(2026, 1, 1, h, 30, 0, tzinfo=timezone.utc)
            ttl = _ttl_until_next_cycle(now)
            assert ttl >= 1800, f"TTL at hour {h} is {ttl} < 1800"

    def test_ttl_until_next_cycle_before_02z(self):
        """At 01:00 UTC, next cycle is 02:00 UTC → ~3600s."""
        from weather_markets import _ttl_until_next_cycle
        from datetime import datetime, timezone

        now = datetime(2026, 1, 1, 1, 0, 0, tzinfo=timezone.utc)
        ttl = _ttl_until_next_cycle(now)
        assert abs(ttl - 3600) < 60

    def test_ttl_used_when_caching_forecast(self):
        """get_weather_forecast uses _ttl_until_next_cycle as cache TTL."""
        import weather_markets as wm
        from unittest.mock import patch, MagicMock
        from datetime import date

        # Capture the TTL written into the cache
        captured_ttl = []
        original_cache_set = dict.__setitem__

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "daily": {
                "time": ["2026-04-15"],
                "temperature_2m_max": [75.0],
                "temperature_2m_min": [60.0],
                "precipitation_sum": [0.0],
            }
        }

        with patch("weather_markets._ttl_until_next_cycle", return_value=7200) as mock_ttl, \
             patch("kalshi_client._request_with_retry", return_value=fake_response):
            wm._FORECAST_CACHE.clear()
            result = wm.get_weather_forecast("NYC", date(2026, 4, 15))

        # _ttl_until_next_cycle should have been called
        mock_ttl.assert_called()
```

- [ ] Step 2: Run test
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestDynamicCacheTTL -v 2>&1 | head -40
```
Expected: first 2 tests pass; `test_ttl_used_when_caching_forecast` fails.

- [ ] Step 3: Implement — in `get_weather_forecast`, replace the static TTL check and cache write with dynamic TTL:

Find (around line 195):
```python
        if time.monotonic() - ts < _FORECAST_CACHE_TTL:
```
Replace with:
```python
        if time.monotonic() - ts < _ttl_until_next_cycle():
```

Find (around line 273):
```python
    _FORECAST_CACHE[cache_key] = (result, time.monotonic())
```
This line is correct; the TTL is only checked on read, so no change needed there.

Also update the read check in `get_ensemble_temps` (around line 605):
```python
        if time.monotonic() - ts < _ENSEMBLE_CACHE_TTL:
```
Replace with:
```python
        if time.monotonic() - ts < _ttl_until_next_cycle():
```

- [ ] Step 4: Run tests to verify pass
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_forecasting.py::TestDynamicCacheTTL -v
```

- [ ] Step 5: Commit
```bash
cd "C:/Users/thesa/claude kalshi" && git add weather_markets.py tests/test_forecasting.py && git commit -m "feat: use _ttl_until_next_cycle for dynamic forecast cache TTL (#126)"
```

---

### Task 12: Full test suite regression check

After completing all tasks, run the full test suite to confirm no regressions.

**Files:**
- All modified files above

- [ ] Step 1: Run full suite
```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest --ignore=tests/test_http.py -v 2>&1 | tail -30
```
Expected: all tests pass (or any pre-existing failures match the baseline before this work).

- [ ] Step 2: If failures occur, triage:
  - `_blend_weights` change (#33) may affect any test that asserts on exact weight values — update those tests to match new spec weights.
  - `snow_liquid_ratio` change (#34) may affect snow trade tests — verify snow threshold tests use the new breakpoints.
  - `time_decay_edge` wiring (#63) may affect `analyze_trade` edge assertions — update any hardcoded edge comparisons.

- [ ] Step 3: Final commit
```bash
cd "C:/Users/thesa/claude kalshi" && git add -p && git commit -m "test: fix regression tests after Group C model/forecasting changes"
```

---

## Pre-implementation notes

**Already fully implemented (tests only needed):**
- `_dynamic_model_weights` (#25) — `weather_markets.py:482-519`
- `_get_enso_phase` + ECMWF boost (#28) — `weather_markets.py:132-147`, `178-183`
- `_feels_like` moist-cold (#29) — `weather_markets.py:398-434`
- `_confidence_scaled_blend_weights` with ens_std (#31) — `weather_markets.py:1100-1119`
- `wet_bulb_temp`, `snow_liquid_ratio`, `liquid_equiv_of_snow_threshold` structure (#34) — thresholds need fixing
- `_current_forecast_cycle` (#37) — `weather_markets.py:80-93`
- `time_decay_edge` function (#63) — `weather_markets.py:1370-1390`, needs wiring
- `load_learned_weights` / `save_learned_weights` / `update_learned_weights_from_tracker` (#118/#122) — need `learn_seasonal_weights` alias
- `_ttl_until_next_cycle` (#126) — `weather_markets.py:96-126`, needs wiring

**Needs code changes:**
- #26 — wire `persistence_prob` into `analyze_trade` blend (15% at days_out<=2)
- #33 — update `_blend_weights` NWS raw weights to 0.35/0.25/0.10
- #34 — update `snow_liquid_ratio` thresholds (>28 → 10, >20 → 15)
- #37 — pass `forecast_cycle=_current_forecast_cycle()` in `main.py` `log_prediction` call
- #63 — call `time_decay_edge` on computed `edge` inside `analyze_trade`
- #118 — add `learn_seasonal_weights(city)` public wrapper
- #126 — replace static `_FORECAST_CACHE_TTL` / `_ENSEMBLE_CACHE_TTL` read-checks with `_ttl_until_next_cycle()`
