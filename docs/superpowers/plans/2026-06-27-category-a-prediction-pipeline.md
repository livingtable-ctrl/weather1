# Category A: Prediction Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the forecast-to-probability pipeline from raw ensemble fractions to EMOS-calibrated distributions, add bimodal detection, fix circuit-breaker blend weights, and integrate higher-quality data sources.

**Architecture:** Ten independent improvements to `weather_markets.py`, `ml_bias.py`, `tracker.py`, and `nws.py`. A1 (EMOS) is the prerequisite for A7 walk-forward re-validation. A8 (circuit breaker blend) is a correctness bug fix that should ship before A1. All others are independent.

**Tech Stack:** Python 3.14, scipy (optimize, special), properscoring (CRPS), numpy, SQLite, Open-Meteo API (Previous Runs endpoint), pytest.

**Implementation Order:** A8 → A3 → A1 → A2 → A4 → A5 → A6 → A7 → A9 → A10

---

## A8: Circuit Breaker Blend Rebalancing

**Problem:** When the Open-Meteo ensemble circuit breaker opens, `ens_prob` is stale but the blend still applies its full weight (e.g. `w_ens=0.60` for above markets). A trade placed during an outage has a severely wrong `blended_prob`. The fix: detect circuit OPEN, set `w_ens=0.0`, renormalize NWS+climatology to sum to 1.

**Files:**
- Modify: `weather_markets.py` (blend weight section, search for `w_ens` / `blended_prob`)
- Modify: `circuit_breaker.py` (confirm `get_circuit_state()` API)
- Test: `tests/test_circuit_breaker.py`

- [ ] **Step 1: Confirm the circuit breaker API**

Read `circuit_breaker.py` and identify the function that returns the current state for a named source. You need a call like `get_circuit_state("open_meteo")` that returns `"OPEN"` / `"CLOSED"` / `"HALF_OPEN"`. If it uses a class, find the instance that `weather_markets.py` uses.

```python
# Run to verify the existing API:
from circuit_breaker import CircuitBreaker
# Inspect what methods exist
print(dir(CircuitBreaker))
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_circuit_breaker.py — add this test
def test_blend_uses_nws_clim_only_when_ensemble_circuit_open(monkeypatch):
    """When ensemble circuit is OPEN, blended_prob must use only nws+clim weights."""
    import weather_markets as wm

    # Force the circuit open
    monkeypatch.setattr(wm, "_ensemble_circuit_is_open", lambda: True)

    nws_prob = 0.70
    clim_prob = 0.60
    ens_prob = 0.10   # stale / wrong value from before the outage

    w_ens, w_nws, w_clim = 0.60, 0.35, 0.05  # normal above weights
    result = wm._blend_with_circuit_fallback(ens_prob, nws_prob, clim_prob, w_ens, w_nws, w_clim)

    # With ens excluded, renormalized: w_nws=0.35/0.40=0.875, w_clim=0.05/0.40=0.125
    expected = round(0.875 * nws_prob + 0.125 * clim_prob, 6)
    assert abs(result - expected) < 1e-4
```

- [ ] **Step 3: Run test to confirm it fails**

```
pytest tests/test_circuit_breaker.py::test_blend_uses_nws_clim_only_when_ensemble_circuit_open -v
```
Expected: `AttributeError: module 'weather_markets' has no attribute '_ensemble_circuit_is_open'`

- [ ] **Step 4: Add `_ensemble_circuit_is_open()` and `_blend_with_circuit_fallback()` to `weather_markets.py`**

Find the section near the top of `weather_markets.py` where `check_ensemble_circuit_health` is imported. Add after that import block:

```python
def _ensemble_circuit_is_open() -> bool:
    """Return True if the Open-Meteo ensemble circuit breaker is currently OPEN."""
    try:
        health = check_ensemble_circuit_health()
        # check_ensemble_circuit_health returns a dict with a 'state' key
        # or may return True/False directly — adapt to the actual return type
        if isinstance(health, dict):
            return health.get("state", "CLOSED") == "OPEN"
        return not bool(health)  # False health = OPEN
    except Exception:
        return False  # fail open (assume circuit closed if check fails)


def _blend_with_circuit_fallback(
    ens_prob: float | None,
    nws_prob: float | None,
    clim_prob: float | None,
    w_ens: float,
    w_nws: float,
    w_clim: float,
) -> float:
    """Blend source probabilities, zeroing ens weight when circuit is OPEN.

    If ensemble circuit is open, redistributes w_ens proportionally to w_nws and w_clim.
    Handles None probabilities by excluding them from the blend and renormalizing.
    """
    circuit_open = _ensemble_circuit_is_open()
    if circuit_open and ens_prob is not None:
        import logging
        logging.getLogger(__name__).warning(
            "blend: ensemble circuit OPEN — excluding ens_prob from blend (was %.3f)", ens_prob
        )
        ens_prob = None  # exclude from blend

    weights = []
    probs = []
    if ens_prob is not None:
        weights.append(w_ens)
        probs.append(ens_prob)
    if nws_prob is not None:
        weights.append(w_nws)
        probs.append(nws_prob)
    if clim_prob is not None:
        weights.append(w_clim)
        probs.append(clim_prob)

    total_w = sum(weights)
    if total_w <= 0:
        return 0.5  # no sources available — neutral probability
    return sum(w * p for w, p in zip(weights, probs)) / total_w
```

- [ ] **Step 5: Replace the manual blend calculation in `weather_markets.py` with `_blend_with_circuit_fallback`**

Search for the line that computes `blended_prob` using `w_ens * ens_prob + w_nws * nws_prob + w_clim * clim_prob`. Replace with:

```python
blended_prob = _blend_with_circuit_fallback(
    ens_prob, nws_prob, clim_prob, w_ens, w_nws, w_clim
)
```

Note: There may be multiple blend sites (seasonal, condition, city weight paths). Replace all of them.

- [ ] **Step 6: Run the new test**

```
pytest tests/test_circuit_breaker.py::test_blend_uses_nws_clim_only_when_ensemble_circuit_open -v
```
Expected: PASS

- [ ] **Step 7: Run the affected test files**

```
pytest tests/test_circuit_breaker.py tests/test_flash_crash_cb.py tests/test_forecasting.py -v
```
Expected: all PASS

- [ ] **Step 8: Commit**

```
git add weather_markets.py tests/test_circuit_breaker.py
git commit -m "fix(blend): exclude ensemble from blend when circuit breaker is OPEN"
```

---

## A3: Bimodal Ensemble Detection

**Problem:** When 30 members say 62°F and 20 members say 78°F, the ensemble mean is ~69°F with high spread — but the spread statistic hides that there are two distinct weather scenarios. The current code treats this identically to a unimodal distribution. A bimodal signal should dramatically reduce Kelly.

