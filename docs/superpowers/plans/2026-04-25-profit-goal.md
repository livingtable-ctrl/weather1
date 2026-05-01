# Profit Goal Feature

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user set a personal profit target (default $50) that is saved to disk and used to drive the P&L progress bar on the dashboard. The hardcoded `$50` values in `dashboard.js` and `dashboard.html` are replaced with a configurable value fetched from a new `/api/profit-goal` endpoint.

**Architecture:**
- **Storage:** `data/user_prefs.json` — a simple key/value JSON file in the existing `data/` directory. Key: `"profit_goal"`, default: `50.0`.
- **API:** Two new routes in `web_app.py`:
  - `GET /api/profit-goal` → `{"profit_goal": 50.0}`
  - `POST /api/profit-goal` with body `{"profit_goal": <number>}` → saves and returns updated value
- **Dashboard:** `dashboard.js` fetches the goal on page load and uses it in the P&L bar. A small inline edit widget (click to change) next to the label triggers a POST.
- **HTML:** `templates/dashboard.html` gains a clickable goal display and a hidden input form.

**Tech Stack:** Python (`web_app.py`), JavaScript (`static/dashboard.js`), HTML (`templates/dashboard.html`), `tests/test_profit_goal.py` (new)

---

## Root Cause Summary

| Issue | File | Location | Cause |
|---|---|---|---|
| P&L goal hardcoded | `dashboard.js` | Lines 92–95 | `$50` literal used for label, bar width, and completion check |
| P&L goal hardcoded | `dashboard.html` | Line 59 | Default label text `—/$50` |
| No persistence | (missing) | — | No API or storage for user-set goal |

---

## Task 1: Add persistence layer and API

