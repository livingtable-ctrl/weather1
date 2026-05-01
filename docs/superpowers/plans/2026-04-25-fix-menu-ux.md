# Menu UX Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three interactive-menu UX bugs: cron shows no live output when run from the menu; analyze and cron cannot be cancelled mid-run without killing the whole program; brief cannot be closed once started from the menu.

**Architecture:** All three bugs live in `cmd_menu` in `main.py`. Cron and analyze are called synchronously — wrapping them with `KeyboardInterrupt` handling restores Ctrl-C cancellation and also fixes the "feels stuck" experience. Brief already returns but needs a `input()` confirmation only added when it finishes, not when it starts a blocking wait inside. The cron-output issue is a Windows terminal flush problem — adding `sys.stdout.flush()` before the call and printing a visual separator after cures it.

**Tech Stack:** Python, `main.py`, `tests/test_menu_ux.py` (new file)

---

## Root Cause Summary

| Bug | File | Location | Cause |
|---|---|---|---|
| Cron no live output | `main.py` | ~line 5064 | No `sys.stdout.flush()` before call; Windows buffers output until function returns |
| Can't cancel cron/analyze | `main.py` | ~lines 5056, 5064 | `KeyboardInterrupt` propagates to the outer `while True` loop and kills the menu instead of just the command |
| Brief can't be closed | `main.py` | ~line 5270 | `cmd_brief` ends normally but the shared `input("\n  Press Enter...")` at line 5281 is inside the menu loop — if brief itself raises or hangs, that prompt is never reached |

---

## Task 1: Flush stdout before cron so live output appears immediately

**Files:**
- Modify: `main.py` ~line 5062–5075 (the `elif name_stripped == "Loop":` block)
- Test: `tests/test_menu_ux.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_menu_ux.py`:

```python
"""Tests for menu UX fixes."""
import sys
from unittest.mock import MagicMock, call, patch


class TestCronOutputFlush:
    def test_stdout_flushed_before_cmd_cron(self, monkeypatch):
        """sys.stdout.flush() must be called before cmd_cron in the menu loop."""
        import main

        flush_calls = []
        cron_calls = []

        def fake_flush():
            flush_calls.append(len(cron_calls))  # record flush happened before cron

        def fake_cron(client):
            cron_calls.append(True)

        monkeypatch.setattr(sys.stdout, "flush", fake_flush)
        monkeypatch.setattr(main, "cmd_cron", fake_cron)

        # Simulate menu choosing option "Loop"
        fake_client = MagicMock()
        with patch("builtins.input", side_effect=["3", "q"]):  # 3=Cron, q=quit
            try:
                main.cmd_menu(fake_client)
            except (SystemExit, StopIteration):
                pass

        assert flush_calls, "sys.stdout.flush() was never called"
        assert 0 in flush_calls, "flush must be called BEFORE cmd_cron, not after"
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_menu_ux.py::TestCronOutputFlush -v
```

Expected: FAIL.

- [ ] **Step 3: Add flush to the Loop block**

In `main.py`, find the `elif name_stripped == "Loop":` block (~line 5061) and add `sys.stdout.flush()` before the cron call:

```python
        elif name_stripped == "Loop":
            print(bold("\n  ── Run Cron ──\n"))
            print(dim("  Running a cron cycle now (uses cached data if fresh)…\n"))
            sys.stdout.flush()          # ← ADD THIS
            try:
                cmd_cron._called_from_loop = True  # type: ignore[attr-defined]
                cmd_cron(client)
            except KeyboardInterrupt:   # ← ALSO ADD THIS (Task 2 below)
                print(yellow("\n  Cron cancelled."))
            except Exception as exc:
                print(red(f"  Cron error: {exc}"))
            finally:
                cmd_cron._called_from_loop = False  # type: ignore[attr-defined]
            sys.stdout.flush()          # ← AND THIS (flush after too)
            print(
                dim(
                    "\n  Tip: run  py main.py loop  in a separate terminal to auto-run every 4h."
                )
            )
```

Verify `import sys` is already at the top of `main.py` (it is).

- [ ] **Step 4: Run test to verify it passes**

```
python -m pytest tests/test_menu_ux.py::TestCronOutputFlush -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_menu_ux.py
git commit -m "fix: flush stdout before cron in menu so output appears immediately"
```

---

## Task 2: Allow Ctrl-C to cancel analyze and cron without killing the menu

**Files:**
- Modify: `main.py` ~line 5055 (`elif name_stripped == "Analyze":`)
- Modify: `main.py` ~line 5061 (`elif name_stripped == "Loop":`) — already done in Task 1
- Test: `tests/test_menu_ux.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_menu_ux.py`:

```python
class TestCancelAnalyze:
    def test_keyboard_interrupt_in_analyze_returns_to_menu(self, monkeypatch):
        """KeyboardInterrupt inside cmd_analyze must not kill the menu."""
        import main

        def fake_analyze(client, **kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(main, "cmd_analyze", fake_analyze)

        fake_client = MagicMock()
        menu_returned = False

        # After the interrupted analyze, the menu should loop back (not crash).
        # We simulate: choose Analyze (option 1), then Quit (option 12).
        with patch("builtins.input", side_effect=["1", "12"]):
            try:
                main.cmd_menu(fake_client)
                menu_returned = True
            except KeyboardInterrupt:
                pass  # This would be the bug — interrupt escaped the menu

        assert menu_returned, (
            "KeyboardInterrupt inside cmd_analyze should be caught and return to menu"
        )
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_menu_ux.py::TestCancelAnalyze -v
```

Expected: FAIL — `KeyboardInterrupt` escapes.

- [ ] **Step 3: Wrap `cmd_analyze` call with `KeyboardInterrupt` catch**

In `main.py`, find:
```python
        elif name_stripped == "Analyze":
            cmd_analyze(client)
```

Replace with:
```python
        elif name_stripped == "Analyze":
            try:
                cmd_analyze(client)
            except KeyboardInterrupt:
                print(yellow("\n  Analyze cancelled."))
```

- [ ] **Step 4: Run test to verify it passes**

```
python -m pytest tests/test_menu_ux.py::TestCancelAnalyze -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_menu_ux.py
git commit -m "fix: catch KeyboardInterrupt in analyze/cron so Ctrl-C returns to menu"
```

---

## Task 3: Ensure brief always reaches the "Press Enter" prompt

**Files:**
- Modify: `main.py` ~line 5269 (`elif name_stripped == "Brief":`)
- Test: `tests/test_menu_ux.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_menu_ux.py`:

```python
class TestBriefCloseable:
    def test_brief_exception_still_shows_press_enter(self, monkeypatch, capsys):
        """If cmd_brief raises, the menu must still show the press-Enter prompt."""
        import main

        def fake_brief(client, **kwargs):
            raise RuntimeError("brief error")

        monkeypatch.setattr(main, "cmd_brief", fake_brief)
        fake_client = MagicMock()

        # Choose Brief (option 10 in default menu), then Enter to return, then Quit
        with patch("builtins.input", side_effect=["10", "", "12"]):
            try:
                main.cmd_menu(fake_client)
            except Exception:
                pass

        captured = capsys.readouterr()
        assert "Press Enter" in captured.out, (
            "Menu must always show 'Press Enter to return' even if cmd_brief raises"
        )
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_menu_ux.py::TestBriefCloseable -v
```

Expected: FAIL.

- [ ] **Step 3: Wrap `cmd_brief` in try/except**

In `main.py`, find:
```python
        elif name_stripped == "Brief":
            cmd_brief(client)
```

Replace with:
```python
        elif name_stripped == "Brief":
            try:
                cmd_brief(client)
            except KeyboardInterrupt:
                print(yellow("\n  Brief cancelled."))
            except Exception as _e:
                print(red(f"\n  Brief failed: {_e}"))
```

- [ ] **Step 4: Verify the shared `input(...)` at the end of the loop is reached**

Read `main.py` around line 5280. Confirm the structure is:
```python
        # (all elif branches above)
        input(dim("\n  Press Enter to return to menu..."))
```
This `input` sits OUTSIDE all the `elif` blocks, so as long as the branch doesn't `return` or raise, it is always reached. The fix in Step 3 ensures exceptions don't propagate out of the branch.

- [ ] **Step 5: Run test to verify it passes**

```
python -m pytest tests/test_menu_ux.py::TestBriefCloseable -v
```

Expected: PASS.

- [ ] **Step 6: Run full suite**

```
python -m pytest tests/ -q --tb=short
```

Expected: all prior tests still pass, 3+ new tests pass.

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_menu_ux.py
git commit -m "fix: wrap cmd_brief in try/except so menu always shows press-Enter prompt"
```

---

## Self-Review

**Spec coverage:**
- ✅ Cron no live output → Task 1 (flush before call)
- ✅ Can't cancel analyze/cron → Task 2 (KeyboardInterrupt catch)
- ✅ Brief can't be closed → Task 3 (try/except wrapper)

**Placeholder scan:** None found.

**Type consistency:** No new types introduced.
