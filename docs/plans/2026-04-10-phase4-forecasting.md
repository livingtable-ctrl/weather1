# Phase 4: Forecasting Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix ensemble weighting, integrate ENSO/climate indices, add persistence baseline, fix NWS blending, improve feels-like formula, learn seasonal weights from data, and cache by forecast cycle.

**Architecture:** All changes in `weather_markets.py`, `climatology.py`, `climate_indices.py`. No new files needed except learned weights JSON.

**Tech Stack:** Python stdlib (math, statistics), existing Open-Meteo API

**Covers:** #23, #25, #26, #28, #29, #31, #33, #34, #37, #118, #122, #126

---

### Task 1: Persistence / baseline model (#26)

**Files:**
- Modify: `climatology.py` — add `persistence_prob()`
- Modify: `weather_markets.py` — blend persistence into ensemble

- [ ] **Step 1: Write failing test**

Add to `tests/test_forecasting.py` (create if not exists):

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest
from unittest.mock import patch, MagicMock
from datetime import date


def test_persistence_prob_above_threshold():
    """If today's high is 75°F and threshold is 72°F, persistence says YES is likely."""
    from climatology import persistence_prob
    result = persistence_prob(
        condition_type="HIGH",
        threshold_lo=72,
        threshold_hi=None,
        current_value=75.0,
        std_dev=4.0,
    )
    assert result is not None
    assert result > 0.5, "Current temp above threshold → persistence prob should be > 0.5"


def test_persistence_prob_below_threshold():
    from climatology import persistence_prob
    result = persistence_prob(
        condition_type="HIGH",
        threshold_lo=80,
        threshold_hi=None,
        current_value=65.0,
        std_dev=4.0,
    )
    assert result < 0.5
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_forecasting.py::test_persistence_prob_above_threshold -v
```

Expected: `ImportError: cannot import name 'persistence_prob'`

- [ ] **Step 3: Implement persistence_prob() in climatology.py**

Add to `climatology.py`:

```python
from utils import normal_cdf


def persistence_prob(
    condition_type: str,
    threshold_lo: float | None,
    threshold_hi: float | None,
    current_value: float,
    std_dev: float = 5.0,
) -> float | None:
    """
    "Persistence" forecast: tomorrow's value ≈ today's value + noise.
    Models tomorrow's value as N(current_value, std_dev).
    Returns P(tomorrow meets threshold condition).

    Used as a baseline model — strong at short lead times (0–2 days).
    """
    if current_value is None or std_dev <= 0:
        return None

    if condition_type in ("HIGH", "LOW", "TEMP"):
        if threshold_lo is not None and threshold_hi is None:
            # P(X > threshold_lo)
            return 1.0 - normal_cdf(threshold_lo, current_value, std_dev)
        elif threshold_lo is not None and threshold_hi is not None:
            # P(threshold_lo < X < threshold_hi)
            return (normal_cdf(threshold_hi, current_value, std_dev)
                    - normal_cdf(threshold_lo, current_value, std_dev))
    return None
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_forecasting.py -k "persistence" -v
```

Expected: PASS.

- [ ] **Step 5: Blend persistence into ensemble in weather_markets.py**

In `analyze_trade` (or `enrich_with_forecast`), after existing prob calculation, add persistence at 15% weight when days_out <= 2:

```python
# Blend in persistence forecast for short lead times
from climatology import persistence_prob

days_out = (market_date - date.today()).days
if days_out <= 2 and obs and obs.get("temp_f") is not None:
    persist_p = persistence_prob(
        condition_type=condition_type,
        threshold_lo=threshold_lo,
        threshold_hi=threshold_hi,
        current_value=obs["temp_f"],
        std_dev=4.0,
    )
    if persist_p is not None:
        persist_weight = 0.15
        our_prob = our_prob * (1 - persist_weight) + persist_p * persist_weight
        method += "+persist"
