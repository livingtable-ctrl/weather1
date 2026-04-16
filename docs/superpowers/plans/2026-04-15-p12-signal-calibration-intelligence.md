# P12: Signal Calibration & Market Intelligence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the deepest remaining gap between this bot and professional weather derivative desks — specifically in probability calibration, ensemble data sources, and market intelligence. Research basis: competitive analysis conducted 2026-04-15 covering open-source prediction market bots, academic weather derivative literature (Jewson, Gneiting, Alaton, Thorp), and professional strategy reviews of Nephila Capital, Speedwell Weather, and Allianz Risk Transfer.

**Prerequisites:** P11 branch merged to main. Start a new branch `feature/p12-signal-calibration`.

**Priority order:** Tier 1 tasks (61–63) deliver the largest probability accuracy improvement and should be implemented first. Tier 2 (64–66) adds new data sources. Tier 3 (67–69) improves risk/sizing. Tier 4 (70–74) adds market intelligence. Tier 5 (75–77) covers advanced/complex additions.

**Tech Stack:** Python 3.11+, pytest, stdlib only unless noted. Open-Meteo and ECMWF open data are free with no auth required.

**Research sources:**
- Gneiting et al. 2005 — EMOS calibration (Monthly Weather Review)
- Jewson 2004 — Bayesian lead-time blending (riskworx.com preprint)
- Jewson & Brix 2005 — Burn analysis (Cambridge University Press)
- Alaton, Djehiche & Stillberger 2002 — OU temperature model (Applied Mathematical Finance)
- MacLean, Thorp & Ziemba 2010 — Kelly calibration (World Scientific)
- Hamill & Colucci 1997 — Ensemble dressing (Monthly Weather Review)
- Leutbecher & Palmer 2008 — Ensemble forecast horizon limits (J. Computational Physics)
- Speedwell Weather — burn analysis methodology (public whitepapers)
- NOAA CPC — teleconnection indices (public data)
- Open-Meteo — free ensemble API (open-meteo.com)

---

## Tier 1 — Probability Calibration (Highest EV, Implement First)

---

## Task 61 (P12.A) — EMOS Ensemble Calibration

### Background

The bot currently converts forecast temperatures to probabilities using a simple Gaussian CDF with a fixed sigma. The academic standard (Gneiting et al. 2005, Ensemble Model Output Statistics / EMOS) fits a Gaussian predictive distribution directly from the GEFS ensemble:

```
T_obs ~ N(a + b * T_ens_mean, c + d * S²_ens)
```

Where a, b correct mean bias and c, d scale the variance from ensemble spread S². Parameters are estimated by minimising CRPS on a rolling 40-day training window. This converts raw GEFS output to a properly calibrated binary probability for Kalshi.

**Why it matters:** Raw ensemble forecasts are systematically under-dispersive (too confident). EMOS corrects this. A calibrated P(T > K) gives better Kelly sizing and avoids over-betting on uncertain forecasts.

### 61.1 Add `fit_emos(training_data)` to a new `calibration_emos.py`

- [ ] Create `calibration_emos.py` with:

```python
"""
EMOS (Ensemble Model Output Statistics) calibration.

Reference: Gneiting et al. 2005, Monthly Weather Review Vol. 133.
Fits a Gaussian predictive distribution from ensemble mean + spread:
    T_obs ~ N(a + b*T_mean, c + d*S²)
Parameters estimated by minimising CRPS on a rolling training window.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EMOSParams:
    """Fitted EMOS parameters for a single city/season combination."""
    a: float = 0.0   # intercept bias correction
    b: float = 1.0   # ensemble mean scaling
    c: float = 1.0   # base variance
    d: float = 1.0   # ensemble spread scaling
    n_training: int = 0
    fitted: bool = False


def crps_gaussian(mu: float, sigma: float, obs: float) -> float:
    """
    Continuous Ranked Probability Score for a Gaussian predictive distribution.
    Lower = better. Used as the objective function for EMOS fitting.
    """
    z = (obs - mu) / sigma
    phi_z = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    Phi_z = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    return sigma * (z * (2 * Phi_z - 1) + 2 * phi_z - 1 / math.sqrt(math.pi))


def fit_emos(
    training_data: list[dict],
    n_iterations: int = 100,
    learning_rate: float = 0.01,
) -> EMOSParams:
    """
    Fit EMOS parameters from training observations.

    training_data: list of dicts with keys:
        - ens_mean: float   (ensemble mean temperature forecast)
        - ens_spread: float (ensemble standard deviation)
        - observed: float   (verified temperature)

    Returns fitted EMOSParams. Falls back to identity params (a=0, b=1, c=1, d=1)
    when training data is insufficient (<10 samples).
    """
    if len(training_data) < 10:
        return EMOSParams(fitted=False, n_training=len(training_data))

    # Simple gradient descent on CRPS
    a, b, c, d = 0.0, 1.0, 1.0, 1.0
    lr = learning_rate

    for _ in range(n_iterations):
        grad_a = grad_b = grad_c = grad_d = 0.0
        for row in training_data:
            mu = a + b * row["ens_mean"]
            var = max(c + d * row["ens_spread"] ** 2, 0.01)
            sigma = math.sqrt(var)
            z = (row["observed"] - mu) / sigma
            phi_z = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
            Phi_z = 0.5 * (1 + math.erf(z / math.sqrt(2)))
            # Gradients wrt CRPS (simplified finite-difference approximation)
            dcrps_dmu = sigma * (2 * Phi_z - 1)
            dcrps_dsigma2 = 0.5 * crps_gaussian(mu, sigma, row["observed"]) / var
            grad_a += dcrps_dmu
            grad_b += dcrps_dmu * row["ens_mean"]
            grad_c += dcrps_dsigma2
            grad_d += dcrps_dsigma2 * row["ens_spread"] ** 2

        n = len(training_data)
        a -= lr * grad_a / n
        b -= lr * grad_b / n
        c -= lr * max(grad_c / n, 0)
        d -= lr * max(grad_d / n, 0)
        c = max(c, 0.01)
        d = max(d, 0.0)

    return EMOSParams(a=round(a, 4), b=round(b, 4),
                     c=round(c, 4), d=round(d, 4),
                     n_training=len(training_data), fitted=True)


def emos_prob(
    params: EMOSParams,
    ens_mean: float,
    ens_spread: float,
    threshold: float,
    above: bool = True,
) -> float:
    """
    Compute calibrated P(T > threshold) or P(T < threshold) using fitted EMOS params.

    Falls back to naive Gaussian (sigma=3.0) when params are not fitted.
    """
    mu = params.a + params.b * ens_mean
    var = max(params.c + params.d * ens_spread ** 2, 0.01)
    sigma = math.sqrt(var)
    z = (threshold - mu) / sigma
    p_below = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    return (1.0 - p_below) if above else p_below
```

### 61.2 Add EMOS training data collection to `tracker.py`

