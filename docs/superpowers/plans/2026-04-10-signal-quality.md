# Signal Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stratify bias correction, edge confidence, ensemble weighting, and Kelly sizing by condition type and forecast recency to improve signal accuracy on precip/snow markets.

**Architecture:** Four targeted changes across `tracker.py` and `weather_markets.py` — no schema changes, no new files except a test file. Each change degrades gracefully to current behavior when data is insufficient.

**Tech Stack:** Python 3.11, SQLite (via tracker.py), pytest

---

## File Structure

- **Modify:** `tracker.py` — `get_member_accuracy()` gets `days_back=60` date filter
- **Modify:** `weather_markets.py` — `_CONDITION_CONFIDENCE` constant, `edge_confidence()` updated, `_weights_from_mae()` passes `days_back`, `analyze_trade()` passes `condition_type` to bias + Kelly
- **Create:** `tests/test_signal_quality.py` — 6 new tests

---

## Task 1: `get_member_accuracy(days_back=60)` in tracker.py

**Files:**
- Modify: `tracker.py` (lines 958–1004, `get_member_accuracy` function)
- Test: `tests/test_signal_quality.py` (create new file)

- [ ] **Step 1: Create `tests/test_signal_quality.py` with the days_back test**

```python
"""Tests for Group 2 signal quality improvements."""
import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import tracker


class TestGetMemberAccuracyDaysBack:
    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tracker.DB_PATH = Path(self._tmp.name)
        tracker._initialized = False

    def teardown_method(self):
        import gc
        gc.collect()
        tracker._initialized = False
        self._tmp.close()
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_get_member_accuracy_respects_days_back(self):
        """Old scores (90 days ago) are excluded; recent scores (10 days ago) are included."""
        tracker.init_db()
        now = datetime.now(UTC)
        old_ts = (now - timedelta(days=90)).isoformat()
        recent_ts = (now - timedelta(days=10)).isoformat()

        with tracker._conn() as con:
            # Old score — model_a, bad MAE
            con.execute(
                "INSERT INTO ensemble_member_scores (city, model, predicted_temp, actual_temp, target_date, logged_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("NYC", "model_a", 70.0, 80.0, "2025-01-01", old_ts),
            )
            # Recent score — model_a, good MAE
            con.execute(
                "INSERT INTO ensemble_member_scores (city, model, predicted_temp, actual_temp, target_date, logged_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("NYC", "model_a", 71.0, 72.0, "2025-01-02", recent_ts),
            )

        result = tracker.get_member_accuracy(days_back=60)
        assert "model_a" in result
        # Only the recent score (MAE=1.0) should be included, not the old one (MAE=10.0)
        assert result["model_a"]["mae"] == pytest.approx(1.0)
        assert result["model_a"]["n"] == 1
```

- [ ] **Step 2: Run test to confirm it FAILS**

```bash
pytest tests/test_signal_quality.py::TestGetMemberAccuracyDaysBack -v
```

Expected: `TypeError: get_member_accuracy() got an unexpected keyword argument 'days_back'`

- [ ] **Step 3: Update `get_member_accuracy` in `tracker.py`**

Replace the current function (lines 958–1004) with:

```python
def get_member_accuracy(days_back: int = 60) -> dict:
    """
    Return per-model accuracy stats filtered to recent predictions.

    days_back=60 captures ~one season transition while giving each model
    enough observations (daily scoring ≈ 60 data points per city per model).
    Returns {model: {mae: float, n: int, city_breakdown: {city: mae}}}
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT model, city, predicted_temp, actual_temp
            FROM ensemble_member_scores
            WHERE predicted_temp IS NOT NULL
              AND actual_temp IS NOT NULL
              AND logged_at >= datetime('now', ? || ' days')
            """,
            (f"-{days_back}",),
        ).fetchall()

    if not rows:
        return {}

    by_model: dict[str, list[tuple[str, float, float]]] = {}
    for r in rows:
        by_model.setdefault(r["model"], []).append(
            (r["city"], r["predicted_temp"], r["actual_temp"])
        )

    result: dict = {}
    for model, entries in by_model.items():
        errors = [abs(p - a) for _, p, a in entries]
        mae = sum(errors) / len(errors)
        city_errs: dict[str, list[float]] = {}
        for city, p, a in entries:
            city_errs.setdefault(city, []).append(abs(p - a))
        city_mae = {c: sum(v) / len(v) for c, v in city_errs.items()}
        result[model] = {
            "mae": round(mae, 4),
            "n": len(entries),
            "city_breakdown": {c: round(v, 4) for c, v in city_mae.items()},
        }
    return result
```

