# Group A: Testing Foundation Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill the three remaining test gaps so all subsequent refactoring phases have a safety net.

**Architecture:** Add to existing test files — no new files needed. Each task appends a class to an existing test module and commits.

**Tech Stack:** pytest, unittest.mock, tempfile (stdlib)

**Covers:** #111 (ensemble_stats + _bootstrap_ci unit tests), #112 (below + precip integration tests), #113 (deterministic regression tests on seeded DB)

---

## Current state (read before starting)

- `tests/test_weather_markets.py` — 31 passing tests. Missing: `TestEnsembleStats`, `TestBootstrapCI`.
- `tests/test_integration.py` — 6 passing tests for `analyze_trade` (above condition only). Missing: below + precip paths.
- `tests/test_regression.py` — 2 tests that always skip (baseline JSON has null values). Missing: deterministic regression with seeded DB.
- Run tests: `python -m pytest --ignore=tests/test_http.py` from project root.

---

## File map

| File | Action | What changes |
|------|--------|--------------|
| `tests/test_weather_markets.py` | Append | Add `TestEnsembleStats` class (6 tests) and `TestBootstrapCI` class (5 tests) |
| `tests/test_integration.py` | Append | Add `TestAnalyzePipelineExtra` class with below + precip tests (3 tests) |
| `tests/test_regression.py` | Append | Add `TestBrierScoreComputation` class (3 deterministic tests with seeded DB) |

---

### Task 1: `ensemble_stats` unit tests (#111)

**Files:**
- Modify: `tests/test_weather_markets.py` (append after last test)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_weather_markets.py`:

```python
# ── TestEnsembleStats ─────────────────────────────────────────────────────────


class TestEnsembleStats:
    def test_empty_list_returns_empty_dict(self):
        """ensemble_stats([]) must return {} not raise."""
        from weather_markets import ensemble_stats

        result = ensemble_stats([])
        assert result == {}

    def test_single_element_std_is_zero(self):
        """Single-element ensemble: std=0, min=max=mean=the value."""
        from weather_markets import ensemble_stats

        result = ensemble_stats([75.0])
        assert result["n"] == 1
        assert result["mean"] == pytest.approx(75.0)
        assert result["std"] == pytest.approx(0.0)
        assert result["min"] == pytest.approx(75.0)
        assert result["max"] == pytest.approx(75.0)
        assert result["p10"] == pytest.approx(75.0)
        assert result["p90"] == pytest.approx(75.0)

    def test_returns_all_required_keys(self):
        """Result must contain n, mean, std, min, max, p10, p90."""
        from weather_markets import ensemble_stats

        result = ensemble_stats([60.0, 65.0, 70.0, 75.0, 80.0])
        for key in ("n", "mean", "std", "min", "max", "p10", "p90"):
            assert key in result, f"Missing key: {key}"

    def test_mean_std_correct(self):
        """Verify mean and std match statistics module on known data."""
        import statistics

        from weather_markets import ensemble_stats

        temps = [68.0, 70.0, 72.0, 74.0, 76.0]
        result = ensemble_stats(temps)
        assert result["mean"] == pytest.approx(statistics.mean(temps))
        assert result["std"] == pytest.approx(statistics.stdev(temps), rel=1e-6)

    def test_min_max_correct(self):
        """min and max match the actual extremes."""
        from weather_markets import ensemble_stats

        temps = [55.0, 70.0, 80.0, 63.0, 71.0]
        result = ensemble_stats(temps)
        assert result["min"] == pytest.approx(55.0)
        assert result["max"] == pytest.approx(80.0)

    def test_p10_less_than_p90(self):
        """p10 <= mean <= p90 for a non-degenerate ensemble."""
        from weather_markets import ensemble_stats

        temps = list(range(60, 80))  # [60, 61, ..., 79], 20 values
        result = ensemble_stats(temps)
        assert result["p10"] <= result["mean"]
        assert result["mean"] <= result["p90"]
        assert result["p10"] < result["p90"]