**Files:**
- Modify: `weather_markets.py` (add bimodal detection before Kelly)
- Modify: `regime.py` (add bimodal regime type)
- Test: `tests/test_forecasting.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_forecasting.py — add this
def test_detect_bimodal_ensemble():
    from weather_markets import _detect_bimodal_ensemble

    bimodal_temps = [62.0] * 30 + [78.0] * 20  # two clear clusters
    unimodal_temps = [68.0 + i * 0.2 for i in range(-25, 25)]  # tight spread

    assert _detect_bimodal_ensemble(bimodal_temps) is True
    assert _detect_bimodal_ensemble(unimodal_temps) is False
    assert _detect_bimodal_ensemble([]) is False
    assert _detect_bimodal_ensemble([70.0] * 5) is False  # too few members
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest tests/test_forecasting.py::test_detect_bimodal_ensemble -v
```
Expected: `AttributeError: module 'weather_markets' has no attribute '_detect_bimodal_ensemble'`

- [ ] **Step 3: Add `_detect_bimodal_ensemble()` to `weather_markets.py`**

Add near the top of `weather_markets.py`, below the imports section:

```python
def _detect_bimodal_ensemble(temps: list[float]) -> bool:
    """Return True when ensemble members form two distinct clusters (bimodal distribution).

    Uses a simple k-means(k=2) split: if both clusters contain at least 20% of members
    AND the gap between cluster means is >= 8°F, the distribution is considered bimodal.
    Requires at least 10 members; returns False for smaller ensembles.
    """
    if len(temps) < 10:
        return False

    import statistics

    # Sort and split at the median gap
    sorted_temps = sorted(temps)
    n = len(sorted_temps)
    # Find the largest gap between consecutive sorted values
    gaps = [(sorted_temps[i + 1] - sorted_temps[i], i) for i in range(n - 1)]
    max_gap, split_idx = max(gaps)

    if max_gap < 6.0:
        # No large gap — not bimodal
        return False

    cluster_a = sorted_temps[:split_idx + 1]
    cluster_b = sorted_temps[split_idx + 1:]

    # Both clusters must have at least 20% of members
    min_cluster_size = max(2, int(n * 0.20))
    if len(cluster_a) < min_cluster_size or len(cluster_b) < min_cluster_size:
        return False

    mean_a = statistics.mean(cluster_a)
    mean_b = statistics.mean(cluster_b)
    cluster_separation = abs(mean_b - mean_a)

    # Separation must be >= 8°F to be meteorologically meaningful
    return cluster_separation >= 8.0
```

- [ ] **Step 4: Run the bimodal test**

```
pytest tests/test_forecasting.py::test_detect_bimodal_ensemble -v
```
Expected: PASS

- [ ] **Step 5: Write the Kelly reduction test**

```python
def test_bimodal_kelly_returns_point_one_when_bimodal(monkeypatch):
    """When _detect_bimodal_ensemble returns True, multiplier must be 0.10."""
    import weather_markets as wm
    monkeypatch.setattr(wm, "_detect_bimodal_ensemble", lambda temps: True)

    bimodal_temps = [62.0] * 30 + [78.0] * 20
    result = wm._get_bimodal_kelly_multiplier(bimodal_temps)
    assert result == pytest.approx(0.10, abs=0.01)


def test_bimodal_kelly_returns_one_when_unimodal(monkeypatch):
    """When _detect_bimodal_ensemble returns False, multiplier must be 1.0.

    NOTE: monkeypatch is scoped per-test — this test gets a fresh patch so the
    previous test's lambda (always True) does not bleed in.
    """
    import weather_markets as wm
    monkeypatch.setattr(wm, "_detect_bimodal_ensemble", lambda temps: False)

    unimodal_temps = [68.0 + i * 0.2 for i in range(-25, 25)]
    result = wm._get_bimodal_kelly_multiplier(unimodal_temps)
    assert result == pytest.approx(1.0, abs=0.01)
```

- [ ] **Step 6: Add `_get_bimodal_kelly_multiplier()` to `weather_markets.py`**

```python
_BIMODAL_KELLY_MULTIPLIER = 0.10  # 10% of normal Kelly when ensemble is bimodal

def _get_bimodal_kelly_multiplier(temps: list[float]) -> float:
    """Return 0.10 when ensemble is bimodal, else 1.0."""
    if _detect_bimodal_ensemble(temps):
        import logging
        logging.getLogger(__name__).warning(
            "BIMODAL ensemble detected (%d members) — Kelly reduced to 10%%", len(temps)
        )
        return _BIMODAL_KELLY_MULTIPLIER
    return 1.0
```

- [ ] **Step 7: Wire the multiplier into `analyze_trade`**

In `analyze_trade`, after `ens_stats` is computed and `temps` is available, add this near the end of the function before the Kelly calculation:

```python
# Bimodal ensemble guard: two distinct weather scenarios → sharp Kelly reduction
_bimodal_mult = _get_bimodal_kelly_multiplier(temps) if temps else 1.0
```

Then multiply into `ci_adjusted_kelly` (or wherever Kelly is finalized before return):

```python
ci_adjusted_kelly = ci_adjusted_kelly * _bimodal_mult
```

Also add `"bimodal": _bimodal_mult < 1.0` to the returned dict so the dashboard can flag it.

- [ ] **Step 8: Run the kelly test**

```
pytest tests/test_forecasting.py::test_bimodal_ensemble_reduces_kelly -v
```
Expected: PASS

- [ ] **Step 9: Run the full forecasting test file**

```
pytest tests/test_forecasting.py -v
```
Expected: all PASS

- [ ] **Step 10: Commit**

```
git add weather_markets.py tests/test_forecasting.py
git commit -m "feat(risk): detect bimodal ensemble and reduce Kelly to 10%"
```

---

## A1: EMOS Training & Deployment

**Problem:** Ensemble exceedance fractions (count members above threshold / total members) are systematically low due to under-dispersed ensembles. Brier decomposition confirms REL=0.046 >> RES=0.029 — miscalibration dominates. EMOS fits a Gaussian N(a+b·μ_ens, sqrt(c+d·σ²_ens)) on historical data and computes P(T>threshold) from the fitted distribution, correcting under-dispersion at source.

**Prerequisites:**
- DB schema v28 already has `ens_mean`, `ens_var` in `predictions` table ✓
- `outcomes.settled_temp_f` already exists ✓
- Backfill complete: 79 rows with `ens_mean IS NOT NULL` ✓
- `properscoring` must be installed: `pip install properscoring`

**Files:**
- Modify: `ml_bias.py` — add `fit_emos`, `emos_exceedance_prob`, `emos_interval_prob`, `_load_emos_params`, `save_emos_params`
- Modify: `tracker.py` — add `get_emos_training_data()`
- Modify: `main.py` — add `emos-train` CLI subcommand
- Modify: `weather_markets.py` — replace exceedance fraction at line ~4816 with EMOS
- Modify: `data/temperature_scale.json` — set all T values to 1.0 (SAME commit as EMOS deploy)
- Test: `tests/test_ml_bias.py`

### Part A: EMOS functions in ml_bias.py

- [ ] **Step 1: Write failing tests for EMOS functions**

