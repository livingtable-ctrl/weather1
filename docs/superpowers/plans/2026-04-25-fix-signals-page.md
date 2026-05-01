# Fix Signals Page — Relative Path Bug + Stale Cache Rejection

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the signals page show live data and have the "Run Scan Now" button work reliably.

**Architecture:** Two bugs:
1. `web_app.py` reads `pathlib.Path("data/signals_cache.json")` — a relative path from the CWD at runtime. `cron.py` writes to `Path(__file__).parent / "data" / "signals_cache.json"` (absolute). If the web server is started from any directory other than the project root, the web app never finds the file the cron wrote. Same bug in `api_signals()` reading `data/cron.log`. Fix: use `Path(__file__).parent / "data" / ...` everywhere in `web_app.py`.
2. The 90-minute stale cache rejection is very aggressive for development — if a cron ran 91 minutes ago, the page shows empty signals even though the data is valid. Raise the stale threshold to 4 hours (one full cron cycle) so the page still shows the last scan.

**Tech Stack:** Python (`web_app.py`), `tests/test_signals_page.py` (new)

---

## Root Cause Summary

| Bug | File | Location | Cause |
|---|---|---|---|
| Signals cache never found | `web_app.py` | Line 683 | `pathlib.Path("data/signals_cache.json")` relative to CWD; cron writes to absolute script-relative path |
| Cron log never found | `web_app.py` | Line 1003 | `pathlib.Path("data/cron.log")` same relative-path bug |
| Data disappears after 90 min | `web_app.py` | Line 674 | `MAX_SIGNALS_CACHE_AGE_SECS = 90 * 60` is shorter than a full 4-hour cron cycle |

---

## Task 1: Fix relative paths and stale threshold

**Files:**
- Modify: `web_app.py` lines 674, 683, 1003
- Create: `tests/test_signals_page.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_signals_page.py`:

```python
"""Tests for signals page path handling."""
import json
import time
from pathlib import Path
from unittest.mock import patch


class TestSignalsCachePath:
    def test_live_signals_reads_from_script_relative_data_dir(self, tmp_path, monkeypatch):
        """api/live_signals must find signals_cache.json relative to web_app.py, not CWD."""
        import web_app

        # Write a fake signals cache in a temp dir (simulating the correct absolute path)
        fake_cache = {
            "signals": [{"ticker": "KXWT-24-T50-B3", "city": "NYC", "edge_pct": 12.5}],
            "summary": {"scanned": 5, "with_edge": 1, "strong": 0, "low_risk": 0},
            "generated_at": "2026-04-25T12:00:00",
        }

        # Patch the DATA_DIR used inside web_app so the test controls the path
        monkeypatch.setattr(web_app, "_SIGNALS_CACHE_PATH", tmp_path / "signals_cache.json")
        (tmp_path / "signals_cache.json").write_text(json.dumps(fake_cache))

        app = web_app.create_app()
        client = app.test_client()
        resp = client.get("/api/live_signals")
        data = resp.get_json()

        assert resp.status_code == 200
        assert len(data["signals"]) == 1
        assert data["signals"][0]["ticker"] == "KXWT-24-T50-B3"

    def test_stale_threshold_is_at_least_4_hours(self):
        """MAX_SIGNALS_CACHE_AGE_SECS must be >= 14400 (4 hours = one cron cycle)."""
        import web_app
        assert web_app.MAX_SIGNALS_CACHE_AGE_SECS >= 4 * 3600, (
            f"Stale threshold {web_app.MAX_SIGNALS_CACHE_AGE_SECS}s is shorter than "
            "a full 4-hour cron cycle; signals disappear between runs"
        )

    def test_cron_log_path_is_absolute(self):
        """api/signals must use an absolute path to data/cron.log."""
        import web_app
        assert web_app._CRON_LOG_PATH.is_absolute(), (
            "_CRON_LOG_PATH must be absolute (relative to web_app.py), not CWD-relative"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_signals_page.py -v
```

Expected: FAIL — `_SIGNALS_CACHE_PATH` and `_CRON_LOG_PATH` don't exist as module-level attributes yet; `MAX_SIGNALS_CACHE_AGE_SECS` is inside `create_app()` scope.

- [ ] **Step 3: Refactor paths and threshold to module level in `web_app.py`**

Near the top of `web_app.py`, after the existing imports, add:

```python
_DATA_DIR = Path(__file__).parent / "data"
_SIGNALS_CACHE_PATH: Path = _DATA_DIR / "signals_cache.json"
_CRON_LOG_PATH: Path = _DATA_DIR / "cron.log"
MAX_SIGNALS_CACHE_AGE_SECS: int = 4 * 60 * 60  # 4 hours — one full cron cycle
```

- [ ] **Step 4: Update `api_live_signals` to use the module-level path**

In `web_app.py`, inside `api_live_signals()`, replace:

```python
        cache_path = pathlib.Path("data/signals_cache.json")
```

with:

```python
        cache_path = _SIGNALS_CACHE_PATH
```

And remove the `import pathlib` line that was only used for this.

Also replace the inline constant:

```python
    MAX_SIGNALS_CACHE_AGE_SECS = 90 * 60  # 90 minutes
```

with nothing — it's now a module-level variable defined in Step 3.

- [ ] **Step 5: Update `api_signals` to use the module-level cron log path**

In `web_app.py`, inside `api_signals()`, replace:

```python
        cron_log = pathlib.Path("data/cron.log")
```

with:

```python
        cron_log = _CRON_LOG_PATH
```

- [ ] **Step 6: Run tests to verify they pass**

```
python -m pytest tests/test_signals_page.py -v
```

Expected: PASS.

- [ ] **Step 7: Run full suite**

```
python -m pytest tests/ -q --tb=short
```

Expected: all prior tests still pass, 3 new tests pass.

- [ ] **Step 8: Commit**

```bash
git add web_app.py tests/test_signals_page.py
git commit -m "fix: signals cache uses absolute path; raise stale threshold to 4h"
```

---

## Self-Review

**Spec coverage:**
- ✅ Signals cache not found → Step 3–4 (`_SIGNALS_CACHE_PATH` absolute)
- ✅ Cron log not found → Step 3–5 (`_CRON_LOG_PATH` absolute)
- ✅ Data disappears after 90 min → Step 3 (threshold raised to 4h)

**Placeholder scan:** None found.

**Type consistency:** `_SIGNALS_CACHE_PATH` and `_CRON_LOG_PATH` are `Path` — matches the `open(cache_path)` calls already in the code.