```

- [ ] **Step 2: Run to confirm they pass**

```bash
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_weather_markets.py::TestEnsembleStats -v
```

Expected:
```
PASSED tests/test_weather_markets.py::TestEnsembleStats::test_empty_list_returns_empty_dict
PASSED tests/test_weather_markets.py::TestEnsembleStats::test_single_element_std_is_zero
PASSED tests/test_weather_markets.py::TestEnsembleStats::test_returns_all_required_keys
PASSED tests/test_weather_markets.py::TestEnsembleStats::test_mean_std_correct
PASSED tests/test_weather_markets.py::TestEnsembleStats::test_min_max_correct
PASSED tests/test_weather_markets.py::TestEnsembleStats::test_p10_less_than_p90
6 passed
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_weather_markets.py
git commit -m "test: add TestEnsembleStats unit tests for ensemble_stats (#111)"
```

---

### Task 2: `_bootstrap_ci` unit tests (#111)

**Files:**
- Modify: `tests/test_weather_markets.py` (append after TestEnsembleStats)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_weather_markets.py`:

```python
# ── TestBootstrapCI ───────────────────────────────────────────────────────────


class TestBootstrapCI:
    """Tests for _bootstrap_ci — bootstrap 90% CI on ensemble probability."""

    def test_too_few_members_returns_wide_ci(self):
        """N < 5 → maximally uncertain (0.0, 1.0)."""
        from weather_markets import _bootstrap_ci

        temps = [70.0, 71.0, 72.0]  # only 3 members
        condition = {"type": "above", "threshold": 68.0}
        lo, hi = _bootstrap_ci(temps, condition)
        assert lo == pytest.approx(0.0)
        assert hi == pytest.approx(1.0)

    def test_small_n_under_30_returns_wide_ci(self):
        """N < 30 but >= 5 → also returns (0.0, 1.0) per #114."""
        from weather_markets import _bootstrap_ci

        temps = list(range(60, 75))  # 15 members
        condition = {"type": "above", "threshold": 68.0}
        lo, hi = _bootstrap_ci(temps, condition)
        assert lo == pytest.approx(0.0)
        assert hi == pytest.approx(1.0)

    def test_above_condition_clear_outcome(self):
        """N >= 30, all temps above threshold → CI near (1.0, 1.0)."""
        from weather_markets import _bootstrap_ci

        temps = [80.0] * 40  # 40 members all above 70
        condition = {"type": "above", "threshold": 70.0}
        lo, hi = _bootstrap_ci(temps, condition, n=200)
        assert lo >= 0.9, f"Expected lo near 1.0, got {lo}"
        assert hi == pytest.approx(1.0, abs=1e-9)

    def test_below_condition_returns_valid_tuple(self):
        """'below' condition: returns (lo, hi) with 0 <= lo <= hi <= 1."""
        from weather_markets import _bootstrap_ci

        temps = list(range(50, 90))  # 40 members spanning 50–89°F
        condition = {"type": "below", "threshold": 70.0}
        lo, hi = _bootstrap_ci(temps, condition, n=200)
        assert 0.0 <= lo <= hi <= 1.0

    def test_between_condition_returns_valid_tuple(self):
        """'between' condition: returns (lo, hi) with 0 <= lo <= hi <= 1."""
        from weather_markets import _bootstrap_ci

        temps = list(range(60, 100))  # 40 members spanning 60–99°F
        condition = {"type": "between", "lower": 70.0, "upper": 80.0}
        lo, hi = _bootstrap_ci(temps, condition, n=200)
        assert 0.0 <= lo <= hi <= 1.0
```

- [ ] **Step 2: Run to confirm they pass**

```bash
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_weather_markets.py::TestBootstrapCI -v
```

Expected:
```
PASSED tests/test_weather_markets.py::TestBootstrapCI::test_too_few_members_returns_wide_ci
PASSED tests/test_weather_markets.py::TestBootstrapCI::test_small_n_under_30_returns_wide_ci
PASSED tests/test_weather_markets.py::TestBootstrapCI::test_above_condition_clear_outcome
PASSED tests/test_weather_markets.py::TestBootstrapCI::test_below_condition_returns_valid_tuple
PASSED tests/test_weather_markets.py::TestBootstrapCI::test_between_condition_returns_valid_tuple
5 passed
```

- [ ] **Step 3: Run the full weather_markets test file to confirm no regressions**

```bash
python -m pytest tests/test_weather_markets.py -v --tb=short 2>&1 | tail -10
```

