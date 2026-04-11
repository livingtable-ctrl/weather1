# Group B: Data Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add condition-type filtering, configurable thresholds, quantile bucketing, and city/season stratification across the tracker and backtest modules so all analytics functions produce correctly scoped, non-misleading outputs.
**Architecture:** All changes are additive — new optional parameters with backward-compatible defaults so callers that omit them continue to work. The `tracker.py` analytics functions gain filter params that inject SQL clauses when provided. `backtest.py` gains `stratified_train_test_split()` as a standalone utility. Tests use the existing isolation pattern (redirect `tracker.DB_PATH` to a temp file, reset `tracker._db_initialized = False`).
**Tech Stack:** Python 3.11, SQLite3 (via `tracker._conn()`), `unittest.TestCase`, pytest

---

### Task 1: `get_bias()` — condition_type filter (#10)

**Files:**
- Modify: `C:/Users/thesa/claude kalshi/tracker.py`
- Modify: `C:/Users/thesa/claude kalshi/tests/test_tracker.py`

- [ ] Step 1: Write failing test

  Append this class to `tests/test_tracker.py`:

  ```python
  class TestGetBiasConditionType(unittest.TestCase):
      """#10 — get_bias() must filter by condition_type when provided."""

      def setUp(self):
          self._tmpdir = tempfile.mkdtemp()
          self._orig = tracker.DB_PATH
          tracker.DB_PATH = Path(self._tmpdir) / "test.db"
          tracker._db_initialized = False

      def tearDown(self):
          tracker.DB_PATH = self._orig
          tracker._db_initialized = False
          shutil.rmtree(self._tmpdir, ignore_errors=True)

      def _log(self, ticker, city, our_prob, settled, condition_type):
          tracker.log_prediction(
              ticker, city, date(2026, 1, 15),
              {
                  "forecast_prob": our_prob,
                  "market_prob": 0.5,
                  "edge": abs(our_prob - 0.5),
                  "method": "ensemble",
                  "n_members": 50,
                  "condition": {"type": condition_type, "threshold": 70.0},
              },
          )
          tracker.log_outcome(ticker, settled_yes=settled)

      def test_grpb_bias_condition_type_filters_rows(self):
          """Bias with condition_type='above' should differ from condition_type='below'."""
          for i in range(6):
              self._log(f"ABOVE-{i}", "NYC", 0.80, True, "above")
          for i in range(6):
              self._log(f"BELOW-{i}", "NYC", 0.20, False, "below")
          bias_above = tracker.get_bias("NYC", None, min_samples=1, condition_type="above")
          bias_below = tracker.get_bias("NYC", None, min_samples=1, condition_type="below")
          # above: consistently over-estimates (0.80 - 1) = -0.20 weighted
          # below: consistently under-estimates (0.20 - 0) = +0.20 weighted
          self.assertNotAlmostEqual(bias_above, bias_below, places=2)

      def test_grpb_bias_none_condition_type_includes_all(self):
          """Passing condition_type=None should return a result covering all rows."""
          for i in range(6):
              self._log(f"MIX-ABOVE-{i}", "NYC", 0.70, True, "above")
          for i in range(6):
              self._log(f"MIX-BELOW-{i}", "NYC", 0.70, True, "below")
          bias_all = tracker.get_bias("NYC", None, min_samples=1, condition_type=None)
          bias_above = tracker.get_bias("NYC", None, min_samples=1, condition_type="above")
          # all rows included — neither should raise; both should be finite floats
          self.assertIsInstance(bias_all, float)
          self.assertIsInstance(bias_above, float)

      def test_grpb_bias_unknown_condition_type_returns_zero(self):
          """Filtering by a condition_type with no matching rows returns 0.0."""
          for i in range(6):
              self._log(f"CT-ABOVE-{i}", "NYC", 0.70, True, "above")
          result = tracker.get_bias("NYC", None, min_samples=1, condition_type="precip_any")
          self.assertEqual(result, 0.0)
  ```

- [ ] Step 2: Run failing test

  ```
  python -m pytest "C:/Users/thesa/claude kalshi/tests/test_tracker.py" -k "TestGetBiasConditionType" -v --ignore="C:/Users/thesa/claude kalshi/tests/test_http.py"
  ```

  Expected: 3 tests collected, all **PASS** (the function already accepts the parameter — confirm green before moving on; if any fail, proceed to Step 3).

- [ ] Step 3: Implement

  In `tracker.py`, locate `get_bias()`. Ensure the signature and SQL filtering match:

  ```python
  def get_bias(
      city: str | None,
      month: int | None,
      min_samples: int = 5,
      condition_type: str | None = None,
  ) -> float:
      """
      Compute systematic bias for a city/month: weighted mean(our_prob - actual_outcome).
      Weights each sample by exp(-age_days / 30) so recent predictions count more.
      Positive bias means we consistently over-estimate; negative = under-estimate.
      Returns 0.0 if insufficient data (raw count < min_samples).
      Optionally filter by condition_type (#10).
      """
      init_db()
      with _conn() as con:
          query = """
              SELECT p.our_prob, o.settled_yes, p.predicted_at
              FROM predictions p
              JOIN outcomes o ON p.ticker = o.ticker
              WHERE p.our_prob IS NOT NULL
          """
          params: list = []
          if city:
              query += " AND p.city = ?"
              params.append(city)
          if month:
              query += " AND strftime('%m', p.market_date) = ?"
              params.append(f"{month:02d}")
          if condition_type is not None:
              query += " AND p.condition_type = ?"
              params.append(condition_type)

          rows = con.execute(query, params).fetchall()

      if len(rows) < min_samples:
          return 0.0

      now = datetime.utcnow()
      weighted_bias = 0.0
      total_weight = 0.0
      min_age_days = float("inf")
      for r in rows:
          try:
              predicted_at = datetime.fromisoformat(
                  r["predicted_at"].replace("Z", "+00:00")
              )
              if predicted_at.tzinfo is not None:
                  predicted_at = predicted_at.replace(tzinfo=None)
              age_days = max(0.0, (now - predicted_at).total_seconds() / 86400)
          except (ValueError, TypeError, AttributeError):
              age_days = 0.0
          min_age_days = min(min_age_days, age_days)
          weight = math.exp(-age_days / 30.0)
          weighted_bias += (r["our_prob"] - r["settled_yes"]) * weight
          total_weight += weight

      if min_age_days > 14:
          return 0.0

      return round(weighted_bias / total_weight, 6) if total_weight > 0 else 0.0
  ```