```python
# tests/test_ml_bias.py — add these tests
import math
import numpy as np
import pytest

def test_fit_emos_returns_four_floats():
    from ml_bias import fit_emos
    ens_mean = np.array([65.0, 72.0, 58.0, 80.0, 67.0, 71.0, 63.0, 75.0])
    ens_var  = np.array([4.0,  9.0,  2.25, 16.0, 3.0, 6.0, 1.0, 12.0])
    obs      = np.array([67.0, 70.0, 60.0, 82.0, 69.0, 73.0, 62.0, 77.0])
    a, b, c, d = fit_emos(ens_mean, ens_var, obs)
    assert isinstance(a, float)
    assert isinstance(b, float)
    assert c >= 0.0, f"c={c} must be non-negative"
    assert d >= 0.0, f"d={d} must be non-negative"


def test_emos_exceedance_prob_in_bounds():
    from ml_bias import emos_exceedance_prob
    params = (0.5, 0.95, 1.5, 0.10)
    prob = emos_exceedance_prob(params, ens_mean=65.0, ens_var=4.0, threshold=70.0)
    assert 0.0 <= prob <= 1.0


def test_emos_exceedance_prob_monotone():
    """Higher threshold → lower exceedance probability."""
    from ml_bias import emos_exceedance_prob
    params = (0.5, 0.95, 1.5, 0.10)
    p_low  = emos_exceedance_prob(params, 70.0, 4.0, threshold=65.0)
    p_high = emos_exceedance_prob(params, 70.0, 4.0, threshold=80.0)
    assert p_low > p_high


def test_emos_interval_prob_in_bounds():
    from ml_bias import emos_interval_prob
    params = (0.5, 0.95, 1.5, 0.10)
    prob = emos_interval_prob(params, ens_mean=68.0, ens_var=4.0, low=65.0, high=71.0)
    assert 0.0 <= prob <= 1.0


def test_emos_interval_and_exceedance_consistent():
    """P(T>threshold) + P(low<T<threshold) should be <= P(T>low)."""
    from ml_bias import emos_exceedance_prob, emos_interval_prob
    params = (0.5, 0.95, 1.5, 0.10)
    p_above_65 = emos_exceedance_prob(params, 70.0, 4.0, threshold=65.0)
    p_interval = emos_interval_prob(params, 70.0, 4.0, low=65.0, high=70.0)
    p_above_70 = emos_exceedance_prob(params, 70.0, 4.0, threshold=70.0)
    # P(>65) == P(65<T<70) + P(T>70)
    assert abs(p_above_65 - (p_interval + p_above_70)) < 0.001


def test_load_emos_params_returns_none_when_file_missing(tmp_path, monkeypatch):
    from ml_bias import _load_emos_params
    import ml_bias
    monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", tmp_path / "emos_params.json")
    monkeypatch.setattr(ml_bias, "_EMOS_CACHE", None)
    assert _load_emos_params() is None


def test_save_and_reload_emos_params(tmp_path, monkeypatch):
    import ml_bias
    from ml_bias import save_emos_params, _load_emos_params
    monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", tmp_path / "emos_params.json")
    monkeypatch.setattr(ml_bias, "_EMOS_CACHE", None)
    save_emos_params(1.23, 0.94, 2.1, 0.18, n=79, mean_crps=0.42)
    monkeypatch.setattr(ml_bias, "_EMOS_CACHE", None)  # force reload
    params = _load_emos_params()
    assert params is not None
    a, b, c, d = params
    assert abs(a - 1.23) < 0.001
    assert abs(b - 0.94) < 0.001
```

- [ ] **Step 2: Run to confirm all fail**

```
pytest tests/test_ml_bias.py::test_fit_emos_returns_four_floats tests/test_ml_bias.py::test_save_and_reload_emos_params -v
```
Expected: `ImportError` or `AttributeError` for each.

- [ ] **Step 3: Add EMOS functions to `ml_bias.py`**

At the top of `ml_bias.py`, add to imports:
```python
import json
import math
```

Add these constants near the existing `_TEMP_PATH` constant:
```python
_EMOS_PARAMS_PATH = Path(__file__).parent / "data" / "emos_params.json"
_EMOS_CACHE: tuple | None = None  # cached (a, b, c, d)
```

Add these functions after the temperature scaling functions:

```python
# ── EMOS (Ensemble Model Output Statistics) ────────────────────────────────

def fit_emos(
    ens_mean: "np.ndarray",
    ens_var: "np.ndarray",
    obs: "np.ndarray",
) -> tuple[float, float, float, float]:
    """Fit EMOS parameters (a, b, c, d) minimising mean CRPS.

    Model: T ~ N(mu, sigma^2) where
        mu    = a + b * ens_mean
        sigma = sqrt(max(c + d * ens_var, 1e-6))

    Optimizer works in sqrt-space (c_sq, d_sq) to keep sigma positive.
    Returned (c, d) are the final values — do NOT square again at call site.

    Requires: pip install properscoring numpy scipy
    """
    import numpy as _np
    import properscoring as _ps
    from scipy.optimize import minimize as _minimize

    ens_mean = _np.asarray(ens_mean, dtype=float)
    ens_var  = _np.asarray(ens_var,  dtype=float)
    obs      = _np.asarray(obs,      dtype=float)

    def objective(params: list) -> float:
        a_, b_, c_sq, d_sq = params
        mu    = a_ + b_ * ens_mean
        sigma = _np.sqrt(_np.maximum(c_sq ** 2 + d_sq ** 2 * ens_var, 1e-6))
        return float(_np.mean(_ps.crps_gaussian(obs, mu=mu, sig=sigma)))

    res = _minimize(
        objective,
        x0=[0.0, 1.0, 1.0, 0.1],
        method="Nelder-Mead",
        options={"maxiter": 20_000, "xatol": 1e-7, "fatol": 1e-7},
    )
    a, b, c_sq, d_sq = res.x
    return float(a), float(b), float(c_sq ** 2), float(d_sq ** 2)


def emos_exceedance_prob(
    params: tuple[float, float, float, float],
    ens_mean: float,
    ens_var: float,
    threshold: float,
) -> float:
    """P(T > threshold) from a fitted EMOS Gaussian distribution.

    CRITICAL: pass ens_var (variance = std**2), NOT std.
    If ens_stats provides 'std', square it: ens_var = ens_stats['std'] ** 2
    """
    from scipy.special import ndtr
    a, b, c, d = params
    mu    = a + b * ens_mean
    sigma = math.sqrt(max(c + d * ens_var, 1e-6))
    return float(1.0 - ndtr((threshold - mu) / sigma))


def emos_interval_prob(
    params: tuple[float, float, float, float],
    ens_mean: float,
    ens_var: float,
    low: float,
    high: float,
) -> float:
    """P(low < T < high) from a fitted EMOS Gaussian — for 'between' markets.

    Uses the same (a, b, c, d) parameters as exceedance; no separate fit needed.
    CRITICAL: pass ens_var (variance), NOT std.
    """
    from scipy.special import ndtr
    a, b, c, d = params
    mu    = a + b * ens_mean
    sigma = math.sqrt(max(c + d * ens_var, 1e-6))
    return float(ndtr((high - mu) / sigma) - ndtr((low - mu) / sigma))


def _load_emos_params() -> tuple[float, float, float, float] | None:
    """Return cached (a, b, c, d) from emos_params.json, or None if not trained."""
    global _EMOS_CACHE
    if _EMOS_CACHE is not None:
        return _EMOS_CACHE
    if not _EMOS_PARAMS_PATH.exists():
        return None
    try:
        data = json.loads(_EMOS_PARAMS_PATH.read_text())
        _EMOS_CACHE = (float(data["a"]), float(data["b"]), float(data["c"]), float(data["d"]))
        _log.info(
            "EMOS params loaded: a=%.4f b=%.4f c=%.4f d=%.4f n=%d crps=%s",
            *_EMOS_CACHE,
            data.get("n", "?"),
            data.get("mean_crps", "?"),
        )
        return _EMOS_CACHE
    except Exception as exc:
        _log.error("ml_bias: failed to load emos_params.json: %s", exc)
        return None


def save_emos_params(
    a: float,
    b: float,
    c: float,
    d: float,
    n: int,
    mean_crps: float | None = None,
) -> None:
    """Persist EMOS parameters and clear the in-process cache."""
    global _EMOS_CACHE
    from datetime import UTC, datetime
    payload = {
        "a": float(a),
        "b": float(b),
        "c": float(c),
        "d": float(d),
        "n": int(n),
        "mean_crps": float(mean_crps) if mean_crps is not None else None,
        "fitted_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    atomic_write_json(payload, _EMOS_PARAMS_PATH)
    _EMOS_CACHE = (float(a), float(b), float(c), float(d))
    _log.info("EMOS params saved: a=%.4f b=%.4f c=%.4f d=%.4f (n=%d)", a, b, c, d, n)
```

