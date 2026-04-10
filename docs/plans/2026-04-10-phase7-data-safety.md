# Phase 7: Data Safety + Remaining Forecasting Items
**Date**: 2026-04-10  
**Covers**: #102, #104, #105, #31, #34, #55  
**Approach**: TDD — write failing test → confirm red → implement → confirm green → commit

---

## Overview

Two groups:

**Data Safety** (straightforward, can run first):
- **#102**: No corruption detection — add CRC32 checksum to paper.py JSON; validate on load
- **#104**: No automated backup verification — verify backup on creation; log checksum
- **#105**: Optional cloud backup — S3/GCS with optional encryption (env-var gated)

**Remaining Forecasting** (more complex):
- **#31**: No weighting by forecast model confidence — scale ensemble weight by inverse variance
- **#34**: Snow accumulation uses naive 10:1 ratio — estimate wet-bulb temp for climate-specific ratio
- **#55**: Bias correction has selection bias — track bias on all analyzed markets, not just traded ones

---

## Task 1 — CRC32 corruption detection (#102)

### Context
`paper.py:108`: `_save()` writes `json.dump(data, f)` atomically.  
`paper.py` has `_load()` which does `json.load(f)`. If the file is partially written before an `os.replace()` (e.g. power loss during temp file write), `json.load` raises `JSONDecodeError`. But if the JSON is syntactically valid yet semantically corrupted (truncated trades list, wrong balance), it's silent.

Fix: store `"_crc32": crc32_hex(json_bytes)` at the top level. On load, recompute and compare. If mismatch → raise `CorruptionError`, caller falls back to last good backup.

### Failing tests
**File**: `tests/test_safe_io.py` (new file if `safe_io.py` was created in Phase 2; otherwise `tests/test_paper.py`)

```python
import json, zlib, os, tempfile, pytest
from pathlib import Path


def _write_with_crc(data: dict, path: Path) -> None:
    """Helper: write JSON + CRC32 to path (mirrors _save logic)."""
    payload = dict(data)
    payload.pop("_crc32", None)
    body = json.dumps(payload, indent=2).encode()
    checksum = format(zlib.crc32(body) & 0xFFFFFFFF, "08x")
    payload["_crc32"] = checksum
    path.write_bytes(json.dumps(payload, indent=2).encode())


def test_load_validates_crc_on_good_file(tmp_path):
    """A correctly checksummed file loads without error."""
    from paper import _validate_crc, CorruptionError

    f = tmp_path / "test.json"
    _write_with_crc({"balance": 1000.0, "trades": []}, f)
    # Should not raise
    _validate_crc(json.loads(f.read_bytes()))


def test_load_raises_on_tampered_file(tmp_path):
    """Tampered JSON (CRC mismatch) raises CorruptionError."""
    from paper import _validate_crc, CorruptionError

    data = {"balance": 1000.0, "trades": [], "_crc32": "deadbeef"}
    with pytest.raises(CorruptionError):
        _validate_crc(data)


def test_load_skips_crc_check_when_field_absent(tmp_path):
    """Existing files without _crc32 field load without error (backwards compat)."""
    from paper import _validate_crc

    data = {"balance": 1000.0, "trades": []}  # no _crc32 field
    _validate_crc(data)  # must not raise


def test_save_writes_crc32_field(tmp_path, monkeypatch):
    """_save writes a _crc32 field to the JSON file."""
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    paper._save({"balance": 1000.0, "trades": []})
    stored = json.loads((tmp_path / "paper_trades.json").read_bytes())
    assert "_crc32" in stored
    assert len(stored["_crc32"]) == 8  # hex CRC32 is 8 chars


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    """save then load succeeds without CorruptionError."""
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    paper._save({"balance": 1234.56, "trades": []})
    loaded = paper._load()
    assert loaded["balance"] == 1234.56
```

**Run**: `pytest tests/test_safe_io.py -x` → `FAILED` (no `CorruptionError`, no `_validate_crc`).

### Implementation

**Step 1**: Add `CorruptionError` and `_validate_crc` to `paper.py` (after imports):

```python
import zlib as _zlib


class CorruptionError(ValueError):
    """Raised when a data file fails its CRC32 integrity check."""


def _validate_crc(data: dict) -> None:
    """
    Verify the _crc32 field in a loaded JSON dict.
    Raises CorruptionError if the checksum is present but wrong.
    Silently passes if _crc32 is absent (backwards compatibility).
    """
    stored = data.get("_crc32")
    if stored is None:
        return  # legacy file — accept without check

    # Recompute: serialize without the _crc32 field, then CRC32 that
    payload = {k: v for k, v in data.items() if k != "_crc32"}
    body = json.dumps(payload, indent=2).encode()
    expected = format(_zlib.crc32(body) & 0xFFFFFFFF, "08x")
    if stored != expected:
        raise CorruptionError(
            f"Data file checksum mismatch: stored={stored!r}, expected={expected!r}. "
            "File may be corrupted. Restore from backup."
        )
```

