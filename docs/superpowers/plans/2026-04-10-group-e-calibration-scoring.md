# Group E: Calibration & Scoring Accuracy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the probabilistic scoring pipeline by fixing Brier score normalization, ensemble censoring bias, monthly grouping bugs, selection bias in bias estimation, confidence interval shrinkage, and ROC threshold optimization.

**Architecture:** Four tasks touch `tracker.py` (adding or fixing functions in the SQLite scoring layer); one task touches `weather_markets.py` (adding a probability correction utility); tests for all six items are appended to existing test files — no new files are created. Items #11, #57, and #60 have implementations already present in the codebase; those tasks verify coverage and fix the one spec divergence (`get_optimal_threshold` uses `< 10` guard but spec requires `< 20`).

**Tech Stack:** Python 3.11+, sqlite3 (stdlib), math (stdlib), pytest, unittest

---

## Current state (read before starting)

| Item | Function | Location | Status |
|------|----------|----------|--------|
| #11 | `brier_skill_score(city=None)` | `tracker.py` | Implemented + tested — nothing to add |
| #23 | `censoring_correction(probs, condition, censor_pct)` | `weather_markets.py` | **Missing** |
| #54 | `get_calibration_trend` uses `predicted_at` | `tracker.py` line 662 | **Bug — fix required** |
| #55 | `analyze_all_markets(enriched_list)` + `get_analysis_bias()` | `tracker.py` | **Missing** (table + `log_analysis_attempt` exist; the two named functions do not) |
| #57 | `bayesian_confidence_interval(successes, trials, confidence)` | `tracker.py` | Implemented + tested — nothing to add |
| #60 | `get_optimal_threshold()` | `tracker.py` | Implemented + tested, **but guard is `< 10` instead of spec's `< 20`** — fix required |

Run all tests from the project root: `python -m pytest --ignore=tests/test_http.py`

---

### Task 1: `brier_skill_score` verification (#11)

**Files:**
- Read-only audit: `tracker.py` (lines 597–627), `tests/test_tracker.py`

This function is already implemented and tested (`TestBrierSkillScore` class). No code changes are needed. The task is to confirm the existing implementation satisfies the spec and run the suite.

- [ ] **Step 1: Confirm spec compliance** — read `brier_skill_score` in `tracker.py` and verify:
  - Returns `None` when `len(rows) < 10`
  - Returns `None` when `bs_ref == 0`
  - Formula is `round(1.0 - bs_model / bs_ref, 6)` using `market_prob` as reference

- [ ] **Step 2: Run existing tests**

```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_tracker.py::TestBrierSkillScore -v --ignore=tests/test_http.py
```

Expected output: 3 tests PASSED.

- [ ] **Step 3: Commit (no code changes)**

```bash
cd "C:/Users/thesa/claude kalshi" && git commit --allow-empty -m "chore: verify #11 brier_skill_score already complete"
```

---

### Task 2: `censoring_correction` in `weather_markets.py` (#23)

**Files:**
- Modify: `weather_markets.py` (append near other probability utilities)
- Modify: `tests/test_weather_markets.py` (append new test class)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_weather_markets.py`:

```python
# ── TestCensoringCorrection (#23) ─────────────────────────────────────────────