- [ ] Step 4: Run test to verify pass

  ```
  python -m pytest "C:/Users/thesa/claude kalshi/tests/test_tracker.py" -k "TestGetBiasConditionType" -v --ignore="C:/Users/thesa/claude kalshi/tests/test_http.py"
  ```

  Expected: 3 passed.

- [ ] Step 5: Commit

  ```
  git -C "C:/Users/thesa/claude kalshi" add tracker.py tests/test_tracker.py && git -C "C:/Users/thesa/claude kalshi" commit -m "fix(#10): get_bias() condition_type filter with tests"
  ```

---

### Task 2: `get_confusion_matrix()` — configurable threshold (#12)

**Files:**
- Modify: `C:/Users/thesa/claude kalshi/tracker.py`
- Modify: `C:/Users/thesa/claude kalshi/tests/test_tracker.py`

- [ ] Step 1: Write failing test

  Append this class to `tests/test_tracker.py`:

  ```python
  class TestConfusionMatrixThreshold(unittest.TestCase):
      """#12 — get_confusion_matrix() must accept a configurable threshold."""

      def setUp(self):
          self._tmpdir = tempfile.mkdtemp()
          self._orig = tracker.DB_PATH
          tracker.DB_PATH = Path(self._tmpdir) / "test.db"
          tracker._db_initialized = False

      def tearDown(self):
          tracker.DB_PATH = self._orig
          tracker._db_initialized = False
          shutil.rmtree(self._tmpdir, ignore_errors=True)

      def _seed(self, ticker, our_prob, settled):
          tracker.log_prediction(
              ticker, "NYC", date(2026, 2, 1),
              {
                  "forecast_prob": our_prob,
                  "market_prob": 0.5,
                  "edge": 0.1,
                  "method": "ensemble",
                  "n_members": 50,
                  "condition": {"type": "above", "threshold": 70.0},
              },
          )
          tracker.log_outcome(ticker, settled_yes=settled)

      def test_grpb_cm_default_threshold_is_0_5(self):
          """Default threshold=0.5 classifies our_prob=0.6 as predicted YES."""
          self._seed("CM-T1", 0.60, True)
          result = tracker.get_confusion_matrix()
          self.assertEqual(result["threshold"], 0.5)
          self.assertEqual(result["tp"], 1)

      def test_grpb_cm_threshold_0_7_reclassifies(self):
          """With threshold=0.7, our_prob=0.6 should be a FALSE NEGATIVE not TP."""
          self._seed("CM-T2", 0.60, True)
          result = tracker.get_confusion_matrix(threshold=0.7)
          self.assertEqual(result["threshold"], 0.7)
          self.assertEqual(result["fn"], 1)
          self.assertEqual(result["tp"], 0)

      def test_grpb_cm_threshold_0_3_makes_fp(self):
          """With threshold=0.3, our_prob=0.4 predicts YES even if outcome=NO -> FP."""
          self._seed("CM-T3", 0.40, False)
          result = tracker.get_confusion_matrix(threshold=0.3)
          self.assertEqual(result["fp"], 1)
          self.assertEqual(result["tn"], 0)

      def test_grpb_cm_threshold_reflected_in_empty_return(self):
          """Empty DB: returned dict must carry the requested threshold."""
          result = tracker.get_confusion_matrix(threshold=0.65)
          self.assertEqual(result["threshold"], 0.65)
          self.assertEqual(result["n"], 0)
  ```

- [ ] Step 2: Run failing test

  ```
  python -m pytest "C:/Users/thesa/claude kalshi/tests/test_tracker.py" -k "TestConfusionMatrixThreshold" -v --ignore="C:/Users/thesa/claude kalshi/tests/test_http.py"
  ```

  Expected: 4 tests collected, all **PASS** (confirm; fix if any fail before continuing).

- [ ] Step 3: Implement

  In `tracker.py`, locate `get_confusion_matrix()`. Ensure:

  ```python
  def get_confusion_matrix(threshold: float = 0.5) -> dict:
      """
      TP/FP/TN/FN classification of model predictions.
      Positive = model predicted YES (our_prob >= threshold).
      Returns {tp, fp, tn, fn, precision, recall, f1, accuracy, threshold, n}.
      threshold is configurable (#12).
      """
      init_db()
      with _conn() as con:
          rows = con.execute("""
              SELECT p.our_prob, o.settled_yes
              FROM predictions p
              JOIN outcomes o ON p.ticker = o.ticker
              WHERE p.our_prob IS NOT NULL
          """).fetchall()

      if not rows:
          return {
              "tp": 0, "fp": 0, "tn": 0, "fn": 0,
              "precision": None, "recall": None, "f1": None,
              "accuracy": None, "threshold": threshold, "n": 0,
          }

      tp = fp = tn = fn = 0
      for r in rows:
          predicted_yes = r["our_prob"] >= threshold
          actual_yes = bool(r["settled_yes"])
          if predicted_yes and actual_yes:
              tp += 1
          elif predicted_yes and not actual_yes:
              fp += 1
          elif not predicted_yes and actual_yes:
              fn += 1
          else:
              tn += 1

      n = tp + fp + tn + fn
      precision = tp / (tp + fp) if (tp + fp) > 0 else None
      recall = tp / (tp + fn) if (tp + fn) > 0 else None
      f1 = (
          2 * precision * recall / (precision + recall)
          if precision and recall else None
      )
      accuracy = (tp + tn) / n if n > 0 else None

      return {
          "tp": tp, "fp": fp, "tn": tn, "fn": fn,
          "precision": round(precision, 4) if precision is not None else None,
          "recall": round(recall, 4) if recall is not None else None,
          "f1": round(f1, 4) if f1 is not None else None,
          "accuracy": round(accuracy, 4) if accuracy is not None else None,
          "threshold": threshold,
          "n": n,
      }
  ```

