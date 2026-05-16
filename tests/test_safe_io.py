import json
import zlib
from pathlib import Path

import pytest


def _write_with_crc(data: dict, path: Path) -> None:
    payload = dict(data)
    payload.pop("_crc32", None)
    body = json.dumps(payload, indent=2).encode()
    checksum = format(zlib.crc32(body) & 0xFFFFFFFF, "08x")
    payload["_crc32"] = checksum
    path.write_bytes(json.dumps(payload, indent=2).encode())


def test_load_validates_crc_on_good_file(tmp_path):
    from paper import _validate_crc

    f = tmp_path / "test.json"
    _write_with_crc({"balance": 1000.0, "trades": []}, f)
    _validate_crc(json.loads(f.read_bytes()))


def test_load_raises_on_tampered_file(tmp_path):
    from paper import CorruptionError, _validate_crc

    data = {"balance": 1000.0, "trades": [], "_crc32": "deadbeef"}
    with pytest.raises(CorruptionError):
        _validate_crc(data)


def test_load_skips_crc_check_when_field_absent(tmp_path):
    from paper import _validate_crc

    data = {"balance": 1000.0, "trades": []}
    _validate_crc(data)


def test_save_writes_checksum_field(tmp_path, monkeypatch):
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    paper._save({"balance": 1000.0, "trades": []})
    stored = json.loads((tmp_path / "paper_trades.json").read_bytes())
    assert "_checksum" in stored
    # P1-5: new writes must use full 64-char SHA-256 hex
    assert len(stored["_checksum"]) == 64


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    paper._save({"balance": 1234.56, "trades": []})
    loaded = paper._load()
    assert loaded["balance"] == 1234.56


def test_verify_backup_passes_on_good_file(tmp_path):
    from paper import verify_backup

    data = {"balance": 999.0, "trades": []}
    body = json.dumps(data, indent=2).encode()
    checksum = format(zlib.crc32(body) & 0xFFFFFFFF, "08x")
    data_with_crc = {**data, "_crc32": checksum}
    backup_path = tmp_path / "backup.json"
    backup_path.write_text(json.dumps(data_with_crc, indent=2))
    assert verify_backup(backup_path) is True


def test_verify_backup_fails_on_corrupt_file(tmp_path):
    from paper import verify_backup

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text('{"balance": 999, "_crc32": "badf00d0"}')
    assert verify_backup(corrupt) is False


def test_verify_backup_fails_on_invalid_json(tmp_path):
    from paper import verify_backup

    bad = tmp_path / "bad.json"
    bad.write_text("NOT JSON {{{")
    assert verify_backup(bad) is False


def test_verify_backup_logs_checksum_on_success(tmp_path, caplog):
    import logging

    from paper import verify_backup

    data = {"balance": 500.0, "trades": []}
    body = json.dumps(data, indent=2).encode()
    checksum = format(zlib.crc32(body) & 0xFFFFFFFF, "08x")
    data["_crc32"] = checksum
    good = tmp_path / "good.json"
    good.write_text(json.dumps(data, indent=2))
    with caplog.at_level(logging.INFO):
        verify_backup(good)
    assert any(
        "crc32" in r.message.lower()
        or "sha-256" in r.message.lower()
        or checksum in r.message
        for r in caplog.records
    )


# ── P1-5: _validate_checksum constant-time comparison ─────────────────────────


def test_validate_checksum_passes_on_valid_64char(tmp_path, monkeypatch):
    """P1-5: valid 64-char checksum must pass validation."""
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    paper._save({"balance": 500.0, "trades": []})
    data = json.loads((tmp_path / "paper_trades.json").read_bytes())
    paper._validate_checksum(data)  # must not raise


def test_validate_checksum_rejects_empty_string(tmp_path):
    """P1-5: empty checksum string must raise CorruptionError (was silently passing)."""
    from paper import CorruptionError, _validate_checksum

    data = {"balance": 500.0, "trades": [], "_checksum": ""}
    with pytest.raises(CorruptionError, match="length"):
        _validate_checksum(data)


def test_validate_checksum_rejects_one_char(tmp_path):
    """P1-5: 1-char checksum must raise CorruptionError (was passing 1/16 of corruptions)."""
    from paper import CorruptionError, _validate_checksum

    data = {"balance": 500.0, "trades": [], "_checksum": "a"}
    with pytest.raises(CorruptionError, match="length"):
        _validate_checksum(data)


def test_validate_checksum_rejects_mismatch(tmp_path):
    """P1-5: tampered data must raise CorruptionError."""
    from paper import CorruptionError, _validate_checksum

    data = {"balance": 500.0, "trades": [], "_checksum": "a" * 64}
    with pytest.raises(CorruptionError, match="mismatch"):
        _validate_checksum(data)


def test_validate_checksum_accepts_legacy_16char(tmp_path, monkeypatch):
    """P1-5: 16-char checksums (prior format) must still pass validation."""
    import hashlib

    from paper import _validate_checksum

    payload = {"balance": 500.0, "trades": []}
    body = json.dumps(payload, indent=2, sort_keys=True, default=str).encode()
    checksum_16 = hashlib.sha256(body).hexdigest()[:16]
    data = {**payload, "_checksum": checksum_16}
    _validate_checksum(data)  # must not raise


def test_validate_checksum_skips_when_absent():
    """P1-5: no _checksum field means no validation (legacy files without checksum)."""
    from paper import _validate_checksum

    _validate_checksum({"balance": 500.0, "trades": []})  # must not raise


# ── P1-6: atomic_write_json raises on %TEMP% fallback ─────────────────────────


def test_atomic_write_raises_when_all_retries_fail(tmp_path, monkeypatch):
    """P1-6: AtomicWriteError must be raised when the primary path is unwritable."""
    import os

    import safe_io

    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()

    def fail_replace(src, dst):
        raise OSError("simulated disk full")

    monkeypatch.setattr(os, "replace", fail_replace)

    target = readonly_dir / "data.json"
    from safe_io import AtomicWriteError

    with pytest.raises(AtomicWriteError):
        safe_io.atomic_write_json({"key": "value"}, target, retries=1)


def test_atomic_write_emergency_copy_written_on_failure(tmp_path, monkeypatch):
    """P1-6: emergency copy is written to fallback_dir before raising."""
    import os

    import safe_io

    emergency_dir = tmp_path / "emergency"
    emergency_dir.mkdir()

    def fail_replace(src, dst):
        raise OSError("simulated disk full")

    monkeypatch.setattr(os, "replace", fail_replace)

    target = tmp_path / "data" / "paper_trades.json"
    from safe_io import AtomicWriteError

    with pytest.raises(AtomicWriteError):
        safe_io.atomic_write_json(
            {"key": "value"}, target, retries=1, fallback_dir=emergency_dir
        )

    # Emergency copy must exist for manual recovery
    assert (emergency_dir / "paper_trades.json").exists()
