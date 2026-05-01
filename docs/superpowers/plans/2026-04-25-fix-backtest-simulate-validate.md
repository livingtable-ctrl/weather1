# Fix Backtest / Simulate / Validate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore `backtest`, `simulate`, and `validate` (walk-forward) commands so they fetch real settled Kalshi weather markets and produce accurate results.

**Architecture:** Three independent fixes share a common root cause — stale or wrong API status params and no pagination. Fix 1 is a one-liner in `main.py`. Fix 2 is the core engine change in `backtest.py`: add cursor-based pagination and a helper that surfaces API errors. Fix 3 wraps `cmd_backtest` and `cmd_walkforward` in proper error handling so failures are shown, not swallowed.

**Tech Stack:** Python, `requests` (via `kalshi_client.py`), `backtest.py`, `main.py`, `tests/test_backtest.py`

---

## Root Cause Summary

| Command | File | Bug | Effect |
|---|---|---|---|
| `simulate` | `main.py:6025` | `status="finalized"` (invalid) | 400 Bad Request every time |
| `backtest` | `backtest.py:264` | `status="settled"`, `limit=200`, no pagination, no error handling | Returns ≤200 total markets (mostly non-weather), crashes silently on any API error |
| `validate` (walkforward) | `backtest.py:535` | Calls `run_backtest` which has the same pagination bug | Inherits all backtest bugs |

---

## Task 1: Fix `cmd_simulate` — wrong status param

**Files:**
- Modify: `main.py:6025`
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_backtest.py`, add a test class at the bottom:

```python
class TestCmdSimulateStatusParam:
    def test_simulate_calls_get_markets_with_settled_not_finalized(self, monkeypatch):
        """cmd_simulate must use status='settled', not 'finalized'."""
        import main
        from unittest.mock import MagicMock, patch

        fake_client = MagicMock()
        fake_client.get_markets.return_value = []  # empty → "no markets" exit

        with patch("main.build_client", return_value=fake_client):
            try:
                main.cmd_simulate(fake_client)
            except SystemExit:
                pass

        call_kwargs = fake_client.get_markets.call_args
        assert call_kwargs is not None, "get_markets was never called"
        status_used = call_kwargs.kwargs.get("status") or call_kwargs.args[0] if call_kwargs.args else None
        # Accept keyword or positional
        all_kwargs = {**dict(enumerate(call_kwargs.args)), **call_kwargs.kwargs}
        assert "settled" in str(all_kwargs), (
            f"Expected status='settled', got: {all_kwargs}"
        )
        assert "finalized" not in str(all_kwargs), (
            "status='finalized' is rejected by the Kalshi API with a 400"
        )
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_backtest.py::TestCmdSimulateStatusParam -v
```

Expected: FAIL — `status='finalized'` found in call kwargs.

- [ ] **Step 3: Apply the one-line fix**

In `main.py` line 6025, change:
```python
        markets = client.get_markets(status="finalized", limit=50)
```
to:
```python
        markets = client.get_markets(status="settled", limit=50)