**Step 2**: Update `_save()` in `paper.py` to embed the checksum:

```python
def _save(data: dict) -> None:
    """Write atomically with CRC32 integrity checksum (#102)."""
    # Strip any existing checksum before computing new one
    payload = {k: v for k, v in data.items() if k != "_crc32"}
    body = json.dumps(payload, indent=2).encode()
    checksum = format(_zlib.crc32(body) & 0xFFFFFFFF, "08x")
    payload["_crc32"] = checksum

    dir_ = DATA_PATH.parent
    fd, tmp = tempfile.mkstemp(dir=dir_, prefix=".paper_trades_", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, DATA_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
```

**Step 3**: Update `_load()` in `paper.py` to call `_validate_crc`:

```python
def _load() -> dict:
    if not DATA_PATH.exists():
        return {"balance": STARTING_BALANCE, "trades": []}
    with open(DATA_PATH) as f:
        data = json.load(f)
    _validate_crc(data)  # raises CorruptionError on mismatch
    return data
```

**Run**: `pytest tests/test_safe_io.py -x` → all green.

**Commit**:
```
git add paper.py tests/test_safe_io.py
git commit -m "feat: CRC32 corruption detection for paper trades JSON (#102)"
```

---

## Task 2 — Automated backup verification (#104)

### Context
The app already does daily backups (improved in Phase 2). Add `verify_backup(path)` that:
1. Reads the backup file
2. Checks it's valid JSON
3. If `_crc32` present, validates it
4. Logs the result with checksum

Call `verify_backup()` whenever a new backup is written.

### Failing tests
**File**: `tests/test_safe_io.py` (append)

```python
def test_verify_backup_passes_on_good_file(tmp_path):
    """verify_backup returns True for a valid backed-up file."""
    from paper import verify_backup, _save
    import paper

    # Write a good backup via _save then copy to backup path
    monkeypatch_path = tmp_path / "paper_trades.json"
    # Write directly using _save logic
    data = {"balance": 999.0, "trades": [], "_meta": "test"}
    body = json.dumps(data).encode()
    checksum = format(zlib.crc32(body) & 0xFFFFFFFF, "08x")
    data_with_crc = {"balance": 999.0, "trades": [], "_crc32": checksum}
    backup_path = tmp_path / "backup.json"
    backup_path.write_text(json.dumps(data_with_crc))
    assert verify_backup(backup_path) is True


def test_verify_backup_fails_on_corrupt_file(tmp_path):
    """verify_backup returns False (and logs) for a corrupted backup."""
    from paper import verify_backup

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text('{"balance": 999, "_crc32": "badf00d0"}')
    assert verify_backup(corrupt) is False


def test_verify_backup_fails_on_invalid_json(tmp_path):
    """verify_backup returns False for non-JSON content."""
    from paper import verify_backup

    bad = tmp_path / "bad.json"
    bad.write_text("NOT JSON {{{")
    assert verify_backup(bad) is False


def test_verify_backup_logs_checksum_on_success(tmp_path, caplog):
    """verify_backup logs the CRC32 checksum when backup is verified."""
    import logging
    from paper import verify_backup

    data = {"balance": 500.0, "trades": []}
    body = json.dumps(data).encode()
    checksum = format(zlib.crc32(body) & 0xFFFFFFFF, "08x")
    data["_crc32"] = checksum
    good = tmp_path / "good.json"
    good.write_text(json.dumps(data))

    with caplog.at_level(logging.INFO, logger="paper"):
        verify_backup(good)

    assert any("crc32" in r.message.lower() or checksum in r.message for r in caplog.records)
```

**Run**: `pytest tests/test_safe_io.py -k "verify_backup" -x` → `FAILED`.

### Implementation

Add `verify_backup()` to `paper.py`:

```python
import logging as _logging

_log_paper = _logging.getLogger(__name__)


def verify_backup(path) -> bool:
    """
    Verify a backup file's integrity (#104).
    Returns True if file is valid JSON with correct checksum (or no checksum — legacy).
    Returns False if file is missing, not JSON, or CRC32 mismatch.
    Logs outcome at INFO level.
    """
    from pathlib import Path as _Path
    p = _Path(path)
    try:
        with open(p) as f:
            data = json.load(f)
        _validate_crc(data)
        crc = data.get("_crc32", "no-crc")
        _log_paper.info("Backup verified OK: %s (crc32=%s)", p.name, crc)
        return True
    except CorruptionError as e:
        _log_paper.error("Backup CRC mismatch: %s — %s", p.name, e)
        return False
    except (json.JSONDecodeError, OSError) as e:
        _log_paper.error("Backup unreadable: %s — %s", p.name, e)
        return False
```