Expected: All 42 tests pass (31 original + 6 ensemble_stats + 5 bootstrap_ci).

- [ ] **Step 4: Commit**

```bash
git add tests/test_weather_markets.py
git commit -m "test: add TestBootstrapCI unit tests for _bootstrap_ci (#111)"
```

---

### Task 3: Integration tests — below and precip conditions (#112)

**Files:**
- Modify: `tests/test_integration.py` (append after existing `TestAnalyzePipeline` class)

The existing `TestAnalyzePipeline` already tests `analyze_trade` for the "above" condition. We need tests for:
- A LOW market (below condition) — `series_ticker = "KXLOWNY"`, ticker `"KXLOWNY-26APR15-T55"`
- A precipitation market (precip_any) — `ticker = "KXRAIN-26APR15"`, `series_ticker = "KXRAIN"`

Look at how `analyze_trade` dispatches:
- For precip: detects via `series_ticker` containing "KXRAIN" → calls `_analyze_precip_trade`
- For below: ticker suffix `-T55` on a `KXLOWNY` series → condition type "below"

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_integration.py`:

```python
class TestAnalyzePipelineExtra:
    """Additional integration tests for below + precip conditions (#112)."""

    @patch("weather_markets.get_live_observation", return_value=None)
    @patch("weather_markets.nws_prob", return_value=0.45)
    @patch("weather_markets.climatological_prob", return_value=0.40)
    @patch("weather_markets.temperature_adjustment", return_value=0.0)
    @patch(
        "weather_markets.get_ensemble_temps",
        return_value=[
            50.0, 51.0, 52.0, 53.0, 54.0, 55.0, 56.0, 57.0, 58.0, 59.0, 60.0, 61.0,
        ],
    )
    def test_analyze_trade_below_condition(
        self, mock_ens, mock_temp_adj, mock_clim, mock_nws, mock_obs
    ):
        """analyze_trade handles a LOW market (below condition) correctly."""
        from weather_markets import analyze_trade

        enriched = _make_enriched(
            ticker="KXLOWNY-26APR15-T55",
            city="NYC",
            target_date=date(2026, 4, 15),
            forecast={"high_f": 68.0, "low_f": 52.0, "precip_in": 0.0,
                      "date": "2026-04-15"},
        )
        enriched["series_ticker"] = "KXLOWNY"

        result = analyze_trade(enriched)

        assert result is not None, "below condition should return a result"
        assert "forecast_prob" in result
        assert 0.0 <= result["forecast_prob"] <= 1.0
        assert result["condition"]["type"] == "below"

    @patch("weather_markets.get_live_observation", return_value=None)
    @patch(
        "weather_markets.get_ensemble_precip",
        return_value=[0.0, 0.0, 0.05, 0.12, 0.0, 0.0, 0.08, 0.0, 0.0, 0.0, 0.15, 0.0],
    )
    @patch("weather_markets.climatological_prob", return_value=0.30)
    def test_analyze_trade_precip_any_condition(
        self, mock_clim, mock_ens_precip, mock_obs
    ):
        """analyze_trade handles a precip_any (any rain) market correctly."""
        from weather_markets import analyze_trade

        enriched = _make_enriched(
            ticker="KXRAIN-26APR15",
            city="NYC",
            target_date=date(2026, 4, 15),
            forecast={"high_f": 68.0, "low_f": 55.0, "precip_in": 0.02,
                      "date": "2026-04-15"},
        )
        enriched["series_ticker"] = "KXRAIN"
        enriched["title"] = "Will there be any measurable rain in NYC on Apr 15?"

        result = analyze_trade(enriched)

        # Precip markets may or may not return a result depending on ensemble data
        # but must never raise
        assert result is None or isinstance(result, dict)
        if result is not None:
            assert "forecast_prob" in result
            assert 0.0 <= result["forecast_prob"] <= 1.0

    @patch("weather_markets.get_live_observation", return_value=None)
    @patch("weather_markets.nws_prob", return_value=0.70)
    @patch("weather_markets.climatological_prob", return_value=0.65)
    @patch("weather_markets.temperature_adjustment", return_value=0.0)
    @patch(
        "weather_markets.get_ensemble_temps",
        return_value=[
            70.0, 71.0, 72.0, 73.0, 68.0, 69.0, 71.5, 70.5, 72.5, 67.0, 70.0, 71.0,
        ],
    )
    def test_analyze_trade_signal_is_valid(
        self, mock_ens, mock_temp_adj, mock_clim, mock_nws, mock_obs
    ):
        """signal field must be one of BUY / SELL / PASS."""
        from weather_markets import analyze_trade

        enriched = _make_enriched()
        result = analyze_trade(enriched)

        assert result is not None
        assert "signal" in result
        assert result["signal"] in ("BUY", "SELL", "PASS"), (
            f"Unexpected signal: {result['signal']!r}"
        )