**Files:**
- Create: `tests/test_profit_goal.py`
- Modify: `web_app.py` (add two routes)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profit_goal.py`:

```python
"""Tests for profit goal API endpoints."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch


class TestProfitGoalApi:
    def _make_app(self, data_dir):
        import web_app
        return web_app.create_app()

    def test_get_returns_default_when_no_prefs_file(self, tmp_path, monkeypatch):
        """GET /api/profit-goal returns default 50.0 when data/user_prefs.json is absent."""
        import web_app

        monkeypatch.setattr(web_app, "_PREFS_PATH", tmp_path / "user_prefs.json")
        app = web_app.create_app()
        client = app.test_client()

        resp = client.get("/api/profit-goal")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["profit_goal"] == 50.0

    def test_post_saves_and_returns_new_goal(self, tmp_path, monkeypatch):
        """POST /api/profit-goal saves the value and returns it."""
        import web_app

        prefs = tmp_path / "user_prefs.json"
        monkeypatch.setattr(web_app, "_PREFS_PATH", prefs)
        app = web_app.create_app()
        client = app.test_client()

        resp = client.post(
            "/api/profit-goal",
            data=json.dumps({"profit_goal": 200.0}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["profit_goal"] == 200.0

        # Verify persisted
        saved = json.loads(prefs.read_text())
        assert saved["profit_goal"] == 200.0

    def test_post_rejects_non_positive_goal(self, tmp_path, monkeypatch):
        """POST /api/profit-goal rejects zero or negative values."""
        import web_app

        monkeypatch.setattr(web_app, "_PREFS_PATH", tmp_path / "user_prefs.json")
        app = web_app.create_app()
        client = app.test_client()

        for bad in [0, -10, -0.01]:
            resp = client.post(
                "/api/profit-goal",
                data=json.dumps({"profit_goal": bad}),
                content_type="application/json",
            )
            assert resp.status_code == 400, f"Expected 400 for goal={bad}"

    def test_get_reads_persisted_value(self, tmp_path, monkeypatch):
        """GET /api/profit-goal returns a previously saved value."""
        import web_app

        prefs = tmp_path / "user_prefs.json"
        prefs.write_text(json.dumps({"profit_goal": 150.0}))
        monkeypatch.setattr(web_app, "_PREFS_PATH", prefs)
        app = web_app.create_app()
        client = app.test_client()

        resp = client.get("/api/profit-goal")
        assert resp.status_code == 200
        assert resp.get_json()["profit_goal"] == 150.0
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_profit_goal.py -v
```

Expected: FAIL — `_PREFS_PATH` and the routes do not exist yet.

- [ ] **Step 3: Add `_PREFS_PATH` and two routes to `web_app.py`**

Near the top of `web_app.py`, after the existing imports, add:

```python
import json as _json
from pathlib import Path as _Path

_PREFS_PATH: _Path = _Path(__file__).parent / "data" / "user_prefs.json"
_DEFAULT_PROFIT_GOAL: float = 50.0


def _load_profit_goal() -> float:
    try:
        if _PREFS_PATH.exists():
            data = _json.loads(_PREFS_PATH.read_text())
            return float(data.get("profit_goal", _DEFAULT_PROFIT_GOAL))
    except Exception:
        pass
    return _DEFAULT_PROFIT_GOAL


def _save_profit_goal(goal: float) -> None:
    _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing: dict = {}
        if _PREFS_PATH.exists():
            existing = _json.loads(_PREFS_PATH.read_text())
    except Exception:
        existing = {}
    existing["profit_goal"] = goal
    _PREFS_PATH.write_text(_json.dumps(existing, indent=2))
```

Then, inside `create_app()` alongside the other routes, add:

```python
    @app.route("/api/profit-goal", methods=["GET"])
    def api_get_profit_goal():
        return jsonify({"profit_goal": _load_profit_goal()})

    @app.route("/api/profit-goal", methods=["POST"])
    def api_set_profit_goal():
        try:
            body = request.get_json(force=True) or {}
            goal = float(body.get("profit_goal", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "profit_goal must be a number"}), 400
        if goal <= 0:
            return jsonify({"error": "profit_goal must be positive"}), 400
        _save_profit_goal(goal)
        return jsonify({"profit_goal": goal})
```

> **Note:** `request` and `jsonify` are already imported from Flask in `web_app.py`.

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_profit_goal.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web_app.py tests/test_profit_goal.py
git commit -m "feat: add GET/POST /api/profit-goal with persistence to data/user_prefs.json"
```

---

## Task 2: Wire dashboard JS and HTML to use the saved goal

**Files:**
- Modify: `static/dashboard.js` lines 88–96
- Modify: `templates/dashboard.html` lines 58–63

- [ ] **Step 1: Update `dashboard.js` to fetch and use the goal**

In `static/dashboard.js`, replace the P&L progress block (lines 88–96):

```javascript
      // P&L progress bar (target: $50)
      var pnl = d.total_pnl || 0;
      var pnlLabel = document.getElementById('grad-pnl-label');
      var pnlBar = document.getElementById('grad-pnl-bar');
      if (pnlLabel) pnlLabel.textContent = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2) + '/$50';
      if (pnlBar) {
        pnlBar.style.width = Math.min(100, Math.max(0, (pnl / 50) * 100)) + '%';
        pnlBar.classList.toggle('complete', pnl >= 50);
      }
```

With:

```javascript
      // P&L progress bar — goal fetched from /api/profit-goal
      var pnl = d.total_pnl || 0;
      fetch('/api/profit-goal')
        .then(function(r) { return r.json(); })
        .then(function(g) {
          var goal = g.profit_goal || 50;
          var pnlLabel = document.getElementById('grad-pnl-label');
          var pnlBar = document.getElementById('grad-pnl-bar');
          var goalSpan = document.getElementById('grad-pnl-goal');
          if (pnlLabel) pnlLabel.textContent = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2) + '/$' + goal.toFixed(0);
          if (goalSpan) goalSpan.textContent = '$' + goal.toFixed(0);
          if (pnlBar) {
            pnlBar.style.width = Math.min(100, Math.max(0, (pnl / goal) * 100)) + '%';
            pnlBar.classList.toggle('complete', pnl >= goal);
          }
        })
        .catch(function() {
          // Fallback: hardcoded $50
          var pnlLabel = document.getElementById('grad-pnl-label');
          var pnlBar = document.getElementById('grad-pnl-bar');
          if (pnlLabel) pnlLabel.textContent = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2) + '/$50';
          if (pnlBar) {
            pnlBar.style.width = Math.min(100, Math.max(0, (pnl / 50) * 100)) + '%';
            pnlBar.classList.toggle('complete', pnl >= 50);
          }
        });
```

Also add a goal-edit handler at the end of `dashboard.js` (outside the `fetch('/api/graduation')` callback):

```javascript
    // Allow clicking the goal label to change the profit target
    var goalSpan = document.getElementById('grad-pnl-goal');
    if (goalSpan) {
      goalSpan.style.cursor = 'pointer';
      goalSpan.title = 'Click to change profit goal';
      goalSpan.addEventListener('click', function() {
        var current = parseFloat(goalSpan.textContent.replace(/[^0-9.]/g, '')) || 50;
        var input = prompt('Set profit goal ($):', current);
        if (input === null) return;
        var newGoal = parseFloat(input);
        if (isNaN(newGoal) || newGoal <= 0) { alert('Enter a positive number.'); return; }
        fetch('/api/profit-goal', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({profit_goal: newGoal})
        }).then(function() { location.reload(); });
      });
    }
```

- [ ] **Step 2: Update `dashboard.html` to add the goal span**

In `templates/dashboard.html`, find (line 59):
```html
        <span id="grad-pnl-label">—/$50</span>
```

Replace with:
```html
        <span id="grad-pnl-label">—/<span id="grad-pnl-goal" title="Click to change profit goal" style="cursor:pointer;text-decoration:underline dotted">$50</span></span>
```

- [ ] **Step 3: Smoke-test in the running app**

Start the app and open the dashboard. Verify:
1. P&L bar label shows `—/$50` (or actual P&L) by default.
2. Clicking `$50` prompts for a new goal.
3. Entering `200` reloads the page and shows `/$200`.
4. Refreshing keeps the new value.

- [ ] **Step 4: Run full suite**

```
python -m pytest tests/ -q --tb=short
```

Expected: all prior tests still pass, 4 new profit-goal API tests pass.

- [ ] **Step 5: Commit**

```bash
git add static/dashboard.js templates/dashboard.html
git commit -m "feat: P&L bar uses configurable profit goal; click label to change target"
```

---

## Self-Review

**Spec coverage:**
- ✅ Profit goal stored → `data/user_prefs.json` via `_save_profit_goal()`
- ✅ Profit goal displayed → P&L bar label shows `+$X.XX/$GOAL`
- ✅ Profit goal editable → click goal span → prompt → POST → reload

**Placeholder scan:** None found.

**Type consistency:** `profit_goal` stored as `float`, returned as `float`, displayed as `int` (`.toFixed(0)`).
