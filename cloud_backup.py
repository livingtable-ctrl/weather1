"""cloud_backup.py — sync data/ to OneDrive, Google Drive, or a custom path."""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from paths import DATA_DIR

_log = logging.getLogger(__name__)

# Files in data/ worth backing up (skip .shm/.wal SQLite temp files and logs)
_BACKUP_EXTENSIONS = {".json", ".db"}
_SKIP_NAMES = {"signals_cache.json", "analyze_log.txt"}


def _sqlite_source_is_empty(path: Path) -> bool:
    """True only if `path` is a VALID, openable SQLite DB with zero
    tables -- e.g. a 0-byte file (SQLite treats an empty file as a valid,
    freshly-initialized empty database, confirmed live) or one that was
    `sqlite3.connect()`ed but never had a schema created. False for
    anything else, including a file that ISN'T a valid SQLite DB at all
    (garbage bytes, truncated/corrupt) -- that's a real failure the
    caller should still attempt to back up (and warn about when it fails),
    not silently skip.

    AUD batch-25 opus-review-round-2 M1: this project's own data/ has 4
    vestigial zero-byte .db files (kalshi.db, paper_trades.db, tracker.db,
    trades.db -- nothing in the codebase opens them) that backup_data()
    used to happily shutil.copy2() as-is. Once backup_data() started
    routing .db files through backup_sqlite_db's readability check
    (table-existence required), these 4 files failed it on every single
    cron cycle forever -- 4 spurious WARNINGs per run and a permanently
    False return value, both of which bury the genuine backup failure
    this batch exists to make visible. A file with zero tables was never
    going to have anything worth backing up in the first place, so it's
    treated as "nothing to do" here, not "backup failed".
    """
    try:
        con = sqlite3.connect(str(path))
        try:
            n = con.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
            return n == 0
        finally:
            con.close()
    except sqlite3.Error:
        return False


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
    except Exception as exc:
        _log.debug("cloud_backup: HKLM Google Drive registry not found: %s", exc)

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
    except Exception as exc:
        _log.debug("cloud_backup: HKCU Google Drive registry not found: %s", exc)

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
        data_dir = DATA_DIR

    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
    dest = sync_root / "KalshiBot" / "data" / today_str
    dest.mkdir(parents=True, exist_ok=True)

    from safe_io import backup_sqlite_db

    copied = 0
    all_readable = True
    try:
        for src_file in data_dir.iterdir():
            if src_file.is_file() and src_file.suffix in _BACKUP_EXTENSIONS:
                if src_file.name in _SKIP_NAMES:
                    continue
                dest_file = dest / src_file.name
                try:
                    if src_file.suffix == ".db":
                        if _sqlite_source_is_empty(src_file):
                            _log.debug(
                                "cloud_backup: skipping %s -- no tables "
                                "(nothing to back up)",
                                src_file.name,
                            )
                            continue
                        # WAL-safe: shutil.copy2 on the raw .db file
                        # silently omits anything committed but not yet
                        # checkpointed out of the .db-wal sidecar (AUD
                        # backup/pass20 finding -- reproduced live: a
                        # committed row survived only in the WAL, and the
                        # plain-copy backup came back with "no such table"
                        # for a table that had existed since before the
                        # last checkpoint).
                        if not backup_sqlite_db(src_file, dest_file):
                            _log.warning(
                                "cloud_backup: backup copy of %s failed its "
                                "post-copy readability check -- not "
                                "retained (any earlier good backup at this "
                                "path is untouched)",
                                src_file.name,
                            )
                            all_readable = False
                            continue
                    else:
                        shutil.copy2(src_file, dest_file)
                except Exception as file_exc:
                    # Per-file isolation: one unreadable/corrupt source
                    # file (backup_sqlite_db can raise for a source that
                    # isn't a valid SQLite DB at all, not just an
                    # unreadable-after-copy one) must not abort the whole
                    # run and silently skip every OTHER file in data_dir --
                    # that would include execution_log.db, the live-order
                    # ledger this batch exists to make sure gets backed up.
                    _log.warning(
                        "cloud_backup: failed to back up %s: %s -- "
                        "skipping, continuing with remaining files",
                        src_file.name,
                        file_exc,
                    )
                    all_readable = False
                    continue
                copied += 1
        _log.info("cloud_backup: synced %d file(s) to %s", copied, dest)

        # Prune backup directories older than 30 days.
        # batch-33 M-21 LOW(a): directory names are stamped with
        # datetime.now(UTC) (`today_str` above) but this compared them
        # against date.today() -- LOCAL system time. Near local midnight
        # (either side of UTC midnight, depending on timezone) that
        # mismatch makes today's own just-created directory look 1 day
        # old, or lets a 30-day-old directory look fresh for up to another
        # day, purely from the local/UTC gap. Compare UTC-to-UTC instead.
        backup_root = sync_root / "KalshiBot" / "data"
        _today_utc = datetime.now(UTC).date()
        for old_dir in backup_root.iterdir():
            if not old_dir.is_dir():
                continue
            try:
                from datetime import date

                dir_date = date.fromisoformat(old_dir.name)
            except ValueError:
                continue  # not a date-named directory
            if (_today_utc - dir_date).days <= 30:
                continue
            try:
                shutil.rmtree(old_dir)
                _log.debug("cloud_backup: pruned old backup %s", old_dir.name)
            except OSError as _prune_exc:
                # batch-33 M-21 LOW(a): an rmtree failure (e.g. a file
                # still open, permission denied) used to be uncaught here,
                # propagating past this whole try block to the outer
                # `except Exception: return False` -- turning a backup
                # run that copied every file successfully (all_readable
                # still True) into a reported FAILURE just because an
                # unrelated old directory couldn't be deleted. Isolate it:
                # log and keep pruning/reporting the real backup result.
                _log.warning(
                    "cloud_backup: failed to prune old backup %s: %s",
                    old_dir.name,
                    _prune_exc,
                )
        return all_readable
    except Exception as exc:
        _log.warning("cloud_backup: sync failed: %s", exc)
        return False