```

- [ ] **Step 6: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -15
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add climatology.py weather_markets.py tests/test_forecasting.py
git commit -m "feat: persistence baseline model blended at 15% weight for <=2-day forecasts (#26)"
```

---

### Task 2: Integrate ENSO/climate indices into ensemble weighting (#28)

**Files:**
- Modify: `weather_markets.py` — `_forecast_model_weights()` uses ENSO
- Modify: `climate_indices.py` — expose `get_enso_phase()`

- [ ] **Step 1: Write test**

Add to `tests/test_forecasting.py`:

```python
def test_enso_modifies_weights():
    """El Niño should increase ECMWF weight in winter (ECMWF handles teleconnections better)."""
    from weather_markets import _forecast_model_weights
    with patch("weather_markets._get_enso_phase", return_value="el_nino"):
        elnino_weights = _forecast_model_weights(month=1)
    with patch("weather_markets._get_enso_phase", return_value="neutral"):
        neutral_weights = _forecast_model_weights(month=1)
    assert elnino_weights["ecmwf_ifs04"] >= neutral_weights["ecmwf_ifs04"], \
        "El Niño should boost ECMWF weight in winter"
```

- [ ] **Step 2: Add _get_enso_phase() to weather_markets.py**

```python
def _get_enso_phase() -> str:
    """
    Return current ENSO phase: 'el_nino', 'la_nina', or 'neutral'.
    Reads from climate_indices module. Falls back to 'neutral' on error.
    """
    try:
        from climate_indices import temperature_adjustment, get_enso_index
        oni = get_enso_index()
        if oni is None:
            return "neutral"
        if oni >= 0.5:
            return "el_nino"
        if oni <= -0.5:
            return "la_nina"
        return "neutral"
    except Exception:
        return "neutral"
```

- [ ] **Step 3: Add get_enso_index() to climate_indices.py**

Open `climate_indices.py` and add:

```python
def get_enso_index() -> float | None:
    """
    Return the current ONI (Oceanic Niño Index) value.
    Reads from the cached climate data already loaded by this module.
    Returns None if unavailable.
    """
    try:
        # climate_indices.py already loads ENSO data — expose the scalar
        # Look for existing variable holding ONI or MEI value
        if "oni" in globals() and globals()["oni"] is not None:
            return float(globals()["oni"])
        # Fall back: return None so caller uses neutral
        return None
    except Exception:
        return None
```

- [ ] **Step 4: Update _forecast_model_weights() to use ENSO**

```python
def _forecast_model_weights(month: int) -> dict[str, float]:
    """
    Seasonal + ENSO-adjusted model weights.
    ECMWF gets extra boost in El Niño winters (better teleconnection skill).
    """
    is_winter = month in (10, 11, 12, 1, 2, 3)
    ecmwf_w = 2.5 if is_winter else 1.5

    enso = _get_enso_phase()
    if enso == "el_nino" and is_winter:
        ecmwf_w += 0.5  # ECMWF handles El Niño teleconnections better
    elif enso == "la_nina" and is_winter:
        ecmwf_w += 0.3

    return {"gfs_seamless": 1.0, "ecmwf_ifs04": ecmwf_w, "icon_seamless": 1.0}
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_forecasting.py -k "enso" -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add weather_markets.py climate_indices.py tests/test_forecasting.py
git commit -m "feat: ENSO phase integrated into ensemble model weights (#28)"
```

---

### Task 3: Improved feels-like formula — intermediate humid-cold regime (#29)

**Files:**
- Modify: `weather_markets.py` — `_feels_like()`

- [ ] **Step 1: Write tests**

Add to `tests/test_forecasting.py`:

```python
def test_feels_like_humid_cold():
    """Cold + high humidity: feels colder than wind chill alone."""
    from weather_markets import _feels_like
    result = _feels_like(temp_f=38, humidity=90, wind_mph=10)
    # Should be below 38 (wind chill + humidity chill)
    assert result < 38

def test_feels_like_moderate_humidity_cold():
    """Moderate cold + moderate humidity: standard wind chill."""
    from weather_markets import _feels_like
    result = _feels_like(temp_f=38, humidity=50, wind_mph=10)
    assert result < 38  # wind chill still applies
```