```

- [ ] **Step 4: Run test to verify it passes**

```
python -m pytest tests/test_backtest.py::TestCmdSimulateStatusParam -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_backtest.py
git commit -m "fix: cmd_simulate status param finalized→settled"
```

---

## Task 2: Add cursor pagination + error surfacing to `run_backtest`

**Files:**
- Modify: `backtest.py:230–265` (the `run_backtest` function opening)
- Modify: `backtest.py` — add `_fetch_settled_markets(client, max_pages)` helper above `run_backtest`
- Test: `tests/test_backtest.py`

**Background:** The Kalshi `/markets` API returns at most 200 markets per page. It includes a `cursor` field in the response JSON for fetching the next page. Without pagination we may get 200 non-weather markets and 0 results. We also need to surface 400 errors instead of crashing.

- [ ] **Step 1: Write two failing tests**

In `tests/test_backtest.py`, add:

```python
class TestFetchSettledMarkets:
    def test_pagination_follows_cursor(self, monkeypatch):
        """_fetch_settled_markets must follow the cursor until exhausted."""
        from unittest.mock import MagicMock, patch
        import backtest

        fake_client = MagicMock()
        page1 = {"markets": [{"ticker": "T1"}], "cursor": "abc123"}
        page2 = {"markets": [{"ticker": "T2"}], "cursor": None}
        fake_client._get.side_effect = [page1, page2]

        result = backtest._fetch_settled_markets(fake_client, max_pages=5)

        assert len(result) == 2
        assert fake_client._get.call_count == 2
        # Second call must pass the cursor
        second_call_params = fake_client._get.call_args_list[1][1]["params"]
        assert second_call_params.get("cursor") == "abc123"

    def test_api_error_raises_with_clear_message(self, monkeypatch):
        """_fetch_settled_markets must raise RuntimeError with a readable message on 400."""
        import requests
        import backtest
        from unittest.mock import MagicMock

        fake_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 400
        resp.text = "Bad Request"
        fake_client._get.side_effect = requests.HTTPError(response=resp)

        import pytest
        with pytest.raises((requests.HTTPError, RuntimeError)):
            backtest._fetch_settled_markets(fake_client, max_pages=5)
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_backtest.py::TestFetchSettledMarkets -v
```

Expected: FAIL — `_fetch_settled_markets` does not exist yet.

- [ ] **Step 3: Add `_fetch_settled_markets` helper to `backtest.py`**

Insert this function immediately above `def run_backtest(` (around line 230):

```python
def _fetch_settled_markets(client, max_pages: int = 20) -> list[dict]:
    """
    Fetch all settled Kalshi markets using cursor-based pagination.
    Returns a flat list across all pages.
    Raises the original HTTPError on API failure so callers can surface it.
    """
    markets: list[dict] = []
    cursor: str | None = None

    for _ in range(max_pages):
        params: dict = {"status": "settled", "limit": 200}
        if cursor:
            params["cursor"] = cursor

        data = client._get("/markets", params=params, auth=True)
        page = data.get("markets", [])
        markets.extend(page)

        cursor = data.get("cursor") or data.get("next_cursor")
        if not cursor or not page:
            break

    return markets
```

- [ ] **Step 4: Replace the single `get_markets` call in `run_backtest`**

In `backtest.py`, find line 264:
```python
    markets = client.get_markets(status="settled", limit=200)
```
Replace with:
```python
    markets = _fetch_settled_markets(client, max_pages=20)
```

- [ ] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/test_backtest.py::TestFetchSettledMarkets -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backtest.py tests/test_backtest.py
git commit -m "fix: paginate settled market fetch in run_backtest (L→no limit)"
```

---

## Task 3: Add error handling to `cmd_backtest` and `cmd_walkforward`

**Files:**
- Modify: `main.py:5320` (the `run_backtest(...)` call inside `cmd_backtest`)
- Modify: `main.py:4553` (the `run_walk_forward(...)` call — already has try/except, but verify it catches `HTTPError`)
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write the failing test**

```python
class TestCmdBacktestErrorHandling:
    def test_api_error_prints_message_not_traceback(self, monkeypatch, capsys):
        """cmd_backtest must catch API errors and print a readable message."""
        import requests
        import main
        from unittest.mock import MagicMock, patch

        fake_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 400
        http_err = requests.HTTPError("400 Bad Request", response=resp)

        with patch("main.run_backtest", side_effect=http_err):
            main.cmd_backtest(fake_client, [])

        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert "400" in output or "Bad Request" in output or "error" in output.lower(), (
            "Expected a readable error message, got nothing"
        )
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_backtest.py::TestCmdBacktestErrorHandling -v
```

Expected: FAIL — unhandled `HTTPError` propagates instead of printing.

- [ ] **Step 3: Wrap `run_backtest` call in `cmd_backtest`**

In `main.py`, find the call at line ~5320:
```python
    summary = run_backtest(
        client,
        city_filter=city_filter,
        days_back=days_back,
        on_progress=_bt_progress,
    )
```
Wrap it:
```python
    try:
        summary = run_backtest(
            client,
            city_filter=city_filter,
            days_back=days_back,
            on_progress=_bt_progress,
        )
    except Exception as e:
        print()  # newline after progress bar
        print(red(f"  Backtest failed: {e}"))
        print(dim("  Tip: check your API credentials and try again."))
        return
```

- [ ] **Step 4: Verify `cmd_walkforward` already catches exceptions**

Read `main.py` around line 4553. It already has:
```python
    try:
        result = run_walk_forward(client)
    except Exception as e:
        print(red(f"  Walk-forward test failed: {e}"))
        return
```
If present, no change needed. If missing, add the same pattern.

- [ ] **Step 5: Run test to verify it passes**

```
python -m pytest tests/test_backtest.py::TestCmdBacktestErrorHandling -v
```

Expected: PASS.

- [ ] **Step 6: Run full suite**

```
python -m pytest tests/ -q --tb=short
```

Expected: all prior tests still pass, 3 new tests added.

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_backtest.py
git commit -m "fix: catch API errors in cmd_backtest; surface readable message"
```

---

## Self-Review

**Spec coverage:**
- ✅ backtest broken → Task 2 (pagination) + Task 3 (error handling)
- ✅ simulate 400 error → Task 1 (status param)
- ✅ validate broken → inherits backtest fix from Task 2; error handling verified in Task 3 Step 4

**Placeholder scan:** None found.

**Type consistency:** `_fetch_settled_markets` returns `list[dict]` — matches what `run_backtest` iterates over.