- [ ] **Step 4: Run test to confirm it PASSES**

```bash
pytest tests/test_signal_quality.py::TestGetMemberAccuracyDaysBack -v
```

Expected: 1 passed.

- [ ] **Step 5: Run full suite for regressions**

```bash
pytest --tb=short -q 2>&1 | tail -10
```

Expected: same pass/fail counts as before (480 passed, 13 pre-existing failures in test_paper.py).

- [ ] **Step 6: Commit**

```bash
git add tracker.py tests/test_signal_quality.py
git commit -m "feat: add days_back=60 filter to get_member_accuracy (#25)"
```

---

## Task 2: `_CONDITION_CONFIDENCE` + `edge_confidence(condition_type)` in weather_markets.py

**Files:**
- Modify: `weather_markets.py` (line 1449, `edge_confidence` function; add constant near module level)
- Test: `tests/test_signal_quality.py`

- [ ] **Step 1: Add 3 tests to `tests/test_signal_quality.py`**

Read the file, then append this class:

```python
class TestEdgeConfidenceConditionType:
    def test_precip_snow_lower_than_temp(self):
        """Same horizon, snow produces lower confidence than temperature."""
        from weather_markets import edge_confidence
        snow = edge_confidence(5, condition_type="precip_snow")
        temp = edge_confidence(5, condition_type="above")
        assert snow < temp

    def test_condition_compounds_horizon(self):
        """days_out=10, precip_snow: horizon≈0.7143, × 0.80 ≈ 0.5714."""
        from weather_markets import edge_confidence
        result = edge_confidence(10, condition_type="precip_snow")
        # horizon = 0.80 - (10-7)/7.0 * 0.20 = 0.80 - 0.08571 ≈ 0.7143
        # × 0.80 ≈ 0.5714
        assert result == pytest.approx(0.5714, abs=0.001)

    def test_unknown_condition_defaults_to_one(self):
        """Unknown condition_type uses multiplier of 1.0 — no change."""
        from weather_markets import edge_confidence
        without = edge_confidence(5)
        with_unknown = edge_confidence(5, condition_type="unknown_type")
        assert without == pytest.approx(with_unknown)
```

- [ ] **Step 2: Run tests to confirm they FAIL**

```bash
pytest tests/test_signal_quality.py::TestEdgeConfidenceConditionType -v
```

Expected: `TypeError: edge_confidence() got an unexpected keyword argument 'condition_type'`

- [ ] **Step 3: Add `_CONDITION_CONFIDENCE` constant to `weather_markets.py`**

Find a suitable location near the top of `weather_markets.py` where other module-level constants live (search for `MIN_EDGE` or `KALSHI_FEE_RATE` as landmarks). Add:

```python
# Per-condition-type confidence multiplier applied on top of horizon discount (#14/#39).
# Precipitation forecasts have higher irreducible uncertainty; snow requires two
# thresholds (precip AND temperature), making it the hardest to forecast.
_CONDITION_CONFIDENCE: dict[str, float] = {
    "above": 1.00,
    "below": 1.00,
    "between": 1.00,
    "precip_any": 0.90,
    "precip_above": 0.85,
    "precip_snow": 0.80,
}
```

- [ ] **Step 4: Update `edge_confidence` in `weather_markets.py`**

Replace the function at line 1449 with:

```python
def edge_confidence(days_out: int, condition_type: str | None = None) -> float:
    """Horizon + condition discount factor for edge signal (#63/#14).

    Combines the existing piecewise horizon discount with a per-condition
    multiplier from _CONDITION_CONFIDENCE. Precipitation and snow markets are
    inherently harder to forecast, so their effective edge is discounted further.

    Far-out markets are noisier; floor of 0.60 (horizon) ensures strong
    far-out edges still pass MIN_EDGE even without condition discount.

    Piecewise linear horizon:
      days_out 0–2  : 1.00
      days_out 3–7  : linear 1.00 → 0.80
      days_out 8–14 : linear 0.80 → 0.60
      days_out > 14 : 0.60 (floor)
    """
    if days_out <= 2:
        horizon = 1.0
    elif days_out <= 7:
        horizon = 1.0 - (days_out - 2) / 5.0 * 0.20
    elif days_out <= 14:
        horizon = 0.80 - (days_out - 7) / 7.0 * 0.20
    else:
        horizon = 0.60
    cond = _CONDITION_CONFIDENCE.get(condition_type or "", 1.0)
    return round(horizon * cond, 4)
```

