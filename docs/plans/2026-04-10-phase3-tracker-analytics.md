# Phase 3: Tracker & Analytics Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix calibration, Brier scoring, confusion matrix, bias, and edge decay so analytics are statistically sound and stratified by market type.

**Architecture:** All changes in tracker.py. New parameters added to existing functions; backwards-compatible.

**Tech Stack:** Python stdlib (statistics, math), sqlite3

**Covers:** #10, #11, #12, #13, #14, #18, #54, #56, #57, #60

---

### Task 1: get_bias() stratified by condition_type (#10)

**Files:**
- Modify: `tracker.py` — `get_bias()`

- [ ] **Step 1: Write failing test**

Add to `tests/test_tracker.py`:

```python
def test_get_bias_filters_by_condition_type(tmp_path):
    t, orig = make_test_db(tmp_path)
    # HIGH prediction: we said 0.8, settled YES
    t.log_prediction("T1", "NYC", "2026-01-01", "HIGH", 72, None, 0.8, 0.7, 0.1, "ensemble", 10, 1)
    t.record_outcome("T1", settled_yes=True)
    # PRECIP prediction: we said 0.2, settled NO
    t.log_prediction("T2", "NYC", "2026-01-02", "PRECIP", None, None, 0.2, 0.3, 0.1, "ensemble", 10, 1)
    t.record_outcome("T2", settled_yes=False)

    bias_high = t.get_bias("NYC", condition_type="HIGH")
    bias_precip = t.get_bias("NYC", condition_type="PRECIP")
    bias_all = t.get_bias("NYC")

    # With only 1 sample each, bias might be None or a float
    assert bias_high is None or isinstance(bias_high, float)
    assert bias_precip is None or isinstance(bias_precip, float)
    # All-types bias should differ from per-type if distributions differ
    t.DB_PATH = orig
    t._db_initialized = False
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_tracker.py::test_get_bias_filters_by_condition_type -v
```

Expected: FAIL — `get_bias` doesn't accept `condition_type`.

- [ ] **Step 3: Update get_bias() in tracker.py**

Find `get_bias` and add the `condition_type` parameter:

```python
def get_bias(city: str, condition_type: str | None = None, min_samples: int = 10) -> float | None:
    """
    Return mean(our_prob - settled_yes) for resolved predictions in `city`.
    Positive bias → we overestimate. Negative → we underestimate.
    Optionally filter by condition_type (e.g. 'HIGH', 'PRECIP', 'LOW').
    Returns None if fewer than min_samples resolved predictions.
    """
    query = """
        SELECT p.our_prob, o.settled_yes
        FROM predictions p
        JOIN outcomes o ON p.ticker = o.ticker
        WHERE p.city = ?
    """
    params: list = [city]
    if condition_type:
        query += " AND p.condition_type = ?"
        params.append(condition_type)

    with _conn() as con:
        rows = con.execute(query, params).fetchall()

    if len(rows) < min_samples:
        return None
    return statistics.mean(r["our_prob"] - r["settled_yes"] for r in rows)
```

- [ ] **Step 4: Run test**

```bash
python -m pytest tests/test_tracker.py::test_get_bias_filters_by_condition_type -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tracker.py tests/test_tracker.py
git commit -m "feat: get_bias() now stratified by condition_type (#10)"
```

---

### Task 2: Brier skill score vs climatology baseline (#11)

**Files:**
- Modify: `tracker.py` — add `brier_skill_score()`

- [ ] **Step 1: Write failing test**

Add to `tests/test_tracker.py`:

```python
def test_brier_skill_score_perfect_model(tmp_path):
    t, orig = make_test_db(tmp_path)
    # Perfect model: our_prob=1.0, settled YES, market_prob=0.5
    for i in range(15):
        t.log_prediction(f"T{i}", "NYC", f"2026-01-{i+1:02d}", "HIGH", 72, None,
                         1.0, 0.5, 0.5, "ensemble", 10, 1)
        t.record_outcome(f"T{i}", settled_yes=True)
    bss = t.brier_skill_score()
    assert bss is not None
    assert bss > 0, "Perfect model should have positive skill over climatology"
    t.DB_PATH = orig
    t._db_initialized = False


def test_brier_skill_score_no_skill_model(tmp_path):
    t, orig = make_test_db(tmp_path)
    # Climatology-level model: our_prob == market_prob
    for i in range(15):
        t.log_prediction(f"T{i}", "NYC", f"2026-01-{i+1:02d}", "HIGH", 72, None,
                         0.6, 0.6, 0.0, "ensemble", 10, 1)
        t.record_outcome(f"T{i}", settled_yes=True)
    bss = t.brier_skill_score()
    assert bss is not None
    assert abs(bss) < 0.01, "Model identical to reference should have ~0 skill"
    t.DB_PATH = orig
    t._db_initialized = False
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_tracker.py -k "brier_skill" -v
```

