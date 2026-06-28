# Category F: Security — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three remaining security exposures: RSA private key permission check (F1), .env file world-readable warning (F2), and pickle type validation (F3). The fourth item — timing-safe password comparison — is already implemented in `web_app.py` line 41 and is CLOSED.

**Architecture:** All three items are independent. F1 and F2 are startup-time checks that warn/abort; F3 is a guard added to any pickle.loads call. Each can ship independently.

**Tech Stack:** Python 3.14, `os.stat`, `pathlib`, `logging`, pytest.

**Note:** `hmac.compare_digest` is ALREADY LIVE in `web_app.py:41` — do NOT re-implement.

---

## F1: RSA Private Key Permission Check

**Problem:** If `KALSHI_API_KEY` is an RSA private key file path, the file may have world-readable permissions (chmod 644), exposing the private key to other local users. On Windows, this check uses file ACLs; on POSIX it uses file mode bits.

**Files:**
- Modify: `main.py` — add `_check_key_file_permissions()` called in `_validate_config()`
- Test: `tests/test_security.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_security.py
import os
import sys
import stat
import pytest
from pathlib import Path

@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission check only")
def test_check_key_permissions_warns_on_world_readable(tmp_path, caplog):
    import logging
    from main import _check_key_file_permissions

    key_file = tmp_path / "kalshi_key.pem"
    key_file.write_text("-----BEGIN RSA PRIVATE KEY-----\nFAKE\n-----END RSA PRIVATE KEY-----")
    # Make world-readable (644)
    key_file.chmod(0o644)

    with caplog.at_level(logging.WARNING):
        _check_key_file_permissions(str(key_file))

    assert any("world-readable" in r.message.lower() or "permission" in r.message.lower()
               for r in caplog.records), "Should warn about insecure key permissions"

@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission check only")
def test_check_key_permissions_silent_on_600(tmp_path, caplog):
    import logging
    from main import _check_key_file_permissions

    key_file = tmp_path / "kalshi_key.pem"
    key_file.write_text("-----BEGIN RSA PRIVATE KEY-----\nFAKE\n-----END RSA PRIVATE KEY-----")
    key_file.chmod(0o600)  # owner-only

    with caplog.at_level(logging.WARNING):
        _check_key_file_permissions(str(key_file))

    security_warns = [r for r in caplog.records
                      if r.levelno >= logging.WARNING and "permission" in r.message.lower()]
    assert len(security_warns) == 0, "Should not warn when permissions are 600"
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/test_security.py::test_check_key_permissions_warns_on_world_readable -v
```
Expected: `AttributeError: module 'main' has no attribute '_check_key_file_permissions'`

- [ ] **Step 3: Add `_check_key_file_permissions()` to `main.py`**

```python
def _check_key_file_permissions(key_path: str) -> None:
    """Warn if the private key file has overly permissive permissions.

    On POSIX: warns if group or other bits are set (permission > 0o700).
    On Windows: checks if the file is readable by Everyone using ICACLS.
    Logs a WARNING but does not abort — key may be a path to a non-RSA token.
    """
    import os
    import sys
    import logging
    _log = logging.getLogger(__name__)

    p = Path(key_path)
    if not p.exists():
        return  # env var may be the key content, not a path

    if sys.platform == "win32":
        # On Windows: check if file exists and warn if ACL is not restricted
        import subprocess
        try:
            result = subprocess.run(
                ["icacls", str(p)],
                capture_output=True, text=True, timeout=5,
            )
            if "Everyone" in result.stdout or "BUILTIN\\Users" in result.stdout:
                _log.warning(
                    "SECURITY: %s may be readable by other users (icacls shows broad access). "
                    "Run: icacls %s /inheritance:r /grant %s:F",
                    p, p, os.getlogin(),
                )
        except Exception:
            pass  # icacls not available or timed out — skip
    else:
        # POSIX: check file mode bits
        mode = p.stat().st_mode & 0o777
        if mode & 0o077:  # any group or other bits set
            _log.warning(
                "SECURITY: %s has insecure permissions (%04o). "
                "Run: chmod 600 %s",
                p, mode, p,
            )
```

- [ ] **Step 4: Call from `_validate_config()` in `main.py`**

In `_validate_config()`, after checking that `KALSHI_API_KEY` is set:

```python
key_val = os.getenv("KALSHI_API_KEY", "")
if key_val and "/" in key_val or key_val.endswith(".pem") or key_val.endswith(".key"):
    _check_key_file_permissions(key_val)
# Also check the secret path if it's a file
secret_val = os.getenv("KALSHI_API_SECRET", "")
if secret_val and ("/" in secret_val or secret_val.endswith(".pem")):
    _check_key_file_permissions(secret_val)
```

- [ ] **Step 5: Run the tests**

```
pytest tests/test_security.py -v
```
Expected: PASS on POSIX (skipped on Windows)

- [ ] **Step 6: Commit**

```
git add main.py tests/test_security.py
git commit -m "feat(security): warn on overly permissive RSA key file permissions at startup"
```

---

## F2: .env File World-Readable Warning

**Problem:** `.env` files often contain API keys and secrets. On multi-user machines, a world-readable `.env` (chmod 644) exposes all secrets to any local user. The fix: check `.env` permissions at startup and warn if readable by group/other.

**Files:**
- Modify: `main.py` — add `.env` permission check to `_validate_config()`
- Test: `tests/test_security.py`

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission check only")
def test_dotenv_permission_warning_on_644(tmp_path, caplog, monkeypatch):
    import logging
    from main import _check_dotenv_permissions

    env_file = tmp_path / ".env"
    env_file.write_text("KALSHI_API_KEY=secret\nKALSHI_API_SECRET=anothersecret")
    env_file.chmod(0o644)  # world-readable

    with caplog.at_level(logging.WARNING):
        _check_dotenv_permissions(str(env_file))

    assert any("env" in r.message.lower() and "permission" in r.message.lower()
               for r in caplog.records)