```

- [ ] **Step 2: Check that `get_ensemble_precip` exists in weather_markets.py**

```bash
cd "C:/Users/thesa/claude kalshi"
python -c "from weather_markets import get_ensemble_precip; print('ok')"
```

If this raises `ImportError`, the precip test must patch `weather_markets._analyze_precip_trade` instead. In that case replace the precip test's `@patch` decorator:

```python
@patch("weather_markets.get_live_observation", return_value=None)
@patch(
    "weather_markets._analyze_precip_trade",
    return_value={"forecast_prob": 0.30, "market_prob": 0.35, "edge": -0.05,
                  "signal": "PASS", "recommended_side": "NO",
                  "condition": {"type": "precip_any"}, "method": "ensemble",
                  "data_quality": 0.7},
)
def test_analyze_trade_precip_any_condition(self, mock_precip, mock_obs):
    """analyze_trade routes precip_any markets through _analyze_precip_trade."""
    from weather_markets import analyze_trade

    enriched = _make_enriched(
        ticker="KXRAIN-26APR15",
        city="NYC",
        target_date=date(2026, 4, 15),
        forecast={"high_f": 68.0, "low_f": 55.0, "precip_in": 0.02,
                  "date": "2026-04-15"},
    )
    enriched["series_ticker"] = "KXRAIN"
    enriched["title"] = "Will there be any measurable rain in NYC on Apr 15?"

    result = analyze_trade(enriched)

    assert result is not None
    assert result["condition"]["type"] == "precip_any"
    assert "forecast_prob" in result