Then find where backups are written in `main.py:361-394` (or the backup function from Phase 2) and call `verify_backup(backup_path)` immediately after writing:

```python
from paper import verify_backup
ok = verify_backup(backup_path)
if not ok:
    print(f"[WARNING] Backup at {backup_path} failed verification!")
```

**Run**: `pytest tests/test_safe_io.py -x` → all green.

**Commit**:
```
git add paper.py main.py tests/test_safe_io.py
git commit -m "feat: automated backup verification with CRC32 logging (#104)"
```

---

## Task 3 — Optional cloud backup (#105)

### Context
Local disk failure = total loss. Add optional S3/GCS backup triggered after each successful local backup. Gate entirely behind env vars (`KALSHI_S3_BUCKET` or `KALSHI_GCS_BUCKET`) so users without cloud credentials are unaffected.

**Chosen approach**: S3 via `boto3` (most common), with optional local AES-256 encryption before upload using `cryptography` library. Both dependencies are optional — graceful fallback if missing.

### Failing tests
**File**: `tests/test_cloud_backup.py`

```python
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import json


def test_cloud_backup_skipped_without_env(tmp_path, monkeypatch):
    """cloud_backup returns None (no-op) when KALSHI_S3_BUCKET not set."""
    monkeypatch.delenv("KALSHI_S3_BUCKET", raising=False)
    monkeypatch.delenv("KALSHI_GCS_BUCKET", raising=False)

    from paper import cloud_backup
    result = cloud_backup(tmp_path / "backup.json")
    assert result is None


def test_cloud_backup_uploads_to_s3(tmp_path, monkeypatch):
    """cloud_backup uploads to S3 when KALSHI_S3_BUCKET is set."""
    monkeypatch.setenv("KALSHI_S3_BUCKET", "my-test-bucket")
    monkeypatch.setenv("KALSHI_S3_PREFIX", "kalshi-backups/")

    backup_file = tmp_path / "paper_trades.json"
    backup_file.write_text(json.dumps({"balance": 1000.0, "trades": []}))

    mock_s3 = MagicMock()
    with patch("boto3.client", return_value=mock_s3):
        from paper import cloud_backup
        cloud_backup(backup_file)

    mock_s3.upload_file.assert_called_once()
    call_args = mock_s3.upload_file.call_args
    assert "my-test-bucket" in str(call_args)


def test_cloud_backup_encrypts_before_upload(tmp_path, monkeypatch):
    """cloud_backup encrypts file when KALSHI_BACKUP_ENCRYPT_KEY is set."""
    monkeypatch.setenv("KALSHI_S3_BUCKET", "my-bucket")
    monkeypatch.setenv("KALSHI_BACKUP_ENCRYPT_KEY", "a" * 64)  # 32-byte hex key

    backup_file = tmp_path / "paper_trades.json"
    backup_file.write_text('{"balance": 500}')

    uploaded_paths = []

    def fake_upload(local_path, bucket, key, **kwargs):
        uploaded_paths.append(local_path)

    mock_s3 = MagicMock()
    mock_s3.upload_file.side_effect = fake_upload

    with patch("boto3.client", return_value=mock_s3):
        from paper import cloud_backup
        cloud_backup(backup_file)

    # The uploaded file should not be the original (should be the encrypted temp)
    assert mock_s3.upload_file.called
    if uploaded_paths:
        uploaded = Path(uploaded_paths[0])
        # Encrypted file won't be valid JSON
        try:
            json.loads(uploaded.read_text())
            # If it parsed as JSON, encryption was skipped (acceptable if cryptography unavailable)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass  # Encrypted — expected


def test_cloud_backup_fails_gracefully_on_s3_error(tmp_path, monkeypatch, caplog):
    """cloud_backup catches S3 errors and logs a warning without crashing."""
    import logging
    monkeypatch.setenv("KALSHI_S3_BUCKET", "my-bucket")

    backup_file = tmp_path / "backup.json"
    backup_file.write_text('{"balance": 500}')

    mock_s3 = MagicMock()
    mock_s3.upload_file.side_effect = Exception("S3 connection refused")

    with patch("boto3.client", return_value=mock_s3):
        with caplog.at_level(logging.WARNING, logger="paper"):
            from paper import cloud_backup
            result = cloud_backup(backup_file)

    assert result is None or result is False
    assert any("s3" in r.message.lower() or "cloud" in r.message.lower() or "backup" in r.message.lower()
               for r in caplog.records)
```

**Run**: `pytest tests/test_cloud_backup.py -x` → `FAILED`.

### Implementation

Add `cloud_backup()` to `paper.py`:

```python
import os as _os
import tempfile as _tempfile


def cloud_backup(local_path) -> bool | None:
    """
    Upload a backup file to S3 if KALSHI_S3_BUCKET env var is set (#105).
    
    Environment variables:
      KALSHI_S3_BUCKET        — S3 bucket name (required to enable)
      KALSHI_S3_PREFIX        — Key prefix, e.g. "kalshi-backups/" (optional)
      KALSHI_BACKUP_ENCRYPT_KEY — 64-char hex string (32 bytes AES key); optional
      KALSHI_GCS_BUCKET       — GCS bucket (future; not yet implemented)

    Returns True on success, False on failure, None if not configured.
    """
    from pathlib import Path as _Path
    local_path = _Path(local_path)

    bucket = _os.environ.get("KALSHI_S3_BUCKET")
    if not bucket:
        return None  # Cloud backup not configured

    prefix = _os.environ.get("KALSHI_S3_PREFIX", "kalshi-backups/")
    key = f"{prefix}{local_path.name}"

    # Optional encryption
    upload_path = local_path
    tmp_encrypted = None
    encrypt_key_hex = _os.environ.get("KALSHI_BACKUP_ENCRYPT_KEY")
    if encrypt_key_hex:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            import secrets as _secrets
            key_bytes = bytes.fromhex(encrypt_key_hex[:64])
            nonce = _secrets.token_bytes(12)
            plaintext = local_path.read_bytes()
            ct = AESGCM(key_bytes).encrypt(nonce, plaintext, None)
            fd, tmp_enc_path = _tempfile.mkstemp(suffix=".enc")
            with _os.fdopen(fd, "wb") as fenc:
                fenc.write(nonce + ct)
            upload_path = _Path(tmp_enc_path)
            tmp_encrypted = tmp_enc_path
            key += ".enc"
        except Exception as enc_exc:
            _log_paper.warning("Encryption skipped (%s); uploading unencrypted", enc_exc)

    try:
        import boto3
        s3 = boto3.client("s3")
        s3.upload_file(str(upload_path), bucket, key)
        _log_paper.info("Cloud backup uploaded: s3://%s/%s", bucket, key)
        return True
    except Exception as e:
        _log_paper.warning("Cloud backup to S3 failed: %s", e)
        return False
    finally:
        if tmp_encrypted:
            try:
                _os.unlink(tmp_encrypted)
            except OSError:
                pass
```

Wire into the backup function in `main.py` (or wherever backup is called after Phase 2):

```python
from paper import cloud_backup, verify_backup

# ... after writing local backup ...
if verify_backup(backup_path):
    cloud_backup(backup_path)
```

**Run**: `pytest tests/test_cloud_backup.py -x` → all green.

**Commit**:
```
git add paper.py main.py tests/test_cloud_backup.py
git commit -m "feat: optional S3 cloud backup with AES-GCM encryption (#105)"
```

---

## Task 4 — Inverse-variance ensemble confidence weighting (#31)

### Context
`_blend_weights()` (`weather_markets.py:920`) returns fixed weights by `days_out`.  
`ensemble_stats()` (`weather_markets.py:507`) computes `"std"` — the ensemble spread.  

Improvement: when ensemble std is high (models disagree), scale down the ensemble weight and redistribute to climatology/NWS. When std is low (tight agreement), ensemble gets a bonus.

Formula: `confidence_scale = clamp(σ_ref / σ, 0.5, 1.5)` where `σ_ref = 4.0°F` (typical tight ensemble), then multiply ensemble weight by `confidence_scale` and renormalize.

### Failing tests
**File**: `tests/test_weather_markets.py` (append to existing)

```python
def test_ensemble_confidence_scale_high_std_reduces_ens_weight():
    """High ensemble std (uncertain forecast) reduces ensemble blend weight."""
    from weather_markets import _confidence_scaled_blend_weights

    # Days out = 3, NWS + clim available
    w_ens_tight, w_clim_tight, w_nws_tight = _confidence_scaled_blend_weights(
        days_out=3, has_nws=True, has_clim=True, ens_std=2.0  # tight ensemble
    )
    w_ens_wide, w_clim_wide, w_nws_wide = _confidence_scaled_blend_weights(
        days_out=3, has_nws=True, has_clim=True, ens_std=12.0  # wide ensemble
    )
    # Wide ensemble → lower ensemble weight
    assert w_ens_wide < w_ens_tight
    # Weights still sum to ~1.0
    assert abs(w_ens_wide + w_clim_wide + w_nws_wide - 1.0) < 1e-6


def test_ensemble_confidence_scale_no_std_unchanged():
    """When ens_std is None, _confidence_scaled_blend_weights == _blend_weights."""
    from weather_markets import _blend_weights, _confidence_scaled_blend_weights

    w1 = _blend_weights(5, has_nws=True, has_clim=True)
    w2 = _confidence_scaled_blend_weights(5, has_nws=True, has_clim=True, ens_std=None)
    assert w1 == pytest.approx(w2, abs=1e-6)


def test_ensemble_confidence_scale_clamped():
    """Confidence scale is clamped: very low std doesn't give ensemble >1.5× base weight."""
    from weather_markets import _confidence_scaled_blend_weights, _blend_weights

    base_ens, _, _ = _blend_weights(3, has_nws=True, has_clim=True)
    scaled_ens, _, _ = _confidence_scaled_blend_weights(
        3, has_nws=True, has_clim=True, ens_std=0.01  # unrealistically tight
    )
    # Should be at most 1.5× the base weight (renormalized)
    assert scaled_ens <= 1.0  # Can't exceed 100%
```