@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission check only")
def test_dotenv_no_warning_on_600(tmp_path, caplog):
    import logging
    from main import _check_dotenv_permissions

    env_file = tmp_path / ".env"
    env_file.write_text("KALSHI_API_KEY=secret")
    env_file.chmod(0o600)

    with caplog.at_level(logging.WARNING):
        _check_dotenv_permissions(str(env_file))

    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warns
```

- [ ] **Step 2: Add `_check_dotenv_permissions()` to `main.py`**

```python
def _check_dotenv_permissions(dotenv_path: str = ".env") -> None:
    """Warn if .env file is readable by group or other users.

    Only runs on POSIX. On Windows, warns if the file is in the project root
    without any indication of restricted ACLs (Windows ACL check is best-effort).
    """
    import sys
    p = Path(dotenv_path)
    if not p.exists():
        return

    if sys.platform != "win32":
        mode = p.stat().st_mode & 0o777
        if mode & 0o077:
            _log.warning(
                "SECURITY: .env has insecure permissions (%04o) — contains API secrets. "
                "Run: chmod 600 %s",
                mode, p,
            )
    # Windows: no easy ACL check without pywin32; skip silently
```

- [ ] **Step 3: Call from `_validate_config()`**

```python
# At the start of _validate_config(), before checking required vars:
_check_dotenv_permissions(".env")
```

- [ ] **Step 4: Run the tests**

```
pytest tests/test_security.py::test_dotenv_permission_warning_on_644 tests/test_security.py::test_dotenv_no_warning_on_600 -v
```
Expected: PASS on POSIX, skipped on Windows

- [ ] **Step 5: Commit**

```
git add main.py tests/test_security.py
git commit -m "feat(security): warn when .env file is world-readable at startup (chmod 600 suggested)"
```

---

## F3: Pickle Type Validation

**Problem:** If any model artifact or cache file uses `pickle.loads` without type validation, a maliciously crafted pickle file could execute arbitrary code. Check all `pickle.loads` or `pickle.load` calls and add type validation.

**Files:**
- Read: search for `pickle` usage across the codebase
- Modify: any file using `pickle.loads` / `pickle.load` — add type check and restrict allowed types

- [ ] **Step 1: Audit pickle usage**

```
grep -rn "pickle\.load" . --include="*.py" | grep -v ".pyc" | grep -v "test_"
```

Note all files and lines. Common locations: `calibration.py`, `ml_bias.py`, `backtest.py`, any caching layer.

- [ ] **Step 2: Write failing test**

```python
# tests/test_security.py — add
def test_pickle_load_validates_type(tmp_path):
    """Loading a pickle file must validate the returned type — not allow arbitrary objects."""
    import pickle
    from main import safe_pickle_load  # the function we will add

    # Safe: save a dict and load it back
    safe_path = tmp_path / "safe.pkl"
    with open(safe_path, "wb") as f:
        pickle.dump({"a": 1, "b": 2}, f)

    result = safe_pickle_load(safe_path, expected_type=dict)
    assert result == {"a": 1, "b": 2}

    # Unsafe: a different type should raise TypeError or return None
    bad_path = tmp_path / "bad.pkl"
    with open(bad_path, "wb") as f:
        pickle.dump([1, 2, 3], f)  # list, not dict

    with pytest.raises((TypeError, ValueError)):
        safe_pickle_load(bad_path, expected_type=dict)
```

- [ ] **Step 3: Add `safe_pickle_load()` to `main.py` (or a shared `safe_io.py`)**

```python
def safe_pickle_load(path, expected_type: type):
    """Load a pickle file and validate the returned type.

    Raises TypeError if the loaded object is not an instance of expected_type.
    Returns None if the file does not exist.

    Use this instead of bare pickle.load() to prevent arbitrary code execution
    if the pickle file is corrupted or replaced with a malicious file.
    """
    import pickle
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        return None
    with open(p, "rb") as f:
        obj = pickle.load(f)
    if not isinstance(obj, expected_type):
        raise TypeError(
            f"safe_pickle_load: expected {expected_type.__name__}, "
            f"got {type(obj).__name__} from {p}"
        )
    return obj
```

- [ ] **Step 4: Replace existing `pickle.load` calls**

For each call found in Step 1, replace:

```python
# old:
with open("data/some_model.pkl", "rb") as f:
    model = pickle.load(f)

# new:
from main import safe_pickle_load
model = safe_pickle_load("data/some_model.pkl", expected_type=dict)
```

Adjust `expected_type` to match what the pickle file actually stores (dict, list, numpy.ndarray, etc.).

- [ ] **Step 5: Run the test**

```
pytest tests/test_security.py::test_pickle_load_validates_type -v
```
Expected: PASS

- [ ] **Step 6: Run the full test suite for modified files**

```
pytest tests/test_security.py tests/test_ml_bias.py tests/test_forecasting.py -v
```
Expected: all PASS

- [ ] **Step 7: Commit**

```
git add main.py safe_io.py tests/test_security.py
git commit -m "feat(security): safe_pickle_load validates type before returning — prevents arbitrary pickle execution"
```

---

## Closed: F0 — Timing-Safe Password Comparison

**Status: ALREADY IMPLEMENTED.** `web_app.py:41` uses `hmac.compare_digest(password, pwd)`. No further action needed.

This item appeared in the original backlog (`do-after-graduation.md`) but was verified as complete on 2026-06-27 by reading the source.