Expected: `AttributeError: module 'tracker' has no attribute 'brier_skill_score'`

- [ ] **Step 3: Implement brier_skill_score() in tracker.py**

```python
def brier_skill_score(city: str | None = None) -> float | None:
    """
    Brier Skill Score = 1 - (BS_model / BS_reference).
    Reference is the market probability (a reasonable baseline).
    BSS > 0 means our model adds value over just using market prices.
    BSS = 1 is perfect. BSS = 0 means no skill. BSS < 0 means worse than reference.
    Returns None if insufficient data.
    """
    query = """
        SELECT p.our_prob, p.market_prob, o.settled_yes
        FROM predictions p
        JOIN outcomes o ON p.ticker = o.ticker
        WHERE p.market_prob IS NOT NULL
    """
    params: list = []
    if city:
        query += " AND p.city = ?"
        params.append(city)

    with _conn() as con:
        rows = con.execute(query, params).fetchall()

    if len(rows) < 10:
        return None

    bs_model = statistics.mean((r["our_prob"] - r["settled_yes"]) ** 2 for r in rows)
    bs_ref = statistics.mean((r["market_prob"] - r["settled_yes"]) ** 2 for r in rows)

    if bs_ref == 0:
        return None  # avoid division by zero (perfect reference)
    return 1.0 - (bs_model / bs_ref)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_tracker.py -k "brier" -v
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add tracker.py tests/test_tracker.py
git commit -m "feat: Brier Skill Score vs market baseline (#11)"
```

---

### Task 3: Confusion matrix with tunable threshold (#12)

**Files:**
- Modify: `tracker.py` — `get_confusion_matrix()`

- [ ] **Step 1: Write test**

Add to `tests/test_tracker.py`:

```python
def test_confusion_matrix_custom_threshold(tmp_path):
    t, orig = make_test_db(tmp_path)
    # our_prob=0.7 at threshold=0.6 → predicted YES (TP if settled YES)
    t.log_prediction("CM1", "NYC", "2026-01-01", "HIGH", 72, None, 0.7, 0.6, 0.1, "ens", 10, 1)
    t.record_outcome("CM1", settled_yes=True)
    # our_prob=0.7 at threshold=0.8 → predicted NO (FN if settled YES)
    t.log_prediction("CM2", "NYC", "2026-01-02", "HIGH", 72, None, 0.7, 0.6, 0.1, "ens", 10, 1)
    t.record_outcome("CM2", settled_yes=True)

    cm_low = t.get_confusion_matrix(threshold=0.6)
    cm_high = t.get_confusion_matrix(threshold=0.8)
    assert cm_low is not None
    assert cm_high is not None
    # At low threshold both should be TP; at high threshold both FN
    assert cm_low.get("tp", 0) >= 1
    assert cm_high.get("fn", 0) >= 1
    t.DB_PATH = orig
    t._db_initialized = False
```

- [ ] **Step 2: Update get_confusion_matrix() in tracker.py**

Find `get_confusion_matrix` at line 648 and add the `threshold` parameter:

```python
def get_confusion_matrix(threshold: float = 0.5, city: str | None = None) -> dict | None:
    """
    Compute TP, FP, TN, FN at the given probability threshold.
    Returns dict with keys: tp, fp, tn, fn, precision, recall, f1.
    Returns None if no resolved predictions.
    """
    query = """
        SELECT p.our_prob, o.settled_yes
        FROM predictions p
        JOIN outcomes o ON p.ticker = o.ticker
    """
    params: list = []
    if city:
        query += " WHERE p.city = ?"
        params.append(city)

    with _conn() as con:
        rows = con.execute(query, params).fetchall()

    if not rows:
        return None

    tp = fp = tn = fn = 0
    for r in rows:
        pred_yes = r["our_prob"] >= threshold
        actual_yes = bool(r["settled_yes"])
        if pred_yes and actual_yes:
            tp += 1
        elif pred_yes and not actual_yes:
            fp += 1
        elif not pred_yes and not actual_yes:
            tn += 1
        else:
            fn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": precision, "recall": recall, "f1": f1,
            "threshold": threshold}
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_tracker.py -k "confusion" -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tracker.py tests/test_tracker.py
git commit -m "feat: confusion matrix with configurable threshold (#12)"
```