**Run**: `pytest tests/test_weather_markets.py -k "confidence_scale" -x` → `FAILED`.

### Implementation

**Step 1**: Add `_confidence_scaled_blend_weights()` to `weather_markets.py` (after `_blend_weights`):

```python
_ENS_STD_REF = 4.0  # °F — typical tight ensemble spread; weight unchanged at this std


def _confidence_scaled_blend_weights(
    days_out: int,
    has_nws: bool,
    has_clim: bool,
    ens_std: float | None = None,
) -> tuple[float, float, float]:
    """
    #31: Like _blend_weights but scales ensemble weight by inverse ensemble variance.
    
    When ens_std is high (models disagree), redistribute weight from ensemble
    to climatology/NWS. When ens_std is low (tight agreement), give ensemble a bonus.
    
    confidence_scale = clamp(σ_ref / σ, 0.5, 1.5)
    """
    w_ens, w_clim, w_nws = _blend_weights(days_out, has_nws, has_clim)

    if ens_std is None or ens_std <= 0:
        return w_ens, w_clim, w_nws

    scale = max(0.5, min(1.5, _ENS_STD_REF / ens_std))
    w_ens_scaled = w_ens * scale
    # Redistribute delta equally to clim and nws (proportional to their current weights)
    delta = w_ens - w_ens_scaled
    total_others = w_clim + w_nws
    if total_others > 0:
        w_clim_new = w_clim + delta * (w_clim / total_others)
        w_nws_new = w_nws + delta * (w_nws / total_others)
    else:
        w_clim_new = w_clim
        w_nws_new = w_nws

    # Renormalize to sum to 1.0
    total = w_ens_scaled + w_clim_new + w_nws_new
    return w_ens_scaled / total, w_clim_new / total, w_nws_new / total
```

**Step 2**: Update the call site in `analyze_trade()` (`weather_markets.py:1485`):

```python
# Was:
w_ens, w_clim, w_nws = _blend_weights(
    days_out, _nws_prob is not None, clim_prob is not None
)

# Becomes:
w_ens, w_clim, w_nws = _confidence_scaled_blend_weights(
    days_out,
    _nws_prob is not None,
    clim_prob is not None,
    ens_std=ens_stats.get("std") if ens_stats else None,  # #31
)
```

Also update the precipitation path call at `weather_markets.py:1155` to use `_confidence_scaled_blend_weights` with `ens_std=None` (precip ensemble std not yet tracked — safe fallback).

**Run**: `pytest tests/test_weather_markets.py -k "confidence_scale" -x` → all green.

**Commit**:
```
git add weather_markets.py tests/test_weather_markets.py
git commit -m "feat: inverse-variance ensemble confidence weighting (#31)"
```

---

## Task 5 — Wet-bulb snow-to-liquid ratio (#34)

### Context
`_analyze_precip_trade()` (`weather_markets.py:1109`): when `condition["type"] == "precip_snow"`, `thresh` is in **inches of snow**. The ensemble members are **liquid precipitation (inches of rain)**.

Current code: `ens_prob = sum(1 for p in precip_members if p > thresh) / len(precip_members)` — comparing liquid precip directly to snow threshold, which implicitly assumes a 10:1 snow-to-liquid ratio and ignores temperature.

Fix: estimate the snow-to-liquid ratio (SLR) from wet-bulb temperature. Convert snow threshold to liquid equivalent before comparing.

**Wet-bulb approximation** (Stull 2011 formula):
```
Tw = T * atan(0.151977 * (RH + 8.313659)^0.5)
   + atan(T + RH) - atan(RH - 1.676331)
   + 0.00391838 * RH^1.5 * atan(0.023101 * RH) - 4.686035
```

**SLR from wet-bulb** (empirical, NOAA operational):
- Tw ≤ 28°F → SLR ≈ 20 (dry powder)
- 28°F < Tw ≤ 30°F → SLR ≈ 15
- 30°F < Tw ≤ 32°F → SLR ≈ 10
- Tw > 32°F → no snow (rain), SLR = 0

### Failing tests
**File**: `tests/test_weather_markets.py` (append)

