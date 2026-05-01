# Fix Web Analytics Charts — All Shape Mismatches

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all broken charts on the analytics page. The root cause is four shape mismatches between the Python API responses and what `static/analytics.js` reads. Bug #1 is critical: a `TypeError` from the calibration chart crash propagates silently and prevents ALL subsequent charts in the same `loadAnalytics()` callback from rendering (attribution, Brier-by-days, city calibration — all blank because the crash fires first).

**Architecture:**
All fixes are in `static/analytics.js`. The API responses are correct — the JS is reading them wrong.

| Chart | Bug | Fix |
|---|---|---|
| Calibration Curve | `d.model_calibration_buckets` is `{"buckets":[...]}` but JS maps it as an array → **TypeError crash** | Unwrap `.buckets`; rename `.predicted_prob` → `.our_prob_avg` |
| P&L Attribution by Source | `attr[s].brier_score` → key is `"brier"` not `"brier_score"` | Change to `attr[s].brier` |
| ROC Curve | `roc.fpr`/`roc.tpr` flat arrays → actual shape is `roc.points: [{fpr,tpr}]` | Map over `roc.points` |
| All downstream charts in `loadAnalytics()` | Blocked by calibration crash above | Unblocked once crash is fixed |

**Charts that need real data (not code bugs):** Brier Score History, ICON vs GFS Accuracy, Model Blend by City, Price Improvement, Source Reliability all have correct JS logic — they show "no data" until enough settled trades exist in the DB. No code changes needed for those.

**Tech Stack:** JavaScript (`static/analytics.js`), Python test for API shape (`tests/test_web_analytics.py`)

---

## Root Cause Summary

| Chart | File | Bug | Effect |
|---|---|---|---|
| Calibration Curve | `static/analytics.js` line 36 | `calBuckets.map(...)` throws TypeError — `calBuckets` is `{buckets:[...]}` not an array | **Crashes entire `loadAnalytics()` callback** |
| Calibration Curve | `static/analytics.js` line 38 | `.predicted_prob` field doesn't exist; correct field is `our_prob_avg` | Blank x-axis even if unwrapped |
| P&L Attribution | `static/analytics.js` line 76 | `.brier_score` doesn't exist; API returns `.brier` | All attribution bars show 0 |
| ROC Curve | `static/analytics.js` lines 56–62 | Reads `roc.fpr`/`roc.tpr` as flat arrays; real shape is `roc.points: [{fpr,tpr}]` | ROC line never draws |

---

## Task 1: Fix `loadAnalytics()` — calibration crash, attribution field, and ROC shape

**Files:**
- Modify: `static/analytics.js` (3 changes within `loadAnalytics()`)
- Create: `tests/test_web_analytics.py`

- [ ] **Step 1: Write failing tests that pin the API contract**

Create `tests/test_web_analytics.py`:

```python
"""Tests for web analytics API shape contracts."""
import json
from unittest.mock import patch


class TestAnalyticsApiShape:
    def test_model_calibration_buckets_has_buckets_key(self, monkeypatch):
        """api_analytics must return model_calibration_buckets with a .buckets array
        whose items have our_prob_avg and actual_rate keys (NOT predicted_prob)."""
        import web_app

        mock_buckets = {
            "buckets": [
                {
                    "range": "40-50%",
                    "our_prob_avg": 0.45,
                    "actual_rate": 0.43,
                    "deviation": -0.02,
                    "n": 12,
                }
            ]
        }

        with patch("tracker.brier_score", return_value=0.18), \
             patch("tracker.get_brier_by_days_out", return_value={}), \
             patch("tracker.get_calibration_by_city", return_value={}), \
             patch("tracker.get_component_attribution", return_value={}), \
             patch("tracker.get_model_calibration_buckets", return_value=mock_buckets):
            app = web_app.create_app()
            client = app.test_client()
            resp = client.get("/api/analytics")

        assert resp.status_code == 200
        data = resp.get_json()
        cal = data.get("model_calibration_buckets")
        assert cal is not None, "model_calibration_buckets key missing"
        assert "buckets" in cal, f"Expected 'buckets' key, got: {list(cal.keys())}"
        bucket = cal["buckets"][0]
        assert "our_prob_avg" in bucket, f"Expected 'our_prob_avg', got: {list(bucket.keys())}"
        assert "predicted_prob" not in bucket, "predicted_prob does not exist in API response"

    def test_roc_auc_has_points_array(self):
        """api_analytics must return roc_auc with points:[{fpr,tpr}] — NOT top-level fpr/tpr arrays."""
        import web_app

        mock_roc = {
            "auc": 0.72,
            "n": 100,
            "points": [
                {"fpr": 0.0, "tpr": 0.0},
                {"fpr": 0.5, "tpr": 0.8},
                {"fpr": 1.0, "tpr": 1.0},
            ],
        }

        with patch("tracker.brier_score", return_value=0.18), \
             patch("tracker.get_brier_by_days_out", return_value={}), \
             patch("tracker.get_calibration_by_city", return_value={}), \
             patch("tracker.get_component_attribution", return_value={}), \
             patch("tracker.get_roc_auc", return_value=mock_roc):
            app = web_app.create_app()
            client = app.test_client()
            resp = client.get("/api/analytics")

        assert resp.status_code == 200
        data = resp.get_json()
        roc = data.get("roc_auc")
        assert roc is not None, "roc_auc missing from response"
        assert "points" in roc, f"Expected 'points' key, got: {list(roc.keys())}"
        assert "fpr" not in roc, "roc_auc must NOT have top-level 'fpr' array"
        pt = roc["points"][0]
        assert "fpr" in pt and "tpr" in pt

    def test_component_attribution_key_is_brier_not_brier_score(self):
        """api_analytics component_attribution must use 'brier' key, not 'brier_score'."""
        import web_app

        mock_attr = {"gaussian": {"n": 20, "brier": 0.18}}

        with patch("tracker.brier_score", return_value=0.18), \
             patch("tracker.get_brier_by_days_out", return_value={}), \
             patch("tracker.get_calibration_by_city", return_value={}), \
             patch("tracker.get_component_attribution", return_value=mock_attr):
            app = web_app.create_app()
            client = app.test_client()
            resp = client.get("/api/analytics")

        data = resp.get_json()
        attr = data.get("component_attribution", {})
        gaussian = attr.get("gaussian", {})
        assert "brier" in gaussian, f"Expected key 'brier', got: {list(gaussian.keys())}"
        assert "brier_score" not in gaussian, "'brier_score' is wrong key name"
```