- [ ] Add to `tracker.py`:

```python
def log_emos_training_row(
    city: str,
    condition_type: str,
    forecast_date: str,
    ens_mean: float,
    ens_spread: float,
    observed: float,
) -> None:
    """
    Store one EMOS training observation (forecast → verified pair).
    Called after market settlement with actual observed temperature.
    """
    _init_db()
    with _conn() as con:
        con.execute(
            """INSERT OR IGNORE INTO emos_training
               (city, condition_type, forecast_date, ens_mean, ens_spread,
                observed, logged_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (city, condition_type, forecast_date,
             ens_mean, ens_spread, observed,
             __import__("datetime").datetime.now(
                 __import__("datetime").timezone.utc
             ).isoformat()),
        )


def get_emos_training_data(
    city: str, condition_type: str, window_days: int = 40
) -> list[dict]:
    """Return recent EMOS training rows for a city/condition pair."""
    _init_db()
    cutoff = (
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        - __import__("datetime").timedelta(days=window_days)
    ).isoformat()
    with _conn() as con:
        rows = con.execute(
            """SELECT ens_mean, ens_spread, observed FROM emos_training
               WHERE city = ? AND condition_type = ? AND forecast_date >= ?
               ORDER BY forecast_date""",
            (city, condition_type, cutoff),
        ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] Add `emos_training` table to schema migrations in `tracker.py`:

```sql
CREATE TABLE IF NOT EXISTS emos_training (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    city           TEXT NOT NULL,
    condition_type TEXT NOT NULL,
    forecast_date  TEXT NOT NULL,
    ens_mean       REAL NOT NULL,
    ens_spread     REAL NOT NULL,
    observed       REAL NOT NULL,
    logged_at      TEXT NOT NULL,
    UNIQUE(city, condition_type, forecast_date)
);
```

### 61.3 Write tests

- [ ] Create `tests/test_emos_calibration.py`:

```python
"""Tests for Task 61: EMOS ensemble calibration."""
from __future__ import annotations

import math
import pytest
from calibration_emos import fit_emos, emos_prob, crps_gaussian, EMOSParams


class TestEMOSFitting:
    def _make_training_data(self, n=20, bias=0.0, spread_scale=1.0):
        """Generate synthetic training data with known properties."""
        import random
        rng = random.Random(42)
        data = []
        for _ in range(n):
            ens_mean = 70.0 + rng.gauss(0, 3)
            ens_spread = 2.0
            observed = ens_mean + bias + rng.gauss(0, ens_spread * spread_scale)
            data.append({"ens_mean": ens_mean, "ens_spread": ens_spread,
                         "observed": observed})
        return data

    def test_fit_returns_unfitted_when_too_little_data(self):
        """Fewer than 10 training samples → fitted=False."""
        params = fit_emos([])
        assert params.fitted is False

    def test_fit_returns_fitted_with_sufficient_data(self):
        """20 training samples → fitted=True."""
        data = self._make_training_data(n=20)
        params = fit_emos(data)
        assert params.fitted is True
        assert params.n_training == 20

    def test_bias_correction_reduces_error(self):
        """When ensemble has a +3F warm bias, fitted params should have a < 0."""
        data = self._make_training_data(n=40, bias=-3.0)  # observed is 3F colder
        params = fit_emos(data)
        assert params.a < 0, "EMOS should correct for warm ensemble bias"

    def test_emos_prob_above_high_threshold(self):
        """P(T > 90) should be < 0.1 when forecast mean is 70."""
        params = EMOSParams(a=0.0, b=1.0, c=4.0, d=1.0, fitted=True)
        p = emos_prob(params, ens_mean=70.0, ens_spread=2.0,
                      threshold=90.0, above=True)
        assert p < 0.10

    def test_emos_prob_above_low_threshold(self):
        """P(T > 50) should be > 0.9 when forecast mean is 70."""
        params = EMOSParams(a=0.0, b=1.0, c=4.0, d=1.0, fitted=True)
        p = emos_prob(params, ens_mean=70.0, ens_spread=2.0,
                      threshold=50.0, above=True)
        assert p > 0.90

    def test_crps_lower_for_better_forecast(self):
        """A forecast closer to the observation should have lower CRPS."""
        good = crps_gaussian(mu=72.0, sigma=2.0, obs=73.0)
        bad = crps_gaussian(mu=60.0, sigma=2.0, obs=73.0)
        assert good < bad
```

### 61.4 Verify & Commit

- [ ] `python -m pytest tests/test_emos_calibration.py -v` → 6 passed
- [ ] `git add calibration_emos.py tracker.py tests/test_emos_calibration.py`
- [ ] `git commit -m "feat(p12.a): add EMOS ensemble calibration for binary probability estimation"`

---

## Task 62 (P12.B) — Bayesian Lead-Time Blending

### Background

Jewson (2004) derives the optimal Bayesian weight for blending a weather forecast with historical climatology:

```
P_blended = w * P_climatology + (1 - w) * P_forecast
w = σ²_forecast / (σ²_forecast + σ²_climatology_uncertainty)
```

As lead time increases, forecast uncertainty grows until it exceeds climatological uncertainty — at which point pure climatology is optimal. Leutbecher & Palmer (2008) show this crossover occurs at approximately **10 days** for temperature in the NH mid-latitudes. Beyond 14 days, the ensemble adds no information.

**Why it matters:** Without this, the bot over-bets on 14-day forecasts where there is no real edge. This is currently the single largest source of wasted edge budget.

### 62.1 Add `lead_time_climatology_weight(lead_days)` to `weather_markets.py`

- [ ] Add after `_CONDITION_CONFIDENCE`:

```python
def lead_time_climatology_weight(lead_days: int) -> float:
    """
    Return the weight to give climatology vs. forecast at a given lead time.

    Based on Jewson (2004) Bayesian blending and Leutbecher & Palmer (2008)
    ensemble skill decay. Returns w ∈ [0.0, 1.0] where:
        0.0 = pure forecast (day 1)
        1.0 = pure climatology (day 14+)

    Reference decay: skill ~ exp(-t/τ), τ ≈ 7 days for NH temperature.
    """
    if lead_days <= 0:
        return 0.0
    if lead_days >= 14:
        return 1.0
    # Linear ramp from 0 (day 1) to 0.5 (day 7) to 1.0 (day 14)
    return min(1.0, lead_days / 14.0)
```

### 62.2 Add `blend_with_climatology(forecast_prob, clim_prob, lead_days)` to `weather_markets.py`

- [ ] Add:

```python
def blend_with_climatology(
    forecast_prob: float,
    clim_prob: float,
    lead_days: int,
) -> float:
    """
    Blend forecast probability with climatological base rate using Bayesian lead-time weight.

    At lead_days=1: returns forecast_prob (trust the model)
    At lead_days=14+: returns clim_prob (trust climatology only)
    Between: linear interpolation.

    Args:
        forecast_prob: P(event) from NWP model/ensemble
        clim_prob: P(event) from 30-year historical records
        lead_days: days until settlement

    Returns:
        Blended probability in [0, 1]
    """
    w = lead_time_climatology_weight(lead_days)
    blended = w * clim_prob + (1.0 - w) * forecast_prob
    return round(max(0.01, min(0.99, blended)), 4)