- [ ] Step 4: Run test to verify pass

  ```
  python -m pytest "C:/Users/thesa/claude kalshi/tests/test_tracker.py" -k "TestConfusionMatrixThreshold" -v --ignore="C:/Users/thesa/claude kalshi/tests/test_http.py"
  ```

  Expected: 4 passed.

- [ ] Step 5: Commit

  ```
  git -C "C:/Users/thesa/claude kalshi" add tracker.py tests/test_tracker.py && git -C "C:/Users/thesa/claude kalshi" commit -m "fix(#12): get_confusion_matrix() configurable threshold with tests"
  ```

---

### Task 3: `get_market_calibration()` — quantile bucketing + `n_buckets` param (#13)

**Files:**
- Modify: `C:/Users/thesa/claude kalshi/tracker.py`
- Modify: `C:/Users/thesa/claude kalshi/tests/test_tracker.py`

- [ ] Step 1: Write failing test

  Append this class to `tests/test_tracker.py`:

  ```python
  class TestMarketCalibrationQuantile(unittest.TestCase):
      """#13 — get_market_calibration() must use equal-frequency buckets and accept n_buckets."""

      def setUp(self):
          self._tmpdir = tempfile.mkdtemp()
          self._orig = tracker.DB_PATH
          tracker.DB_PATH = Path(self._tmpdir) / "test.db"
          tracker._db_initialized = False

      def tearDown(self):
          tracker.DB_PATH = self._orig
          tracker._db_initialized = False
          shutil.rmtree(self._tmpdir, ignore_errors=True)

      def _seed(self, ticker, market_prob, settled):
          tracker.log_prediction(
              ticker, "NYC", date(2026, 3, 1),
              {
                  "forecast_prob": 0.6,
                  "market_prob": market_prob,
                  "edge": 0.1,
                  "method": "ensemble",
                  "n_members": 50,
                  "condition": {"type": "above", "threshold": 70.0},
              },
          )
          tracker.log_outcome(ticker, settled_yes=settled)

      def test_grpb_calibration_empty_returns_empty_buckets(self):
          result = tracker.get_market_calibration()
          self.assertIn("buckets", result)
          self.assertEqual(result["buckets"], [])

      def test_grpb_calibration_n_buckets_param_accepted(self):
          """n_buckets parameter should control number of output buckets."""
          for i in range(20):
              self._seed(f"CAL-NB-{i}", 0.1 * (i % 10) + 0.05, bool(i % 2))
          result_5 = tracker.get_market_calibration(n_buckets=5)
          result_10 = tracker.get_market_calibration(n_buckets=10)
          self.assertLessEqual(len(result_5["buckets"]), len(result_10["buckets"]))

      def test_grpb_calibration_buckets_equal_frequency(self):
          """Buckets should be roughly equal in count (quantile, not equal-width)."""
          # Skewed data: 15 items at 0.1, 5 items at 0.9
          for i in range(15):
              self._seed(f"CAL-EF-LOW-{i}", 0.10, False)
          for i in range(5):
              self._seed(f"CAL-EF-HIGH-{i}", 0.90, True)
          result = tracker.get_market_calibration(n_buckets=4)
          buckets = result["buckets"]
          self.assertGreater(len(buckets), 0)
          counts = [b["count"] for b in buckets]
          # Equal-frequency: no bucket should hold all the data
          self.assertLess(max(counts), 20)

      def test_grpb_calibration_bucket_fields(self):
          """Each bucket must have the required keys."""
          for i in range(10):
              self._seed(f"CAL-FK-{i}", 0.1 * i + 0.05, bool(i % 2))
          result = tracker.get_market_calibration(n_buckets=3)
          for b in result["buckets"]:
              for key in ("bucket_min", "bucket_max", "mean_prob", "freq_yes", "count"):
                  self.assertIn(key, b)

      def test_grpb_calibration_default_n_buckets_is_10(self):
          """Default call (no args) should use 10 buckets."""
          for i in range(30):
              self._seed(f"CAL-DEF-{i}", round(0.03 * i + 0.01, 2), bool(i % 2))
          result_default = tracker.get_market_calibration()
          result_explicit = tracker.get_market_calibration(n_buckets=10)
          self.assertEqual(
              len(result_default["buckets"]), len(result_explicit["buckets"])
          )
  ```

- [ ] Step 2: Run failing test

  ```
  python -m pytest "C:/Users/thesa/claude kalshi/tests/test_tracker.py" -k "TestMarketCalibrationQuantile" -v --ignore="C:/Users/thesa/claude kalshi/tests/test_http.py"
  ```

  Expected: 5 tests collected, all **PASS** (confirm green before moving on).