---

### Task 4: ROC curve with optimal threshold (#60)

**Files:**
- Modify: `tracker.py` — `get_roc_auc()` and add `get_optimal_threshold()`

- [ ] **Step 1: Write test**

Add to `tests/test_tracker.py`:

```python
def test_get_optimal_threshold(tmp_path):
    t, orig = make_test_db(tmp_path)
    # Create 20 predictions with known labels
    for i in range(10):
        prob = 0.7 + i * 0.01
        t.log_prediction(f"OT{i}", "NYC", f"2026-01-{i+1:02d}", "HIGH", 72, None,
                         prob, 0.5, prob - 0.5, "ens", 10, 1)
        t.record_outcome(f"OT{i}", settled_yes=True)
    for i in range(10, 20):
        prob = 0.3 - (i - 10) * 0.01
        t.log_prediction(f"OT{i}", "NYC", f"2026-01-{i+1:02d}", "HIGH", 72, None,
                         prob, 0.5, prob - 0.5, "ens", 10, 1)
        t.record_outcome(f"OT{i}", settled_yes=False)

    result = t.get_optimal_threshold()
    assert result is not None
    assert "threshold_f1" in result
    assert 0.0 <= result["threshold_f1"] <= 1.0
    t.DB_PATH = orig
    t._db_initialized = False
```

- [ ] **Step 2: Implement get_optimal_threshold()**

Add to `tracker.py`:

```python
def get_optimal_threshold() -> dict | None:
    """
    Sweep thresholds 0.05..0.95 and return the one maximizing F1.
    Also returns threshold maximizing precision-recall balance.
    Returns None if insufficient data.
    """
    with _conn() as con:
        rows = con.execute("""
            SELECT p.our_prob, o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
        """).fetchall()

    if len(rows) < 20:
        return None

    best_f1 = -1.0
    best_thresh_f1 = 0.5

    thresholds = [t / 100 for t in range(5, 96, 5)]
    for thresh in thresholds:
        tp = sum(1 for r in rows if r["our_prob"] >= thresh and r["settled_yes"])
        fp = sum(1 for r in rows if r["our_prob"] >= thresh and not r["settled_yes"])
        fn = sum(1 for r in rows if r["our_prob"] < thresh and r["settled_yes"])
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        if f1 > best_f1:
            best_f1 = f1
            best_thresh_f1 = thresh

    return {"threshold_f1": best_thresh_f1, "best_f1": best_f1}
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_tracker.py -k "optimal_threshold" -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tracker.py tests/test_tracker.py
git commit -m "feat: ROC threshold optimization, get_optimal_threshold() (#60)"
```

---

### Task 5: Adaptive calibration buckets (#13)

**Files:**
- Modify: `tracker.py` — `get_market_calibration()`

- [ ] **Step 1: Write test**

Add to `tests/test_tracker.py`:

```python
def test_calibration_uses_adaptive_buckets(tmp_path):
    t, orig = make_test_db(tmp_path)
    # 30 predictions all clustered at 0.48-0.52
    for i in range(30):
        prob = 0.48 + i * 0.001
        t.log_prediction(f"AC{i}", "NYC", f"2026-01-{i+1:02d}", "HIGH", 72, None,
                         prob, 0.5, prob - 0.5, "ens", 10, 1)
        t.record_outcome(f"AC{i}", settled_yes=(i % 2 == 0))

    cal = t.get_market_calibration(n_buckets=5)
    assert cal is not None
    assert len(cal) <= 5
    t.DB_PATH = orig
    t._db_initialized = False
```

- [ ] **Step 2: Update get_market_calibration()**

Find `get_market_calibration` and update signature + logic:

```python
def get_market_calibration(n_buckets: int = 10) -> list[dict] | None:
    """
    Adaptive calibration: buckets are equal-frequency (quantile-based),
    not fixed 10% widths. Each bucket has roughly the same number of predictions.
    Returns list of dicts: {bucket_min, bucket_max, mean_prob, freq_yes, count}.
    """
    with _conn() as con:
        rows = con.execute("""
            SELECT p.our_prob, o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            ORDER BY p.our_prob
        """).fetchall()

    if len(rows) < n_buckets * 2:
        return None

    probs = [r["our_prob"] for r in rows]
    labels = [r["settled_yes"] for r in rows]
    n = len(rows)
    bucket_size = n // n_buckets
    result = []

    for i in range(n_buckets):
        start = i * bucket_size
        end = start + bucket_size if i < n_buckets - 1 else n
        bucket_probs = probs[start:end]
        bucket_labels = labels[start:end]
        if not bucket_probs:
            continue
        result.append({
            "bucket_min": min(bucket_probs),
            "bucket_max": max(bucket_probs),
            "mean_prob": statistics.mean(bucket_probs),
            "freq_yes": statistics.mean(bucket_labels),
            "count": len(bucket_probs),
        })

    return result
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_tracker.py -k "adaptive_buckets" -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tracker.py tests/test_tracker.py
git commit -m "feat: adaptive calibration buckets (quantile-based) (#13)"
```

---

### Task 6: Per-city calibration by condition type (#56) + Monthly bias fix (#54)

**Files:**
- Modify: `tracker.py` — `get_calibration_by_city()`

- [ ] **Step 1: Update get_calibration_by_city()**

```python
def get_calibration_by_city(condition_type: str | None = None) -> dict[str, dict] | None:
    """
    Return calibration stats per city, optionally filtered by condition_type.
    Returns {city: {mean_prob, freq_yes, count, bias}} or None if no data.
    """
    query = """
        SELECT p.city,
               p.our_prob,
               o.settled_yes,
               strftime('%m', p.market_date) as settle_month
        FROM predictions p
        JOIN outcomes o ON p.ticker = o.ticker
        WHERE p.city IS NOT NULL
    """
    params: list = []
    if condition_type:
        query += " AND p.condition_type = ?"
        params.append(condition_type)

    with _conn() as con:
        rows = con.execute(query, params).fetchall()

    if not rows:
        return None

    from collections import defaultdict
    by_city: dict = defaultdict(list)
    for r in rows:
        by_city[r["city"]].append((r["our_prob"], r["settled_yes"]))

    result = {}
    for city, pairs in by_city.items():
        probs = [p for p, _ in pairs]
        labels = [y for _, y in pairs]
        result[city] = {
            "mean_prob": statistics.mean(probs),
            "freq_yes": statistics.mean(labels),
            "bias": statistics.mean(p - y for p, y in pairs),
            "count": len(pairs),
        }
    return result
```