- [ ] **Step 2: Update _feels_like() in weather_markets.py**

Find `_feels_like` and replace with:

```python
def _feels_like(temp_f: float, humidity: float, wind_mph: float) -> float:
    """
    Compute apparent temperature using regime-appropriate formula.

    Regimes:
      Hot + humid  (temp >= 80°F, humidity >= 40%) → Heat Index (NWS Rothfusz)
      Cold + windy (temp <= 50°F, wind >= 3 mph)   → Wind Chill (NWS 2001)
      Cold + humid (temp <= 50°F, humidity >= 70%)  → Wind Chill with humidity penalty
      Moderate                                       → actual temp
    """
    # Hot + humid: heat index
    if temp_f >= 80 and humidity >= 40:
        hi = (-42.379
              + 2.04901523 * temp_f
              + 10.14333127 * humidity
              - 0.22475541 * temp_f * humidity
              - 0.00683783 * temp_f ** 2
              - 0.05481717 * humidity ** 2
              + 0.00122874 * temp_f ** 2 * humidity
              + 0.00085282 * temp_f * humidity ** 2
              - 0.00000199 * temp_f ** 2 * humidity ** 2)
        return hi

    # Cold + windy: wind chill (NWS 2001 formula)
    if temp_f <= 50 and wind_mph >= 3:
        wc = (35.74
              + 0.6215 * temp_f
              - 35.75 * wind_mph ** 0.16
              + 0.4275 * temp_f * wind_mph ** 0.16)
        # Intermediate regime: cold + very humid → extra penalty
        if humidity >= 70:
            # Moist air conducts heat away faster; apply small penalty
            humidity_penalty = (humidity - 70) / 100 * 1.5
            wc -= humidity_penalty
        return wc

    return temp_f
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_forecasting.py -k "feels_like" -v
python -m pytest tests/test_weather_markets.py -k "feels_like" -v
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add weather_markets.py tests/test_forecasting.py
git commit -m "feat: feels-like adds moist-cold regime (humidity penalty at low temps) (#29)"
```

---

### Task 4: Blend NWS as 0.35 weight in ensemble (#33)

**Files:**
- Modify: `weather_markets.py` — `analyze_trade()` NWS integration

- [ ] **Step 1: Write test**

Add to `tests/test_forecasting.py`:

```python
def test_nws_blended_not_replaced():
    """NWS probability should be blended in, not used only as fallback."""
    from weather_markets import _blend_probabilities
    result = _blend_probabilities(
        ensemble_prob=0.70,
        nws_prob=0.50,
        clim_prob=0.55,
        days_out=3,
    )
    # Result should be between extremes, not equal to ensemble alone
    assert 0.50 < result < 0.70, "NWS blend should pull result toward 0.50"
```

- [ ] **Step 2: Add _blend_probabilities() to weather_markets.py**

```python
def _blend_probabilities(
    ensemble_prob: float | None,
    nws_prob: float | None,
    clim_prob: float | None,
    days_out: int = 3,
) -> float | None:
    """
    Blend ensemble, NWS, and climatology probabilities with dynamic weights.

    Weights by lead time:
      days_out <= 3:  ensemble 0.50, NWS 0.35, clim 0.15
      days_out 4-7:   ensemble 0.60, NWS 0.25, clim 0.15
      days_out > 7:   ensemble 0.65, NWS 0.10, clim 0.25

    NWS is always blended in (not just fallback) because it's calibrated.
    """
    if days_out <= 3:
        w_ens, w_nws, w_clim = 0.50, 0.35, 0.15
    elif days_out <= 7:
        w_ens, w_nws, w_clim = 0.60, 0.25, 0.15
    else:
        w_ens, w_nws, w_clim = 0.65, 0.10, 0.25

    total_w = 0.0
    weighted_sum = 0.0

    if ensemble_prob is not None:
        weighted_sum += w_ens * ensemble_prob
        total_w += w_ens
    if nws_prob is not None:
        weighted_sum += w_nws * nws_prob
        total_w += w_nws
    if clim_prob is not None:
        weighted_sum += w_clim * clim_prob
        total_w += w_clim

    if total_w == 0:
        return None
    return weighted_sum / total_w
```