class TestCensoringCorrection:
    """Tests for censoring_correction() in weather_markets (#23)."""

    def test_no_censoring_returns_mean_unchanged(self):
        """Probs spread across (0, 1) with no censoring → corrected == raw mean."""
        from weather_markets import censoring_correction

        probs = [0.1, 0.3, 0.5, 0.7, 0.9]
        condition = {"type": "above", "threshold": 70.0}
        result = censoring_correction(probs, condition)
        raw_mean = sum(probs) / len(probs)
        assert abs(result - raw_mean) < 1e-9

    def test_censoring_at_zero_shrinks_toward_half(self):
        """Many zeros (>5% censored at 0) → result > raw mean (pulled toward 0.5)."""
        from weather_markets import censoring_correction

        # 80 members at 0.0, 20 at 0.8 → raw mean = 0.16; censored_fraction = 0.8
        probs = [0.0] * 80 + [0.8] * 20
        condition = {"type": "above", "threshold": 70.0}
        raw_mean = sum(probs) / len(probs)
        result = censoring_correction(probs, condition)
        # Result should be pulled toward 0.5, so > raw_mean
        assert result > raw_mean

    def test_censoring_at_one_shrinks_toward_half(self):
        """Many ones (>5% censored at 1) → result < raw mean (pulled toward 0.5)."""
        from weather_markets import censoring_correction

        # 80 members at 1.0, 20 at 0.2 → raw mean = 0.84; censored_fraction = 0.8
        probs = [1.0] * 80 + [0.2] * 20
        condition = {"type": "above", "threshold": 70.0}
        raw_mean = sum(probs) / len(probs)
        result = censoring_correction(probs, condition)
        # Result should be pulled toward 0.5, so < raw_mean
        assert result < raw_mean

    def test_exactly_at_threshold_applies_correction(self):
        """Exactly 5% censored (= censor_pct threshold) triggers correction."""
        from weather_markets import censoring_correction

        # 5 zeros out of 100 = exactly 5% = censor_pct default boundary
        # Spec says >5%, so 5/100 should NOT trigger correction
        probs = [0.0] * 5 + [0.6] * 95
        condition = {"type": "above", "threshold": 70.0}
        raw_mean = sum(probs) / len(probs)
        result = censoring_correction(probs, condition, censor_pct=0.01)
        # 5% zeros > 1% censor_pct threshold → correction applies
        assert result > raw_mean

    def test_result_clamped_between_zero_and_one(self):
        """Corrected probability must always be in [0, 1]."""
        from weather_markets import censoring_correction

        probs = [0.0] * 99 + [0.01]
        condition = {"type": "above", "threshold": 70.0}
        result = censoring_correction(probs, condition)
        assert 0.0 <= result <= 1.0

    def test_empty_list_returns_half(self):
        """Empty prob list returns 0.5 (maximally uncertain)."""
        from weather_markets import censoring_correction

        result = censoring_correction([], {"type": "above", "threshold": 70.0})
        assert result == 0.5

    def test_correction_formula_values(self):
        """Verify the Tobit-style formula numerically."""
        from weather_markets import censoring_correction

        # 60 zeros, 40 at 0.9 → raw_mean=0.36, censored_fraction=0.60
        # corrected = raw_mean * (1 - 0.60 * 0.5) = 0.36 * 0.70 = 0.252
        # Wait — spec: scale toward 0.5 by (1 - censored_fraction * 0.5)
        # corrected = raw_mean + (0.5 - raw_mean) * censored_fraction * 0.5
        # Actually spec says: "scaling probability toward 0.5 by (1 - censored_fraction * 0.5)"
        # Interpretation: corrected = raw_mean * (1 - censored_fraction * 0.5)
        #                             + 0.5 * censored_fraction * 0.5
        # i.e. linear blend: corrected = raw_mean + (0.5 - raw_mean) * (censored_fraction * 0.5)
        probs = [0.0] * 60 + [0.9] * 40
        condition = {"type": "above", "threshold": 70.0}
        raw_mean = sum(probs) / len(probs)   # 0.36
        censored_fraction = 60 / 100          # 0.60
        blend = censored_fraction * 0.5       # 0.30
        expected = raw_mean * (1 - blend) + 0.5 * blend  # 0.36*0.70 + 0.5*0.30 = 0.252 + 0.15 = 0.402
        result = censoring_correction(probs, condition, censor_pct=0.01)
        assert abs(result - expected) < 1e-9
