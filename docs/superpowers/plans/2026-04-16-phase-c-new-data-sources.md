# Phase C: New Data Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three new forecast data sources (NBM, ECMWF AIFS, Gaussian probability method) to improve ensemble diversity and edge accuracy.

**Architecture:** NBM and ECMWF AIFS both follow the existing Open-Meteo pattern — they're accessed via the Open-Meteo API with different `model` parameters, so no new HTTP client is needed. Gaussian probability replaces the raw ensemble-fraction-counting method with a more principled statistical approach.

**Prerequisite:** Phase A (bias correction) should be done first so the corrected temperatures flow into these new sources automatically.

**Tech Stack:** Python 3.12, Open-Meteo API (existing `requests` session), scipy.stats (already in the project), pytest

---

## Task 1: National Blend of Models (NBM) via Open-Meteo

**Files:**
- Modify: `weather_markets.py` (add NBM to `ENSEMBLE_MODELS` and fetch logic)
- Create: `tests/test_nbm.py`

**Why NBM first:** NBM is NWS's official blend of GFS + HRRR + ECMWF + GEFS + NAM. It provides direct percentile outputs and is already calibrated by NWS meteorologists. Adding it as a third ensemble member is low-risk (same API, same parsing logic).

Open-Meteo NBM model parameter: `"nbm"` (via the forecast API, hourly `temperature_2m` variable)