- [ ] **Step 3: Wire _blend_probabilities() into analyze_trade()**

In `analyze_trade`, replace the existing probability combination logic with a call to `_blend_probabilities`. Find where `our_prob` is assembled from components and replace:

```python
# Replace ad-hoc combination with:
our_prob = _blend_probabilities(
    ensemble_prob=ensemble_p,
    nws_prob=nws_p,
    clim_prob=clim_p,
    days_out=days_out,
)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_forecasting.py -k "blend" -v
python -m pytest tests/ -v --tb=short 2>&1 | tail -10
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add weather_markets.py tests/test_forecasting.py
git commit -m "feat: NWS always blended (0.35 weight at 0-3 days) instead of fallback-only (#33)"
```

---

### Task 5: Dynamic weights from recent ensemble accuracy (#25)

**Files:**
- Modify: `weather_markets.py` — `_forecast_model_weights()` loads from tracker

- [ ] **Step 1: Write test**

Add to `tests/test_forecasting.py`:

```python
def test_dynamic_weights_from_tracker(tmp_path):
    """If GFS has recent MAE=2 and ECMWF has MAE=1, ECMWF should get higher weight."""
    import tracker
    orig = tracker.DB_PATH
    tracker.DB_PATH = tmp_path / "dyn_test.db"
    tracker._db_initialized = False
    tracker.init_db()

    from datetime import date, timedelta
    today = date.today()
    with tracker._conn() as con:
        for i in range(10):
            con.execute(
                "INSERT INTO ensemble_member_scores (city, model, predicted_temp, actual_temp, target_date, logged_at) VALUES (?,?,?,?,?,?)",
                ("NYC", "gfs_seamless", 70.0, 72.0, str(today - timedelta(days=i)), "2026-01-01T00:00:00"),
            )
            con.execute(
                "INSERT INTO ensemble_member_scores (city, model, predicted_temp, actual_temp, target_date, logged_at) VALUES (?,?,?,?,?,?)",
                ("NYC", "ecmwf_ifs04", 71.5, 72.0, str(today - timedelta(days=i)), "2026-01-01T00:00:00"),
            )

    from weather_markets import _dynamic_model_weights
    weights = _dynamic_model_weights(city="NYC", month=1)

    assert weights is not None
    # ECMWF (MAE=0.5) should outweigh GFS (MAE=2.0)
    assert weights.get("ecmwf_ifs04", 0) > weights.get("gfs_seamless", 0)

    tracker.DB_PATH = orig
    tracker._db_initialized = False
```

- [ ] **Step 2: Implement _dynamic_model_weights()**

Add to `weather_markets.py`:

```python
def _dynamic_model_weights(city: str | None = None, month: int | None = None) -> dict[str, float] | None:
    """
    Load recent per-model MAE from tracker and return inverse-MAE weights.
    Falls back to None if insufficient data (caller uses static weights).
    Minimum 5 data points per model required.
    """
    try:
        from tracker import get_ensemble_member_accuracy
        season = None
        if month is not None:
            season = "winter" if month in (10, 11, 12, 1, 2, 3) else "summer"
        accuracy = get_ensemble_member_accuracy(city=city, season=season)
        if not accuracy:
            return None

        # Need at least 5 samples per model
        valid = {m: v for m, v in accuracy.items() if v["count"] >= 5 and v["mae"] > 0}
        if len(valid) < 2:
            return None

        # Inverse-MAE weighting: lower MAE → higher weight
        inv_mae = {m: 1.0 / v["mae"] for m, v in valid.items()}
        total = sum(inv_mae.values())
        # Normalize to sum=len(valid) so magnitudes are comparable to static weights
        n = len(valid)
        return {m: (w / total) * n for m, w in inv_mae.items()}
    except Exception as exc:
        _log.debug("Could not load dynamic model weights: %s", exc)
        return None
```