- [ ] **Step 2: Run tests — all 3 should PASS (API shape is already correct)**

```
python -m pytest tests/test_web_analytics.py -v
```

Expected: PASS. These tests pin the contract so future changes can't break the API shape.

- [ ] **Step 3: Fix calibration in `analytics.js`**

Find (around line 35):
```javascript
      var calBuckets = d.model_calibration_buckets;
      if (calBuckets) {
        var xCal = calBuckets.map(function (b) { return b.predicted_prob; });
        var yCal = calBuckets.map(function (b) { return b.actual_rate; });
```

Replace with:
```javascript
      var calBuckets = d.model_calibration_buckets && d.model_calibration_buckets.buckets;
      if (calBuckets && calBuckets.length) {
        var xCal = calBuckets.map(function (b) { return b.our_prob_avg; });
        var yCal = calBuckets.map(function (b) { return b.actual_rate; });
```

> **Why this matters beyond calibration:** The old line `calBuckets.map(...)` throws `TypeError: calBuckets.map is not a function` because `calBuckets` is an object `{buckets:[...]}`, not an array. This TypeError silently crashes the entire `.then(function(d){...})` callback, preventing attribution, Brier-by-days, and city calibration from rendering at all. Unwrapping `.buckets` first fixes the crash and unblocks all subsequent charts.

- [ ] **Step 4: Fix P&L attribution field name in `analytics.js`**

Find (around line 76):
```javascript
        var brierVals = sources.map(function (s) { return (attr[s] || {}).brier_score || 0; });
```

Replace with:
```javascript
        var brierVals = sources.map(function (s) { return (attr[s] || {}).brier || 0; });
```

- [ ] **Step 5: Fix ROC curve in `analytics.js`**

Find (around line 55):
```javascript
      var roc = d.roc_auc;
      if (roc && roc.fpr && roc.tpr) {
```

And (around line 62):
```javascript
            { x: roc.fpr, y: roc.tpr, type: 'scatter', mode: 'lines',
```

Replace the full ROC block:
```javascript
      var roc = d.roc_auc;
      if (roc && roc.points && roc.points.length) {
        var rocFpr = roc.points.map(function(p) { return p.fpr; });
        var rocTpr = roc.points.map(function(p) { return p.tpr; });
        var rocEl = document.getElementById('roc-chart');
        if (rocEl && typeof Plotly !== 'undefined') {
          Plotly.newPlot(rocEl, [
            { x: [0, 1], y: [0, 1], type: 'scatter', mode: 'lines', name: 'Random',
              line: { color: C.muted, dash: 'dash', width: 1 } },
            { x: rocFpr, y: rocTpr, type: 'scatter', mode: 'lines',
              name: 'Model (AUC=' + (roc.auc || 0).toFixed(3) + ')',
              line: { color: C.accent, width: 2 } }
          ], makeLayout({
```

> Read the full existing ROC block before editing to preserve the `makeLayout` call and closing `}` exactly.

- [ ] **Step 6: Run full suite**

```
python -m pytest tests/ -q --tb=short
```

Expected: all prior tests pass, 3 new API-shape tests pass.

- [ ] **Step 7: Commit**

```bash
git add static/analytics.js tests/test_web_analytics.py
git commit -m "fix: analytics charts — unwrap calibration.buckets, our_prob_avg, brier field, roc.points"
```

---

## Self-Review

**Spec coverage:**
- ✅ Calibration Curve crash (TypeError) → Step 3 (unwrap `.buckets`, guard `.length`)
- ✅ Calibration Curve wrong field → Step 3 (`our_prob_avg` not `predicted_prob`)
- ✅ P&L Attribution bars all zero → Step 4 (`.brier` not `.brier_score`)
- ✅ ROC Curve blank → Step 5 (map `roc.points` not `roc.fpr`/`roc.tpr`)
- ✅ All downstream charts in callback unblocked → Step 3 (crash removed)

**Charts that need data, not code fixes (no changes required):**
- Brier Score History (`/api/brier_history`) — correct JS, needs settled trades
- ICON vs GFS Accuracy (`/api/ensemble-accuracy`) — shows expected "no data" message
- Model Blend by City (`/api/model-attribution`) — shows expected "no data" message
- Price Improvement (`/api/price-improvement`) — shows expected "needs 5+ trades" message
- Source Reliability (`/api/source-reliability`) — correct JS, needs data

**Placeholder scan:** None found.

**Type consistency:** Pure JS change — no Python types affected.