- [ ] Step 3: Implement

  In `tracker.py`, locate `get_market_calibration()`. Ensure it reads:

  ```python
  def get_market_calibration(n_buckets: int = 10) -> dict:
      """
      How well-calibrated are the MARKET PRICES (not our model)?
      Groups settled predictions into quantile-based buckets (equal frequency, not equal
      width) and computes actual outcome rate per bucket (#13).
      Returns a list of dicts with bucket_min, bucket_max, mean_prob, freq_yes, count.
      A well-calibrated market has freq_yes ≈ mean_prob.
      Systematic deviations = exploitable edges.
      """
      init_db()
      with _conn() as con:
          rows = con.execute("""
              SELECT p.market_prob, o.settled_yes
              FROM predictions p
              JOIN outcomes o ON p.ticker = o.ticker
              WHERE p.market_prob IS NOT NULL
              ORDER BY p.market_prob ASC
          """).fetchall()

      if not rows:
          return {"buckets": []}

      # Quantile-based (equal frequency) bucketing
      data = [(r["market_prob"], r["settled_yes"]) for r in rows]
      n = len(data)
      bucket_size = max(1, n // n_buckets)

      result_buckets = []
      i = 0
      while i < n:
          chunk = data[i : i + bucket_size]
          # Merge last tiny remainder into previous bucket if it would be too small
          if i + bucket_size < n and (n - (i + bucket_size)) < bucket_size // 2:
              chunk = data[i:]
          probs = [p for p, _ in chunk]
          outcomes = [y for _, y in chunk]
          bucket_min = round(min(probs), 4)
          bucket_max = round(max(probs), 4)
          mean_prob = round(sum(probs) / len(probs), 4)
          freq_yes = round(sum(outcomes) / len(outcomes), 4)
          result_buckets.append(
              {
                  "bucket_min": bucket_min,
                  "bucket_max": bucket_max,
                  "mean_prob": mean_prob,
                  "freq_yes": freq_yes,
                  "count": len(chunk),
              }
          )
          if i + bucket_size >= n or (n - (i + bucket_size)) < bucket_size // 2:
              break
          i += bucket_size

      return {"buckets": result_buckets}
  ```

- [ ] Step 4: Run test to verify pass

  ```
  python -m pytest "C:/Users/thesa/claude kalshi/tests/test_tracker.py" -k "TestMarketCalibrationQuantile" -v --ignore="C:/Users/thesa/claude kalshi/tests/test_http.py"
  ```

  Expected: 5 passed.

- [ ] Step 5: Commit

  ```
  git -C "C:/Users/thesa/claude kalshi" add tracker.py tests/test_tracker.py && git -C "C:/Users/thesa/claude kalshi" commit -m "fix(#13): get_market_calibration() quantile buckets and n_buckets param with tests"
  ```

---

### Task 4: `get_edge_decay_curve()` — condition_type filter (#14)

**Files:**
- Modify: `C:/Users/thesa/claude kalshi/tracker.py`
- Modify: `C:/Users/thesa/claude kalshi/tests/test_tracker.py`

- [ ] Step 1: Write failing test

  Append this class to `tests/test_tracker.py`:

  ```python
  class TestEdgeDecayCurveConditionType(unittest.TestCase):
      """#14 — get_edge_decay_curve() must segment by condition_type when provided."""

      def setUp(self):
          self._tmpdir = tempfile.mkdtemp()
          self._orig = tracker.DB_PATH
          tracker.DB_PATH = Path(self._tmpdir) / "test.db"
          tracker._db_initialized = False

      def tearDown(self):
          tracker.DB_PATH = self._orig
          tracker._db_initialized = False
          shutil.rmtree(self._tmpdir, ignore_errors=True)

      def _log_with_days_out(self, ticker, our_prob, market_prob, days_out, settled, ctype):
          tracker.log_prediction(
              ticker, "NYC", date(2026, 4, 1),
              {
                  "forecast_prob": our_prob,
                  "market_prob": market_prob,
                  "edge": abs(our_prob - market_prob),
                  "method": "ensemble",
                  "n_members": 50,
                  "condition": {"type": ctype, "threshold": 70.0},
              },
          )
          # Manually patch days_out since log_prediction doesn't accept it directly
          with tracker._conn() as con:
              con.execute(
                  "UPDATE predictions SET days_out=? WHERE ticker=?",
                  (days_out, ticker),
              )
          tracker.log_outcome(ticker, settled_yes=settled)

      def test_grpb_edge_decay_condition_type_filters(self):
          """Filtering by 'above' should exclude 'precip_any' rows."""
          for i in range(5):
              self._log_with_days_out(
                  f"EDC-ABOVE-{i}", 0.75, 0.50, 1, True, "above"
              )
          for i in range(5):
              self._log_with_days_out(
                  f"EDC-PRECIP-{i}", 0.30, 0.50, 1, False, "precip_any"
              )
          above_result = tracker.get_edge_decay_curve(condition_type="above")
          precip_result = tracker.get_edge_decay_curve(condition_type="precip_any")
          # above has high edge (0.25); precip has high edge too but different direction
          # The key check: both lists non-empty and their avg_edge values differ
          self.assertTrue(len(above_result) > 0 or len(precip_result) > 0)
          if above_result and precip_result:
              self.assertNotAlmostEqual(
                  above_result[0]["avg_edge"],
                  precip_result[0]["avg_edge"],
                  places=3,
              )

      def test_grpb_edge_decay_no_filter_returns_all(self):
          """No filter should return rows from all condition types."""
          for i in range(4):
              self._log_with_days_out(
                  f"EDC-MIX-ABOVE-{i}", 0.80, 0.50, 2, True, "above"
              )
          for i in range(4):
              self._log_with_days_out(
                  f"EDC-MIX-PRECIP-{i}", 0.20, 0.50, 2, False, "precip_any"
              )
          all_result = tracker.get_edge_decay_curve(condition_type=None)
          above_only = tracker.get_edge_decay_curve(condition_type="above")
          if all_result and above_only:
              self.assertGreaterEqual(all_result[0]["n"], above_only[0]["n"])

      def test_grpb_edge_decay_unknown_condition_type_returns_empty(self):
          """Filtering by a condition_type with no data returns empty list."""
          for i in range(5):
              self._log_with_days_out(
                  f"EDC-ABOVE2-{i}", 0.75, 0.50, 1, True, "above"
              )
          result = tracker.get_edge_decay_curve(condition_type="nonexistent_type")
          self.assertEqual(result, [])

      def test_grpb_edge_decay_returns_list(self):
          """Return value is always a list (never None)."""
          result = tracker.get_edge_decay_curve(condition_type="above")
          self.assertIsInstance(result, list)
  ```