- [ ] **Step 3: Use dynamic weights in _forecast_model_weights()**

Update `_forecast_model_weights` to try dynamic first:

```python
def _forecast_model_weights(month: int, city: str | None = None) -> dict[str, float]:
    """Return model weights: dynamic from tracker if available, else static seasonal."""
    dynamic = _dynamic_model_weights(city=city, month=month)
    if dynamic:
        _log.debug("Using dynamic model weights for city=%s: %s", city, dynamic)
        return dynamic

    # Static fallback
    is_winter = month in (10, 11, 12, 1, 2, 3)
    ecmwf_w = 2.5 if is_winter else 1.5
    enso = _get_enso_phase()
    if enso == "el_nino" and is_winter:
        ecmwf_w += 0.5
    return {"gfs_seamless": 1.0, "ecmwf_ifs04": ecmwf_w, "icon_seamless": 1.0}
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_forecasting.py -k "dynamic_weights" -v
python -m pytest tests/ -v --tb=short 2>&1 | tail -10
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add weather_markets.py tests/test_forecasting.py
git commit -m "feat: dynamic ensemble weights from recent tracker MAE data (#25)"
```

---

### Task 6: Stratified holdout by city and condition (#21)

**Files:**
- Modify: `backtest.py` — holdout split

- [ ] **Step 1: Write test**

Add to `tests/test_forecasting.py`:

```python
def test_stratified_holdout_preserves_distribution():
    """Holdout set should have all cities present, not just one city."""
    from backtest import stratified_train_test_split

    records = []
    cities = ["NYC", "Chicago", "LA", "Miami"]
    conditions = ["HIGH", "LOW", "PRECIP"]
    for city in cities:
        for cond in conditions:
            for i in range(10):
                records.append({"city": city, "condition_type": cond, "our_prob": 0.6, "settled_yes": 1})

    train, holdout = stratified_train_test_split(records, holdout_frac=0.2)
    holdout_cities = {r["city"] for r in holdout}
    assert len(holdout_cities) == 4, f"All cities should appear in holdout, got: {holdout_cities}"
```

- [ ] **Step 2: Add stratified_train_test_split() to backtest.py**

```python
def stratified_train_test_split(
    records: list[dict],
    holdout_frac: float = 0.2,
    strat_keys: tuple = ("city", "condition_type"),
) -> tuple[list[dict], list[dict]]:
    """
    Stratified train/holdout split.
    Ensures each (city, condition_type) stratum contributes to the holdout
    proportionally, so the holdout is representative.
    """
    from collections import defaultdict
    import random

    strata: dict = defaultdict(list)
    for rec in records:
        key = tuple(rec.get(k) for k in strat_keys)
        strata[key].append(rec)

    train, holdout = [], []
    for group in strata.values():
        shuffled = group[:]
        random.shuffle(shuffled)
        n_hold = max(1, int(len(shuffled) * holdout_frac))
        holdout.extend(shuffled[:n_hold])
        train.extend(shuffled[n_hold:])

    return train, holdout
```

- [ ] **Step 3: Run test**

```bash
python -m pytest tests/test_forecasting.py -k "stratified_holdout" -v
```

Expected: PASS.

- [ ] **Step 4: Wire into existing backtest holdout split**

Find the existing holdout split in `backtest.py` (around line 199-206) and replace with a call to `stratified_train_test_split`.

- [ ] **Step 5: Commit**