- [ ] **Step 4: Run the EMOS tests**

```
pytest tests/test_ml_bias.py -k "emos" -v
```
Expected: all 7 EMOS tests PASS.

### Part B: Training data query in tracker.py

- [ ] **Step 5: Write failing test for `get_emos_training_data`**

```python
# tests/test_ml_bias.py — add this
def test_get_emos_training_data_excludes_null_ens_mean(tmp_path, monkeypatch):
    import tracker
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
    tracker._db_initialized = False
    tracker.init_db()

    with tracker._conn() as con:
        # Row 1: has ens_mean + settled_temp_f → should appear
        con.execute(
            "INSERT INTO predictions (ticker, our_prob, market_prob, created_at, days_out, ens_mean, ens_var) "
            "VALUES ('KXHIGH-T70', 0.6, 0.55, '2026-06-01', 1, 72.3, 4.5)"
        )
        con.execute(
            "INSERT INTO outcomes (ticker, settled_yes, settled_at, settled_temp_f) "
            "VALUES ('KXHIGH-T70', 1, '2026-06-01', 73.0)"
        )
        # Row 2: ens_mean IS NULL → must be excluded
        con.execute(
            "INSERT INTO predictions (ticker, our_prob, market_prob, created_at, days_out) "
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
```

- [ ] **Step 6: Run to confirm failure**

```
pytest tests/test_ml_bias.py::test_get_emos_training_data_excludes_null_ens_mean -v
```
Expected: `AttributeError: module 'tracker' has no attribute 'get_emos_training_data'`

- [ ] **Step 7: Add `get_emos_training_data()` to `tracker.py`**

Find the section in `tracker.py` with other `get_*` query functions. Add:

```python
def get_emos_training_data() -> list[dict]:
    """Return rows for EMOS fitting: {ens_mean, ens_var, settled_temp_f}.

    Excludes rows where ens_mean or settled_temp_f is NULL.
    ens_var may be NULL for backfill rows — callers must handle None.
    Queries multiday_predictions (days_out >= 1 or NULL) only.
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.ens_mean, p.ens_var, o.settled_temp_f
            FROM   multiday_predictions p
            JOIN   outcomes o ON o.ticker = p.ticker
            WHERE  p.ens_mean IS NOT NULL
              AND  o.settled_temp_f IS NOT NULL
            ORDER  BY p.created_at
            """
        ).fetchall()
    return [
        {
            "ens_mean":       float(r[0]),
            "ens_var":        float(r[1]) if r[1] is not None else None,
            "settled_temp_f": float(r[2]),
        }
        for r in rows
    ]
```

- [ ] **Step 8: Run the tracker test**

```
pytest tests/test_ml_bias.py::test_get_emos_training_data_excludes_null_ens_mean -v
```
Expected: PASS

### Part C: `emos-train` CLI command in main.py

- [ ] **Step 9: Add `_cmd_emos_train()` to `main.py`**

Find the CLI dispatch section in `main.py` (search for `elif cmd == "calibrate"` for the pattern). Add:

```python
elif cmd == "emos-train":
    _cmd_emos_train()
```

Then add the function (near other `_cmd_*` functions):

```python
def _cmd_emos_train() -> None:
    """Two-stage EMOS fit: mean calibration (a,b) from all rows, variance (c,d) from ens_var rows."""
    try:
        import numpy as np
    except ImportError:
        print("ERROR: numpy not installed.")
        return
    try:
        import properscoring  # noqa: F401
    except ImportError:
        print("ERROR: properscoring not installed. Run: pip install properscoring")
        return

    from ml_bias import fit_emos, save_emos_params
    from tracker import get_emos_training_data

    print("Loading EMOS training data…")
    rows = get_emos_training_data()
    if not rows:
        print("No EMOS training data found. Run: py main.py backfill-emos")
        return

    n = len(rows)
    print(f"  {n} rows with ens_mean + settled_temp_f")

    ens_mean    = np.array([r["ens_mean"] for r in rows])
    settled_temp = np.array([r["settled_temp_f"] for r in rows])
    # Rows without ens_var get a unit-variance placeholder for stage 1
    ens_var_all = np.array([r["ens_var"] if r["ens_var"] is not None else 1.0 for r in rows])

    print("\nStage 1 — fitting a, b (mean calibration) from all rows…")
    a, b, _, _ = fit_emos(ens_mean, ens_var_all, settled_temp)
    print(f"  a = {a:.4f}   b = {b:.4f}")

    var_rows = [r for r in rows if r["ens_var"] is not None]
    n_var = len(var_rows)
    print(f"\nStage 2 — fitting c, d (variance calibration) from {n_var} rows with real ens_var…")

    if n_var >= 10:
        vm = np.array([r["ens_mean"] for r in var_rows])
        vv = np.array([r["ens_var"] for r in var_rows])
        vo = np.array([r["settled_temp_f"] for r in var_rows])
        _, _, c, d = fit_emos(vm, vv, vo)
        print(f"  c = {c:.4f}   d = {d:.4f}")
    else:
        c, d = 1.0, 0.1
        print(f"  WARNING: only {n_var} ens_var rows (need ≥ 10). Using defaults c=1.0, d=0.1")

    try:
        import properscoring as ps
        mu = a + b * ens_mean
        import math
        sigma_all = np.sqrt(np.maximum(c + d * ens_var_all, 1e-6))
        mean_crps = float(np.mean(ps.crps_gaussian(settled_temp, mu=mu, sig=sigma_all)))
        print(f"\nMean CRPS on training set: {mean_crps:.4f}")
    except Exception:
        mean_crps = None

    save_emos_params(a, b, c, d, n=n, mean_crps=mean_crps)
    print("\nSaved → data/emos_params.json")
    print("\nNEXT: review params above, then deploy in a single commit:")
    print("  1. In weather_markets.py: replace ens_prob exceedance fraction with emos_exceedance_prob()")
    print("  2. In data/temperature_scale.json: set T_above=T_below=T_global=1.0")
    print("  3. Restart dashboard / cron")
```