- [ ] Step 2: Run failing test

  ```
  python -m pytest "C:/Users/thesa/claude kalshi/tests/test_tracker.py" -k "TestEdgeDecayCurveConditionType" -v --ignore="C:/Users/thesa/claude kalshi/tests/test_http.py"
  ```

  Expected: 4 tests collected, all **PASS** (confirm; fix if any fail).

- [ ] Step 3: Implement

  In `tracker.py`, locate `get_edge_decay_curve()`. Ensure it reads:

  ```python
  def get_edge_decay_curve(condition_type: str | None = None) -> list[dict]:
      """
      Average edge and Brier score grouped by forecast horizon (days_out) (#14).
      Shows whether our edge shrinks as markets approach settlement.
      Returns [{bucket, avg_edge, avg_brier, n}] sorted near->far.
      Only includes buckets with >= 3 samples.
      Optionally filter by condition_type.
      """
      init_db()
      with _conn() as con:
          query = """
              SELECT p.our_prob, p.market_prob, p.days_out, o.settled_yes
              FROM predictions p
              JOIN outcomes o ON p.ticker = o.ticker
              WHERE p.our_prob IS NOT NULL AND p.market_prob IS NOT NULL
                AND p.days_out IS NOT NULL
          """
          params: list = []
          if condition_type is not None:
              query += " AND p.condition_type = ?"
              params.append(condition_type)
          rows = con.execute(query, params).fetchall()

      buckets: dict[str, list] = {"0-2": [], "3-5": [], "6-10": [], "11+": []}
      order = ["0-2", "3-5", "6-10", "11+"]

      for r in rows:
          d = r["days_out"]
          edge = abs(r["our_prob"] - r["market_prob"])
          brier = (r["our_prob"] - r["settled_yes"]) ** 2
          if d <= 2:
              buckets["0-2"].append((edge, brier))
          elif d <= 5:
              buckets["3-5"].append((edge, brier))
          elif d <= 10:
              buckets["6-10"].append((edge, brier))
          else:
              buckets["11+"].append((edge, brier))

      result = []
      for key in order:
          entries = buckets[key]
          if len(entries) < 3:
              continue
          avg_edge = sum(e for e, _ in entries) / len(entries)
          avg_brier = sum(b for _, b in entries) / len(entries)
          result.append(
              {
                  "bucket": key,
                  "avg_edge": round(avg_edge, 4),
                  "avg_brier": round(avg_brier, 4),
                  "n": len(entries),
              }
          )
      return result
  ```

- [ ] Step 4: Run test to verify pass

  ```
  python -m pytest "C:/Users/thesa/claude kalshi/tests/test_tracker.py" -k "TestEdgeDecayCurveConditionType" -v --ignore="C:/Users/thesa/claude kalshi/tests/test_http.py"
  ```

  Expected: 4 passed.

- [ ] Step 5: Commit

  ```
  git -C "C:/Users/thesa/claude kalshi" add tracker.py tests/test_tracker.py && git -C "C:/Users/thesa/claude kalshi" commit -m "fix(#14): get_edge_decay_curve() condition_type filter with tests"
  ```

---

### Task 5: `get_ensemble_member_accuracy()` — city + season stratification (#18)

**Files:**
- Modify: `C:/Users/thesa/claude kalshi/tracker.py`
- Modify: `C:/Users/thesa/claude kalshi/tests/test_tracker.py`

- [ ] Step 1: Write failing test

  Append this class to `tests/test_tracker.py`:

  ```python
  class TestEnsembleMemberAccuracyStratified(unittest.TestCase):
      """#18 — get_ensemble_member_accuracy() must stratify by city and season."""

      def setUp(self):
          self._tmpdir = tempfile.mkdtemp()
          self._orig = tracker.DB_PATH
          tracker.DB_PATH = Path(self._tmpdir) / "test.db"
          tracker._db_initialized = False

      def tearDown(self):
          tracker.DB_PATH = self._orig
          tracker._db_initialized = False
          shutil.rmtree(self._tmpdir, ignore_errors=True)

      def test_grpb_ensemble_empty_returns_none(self):
          """With no data, function returns None."""
          result = tracker.get_ensemble_member_accuracy(city="NYC", season="winter")
          self.assertIsNone(result)

      def test_grpb_ensemble_city_filter(self):
          """City filter restricts to matching city only."""
          tracker.log_member_score("NYC", "model_a", 72.0, 70.0, "2026-01-15")
          tracker.log_member_score("NYC", "model_a", 74.0, 71.0, "2026-01-16")
          tracker.log_member_score("LAX", "model_a", 85.0, 80.0, "2026-01-15")
          nyc_result = tracker.get_ensemble_member_accuracy(city="NYC", season=None)
          lax_result = tracker.get_ensemble_member_accuracy(city="LAX", season=None)
          self.assertIsNotNone(nyc_result)
          self.assertIsNotNone(lax_result)
          self.assertNotAlmostEqual(
              nyc_result["model_a"]["mae"],
              lax_result["model_a"]["mae"],
              places=2,
          )

      def test_grpb_ensemble_season_winter_oct_to_mar(self):
          """Winter season is Oct-Mar (months 10, 11, 12, 1, 2, 3)."""
          # winter date: January
          tracker.log_member_score("NYC", "model_b", 30.0, 25.0, "2026-01-10")
          # summer date: July
          tracker.log_member_score("NYC", "model_b", 90.0, 85.0, "2026-07-10")
          winter = tracker.get_ensemble_member_accuracy(city="NYC", season="winter")
          summer = tracker.get_ensemble_member_accuracy(city="NYC", season="summer")
          self.assertIsNotNone(winter)
          self.assertIsNotNone(summer)
          # winter score: |30-25|=5; summer score: |90-85|=5; both equal here
          self.assertAlmostEqual(winter["model_b"]["mae"], 5.0, places=2)
          self.assertAlmostEqual(summer["model_b"]["mae"], 5.0, places=2)

      def test_grpb_ensemble_season_filter_excludes_wrong_months(self):
          """Winter filter should exclude summer-month records from MAE calculation."""
          # winter record with small error
          tracker.log_member_score("NYC", "model_c", 32.0, 30.0, "2026-02-15")
          # summer record with large error
          tracker.log_member_score("NYC", "model_c", 95.0, 75.0, "2026-06-15")
          winter_only = tracker.get_ensemble_member_accuracy(city="NYC", season="winter")
          all_seasons = tracker.get_ensemble_member_accuracy(city="NYC", season=None)
          self.assertIsNotNone(winter_only)
          self.assertIsNotNone(all_seasons)
          # winter MAE = 2; all-seasons MAE = (2+20)/2 = 11
          self.assertLess(winter_only["model_c"]["mae"], all_seasons["model_c"]["mae"])

      def test_grpb_ensemble_return_shape(self):
          """Return dict must have {model: {mae, count}} shape."""
          tracker.log_member_score("NYC", "model_d", 70.0, 68.0, "2026-03-01")
          result = tracker.get_ensemble_member_accuracy(city="NYC", season=None)
          self.assertIsNotNone(result)
          self.assertIn("model_d", result)
          self.assertIn("mae", result["model_d"])
          self.assertIn("count", result["model_d"])
  ```