def restore_data(data_dir: Path | None = None, confirm: bool = False) -> bool:
    """
    Copy files from <sync_folder>/KalshiBot/data/ back into local data/.
    Use this on a new PC after cloning the repo.

    confirm=True is required to prevent accidental overwrites of live files.
    Returns True on success, False if nothing to restore.
    """
    if not confirm:
        raise ValueError(
            "restore_data() requires confirm=True to prevent accidental overwrite of live files. "
            "Pass confirm=True only after verifying the backup source is correct."
        )

    sync_root = _find_sync_folder()
    if sync_root is None:
        print(
            "No cloud sync folder found. Set CLOUD_BACKUP_PATH in .env or sign in to OneDrive."
        )
        return False

    # Find the most recent date-stamped backup directory
    backup_root = sync_root / "KalshiBot" / "data"
    if not backup_root.exists():
        print(f"No backup found at {backup_root}")
        return False

    date_dirs = sorted(
        (d for d in backup_root.iterdir() if d.is_dir()),
        key=lambda d: d.name,
        reverse=True,
    )
    src = next((d for d in date_dirs if d.name[:4].isdigit()), None)
    if src is None:
        # Fall back to backup_root itself for pre-rotation backups
        src = backup_root

    if data_dir is None:
        data_dir = DATA_DIR

    # Snapshot current data/ before overwriting
    snapshot_dir = (
        data_dir / f".pre_restore_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}"
    )
    if data_dir.exists():
        # AUD batch-25 opus-review M6: previously passed
        # ignore=shutil.ignore_patterns("*.shm", "*.wal") here, intending
        # to exclude SQLite's WAL/SHM sidecars. Those globs never actually
        # matched anything, though -- SQLite names them
        # "<dbname>.db-wal"/"<dbname>.db-shm" (hyphen before the suffix,
        # not a dot), so this snapshot was already including them by
        # accident, not by design. Removed anyway: dead exclusion logic
        # that LOOKS like it's protecting the pre-restore safety net from
        # this batch's WAL-omission bug (item 1) but silently does nothing
        # is worse than no logic at all for the next person reading it.
        #
        # batch-33 M-21 LOW(b): snapshot_dir lives INSIDE data_dir itself,
        # so copying data_dir wholesale also copies every PRIOR
        # `.pre_restore_*` snapshot still sitting there into the new one --
        # each successive restore nests the last, growing without bound
        # (a snapshot-of-a-snapshot-of-a-snapshot...). safe_io's own
        # `.history`/`.emergency` state directories are the same shape:
        # they're recovery/audit copies in their own right, not live data
        # worth re-snapshotting inside another snapshot. Exclude all three
        # (directories and any sidecar files matching their naming, e.g. a
        # stray `*.emergency.tmp`) from the copy.
        shutil.copytree(
            data_dir,
            snapshot_dir,
            ignore=shutil.ignore_patterns(
                ".pre_restore_*", ".history", ".emergency", "*.emergency.tmp"
            ),
        )
        print(f"  Current data/ snapshotted to {snapshot_dir.name}")

    data_dir.mkdir(parents=True, exist_ok=True)

    from safe_io import _replace_with_retry

    copied = 0
    attempted = 0
    for src_file in src.iterdir():
        if src_file.is_file() and src_file.suffix in _BACKUP_EXTENSIONS:
            attempted += 1
            dest_file = data_dir / src_file.name
            try:
                if src_file.suffix == ".db":
                    # AUD batch-25 opus-review M6: the backup copy being
                    # restored is a complete, checkpointed snapshot (it was
                    # made via backup_sqlite_db, or is a legacy plain
                    # copy) -- but any -wal/-shm sidecar still sitting next
                    # to the LIVE dest_file belongs to the OLD database
                    # this restore is about to replace. Left in place,
                    # those stale sidecars would apply outdated WAL frames
                    # (wrong page numbers/checksums for the new file
                    # underneath them) the moment something next opens
                    # dest_file in WAL mode.
                    #
                    # opus-review-round-2 M3 / round-3 M-1: copy to a
                    # sibling temp path first and swap it into place with
                    # a Windows-retry-safe replace BEFORE touching the
                    # live sidecars, not after. Round 2 caught the
                    # original order (delete sidecars, then copy) risking
                    # data loss if the copy raised; round 3 caught that
                    # round 2's fix (copy, delete sidecars, THEN replace)
                    # still had the identical risk one step later -- if
                    # `_replace_with_retry` itself failed (e.g. sustained
                    # Windows sharing violation past its retry budget)
                    # after the sidecar unlinks had already succeeded, the
                    # live WAL was gone with no replacement in place,
                    # reproduced live in round 3's review. Doing the
                    # replace FIRST means by the time sidecar cleanup
                    # happens, dest_file already holds the new, correct
                    # content -- a failure at THAT point can only leave a
                    # stale sidecar behind (loud ERROR below, matching the
                    # M6 bug's failure mode but now logged instead of
                    # silent), never lose data the restore was supposed to
                    # deliver.
                    tmp_restore = dest_file.with_name(
                        f".{dest_file.name}.restore_tmp_{os.getpid()}_"
                        f"{threading.get_ident()}"
                    )
                    try:
                        shutil.copy2(src_file, tmp_restore)
                        _replace_with_retry(str(tmp_restore), dest_file)
                    except Exception:
                        tmp_restore.unlink(missing_ok=True)
                        raise
                    # The restore itself has now succeeded -- dest_file
                    # holds the new content. Cleaning up stale sidecars
                    # from the OLD database is a correctness follow-up
                    # (leaving them risks the M6 bug the next time
                    # dest_file is opened), not something a failure here
                    # should be allowed to undo the restore over.
                    for suffix in ("-wal", "-shm"):
                        stale = dest_file.with_name(dest_file.name + suffix)
                        try:
                            stale.unlink(missing_ok=True)
                        except OSError as sidecar_exc:
                            _log.error(
                                "restore_data: restored %s but could not "
                                "remove its stale %s sidecar (%s) -- "
                                "delete it manually before this database "
                                "is next opened, or it may apply stale "
                                "WAL frames left over from the previous "
                                "database",
                                dest_file.name,
                                suffix,
                                sidecar_exc,
                            )
                else:
                    shutil.copy2(src_file, dest_file)
                copied += 1
                print(f"  Restored {src_file.name}")
            except Exception as exc:
                _log.warning("restore_data: failed to copy %s: %s", src_file.name, exc)

    if copied == 0:
        if attempted == 0:
            print("Backup folder exists but contains no data files.")
        else:
            # opus-review-round-3 L4: the old message here ("contains no
            # data files") was actively misleading when files WERE found
            # but every single one failed to restore -- it reads as "there
            # was nothing to restore" rather than "a restore was attempted
            # and failed", and gives no hint that live sidecars may have
            # been touched (see the ERROR log above, if any).
            print(
                f"Restore failed: found {attempted} file(s) in the backup "
                f"folder but none restored successfully -- see warnings "
                f"above."
            )
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