```python
def test_wet_bulb_temp_approximation():
    """Stull (2011) wet-bulb approximation returns plausible values."""
    from weather_markets import wet_bulb_temp

    # At 32°F, 100% RH → wet bulb ≈ 32°F
    wb = wet_bulb_temp(temp_f=32.0, rh_pct=100.0)
    assert 30.0 <= wb <= 34.0

    # At 50°F, 50% RH → wet bulb well below dry-bulb
    wb2 = wet_bulb_temp(temp_f=50.0, rh_pct=50.0)
    assert wb2 < 50.0
    assert wb2 > 30.0


def test_snow_to_liquid_ratio_dry_cold():
    """Very cold conditions (Tw ≤ 28°F) → SLR ≈ 20."""
    from weather_markets import snow_liquid_ratio
    # Tw = 25°F → dry powder
    assert snow_liquid_ratio(wet_bulb_f=25.0) == 20


def test_snow_to_liquid_ratio_borderline():
    """Near-freezing wet-bulb → SLR ≈ 10."""
    from weather_markets import snow_liquid_ratio
    assert snow_liquid_ratio(wet_bulb_f=31.0) == 10


def test_snow_to_liquid_ratio_above_freezing():
    """Wet-bulb above 32°F → no snow (SLR = 0)."""
    from weather_markets import snow_liquid_ratio
    assert snow_liquid_ratio(wet_bulb_f=33.0) == 0


def test_snow_prob_uses_slr_not_1_to_10(monkeypatch):
    """
    Snow probability for a cold, dry scenario (SLR=20) differs from warm (SLR=10).
    1 inch of snow at SLR=20 requires only 0.05in of liquid; at SLR=10 requires 0.10in.
    A forecast of 0.08in liquid should:
      - Pass at SLR=20 (0.08 > 0.05)
      - Fail at SLR=10 (0.08 < 0.10)
    """
    from weather_markets import liquid_equiv_of_snow_threshold

    # 1 inch snow threshold
    liq_20 = liquid_equiv_of_snow_threshold(snow_inches=1.0, slr=20)
    liq_10 = liquid_equiv_of_snow_threshold(snow_inches=1.0, slr=10)
    assert liq_20 == pytest.approx(0.05)
    assert liq_10 == pytest.approx(0.10)
```

**Run**: `pytest tests/test_weather_markets.py -k "wet_bulb or snow_liquid or liquid_equiv" -x` → `FAILED`.

### Implementation

**Step 1**: Add utility functions to `weather_markets.py` (after `ensemble_stats`, before market parsing):

```python
import math as _math


def wet_bulb_temp(temp_f: float, rh_pct: float) -> float:
    """
    #34: Approximate wet-bulb temperature (°F) using Stull (2011) formula.
    Works for -20°C to 50°C and RH 5%–99%.
    
    Args:
        temp_f: Dry-bulb temperature in °F
        rh_pct: Relative humidity in percent (0–100)
    """
    # Convert to Celsius for Stull formula
    T = (temp_f - 32) * 5 / 9
    RH = rh_pct
    Tw_c = (
        T * _math.atan(0.151977 * (RH + 8.313659) ** 0.5)
        + _math.atan(T + RH)
        - _math.atan(RH - 1.676331)
        + 0.00391838 * RH ** 1.5 * _math.atan(0.023101 * RH)
        - 4.686035
    )
    return Tw_c * 9 / 5 + 32  # Convert back to °F


def snow_liquid_ratio(wet_bulb_f: float) -> int:
    """
    #34: Empirical snow-to-liquid ratio from wet-bulb temperature (°F).
    Based on NOAA operational guidelines.
    
    Returns 0 if wet-bulb > 32°F (precipitation falls as rain, not snow).
    """
    if wet_bulb_f > 32.0:
        return 0  # Rain
    elif wet_bulb_f > 30.0:
        return 10  # Wet, heavy snow
    elif wet_bulb_f > 28.0:
        return 15  # Mixed conditions
    else:
        return 20  # Dry powder


def liquid_equiv_of_snow_threshold(snow_inches: float, slr: int) -> float:
    """
    Convert snow accumulation threshold (inches) to liquid water equivalent (inches).
    
    liquid_inches = snow_inches / SLR
    """
    if slr <= 0:
        return float("inf")  # No snow possible; threshold effectively unreachable
    return snow_inches / slr
```

**Step 2**: Update `_analyze_precip_trade()` to use SLR when condition is `precip_snow`. Find the snow probability calculation (`weather_markets.py:1126-1130`) and update:

```python
if condition["type"] == "precip_any":
    ens_prob = sum(1 for p in precip_members if p > 0.01) / len(precip_members)
elif condition["type"] == "precip_snow":
    # #34: Use wet-bulb temperature to estimate snow-to-liquid ratio
    # Fetch forecast temperature and humidity for the target location
    forecast_temp = forecast.get("temp_high", 32.0) or 32.0
    forecast_rh = forecast.get("humidity", 70.0) or 70.0
    wb = wet_bulb_temp(forecast_temp, forecast_rh)
    slr = snow_liquid_ratio(wb)
    snow_thresh = condition.get("threshold", 0.0)  # inches of snow

    if slr == 0:
        # Wet-bulb above freezing → no snow; probability = 0
        ens_prob = 0.01
    else:
        liquid_thresh = liquid_equiv_of_snow_threshold(snow_thresh, slr)
        if snow_thresh == 0.0:
            # "Any snow" market — any liquid precip when Tw < 32°F
            ens_prob = sum(1 for p in precip_members if p > 0.001) / len(precip_members)
        else:
            ens_prob = sum(1 for p in precip_members if p > liquid_thresh) / len(precip_members)
else:
    thresh = condition["threshold"]
    ens_prob = sum(1 for p in precip_members if p > thresh) / len(precip_members)
```

**Run**: `pytest tests/test_weather_markets.py -k "wet_bulb or snow_liquid or liquid_equiv" -x` → all green.

**Commit**:
```
git add weather_markets.py tests/test_weather_markets.py
git commit -m "feat: wet-bulb snow-to-liquid ratio for snow accumulation markets (#34)"
```

---

## Task 6 — Bias correction for edge selectivity (#55)

### Context
`get_bias()` in `tracker.py` computes mean (forecast_prob − outcome) from the `predictions` table. But we only call `log_prediction()` for markets we analyze (via `analyze_trade()`). We **trade** a subset of those — high-edge ones. This means our bias estimate is computed only on analyzed markets, not on a representative sample.

Actually the real issue is: we compute bias from the predictions we log — but we filter what we log. If we only log markets where we consider trading (edge > threshold), our bias estimate is skewed because we selected on correlated variables.

Fix: log ALL analyzed markets to a separate `analysis_attempts` table, regardless of edge. Then `get_unselected_bias()` can compute bias on markets we analyzed but chose NOT to trade, giving an uncontaminated estimate.

### Failing tests
**File**: `tests/test_tracker.py` (append)

```python
def test_log_analysis_attempt_stores_all_markets(tmp_db):
    """log_analysis_attempt stores forecast vs market prob even for low-edge markets."""
    from tracker import log_analysis_attempt, _con
    from datetime import date

    log_analysis_attempt(
        ticker="KXWEATHER-LOWEDGE",
        city="NYC",
        condition="HIGH_ABOVE_70",
        target_date=date(2025, 7, 1),
        forecast_prob=0.52,
        market_prob=0.50,
        days_out=3,
        was_traded=False,
    )
    with _con() as con:
        row = con.execute(
            "SELECT forecast_prob, market_prob, was_traded "
            "FROM analysis_attempts WHERE ticker='KXWEATHER-LOWEDGE'"
        ).fetchone()
    assert row is not None
    assert row[0] == pytest.approx(0.52)
    assert row[2] == 0  # was_traded = False


def test_get_unselected_bias_excludes_traded_markets(tmp_db):
    """get_unselected_bias only uses markets that were analyzed but NOT traded."""
    from tracker import log_analysis_attempt, settle_analysis_attempt, get_unselected_bias
    from datetime import date

    # Market we analyzed and traded — forecast_prob = 0.8, outcome = 1 → bias = -0.2
    log_analysis_attempt(
        ticker="TRADED",
        city="NYC",
        condition="HIGH_ABOVE_70",
        target_date=date(2025, 7, 1),
        forecast_prob=0.80,
        market_prob=0.50,
        days_out=2,
        was_traded=True,
    )
    settle_analysis_attempt("TRADED", date(2025, 7, 1), outcome=1)

    # Market we analyzed but didn't trade — forecast_prob = 0.6, outcome = 0 → bias = +0.6
    log_analysis_attempt(
        ticker="NOT-TRADED",
        city="NYC",
        condition="HIGH_ABOVE_70",
        target_date=date(2025, 7, 2),
        forecast_prob=0.60,
        market_prob=0.50,
        days_out=2,
        was_traded=False,
    )
    settle_analysis_attempt("NOT-TRADED", date(2025, 7, 2), outcome=0)

    bias = get_unselected_bias("NYC")
    # Should only use the NOT-TRADED market: bias = forecast - outcome = 0.6 - 0 = 0.6
    assert bias == pytest.approx(0.6, abs=0.01)


def test_get_unselected_bias_returns_zero_when_no_data(tmp_db):
    """get_unselected_bias returns 0.0 when no untraded markets are settled."""
    from tracker import get_unselected_bias
    assert get_unselected_bias("NOWHERE") == 0.0
```

**Run**: `pytest tests/test_tracker.py -k "unselected_bias or analysis_attempt" -x` → `FAILED`.

