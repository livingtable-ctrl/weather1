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


def _find_google_drive() -> Path | None:
    """
    Find the Google Drive sync folder on Windows.
    Checks (in order):
      1. GOOGLE_DRIVE_PATH env var
      2. Windows registry (Google Drive for Desktop — reliable for any drive letter)
      3. Common fallback paths (old Backup and Sync installs)
    """
    # 1. Explicit env var
    env_path = os.environ.get("GOOGLE_DRIVE_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
        _log.warning("cloud_backup: GOOGLE_DRIVE_PATH %s does not exist", env_path)

    # 2. Registry — Google Drive for Desktop stores its root path here
    try:
        import winreg

        key = winreg.OpenKey(  # type: ignore[attr-defined]
            winreg.HKEY_LOCAL_MACHINE,  # type: ignore[attr-defined]
            r"SOFTWARE\Google\DriveFS",
        )
        root, _ = winreg.QueryValueEx(key, "PerAccountPreferences")  # type: ignore[attr-defined]
        winreg.CloseKey(key)  # type: ignore[attr-defined]
        # PerAccountPreferences points to a folder; "My Drive" lives one level up
        p = Path(root).parent / "My Drive"
        if p.exists():
            return p
    except Exception:
        pass

    # 3. Try the current user registry hive
    try:
        import winreg

        key = winreg.OpenKey(  # type: ignore[attr-defined]
            winreg.HKEY_CURRENT_USER,  # type: ignore[attr-defined]
            r"Software\Google\DriveFS",
        )
        root, _ = winreg.QueryValueEx(key, "RootPath")  # type: ignore[attr-defined]
        winreg.CloseKey(key)  # type: ignore[attr-defined]
        p = Path(root) / "My Drive"
        if p.exists():
            return p
        # Some versions store just the root without "My Drive" subdir
        p2 = Path(root)
        if p2.exists():
            return p2
    except Exception:
        pass

    # 4. Scan all drive letters for a Google Drive virtual mount
    import string

    for letter in string.ascii_uppercase:
        for subdir in ("My Drive", "Google Drive"):
            p = Path(f"{letter}:/{subdir}")
            try:
                if p.exists():
                    return p
            except OSError:
                pass

    # 5. Old Backup and Sync install locations
    for candidate in [
        Path.home() / "Google Drive",
        Path.home() / "My Drive",
        Path.home() / "GoogleDrive",
    ]:
        if candidate.exists():
            return candidate

    return None


def _find_sync_folder() -> Path | None:
    """
    Return the best available cloud sync folder, in priority order:
      1. CLOUD_BACKUP_PATH env var (fully custom path)
      2. Google Drive
      3. OneDrive (fallback)
    Returns None if nothing is found.
    """
    # 1. Explicit override
    custom = os.environ.get("CLOUD_BACKUP_PATH")
    if custom:
        p = Path(custom)
        if p.exists():
            return p
        _log.warning("cloud_backup: CLOUD_BACKUP_PATH %s does not exist", custom)

    # 2. Google Drive
    gdrive = _find_google_drive()
    if gdrive is not None:
        return gdrive

    # 3. OneDrive — Windows sets %ONEDRIVE% automatically when signed in
    onedrive = os.environ.get("ONEDRIVE")
    if onedrive:
        p = Path(onedrive)
        if p.exists():
            return p

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