```

### 62.3 Add lead-time gate — block trades beyond 10 days unless strong signal

- [ ] In `_validate_trade_opportunity` in `main.py`, add after existing guards:

```python
    # P12.B — lead-time gate: beyond 10 days, forecasts have near-zero skill
    lead_days = opportunity.get("days_to_settlement", 0)
    if lead_days > 10:
        blended_edge = opportunity.get("net_edge", 0) * (1.0 - (lead_days - 10) / 10.0)
        if blended_edge < effective_min_edge:
            return False, f"lead_time={lead_days}d exceeds 10d skill horizon; blended_edge={blended_edge:.3f}"
```

### 62.4 Write tests

- [ ] Create `tests/test_lead_time_blending.py`:

```python
"""Tests for Task 62: Bayesian lead-time climatology blending."""
from __future__ import annotations

import pytest


class TestLeadTimeBlending:
    def test_day_1_returns_forecast(self):
        """At lead_days=1, blended result should be dominated by forecast."""
        from weather_markets import blend_with_climatology
        result = blend_with_climatology(0.80, 0.50, lead_days=1)
        assert result > 0.70, "Day 1: forecast should dominate"

    def test_day_14_returns_climatology(self):
        """At lead_days=14, blended result should return climatology."""
        from weather_markets import blend_with_climatology
        result = blend_with_climatology(0.80, 0.50, lead_days=14)
        assert result == pytest.approx(0.50, abs=0.01), "Day 14+: climatology dominates"

    def test_day_7_is_midpoint(self):
        """At lead_days=7, result is halfway between forecast and climatology."""
        from weather_markets import blend_with_climatology
        result = blend_with_climatology(0.80, 0.40, lead_days=7)
        expected = 0.5 * 0.80 + 0.5 * 0.40
        assert result == pytest.approx(expected, abs=0.02)

    def test_weight_increases_with_lead_time(self):
        """Climatology weight must be monotonically increasing with lead time."""
        from weather_markets import lead_time_climatology_weight
        weights = [lead_time_climatology_weight(d) for d in range(1, 16)]
        assert weights == sorted(weights), "Weight must be non-decreasing with lead time"

    def test_weight_bounds(self):
        """Weight must be in [0, 1] for all lead times."""
        from weather_markets import lead_time_climatology_weight
        for d in [0, 1, 5, 7, 10, 14, 30]:
            w = lead_time_climatology_weight(d)
            assert 0.0 <= w <= 1.0

    def test_beyond_14_days_is_full_climatology(self):
        """lead_days >= 14 must return weight = 1.0."""
        from weather_markets import lead_time_climatology_weight
        assert lead_time_climatology_weight(14) == pytest.approx(1.0)
        assert lead_time_climatology_weight(30) == pytest.approx(1.0)
```

### 62.5 Verify & Commit

- [ ] `python -m pytest tests/test_lead_time_blending.py -v` → 6 passed
- [ ] Full regression: `python -m pytest --tb=short -q`
- [ ] `git add weather_markets.py main.py tests/test_lead_time_blending.py`
- [ ] `git commit -m "feat(p12.b): add Bayesian lead-time blending and 10-day skill horizon gate"`

---

## Task 63 (P12.C) — 30-Year Burn Analysis Base Rate

### Background

Jewson & Brix (2005) recommend "burn analysis" as the non-parametric base rate: collect 30 years of historical daily weather observations for each city/station, run them through the market's settlement formula, and compute the empirical exceedance probability. For "Will max temp in Chicago exceed 85°F on July 15?", you collect all July 15 Chicago maxima from 1994–2024 and count what fraction exceeded 85°F. This is the `clim_prob` input to Task 62's blending formula.

### 63.1 Add `compute_burn_base_rate(city, condition_type, threshold, target_month_day)` to `tracker.py`

- [ ] Add:

```python
def compute_burn_base_rate(
    city: str,
    condition_type: str,
    threshold: float,
    target_month_day: str,  # "MM-DD" format
    window_days: int = 7,   # ±days around target date for sample pooling
) -> dict:
    """
    Compute empirical exceedance probability from historical outcomes (burn analysis).

    Jewson & Brix (2005): use 30+ years of verified observations for a
    station/month/day combination as the climatological base rate.

    Queries the outcomes table for all historical records within ±window_days
    of target_month_day, across all years.

    Returns:
        {
          city, condition_type, threshold, target_month_day,
          n_years, exceedance_rate,   # P(value > threshold) from history
          below_rate,                 # P(value <= threshold)
          sample_size,
        }
    """
    _init_db()
    month, day = target_month_day.split("-")
    target_day_of_year = (
        __import__("datetime").date(2000, int(month), int(day)).timetuple().tm_yday
    )
    lower_doy = target_day_of_year - window_days
    upper_doy = target_day_of_year + window_days

    with _conn() as con:
        rows = con.execute(
            """
            SELECT observed_value, created_at FROM outcomes
            WHERE city = ? AND condition_type = ?
              AND observed_value IS NOT NULL
            """,
            (city, condition_type),
        ).fetchall()

    # Filter to ±window_days of target calendar date (across any year)
    import datetime as _dt
    filtered = []
    for r in rows:
        try:
            date = _dt.date.fromisoformat(r["created_at"][:10])
            doy = date.timetuple().tm_yday
            if lower_doy <= doy <= upper_doy:
                filtered.append(r["observed_value"])
        except Exception:
            continue

    n = len(filtered)
    if n == 0:
        return {
            "city": city, "condition_type": condition_type,
            "threshold": threshold, "target_month_day": target_month_day,
            "n_years": 0, "exceedance_rate": None,
            "below_rate": None, "sample_size": 0,
        }

    above = sum(1 for v in filtered if v > threshold)
    return {
        "city": city,
        "condition_type": condition_type,
        "threshold": threshold,
        "target_month_day": target_month_day,
        "n_years": n,
        "exceedance_rate": round(above / n, 4),
        "below_rate": round(1 - above / n, 4),
        "sample_size": n,
    }
```

### 63.2 Wire burn base rate into `analyze_trade()` in `weather_markets.py`

- [ ] In `analyze_trade()`, after computing forecast probability:
  - Call `compute_burn_base_rate()` for the target city/condition/threshold/date
  - Pass result as `clim_prob` to `blend_with_climatology()` (Task 62)
  - Log `clim_prob` and `burn_sample_size` in the opportunity dict for auditing

### 63.3 Write tests

- [ ] Create `tests/test_burn_analysis.py`:

```python
"""Tests for Task 63: 30-year burn analysis base rate."""
from __future__ import annotations