- [ ] **Step 5: Run tests to confirm they PASS**

```bash
pytest tests/test_signal_quality.py::TestEdgeConfidenceConditionType -v
```

Expected: 3 passed.

- [ ] **Step 6: Run full suite for regressions**

```bash
pytest --tb=short -q 2>&1 | tail -10
```

The existing `TestEdgeConfidence` tests in `tests/test_weather_markets.py` call `edge_confidence(days_out)` without `condition_type` — they must still pass since `condition_type=None` defaults to multiplier 1.0.

- [ ] **Step 7: Commit**

```bash
git add weather_markets.py tests/test_signal_quality.py
git commit -m "feat: add _CONDITION_CONFIDENCE + condition_type param to edge_confidence (#14)"
```

---

## Task 3: Wire `condition_type` into bias correction and Kelly in `analyze_trade()`

**Files:**
- Modify: `weather_markets.py` (lines ~2041 for bias, ~2173 for Kelly)
- Test: `tests/test_signal_quality.py`

- [ ] **Step 1: Add 2 tests to `tests/test_signal_quality.py`**

Read the file, then append this class:

```python
class TestAnalyzeTradeConditionType:
    def test_bias_correction_condition_type_param_accepted(self):
        """get_bias accepts condition_type kwarg — confirms the interface exists for wiring."""
        from tracker import get_bias
        # Should not raise TypeError. Returns 0.0 when no history exists.
        result_global = get_bias("NYC", 5)
        result_cond = get_bias("NYC", 5, condition_type="above")
        assert isinstance(result_global, float)
        assert isinstance(result_cond, float)

    def test_condition_type_scale_in_kelly(self):
        """_CONDITION_CONFIDENCE values correctly rank: precip_snow < precip_any < above."""
        from weather_markets import _CONDITION_CONFIDENCE
        assert _CONDITION_CONFIDENCE["above"] == pytest.approx(1.00)
        assert _CONDITION_CONFIDENCE["precip_any"] == pytest.approx(0.90)
        assert _CONDITION_CONFIDENCE["precip_above"] == pytest.approx(0.85)
        assert _CONDITION_CONFIDENCE["precip_snow"] == pytest.approx(0.80)
        # Snow Kelly is exactly 80% of equivalent temperature Kelly
        base = 0.15
        assert base * _CONDITION_CONFIDENCE["precip_snow"] == pytest.approx(base * 0.80)
        assert base * _CONDITION_CONFIDENCE["precip_snow"] < base * _CONDITION_CONFIDENCE["above"]
```

- [ ] **Step 2: Run tests to confirm the constants test PASSES immediately**

```bash
pytest tests/test_signal_quality.py::TestAnalyzeTradeConditionType::test_condition_type_scale_in_kelly -v
```

Expected: 1 passed (constants are already set from Task 2).

- [ ] **Step 3: Update the bias correction call in `analyze_trade()`**

Find this block (around line 2041):

```python
    bias = 0.0
    try:
        from tracker import get_bias

        bias = get_bias(city, target_date.month)
        blended_prob = max(0.01, min(0.99, blended_prob - bias))
    except Exception as _exc:
```

Change `get_bias(city, target_date.month)` to:

```python
        bias = get_bias(city, target_date.month, condition_type=condition["type"])
```

- [ ] **Step 4: Add `condition_type_scale` to `ci_adjusted_kelly` in `analyze_trade()`**

Find this block (around line 2173):

```python
    ci_adjusted_kelly = round(
        bk
        * quality_scale
        * anomaly_scale
        * spread_scale
        * time_kelly_scale
        * _confidence_boost,
        6,
    )
```

Replace with:

```python
    condition_type_scale = _CONDITION_CONFIDENCE.get(condition["type"], 1.0)
    ci_adjusted_kelly = round(
        bk
        * quality_scale
        * anomaly_scale
        * spread_scale
        * time_kelly_scale
        * _confidence_boost
        * condition_type_scale,  # #39: scale down Kelly for harder-to-forecast conditions
        6,
    )
```

- [ ] **Step 5: Update the `edge_confidence` call in `analyze_trade()` to pass condition_type**

Find this line (around line 2154):

```python
    _edge_conf = edge_confidence(days_out)
```

Replace with:

```python
    _edge_conf = edge_confidence(days_out, condition_type=condition["type"])
```

- [ ] **Step 6: Run all signal quality tests**

```bash
pytest tests/test_signal_quality.py -v
```

Expected: 6 passed.

- [ ] **Step 7: Run full suite for regressions**

```bash
pytest --tb=short -q 2>&1 | tail -10
```

Expected: same pass/fail baseline.

- [ ] **Step 8: Commit**

```bash
git add weather_markets.py tests/test_signal_quality.py
git commit -m "feat: wire condition_type into bias correction, edge_confidence, and Kelly (#10/#39)"
```

---

## Task 4: Wire `days_back=60` into `_weights_from_mae()` and fix cache key

**Files:**
- Modify: `weather_markets.py` (lines 446–485, `_weights_from_mae` function)

No new tests needed — Task 1 already verified `get_member_accuracy(days_back=60)` returns recent-only data. This task just ensures that the production call path uses it.

- [ ] **Step 1: Update `_weights_from_mae` in `weather_markets.py`**

Find the function at line ~446. Make two changes:

**a. Update the signature** to accept and pass `days_back`:

```python
def _weights_from_mae(city: str, min_n: int = 20, days_back: int = 60) -> dict[str, float] | None:
```

**b. Fix the cache key** to include `days_back` (so different windows don't collide):

```python
    cache_key = (city, days_back)
    if cache_key in _MAE_WEIGHTS_CACHE:
        return _MAE_WEIGHTS_CACHE[cache_key]
```

**c. Update the `get_member_accuracy` call**:

```python
        acc = get_member_accuracy(days_back=days_back)
```

**d. Update the cache write**:

```python
    _MAE_WEIGHTS_CACHE[cache_key] = normalised
    return normalised
```

Full updated function:

```python
def _weights_from_mae(city: str, min_n: int = 20, days_back: int = 60) -> dict[str, float] | None:
    """
    #25/#118: Derive per-model blend weights from inverse-MAE scores in tracker.
    Uses a rolling days_back window (default 60 days) to capture recent model drift.
    Returns None if insufficient data (< min_n observations per model).
    Lower MAE → higher weight. Normalised so weights sum to the number of models.
    City-specific data is preferred; falls back to global MAE if city data is thin.
    """
    cache_key = (city, days_back)
    if cache_key in _MAE_WEIGHTS_CACHE:
        return _MAE_WEIGHTS_CACHE[cache_key]
    try:
        from tracker import get_member_accuracy

        acc = get_member_accuracy(days_back=days_back)  # {model: {mae, n, city_breakdown}}
    except Exception:
        return None

    if not acc:
        return None

    weights: dict[str, float] = {}
    for model, stats in acc.items():
        city_bd = stats.get("city_breakdown", {})
        city_mae = city_bd.get(city)
        city_n = sum(1 for _ in city_bd) if city_bd else 0
        mae = city_mae if (city_mae is not None and city_n >= min_n) else stats["mae"]
        n = stats["n"]
        if n < min_n or mae <= 0:
            return None  # too little data — don't trust yet
        weights[model] = 1.0 / mae

    if not weights:
        return None

    total = sum(weights.values())
    n_models = len(weights)
    normalised = {m: v / total * n_models for m, v in weights.items()}
    _MAE_WEIGHTS_CACHE[cache_key] = normalised
    return normalised
```

- [ ] **Step 2: Run full suite**

```bash
pytest --tb=short -q 2>&1 | tail -10
```

Expected: same baseline.

- [ ] **Step 3: Commit**

```bash
git add weather_markets.py
git commit -m "feat: pass days_back=60 through _weights_from_mae for recent-MAE weighting (#25)"
```