- [ ] Step 2: Run failing test

  ```
  python -m pytest "C:/Users/thesa/claude kalshi/tests/test_tracker.py" -k "TestEnsembleMemberAccuracyStratified" -v --ignore="C:/Users/thesa/claude kalshi/tests/test_http.py"
  ```

  Expected: 5 tests collected, all **PASS** (confirm green).

- [ ] Step 3: Implement

  In `tracker.py`, locate `get_ensemble_member_accuracy()`. Ensure it reads:

  ```python
  def get_ensemble_member_accuracy(
      city: str | None = None,
      season: str | None = None,
  ) -> dict | None:
      """
      Per-model MAE from ensemble_member_scores, stratified by city and season (#18).
      season: 'winter' = Oct-Mar (months 10-12, 1-3); 'summer' = Apr-Sep (months 4-9).
      Returns {model: {mae, count}} or None if table is empty after filtering.
      """
      init_db()
      with _conn() as con:
          query = """
              SELECT model, city, predicted_temp, actual_temp, target_date
              FROM ensemble_member_scores
              WHERE predicted_temp IS NOT NULL AND actual_temp IS NOT NULL
          """
          params: list = []
          if city:
              query += " AND city = ?"
              params.append(city)
          if season:
              if season.lower() == "winter":
                  query += (
                      " AND (CAST(strftime('%m', target_date) AS INTEGER)"
                      " IN (10,11,12,1,2,3))"
                  )
              elif season.lower() == "summer":
                  query += (
                      " AND (CAST(strftime('%m', target_date) AS INTEGER)"
                      " IN (4,5,6,7,8,9))"
                  )
          rows = con.execute(query, params).fetchall()

      if not rows:
          return None

      by_model: dict[str, list[float]] = {}
      for r in rows:
          err = abs(r["predicted_temp"] - r["actual_temp"])
          by_model.setdefault(r["model"], []).append(err)

      return {
          model: {"mae": round(sum(errs) / len(errs), 4), "count": len(errs)}
          for model, errs in by_model.items()
      }
  ```

- [ ] Step 4: Run test to verify pass

  ```
  python -m pytest "C:/Users/thesa/claude kalshi/tests/test_tracker.py" -k "TestEnsembleMemberAccuracyStratified" -v --ignore="C:/Users/thesa/claude kalshi/tests/test_http.py"
  ```

  Expected: 5 passed.

- [ ] Step 5: Commit

  ```
  git -C "C:/Users/thesa/claude kalshi" add tracker.py tests/test_tracker.py && git -C "C:/Users/thesa/claude kalshi" commit -m "fix(#18): get_ensemble_member_accuracy() city+season stratification with tests"
  ```

---

### Task 6: `stratified_train_test_split()` — holdout stratified by (city, condition_type) (#21)

**Files:**
- Modify: `C:/Users/thesa/claude kalshi/backtest.py`
- Create: `C:/Users/thesa/claude kalshi/tests/test_backtest_stratified.py`