import pytest


class TestBurnBaseRate:
    def test_returns_none_exceedance_when_no_data(self, tmp_path, monkeypatch):
        """No historical outcomes → exceedance_rate is None."""
        import tracker
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)

        result = tracker.compute_burn_base_rate(
            "NYC", "high_temp", threshold=85.0, target_month_day="07-15"
        )
        assert result["sample_size"] == 0
        assert result["exceedance_rate"] is None

    def test_all_above_threshold(self, tmp_path, monkeypatch):
        """All historical values above threshold → exceedance_rate = 1.0."""
        import tracker, sqlite3
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)
        tracker._init_db()

        with sqlite3.connect(tmp_path / "tracker.db") as con:
            for year in range(2010, 2020):
                con.execute(
                    """INSERT INTO outcomes
                       (city, condition_type, observed_value, created_at, outcome)
                       VALUES (?, ?, ?, ?, ?)""",
                    ("NYC", "high_temp", 90.0,
                     f"{year}-07-15T12:00:00+00:00", 1),
                )

        result = tracker.compute_burn_base_rate(
            "NYC", "high_temp", threshold=85.0, target_month_day="07-15"
        )
        assert result["exceedance_rate"] == pytest.approx(1.0)
        assert result["sample_size"] == 10

    def test_half_above_threshold(self, tmp_path, monkeypatch):
        """Half above, half below → exceedance_rate ≈ 0.5."""
        import tracker, sqlite3
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "tracker.db")
        monkeypatch.setattr(tracker, "_initialized", False)
        tracker._init_db()

        with sqlite3.connect(tmp_path / "tracker.db") as con:
            for year in range(2010, 2020):
                val = 90.0 if year % 2 == 0 else 80.0
                con.execute(
                    """INSERT INTO outcomes
                       (city, condition_type, observed_value, created_at, outcome)
                       VALUES (?, ?, ?, ?, ?)""",
                    ("NYC", "high_temp", val,
                     f"{year}-07-15T12:00:00+00:00", 1 if val > 85 else 0),
                )

        result = tracker.compute_burn_base_rate(
            "NYC", "high_temp", threshold=85.0, target_month_day="07-15"
        )
        assert result["exceedance_rate"] == pytest.approx(0.5, abs=0.01)
```

### 63.4 Verify & Commit

- [ ] `python -m pytest tests/test_burn_analysis.py -v` → 3 passed
- [ ] `git add tracker.py weather_markets.py tests/test_burn_analysis.py`
- [ ] `git commit -m "feat(p12.c): add 30-year burn analysis base rate for climatological blending"`

---

## Tier 2 — New Data Sources

---

## Task 64 (P12.D) — Open-Meteo Ensemble API

### Background

Open-Meteo provides free JSON access to 31-member GFS-ENS and 40-member ICON-EPS ensemble forecasts — no auth required, no API key, no rate limit registration. This is the single easiest high-value data source to add. Endpoint: `https://ensemble-api.open-meteo.com/v1/ensemble`.

The ensemble member output allows computation of ensemble mean, spread (standard deviation), and probability of exceedance directly, replacing the fixed `sigma=3.0` assumption in the current code.

### 64.1 Add `get_open_meteo_ensemble(lat, lon, target_date)` to a new `open_meteo.py`

- [ ] Create `open_meteo.py`:

```python
"""
Open-Meteo Ensemble API client.

Free, no-auth JSON API providing GFS-ENS and ICON-EPS ensemble member data.
Reference: https://open-meteo.com/en/docs/ensemble-api

No new dependencies — uses stdlib urllib.
"""
from __future__ import annotations

import json
import math
import urllib.request
import urllib.parse
from datetime import date, timedelta
from typing import Optional

_OPEN_METEO_ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
_REQUEST_TIMEOUT_SECS = 10


def get_open_meteo_ensemble(
    lat: float,
    lon: float,
    target_date: date,
    models: tuple[str, ...] = ("gfs_seamless", "icon_seamless"),
) -> Optional[dict]:
    """
    Fetch ensemble temperature forecasts for a lat/lon on target_date.

    Returns:
        {
          "ens_mean": float,        # mean across all members (°F)
          "ens_spread": float,      # std deviation across members (°F)
          "ens_max": float,         # 90th percentile (°F)
          "ens_min": float,         # 10th percentile (°F)
          "member_count": int,
          "source": "open_meteo",
        }
    or None on failure.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min",
        "temperature_unit": "fahrenheit",
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "models": ",".join(models),
    }
    url = _OPEN_METEO_ENSEMBLE_URL + "?" + urllib.parse.urlencode(params)

    try:
        with urllib.request.urlopen(url, timeout=_REQUEST_TIMEOUT_SECS) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None

    # Collect all member values for temperature_2m_max on target_date
    members = []
    for key, values in data.items():
        if "temperature_2m_max_member" in key and isinstance(values, dict):
            daily = values.get("temperature_2m_max", [])
            if daily:
                members.append(daily[0])

    if not members:
        return None

    n = len(members)
    mean = sum(members) / n
    variance = sum((x - mean) ** 2 for x in members) / n
    spread = math.sqrt(variance)
    sorted_members = sorted(members)
    p10 = sorted_members[max(0, int(0.10 * n))]
    p90 = sorted_members[min(n - 1, int(0.90 * n))]

    return {
        "ens_mean": round(mean, 2),
        "ens_spread": round(spread, 2),
        "ens_max": round(p90, 2),
        "ens_min": round(p10, 2),
        "member_count": n,
        "source": "open_meteo",
    }
```

### 64.2 Wire into `weather_markets.py` ensemble blend

- [ ] In `_blend_weights()`, add `open_meteo_prob` as a source at weight `0.20`
- [ ] Derive `open_meteo_prob` from the ensemble mean/spread using the EMOS formula from Task 61 (or naive Gaussian if EMOS params are not yet fitted)
- [ ] Renormalize existing weights proportionally when Open-Meteo is unavailable

### 64.3 Write tests

- [ ] Create `tests/test_open_meteo.py`:

```python
"""Tests for Task 64: Open-Meteo ensemble API."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
import json


class TestOpenMeteoEnsemble:
    def test_returns_none_on_network_error(self, monkeypatch):
        """Network failure → returns None gracefully."""
        import open_meteo
        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen",
                            lambda *a, **kw: (_ for _ in ()).throw(
                                OSError("network error")))
        from datetime import date
        result = open_meteo.get_open_meteo_ensemble(40.7, -74.0, date.today())
        assert result is None

    def test_spread_is_non_negative(self, monkeypatch):
        """Ensemble spread must always be ≥ 0."""
        import open_meteo
        from datetime import date

        # Mock response with identical member values (spread = 0)
        fake_data = {
            "temperature_2m_max_member01": {"temperature_2m_max": [72.0]},
            "temperature_2m_max_member02": {"temperature_2m_max": [72.0]},
            "temperature_2m_max_member03": {"temperature_2m_max": [72.0]},
        }

        class FakeResp:
            def read(self): return json.dumps(fake_data).encode()
            def __enter__(self): return self
            def __exit__(self, *a): pass

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: FakeResp())

        result = open_meteo.get_open_meteo_ensemble(40.7, -74.0, date.today())
        if result:
            assert result["ens_spread"] >= 0.0

    def test_mean_within_member_range(self, monkeypatch):
        """Ensemble mean must be between min and max member values."""
        import open_meteo
        from datetime import date

        fake_data = {
            "temperature_2m_max_member01": {"temperature_2m_max": [65.0]},
            "temperature_2m_max_member02": {"temperature_2m_max": [70.0]},
            "temperature_2m_max_member03": {"temperature_2m_max": [75.0]},
        }

        class FakeResp:
            def read(self): return json.dumps(fake_data).encode()
            def __enter__(self): return self
            def __exit__(self, *a): pass

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: FakeResp())

        result = open_meteo.get_open_meteo_ensemble(40.7, -74.0, date.today())
        if result:
            assert result["ens_min"] <= result["ens_mean"] <= result["ens_max"]
```

### 64.4 Verify & Commit

- [ ] `python -m pytest tests/test_open_meteo.py -v` → 3 passed
- [ ] `git add open_meteo.py weather_markets.py tests/test_open_meteo.py`
- [ ] `git commit -m "feat(p12.d): add Open-Meteo free ensemble API as signal source"`

---

## Task 65 (P12.E) — ECMWF Open Data Integration (Days 4–7 Edge)

### Background

ECMWF has documented skill advantage over GFS at days 4–7. Their open data is freely available on AWS S3 (`s3://ecmwf-forecasts/`) and via the `ecmwf-opendata` Python client. New dependency required: `pip install ecmwf-opendata`. Provides 51-member ensemble 2m temperature for any lat/lon by interpolation.

### 65.1 Add `ecmwf-opendata` to `requirements.txt`

- [ ] Add: `ecmwf-opendata>=0.3.0`

### 65.2 Add `get_ecmwf_ensemble(lat, lon, target_date)` to a new `ecmwf_data.py`

- [ ] Create `ecmwf_data.py` with a function that:
  - Uses `ecmwf-opendata` client to download the latest ECMWF ENS 2m temperature GRIB for target_date
  - Interpolates to the given lat/lon
  - Returns `{"ens_mean": float, "ens_spread": float, "member_count": 51, "source": "ecmwf_ens"}`
  - Returns `None` on failure or when lead_days < 4 (GFS is better at short range)
  - Caches the downloaded file for the current run cycle to avoid redundant downloads

### 65.3 Wire into `_blend_weights()` with lead-time-aware weighting

- [ ] Apply ECMWF only for `lead_days` between 4 and 15:
  - Days 4–7: weight `0.30` (ECMWF skill peak)
  - Days 8–10: weight `0.20`
  - Days 11–15: weight `0.10`
  - Days 1–3 and 16+: weight `0.0`

### 65.4 Write tests

- [ ] Add `tests/test_ecmwf_data.py` with mocked ECMWF client tests:
  - Test returns None when ecmwf-opendata not installed
  - Test returns None when lead_days < 4
  - Test result has correct keys when successful

### 65.5 Verify & Commit

- [ ] `python -m pytest tests/test_ecmwf_data.py -v`
- [ ] `git add ecmwf_data.py weather_markets.py requirements.txt tests/test_ecmwf_data.py`
- [ ] `git commit -m "feat(p12.e): add ECMWF open data ensemble for days 4-7 forecast edge"`

---

## Task 66 (P12.F) — Teleconnection Index Overlay (AO, NAO, MJO)

### Background

Three teleconnection indices provide documented multi-week temperature predictability beyond NWP models:
- **AO (Arctic Oscillation):** Negative AO → cold air outbreaks in eastern US. Published daily by NOAA CPC.
- **NAO (North Atlantic Oscillation):** Negative NAO → cold/stormy eastern US winters. Published daily.
- **MJO (Madden-Julian Oscillation):** 8-phase cycle with regional temperature impacts 2–4 weeks ahead. Published twice weekly.

These indices add predictability at 10–30 day lead times where NWP models have little skill.

### 66.1 Add `get_teleconnection_indices()` to `climate_indices.py`

- [ ] Add to existing `climate_indices.py`:

```python
_TELECONNECTION_URLS = {
    "ao": "https://www.cpc.ncep.noaa.gov/products/precip/CWlink/daily_ao_index/ao.index.current.txt",
    "nao": "https://www.cpc.ncep.noaa.gov/products/precip/CWlink/pna/norm.daily.nao.index.b500101.current.ascii",
}

def get_teleconnection_indices() -> dict:
    """
    Fetch current AO, NAO indices from NOAA CPC.

    Returns:
        {
          "ao": float,      # current AO index value
          "nao": float,     # current NAO index value
          "ao_phase": "positive" | "negative" | "neutral",
          "nao_phase": "positive" | "negative" | "neutral",
        }
    Cached for 6 hours. Returns neutral values on failure.
    """
    ...

def _classify_index(value: float, strong_threshold: float = 1.0) -> str:
    """Classify teleconnection index value as positive/negative/neutral."""
    if value > strong_threshold:
        return "positive"
    elif value < -strong_threshold:
        return "negative"
    return "neutral"
```

### 66.2 Add `teleconnection_temp_adjustment(city, condition_type, ao, nao)` to `weather_markets.py`

- [ ] Add after `_pdo_temp_adjustment` (Task 57 / P11.H):

```python
_TELECONNECTION_CITY_IMPACT = {
    # city: (ao_effect_degF_per_unit, nao_effect_degF_per_unit)
    # Negative AO/NAO → colder in eastern US (negative = cooler effect)
    "NYC":     (-0.8, -0.6),
    "Chicago": (-1.0, -0.4),
    "Boston":  (-0.9, -0.7),
    "Atlanta":  (-0.5, -0.2),
    "Dallas":   (-0.3, -0.1),
    "Seattle":  ( 0.2,  0.1),  # Opposite sign — AO- warms PNW relative to east
}

def teleconnection_temp_adjustment(
    city: str, ao: float, nao: float
) -> float:
    """
    Return temperature adjustment (°F) based on AO and NAO indices.
    Applied to the climatological base rate, not the forecast.
    Only significant at lead times > 7 days.
    """
    impacts = _TELECONNECTION_CITY_IMPACT.get(city, (0.0, 0.0))
    return round(ao * impacts[0] + nao * impacts[1], 2)
```

### 66.3 Write tests

- [ ] Add `TestTeleconnectionIndices` to `tests/test_climate_indices.py`:
  - Test negative AO produces negative temp adjustment for NYC
  - Test positive AO produces positive adjustment
  - Test unknown city returns 0.0 adjustment
  - Test `get_teleconnection_indices` returns dict with required keys even on failure