```

- [ ] **Step 3: Run to confirm all tests pass**

```bash
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_integration.py -v --tb=short
```

Expected:
```
PASSED test_analyze_trade_returns_result
PASSED test_analyze_trade_handles_missing_forecast
PASSED test_analyze_trade_works_without_nws_or_clim
PASSED test_analyze_trade_missing_city_returns_none
PASSED test_analyze_trade_missing_date_returns_none
PASSED test_analyze_trade_invalid_input_raises
PASSED test_analyze_trade_below_condition
PASSED test_analyze_trade_precip_any_condition
PASSED test_analyze_trade_signal_is_valid
9 passed
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add below + precip integration tests for analyze_trade (#112)"
```

---

### Task 4: Deterministic regression tests with seeded DB (#113)

**Goal:** The existing `test_regression.py` always skips because `regression_baseline.json` has null values. Add a class that seeds an in-memory tracker DB with known predictions+outcomes and verifies `brier_score()` and `get_roc_auc()` return mathematically correct values. This catches any future change to the computation formulas.

**Files:**
- Modify: `tests/test_regression.py` (append after existing tests)

**Math check** (use as expected values in tests):

Brier score = mean((our_prob − outcome)²)

4 predictions: probs=[0.9, 0.1, 0.8, 0.2], outcomes=[True, False, True, False]
BS = ((0.9−1)² + (0.1−0)² + (0.8−1)² + (0.2−0)²) / 4
   = (0.01 + 0.01 + 0.04 + 0.04) / 4 = 0.10 / 4 = **0.025**

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_regression.py`:

```python
import shutil
import tempfile
from datetime import date
from pathlib import Path

import tracker


class TestBrierScoreComputation:
    """Deterministic regression tests using a seeded in-memory DB (#113).

    These tests verify that brier_score() and get_roc_auc() produce the
    mathematically correct value on known data. If the formula changes, these
    will catch it.
    """

    def setup_method(self):
        """Redirect tracker to a fresh temp DB before each test."""
        self._tmpdir = tempfile.mkdtemp()
        self._orig_path = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test.db"
        tracker._db_initialized = False

    def teardown_method(self):
        tracker.DB_PATH = self._orig_path
        tracker._db_initialized = False
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _seed(self, probs_outcomes: list[tuple[str, float, bool]]) -> None:
        """Log predictions+outcomes into the temp DB.

        Each tuple is (ticker_suffix, our_prob, settled_yes).
        """
        for suffix, prob, outcome in probs_outcomes:
            ticker = f"KXTEST-{suffix}"
            tracker.log_prediction(
                ticker,
                "NYC",
                date(2026, 4, 10),
                {
                    "forecast_prob": prob,
                    "market_prob": 0.5,
                    "edge": prob - 0.5,
                    "method": "ensemble",
                    "n_members": 12,
                    "condition": {"type": "above", "threshold": 70.0},
                },
            )
            tracker.log_outcome(ticker, settled_yes=outcome)

    def test_brier_score_known_value(self):
        """BS on [0.9→YES, 0.1→NO, 0.8→YES, 0.2→NO] must equal 0.025."""
        self._seed([
            ("A", 0.9, True),
            ("B", 0.1, False),
            ("C", 0.8, True),
            ("D", 0.2, False),
        ])
        result = tracker.brier_score()
        assert result is not None
        assert result == pytest.approx(0.025, abs=1e-6), (
            f"Expected Brier=0.025, got {result}"
        )

    def test_brier_score_no_data_returns_none(self):
        """brier_score() on empty DB returns None (not 0.0, not error)."""
        result = tracker.brier_score()
        assert result is None

    def test_roc_auc_perfect_classifier(self):
        """AUC=1.0 when high probs always → YES and low probs always → NO."""
        self._seed([
            ("E1", 0.9, True),
            ("E2", 0.85, True),
            ("E3", 0.80, True),
            ("E4", 0.75, True),
            ("E5", 0.70, True),
            ("E6", 0.20, False),
            ("E7", 0.15, False),
            ("E8", 0.10, False),
            ("E9", 0.05, False),
            ("E10", 0.02, False),
        ])
        result = tracker.get_roc_auc()
        assert result["auc"] is not None
        assert result["auc"] == pytest.approx(1.0, abs=1e-6), (
            f"Expected AUC=1.0 for perfect classifier, got {result['auc']}"
        )
```

- [ ] **Step 2: Run to confirm all three tests pass**

```bash
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_regression.py -v --tb=short
```

Expected:
```
SKIPPED  test_brier_score_not_degraded (No baseline Brier score yet)
SKIPPED  test_roc_auc_not_degraded (No baseline ROC-AUC yet)
PASSED   TestBrierScoreComputation::test_brier_score_known_value
PASSED   TestBrierScoreComputation::test_brier_score_no_data_returns_none
PASSED   TestBrierScoreComputation::test_roc_auc_perfect_classifier
2 skipped, 3 passed
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_regression.py
git commit -m "test: add deterministic Brier/ROC regression tests with seeded DB (#113)"
```

---

### Task 5: Full suite green-check

- [ ] **Step 1: Run the full suite**

```bash
cd "C:/Users/thesa/claude kalshi"
python -m pytest --ignore=tests/test_http.py -v --tb=short 2>&1 | tail -20
```

Expected: All tests pass (or skip for baseline/missing-responses reasons). Zero new failures vs. the 15 pre-existing failures in `test_paper.py` (13) and `test_weather.py` (2).

- [ ] **Step 2: Commit if anything was fixed**

Only commit if you had to make additional fixes. Otherwise this step is done.

---

## Self-review

**Spec coverage:**
- #111 `ensemble_stats` tests → Task 1 ✓
- #111 `_bootstrap_ci` tests → Task 2 ✓
- #111 `analyze_trade edge cases` → covered by existing tests (already passing) ✓
- #112 full pipeline integration → Task 3 adds below + precip + signal validation ✓
- #113 regression test loading historical markets → Task 4 uses seeded DB to verify formula ✓

**Placeholder scan:** No TBDs, all code blocks are complete.

**Type consistency:** `_make_enriched` helper defined in `test_integration.py` at module level (already exists, reused by new class). `tracker.log_prediction` signature matches actual function. `tracker.log_outcome` matches actual function.
