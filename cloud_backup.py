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

# Retention for the date-named snapshot directories under
# <sync_folder>/KalshiBot/data/. batch-86 item 1: the previous policy was a
# flat 30 days of daily FULL, uncompressed copies. Measured 2026-08-26, a
# snapshot is 65.3 MB (predictions.db alone is 50.6 MB and is re-copied
# whole every cron cycle), so that policy projects to 31 copies / ~2.0 GB
# in the operator's OneDrive -- and it silently multiplies the cost of
# every per-table retention decision made elsewhere (batch-78 set 730 days
# for ensemble_member_values and 30 for orderbook_depth_snapshots without
# that multiplier in view) by the number of snapshots retained.
#
# Tiered instead: every day for the last week, then one snapshot per week
# out to 90 days. Steady state is 19-20 snapshots (8 in the daily tier,
# ages 0-7, plus 11 or 12 weekly keepers across the 83-day span) -- about
# 1.3 GB, and the horizon triples. Cheaper and longer-reaching, but not
# free: between 8 and 30 days old there are now ~3 restore points where the
# flat window kept 23. Daily granularity past one week is what was traded
# away.
#
# SUNDAY is the weekly keeper, not Monday. cron's weekly DB retention sweep
# fires on UTC Monday and DELETES rows (purge_old_predictions,
# prune_api_requests, prune_old_analysis_attempts, ...). Snapshot dirs
# accumulate across a day, so a Monday snapshot is the post-sweep state --
# the one snapshot of the week that has already lost those rows. Sunday's
# is the last one before each sweep, so it still holds them. Identical
# cost, strictly more recoverable. (An earlier revision of this change kept
# Monday "to align with the sweep", which is exactly backwards; caught in
# review.)
_KEEP_DAILY_DAYS = 7
_KEEP_WEEKLY_DAYS = 90
_WEEKLY_KEEP_WEEKDAY = 6  # Sunday -- the last snapshot BEFORE Monday's sweep


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
    db_sources = 0
    db_expected: list[str] = []  # non-empty .db sources that SHOULD land
    db_skipped_empty: list[str] = []  # zero-table sources, skipped
    try:
        for src_file in data_dir.iterdir():
            if src_file.is_file() and src_file.suffix in _BACKUP_EXTENSIONS:
                if src_file.name in _SKIP_NAMES:
                    continue
                dest_file = dest / src_file.name
                try:
                    if src_file.suffix == ".db":
                        db_sources += 1
                        if _sqlite_source_is_empty(src_file):
                            # Recorded as well as logged: this DEBUG line
                            # is discarded in production (main.py sets the
                            # root logger to INFO), which is how the
                            # 2026-08-25 snapshot lost both databases with
                            # no trace. The names go into the INFO summary
                            # below instead, where a primary database
                            # having quietly become zero-table -- e.g. a
                            # truncated execution_log.db -- is legible
                            # without reintroducing batch-25's four
                            # WARNINGs per cycle.
                            db_skipped_empty.append(src_file.name)
                            _log.debug(
                                "cloud_backup: skipping %s -- no tables "
                                "(nothing to back up)",
                                src_file.name,
                            )
                            continue
                        db_expected.append(src_file.name)
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

        # batch-86 item 1: a snapshot with no database in it is not a
        # restore point, and until now nothing said so. Measured live on
        # 2026-08-26: <sync>/KalshiBot/data/2026-08-25 holds 100 .json
        # files and ZERO .db, so a restore to that day is impossible --
        # snapshot dirs are date-named and only ever rewritten within
        # their own day, so it is a permanent hole, not a transient race.
        # Every run that produced it logged `synced 99 file(s)` at INFO
        # and returned True.
        #
        # Of the three copy-loop paths that produce this shape, the two
        # loud ones (backup_sqlite_db's post-copy readability check, and
        # the per-file `except`) both log WARNING and neither appears
        # anywhere in bot.log for that date -- so it was the third, the
        # `_sqlite_source_is_empty` skip, which logs at DEBUG. main.py
        # sets the ROOT logger to INFO, so that record is discarded before
        # it reaches any handler: the skip is invisible in production by
        # construction, and no combination of per-file logging fixes that
        # on its own.
        #
        # So report the OUTCOME rather than trusting any single branch to
        # announce itself. `dest` is checked (not just this run's copies)
        # because the snapshot dir accumulates across the day's cron
        # cycles -- a database copied by an earlier cycle still makes the
        # snapshot restorable, and must not raise a false alarm.
        #
        # The enumeration itself is guarded: `dest` is a cloud-sync folder
        # and glob can raise OSError when OneDrive is offline or holding a
        # lock. Unguarded that would escape to the function-level handler,
        # returning False for a run whose copies all succeeded AND skipping
        # the prune loop entirely -- the same shape batch-33 M-21 LOW(a)
        # fixed for rmtree. An unreadable destination is "unknown", not
        # "empty": log it and make no claim either way.
        #
        # The `p.is_file()` filter carries one unverified assumption: a
        # OneDrive Files-On-Demand placeholder (a dehydrated 50 MB
        # predictions.db) is expected to stat normally without triggering
        # a recall, so is_file() should stay True. That was NOT confirmed
        # live. If it ever returned False for a dehydrated file, this
        # would false-alarm on a perfectly good snapshot -- one WARNING
        # and a False return per cycle, throttled by cron's 6-hour alert
        # cooldown, not data loss. Worth checking if that alert ever fires
        # against a snapshot that visibly does contain databases.
        try:
            snapshot_dbs = sorted(p.name for p in dest.glob("*.db") if p.is_file())
            snapshot_known = True
        except OSError as _glob_exc:
            snapshot_dbs = []
            snapshot_known = False
            _log.warning(
                "cloud_backup: could not enumerate %s to confirm the "
                "snapshot's databases (%s) -- not treating that as a "
                "missing-database failure",
                dest,
                _glob_exc,
            )
        _log.info(
            "cloud_backup: synced %d file(s) to %s -- snapshot holds %d "
            "database(s): %s%s",
            copied,
            dest,
            len(snapshot_dbs),
            ", ".join(snapshot_dbs) or ("UNKNOWN" if not snapshot_known else "NONE"),
            (
                f"; {len(db_skipped_empty)} source(s) skipped as empty: "
                + ", ".join(sorted(db_skipped_empty))
                if db_skipped_empty
                else ""
            ),
        )
        # A non-empty source that did not reach the snapshot. The two loud
        # copy-failure paths already warn per file, so in practice this
        # catches the shapes they do not: a copy that reported success but
        # left nothing behind, or a destination file removed under us.
        # Zero-table sources are excluded by construction (they never enter
        # db_expected), so the 4 vestigial files stay silent.
        missing = sorted(set(db_expected) - set(snapshot_dbs))
        if snapshot_known and missing:
            _log.warning(
                "cloud_backup: snapshot %s is missing database(s) that were "
                "present and non-empty in %s: %s",
                today_str,
                data_dir,
                ", ".join(missing),
            )
            all_readable = False
        # Total absence is kept as its own check rather than folded into
        # `missing`, because it is the one the 2026-08-25 snapshot would
        # have tripped: every .db source was zero-table, so db_expected was
        # EMPTY and nothing was "missing" -- yet the snapshot had no
        # database in it and was not a restore point.
        #
        # Alert-spam check (this bool is the only input to cron.py's
        # send_system_alert, cooldown_key="cloud_backup_failed"): that
        # cooldown is disk-persisted at 6 hours, so the worst case is 4
        # alerts/day rather than one per cycle. The only configuration that
        # sustains it is a data_dir whose .db files are ALL zero-table --
        # no .db is tracked in git, so a fresh clone has db_sources == 0
        # and stays quiet until a real database appears. Accepted.
        if db_sources and snapshot_known and not snapshot_dbs:
            # Gated on db_sources so a data_dir that legitimately has no
            # .db at all (several tests, and any JSON-only deployment) is
            # not reported as a failed backup. Any .db source counts,
            # including the 4 vestigial zero-table files -- gating on
            # "the source had a NON-EMPTY .db" instead would have stayed
            # silent for the exact 2026-08-25 shape, since the whole point
            # is that backup_data saw nothing worth copying.
            _log.warning(
                "cloud_backup: snapshot %s contains NO database -- %d .db "
                "source file(s) were present in %s but none was backed up "
                "(zero-table sources are skipped at DEBUG). This snapshot "
                "is not a usable restore point",
                today_str,
                db_sources,
                data_dir,
            )
            all_readable = False

        # Prune backup directories: keep every day for the last
        # _KEEP_DAILY_DAYS, then one per week out to _KEEP_WEEKLY_DAYS.
        # See those constants for the measurement behind the shape.
        #
        # batch-33 M-21 LOW(a): directory names are stamped with
        # datetime.now(UTC) (`today_str` above) but this compared them
        # against date.today() -- LOCAL system time. Near local midnight
        # (either side of UTC midnight, depending on timezone) that
        # mismatch makes today's own just-created directory look 1 day
        # old, or lets a 30-day-old directory look fresh for up to another
        # day, purely from the local/UTC gap. Compare UTC-to-UTC instead.
        backup_root = sync_root / "KalshiBot" / "data"
        _today_utc = datetime.now(UTC).date()
        # Materialised with list() before deleting: the loop rmtree's
        # entries out of the very directory it is scanning, and the tiered
        # policy removes several times more per pass than the flat window
        # did. Free insurance against a mid-iteration os.scandir surprise.
        for old_dir in list(backup_root.iterdir()):
            # Non-directories are skipped DELIBERATELY, not as an oversight.
            # Before the dated-folder scheme, backup_data wrote files straight
            # into <sync>/KalshiBot/data/ and those flat copies are still
            # there -- measured 2026-08-27: 35 files, 19.9 MB, dominated by a
            # 16.2 MB predictions.db from 2026-05-01. They are stale by four
            # months and nothing has ever aged them out.
            #
            # They stay because restore_data's `src = backup_root` fallback
            # reads them: they are the last-resort restore path when no dated
            # directory exists. 19.9 MB is not worth trading that for, and a
            # prune loop that deletes individual FILES from the backup root
            # is a materially more dangerous loop to get wrong than one that
            # only ever removes whole dated directories.
            #
            # Consequence worth knowing when reading retention numbers: every
            # retention figure in this module counts dated DIRECTORIES, and
            # these files are in none of them.
            if not old_dir.is_dir():
                continue
            try:
                from datetime import date

                dir_date = date.fromisoformat(old_dir.name)
            except ValueError:
                # Not parseable as a date -- left alone. Note 3.11+
                # fromisoformat also accepts basic ISO ("20260817"), so a
                # directory named that way is treated as dated; nothing
                # here creates such names, and keeping one is harmless.
                continue
            _age_days = (_today_utc - dir_date).days
            # Daily tier. A future-dated directory (clock skew) has a
            # negative age and lands here too, exactly as it did under the
            # old flat window.
            if _age_days <= _KEEP_DAILY_DAYS:
                continue
            # Weekly tier: one keeper per week out to the horizon.
            if (
                _age_days <= _KEEP_WEEKLY_DAYS
                and dir_date.weekday() == _WEEKLY_KEEP_WEEKDAY
            ):
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