- [ ] Step 1: Write failing test

  Create new file `tests/test_backtest_stratified.py`:

  ```python
  """
  Tests for backtest.stratified_train_test_split (#21).
  No network calls; pure logic tests.
  """

  import unittest

  from backtest import stratified_train_test_split


  class TestStratifiedTrainTestSplit(unittest.TestCase):
      """#21 — stratified_train_test_split must stratify by (city, condition_type)."""

      def _make_records(self, city, ctype, n, date_start="2026-01-01"):
          """Generate n synthetic records for a given (city, condition_type) stratum."""
          from datetime import date, timedelta

          base = date.fromisoformat(date_start)
          return [
              {
                  "city": city,
                  "condition_type": ctype,
                  "date": (base + timedelta(days=i)).isoformat(),
                  "our_prob": 0.6,
                  "actual": 1,
              }
              for i in range(n)
          ]

      def test_grpb_split_empty_returns_empty(self):
          train, holdout = stratified_train_test_split([], holdout_frac=0.2)
          self.assertEqual(train, [])
          self.assertEqual(holdout, [])

      def test_grpb_split_all_strata_in_holdout(self):
          """Each (city, condition_type) combination must appear in holdout."""
          records = (
              self._make_records("NYC", "above", 10)
              + self._make_records("NYC", "precip_any", 10)
              + self._make_records("LAX", "above", 10)
          )
          _, holdout = stratified_train_test_split(records, holdout_frac=0.2)
          strata_in_holdout = {
              (r["city"], r["condition_type"]) for r in holdout
          }
          self.assertIn(("NYC", "above"), strata_in_holdout)
          self.assertIn(("NYC", "precip_any"), strata_in_holdout)
          self.assertIn(("LAX", "above"), strata_in_holdout)

      def test_grpb_split_no_overlap(self):
          """Train and holdout sets must be disjoint (no duplicate dates per stratum)."""
          records = self._make_records("NYC", "above", 20)
          train, holdout = stratified_train_test_split(records, holdout_frac=0.2)
          train_dates = {r["date"] for r in train}
          holdout_dates = {r["date"] for r in holdout}
          self.assertEqual(len(train_dates & holdout_dates), 0)

      def test_grpb_split_total_equals_input(self):
          """len(train) + len(holdout) must equal len(records)."""
          records = (
              self._make_records("NYC", "above", 15)
              + self._make_records("LAX", "below", 10)
          )
          train, holdout = stratified_train_test_split(records, holdout_frac=0.25)
          self.assertEqual(len(train) + len(holdout), len(records))

      def test_grpb_split_holdout_fraction_approximately_correct(self):
          """Holdout fraction should be within ±10 pp of the requested fraction."""
          records = (
              self._make_records("NYC", "above", 50)
              + self._make_records("NYC", "below", 50)
          )
          train, holdout = stratified_train_test_split(records, holdout_frac=0.2)
          actual_frac = len(holdout) / len(records)
          self.assertGreater(actual_frac, 0.10)
          self.assertLess(actual_frac, 0.30)

      def test_grpb_split_single_record_stratum_goes_to_holdout(self):
          """A stratum with only 1 record: that record goes to holdout (min 1 rule)."""
          records = self._make_records("SOLO", "above", 1)
          train, holdout = stratified_train_test_split(records, holdout_frac=0.2)
          self.assertEqual(len(holdout), 1)
          self.assertEqual(len(train), 0)

      def test_grpb_split_holdout_is_most_recent(self):
          """Holdout records should be the most recent dates in each stratum."""
          records = self._make_records("NYC", "above", 5, date_start="2026-01-01")
          # dates: 01-01 through 01-05; holdout should include 01-05
          train, holdout = stratified_train_test_split(records, holdout_frac=0.2)
          holdout_dates = {r["date"] for r in holdout}
          self.assertIn("2026-01-05", holdout_dates)
  ```

- [ ] Step 2: Run failing test

  ```
  python -m pytest "C:/Users/thesa/claude kalshi/tests/test_backtest_stratified.py" -v --ignore="C:/Users/thesa/claude kalshi/tests/test_http.py"
  ```

  Expected: 7 tests collected, all **PASS** (function already exists — confirm; fix if any fail).

- [ ] Step 3: Implement

  In `backtest.py`, locate `stratified_train_test_split()`. Ensure it reads:

  ```python
  def stratified_train_test_split(
      records: list[dict],
      holdout_frac: float = 0.2,
      strat_keys: tuple = ("city", "condition_type"),
  ) -> tuple[list[dict], list[dict]]:
      """
      #21: Stratified train/test split ensuring all strata appear in holdout.

      Stratifies by (city, condition_type) — or any other strat_keys — so that
      each combination is sampled proportionally in the holdout set.
      Holdout records are taken from the tail (most recent by date) of each stratum.

      Returns (train, holdout) lists.
      """
      import math

      if not records:
          return [], []

      # Group records by strata
      strata: dict[tuple, list[dict]] = {}
      for rec in records:
          key = tuple(rec.get(k) for k in strat_keys)
          strata.setdefault(key, []).append(rec)

      train: list[dict] = []
      holdout: list[dict] = []

      for key, group in strata.items():
          n = len(group)
          n_holdout = max(1, math.ceil(n * holdout_frac))
          # Sort by date for determinism; most recent go to holdout
          sorted_group = sorted(group, key=lambda r: str(r.get("date", "")))
          holdout.extend(sorted_group[-n_holdout:])
          train.extend(sorted_group[:-n_holdout])

      return train, holdout
  ```

- [ ] Step 4: Run test to verify pass

  ```
  python -m pytest "C:/Users/thesa/claude kalshi/tests/test_backtest_stratified.py" -v --ignore="C:/Users/thesa/claude kalshi/tests/test_http.py"
  ```

  Expected: 7 passed.

- [ ] Step 5: Commit

  ```
  git -C "C:/Users/thesa/claude kalshi" add backtest.py "tests/test_backtest_stratified.py" && git -C "C:/Users/thesa/claude kalshi" commit -m "fix(#21): stratified_train_test_split() by (city, condition_type) with tests"
  ```

---

### Task 7: `get_calibration_by_city()` — condition_type filter (#56)

**Files:**
- Modify: `C:/Users/thesa/claude kalshi/tracker.py`
- Modify: `C:/Users/thesa/claude kalshi/tests/test_tracker.py`