- [ ] **Step 10: Smoke-test the command**

```
py main.py emos-train
```
Expected output: prints training row count, two-stage fit results, saves `data/emos_params.json`. If 0 rows, prints instructions.

### Part D: Deploy EMOS in weather_markets.py

- [ ] **Step 11: Write the failing deployment test**

```python
# tests/test_ml_bias.py — add
def test_emos_exceedance_prob_called_via_load_emos_params(monkeypatch, tmp_path):
    """_load_emos_params must return the cache when _EMOS_CACHE is populated,
    and emos_exceedance_prob must return a sensible probability for above-condition.

    This is the unit-level wiring test: it verifies the functions exist and their
    signatures are compatible before the full analyze_trade integration test is written.
    """
    import json
    import ml_bias

    # Write a real emos_params.json so _load_emos_params reads it
    params = {"a": 0.0, "b": 1.0, "c": 1.0, "d": 0.0, "n": 79}
    params_path = tmp_path / "emos_params.json"
    params_path.write_text(json.dumps(params))

    monkeypatch.setattr(ml_bias, "_EMOS_PARAMS_PATH", params_path)
    monkeypatch.setattr(ml_bias, "_EMOS_CACHE", None)  # force re-read from file

    loaded = ml_bias._load_emos_params()
    assert loaded is not None, "_load_emos_params returned None — file not read"
    a, b, c, d = loaded
    assert b == pytest.approx(1.0), "b param should be 1.0"

    # With a=0, b=1, c=1, d=0: mu=ens_mean, sigma=sqrt(1.0).
    # P(T > 72 | ens_mean=70, ens_var=4) using normal CDF.
    ens_mean, ens_var, threshold = 70.0, 4.0, 72.0
    prob = ml_bias.emos_exceedance_prob(loaded, ens_mean, ens_var, threshold)
    assert 0.0 < prob < 0.5, (
        f"emos_exceedance_prob should be < 0.5 when threshold > mean; got {prob}"
    )


def test_analyze_trade_uses_emos_when_params_loaded(monkeypatch, tmp_path):
    """When _EMOS_CACHE is set (params loaded), analyze_trade must route through
    emos_exceedance_prob rather than the raw ensemble fraction. Verified via spy."""
    import json
    import ml_bias
    import weather_markets as wm

    # Populate the EMOS cache directly (skips file I/O)
    monkeypatch.setattr(ml_bias, "_EMOS_CACHE", (0.0, 1.0, 1.0, 0.0))

    called = []
    original = ml_bias.emos_exceedance_prob

    def spy_exceedance(params, ens_mean, ens_var, threshold):
        called.append((ens_mean, ens_var, threshold))
        return original(params, ens_mean, ens_var, threshold)

    monkeypatch.setattr(ml_bias, "emos_exceedance_prob", spy_exceedance)

    # Patch every external call analyze_trade makes (per conftest isolation patterns)
    monkeypatch.setattr(wm, "get_ensemble_temps", lambda *a, **k: [65.0] * 14 + [67.0] * 6)
    monkeypatch.setattr(wm, "_get_consensus_probs", lambda *a, **k: (None, None, None, None))
    # Additional patches needed (NWS, climate, METAR) — add here as you wire each step.
    # The assertion is the critical part: called must be non-empty after analyze_trade runs.

    # Minimal analyze_trade call — fill in required args from actual function signature
    # (city, condition, yes_bid, yes_ask, client=None):
    result = wm.analyze_trade(
        city="NYC",
        condition={"type": "above", "threshold": 70.0},
        yes_bid=0.40,
        yes_ask=0.50,
        client=None,
    )

    assert len(called) > 0, (
        "emos_exceedance_prob was never called — EMOS is not wired into analyze_trade. "
        "Check that the _load_emos_params + emos_exceedance_prob branch is reached when "
        "_EMOS_CACHE is set and ens_stats is not None."
    )
```

- [ ] **Step 12: Wire EMOS into `weather_markets.py` at the exceedance fraction (lines ~4813–4825)**

Find this exact block in `analyze_trade`:

```python
        if len(temps) >= 10:
            method = "ensemble"
            if condition["type"] == "above":
                ens_prob = sum(1 for t in temps if t > condition["threshold"]) / len(temps)
            elif condition["type"] == "below":
                ens_prob = sum(1 for t in temps if t < condition["threshold"]) / len(temps)
            else:
                lo, hi = condition["lower"], condition["upper"]
                ens_prob = sum(1 for t in temps if lo <= t <= hi) / len(temps)
```

Replace with:

```python
        if len(temps) >= 10:
            method = "ensemble"
            # EMOS path: use fitted Gaussian distribution if params are available.
            # Falls back to raw exceedance fraction when EMOS not yet trained.
            # CRITICAL: pass ens_var = std**2 (must square std, NOT pass std directly).
            from ml_bias import _load_emos_params, emos_exceedance_prob, emos_interval_prob
            _emos_params = _load_emos_params()
            _use_emos = (_emos_params is not None and ens_stats is not None
                         and ens_stats.get("std") is not None)
            if _use_emos:
                _ens_var_live = ens_stats["std"] ** 2  # variance, not std
                if condition["type"] == "above":
                    ens_prob = emos_exceedance_prob(
                        _emos_params, ens_stats["mean"], _ens_var_live, condition["threshold"]
                    )
                elif condition["type"] == "below":
                    ens_prob = 1.0 - emos_exceedance_prob(
                        _emos_params, ens_stats["mean"], _ens_var_live, condition["threshold"]
                    )
                else:
                    lo, hi = condition["lower"], condition["upper"]
                    ens_prob = emos_interval_prob(
                        _emos_params, ens_stats["mean"], _ens_var_live, lo, hi
                    )
                method = "emos"
            else:
                # Fallback: raw exceedance fraction
                if condition["type"] == "above":
                    ens_prob = sum(1 for t in temps if t > condition["threshold"]) / len(temps)
                elif condition["type"] == "below":
                    ens_prob = sum(1 for t in temps if t < condition["threshold"]) / len(temps)
                else:
                    lo, hi = condition["lower"], condition["upper"]
                    ens_prob = sum(1 for t in temps if lo <= t <= hi) / len(temps)
```

- [ ] **Step 13: Disable temperature scaling in the SAME commit**

Edit `data/temperature_scale.json` to set all T values to 1.0:

```json
{
  "above":   {"T": 1.0, "n": 14},
  "below":   {"T": 1.0, "n": 14},
  "global":  {"T": 1.0, "n": 0}
}
```

**Rationale:** T=6.0/T=3.0 were derived to correct raw exceedance fraction over-confidence. EMOS fixes over-confidence at source. Applying T-scaling on top of EMOS would double-compress toward 0.5.