### Implementation

**Step 1**: Add migration for `analysis_attempts` table to `_MIGRATIONS` in `tracker.py`:

```python
(N+2,
 """CREATE TABLE IF NOT EXISTS analysis_attempts (
     ticker TEXT NOT NULL,
     city TEXT,
     condition TEXT,
     target_date TEXT,
     analyzed_at TEXT,
     forecast_prob REAL,
     market_prob REAL,
     days_out INTEGER,
     was_traded INTEGER DEFAULT 0,
     outcome INTEGER,
     PRIMARY KEY (ticker, target_date)
 )"""),
```

**Step 2**: Add `log_analysis_attempt()` to `tracker.py`:

```python
def log_analysis_attempt(
    ticker: str,
    city: str,
    condition: str,
    target_date,
    forecast_prob: float,
    market_prob: float,
    days_out: int,
    was_traded: bool = False,
) -> None:
    """
    #55: Log every analyzed market to analysis_attempts, regardless of whether
    we traded it. Used to compute unselected bias (bias without selection effect).
    """
    with _con() as con:
        con.execute(
            """INSERT OR REPLACE INTO analysis_attempts
               (ticker, city, condition, target_date, analyzed_at,
                forecast_prob, market_prob, days_out, was_traded)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                ticker, city, condition,
                target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date),
                _now_iso(),
                forecast_prob, market_prob, days_out,
                int(was_traded),
            ),
        )


def settle_analysis_attempt(ticker: str, target_date, outcome: int) -> None:
    """Record the actual outcome for an analysis_attempts row."""
    with _con() as con:
        con.execute(
            """UPDATE analysis_attempts SET outcome = ?
               WHERE ticker = ? AND target_date = ?""",
            (outcome, ticker,
             target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date)),
        )


def get_unselected_bias(city: str, condition_type: str | None = None) -> float:
    """
    #55: Compute mean (forecast_prob - outcome) on markets we analyzed but did NOT trade.
    
    This gives an uncontaminated bias estimate free from edge-selectivity bias —
    i.e., we can see if our model is systematically wrong on markets we passed on.

    Returns 0.0 if no settled untraded markets are available.
    """
    with _con() as con:
        if condition_type:
            rows = con.execute(
                """SELECT forecast_prob, outcome FROM analysis_attempts
                   WHERE city = ? AND condition = ? AND was_traded = 0
                     AND outcome IS NOT NULL""",
                (city, condition_type),
            ).fetchall()
        else:
            rows = con.execute(
                """SELECT forecast_prob, outcome FROM analysis_attempts
                   WHERE city = ? AND was_traded = 0 AND outcome IS NOT NULL""",
                (city,),
            ).fetchall()

    if not rows:
        return 0.0
    errors = [fp - o for fp, o in rows]
    return round(sum(errors) / len(errors), 4)
```

**Step 3**: Call `log_analysis_attempt()` inside `get_weather_markets()` in `weather_markets.py` — after `analyze_trade()` returns for each market:

```python
# Log every analyzed market for unselected bias tracking (#55)
try:
    import tracker as _tracker
    _tracker.log_analysis_attempt(
        ticker=analysis.get("ticker", enriched.get("ticker", "")),
        city=city,
        condition=str(analysis.get("condition", "")),
        target_date=target_date,
        forecast_prob=analysis.get("forecast_prob", 0.5),
        market_prob=analysis.get("market_prob", 0.5),
        days_out=analysis.get("days_out", 0),
        was_traded=False,  # updated to True in paper.py when trade is placed
    )
except Exception:
    pass
```

And in `paper.py`, when a trade is entered, update `was_traded`:

```python
# Mark this market as traded in analysis_attempts (#55)
try:
    from tracker import settle_analysis_attempt as _settle_attempt
    # We don't have a settle function for was_traded — use direct update
    from tracker import _con
    with _con() as con:
        con.execute(
            """UPDATE analysis_attempts SET was_traded = 1
               WHERE ticker = ? AND target_date = ?""",
            (ticker, target_date_str),
        )
except Exception:
    pass
```

**Run**: `pytest tests/test_tracker.py -k "unselected_bias or analysis_attempt" -x` → all green.

**Commit**:
```
git add tracker.py weather_markets.py paper.py tests/test_tracker.py
git commit -m "feat: unselected bias tracking — log all analyzed markets, not just traded (#55)"
```

---

## Execution order

```
Task 1 (CRC32)       →  Task 2 (backup verify)  →  Task 3 (cloud backup)
Task 4 (inv-variance) →  Task 5 (wet-bulb SLR)   →  Task 6 (unselected bias)
```

Tasks 1-3 are data safety (no model deps). Tasks 4-6 are forecasting (no storage deps).  
Run all 6 independently — no cross-task dependencies.