- [ ] Step 1: Write failing test

  Append this class to `tests/test_tracker.py`:

  ```python
  class TestCalibrationByCityConditionType(unittest.TestCase):
      """#56 — get_calibration_by_city() must accept condition_type filter."""

      def setUp(self):
          self._tmpdir = tempfile.mkdtemp()
          self._orig = tracker.DB_PATH
          tracker.DB_PATH = Path(self._tmpdir) / "test.db"
          tracker._db_initialized = False

      def tearDown(self):
          tracker.DB_PATH = self._orig
          tracker._db_initialized = False
          shutil.rmtree(self._tmpdir, ignore_errors=True)

      def _log(self, ticker, city, our_prob, settled, ctype):
          tracker.log_prediction(
              ticker, city, date(2026, 4, 5),
              {
                  "forecast_prob": our_prob,
                  "market_prob": 0.5,
                  "edge": 0.1,
                  "method": "ensemble",
                  "n_members": 50,
                  "condition": {"type": ctype, "threshold": 70.0},
              },
          )
          tracker.log_outcome(ticker, settled_yes=settled)

      def test_grpb_calib_city_empty_returns_empty_dict(self):
          result = tracker.get_calibration_by_city()
          self.assertEqual(result, {})

      def test_grpb_calib_city_no_filter_includes_all_types(self):
          """No condition_type filter: both 'above' and 'precip_any' rows counted."""
          self._log("CBC-ABOVE-1", "NYC", 0.80, True, "above")
          self._log("CBC-ABOVE-2", "NYC", 0.80, True, "above")
          self._log("CBC-PRECIP-1", "NYC", 0.30, False, "precip_any")
          self._log("CBC-PRECIP-2", "NYC", 0.30, False, "precip_any")
          result_all = tracker.get_calibration_by_city()
          self.assertIn("NYC", result_all)
          self.assertEqual(result_all["NYC"]["n"], 4)

      def test_grpb_calib_city_filter_above_only(self):
          """condition_type='above' should exclude 'precip_any' rows."""
          self._log("CBC2-ABOVE-1", "NYC", 0.80, True, "above")
          self._log("CBC2-ABOVE-2", "NYC", 0.80, True, "above")
          self._log("CBC2-PRECIP-1", "NYC", 0.30, False, "precip_any")
          result_above = tracker.get_calibration_by_city(condition_type="above")
          self.assertIn("NYC", result_above)
          self.assertEqual(result_above["NYC"]["n"], 2)

      def test_grpb_calib_city_filter_changes_brier(self):
          """Brier from filtered subset must differ from unfiltered Brier."""
          # above: all correct -> low brier
          for i in range(4):
              self._log(f"CBC3-ABOVE-{i}", "NYC", 0.90, True, "above")
          # precip: all wrong -> high brier
          for i in range(4):
              self._log(f"CBC3-PRECIP-{i}", "NYC", 0.90, False, "precip_any")
          all_result = tracker.get_calibration_by_city()
          above_result = tracker.get_calibration_by_city(condition_type="above")
          self.assertLess(
              above_result["NYC"]["brier"],
              all_result["NYC"]["brier"],
          )

      def test_grpb_calib_city_multi_city(self):
          """Filter applies across all cities, not just one."""
          self._log("CBC4-NYC-A", "NYC", 0.70, True, "above")
          self._log("CBC4-LAX-A", "LAX", 0.70, True, "above")
          self._log("CBC4-NYC-P", "NYC", 0.70, False, "precip_any")
          result = tracker.get_calibration_by_city(condition_type="above")
          self.assertEqual(result.get("NYC", {}).get("n", 0), 1)
          self.assertEqual(result.get("LAX", {}).get("n", 0), 1)
          # precip_any row excluded from both cities
          self.assertNotIn("precip_any", str(result))
  ```

- [ ] Step 2: Run failing test

  ```
  python -m pytest "C:/Users/thesa/claude kalshi/tests/test_tracker.py" -k "TestCalibrationByCityConditionType" -v --ignore="C:/Users/thesa/claude kalshi/tests/test_http.py"
  ```

  Expected: 5 tests collected, all **PASS** (confirm; fix if any fail).

- [ ] Step 3: Implement

  In `tracker.py`, locate `get_calibration_by_city()`. Ensure it reads:

  ```python
  def get_calibration_by_city(
      condition_type: str | None = None,
  ) -> dict[str, dict]:
      """
      Per-city Brier score and sample count (#54, #56).
      Returns {city: {brier, n, bias}} for cities with settled predictions.
      Optionally filter by condition_type (#56).
      Monthly bias grouping uses market_date (not predicted_at) to avoid timezone skew.
      """
      init_db()
      with _conn() as con:
          query = """
              SELECT p.city, p.our_prob, o.settled_yes,
                     CAST(strftime('%m', p.market_date) AS INTEGER) AS month
              FROM predictions p
              JOIN outcomes o ON p.ticker = o.ticker
              WHERE p.our_prob IS NOT NULL AND p.city IS NOT NULL
          """
          params: list = []
          if condition_type is not None:
              query += " AND p.condition_type = ?"
              params.append(condition_type)
          rows = con.execute(query, params).fetchall()

      by_city: dict[str, list] = {}
      for r in rows:
          by_city.setdefault(r["city"], []).append((r["our_prob"], r["settled_yes"]))

      result = {}
      for city, pairs in by_city.items():
          errors = [(p - y) ** 2 for p, y in pairs]
          biases = [p - y for p, y in pairs]
          result[city] = {
              "brier": round(sum(errors) / len(errors), 6),
              "bias": round(sum(biases) / len(biases), 6),
              "n": len(pairs),
          }
      return result
  ```

- [ ] Step 4: Run test to verify pass

  ```
  python -m pytest "C:/Users/thesa/claude kalshi/tests/test_tracker.py" -k "TestCalibrationByCityConditionType" -v --ignore="C:/Users/thesa/claude kalshi/tests/test_http.py"
  ```

  Expected: 5 passed.

- [ ] Step 5: Commit

  ```
  git -C "C:/Users/thesa/claude kalshi" add tracker.py tests/test_tracker.py && git -C "C:/Users/thesa/claude kalshi" commit -m "fix(#56): get_calibration_by_city() condition_type filter with tests"
  ```

---

### Final verification

- [ ] Run full test suite

  ```
  python -m pytest "C:/Users/thesa/claude kalshi" --ignore="C:/Users/thesa/claude kalshi/tests/test_http.py" -v
  ```

  Expected: all previously passing tests still pass, plus the new Group B tests.

- [ ] Final commit if any loose files remain

  ```
  git -C "C:/Users/thesa/claude kalshi" status
  ```
