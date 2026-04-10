import json
import sys
from unittest.mock import MagicMock


def test_cloud_backup_skipped_without_env(tmp_path, monkeypatch):
    monkeypatch.delenv("KALSHI_S3_BUCKET", raising=False)
    monkeypatch.delenv("KALSHI_GCS_BUCKET", raising=False)
    from paper import cloud_backup

    result = cloud_backup(tmp_path / "backup.json")
    assert result is None


def test_cloud_backup_uploads_to_s3(tmp_path, monkeypatch):
    monkeypatch.setenv("KALSHI_S3_BUCKET", "my-test-bucket")
    monkeypatch.setenv("KALSHI_S3_PREFIX", "kalshi-backups/")
    backup_file = tmp_path / "paper_trades.json"
    backup_file.write_text(json.dumps({"balance": 1000.0, "trades": []}))
    mock_s3 = MagicMock()
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_s3
    monkeypatch.setitem(sys.modules, "boto3", mock_boto3)
    from paper import cloud_backup

    cloud_backup(backup_file)
    mock_s3.upload_file.assert_called_once()
    call_args = mock_s3.upload_file.call_args
    assert "my-test-bucket" in str(call_args)


def test_cloud_backup_fails_gracefully_on_s3_error(tmp_path, monkeypatch, caplog):
    import logging

    monkeypatch.setenv("KALSHI_S3_BUCKET", "my-bucket")
    backup_file = tmp_path / "backup.json"
    backup_file.write_text('{"balance": 500}')
    mock_s3 = MagicMock()
    mock_s3.upload_file.side_effect = Exception("S3 connection refused")
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_s3
    monkeypatch.setitem(sys.modules, "boto3", mock_boto3)
    with caplog.at_level(logging.WARNING):
        from paper import cloud_backup

        result = cloud_backup(backup_file)
    assert result is None or result is False
    assert any(
        "s3" in r.message.lower()
        or "cloud" in r.message.lower()
        or "backup" in r.message.lower()
        for r in caplog.records
    )


# ── cloud_backup.py module (#105) ─────────────────────────────────────────────


def test_backup_to_s3_calls_upload(tmp_path, monkeypatch):
    """backup_to_s3 calls boto3.client('s3').upload_file with correct args."""
    import importlib
    import sys
    from unittest.mock import MagicMock

    mock_s3 = MagicMock()
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_s3
    monkeypatch.setitem(sys.modules, "boto3", mock_boto3)

    local = tmp_path / "predictions_2026-04-10.db"
    local.write_bytes(b"data")

    import cloud_backup

    importlib.reload(cloud_backup)

    cloud_backup.backup_to_s3(local, "my-bucket", "backups/predictions_2026-04-10.db")
    mock_s3.upload_file.assert_called_once_with(
        str(local), "my-bucket", "backups/predictions_2026-04-10.db"
    )


def test_backup_to_s3_skips_when_boto3_missing(tmp_path, monkeypatch, caplog):
    """backup_to_s3 logs a warning and does not raise when boto3 is not installed."""
    import importlib
    import logging
    import sys

    monkeypatch.setitem(sys.modules, "boto3", None)

    import cloud_backup

    importlib.reload(cloud_backup)

    local = tmp_path / "file.db"
    local.write_bytes(b"x")

    with caplog.at_level(logging.WARNING):
        cloud_backup.backup_to_s3(local, "bucket", "key")

    assert any(
        "boto3" in r.message.lower() or "skip" in r.message.lower()
        for r in caplog.records
    )


def test_backup_to_s3_skips_without_env(tmp_path, monkeypatch):
    """backup_to_s3 with no bucket returns None."""
    import importlib

    monkeypatch.delenv("CLOUD_BACKUP_BUCKET", raising=False)

    import cloud_backup

    importlib.reload(cloud_backup)

    local = tmp_path / "file.db"
    local.write_bytes(b"x")

    result = cloud_backup.backup_to_s3(local, bucket=None, key="test")
    assert result is None