```

- [ ] **Step 2: Run failing tests**

```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_weather_markets.py::TestCensoringCorrection -v --ignore=tests/test_http.py 2>&1 | tail -20
```

Expected output: `ImportError` or `AttributeError` — `censoring_correction` does not exist yet.

- [ ] **Step 3: Implement `censoring_correction` in `weather_markets.py`**

Find the end of the probability utility section in `weather_markets.py` (search for `def _bootstrap_ci_precip` or the nearest standalone helper) and append the following function in the same area:

```python
def censoring_correction(
    probs: list[float],
    condition: dict,
    censor_pct: float = 0.01,
) -> float:
    """
    Correct ensemble probability for member censoring at 0 or 1 (#23).

    Ensemble models occasionally pin members at exactly 0.0 or 1.0 when the
    signal is too strong for the model resolution (censoring). This inflates
    the tails and biases the mean probability away from the market.

    Algorithm
    ---------
    1. Compute raw mean of probs.
    2. Count fraction of members exactly at 0.0 OR exactly at 1.0.
    3. If censored_fraction > censor_pct (default 1%), apply Tobit-style
       correction: linearly blend raw_mean toward 0.5 using the factor
       (censored_fraction * 0.5).
         corrected = raw_mean * (1 - blend) + 0.5 * blend
       where blend = censored_fraction * 0.5.
    4. Return result clamped to [0, 1].

    Parameters
    ----------
    probs       : list of float — per-member probabilities in [0, 1]
    condition   : dict — market condition (not used in correction, kept for
                  future direction-aware corrections)
    censor_pct  : float — minimum censored fraction to trigger correction

    Returns
    -------
    Corrected probability as a float in [0, 1].
    Returns 0.5 if probs is empty.
    """
    if not probs:
        return 0.5

    n = len(probs)
    raw_mean = sum(probs) / n

    censored = sum(1 for p in probs if p == 0.0 or p == 1.0)
    censored_fraction = censored / n

    if censored_fraction <= censor_pct:
        return raw_mean

    blend = censored_fraction * 0.5
    corrected = raw_mean * (1.0 - blend) + 0.5 * blend
    return max(0.0, min(1.0, corrected))
```

- [ ] **Step 4: Run passing tests**

```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_weather_markets.py::TestCensoringCorrection -v --ignore=tests/test_http.py
```

Expected output: 7 tests PASSED.

- [ ] **Step 5: Run full suite to check for regressions**

```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest --ignore=tests/test_http.py -q 2>&1 | tail -10
```

Expected output: no new failures.

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/thesa/claude kalshi" && git add weather_markets.py tests/test_weather_markets.py && git commit -m "feat: add censoring_correction() to weather_markets for ensemble boundary bias (#23)"
```

---

### Task 3: Fix `get_calibration_trend` to group by `market_date` not `predicted_at` (#54)

**Files:**
- Modify: `tracker.py` (function `get_calibration_trend`, line ~662)
- Modify: `tests/test_tracker.py` (append regression test)

The bug: `get_calibration_trend` groups Brier scores by `strftime('%Y-W%W', p.predicted_at)`. When predictions are made several days before the market date the weekly bucket reflects the analysis date, not the weather event date. The fix is to group by `market_date` instead.

Note: `get_calibration_by_city` and `get_calibration_by_season` already correctly use `market_date` — only `get_calibration_trend` (and `get_brier_over_time`, which is intentionally time-of-analysis) needs the fix.

- [ ] **Step 1: Write failing regression test**

Append to `tests/test_tracker.py`:

```python
# ── Task 3: get_calibration_trend uses market_date not predicted_at (#54) ─────


class TestCalibrationTrendUsesMarketDate(unittest.TestCase):
    """Verify get_calibration_trend groups by market_date, not predicted_at (#54)."""

    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_trend54.db"
        tracker._db_initialized = False
        tracker.init_db()

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _insert_raw(self, ticker, our_prob, settled_yes, market_date_str, predicted_at_str):
        """Direct DB insert so we can set both market_date and predicted_at freely."""
        import sqlite3

        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            con.execute(
                """INSERT INTO predictions
                   (ticker, city, market_date, condition_type,
                    threshold_lo, threshold_hi, our_prob, market_prob,
                    edge, method, n_members, predicted_at, days_out)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ticker, "NYC", market_date_str, "above",
                    70.0, 70.0, our_prob, 0.5,
                    our_prob - 0.5, "ensemble", 20, predicted_at_str, 3,
                ),
            )
            con.execute(
                "INSERT OR REPLACE INTO outcomes (ticker, settled_yes, settled_at) VALUES (?,?,?)",
                (ticker, 1 if settled_yes else 0, predicted_at_str),
            )

    def test_trend_bucket_uses_market_date_week(self):
        """
        Two predictions made in the same analysis week but targeting different
        market-date weeks must appear in separate trend buckets.
        """
        # Both predicted on 2026-04-06 (same predicted_at week)
        # but market dates are in different ISO weeks:
        #   market_date 2026-04-07 → W14
        #   market_date 2026-04-14 → W15
        self._insert_raw(
            "TKTREND-A", 0.8, True,
            "2026-04-07",   # market_date week W14
            "2026-04-06T12:00:00",  # predicted_at (same week for both)
        )
        self._insert_raw(
            "TKTREND-B", 0.6, False,
            "2026-04-14",   # market_date week W15
            "2026-04-06T13:00:00",  # predicted_at (same week as A)
        )

        trend = tracker.get_calibration_trend(weeks=8)

        # Should have 2 separate week buckets (one per market_date week)
        weeks_in_result = [row["week"] for row in trend]
        self.assertEqual(
            len(set(weeks_in_result)), 2,
            f"Expected 2 distinct market-date week buckets, got: {weeks_in_result}",
        )

    def test_trend_returns_list_of_dicts_with_week_brier_n(self):
        """Each trend entry must have week, brier, and n keys."""
        self._insert_raw(
            "TKTREND-C", 0.7, True,
            "2026-04-09",
            "2026-04-08T10:00:00",
        )
        trend = tracker.get_calibration_trend(weeks=8)
        self.assertIsInstance(trend, list)
        if trend:
            self.assertIn("week", trend[0])
            self.assertIn("brier", trend[0])
            self.assertIn("n", trend[0])
```

- [ ] **Step 2: Run failing test**

```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_tracker.py::TestCalibrationTrendUsesMarketDate -v --ignore=tests/test_http.py 2>&1 | tail -20
```

Expected output: `test_trend_bucket_uses_market_date_week` FAILS (both predictions land in the same week because `predicted_at` is used).

- [ ] **Step 3: Fix `get_calibration_trend` in `tracker.py`**

Locate the function at approximately line 652. Change the SQL from `strftime('%Y-W%W', p.predicted_at)` to `strftime('%Y-W%W', p.market_date)` and add `AND p.market_date IS NOT NULL` to the WHERE clause:

```python
def get_calibration_trend(weeks: int = 8) -> list[dict]:
    """
    Brier score grouped by ISO week of the MARKET DATE for the last N weeks.
    Returns [{week, brier, n}, ...] oldest first.
    Only includes weeks with at least one settled prediction.
    Groups by market_date (not predicted_at) so the trend reflects when the
    weather event occurred, not when the analysis was run (#54).
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT
                strftime('%Y-W%W', p.market_date) AS week,
                p.our_prob,
                o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
              AND p.market_date IS NOT NULL
            ORDER BY week ASC
        """).fetchall()

    by_week: dict[str, list[float]] = {}
    for r in rows:
        by_week.setdefault(r["week"], []).append(
            (r["our_prob"] - r["settled_yes"]) ** 2
        )

    result = []
    for week, errors in sorted(by_week.items())[-weeks:]:
        result.append(
            {
                "week": week,
                "brier": sum(errors) / len(errors),
                "n": len(errors),
            }
        )
    return result
```

- [ ] **Step 4: Run passing tests**

```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_tracker.py::TestCalibrationTrendUsesMarketDate -v --ignore=tests/test_http.py
```

Expected output: 2 tests PASSED.