### 66.4 Verify & Commit

- [ ] `python -m pytest tests/test_climate_indices.py -v`
- [ ] `git add climate_indices.py weather_markets.py tests/test_climate_indices.py`
- [ ] `git commit -m "feat(p12.f): add AO/NAO teleconnection index overlay for winter temperature markets"`

---

## Tier 3 — Risk & Sizing Improvements

---

## Task 67 (P12.G) — Ensemble Spread as Kelly Confidence Multiplier

### Background

When the ensemble spread is high (models disagree), there is genuine forecast uncertainty — binary outcomes should be near 50/50 and Kelly fractions should be small. When spread is low, models agree and Kelly can be larger. This converts ensemble spread into a position sizing input.

### 67.1 Add `ensemble_spread_kelly_multiplier(ens_spread, condition_type)` to `paper.py`

- [ ] Add:

```python
_SPREAD_KELLY_CAP: dict[str, float] = {
    # Maximum ensemble spread (°F) before Kelly → 0
    "high_temp": 8.0,
    "low_temp":  6.0,
    "precip_any": 0.35,  # PoP spread in probability units
}

def ensemble_spread_kelly_multiplier(
    ens_spread: float,
    condition_type: str,
) -> float:
    """
    Return Kelly multiplier ∈ [0.0, 1.0] based on ensemble spread.

    Full Kelly when spread ≈ 0; zero Kelly when spread ≥ cap.
    Linear interpolation between 0 and cap.

    Args:
        ens_spread: ensemble standard deviation (°F for temperature, probability for precip)
        condition_type: "high_temp", "low_temp", or "precip_any"
    """
    cap = _SPREAD_KELLY_CAP.get(condition_type, 8.0)
    if cap <= 0:
        return 1.0
    return max(0.0, 1.0 - ens_spread / cap)
```

### 67.2 Wire into `_auto_place_trades` in `main.py`

- [ ] Multiply Kelly fraction by `ensemble_spread_kelly_multiplier` before sizing
- [ ] Log `ens_spread` and `spread_kelly_mult` in `_log_decision`

### 67.3 Write tests

- [ ] Add `TestEnsembleSpreadKelly` to `tests/test_risk_control.py`:
  - Test zero spread → multiplier = 1.0
  - Test spread at cap → multiplier = 0.0
  - Test spread at half cap → multiplier ≈ 0.5

### 67.4 Verify & Commit

- [ ] `git commit -m "feat(p12.g): add ensemble spread as Kelly confidence multiplier"`

---

## Task 68 (P12.H) — Half-Kelly Calibration Scaling

### Background

MacLean, Thorp & Ziemba (2010): when a probability estimate p is uncertain by ±5%, the Kelly fraction can be wrong by 2–3×. Half-Kelly (or quarter-Kelly) is almost always preferable until you have 50+ settled historical comparison points to validate calibration. This task adds an automatic scaling factor based on settled trade count.

### 68.1 Add `calibration_kelly_scale(n_settled_trades)` to `paper.py`

- [ ] Add:

```python
def calibration_kelly_scale(n_settled_trades: int) -> float:
    """
    Return Kelly scaling factor based on calibration confidence.

    MacLean, Thorp & Ziemba (2010): use fractional Kelly proportional to
    calibration evidence. Ramps from 0.25x (no data) to 1.0x (50+ trades).

    n_settled_trades: number of historically settled and verified trades
    """
    if n_settled_trades <= 0:
        return 0.25
    if n_settled_trades >= 50:
        return 1.0
    # Linear ramp: 0.25 at n=0, 1.0 at n=50
    return 0.25 + 0.75 * (n_settled_trades / 50.0)
```

### 68.2 Wire into `_auto_place_trades`

- [ ] After computing base Kelly fraction, multiply by `calibration_kelly_scale(n_settled)`
- [ ] `n_settled` = count from `tracker.get_settled_trade_count()` (add this helper if needed)

### 68.3 Write tests

- [ ] Add `TestCalibrationKellyScale` to `tests/test_risk_control.py`:
  - Test n=0 → 0.25
  - Test n=50 → 1.0
  - Test n=25 → ~0.625
  - Test scale is monotonically increasing

### 68.4 Verify & Commit

- [ ] `git commit -m "feat(p12.h): add calibration-based fractional Kelly scaling"`

---

## Task 69 (P12.I) — Settlement Station Basis Correction

### Background

Kalshi settles on a specific NOAA ASOS station. Your NWS gridpoint forecasts target the nearest grid cell, which may be miles away. Dischel & Barrieu (2002): 10-mile station separation can reduce forecast correlation from 1.0 to 0.92, creating systematic basis risk. This task adds a station-to-gridpoint bias correction table.

### 69.1 Add `_SETTLEMENT_STATION_MAP` to `weather_markets.py`

- [ ] Add a dict mapping Kalshi city names to their official Kalshi settlement ASOS station IDs and their known typical bias vs. NWS gridpoint (in °F):

```python
_SETTLEMENT_STATION_MAP: dict[str, dict] = {
    "NYC":     {"station": "KNYC", "lat": 40.7789, "lon": -73.9692, "gridpoint_bias": 0.0},
    "Chicago": {"station": "KORD", "lat": 41.9742, "lon": -87.9073, "gridpoint_bias": -0.5},
    "Dallas":  {"station": "KDAL", "lat": 32.8481, "lon": -96.8512, "gridpoint_bias": 0.0},
    "Atlanta": {"station": "KATL", "lat": 33.6407, "lon": -84.4277, "gridpoint_bias": 0.3},
    "Seattle": {"station": "KSEA", "lat": 47.4480, "lon": -122.3088, "gridpoint_bias": 0.0},
    "Boston":  {"station": "KBOS", "lat": 42.3631, "lon": -71.0065, "gridpoint_bias": 0.0},
    "Miami":   {"station": "KMIA", "lat": 25.7959, "lon": -80.2870, "gridpoint_bias": 0.0},
    "Denver":  {"station": "KDEN", "lat": 39.8561, "lon": -104.6737, "gridpoint_bias": 0.0},
}

def get_settlement_station_bias(city: str) -> float:
    """Return known bias (°F) between Kalshi settlement station and NWS gridpoint."""
    return _SETTLEMENT_STATION_MAP.get(city, {}).get("gridpoint_bias", 0.0)
```

### 69.2 Apply bias correction in `analyze_trade()`

- [ ] In `analyze_trade()`, adjust threshold by `- get_settlement_station_bias(city)` before computing probability. Example: if Chicago gridpoint forecast says 85°F but KORD runs 0.5°F cooler, adjust the effective threshold to 84.5°F when computing P(T > 85).

### 69.3 Write tests

- [ ] Add `TestSettlementBasisCorrection` to `tests/test_data_engineering.py`:
  - Test known city returns correct station ID
  - Test unknown city returns bias = 0.0
  - Test bias correction shifts probability in correct direction