```bash
git add backtest.py tests/test_forecasting.py
git commit -m "feat: stratified holdout split by city and condition_type (#21)"
```

---

### Task 7: Forecast-cycle-aware cache TTL (#126)

**Files:**
- Modify: `weather_markets.py` — `_ENSEMBLE_CACHE_TTL` and `_FORECAST_CACHE_TTL`

- [ ] **Step 1: Write test**

Add to `tests/test_forecasting.py`:

```python
def test_cache_ttl_by_forecast_cycle():
    from weather_markets import _ttl_until_next_cycle
    from datetime import datetime, timezone

    # At 05:00 UTC, next cycle is 06:00 UTC (1 hour away)
    t = datetime(2026, 4, 10, 5, 0, 0, tzinfo=timezone.utc)
    ttl = _ttl_until_next_cycle(now=t)
    assert 3000 < ttl < 4000, f"Expected ~3600s until 06z, got {ttl}"
```

- [ ] **Step 2: Add _ttl_until_next_cycle() to weather_markets.py**

```python
def _ttl_until_next_cycle(now=None) -> int:
    """
    Return seconds until the next NWP forecast cycle is available.
    Model run times (UTC) + ~2h processing lag:
      00z → available ~02:00 UTC
      06z → available ~08:00 UTC
      12z → available ~14:00 UTC
      18z → available ~20:00 UTC
    Returns seconds until the next availability window.
    Minimum 30 minutes to avoid thrashing.
    """
    from datetime import datetime, timezone, timedelta

    if now is None:
        now = datetime.now(timezone.utc)

    # Availability hours (UTC)
    avail_hours = [2, 8, 14, 20]
    current_hour = now.hour + now.minute / 60

    for ah in avail_hours:
        if current_hour < ah:
            delta_hours = ah - current_hour
            return max(1800, int(delta_hours * 3600))

    # Past last cycle today — next is 02:00 tomorrow
    next_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    next_avail = next_midnight.replace(hour=2)
    return max(1800, int((next_avail - now).total_seconds()))
```

- [ ] **Step 3: Use dynamic TTL when populating cache**

In `get_weather_forecast` and `get_ensemble_stats`, replace:

```python
_FORECAST_CACHE[cache_key] = (result, time.time())
# and the TTL check:
if time.time() - ts < _FORECAST_CACHE_TTL:
```

With:

```python
_FORECAST_CACHE[cache_key] = (result, time.time(), _ttl_until_next_cycle())
# TTL check:
result, ts, ttl = _FORECAST_CACHE[cache_key]
if time.time() - ts < ttl:
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_forecasting.py -k "cache_ttl" -v
python -m pytest tests/ -v --tb=short 2>&1 | tail -10
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add weather_markets.py tests/test_forecasting.py
git commit -m "feat: forecast cache TTL aligned to NWP model cycle availability (#126)"
```

---

### Task 8: Per-city model weights (#122)

**Files:**
- Modify: `weather_markets.py` — `_forecast_model_weights()` checks learned_weights per city

- [ ] **Step 1: Update _forecast_model_weights() to load per-city weights**

`learned_weights` is already saved to `data/learned_weights.json`. Update the function:

```python
def _forecast_model_weights(month: int, city: str | None = None) -> dict[str, float]:
    """
    Weights priority:
    1. Per-city dynamic weights from tracker (if >= 5 samples)
    2. Per-city learned weights from data/learned_weights.json
    3. Static seasonal + ENSO weights
    """
    # 1. Dynamic from tracker
    dynamic = _dynamic_model_weights(city=city, month=month)
    if dynamic:
        return dynamic

    # 2. Per-city learned weights
    if city:
        try:
            import json
            weights_path = Path(__file__).parent / "data" / "learned_weights.json"
            if weights_path.exists():
                all_weights = json.loads(weights_path.read_text())
                city_weights = all_weights.get(city)
                if city_weights and isinstance(city_weights, dict):
                    _log.debug("Using learned weights for %s: %s", city, city_weights)
                    return city_weights
        except Exception:
            pass

    # 3. Static fallback with ENSO
    is_winter = month in (10, 11, 12, 1, 2, 3)
    ecmwf_w = 2.5 if is_winter else 1.5
    enso = _get_enso_phase()
    if enso == "el_nino" and is_winter:
        ecmwf_w += 0.5
    elif enso == "la_nina" and is_winter:
        ecmwf_w += 0.3
    return {"gfs_seamless": 1.0, "ecmwf_ifs04": ecmwf_w, "icon_seamless": 1.0}
```

