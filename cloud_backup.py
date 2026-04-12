"""cloud_backup.py — sync data/ to OneDrive, Google Drive, or a custom path."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

_log = logging.getLogger(__name__)

# Files in data/ worth backing up (skip .shm/.wal SQLite temp files and logs)
_BACKUP_EXTENSIONS = {".json", ".db"}
_SKIP_NAMES = {"signals_cache.json", "analyze_log.txt"}


def _find_sync_folder() -> Path | None:
    """
    Return the best available cloud sync folder, in priority order:
      1. CLOUD_BACKUP_PATH env var (user-specified)
      2. OneDrive (built into Windows 11 — ONEDRIVE env var set by system)
      3. Google Drive (common install paths)
    Returns None if nothing is found.
    """
    # 1. Explicit override
    custom = os.environ.get("CLOUD_BACKUP_PATH")
    if custom:
        p = Path(custom)
        if p.exists():
            return p
        _log.warning("cloud_backup: CLOUD_BACKUP_PATH %s does not exist", custom)

    # 2. OneDrive — Windows sets %ONEDRIVE% automatically when signed in
    onedrive = os.environ.get("ONEDRIVE")
    if onedrive:
        p = Path(onedrive)
        if p.exists():
            return p

    # 3. Google Drive — typical default install locations
    for candidate in [
        Path.home() / "Google Drive",
        Path.home() / "GoogleDrive",
        Path("G:/My Drive"),
        Path("G:/Google Drive"),
    ]:
        if candidate.exists():
            return candidate

    return None


def backup_data(data_dir: Path | None = None) -> bool:
    """
    Copy important files from data/ into <sync_folder>/KalshiBot/data/.
    Returns True on success, False on failure, None if no sync folder configured.
    """
    sync_root = _find_sync_folder()
    if sync_root is None:
        _log.debug(
            "cloud_backup: no sync folder found — set CLOUD_BACKUP_PATH in .env "
            "or sign in to OneDrive/Google Drive"
        )
        return None  # type: ignore[return-value]

    if data_dir is None:
        data_dir = Path(__file__).parent / "data"

    dest = sync_root / "KalshiBot" / "data"
    dest.mkdir(parents=True, exist_ok=True)

    copied = 0
    try:
        for src_file in data_dir.iterdir():
            if src_file.is_file() and src_file.suffix in _BACKUP_EXTENSIONS:
                if src_file.name in _SKIP_NAMES:
                    continue
                shutil.copy2(src_file, dest / src_file.name)
                copied += 1
        _log.info("cloud_backup: synced %d file(s) to %s", copied, dest)
        return True
    except Exception as exc:
        _log.warning("cloud_backup: sync failed: %s", exc)
        return False


def restore_data(data_dir: Path | None = None) -> bool:
    """
    Copy files from <sync_folder>/KalshiBot/data/ back into local data/.
    Use this on a new PC after cloning the repo.
    Returns True on success, False if nothing to restore.
    """
    sync_root = _find_sync_folder()
    if sync_root is None:
        print(
            "No cloud sync folder found. Set CLOUD_BACKUP_PATH in .env or sign in to OneDrive."
        )
        return False

    src = sync_root / "KalshiBot" / "data"
    if not src.exists():
        print(f"No backup found at {src}")
        return False

    if data_dir is None:
        data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for src_file in src.iterdir():
        if src_file.is_file() and src_file.suffix in _BACKUP_EXTENSIONS:
            dest_file = data_dir / src_file.name
            shutil.copy2(src_file, dest_file)
            copied += 1
            print(f"  Restored {src_file.name}")

    if copied == 0:
        print("Backup folder exists but contains no data files.")
        return False

    print(f"\n  {copied} file(s) restored from {src}")
    return True


# Legacy S3 function kept for compatibility
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