- [ ] **Step 2: Fix monthly bias to use target_date month (#54)**

Find `get_calibration_trend` or monthly bias computation and ensure it uses `market_date` (the settlement date), not `predicted_at`:

```python
# In any monthly grouping query, use:
"strftime('%Y-%m', p.market_date) as month"
# NOT:
"strftime('%Y-%m', p.predicted_at) as month"
```

Search for and fix:

```bash
grep -n "predicted_at.*month\|strftime.*predicted_at" "C:/Users/thesa/claude kalshi/tracker.py"
```

- [ ] **Step 3: Write test for condition_type stratification**

Add to `tests/test_tracker.py`:

```python
def test_calibration_by_city_stratified(tmp_path):
    t, orig = make_test_db(tmp_path)
    # NYC HIGH: well calibrated
    for i in range(15):
        t.log_prediction(f"CAL_H{i}", "NYC", "2026-01-01", "HIGH", 72, None,
                         0.7, 0.6, 0.1, "ens", 10, 1)
        t.record_outcome(f"CAL_H{i}", settled_yes=True)
    # NYC PRECIP: poorly calibrated
    for i in range(15):
        t.log_prediction(f"CAL_P{i}", "NYC", "2026-01-02", "PRECIP", None, None,
                         0.8, 0.5, 0.3, "ens", 10, 1)
        t.record_outcome(f"CAL_P{i}", settled_yes=False)

    high_cal = t.get_calibration_by_city(condition_type="HIGH")
    precip_cal = t.get_calibration_by_city(condition_type="PRECIP")

    assert "NYC" in high_cal
    assert "NYC" in precip_cal
    assert high_cal["NYC"]["bias"] != precip_cal["NYC"]["bias"]
    t.DB_PATH = orig
    t._db_initialized = False
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_tracker.py -v
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add tracker.py tests/test_tracker.py
git commit -m "feat: calibration_by_city stratified by condition_type; fix monthly bias to use market_date (#54, #56)"
```

---

### Task 7: Ensemble MAE stratified by season and region (#18)

**Files:**
- Modify: `tracker.py` — `get_source_reliability()` / member accuracy

- [ ] **Step 1: Add seasonal breakdown to member accuracy**

Add function to `tracker.py`:

```python
def get_ensemble_member_accuracy(city: str | None = None, season: str | None = None) -> dict | None:
    """
    Return MAE per model, optionally stratified by city and season.
    season: 'winter' (Oct-Mar) or 'summer' (Apr-Sep).
    Returns {model: {mae, count}} or None.
    """
    query = """
        SELECT model,
               ABS(predicted_temp - actual_temp) as abs_err,
               strftime('%m', target_date) as month
        FROM ensemble_member_scores
        WHERE actual_temp IS NOT NULL AND predicted_temp IS NOT NULL
    """
    params: list = []
    if city:
        query += " AND city = ?"
        params.append(city)

    with _conn() as con:
        rows = con.execute(query, params).fetchall()

    if not rows:
        return None

    WINTER_MONTHS = {"10", "11", "12", "01", "02", "03"}
    from collections import defaultdict
    by_model: dict = defaultdict(list)

    for r in rows:
        if season == "winter" and r["month"] not in WINTER_MONTHS:
            continue
        if season == "summer" and r["month"] in WINTER_MONTHS:
            continue
        by_model[r["model"]].append(r["abs_err"])

    if not by_model:
        return None

    return {
        model: {"mae": statistics.mean(errors), "count": len(errors)}
        for model, errors in by_model.items()
    }
```

- [ ] **Step 2: Write test**

Add to `tests/test_tracker.py`:

```python
def test_ensemble_member_accuracy_seasonal(tmp_path):
    import tracker
    orig = tracker.DB_PATH
    tracker.DB_PATH = tmp_path / "ens_test.db"
    tracker._db_initialized = False
    tracker.init_db()

    with tracker._conn() as con:
        # Winter data
        for i in range(5):
            con.execute(
                "INSERT INTO ensemble_member_scores (city, model, predicted_temp, actual_temp, target_date, logged_at) VALUES (?,?,?,?,?,?)",
                ("NYC", "gfs_seamless", 32.0, 35.0, f"2026-01-{i+1:02d}", "2026-01-01T00:00:00")
            )
        # Summer data
        for i in range(5):
            con.execute(
                "INSERT INTO ensemble_member_scores (city, model, predicted_temp, actual_temp, target_date, logged_at) VALUES (?,?,?,?,?,?)",
                ("NYC", "gfs_seamless", 80.0, 90.0, f"2026-07-{i+1:02d}", "2026-07-01T00:00:00")
            )

    winter_acc = tracker.get_ensemble_member_accuracy(city="NYC", season="winter")
    summer_acc = tracker.get_ensemble_member_accuracy(city="NYC", season="summer")

    assert winter_acc is not None
    assert summer_acc is not None
    assert winter_acc["gfs_seamless"]["mae"] != summer_acc["gfs_seamless"]["mae"]

    tracker.DB_PATH = orig
    tracker._db_initialized = False
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_tracker.py -v
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add tracker.py tests/test_tracker.py
git commit -m "feat: ensemble member MAE stratified by season and city (#18)"
```

---

### Task 8: Bayesian shrinking confidence intervals (#57)

**Files:**
- Modify: `tracker.py` — any CI computation using bootstrap

- [ ] **Step 1: Add shrinking CI function**

Add to `tracker.py`:

```python
def bayesian_confidence_interval(successes: int, trials: int, confidence: float = 0.90) -> tuple[float, float]:
    """
    Beta-distribution posterior CI for a proportion.
    Prior: Beta(1, 1) (uniform). Posterior: Beta(1+successes, 1+failures).
    CI shrinks correctly as N → ∞ unlike fixed bootstrap CI.
    Returns (lower, upper).
    """
    import math

    alpha_prior = 1.0
    beta_prior = 1.0
    a = alpha_prior + successes
    b = beta_prior + (trials - successes)

    # Use Wilson interval approximation (closed-form, accurate)
    z = 1.645 if confidence == 0.90 else 1.96  # 90% or 95%
    p_hat = a / (a + b)
    n = a + b
    center = (p_hat + z * z / (2 * n)) / (1 + z * z / n)
    margin = z * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, center - margin), min(1.0, center + margin)
```

- [ ] **Step 2: Write test**

Add to `tests/test_tracker.py`:

```python
def test_bayesian_ci_shrinks_with_more_data():
    from tracker import bayesian_confidence_interval
    lo_small, hi_small = bayesian_confidence_interval(5, 10)
    lo_large, hi_large = bayesian_confidence_interval(500, 1000)
    width_small = hi_small - lo_small
    width_large = hi_large - lo_large
    assert width_large < width_small, "CI should shrink with more data"

def test_bayesian_ci_bounds_valid():
    from tracker import bayesian_confidence_interval
    lo, hi = bayesian_confidence_interval(7, 10)
    assert 0.0 <= lo <= hi <= 1.0
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_tracker.py -k "bayesian_ci" -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tracker.py tests/test_tracker.py
git commit -m "feat: Bayesian shrinking confidence intervals for calibration (#57)"
```

---

### Task 9: Edge decay curve stratified by condition type (#14)

**Files:**
- Modify: `tracker.py` — `get_edge_decay_curve()`

- [ ] **Step 1: Update get_edge_decay_curve()**

Find `get_edge_decay_curve` and add `condition_type` parameter:

```python
def get_edge_decay_curve(condition_type: str | None = None) -> list[dict] | None:
    """
    Return average realized edge (our_prob - market_prob) binned by days_out.
    Optionally filter by condition_type so temp and precip markets have separate curves.
    """
    query = """
        SELECT p.days_out,
               p.our_prob - p.market_prob as pred_edge,
               o.settled_yes,
               p.our_prob
        FROM predictions p
        JOIN outcomes o ON p.ticker = o.ticker
        WHERE p.days_out IS NOT NULL AND p.market_prob IS NOT NULL
    """
    params: list = []
    if condition_type:
        query += " AND p.condition_type = ?"
        params.append(condition_type)
    query += " ORDER BY p.days_out"

    with _conn() as con:
        rows = con.execute(query, params).fetchall()

    if len(rows) < 10:
        return None

    from collections import defaultdict
    by_days: dict = defaultdict(list)
    for r in rows:
        realized = r["our_prob"] - r["settled_yes"]
        by_days[r["days_out"]].append(realized)

    return [
        {"days_out": days, "mean_realized_edge": statistics.mean(vals), "count": len(vals)}
        for days, vals in sorted(by_days.items())
        if len(vals) >= 3
    ]
```

- [ ] **Step 2: Write test**

Add to `tests/test_tracker.py`:

```python
def test_edge_decay_by_condition(tmp_path):
    t, orig = make_test_db(tmp_path)
    for i in range(15):
        t.log_prediction(f"ED_H{i}", "NYC", "2026-01-01", "HIGH", 72, None,
                         0.7, 0.6, 0.1, "ens", 10, i % 7 + 1)
        t.record_outcome(f"ED_H{i}", settled_yes=True)
    for i in range(15):
        t.log_prediction(f"ED_P{i}", "NYC", "2026-01-01", "PRECIP", None, None,
                         0.6, 0.5, 0.1, "ens", 10, i % 7 + 1)
        t.record_outcome(f"ED_P{i}", settled_yes=False)

    high_curve = t.get_edge_decay_curve(condition_type="HIGH")
    precip_curve = t.get_edge_decay_curve(condition_type="PRECIP")
    assert high_curve is not None or precip_curve is not None
    t.DB_PATH = orig
    t._db_initialized = False
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_tracker.py -v
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add tracker.py tests/test_tracker.py
git commit -m "feat: edge decay curve stratified by condition_type (#14)"
```