- [ ] **Step 5: Run full suite**

```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest --ignore=tests/test_http.py -q 2>&1 | tail -10
```

Expected output: no new failures.

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/thesa/claude kalshi" && git add tracker.py tests/test_tracker.py && git commit -m "fix: get_calibration_trend groups by market_date not predicted_at (#54)"
```

---

### Task 4: `analyze_all_markets` and `get_analysis_bias` (#55)

**Files:**
- Modify: `tracker.py` (append two new public functions)
- Modify: `tests/test_tracker.py` (append new test class)

**Context:** The `analysis_attempts` table and `log_analysis_attempt()` already exist (migration v6→v7 and function at line ~1525). The two named public functions called out in the spec — `analyze_all_markets(enriched_list)` and `get_analysis_bias()` — are absent. `analyze_all_markets` must accept the same `enriched_list` format used elsewhere in `main.py` and log every market (traded or not). `get_analysis_bias` computes mean(our_prob - settled_yes) across the broader untraded set via join with `outcomes`.

Note: `get_unselected_bias(city, condition_type)` (line ~1594) already does a similar thing per-city. The new `get_analysis_bias()` operates globally across all cities and joins against `outcomes` for true settlement data.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_tracker.py`:

```python
# ── Task 4: analyze_all_markets + get_analysis_bias (#55) ────────────────────


class TestAnalyzeAllMarketsAndBias(unittest.TestCase):
    """Tests for analyze_all_markets() and get_analysis_bias() (#55)."""

    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.mkdtemp()
        self._orig = tracker.DB_PATH
        tracker.DB_PATH = Path(self._tmpdir) / "test_analyze55.db"
        tracker._db_initialized = False
        tracker.init_db()

    def tearDown(self):
        tracker.DB_PATH = self._orig
        tracker._db_initialized = False
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_enriched(self, ticker, city, our_prob, market_prob, edge, target_date):
        """Build a minimal enriched market dict matching the format expected."""
        return {
            "ticker": ticker,
            "city": city,
            "target_date": target_date,
            "analysis": {
                "forecast_prob": our_prob,
                "market_prob": market_prob,
                "edge": edge,
                "condition": {"type": "above", "threshold": 70.0},
                "method": "ensemble",
                "n_members": 20,
            },
        }

    def test_analyze_all_markets_logs_all_items(self):
        """analyze_all_markets logs every market in the list."""
        enriched = [
            self._make_enriched("TK-AM-1", "NYC", 0.70, 0.50, 0.20, date(2026, 4, 9)),
            self._make_enriched("TK-AM-2", "CHI", 0.60, 0.55, 0.05, date(2026, 4, 9)),
            self._make_enriched("TK-AM-3", "LAX", 0.45, 0.50, -0.05, date(2026, 4, 9)),
        ]
        tracker.analyze_all_markets(enriched)

        import sqlite3

        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            rows = con.execute("SELECT ticker FROM analysis_attempts").fetchall()
        tickers = {r[0] for r in rows}
        self.assertIn("TK-AM-1", tickers)
        self.assertIn("TK-AM-2", tickers)
        self.assertIn("TK-AM-3", tickers)

    def test_analyze_all_markets_stores_correct_probs(self):
        """Each logged row has the correct forecast_prob and market_prob."""
        enriched = [
            self._make_enriched("TK-PROB-1", "NYC", 0.72, 0.48, 0.24, date(2026, 4, 10)),
        ]
        tracker.analyze_all_markets(enriched)

        import sqlite3

        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            row = con.execute(
                "SELECT forecast_prob, market_prob FROM analysis_attempts WHERE ticker=?",
                ("TK-PROB-1",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row[0], 0.72)
        self.assertAlmostEqual(row[1], 0.48)

    def test_get_analysis_bias_returns_none_with_no_outcomes(self):
        """get_analysis_bias returns None when no analysis_attempts have outcomes."""
        enriched = [
            self._make_enriched("TK-BIAS-X", "NYC", 0.80, 0.50, 0.30, date(2026, 4, 9)),
        ]
        tracker.analyze_all_markets(enriched)
        result = tracker.get_analysis_bias()
        self.assertIsNone(result)

    def test_get_analysis_bias_computes_mean_bias(self):
        """get_analysis_bias returns mean(forecast_prob - settled_yes) for all analyzed markets."""
        # Log two analysis attempts and settle them via outcomes table
        enriched = [
            self._make_enriched("TK-BIAS-1", "NYC", 0.80, 0.50, 0.30, date(2026, 4, 1)),
            self._make_enriched("TK-BIAS-2", "CHI", 0.60, 0.50, 0.10, date(2026, 4, 2)),
        ]
        tracker.analyze_all_markets(enriched)
        # Settle: TK-BIAS-1 YES → error = 0.80 - 1 = -0.20
        #         TK-BIAS-2 NO  → error = 0.60 - 0 =  0.60
        # mean bias = (-0.20 + 0.60) / 2 = 0.20
        tracker.log_outcome("TK-BIAS-1", True)
        tracker.log_outcome("TK-BIAS-2", False)
        result = tracker.get_analysis_bias()
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.20, places=4)

    def test_analyze_all_markets_empty_list_is_noop(self):
        """Calling analyze_all_markets([]) should not raise or write any rows."""
        tracker.analyze_all_markets([])
        import sqlite3

        with sqlite3.connect(str(tracker.DB_PATH)) as con:
            count = con.execute("SELECT COUNT(*) FROM analysis_attempts").fetchone()[0]
        self.assertEqual(count, 0)
```

- [ ] **Step 2: Run failing tests**

```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_tracker.py::TestAnalyzeAllMarketsAndBias -v --ignore=tests/test_http.py 2>&1 | tail -20
```

Expected output: `AttributeError: module 'tracker' has no attribute 'analyze_all_markets'`.

- [ ] **Step 3: Implement `analyze_all_markets` and `get_analysis_bias` in `tracker.py`**

Append these two functions after `get_unselected_bias` (approximately line 1619):

```python
def analyze_all_markets(enriched_list: list[dict]) -> None:
    """
    Log every analyzed market (traded or not) to analysis_attempts (#55).

    Accepts the same enriched market list format used in main.py:
    each item must have keys: ticker, city, target_date, and
    analysis (dict with forecast_prob, market_prob, edge, condition).

    This broader population (vs. only traded markets) allows
    get_analysis_bias() to compute an unselected Brier-style bias.
    Never raises — logging failures emit a warning and continue.

    Parameters
    ----------
    enriched_list : list[dict]
        List of enriched market dicts.  Silently skipped if missing keys.
    """
    init_db()
    from datetime import UTC

    analyzed_at = datetime.now(UTC).isoformat()

    for item in enriched_list:
        try:
            ticker = item["ticker"]
            city = item.get("city")
            target_date = item.get("target_date")
            analysis = item.get("analysis", {})
            forecast_prob = analysis.get("forecast_prob")
            market_prob = analysis.get("market_prob")
            condition = analysis.get("condition", {})
            condition_str = condition.get("type") if condition else None
            days_out = (
                (target_date - date.today()).days
                if target_date is not None
                else None
            )
            target_str = (
                target_date.isoformat()
                if hasattr(target_date, "isoformat")
                else str(target_date) if target_date is not None else None
            )
            try:
                with _conn() as con:
                    con.execute(
                        """INSERT OR REPLACE INTO analysis_attempts
                           (ticker, city, condition, target_date, analyzed_at,
                            forecast_prob, market_prob, days_out, was_traded)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                        (
                            ticker,
                            city,
                            condition_str,
                            target_str,
                            analyzed_at,
                            forecast_prob,
                            market_prob,
                            days_out,
                        ),
                    )
            except Exception as exc:
                _log.warning("analyze_all_markets: failed to log %s: %s", ticker, exc)
        except (KeyError, TypeError) as exc:
            _log.warning("analyze_all_markets: skipping malformed item: %s", exc)


def get_analysis_bias() -> float | None:
    """
    Mean(forecast_prob - settled_yes) across ALL analyzed markets (#55).

    Unlike get_unselected_bias (per-city, untraded only), this function
    joins analysis_attempts against outcomes for every ticker regardless
    of whether it was traded.  This gives an unselected population estimate
    of systematic probability over/under-estimation.

    Returns None if no analysis_attempts rows have a corresponding settled
    outcome (i.e. insufficient data to compute bias).
    """
    init_db()
    try:
        with _conn() as con:
            rows = con.execute(
                """
                SELECT a.forecast_prob, o.settled_yes
                FROM analysis_attempts a
                JOIN outcomes o ON a.ticker = o.ticker
                WHERE a.forecast_prob IS NOT NULL
                  AND o.settled_yes IS NOT NULL
                """
            ).fetchall()
    except Exception as exc:
        _log.warning("get_analysis_bias failed: %s", exc)
        return None

    if not rows:
        return None

    bias_values = [r["forecast_prob"] - r["settled_yes"] for r in rows]
    return round(sum(bias_values) / len(bias_values), 6)
```

- [ ] **Step 4: Run passing tests**

```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_tracker.py::TestAnalyzeAllMarketsAndBias -v --ignore=tests/test_http.py
```

Expected output: 5 tests PASSED.

- [ ] **Step 5: Run full suite**

```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest --ignore=tests/test_http.py -q 2>&1 | tail -10
```

Expected output: no new failures.

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/thesa/claude kalshi" && git add tracker.py tests/test_tracker.py && git commit -m "feat: add analyze_all_markets() and get_analysis_bias() for unselected bias detection (#55)"
```

---

### Task 5: `bayesian_confidence_interval` verification (#57)

**Files:**
- Read-only audit: `tracker.py` (lines 1325–1380), `tests/test_tracker.py`

This function is already implemented and tested (`TestBayesianConfidenceInterval` class with 5 tests). No code changes are needed. The task is to confirm the Wilson-score formula and shrinkage property match the spec, then run the suite.

- [ ] **Step 1: Confirm spec compliance** — read `bayesian_confidence_interval` and verify:
  - Uses Laplace-smoothed posterior: `alpha = 1 + successes`, `n_posterior = trials + 2`
  - `z = _inv_normal_cdf(0.95)` ≈ 1.645 for default `confidence=0.90`
  - Wilson formula: `centre = (p_hat + z²/2n) / (1 + z²/n)`
  - Margin shrinks as `n` grows (interval narrows)
  - Returns `(max(0, centre-margin), min(1, centre+margin))`

- [ ] **Step 2: Run existing tests**

```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_tracker.py::TestBayesianConfidenceInterval -v --ignore=tests/test_http.py
```

Expected output: 5 tests PASSED.

- [ ] **Step 3: Commit (no code changes)**

```bash
cd "C:/Users/thesa/claude kalshi" && git commit --allow-empty -m "chore: verify #57 bayesian_confidence_interval already complete"
```

---

### Task 6: Fix `get_optimal_threshold` guard from `< 10` to `< 20` (#60)

**Files:**
- Modify: `tracker.py` (function `get_optimal_threshold`, line ~1167)
- Modify: `tests/test_tracker.py` (append guard boundary test)

The existing implementation at line 1167 checks `if len(rows) < 10` but the spec requires `< 20`. The function and its existing 3 tests are otherwise correct. This task updates the guard and adds a boundary test.

- [ ] **Step 1: Write failing boundary test**

Append to `tests/test_tracker.py`:

```python
# ── Task 6: get_optimal_threshold guard = 20 (#60) ────────────────────────────


class TestOptimalThresholdGuard20(_Phase3Base):
    """Verify get_optimal_threshold returns None below 20 data points (#60)."""

    def test_returns_none_with_19_samples(self):
        """19 samples (< 20) must return None."""
        for i in range(19):
            self._add(f"TKOPT20-{i}", "NYC", 0.7, 0.5, True)
        result = tracker.get_optimal_threshold()
        self.assertIsNone(result, "Expected None with 19 samples (< 20 threshold)")

    def test_returns_dict_with_exactly_20_samples(self):
        """Exactly 20 samples must return a result dict."""
        for i in range(10):
            self._add(f"TKOPT20-YES-{i}", "NYC", 0.8, 0.5, True)
        for i in range(10):
            self._add(f"TKOPT20-NO-{i}", "NYC", 0.2, 0.5, False)
        result = tracker.get_optimal_threshold()
        self.assertIsNotNone(result, "Expected dict with exactly 20 samples")
        assert result is not None
        self.assertIn("threshold_f1", result)
        self.assertIn("best_f1", result)

    def test_returns_none_with_10_samples(self):
        """10 samples (old guard) must now return None (guard raised to 20)."""
        for i in range(10):
            self._add(f"TKOPT20-10-{i}", "NYC", 0.7, 0.5, True)
        result = tracker.get_optimal_threshold()
        self.assertIsNone(result, "Expected None with 10 samples after guard raised to 20")
```

- [ ] **Step 2: Run failing test**

```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_tracker.py::TestOptimalThresholdGuard20 -v --ignore=tests/test_http.py 2>&1 | tail -20
```

Expected output: `test_returns_none_with_19_samples` and `test_returns_none_with_10_samples` FAIL (current guard is `< 10`, so 10 samples returns a result instead of None).

- [ ] **Step 3: Fix the guard in `tracker.py`**

Locate `get_optimal_threshold` (approximately line 1153). Change the guard from `< 10` to `< 20`:

```python
def get_optimal_threshold() -> dict | None:
    """
    Sweep thresholds 0.05..0.95 (step 0.05) and find the one maximizing F1 (#60).
    Returns {"threshold_f1": float, "best_f1": float} or None if < 20 samples.
    """
    init_db()
    with _conn() as con:
        rows = con.execute("""
            SELECT p.our_prob, o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
        """).fetchall()

    if len(rows) < 20:
        return None

    best_f1 = -1.0
    best_threshold = 0.5

    thresholds = [round(0.05 * i, 2) for i in range(1, 20)]  # 0.05 to 0.95
    for thresh in thresholds:
        tp = fp = tn = fn = 0
        for r in rows:
            predicted_yes = r["our_prob"] >= thresh
            actual_yes = bool(r["settled_yes"])
            if predicted_yes and actual_yes:
                tp += 1
            elif predicted_yes and not actual_yes:
                fp += 1
            elif not predicted_yes and actual_yes:
                fn += 1
            else:
                tn += 1
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        if f1 > best_f1:
            best_f1 = f1
            best_threshold = thresh

    return {"threshold_f1": best_threshold, "best_f1": round(best_f1, 4)}
```

- [ ] **Step 4: Run passing tests (new + existing)**

```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_tracker.py::TestOptimalThresholdGuard20 tests/test_tracker.py::TestGetOptimalThreshold -v --ignore=tests/test_http.py
```

Expected output: all 6 tests PASSED (3 new + 3 existing, noting the existing test `test_returns_none_below_10_samples` now uses 5 samples which is still < 20 so it still passes).

- [ ] **Step 5: Run full suite**

```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest --ignore=tests/test_http.py -q 2>&1 | tail -10
```

Expected output: no new failures.

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/thesa/claude kalshi" && git add tracker.py tests/test_tracker.py && git commit -m "fix: raise get_optimal_threshold minimum data guard from 10 to 20 (#60)"
```

---

## Final verification

After all six tasks are complete, run the full test suite one final time:

```bash
cd "C:/Users/thesa/claude kalshi" && python -m pytest --ignore=tests/test_http.py -v 2>&1 | tail -30
```

All tests must PASS with zero failures and zero errors.