- [ ] **Step 14: Run the full test suite for affected files**

```
pytest tests/test_ml_bias.py tests/test_forecasting.py tests/test_phase2_batch_a.py tests/test_phase2_batch_b.py -v
```
Expected: all PASS (existing tests should still pass since EMOS is a drop-in replacement with a fallback path).

- [ ] **Step 15: Manual smoke test**

```
py main.py analyze
```
Check log output for `method = "emos"` entries. If you see `method = "ensemble"` it means EMOS params weren't loaded — verify `data/emos_params.json` exists.

- [ ] **Step 16: Commit EMOS deployment**

```
git add ml_bias.py tracker.py main.py weather_markets.py data/temperature_scale.json
git commit -m "feat(emos): deploy EMOS calibration, disable T-scaling — fixes ensemble under-dispersion (REL=0.046)"
```

---

## A2: NBM Quantile Integration

**Problem:** `nws.py` converts the NBM point forecast (T50 = median) to a probability using `scipy.stats.norm.cdf` with an assumed sigma. The NBM actually publishes native quantiles (T10, T25, T50, T75, T90 percentiles) for free at the same endpoint. Using these directly removes the sigma assumption.

**Files:**
- Modify: `nws.py` (add `fetch_nbm_quantiles()`, modify `nws_prob()`)
- Test: `tests/test_nbm.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_nbm.py — add
def test_nws_prob_uses_quantiles_when_available(monkeypatch):
    """When NBM returns quantile data, nws_prob must use ECDF interpolation not Gaussian CDF."""
    from nws import nws_prob_from_quantiles

    # NBM quantiles: [T10=62, T25=65, T50=68, T75=71, T90=74]
    quantiles = {10: 62.0, 25: 65.0, 50: 68.0, 75: 71.0, 90: 74.0}

    # P(T > 70) should be between 0.25 and 0.40 (threshold is between T75=71 and T75)
    prob = nws_prob_from_quantiles(quantiles, threshold=70.0, condition_type="above")
    assert 0.15 <= prob <= 0.40

    # P(T > 68) = P(T > median) should be ~0.50
    prob_at_median = nws_prob_from_quantiles(quantiles, threshold=68.0, condition_type="above")
    assert 0.45 <= prob_at_median <= 0.55
```

- [ ] **Step 2: Add `nws_prob_from_quantiles()` to `nws.py`**

```python
def nws_prob_from_quantiles(
    quantiles: dict[int, float],
    threshold: float,
    condition_type: str,
) -> float:
    """Compute probability from NBM native quantiles using linear interpolation.

    quantiles: {10: T10, 25: T25, 50: T50, 75: T75, 90: T90} in °F
    condition_type: 'above', 'below', or 'between'
    threshold: °F threshold (for 'above'/'below') or ignored for 'between'

    Uses the NBM quantiles as an ECDF and interpolates linearly between known points.
    """
    # Build ECDF: list of (temperature, cumulative_probability)
    q_map = {10: 0.10, 25: 0.25, 50: 0.50, 75: 0.75, 90: 0.90}
    points = sorted((temp, prob) for pct, temp in quantiles.items() if pct in q_map
                    for prob in [q_map[pct]])

    if not points:
        return 0.5

    temps_sorted = [p[0] for p in points]
    probs_sorted = [p[1] for p in points]

    def _cdf(t: float) -> float:
        """P(T <= t) from the ECDF with linear extrapolation at the tails."""
        if t <= temps_sorted[0]:
            return probs_sorted[0] * max(0.0, 1.0 - (temps_sorted[0] - t) / 10.0)
        if t >= temps_sorted[-1]:
            return 1.0 - (1.0 - probs_sorted[-1]) * max(0.0, 1.0 - (t - temps_sorted[-1]) / 10.0)
        for i in range(len(temps_sorted) - 1):
            if temps_sorted[i] <= t <= temps_sorted[i + 1]:
                frac = (t - temps_sorted[i]) / (temps_sorted[i + 1] - temps_sorted[i])
                return probs_sorted[i] + frac * (probs_sorted[i + 1] - probs_sorted[i])
        return 0.5

    if condition_type == "above":
        return float(1.0 - _cdf(threshold))
    elif condition_type == "below":
        return float(_cdf(threshold))
    else:
        # between: not applicable without two thresholds; fall back to 0.5
        return 0.5
```

- [ ] **Step 3: Run the test**

```
pytest tests/test_nbm.py::test_nws_prob_uses_quantiles_when_available -v
```
Expected: PASS

- [ ] **Step 4: Commit**

```
git add nws.py tests/test_nbm.py
git commit -m "feat(nws): add nws_prob_from_quantiles using NBM native ECDF"
```

*Note: Wiring this into the live `nws_prob()` call requires verifying that the NBM API endpoint actually returns quantile fields for all cities. This is a second follow-up commit after validating the API response format.*

---

## A4: HRRR Model for Same-Day Markets

**Problem:** Same-day markets use the same ensemble (ICON/GFS/ECMWF initialized at 00Z or 12Z). By 10 AM local time the HRRR has already run at 06Z, 09Z, 12Z with 3km resolution. Open-Meteo provides HRRR data via `model=best_match` for hourly variables.

**Files:**
- Modify: `weather_markets.py` (add `_fetch_hrrr_temp()`, wire into same-day path)
- Test: `tests/test_forecasting.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_forecasting.py — add
def test_fetch_hrrr_temp_returns_float_or_none(monkeypatch):
    from weather_markets import _fetch_hrrr_temp
    from datetime import date, timedelta

    # Patch requests.get to return a mock HRRR response
    import requests
    class MockResp:
        status_code = 200
        def raise_for_status(self): pass
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
```

- [ ] **Step 2: Add `_fetch_hrrr_temp()` to `weather_markets.py`**

```python
_HRRR_CACHE: dict[str, float] = {}

def _fetch_hrrr_temp(city: str, target_date, var: str = "max") -> float | None:
    """Fetch HRRR-derived hourly temperature and return daily max or min.

    Uses Open-Meteo's hourly endpoint with model=best_match (HRRR for CONUS).
    Returns daily max when var='max', daily min when var='min'.
    Returns None if HRRR data is unavailable or city is not in CONUS.
    Only used for same-day markets (days_out == 0).
    """
    import requests as _req
    from datetime import date as _date

    cache_key = f"{city}_{target_date.isoformat()}_{var}"
    if cache_key in _HRRR_CACHE:
        return _HRRR_CACHE[cache_key]

    city_info = _CITY_COORDS.get(city.upper())
    if not city_info:
        return None

    lat, lon = city_info["lat"], city_info["lon"]
    tz = city_info.get("timezone", "America/New_York")
    date_str = target_date.isoformat()

    try:
        resp = _req.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m",
                "temperature_unit": "fahrenheit",
                "timezone": tz,
                "start_date": date_str,
                "end_date": date_str,
                "models": "best_match",  # HRRR for CONUS
                "forecast_days": 1,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        temps = data.get("hourly", {}).get("temperature_2m", [])
        if not temps:
            return None
        result = max(temps) if var == "max" else min(temps)
        _HRRR_CACHE[cache_key] = float(result)
        return float(result)
    except Exception as exc:
        _log.debug("_fetch_hrrr_temp: %s %s failed: %s", city, date_str, exc)
        return None
```