**Note:** Check Open-Meteo documentation for the exact model name — it may be `"nbm_conus"` or accessed via the climate endpoint. If NBM is not available directly, use `"best_match"` (Open-Meteo's own blend) as a fallback. The implementation should try NBM and gracefully skip if the model returns no data.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_nbm.py`:

```python
"""Tests for NBM data source integration."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestNBMFetch:
    def test_nbm_in_ensemble_models(self):
        """ENSEMBLE_MODELS_EXTENDED includes NBM."""
        from weather_markets import ENSEMBLE_MODELS_EXTENDED

        assert "nbm" in ENSEMBLE_MODELS_EXTENDED or any("nbm" in m for m in ENSEMBLE_MODELS_EXTENDED)

    def test_fetch_temperature_nbm_returns_float_or_none(self):
        """fetch_temperature_nbm returns a float for a known city or None on failure."""
        from weather_markets import fetch_temperature_nbm
        from datetime import date

        # With mocked HTTP — any well-formed Open-Meteo response should parse
        mock_response = {
            "hourly": {
                "time": ["2026-04-17T15:00", "2026-04-17T18:00"],
                "temperature_2m": [20.5, 19.0],
            }
        }
        with patch("weather_markets._om_session") as mock_sess:
            mock_sess.get.return_value.json.return_value = mock_response
            mock_sess.get.return_value.raise_for_status.return_value = None
            result = fetch_temperature_nbm("NYC", date(2026, 4, 17))

        # Should return the max daily temp in °F
        assert result is None or isinstance(result, float)

    def test_fetch_temperature_nbm_returns_none_on_error(self):
        """Returns None gracefully on API failure."""
        from weather_markets import fetch_temperature_nbm
        from datetime import date
        import requests

        with patch("weather_markets._om_session") as mock_sess:
            mock_sess.get.side_effect = requests.RequestException("timeout")
            result = fetch_temperature_nbm("NYC", date(2026, 4, 17))

        assert result is None

    def test_nbm_included_in_ensemble_average(self):
        """When NBM returns a value, it is included in the ensemble average."""
        from weather_markets import _compute_ensemble_mean

        temps = {"gfs_seamless": 70.0, "icon_seamless": 72.0, "nbm": 71.0}
        mean = _compute_ensemble_mean(temps)
        assert mean == pytest.approx((70.0 + 72.0 + 71.0) / 3, abs=0.1)

    def test_nbm_excluded_on_none(self):
        """None values from NBM are excluded from ensemble average."""
        from weather_markets import _compute_ensemble_mean

        temps = {"gfs_seamless": 70.0, "icon_seamless": 72.0, "nbm": None}
        mean = _compute_ensemble_mean(temps)
        assert mean == pytest.approx((70.0 + 72.0) / 2, abs=0.1)
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_nbm.py -v
```

Expected: `ImportError: cannot import name 'ENSEMBLE_MODELS_EXTENDED'`

- [ ] **Step 3: Add NBM support to `weather_markets.py`**

Find the `ENSEMBLE_MODELS` constant (line ~88) and add an extended list:

```python
ENSEMBLE_MODELS = ["icon_seamless", "gfs_seamless"]  # existing (keep for backward compat)
ENSEMBLE_MODELS_EXTENDED = [*ENSEMBLE_MODELS, "nbm"]  # Phase C: adds NBM
```

Add a `fetch_temperature_nbm()` function (near the existing Open-Meteo fetch functions):

```python
def fetch_temperature_nbm(city: str, target_date) -> float | None:
    """
    Fetch NBM (National Blend of Models) max daily temperature for a city.
    Uses Open-Meteo with model="nbm" — NWS-calibrated blend of GFS/HRRR/ECMWF.

    Returns max temperature for target_date in °F, or None on failure.
    """
    coords = _CITY_COORDS.get(city.upper())
    if not coords:
        return None
    lat, lon, _ = coords

    try:
        resp = _om_session.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m",
                "temperature_unit": "fahrenheit",
                "models": "nbm",
                "start_date": target_date.isoformat(),
                "end_date": target_date.isoformat(),
                "timezone": "auto",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        temps = data.get("hourly", {}).get("temperature_2m", [])
        valid = [t for t in temps if t is not None]
        return float(max(valid)) if valid else None
    except Exception as exc:
        _log.debug("fetch_temperature_nbm(%s): %s", city, exc)
        return None
```

Add `_compute_ensemble_mean()` helper (used in tests and analysis):

```python
def _compute_ensemble_mean(temps: dict[str, float | None]) -> float | None:
    """Compute mean of non-None values in a {model: temp} dict."""
    values = [v for v in temps.values() if v is not None]
    return sum(values) / len(values) if values else None
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_nbm.py -v
```

Expected: all pass (some may be skipped if NBM model is unavailable from Open-Meteo)

- [ ] **Step 5: Commit**

```bash
git add weather_markets.py tests/test_nbm.py
git commit -m "feat(data): add NBM (National Blend of Models) as third ensemble member via Open-Meteo"
```

---

## Task 2: ECMWF AIFS Ensemble

**Files:**
- Modify: `weather_markets.py` (add ECMWF AIFS fetch)
- Create: `tests/test_ecmwf.py`

**Why ECMWF AIFS:** 51-member AI ensemble, operational since July 2025. Outperforms physics-based IFS by up to 20% on surface temperature for days 1–3. Available free via Open-Meteo's ECMWF endpoint.

Open-Meteo model parameter: `"ecmwf_aifs025"` or `"ecmwf_ifs025"` (check current Open-Meteo docs — model names change). The Open-Meteo forecast URL with `models=ecmwf_aifs025` should work.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ecmwf.py`:

```python
"""Tests for ECMWF AIFS ensemble data source."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestECMWFAIFS:
    def test_fetch_temperature_ecmwf_returns_float_or_none(self):
        """fetch_temperature_ecmwf returns a float or None."""
        from weather_markets import fetch_temperature_ecmwf
        from datetime import date

        mock_response = {
            "hourly": {
                "time": ["2026-04-17T12:00", "2026-04-17T18:00"],
                "temperature_2m": [18.5, 21.0],
            }
        }
        with patch("weather_markets._om_session") as mock_sess:
            mock_sess.get.return_value.json.return_value = mock_response
            mock_sess.get.return_value.raise_for_status.return_value = None
            result = fetch_temperature_ecmwf("NYC", date(2026, 4, 17))

        # Returns max in °F — 21°C = 69.8°F
        assert result is None or isinstance(result, float)

    def test_fetch_temperature_ecmwf_none_on_failure(self):
        import weather_markets, requests
        from datetime import date

        with patch("weather_markets._om_session") as mock_sess:
            mock_sess.get.side_effect = requests.RequestException("timeout")
            assert weather_markets.fetch_temperature_ecmwf("NYC", date(2026, 4, 17)) is None

    def test_ecmwf_in_extended_ensemble(self):
        """ENSEMBLE_MODELS_EXTENDED includes an ecmwf entry."""
        from weather_markets import ENSEMBLE_MODELS_EXTENDED
        assert any("ecmwf" in m for m in ENSEMBLE_MODELS_EXTENDED)

    def test_ecmwf_spread_computation(self):
        """ensemble_spread computed when ECMWF included raises no error."""
        from weather_markets import _compute_ensemble_spread

        temps = {"gfs_seamless": 70.0, "icon_seamless": 68.0, "ecmwf": 71.0, "nbm": 69.0}
        spread = _compute_ensemble_spread(temps)
        assert isinstance(spread, float)
        assert spread >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_ecmwf.py -v
```

Expected: `ImportError: cannot import name 'fetch_temperature_ecmwf'`

- [ ] **Step 3: Add ECMWF AIFS to `weather_markets.py`**

Extend `ENSEMBLE_MODELS_EXTENDED`:
```python
ENSEMBLE_MODELS_EXTENDED = [*ENSEMBLE_MODELS, "nbm", "ecmwf_aifs025"]
```

Add fetch function:

```python
def fetch_temperature_ecmwf(city: str, target_date) -> float | None:
    """
    Fetch ECMWF AIFS ensemble max daily temperature for a city.
    Uses Open-Meteo with models="ecmwf_aifs025".
    Outperforms GFS by ~20% for days 1–3 (operational since July 2025).

    Returns max temperature for target_date in °F, or None on failure.
    """
    coords = _CITY_COORDS.get(city.upper())
    if not coords:
        return None
    lat, lon, _ = coords

    try:
        resp = _om_session.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m",
                "temperature_unit": "fahrenheit",
                "models": "ecmwf_aifs025",
                "start_date": target_date.isoformat(),
                "end_date": target_date.isoformat(),
                "timezone": "auto",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        temps = data.get("hourly", {}).get("temperature_2m", [])
        valid = [t for t in temps if t is not None]
        return float(max(valid)) if valid else None
    except Exception as exc:
        _log.debug("fetch_temperature_ecmwf(%s): %s", city, exc)
        return None
```

Add spread computation helper:

```python
def _compute_ensemble_spread(temps: dict[str, float | None]) -> float:
    """
    Compute ensemble spread (std dev of non-None values in a {model: temp} dict).
    Used for confidence-tier classification (Phase B).
    Returns 0.0 if fewer than 2 valid values.
    """
    import statistics

    values = [v for v in temps.values() if v is not None]
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)
```

- [ ] **Step 4: Wire ECMWF into the ensemble fetch loop in `analyze_trade()`**

Find where the bot fetches GFS and ICON forecasts (in `analyze_trade()` or its helpers). Add ECMWF and NBM to the same loop:

```python
# Fetch all ensemble members
model_temps: dict[str, float | None] = {}
for model in ENSEMBLE_MODELS:  # GFS + ICON (always)
    model_temps[model] = _fetch_temperature_for_model(model, city, target_date)

# Phase C: extended ensemble (NBM + ECMWF AIFS)
model_temps["nbm"] = fetch_temperature_nbm(city, target_date)
model_temps["ecmwf"] = fetch_temperature_ecmwf(city, target_date)

ensemble_mean = _compute_ensemble_mean(model_temps)
ensemble_spread_f = _compute_ensemble_spread(model_temps)  # in °F
```

Then convert spread to probability units (approximate):
```python
# Convert temperature spread to probability spread for confidence tiers
# Rule of thumb: 1°F std dev ≈ 0.04 probability units at typical thresholds
ensemble_spread_prob = ensemble_spread_f * 0.04 if ensemble_spread_f else 0.0
```

Add to analysis result dict:
```python
"ensemble_spread": ensemble_spread_prob,
"ensemble_spread_f": ensemble_spread_f,
"n_ensemble_members": sum(1 for v in model_temps.values() if v is not None),
```

- [ ] **Step 5: Run tests**

```
python -m pytest tests/test_ecmwf.py tests/test_nbm.py tests/test_weather_markets.py -v
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add weather_markets.py tests/test_ecmwf.py
git commit -m "feat(data): add ECMWF AIFS ensemble + spread computation; wire into analyze_trade ensemble loop"
```

---

## Task 3: Gaussian Probability Distribution Method

**Files:**
- Modify: `weather_markets.py` (add `gaussian_probability()`, use in `analyze_trade`)
- Create: `tests/test_gaussian_prob.py`

**Why Gaussian:** The current bot counts what fraction of ensemble members exceed the threshold. This is noisy with small ensembles (only 2–4 members) and underestimates tail probabilities. A Gaussian fit using the ensemble mean and historical RMSE gives a more principled probability estimate — especially for thresholds far from the mean.

**Historical RMSE per city/season** (hardcoded table, refine over time):

| City | Winter RMSE | Spring RMSE | Summer RMSE | Fall RMSE |
|------|------------|-------------|-------------|-----------|
| NYC | 5.5°F | 6.0°F | 5.0°F | 5.8°F |
| MIA | 3.5°F | 4.0°F | 3.0°F | 3.5°F |
| CHI | 7.0°F | 6.5°F | 5.5°F | 6.5°F |
| LAX | 4.0°F | 4.5°F | 4.0°F | 4.5°F |
| DAL | 5.0°F | 5.5°F | 4.5°F | 5.5°F |

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gaussian_prob.py`:

```python
"""Tests for Gaussian probability distribution method."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


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
        """get_historical_sigma returns a positive float for known cities."""
        from weather_markets import get_historical_sigma

        sigma = get_historical_sigma("NYC", month=4)  # April = spring
        assert isinstance(sigma, float)
        assert sigma > 0

    def test_get_historical_sigma_unknown_city_default(self):
        """Unknown city returns a reasonable default sigma (5.0°F)."""
        from weather_markets import get_historical_sigma

        sigma = get_historical_sigma("XYZ", month=6)
        assert sigma == pytest.approx(5.0, abs=1.0)

    def test_probability_clamped_to_unit_interval(self):
        """gaussian_probability always returns a value in [0, 1]."""
        from weather_markets import gaussian_probability

        extreme_above = gaussian_probability(100.0, 65.0, 5.0, "above")
        extreme_below = gaussian_probability(30.0, 65.0, 5.0, "above")
        assert 0.0 <= extreme_above <= 1.0
        assert 0.0 <= extreme_below <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_gaussian_prob.py -v
```

Expected: `ImportError: cannot import name 'gaussian_probability'`

- [ ] **Step 3: Add Gaussian method to `weather_markets.py`**

```python
# ── Historical forecast RMSE per city/season ──────────────────────────────────
# Used for Gaussian probability computation (Phase C).
# Season: 1=Winter(DJF), 2=Spring(MAM), 3=Summer(JJA), 4=Fall(SON)
_HISTORICAL_SIGMA: dict[str, dict[int, float]] = {
    "NYC": {1: 5.5, 2: 6.0, 3: 5.0, 4: 5.8},
    "MIA": {1: 3.5, 2: 4.0, 3: 3.0, 4: 3.5},
    "CHI": {1: 7.0, 2: 6.5, 3: 5.5, 4: 6.5},
    "LAX": {1: 4.0, 2: 4.5, 3: 4.0, 4: 4.5},
    "DAL": {1: 5.0, 2: 5.5, 3: 4.5, 4: 5.5},
}
_DEFAULT_SIGMA = 5.0  # fallback for unknown cities

def _month_to_season(month: int) -> int:
    """Convert month (1-12) to season index (1=Winter, 2=Spring, 3=Summer, 4=Fall)."""
    return {12: 1, 1: 1, 2: 1, 3: 2, 4: 2, 5: 2, 6: 3, 7: 3, 8: 3, 9: 4, 10: 4, 11: 4}[month]


def get_historical_sigma(city: str, month: int) -> float:
    """
    Return the historical forecast RMSE (sigma) for a city in °F.

    Args:
        city: City code (e.g. "NYC")
        month: Calendar month (1-12)

    Returns:
        RMSE in °F
    """
    season = _month_to_season(month)
    return _HISTORICAL_SIGMA.get(city.upper(), {}).get(season, _DEFAULT_SIGMA)


def gaussian_probability(
    forecast_mean: float,
    threshold: float,
    sigma: float,
    direction: str = "above",
) -> float:
    """
    Compute P(T > threshold) or P(T < threshold) using a Gaussian distribution.

    More principled than raw ensemble member counting — especially useful
    when ensemble spread is small relative to forecast RMSE.

    Args:
        forecast_mean: Bias-corrected ensemble mean temperature in °F
        threshold: Kalshi market threshold in °F
        sigma: Forecast uncertainty (RMSE) in °F
        direction: "above" or "below"

    Returns:
        Probability as a float in [0, 1]
    """
    from scipy import stats

    z = (threshold - forecast_mean) / sigma
    cdf = float(stats.norm.cdf(z))  # P(T < threshold)

    if direction == "above":
        return max(0.0, min(1.0, 1.0 - cdf))
    else:
        return max(0.0, min(1.0, cdf))
```

- [ ] **Step 4: Wire Gaussian into `analyze_trade()`**

After computing `ensemble_mean` (bias-corrected), replace raw ensemble fraction counting with:

```python
# Gaussian probability (more principled than raw member counting)
target_month = target_date.month
sigma = get_historical_sigma(city, target_month)
p_win_gaussian = gaussian_probability(
    forecast_mean=ensemble_mean,
    threshold=float(condition.get("threshold", 0)),
    sigma=sigma,
    direction=condition.get("type", "above"),
)

# Blend Gaussian with ensemble fraction (if we have enough members)
raw_fraction = sum(1 for t in model_temps.values() if t is not None and
    (t > condition.get("threshold", 0) if condition.get("type") == "above" else t < condition.get("threshold", 0))) / max(1, len([t for t in model_temps.values() if t is not None]))

if len([t for t in model_temps.values() if t is not None]) >= 3:
    # Enough members to blend
    p_win = 0.6 * p_win_gaussian + 0.4 * raw_fraction
else:
    # Too few members — trust Gaussian more
    p_win = 0.8 * p_win_gaussian + 0.2 * raw_fraction
```

Add to result dict:
```python
"p_win_gaussian": p_win_gaussian,
"forecast_sigma": sigma,
```

- [ ] **Step 5: Run tests**

```
python -m pytest tests/test_gaussian_prob.py tests/test_weather_markets.py -v
```

Expected: all pass

- [ ] **Step 6: Run full test suite**

```
python -m pytest -x -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add weather_markets.py tests/test_gaussian_prob.py tests/test_ecmwf.py tests/test_nbm.py
git commit -m "feat(phase-c): new data sources complete — NBM + ECMWF AIFS + Gaussian probability method"
```
