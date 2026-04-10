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
