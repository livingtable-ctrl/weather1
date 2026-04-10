# Phase 1: Testing Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add unit, integration, and regression tests so all subsequent phases can refactor safely.

**Architecture:** pytest test suite with fixtures that mock the Kalshi API and Open-Meteo API; regression baseline baked in as a JSON fixture.

**Tech Stack:** pytest, pytest-mock, unittest.mock, requests-mock

**Covers:** #111, #112, #113

---

### Task 1: Test infrastructure & fixtures

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/fixtures/sample_markets.json`
- Create: `tests/fixtures/sample_forecast.json`

- [ ] **Step 1: Install test dependencies**

```bash
cd "C:/Users/thesa/claude kalshi"
pip install pytest pytest-mock requests-mock
```

Expected: no errors.

- [ ] **Step 2: Create sample market fixture**

Create `tests/fixtures/sample_markets.json`:

```json
[
  {
    "ticker": "KXHIGHNY-26APR09-T72",
    "title": "NYC High Temp > 72°F on Apr 9",
    "yes_bid": 0.62,
    "yes_ask": 0.65,
    "last_price": 0.63,
    "volume": 1200,
    "open_interest": 3400,
    "close_time": "2026-04-09T23:59:00Z",
    "status": "open"
  },
  {
    "ticker": "KXHIGHCHI-26APR09-T58",
    "title": "Chicago High Temp > 58°F on Apr 9",
    "yes_bid": 0.45,
    "yes_ask": 0.48,
    "last_price": 0.46,
    "volume": 800,
    "open_interest": 2100,
    "close_time": "2026-04-09T23:59:00Z",
    "status": "open"
  }
]
```

- [ ] **Step 3: Create sample forecast fixture**

Create `tests/fixtures/sample_forecast.json`:

```json
{
  "NYC": {
    "high": 74.2,
    "low": 58.1,
    "precip_prob": 0.12,
    "precip_inches": 0.0,
    "ensemble_spread": 3.1
  },
  "Chicago": {
    "high": 56.8,
    "low": 41.3,
    "precip_prob": 0.35,
    "precip_inches": 0.08,
    "ensemble_spread": 4.2
  }
}
```

- [ ] **Step 4: Create conftest.py**

Create `tests/conftest.py`:

```python
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_markets():
    return json.loads((FIXTURES / "sample_markets.json").read_text())


@pytest.fixture
def sample_forecast():
    return json.loads((FIXTURES / "sample_forecast.json").read_text())


@pytest.fixture
def mock_kalshi_client(sample_markets):
    client = MagicMock()
    client.get_markets.return_value = sample_markets
    client.get_market.side_effect = lambda ticker: next(
        (m for m in sample_markets if m["ticker"] == ticker), {}
    )
    return client


@pytest.fixture
def mock_forecast(sample_forecast):
    """Patch get_weather_forecast to return fixture data."""
    with patch("weather_markets.get_weather_forecast") as mock:
        mock.side_effect = lambda city, date: sample_forecast.get(city)
        yield mock
```

- [ ] **Step 5: Run conftest to verify it imports**

```bash
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/conftest.py --collect-only
```

Expected: `no tests ran` (0 errors).

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/fixtures/
git commit -m "test: add pytest fixtures and conftest for unit/integration tests"
```

---

### Task 2: Unit tests for core forecasting functions (#111)

**Files:**
- Create: `tests/test_weather_markets.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_weather_markets.py`:

```python
"""Unit tests for core forecasting functions in weather_markets.py."""
import math
from datetime import date
from unittest.mock import patch, MagicMock
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from weather_markets import (
    _feels_like,
    parse_market_price,
    is_liquid,
    _forecast_model_weights,
)
from utils import normal_cdf


class TestFeelsLike:
    def test_hot_humid_returns_heat_index(self):
        # > 80°F and > 40% humidity → heat index regime
        result = _feels_like(temp_f=90, humidity=70, wind_mph=5)
        assert result > 90, "Heat index should be above actual temp in hot+humid conditions"

    def test_cold_windy_returns_wind_chill(self):
        # < 50°F and wind > 3 mph → wind chill regime
        result = _feels_like(temp_f=30, humidity=50, wind_mph=20)
        assert result < 30, "Wind chill should be below actual temp"

    def test_moderate_returns_actual(self):
        # Moderate conditions → feels like ≈ actual temp
        result = _feels_like(temp_f=65, humidity=50, wind_mph=5)
        assert abs(result - 65) < 5, "Moderate conditions: feels-like near actual"

    def test_zero_wind_no_wind_chill(self):
        result = _feels_like(temp_f=32, humidity=50, wind_mph=0)
        assert result == pytest.approx(32, abs=2), "Zero wind: no wind chill adjustment"


class TestParseMarketPrice:
    def test_parses_yes_bid_ask_midpoint(self):
        market = {"yes_bid": 0.60, "yes_ask": 0.64, "last_price": 0.63}
        price = parse_market_price(market)
        assert price == pytest.approx(0.62, abs=0.01)

    def test_falls_back_to_last_price(self):
        market = {"yes_bid": None, "yes_ask": None, "last_price": 0.55}
        price = parse_market_price(market)
        assert price == pytest.approx(0.55, abs=0.01)

    def test_returns_none_for_empty(self):
        market = {}
        price = parse_market_price(market)
        assert price is None


class TestIsLiquid:
    def test_liquid_market(self):
        market = {"volume": 500, "open_interest": 1000, "yes_bid": 0.30, "yes_ask": 0.35}
        assert is_liquid(market) is True

    def test_low_volume_not_liquid(self):
        market = {"volume": 5, "open_interest": 10, "yes_bid": 0.30, "yes_ask": 0.75}
        assert is_liquid(market) is False


class TestForecastModelWeights:
    def test_winter_boosts_ecmwf(self):
        weights = _forecast_model_weights(month=1)
        assert weights["ecmwf_ifs04"] > weights["gfs_seamless"]

    def test_summer_lower_ecmwf(self):
        winter_w = _forecast_model_weights(month=1)
        summer_w = _forecast_model_weights(month=7)
        assert summer_w["ecmwf_ifs04"] < winter_w["ecmwf_ifs04"]


class TestNormalCdf:
    def test_median(self):
        assert normal_cdf(0, 0, 1) == pytest.approx(0.5, abs=0.001)

    def test_one_sigma_above(self):
        assert normal_cdf(1, 0, 1) == pytest.approx(0.8413, abs=0.001)

    def test_symmetry(self):
        assert normal_cdf(-1, 0, 1) == pytest.approx(1 - normal_cdf(1, 0, 1), abs=0.001)
```

- [ ] **Step 2: Run to verify failures**

```bash
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_weather_markets.py -v 2>&1 | head -40
```

Expected: Some PASS, some FAIL (depending on current implementation). Note which fail.

- [ ] **Step 3: Fix any import errors, then run again**

```bash
python -m pytest tests/test_weather_markets.py -v
```

Expected: All tests pass or clearly fail on logic (not imports).

- [ ] **Step 4: Commit**

```bash
git add tests/test_weather_markets.py
git commit -m "test: unit tests for _feels_like, parse_market_price, is_liquid, model weights (#111)"
```

---

### Task 3: Unit tests for tracker/calibration functions (#111)

**Files:**
- Create: `tests/test_tracker.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tracker.py`:

```python
"""Unit tests for tracker.py — Brier score, calibration, bias calculations."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from unittest.mock import patch, MagicMock
import sqlite3
from pathlib import Path


def make_test_db(tmp_path):
    """Create an in-memory tracker DB with test data."""
    import tracker
    original = tracker.DB_PATH
    tracker.DB_PATH = tmp_path / "test.db"
    tracker._db_initialized = False
    tracker.init_db()
    return tracker, original


class TestBrierScore:
    def test_perfect_prediction_yes(self, tmp_path):
        t, orig = make_test_db(tmp_path)
        # Log a prediction of 1.0 that settled YES → Brier = 0
        t.log_prediction("TICKER1", "NYC", "2026-01-01", "HIGH", 70, None, 1.0, 0.9, 0.1, "ensemble", 10, 1)
        t.record_outcome("TICKER1", settled_yes=True)
        score = t.brier_score()
        assert score is not None
        assert score == pytest.approx(0.0, abs=0.01)
        t.DB_PATH = orig
        t._db_initialized = False

    def test_worst_prediction(self, tmp_path):
        t, orig = make_test_db(tmp_path)
        # Predict 0.0 but settles YES → Brier = 1.0
        t.log_prediction("TICKER2", "NYC", "2026-01-01", "HIGH", 70, None, 0.0, 0.9, -0.9, "ensemble", 10, 1)
        t.record_outcome("TICKER2", settled_yes=True)
        score = t.brier_score()
        assert score == pytest.approx(1.0, abs=0.01)
        t.DB_PATH = orig
        t._db_initialized = False

    def test_no_data_returns_none(self, tmp_path):
        t, orig = make_test_db(tmp_path)
        score = t.brier_score()
        assert score is None
        t.DB_PATH = orig
        t._db_initialized = False


class TestGetBias:
    def test_returns_float_or_none(self, tmp_path):
        t, orig = make_test_db(tmp_path)
        bias = t.get_bias("NYC")
        assert bias is None or isinstance(bias, float)
        t.DB_PATH = orig
        t._db_initialized = False
```

- [ ] **Step 2: Run tests**

```bash
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_tracker.py -v
```

Expected: Tests run (some may fail on edge cases — note them).

- [ ] **Step 3: Commit**

```bash
git add tests/test_tracker.py
git commit -m "test: unit tests for brier_score, get_bias in tracker (#111)"
```

---