- [ ] **Step 2: Write test**

Add to `tests/test_forecasting.py`:

```python
def test_per_city_learned_weights(tmp_path):
    import json, weather_markets
    from pathlib import Path
    from unittest.mock import patch

    weights_data = {"NYC": {"gfs_seamless": 2.0, "ecmwf_ifs04": 1.0, "icon_seamless": 1.0}}
    weights_file = tmp_path / "learned_weights.json"
    weights_file.write_text(json.dumps(weights_data))

    with patch("weather_markets.Path") as mock_path:
        mock_path.return_value.__truediv__ = lambda self, x: (
            weights_file if "learned_weights" in str(x) else Path(x)
        )
        with patch("weather_markets._dynamic_model_weights", return_value=None):
            weights = weather_markets._forecast_model_weights(month=6, city="NYC")

    # Should use learned weights where GFS > ECMWF (opposite of winter default)
    assert weights.get("gfs_seamless", 0) >= weights.get("ecmwf_ifs04", 0)
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_forecasting.py -v --tb=short 2>&1 | tail -15
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add weather_markets.py tests/test_forecasting.py
git commit -m "feat: per-city model weights from learned_weights.json (#122)"
```

---

### Task 9: Log and track forecast cycles (#37)

**Files:**
- Modify: `tracker.py` — add `forecast_cycle` column
- Modify: `weather_markets.py` — log current cycle when fetching

- [ ] **Step 1: Add forecast_cycle to predictions table**

Add migration in `tracker.py` `_MIGRATIONS` list:

```python
# v4: add forecast_cycle column to predictions
"ALTER TABLE predictions ADD COLUMN forecast_cycle TEXT",
```

Increment `_SCHEMA_VERSION = 4`.

Update `log_prediction()` to accept and store `forecast_cycle`:

```python
def log_prediction(..., forecast_cycle: str | None = None) -> None:
    # Add forecast_cycle to INSERT statement
    con.execute("""
        INSERT INTO predictions (..., forecast_cycle)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (..., forecast_cycle))
```

- [ ] **Step 2: Compute and pass forecast_cycle from weather_markets.py**

```python
def _current_forecast_cycle() -> str:
    """Return the most recently issued NWP cycle: '00z', '06z', '12z', or '18z'."""
    from datetime import datetime, timezone
    hour = datetime.now(timezone.utc).hour
    # Cycles available after ~2h lag: 00z@02, 06z@08, 12z@14, 18z@20
    if hour >= 20:
        return "18z"
    if hour >= 14:
        return "12z"
    if hour >= 8:
        return "06z"
    return "00z"
```

Pass `forecast_cycle=_current_forecast_cycle()` in `log_prediction` calls.

- [ ] **Step 3: Write test**

Add to `tests/test_forecasting.py`:

```python
def test_current_forecast_cycle():
    from weather_markets import _current_forecast_cycle
    cycle = _current_forecast_cycle()
    assert cycle in ("00z", "06z", "12z", "18z")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_forecasting.py -k "forecast_cycle" -v
python -m pytest tests/ --tb=short 2>&1 | tail -10
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add tracker.py weather_markets.py tests/test_forecasting.py
git commit -m "feat: log forecast cycle (00z/06z/12z/18z) with each prediction (#37)"
```