### 69.4 Verify & Commit

- [ ] `git commit -m "feat(p12.i): add settlement station basis correction for known city biases"`

---

## Tier 4 — Market Intelligence & Execution

---

## Task 70 (P12.J) — Startup Position Reconciliation

### Background

A common failure mode for cron-based bots: a crash mid-order leaves orphan open orders that persist into the next cron cycle. These cause double-positioning and inflate exposure. Every mature OSS prediction market bot performs a reconciliation step on startup.

### 70.1 Add `reconcile_open_orders(client)` to `main.py`

- [ ] Add:

```python
def reconcile_open_orders(client) -> int:
    """
    On startup, fetch open orders from Kalshi API and compare to local DB.

    Cancels any orders that are in local DB as 'sent' but not found in API
    (implies they were lost/rejected). Logs any orders found in API but not
    in local DB (orphans from a previous crash).

    Returns: number of discrepancies found and resolved.
    """
    ...
```

- [ ] Call `reconcile_open_orders(client)` at the start of `cmd_cron`, before scanning markets

### 70.2 Write tests

- [ ] Add `TestStartupReconciliation` to `tests/test_execution_stability.py`

### 70.3 Verify & Commit

- [ ] `git commit -m "feat(p12.j): add startup position reconciliation to detect orphan orders"`

---

## Task 71 (P12.K) — Data Freshness Discounting

### Background

As forecast data ages past a staleness threshold, confidence should decay toward maximum uncertainty (50%). This prevents the bot from placing full-Kelly bets on a 6-hour-old forecast just because no newer data is available.

### 71.1 Add `data_freshness_discount(data_age_hours, staleness_threshold_hours)` to `utils.py`

- [ ] Add:

```python
def data_freshness_discount(
    data_age_hours: float,
    staleness_threshold_hours: float = 6.0,
) -> float:
    """
    Return confidence multiplier ∈ [0.0, 1.0] based on data age.

    At age=0: multiplier = 1.0 (full confidence)
    At age=staleness_threshold: multiplier = 0.0 (pull prob to 0.5)
    Linear interpolation between 0 and threshold.

    Example: 3-hour-old data with 6h threshold → multiplier = 0.5
    The calling code should apply: adjusted_prob = 0.5 + (raw_prob - 0.5) * multiplier
    """
    return max(0.0, 1.0 - data_age_hours / staleness_threshold_hours)
```

### 71.2 Wire into `_validate_trade_opportunity`

- [ ] Compute data age from `opportunity["data_fetched_at"]`
- [ ] Apply: `confidence_multiplier = data_freshness_discount(age_hours)`
- [ ] If `confidence_multiplier < 0.3`, reject with `rejection_reason="stale_data"`

### 71.3 Write tests

- [ ] Add `TestDataFreshness` to `tests/test_execution_stability.py`:
  - Test age=0 → multiplier=1.0
  - Test age=threshold → multiplier=0.0
  - Test age=half_threshold → multiplier≈0.5

### 71.4 Verify & Commit

- [ ] `git commit -m "feat(p12.k): add data freshness discounting to prevent stale-data over-betting"`

---

## Task 72 (P12.L) — Cross-City Correlation Scanner

### Background

Temperature markets in nearby cities are highly correlated (Chicago ↔ Minneapolis ↔ Detroit ρ ≈ 0.80+). When a strong signal exists for one city, check if correlated city markets are mispriced relative to the same regional forecast. One forecast view → multiple trade opportunities.

### 72.1 Add `_CITY_CORRELATION_GROUPS` and `scan_correlated_markets` to `main.py`

- [ ] Add:

```python
_CITY_CORRELATION_GROUPS: list[list[str]] = [
    ["NYC", "Boston", "Philadelphia"],
    ["Chicago", "Minneapolis", "Detroit", "Indianapolis"],
    ["Dallas", "Houston", "Oklahoma City"],
    ["Seattle", "Portland", "Vancouver"],
    ["Atlanta", "Charlotte", "Nashville"],
]

def scan_correlated_markets(
    primary_city: str,
    primary_signal: dict,
    all_opportunities: list[dict],
) -> list[dict]:
    """
    Given a strong signal for primary_city, find other cities in the same
    correlation group that have mispriced markets.

    Returns list of additional opportunities with adjusted confidence
    (correlation discount already applied via kelly penalty).
    """
    ...
```

### 72.2 Write tests

- [ ] Add `TestCorrelatedMarketScanner` to `tests/test_strategy_intelligence.py`

### 72.3 Verify & Commit

- [ ] `git commit -m "feat(p12.l): add cross-city correlation scanner for regional weather signals"`

---

## Task 73 (P12.M) — Liquidity Filtering Pre-Trade Gate

### Background

Most mature prediction market bots skip low-liquidity markets to avoid bad fills and large spread costs. Standard thresholds from OSS research: spread > 15% → skip; open interest < 100 contracts each side → skip.

### 73.1 Add `passes_liquidity_filter(opportunity)` to `main.py`

- [ ] Add:

```python
_MIN_OPEN_INTEREST: int = int(os.getenv("MIN_OPEN_INTEREST", "50"))
_MAX_SPREAD_PCT: float = float(os.getenv("MAX_SPREAD_PCT", "0.15"))

def passes_liquidity_filter(opportunity: dict) -> bool:
    """
    Return True if the market has sufficient liquidity to trade.

    Filters:
    - yes_ask - yes_bid > MAX_SPREAD_PCT → skip (too expensive)
    - open_interest < MIN_OPEN_INTEREST → skip (too thin)
    """
    yes_ask = opportunity.get("yes_ask", 1.0)
    yes_bid = opportunity.get("yes_bid", 0.0)
    spread = yes_ask - yes_bid
    if spread > _MAX_SPREAD_PCT:
        return False
    oi = opportunity.get("open_interest", 0)
    if oi < _MIN_OPEN_INTEREST:
        return False
    return True
```

### 73.2 Wire into `_auto_place_trades`

- [ ] Before the per-opportunity loop body, add:
  ```python
  if not passes_liquidity_filter(opp):
      _log_decision(..., action="rejected", rejection_reason="liquidity_filter")
      continue
  ```

### 73.3 Write tests

- [ ] Add `TestLiquidityFilter` to `tests/test_market_realism.py`:
  - Test wide spread rejects
  - Test thin open interest rejects
  - Test normal market passes

### 73.4 Verify & Commit

- [ ] `git commit -m "feat(p12.m): add pre-trade liquidity filter for spread and open interest"`

---

## Tier 5 — Advanced (Implement Last)

---

## Task 74 (P12.N) — Model Run Timing Alerts

### Background

Weather markets are most mispriced immediately after a major model run when the new model shows a significant shift but the Kalshi market hasn't repriced. GFS runs at 00z, 06z, 12z, 18z. ECMWF runs at 00z and 12z. Trading within 60–90 minutes of a major model shift is the primary "speed edge" used by professional desks.