### Task 4: Integration test for full analyze pipeline (#112)

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/test_integration.py`:

```python
"""Integration test: market flows through enrich → analyze → result."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from unittest.mock import patch, MagicMock
from datetime import date


SAMPLE_MARKET = {
    "ticker": "KXHIGHNY-26APR09-T72",
    "title": "NYC High > 72°F",
    "yes_bid": 0.60,
    "yes_ask": 0.64,
    "last_price": 0.62,
    "volume": 1000,
    "open_interest": 3000,
    "close_time": "2026-04-09T23:59:00Z",
    "status": "open",
    "city": "NYC",
    "condition_type": "HIGH",
    "threshold_lo": 72,
    "threshold_hi": None,
    "market_date": "2026-04-09",
}

SAMPLE_FORECAST = {
    "high": 74.5,
    "low": 58.2,
    "precip_prob": 0.10,
    "precip_inches": 0.0,
    "ensemble_spread": 3.0,
}


class TestAnalyzePipeline:
    def test_analyze_trade_returns_result(self):
        """analyze_trade should return a dict with 'our_prob' and 'edge' keys."""
        with patch("weather_markets.get_weather_forecast", return_value=SAMPLE_FORECAST), \
             patch("weather_markets.get_ensemble_stats", return_value={"mean": 74.5, "std": 3.0, "members": list(range(10))}), \
             patch("climatology.climatological_prob", return_value=0.55), \
             patch("nws.nws_prob", return_value=0.60):
            from weather_markets import analyze_trade
            result = analyze_trade(SAMPLE_MARKET)

        assert result is not None, "analyze_trade should return a result"
        assert "our_prob" in result, "result must have our_prob"
        assert "edge" in result, "result must have edge"
        assert 0.0 <= result["our_prob"] <= 1.0, "our_prob must be a valid probability"

    def test_analyze_trade_handles_missing_forecast(self):
        """analyze_trade should not crash if forecast data is unavailable."""
        with patch("weather_markets.get_weather_forecast", return_value=None), \
             patch("weather_markets.get_ensemble_stats", return_value=None), \
             patch("climatology.climatological_prob", return_value=0.50):
            from weather_markets import analyze_trade
            result = analyze_trade(SAMPLE_MARKET)
        # Should return None or a dict — must not raise
        assert result is None or isinstance(result, dict)
```

- [ ] **Step 2: Run integration tests**

```bash
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_integration.py -v
```

Expected: Tests pass or reveal specific integration issues to fix.

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: integration test for analyze_trade end-to-end pipeline (#112)"
```

---

### Task 5: Brier regression baseline test (#113)

**Files:**
- Create: `tests/test_regression.py`
- Create: `tests/fixtures/regression_baseline.json`

- [ ] **Step 1: Generate baseline (run once, commit the output)**

```bash
cd "C:/Users/thesa/claude kalshi"
python - <<'EOF'
import json, sys
sys.path.insert(0, ".")
from tracker import brier_score, get_roc_auc
bs = brier_score()
roc = get_roc_auc()
print(json.dumps({"brier_score": bs, "roc_auc": roc}))
EOF
```

Save the output to `tests/fixtures/regression_baseline.json`. If there's no data yet, use:
```json
{"brier_score": null, "roc_auc": null}
```

- [ ] **Step 2: Write regression test**

Create `tests/test_regression.py`:

```python
"""Regression test: Brier score must not degrade more than 1% after refactors."""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from pathlib import Path
import pytest

BASELINE_FILE = Path(__file__).parent / "fixtures" / "regression_baseline.json"
TOLERANCE = 0.01  # 1% degradation allowed


def test_brier_score_not_degraded():
    baseline = json.loads(BASELINE_FILE.read_text())
    baseline_bs = baseline.get("brier_score")
    if baseline_bs is None:
        pytest.skip("No baseline Brier score yet — run with real data first")

    from tracker import brier_score
    current = brier_score()
    assert current is not None, "brier_score() returned None — no data?"
    assert current <= baseline_bs + TOLERANCE, (
        f"Brier score degraded: {current:.4f} vs baseline {baseline_bs:.4f} "
        f"(tolerance {TOLERANCE})"
    )


def test_roc_auc_not_degraded():
    baseline = json.loads(BASELINE_FILE.read_text())
    baseline_roc = baseline.get("roc_auc")
    if baseline_roc is None:
        pytest.skip("No baseline ROC-AUC yet")

    from tracker import get_roc_auc
    current = get_roc_auc()
    assert current is not None
    assert current >= baseline_roc - TOLERANCE, (
        f"ROC-AUC degraded: {current:.4f} vs baseline {baseline_roc:.4f}"
    )
```

- [ ] **Step 3: Run regression tests**

```bash
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_regression.py -v
```

Expected: SKIP (no data) or PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_regression.py tests/fixtures/regression_baseline.json
git commit -m "test: regression baseline for Brier score and ROC-AUC (#113)"
```

---

### Final: Run full test suite

- [ ] **Run everything**

```bash
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All tests pass or skip. Zero errors.

- [ ] **Commit if any fixes were needed**

```bash
git add -A
git commit -m "test: fix remaining test issues, full suite green"
```
