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


def test_save_writes_crc32_field(tmp_path, monkeypatch):
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    paper._save({"balance": 1000.0, "trades": []})
    stored = json.loads((tmp_path / "paper_trades.json").read_bytes())
    # #102: SHA-256 replaced CRC32; accept either field for backward compatibility
    assert "_checksum" in stored or "_crc32" in stored
    checksum_field = stored.get("_checksum") or stored.get("_crc32")
    assert len(checksum_field) == 16


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
        "crc32" in r.message.lower() or checksum in r.message for r in caplog.records
    )