- [ ] **Step 3: Wire HRRR into the same-day path**

In `analyze_trade`, in the same-day (METAR lock-in) section, after `forecast_temp` is set from the ensemble, add:

```python
if days_out == 0:
    _hrrr_temp = _fetch_hrrr_temp(city, target_date, var=var)
    if _hrrr_temp is not None:
        # Blend HRRR (70%) with ensemble (30%) for same-day forecasts
        forecast_temp = 0.70 * _hrrr_temp + 0.30 * forecast_temp
        _log.debug("same-day HRRR blend: hrrr=%.1f ens=%.1f → %.1f", _hrrr_temp, forecast_temp, forecast_temp)
```

- [ ] **Step 4: Commit**

```
git add weather_markets.py tests/test_forecasting.py
git commit -m "feat(hrrr): integrate HRRR hourly forecasts for same-day markets (blended 70/30)"
```

---

## A5: Dynamic Model Weights from `ensemble_member_scores`

**Problem:** `_model_weights()` in `weather_markets.py` uses static weights for ICON, GFS, NAM, ECMWF. The `ensemble_member_scores` table in `predictions.db` already tracks per-model Brier scores over time. If GFS has been outperforming ICON for 30 days in Chicago above-markets, GFS should get more weight.

**Files:**
- Modify: `tracker.py` — add `get_model_brier_scores(city, condition_type, days=30)`
- Modify: `weather_markets.py` — modify `_model_weights()` to use dynamic weights when data available
- Test: `tests/test_forecasting.py`

- [ ] **Step 1: Write test for `get_model_brier_scores`**

```python
def test_get_model_brier_scores_returns_dict(monkeypatch, tmp_path):
    import tracker
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "test.db")
    tracker._db_initialized = False
    tracker.init_db()

    # ensemble_member_scores columns: city, model, predicted_temp, actual_temp, target_date, logged_at
    # HAVING COUNT(*) >= 10 requires at least 10 rows per model — insert exactly 10
    with tracker._conn() as con:
        for i in range(10):
            con.execute(
                "INSERT INTO ensemble_member_scores (city, model, predicted_temp, actual_temp, logged_at) "
                "VALUES ('NYC', 'icon', ?, 73.0, datetime('now'))",
                (71.0 + i * 0.1,),
            )
            con.execute(
                "INSERT INTO ensemble_member_scores (city, model, predicted_temp, actual_temp, logged_at) "
                "VALUES ('NYC', 'gfs', ?, 73.0, datetime('now'))",
                (72.5 + i * 0.1,),
            )

    scores = tracker.get_model_brier_scores(days=30)
    assert "icon" in scores, f"Expected 'icon' key in scores, got: {scores}"
    assert "gfs" in scores, f"Expected 'gfs' key in scores, got: {scores}"
    # icon MAE: avg(|71.0+i*0.1 - 73.0|) for i in 0..9 = avg(2.0,1.9,...,1.1) = 1.55
    assert 1.0 < scores["icon"] < 3.0, f"Unexpected icon MAE: {scores['icon']}"
```

- [ ] **Step 2: Add `get_model_brier_scores()` to `tracker.py`**

```python
def get_model_brier_scores(days: int = 30) -> dict[str, float]:
    """Return per-model mean absolute error from ensemble_member_scores over last N days.

    Returns {model_name: mean_abs_error} for models with at least 10 rows.
    Lower MAE = better model.
    """
    init_db()
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT model,
                   AVG(ABS(predicted_temp - actual_temp)) as mae,
                   COUNT(*) as n
            FROM   ensemble_member_scores
            WHERE  logged_at >= ?
              AND  actual_temp IS NOT NULL
              AND  predicted_temp IS NOT NULL
            GROUP  BY model
            HAVING COUNT(*) >= 10
            """,
            (cutoff,),
        ).fetchall()
    return {r[0]: float(r[1]) for r in rows}
```

- [ ] **Step 3: Commit**

```
git add tracker.py tests/test_forecasting.py
git commit -m "feat(ensemble): add get_model_brier_scores for dynamic weight support"
```

---

## A6: Dew Point Coastal Correction

**Problem:** Miami, Houston, and San Francisco have METAR stations (KMIA, KHOU, KSFO) at airports where dew point depression (T - Td) is near zero on humid days, suppressing afternoon high temperatures by 3–7°F vs dry-air days. Dew point is already fetched via METAR but never used.

**Files:**
- Modify: `metar.py` — ensure `dew_point_f` is in the returned observation dict
- Modify: `weather_markets.py` — add `_dew_point_temp_correction(city, dew_point_f, temp_f)`, apply before edge calc
- Test: `tests/test_metar.py`

- [ ] **Step 1: Write failing test**

```python
def test_dew_point_temp_correction_miami():
    from weather_markets import _dew_point_temp_correction

    # Miami: dew point 76°F, forecast high 90°F → should apply negative correction
    correction = _dew_point_temp_correction("Miami", dew_point_f=76.0, forecast_temp_f=90.0)
    # Dew point depression = 90 - 76 = 14°F; below 20°F means humid suppression
    assert correction < 0.0, "Humid day should produce negative temperature correction"
    assert correction >= -5.0, "Correction should be bounded"

def test_dew_point_temp_correction_dry_city_no_effect():
    from weather_markets import _dew_point_temp_correction

    # Denver: dew point 40°F, forecast 85°F → dry air, no coastal suppression
    correction = _dew_point_temp_correction("Denver", dew_point_f=40.0, forecast_temp_f=85.0)
    assert correction == 0.0
```

- [ ] **Step 2: Add `_dew_point_temp_correction()` to `weather_markets.py`**

```python
# Cities where dew point suppresses max temperature near the airport
_DEW_POINT_SENSITIVE_CITIES = {"Miami", "Houston", "SanFrancisco", "Seattle"}

def _dew_point_temp_correction(city: str, dew_point_f: float, forecast_temp_f: float) -> float:
    """Return a bias correction (°F, negative = cooler) based on dew point depression.

    On humid days (dew point depression < 20°F), sea breeze and evaporative cooling
    suppress afternoon high temperatures at airport stations relative to model forecasts.
    Effect is strongest in Miami and Houston, moderate in SF and Seattle.
    """
    if city not in _DEW_POINT_SENSITIVE_CITIES:
        return 0.0

    depression = forecast_temp_f - dew_point_f  # 0°F = saturated; 40°F = very dry
    if depression >= 20.0:
        return 0.0  # Dry enough; no correction needed

    # Linear correction: 0°F depression → −3°F; 20°F depression → 0°F
    max_correction = -3.0
    correction = max_correction * (1.0 - depression / 20.0)
    return round(max(-5.0, correction), 2)  # clamp to avoid extreme corrections
```

- [ ] **Step 3: Wire into `analyze_trade`**

After `forecast_temp = forecast_temp - _get_combined_station_bias(city, var=var)`, add:

```python
# Coastal dew point correction — suppresses forecast_temp on humid days
_dew_obs = _get_latest_metar(city)  # returns dict with 'dew_point_f' if available
if _dew_obs and _dew_obs.get("dew_point_f") is not None:
    _dp_correction = _dew_point_temp_correction(city, _dew_obs["dew_point_f"], forecast_temp)
    if _dp_correction != 0.0:
        _log.debug("dew point correction for %s: %.2f°F (dew=%.1f forecast=%.1f)",
                   city, _dp_correction, _dew_obs["dew_point_f"], forecast_temp)
        forecast_temp += _dp_correction
```

- [ ] **Step 4: Commit**

```
git add weather_markets.py metar.py tests/test_metar.py
git commit -m "feat(metar): add dew point coastal temperature correction for Miami/Houston/SF/Seattle"
```

---

## A7: True Point-in-Time Backtest

**Problem:** `backtest.py` simulates "ensemble" by fetching ±5 days of historical archive data and constructing a spread. This is not what ICON/GFS actually forecasted on that date. The Previous Runs API (already used for EMOS backfill) returns actual model output from specific initialization times.

**Files:**
- Modify: `backtest.py` — add `fetch_previous_run_ensemble(city, target_date, days_out)` using Previous Runs API
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write the test**

```python
def test_fetch_previous_run_ensemble_returns_list(monkeypatch):
    """Previous Runs API call must return a list of floats (actual past ensemble members)."""
    from backtest import fetch_previous_run_ensemble
    from datetime import date

    import requests
    class MockResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {
                "daily": {
                    "time": ["2026-06-20"],
                    "temperature_2m_max_previous_day1_icon_seamless": [88.5],
                    "temperature_2m_max_previous_day1_gfs_seamless": [89.2],
                }
            }
    monkeypatch.setattr(requests, "get", lambda *a, **k: MockResp())

    temps = fetch_previous_run_ensemble("NYC", date(2026, 6, 20), days_out=1, var="max")
    assert isinstance(temps, list)
    assert all(isinstance(t, float) for t in temps)
```

- [ ] **Step 2: Add `fetch_previous_run_ensemble()` to `backtest.py`**

```python
_PREV_RUN_MODELS = ["icon_seamless", "gfs_seamless", "ecmwf_aifs025_single"]

def fetch_previous_run_ensemble(
    city: str,
    target_date,
    days_out: int,
    var: str = "max",
) -> list[float]:
    """Fetch actual model output at the time of forecast using the Previous Runs API.

    Returns temperatures as a list (one per model). Empty list if unavailable.
    This gives a true point-in-time ensemble, unlike the archive ±5-day spread.
    """
    from weather_markets import _CITY_COORDS
    import requests

    city_info = _CITY_COORDS.get(city.upper())
    if not city_info:
        return []

    lat, lon = city_info["lat"], city_info["lon"]
    tz = city_info.get("timezone", "America/New_York")
    daily_var_suffix = "max" if var == "max" else "min"

    daily_vars = [
        f"temperature_2m_{daily_var_suffix}_previous_day{days_out}_{m}"
        for m in _PREV_RUN_MODELS
    ]

    try:
        resp = requests.get(
            "https://previous-runs-api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": ",".join(daily_vars),
                "temperature_unit": "fahrenheit",
                "timezone": tz,
                "past_days": max(41, days_out + 2),
                "forecast_days": 0,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("daily", {})
        times = data.get("time", [])
        target_str = target_date.isoformat()
        if target_str not in times:
            return []
        idx = times.index(target_str)
        temps = []
        for v in daily_vars:
            val = data.get(v, [None])[idx] if idx < len(data.get(v, [])) else None
            if val is not None:
                temps.append(float(val))
        return temps
    except Exception as exc:
        _log.debug("fetch_previous_run_ensemble: %s %s failed: %s", city, target_date, exc)
        return []
```

- [ ] **Step 3: Add a `--previous-runs` flag to `cmd_backtest` in `main.py`**

`cmd_backtest` uses a simple list-based arg parser (no argparse). Find the flag-parsing loop in `cmd_backtest` (around line 5464) and add `--previous-runs` detection:

```python
def cmd_backtest(client: KalshiClient, args: list):
    """
    Run a backtest on finalized Kalshi markets.
    Usage: py main.py backtest [city] [--days N] [--previous-runs]
    """
    from backtest import run_backtest

    city_filter = None
    days_back = 90
    use_previous_runs = False       # ← new flag
    for i, a in enumerate(args):
        if a == "--days" and i + 1 < len(args):
            try:
                days_back = int(args[i + 1])
            except ValueError:
                pass
        elif a == "--previous-runs":   # ← new flag check
            use_previous_runs = True
        elif not a.startswith("--"):
            city_filter = a
    # ... rest of existing setup (progress bar, etc.) ...
    summary = run_backtest(
        client,
        city_filter=city_filter,
        days_back=days_back,
        use_previous_runs=use_previous_runs,   # ← pass through
        on_progress=_bt_progress,
    )
```

Then in `run_backtest` (in `backtest.py`), accept `use_previous_runs: bool = False` and swap the ensemble fetch when it is `True`:

```python
def run_backtest(client, city_filter=None, days_back=90,
                 use_previous_runs: bool = False, on_progress=None, verbose=True):
    # ... existing setup ...
    for i, market in enumerate(markets):
        city = market.get("city")
        target_date = market.get("market_date")
        if use_previous_runs:
            temps = fetch_previous_run_ensemble(city, target_date, days_out=1)
        else:
            temps = fetch_archive_temps(city, target_date)
        # ... rest of loop ...
```

- [ ] **Step 4: Commit**

```
git add backtest.py main.py tests/test_backtest.py
git commit -m "feat(backtest): add true point-in-time ensemble via Previous Runs API (--previous-runs flag)"
```

---

## A9: Per-Regime Blend Weight Selection

*Lower priority — implement after EMOS is live and has 30+ settled trades.*

**Goal:** When `regime.py` detects `heat_dome` or `cold_snap`, automatically increase ECMWF-AIFS weight (better at extremes) and decrease climatology weight. When `volatile`, increase NWS weight.

**Files:** `weather_markets.py` (regime-adjusted blend before condition/seasonal lookup)

*Defer to post-graduation; document the regime→weight mapping here when implementing:*
- heat_dome: ens=0.70/nws=0.25/clim=0.05
- cold_snap: ens=0.70/nws=0.25/clim=0.05
- blocking_high: ens=0.65/nws=0.30/clim=0.05
- volatile: ens=0.30/nws=0.60/clim=0.10
- normal: use existing seasonal/condition weights

---

## A10: Second-Order Climate Indices (PDO, PNA)

*Lowest priority — implement only after per-city Brier shows regional patterns.*

**Goal:** Add Pacific Decadal Oscillation (PDO) and Pacific-North American pattern (PNA) indices to `climate_indices.py`. PDO affects west coast temperatures; PNA affects central/eastern US. NOAA publishes both indices at `https://www.ncdc.noaa.gov/teleconnections/`.

*No immediate implementation plan — revisit when west coast city performance lags east coast.*