def restore_data(
    data_dir: Path | None = None,
    confirm: bool = False,
    allow_missing_db: bool = False,
) -> bool:
    """
    Copy files from <sync_folder>/KalshiBot/data/ back into local data/.
    Use this on a new PC after cloning the repo.

    confirm=True is required to prevent accidental overwrites of live files.
    Returns True on success, False if nothing to restore.

    allow_missing_db=True proceeds even when the selected snapshot contains
    no .db file at all. Without it such a snapshot is REFUSED, because
    batch-86 proved that shape really occurs (the live 2026-08-25 snapshot
    holds 100 files and zero databases, and is still sitting in the backup
    root) and the old behaviour was to restore its JSON, print "N file(s)
    restored", and return True -- telling an operator mid-incident that a
    restore succeeded when predictions.db and execution_log.db were never
    in it. Appended last and defaulted so no existing keyword caller
    changes meaning; every call site in the repo passes by keyword anyway.
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

    # Guarded for the same reason as the database check below: this walks a
    # cloud-synced tree that can return a transient OSError. Unguarded, an
    # unreadable backup root crashed restore_data with a traceback instead
    # of the "no backup found" it already knows how to report two lines up.
    # Found by a test written for the refusal path, which patched iterdir
    # globally and tripped this one first.
    try:
        date_dirs = sorted(
            (d for d in backup_root.iterdir() if d.is_dir()),
            key=lambda d: d.name,
            reverse=True,
        )
    except OSError as _list_exc:
        print(f"Could not list {backup_root}: {_list_exc}")
        print("Nothing was restored — re-run once the sync folder is readable.")
        return False
    src = next((d for d in date_dirs if d.name[:4].isdigit()), None)
    if src is None:
        # Fall back to backup_root itself for pre-rotation backups
        src = backup_root

    # Refuse a database-less snapshot. The selection above sorts by NAME and
    # takes the newest without looking inside, so a snapshot that holds only
    # .json files is chosen exactly like a complete one -- and the operator
    # reaching for a restore is, by definition, already having a bad day.
    #
    # Fails OPEN on an enumeration error rather than closed: refusing on a
    # bare OSError would turn "I could not read the directory" into the
    # accusation "this snapshot has no database", which is a different and
    # much stronger claim. OneDrive can hand back a transient error for a
    # dehydrated file; see backup_data's own glob for the same reasoning.
    #
    # Deliberately NO is_file() filter, and _has_db below matches it.
    # backup_data's own comment records as UNVERIFIED the assumption that a
    # OneDrive Files-On-Demand dehydrated placeholder still reports
    # is_file() == True. On the BACKUP side a wrong answer there costs one
    # warning; HERE it would block a recovery outright, print the false line
    # "none of them .db", and then suggest a different snapshot that fails
    # the same way. A name match on *.db is sufficient evidence that a
    # snapshot is not empty of databases, and erring toward allowing the
    # restore is the right direction for a guard that fails open everywhere
    # else in this block.
    try:
        _snapshot_dbs = sorted(p.name for p in src.glob("*.db"))
        _enumerated = True
    except OSError as _glob_exc:
        _snapshot_dbs, _enumerated = [], False
        print(f"  Could not enumerate {src} to check for databases ({_glob_exc});")
        print("  proceeding — an unreadable directory is not proof of an empty one.")

    if _enumerated and not _snapshot_dbs and not allow_missing_db:
        # Everything below only DESCRIBES a refusal that is already decided,
        # so each lookup degrades to "unknown" instead of raising. Both walk
        # the same cloud-synced tree whose unreadability this function
        # already treats as non-fatal above -- and an OSError escaping here
        # would replace a clear refusal with a traceback on the one code
        # path an operator reaches mid-incident.
        try:
            _others: int | None = sum(1 for p in src.iterdir() if p.is_file())
        except OSError:
            _others = None
        print(f"\n  REFUSING TO RESTORE — {src.name} contains no database.")
        if _others is None:
            print("  Its contents could not be listed, but it holds no .db.")
        else:
            print(f"  It holds {_others} file(s), none of them .db.")
        print("  Restoring it would copy JSON over your local data/ and report")
        print("  success, while predictions.db and execution_log.db stayed as")
        print("  they are. That is not a restore.")

        def _has_db(d: Path) -> bool:
            try:
                return any(d.glob("*.db"))
            except OSError:
                # Unreadable, so unknown -- excluded from the "try this one
                # instead" suggestion rather than recommended blind.
                return False

        _complete = [d for d in date_dirs if d.name[:4].isdigit() and _has_db(d)]
        if _complete:
            print(f"\n  Newest snapshot that DOES hold a database: {_complete[0].name}")
            print("  Move or rename the empty one to select it, or re-run")
            print("  `py main.py restore --allow-missing-db` to take the JSON")
            print("  from this one anyway.")
        else:
            print("\n  No dated snapshot here holds a database at all.")
        # Log it too. Every other operator-visible failure in this module
        # logs, and a refused restore that leaves no trace in bot.log is
        # gone the moment the terminal scrolls -- in the module whose own
        # comments keep pointing readers at bot.log.
        _log.warning(
            "restore_data: REFUSED %s — snapshot contains no database "
            "(re-run with --allow-missing-db to override)",
            src.name,
        )
        return False

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
