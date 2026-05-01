# Fix Browse Cities — Derive from CITY_COORDS

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the hardcoded 10-city `_BROWSE_CITIES` list in `main.py` and replace it with a live derivation from `CITY_COORDS.keys()` so the browse menu always reflects every city the system knows about (currently 18).

**Architecture:** `CITY_COORDS` is defined in `weather_markets.py` and loaded from `data/cities.json` at import time. `_BROWSE_CITIES` in `main.py` is a static list written alongside the `CITY_COORDS` definition but never updated when new cities are added. The one-line fix replaces the list with `sorted(CITY_COORDS.keys())`. The user-prompt text "1–10" also needs updating to reflect the variable count. The `cmd_browse` function already uses `len(_BROWSE_CITIES)` for bounds-checking, so no other changes are needed.

**Tech Stack:** Python, `main.py`, `tests/test_browse_cities.py` (new file)

---

## Root Cause Summary

| Bug | File | Location | Cause |
|---|---|---|---|
| Browse only shows 10 cities | `main.py` | Line 4075 | `_BROWSE_CITIES` is a hardcoded list; `CITY_COORDS` has 18 cities but `_BROWSE_CITIES` was never updated |

---

## Task 1: Derive `_BROWSE_CITIES` from `CITY_COORDS`

**Files:**
- Modify: `main.py` ~lines 4075–4097
- Test: `tests/test_browse_cities.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_browse_cities.py`:

```python
"""Tests for browse cities derivation fix."""
from unittest.mock import MagicMock, patch


class TestBrowseCitiesMatchesCityCoords:
    def test_browse_cities_includes_all_city_coords(self):
        """_BROWSE_CITIES must be a superset of CITY_COORDS keys."""
        import main
        from weather_markets import CITY_COORDS

        missing = set(CITY_COORDS.keys()) - set(main._BROWSE_CITIES)
        assert not missing, (
            f"Cities in CITY_COORDS but missing from _BROWSE_CITIES: {missing}"
        )

    def test_browse_cities_is_sorted(self):
        """_BROWSE_CITIES must be sorted alphabetically for consistent menus."""
        import main

        assert list(main._BROWSE_CITIES) == sorted(main._BROWSE_CITIES), (
            "_BROWSE_CITIES should be sorted so menu order is deterministic"
        )

    def test_browse_cities_has_no_duplicates(self):
        """_BROWSE_CITIES must not contain duplicate entries."""
        import main

        assert len(main._BROWSE_CITIES) == len(set(main._BROWSE_CITIES)), (
            "_BROWSE_CITIES contains duplicates"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_browse_cities.py -v
```

Expected: FAIL — `_BROWSE_CITIES` only has 10 cities but `CITY_COORDS` has 18.

- [ ] **Step 3: Replace the hardcoded list**

In `main.py`, find lines 4075–4086:
```python
_BROWSE_CITIES = [
    "NYC",
    "Chicago",
    "LA",
    "Boston",
    "Miami",
    "Dallas",
    "Phoenix",
    "Seattle",
    "Denver",
    "Atlanta",
]
```

Replace with:
```python
# Derived from CITY_COORDS so new cities added to data/cities.json
# automatically appear in the browse menu without code changes.
from weather_markets import CITY_COORDS as _CITY_COORDS  # noqa: E402
_BROWSE_CITIES = sorted(_CITY_COORDS.keys())
```

> **Note:** `weather_markets` is already imported elsewhere in `main.py` (search for `from weather_markets import`). If a bare `from weather_markets import CITY_COORDS` already exists at the top, use that name directly instead of the aliased import shown above.

- [ ] **Step 4: Update the prompt text that hardcodes "1–10"**

In `main.py` around line 4097, find:
```python
    raw = input(dim("  Pick a city (1–10, or Enter for all): ")).strip()
```

Replace with:
```python
    raw = input(dim(f"  Pick a city (1–{len(_BROWSE_CITIES)}, or Enter for all): ")).strip()
```

- [ ] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/test_browse_cities.py -v
```

Expected: PASS — 3 tests green.

- [ ] **Step 6: Run full suite**

```
python -m pytest tests/ -q --tb=short
```

Expected: all prior tests still pass, 3 new tests pass.

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_browse_cities.py
git commit -m "fix: derive _BROWSE_CITIES from CITY_COORDS so all 18 cities appear in browse menu"
```

---

## Self-Review

**Spec coverage:**
- ✅ Missing cities in browse — Task 1 (derive from CITY_COORDS)

**Placeholder scan:** None found.

**Type consistency:** `sorted(CITY_COORDS.keys())` returns `list[str]` — same type as the previous hardcoded list.