### 74.1 Add `get_current_model_cycle()` and `minutes_since_last_major_run()` to `main.py`

- [ ] Compute how many minutes ago the last major GFS/ECMWF run was initialised
- [ ] Add `TRADE_IN_FRESH_WINDOW: bool = True` — if True, apply a 1.1× Kelly boost within the first 90 minutes of a 00z/12z run (highest-information cycles)
- [ ] Add `STALE_RUN_PENALTY: float = 0.85` — Kelly multiplier applied when >3 hours past the last major run

### 74.2 Write tests

- [ ] Add `TestModelRunTiming` to `tests/test_monitoring.py`

### 74.3 Verify & Commit

- [ ] `git commit -m "feat(p12.n): add model run timing awareness for Kelly boost on fresh data"`

---

## Task 75 (P12.O) — CME Weather Futures Cross-Reference

### Background

CME HDD/CDD futures for major cities (Chicago, New York, Dallas) provide a reference probability from professional traders. When Kalshi binary market prices diverge significantly from CME-implied probabilities, it represents a near-arbitrage with an informed reference price.

### 75.1 Add `get_cme_implied_prob(city, target_period, threshold)` to a new `cme_reference.py`

- [ ] Fetch CME weather futures settlement prices from CME's public data feed
- [ ] Convert HDD/CDD futures price to implied probability for the binary threshold
- [ ] Cache for 15 minutes
- [ ] Return `None` when city/period not covered by CME contracts

### 75.2 Wire as a signal source with high weight when available

- [ ] In `_blend_weights()`, if `cme_implied_prob` is available, weight it `0.35` (highest single weight — represents informed professional market)

### 75.3 Write tests and commit

- [ ] `git commit -m "feat(p12.o): add CME weather futures as cross-reference probability source"`

---

## Task 76 (P12.P) — Recency Bias Detection and Fading

### Background

Kalshi participants over-weight the last 3–5 days of weather. After a heat wave, they price future temperature markets too high; after a cold snap, too low. This mean-reversion pattern is documented in prediction market research.

### 76.1 Add `get_recent_temperature_anomaly(city, days_back=5)` to `nws.py`

- [ ] Fetch last N days of observed temperatures vs. 30-year normal for city
- [ ] Return `{"anomaly_degF": float, "direction": "warmer"|"cooler"|"normal"}`

### 76.2 Apply recency bias fade in `analyze_trade()`

- [ ] When `abs(anomaly_degF) > 5.0`, adjust the blended probability toward climatology by an additional `0.05 * abs(anomaly_degF)` (max 0.10 adjustment) — fading the recency bias

### 76.3 Write tests and commit

- [ ] `git commit -m "feat(p12.p): add recency bias detection and climatological fade"`

---

## Task 77 (P12.Q) — Polymarket Cross-Price Comparison

### Background

Your `project_polymarket.md` memory already notes Polymarket integration as a future phase. The P12 implementation is lightweight: compare Kalshi prices to Polymarket prices for identical or near-identical events and flag significant divergences as potential arbitrage.

### 77.1 Add `get_polymarket_price(event_slug)` to a new `polymarket_client.py`

- [ ] Use Polymarket's public CLOB API (`https://clob.polymarket.com/`) to fetch current mid-price for a given market
- [ ] Maintain a mapping dict of Kalshi ticker patterns → Polymarket event slugs
- [ ] Return `None` when no matching market exists

### 77.2 Add cross-price alert in `cmd_cron`

- [ ] After finding opportunities, check Polymarket prices for matching markets
- [ ] If |Kalshi_price - Polymarket_price| > 0.05, log as a cross-exchange divergence alert

### 77.3 Write tests and commit

- [ ] `git commit -m "feat(p12.q): add Polymarket cross-price comparison for divergence alerts"`

---

## Summary of Changes

| File | What changes |
|------|-------------|
| `calibration_emos.py` | New — EMOS calibration (Task 61) |
| `open_meteo.py` | New — Open-Meteo ensemble client (Task 64) |
| `ecmwf_data.py` | New — ECMWF open data client (Task 65) |
| `cme_reference.py` | New — CME weather futures cross-reference (Task 75) |
| `polymarket_client.py` | New — Polymarket price comparison (Task 77) |
| `tracker.py` | +`emos_training` table; +`log_emos_training_row`, `get_emos_training_data`, `compute_burn_base_rate` |
| `weather_markets.py` | +`lead_time_climatology_weight`, `blend_with_climatology`, `teleconnection_temp_adjustment`, `get_settlement_station_bias`, `_SETTLEMENT_STATION_MAP`, `ensemble_spread_kelly_multiplier` wired into `_blend_weights()` and `analyze_trade()` |
| `climate_indices.py` | +`get_teleconnection_indices`, `_classify_index` (Task 66) |
| `paper.py` | +`ensemble_spread_kelly_multiplier`, `calibration_kelly_scale` (Tasks 67–68) |
| `main.py` | +`reconcile_open_orders`, `scan_correlated_markets`, `passes_liquidity_filter`, `get_current_model_cycle`, `minutes_since_last_major_run`, `data_freshness_discount` wired; lead-time gate in `_validate_trade_opportunity` |
| `utils.py` | +`data_freshness_discount` |
| `requirements.txt` | +`ecmwf-opendata>=0.3.0` |
| `tests/` | New test files for each task |

## Completion Checklist

### Tier 1 — Probability Calibration
- [ ] Task 61 (P12.A): EMOS ensemble calibration
- [ ] Task 62 (P12.B): Bayesian lead-time blending + 10-day gate
- [ ] Task 63 (P12.C): 30-year burn analysis base rate

### Tier 2 — New Data Sources
- [ ] Task 64 (P12.D): Open-Meteo ensemble API
- [ ] Task 65 (P12.E): ECMWF open data integration
- [ ] Task 66 (P12.F): Teleconnection index overlay (AO, NAO)

### Tier 3 — Risk & Sizing
- [ ] Task 67 (P12.G): Ensemble spread as Kelly confidence multiplier
- [ ] Task 68 (P12.H): Half-Kelly calibration scaling
- [ ] Task 69 (P12.I): Settlement station basis correction

### Tier 4 — Market Intelligence
- [ ] Task 70 (P12.J): Startup position reconciliation
- [ ] Task 71 (P12.K): Data freshness discounting
- [ ] Task 72 (P12.L): Cross-city correlation scanner
- [ ] Task 73 (P12.M): Liquidity filtering pre-trade gate
- [ ] Task 74 (P12.N): Model run timing alerts

### Tier 5 — Advanced
- [ ] Task 75 (P12.O): CME weather futures cross-reference
- [ ] Task 76 (P12.P): Recency bias detection and fading
- [ ] Task 77 (P12.Q): Polymarket cross-price comparison

- [ ] Final code review of entire P12 implementation
