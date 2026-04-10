"""cloud_backup.py — optional S3 upload for local backup files (#105)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

_log = logging.getLogger(__name__)


def backup_to_s3(
    local_path: Path,
    bucket: str | None,
    key: str,
) -> bool | None:
    """Upload local_path to S3 at s3://{bucket}/{key}. Returns True/False/None."""
    resolved_bucket = bucket or os.environ.get("CLOUD_BACKUP_BUCKET")
    if not resolved_bucket:
        return None

    local_path = Path(local_path)

    try:
        import boto3
    except ImportError:
        _log.warning(
            "cloud_backup: boto3 not installed — skipping S3 upload of %s",
            local_path.name,
        )
        return None

    if boto3 is None:
        _log.warning(
            "cloud_backup: boto3 not installed — skipping S3 upload of %s",
            local_path.name,
        )
        return None

    try:
        s3 = boto3.client("s3")
        s3.upload_file(str(local_path), resolved_bucket, key)
        _log.info(
            "cloud_backup: uploaded %s to s3://%s/%s",
            local_path.name,
            resolved_bucket,
            key,
        )
        return True
    except Exception as exc:
        _log.warning("cloud_backup: S3 upload failed for %s: %s", local_path.name, exc)
        return False
