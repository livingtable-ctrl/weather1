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


# ── backup_data() WAL-safety (AUD batch-25 item 1) ─────────────────────────


def _wal_db_with_uncheckpointed_row(db_path):
    """Same fixture shape as test_safe_io.py's -- a WAL-mode DB whose
    committed row has NOT been checkpointed out of the .db-wal sidecar.
    Returns the OPEN connection; caller must close it AFTER backing up
    (closing early auto-checkpoints and silently defeats the test)."""
    import sqlite3

    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, note TEXT)")
    con.commit()
    con.execute("INSERT INTO orders (note) VALUES ('committed row')")
    con.commit()
    wal_path = db_path.with_name(db_path.name + "-wal")
    assert wal_path.exists() and wal_path.stat().st_size > 0
    return con


def test_backup_data_includes_uncheckpointed_wal_row(tmp_path, monkeypatch):
    """End-to-end regression guard for the live-reproduced bug: backup_data()
    on a data_dir containing a WAL-mode .db with an uncheckpointed committed
    row must produce a backup copy that actually contains that row, and
    must return True.

    Mutation check: reverting cloud_backup.backup_data()'s `.db` branch back
    to a bare `shutil.copy2(src_file, dest_file)` makes this test fail --
    the backup copy comes back missing the "orders" table entirely (the
    literal "no such table: orders" this project reproduced live against
    the real data/predictions.db-wal).
    """
    import sqlite3

    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    (tmp_path / "sync").mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "execution_log.db"
    setup_con = _wal_db_with_uncheckpointed_row(db_path)
    try:
        import cloud_backup

        result = cloud_backup.backup_data(data_dir=data_dir)
    finally:
        setup_con.close()

    assert result is True

    backup_root = tmp_path / "sync" / "KalshiBot" / "data"
    subdirs = list(backup_root.iterdir())
    assert len(subdirs) == 1
    backup_file = subdirs[0] / "execution_log.db"
    assert backup_file.exists()

    con = sqlite3.connect(str(backup_file))
    rows = con.execute("SELECT note FROM orders").fetchall()
    con.close()
    assert rows == [("committed row",)]


def test_backup_data_returns_false_and_skips_unreadable_db_copy(tmp_path, monkeypatch):
    """If a .db file's backup copy fails its readability check, backup_data()
    returns False (item 1's "return value must reflect readability, not
    just that copy didn't raise") and doesn't count that file toward
    `copied` -- verified indirectly by the corrupt copy not being left
    behind in the destination.
    """
    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    (tmp_path / "sync").mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    bad_db = data_dir / "corrupt.db"
    bad_db.write_bytes(b"not a real sqlite database")

    import cloud_backup

    result = cloud_backup.backup_data(data_dir=data_dir)

    assert result is False
    backup_root = tmp_path / "sync" / "KalshiBot" / "data"
    subdirs = list(backup_root.iterdir())
    assert len(subdirs) == 1
    assert not (subdirs[0] / "corrupt.db").exists()


def test_backup_data_one_corrupt_db_does_not_block_other_files(tmp_path, monkeypatch):
    """A source .db that isn't a valid SQLite file at all makes
    backup_sqlite_db's own backup() call raise (not just fail the
    post-copy readability check) -- that must not abort the rest of the
    loop and silently skip every OTHER file in data_dir, which would
    include execution_log.db (the file item 2 of this batch exists to make
    sure gets backed up) sitting alongside an unrelated corrupt file.

    Mutation check: removing the per-file try/except in
    cloud_backup.backup_data()'s loop (reverting to letting a per-file
    exception propagate to the function-level try/except) makes this test
    fail -- execution_log.db and paper_trades.json would never get copied
    once corrupt.db's exception aborts the loop partway through.
    """
    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    (tmp_path / "sync").mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "corrupt.db").write_bytes(b"not a real sqlite database")
    (data_dir / "paper_trades.json").write_text('{"balance": 500.0}')

    import sqlite3

    good_db = data_dir / "execution_log.db"
    con = sqlite3.connect(str(good_db))
    con.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY)")
    con.execute("INSERT INTO orders DEFAULT VALUES")
    con.commit()
    con.close()

    import cloud_backup

    result = cloud_backup.backup_data(data_dir=data_dir)

    assert result is False  # corrupt.db still makes the overall result False
    backup_root = tmp_path / "sync" / "KalshiBot" / "data"
    subdirs = list(backup_root.iterdir())
    dest_dir = subdirs[0]
    # The good files alongside corrupt.db must still have been backed up.
    assert (dest_dir / "paper_trades.json").exists()
    assert (dest_dir / "execution_log.db").exists()
    con = sqlite3.connect(str(dest_dir / "execution_log.db"))
    assert con.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
    con.close()
    assert not (dest_dir / "corrupt.db").exists()


def test_backup_data_json_files_unaffected_by_wal_fix(tmp_path, monkeypatch):
    """.json files (paper_trades.json etc.) still use a plain copy -- the
    WAL-safety fix only changes the .db branch."""
    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    (tmp_path / "sync").mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "paper_trades.json").write_text('{"balance": 1000.0}')

    import cloud_backup

    result = cloud_backup.backup_data(data_dir=data_dir)

    assert result is True
    backup_root = tmp_path / "sync" / "KalshiBot" / "data"
    subdirs = list(backup_root.iterdir())
    backup_file = subdirs[0] / "paper_trades.json"
    assert backup_file.read_text() == '{"balance": 1000.0}'


def test_backup_data_skips_zero_table_db_without_warning_or_failure(
    tmp_path, monkeypatch, caplog
):
    """AUD batch-25 opus-review-round-2 M1: a vestigial 0-byte/zero-table
    .db source (this project's real data/ has 4: kalshi.db,
    paper_trades.db, tracker.db, trades.db) must be silently skipped, not
    treated as a backup failure -- there's nothing to back up. Reproduced
    live: once .db files started routing through backup_sqlite_db's
    table-existence check, all 4 real files failed it on every cron cycle
    forever, permanently flipping backup_data()'s return value to False
    and spamming 4 WARNINGs per run, burying the genuine failure this
    batch exists to surface.

    Mutation check: reverting the `_sqlite_source_is_empty` skip (routing
    a 0-byte file straight into backup_sqlite_db like any other .db) makes
    this test fail -- result flips to False and a WARNING is logged.
    """
    import logging

    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    (tmp_path / "sync").mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "kalshi.db").write_bytes(b"")  # 0 bytes, matches real file
    (data_dir / "paper_trades.json").write_text('{"balance": 1000.0}')

    import cloud_backup

    with caplog.at_level(logging.WARNING):
        result = cloud_backup.backup_data(data_dir=data_dir)

    assert result is True
    assert not any("kalshi.db" in r.message for r in caplog.records)

    backup_root = tmp_path / "sync" / "KalshiBot" / "data"
    subdirs = list(backup_root.iterdir())
    assert not (subdirs[0] / "kalshi.db").exists()
    assert (subdirs[0] / "paper_trades.json").exists()


def test_backup_data_still_fails_on_genuinely_corrupt_db(tmp_path, monkeypatch):
    """The M1 empty-source skip must NOT swallow a real corrupt/garbage
    .db file (non-empty bytes that aren't a valid SQLite DB at all) --
    that's still a real failure, distinct from "nothing to back up"."""
    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    (tmp_path / "sync").mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "corrupt.db").write_bytes(b"not a real sqlite database")

    import cloud_backup

    result = cloud_backup.backup_data(data_dir=data_dir)

    assert result is False
    backup_root = tmp_path / "sync" / "KalshiBot" / "data"
    subdirs = list(backup_root.iterdir())
    assert not (subdirs[0] / "corrupt.db").exists()


# ── restore_data() WAL-safety (AUD batch-25 opus-review M6) ────────────────


def test_restore_data_snapshot_includes_wal_sidecars(tmp_path, monkeypatch):
    """The pre-restore safety snapshot must include -wal/-shm sidecars, not
    exclude them -- the snapshot is the last-resort safety net taken
    immediately before overwriting live data, so a live .db with
    uncommitted-to-disk WAL content must not have that content silently
    missing from the one copy meant to make the restore reversible.

    opus-review-caught: an earlier version passed
    `ignore=shutil.ignore_patterns("*.shm", "*.wal")` here, apparently
    intending exactly this exclusion. Verified (via fnmatch, not just
    reading the code) that those globs never actually matched anything --
    SQLite names its sidecars "<dbname>.db-wal"/"<dbname>.db-shm" (hyphen
    before the suffix), so `fnmatch("predictions.db-wal", "*.wal")` is
    False. The exclusion was already inert; still removed as dead logic
    that falsely implies a protection that was never real.

    Mutation check: this test is written against a mutation that DOES
    actually match real filenames (`ignore_patterns("*-shm", "*-wal")`,
    correct globs) rather than against the original inert pattern, since
    the latter wouldn't discriminate at all -- confirmed by temporarily
    reintroducing the correct-glob version and re-running.
    """
    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()
    backup_dir = sync_dir / "KalshiBot" / "data" / "2026-08-20"
    backup_dir.mkdir(parents=True)
    (backup_dir / "predictions.db").write_bytes(b"fake backup db content")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "predictions.db").write_bytes(b"live db content")
    (data_dir / "predictions.db-wal").write_bytes(b"uncommitted wal content")
    (data_dir / "predictions.db-shm").write_bytes(b"shm content")

    import cloud_backup

    result = cloud_backup.restore_data(data_dir=data_dir, confirm=True)
    assert result is True

    snapshot_dirs = [
        p
        for p in data_dir.iterdir()
        if p.is_dir() and p.name.startswith(".pre_restore_")
    ]
    assert len(snapshot_dirs) == 1
    snapshot = snapshot_dirs[0]
    assert (snapshot / "predictions.db-wal").read_bytes() == b"uncommitted wal content"
    assert (snapshot / "predictions.db-shm").read_bytes() == b"shm content"


def test_restore_data_removes_stale_wal_sidecars_at_destination(tmp_path, monkeypatch):
    """Restoring a .db file over a live one must remove any -wal/-shm
    sidecar sitting at that destination path -- opus-review-caught: those
    sidecars belong to the OLD database being replaced. Left in place,
    they'd apply stale WAL frames (wrong page numbers/checksums for the
    new file underneath them) the moment anything next opens the restored
    file in WAL mode.

    Mutation check: removing the -wal/-shm cleanup block in restore_data()
    makes this test fail -- the stale sidecar survives the restore.
    """
    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()
    backup_dir = sync_dir / "KalshiBot" / "data" / "2026-08-20"
    backup_dir.mkdir(parents=True)
    (backup_dir / "predictions.db").write_bytes(b"restored db content")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "predictions.db").write_bytes(b"old live db content")
    (data_dir / "predictions.db-wal").write_bytes(b"stale wal from old db")
    (data_dir / "predictions.db-shm").write_bytes(b"stale shm from old db")

    import cloud_backup

    result = cloud_backup.restore_data(data_dir=data_dir, confirm=True)
    assert result is True

    assert (data_dir / "predictions.db").read_bytes() == b"restored db content"
    assert not (data_dir / "predictions.db-wal").exists()
    assert not (data_dir / "predictions.db-shm").exists()


def test_restore_data_leaves_live_db_and_sidecars_untouched_when_copy_fails(
    tmp_path, monkeypatch
):
    """AUD batch-25 opus-review-round-2 M3: if the copy step itself fails
    partway through, the live .db and its sidecars must be left
    completely untouched -- not left with stale sidecars deleted but no
    replacement copy in place (which would silently destroy the live
    DB's uncommitted WAL content with nothing to show for it, recoverable
    only via the pre-restore snapshot).

    Simulated by making shutil.copy2 raise -- the per-file `except
    Exception` in restore_data() swallows it into a warning and moves on,
    exactly matching a real Windows PermissionError (the bot holding
    predictions.db open) or a disk-full mid-copy.

    Mutation check: reverting restore_data() to delete the sidecars
    BEFORE copying (instead of copy-to-temp -> delete sidecars -> replace)
    makes this test fail -- the live sidecars get deleted even though the
    copy itself never succeeded.
    """
    import shutil

    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()
    backup_dir = sync_dir / "KalshiBot" / "data" / "2026-08-20"
    backup_dir.mkdir(parents=True)
    (backup_dir / "predictions.db").write_bytes(b"restored db content")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "predictions.db").write_bytes(b"old live db content")
    (data_dir / "predictions.db-wal").write_bytes(b"live uncommitted wal content")
    (data_dir / "predictions.db-shm").write_bytes(b"live shm content")

    real_copy2 = shutil.copy2

    def _flaky_copy2(src, dst, *a, **k):
        if ".restore_tmp_" in str(dst):
            raise OSError("simulated PermissionError: file in use")
        return real_copy2(src, dst, *a, **k)

    monkeypatch.setattr(shutil, "copy2", _flaky_copy2)

    import cloud_backup

    result = cloud_backup.restore_data(data_dir=data_dir, confirm=True)

    assert result is False  # copied == 0, nothing succeeded
    assert (data_dir / "predictions.db").read_bytes() == b"old live db content"
    assert (
        data_dir / "predictions.db-wal"
    ).read_bytes() == b"live uncommitted wal content"
    assert (data_dir / "predictions.db-shm").read_bytes() == b"live shm content"
    leftover_tmp = list(data_dir.glob("*.restore_tmp_*"))
    assert leftover_tmp == [], f"temp file(s) left behind: {leftover_tmp}"


def test_restore_data_does_not_destroy_wal_when_final_replace_fails(
    tmp_path, monkeypatch, caplog
):
    """AUD batch-25 opus-review-round-3 M-1: round 2's fix (copy to temp,
    delete sidecars, THEN replace) protected against a failed COPY but
    not a failed REPLACE -- if `_replace_with_retry` itself fails (e.g. a
    sustained Windows sharing violation past its retry budget) after the
    sidecar unlinks had already succeeded, the live WAL was destroyed
    with the OLD main .db file still in place and no replacement,
    reproduced live in round 3's review. Reordering to replace BEFORE
    sidecar cleanup means dest_file already holds the correct (new,
    restored) content by the time sidecar cleanup can fail -- a failure
    there can only leave a stale sidecar behind (logged loudly), never
    lose data the restore was supposed to deliver.

    Mutation check: reverting to delete-sidecars-then-replace (round 2's
    order) makes this test fail -- the live WAL content is gone and
    dest_file still holds the OLD content, not the restored one.
    """
    import logging

    import safe_io

    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()
    backup_dir = sync_dir / "KalshiBot" / "data" / "2026-08-20"
    backup_dir.mkdir(parents=True)
    (backup_dir / "predictions.db").write_bytes(b"restored db content")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "predictions.db").write_bytes(b"old live db content")
    (data_dir / "predictions.db-wal").write_bytes(b"live uncommitted wal content")
    (data_dir / "predictions.db-shm").write_bytes(b"live shm content")

    def _always_fail_replace(src, dst, deadline_secs=0.5):
        raise PermissionError("simulated sustained Windows sharing violation")

    monkeypatch.setattr(safe_io, "_replace_with_retry", _always_fail_replace)

    import cloud_backup

    with caplog.at_level(logging.WARNING):
        result = cloud_backup.restore_data(data_dir=data_dir, confirm=True)

    assert result is False
    # The restore did not complete, but the live WAL must still be
    # present -- NOT deleted before the replace that never happened.
    assert (
        data_dir / "predictions.db-wal"
    ).read_bytes() == b"live uncommitted wal content"
    assert (data_dir / "predictions.db-shm").read_bytes() == b"live shm content"
    leftover_tmp = list(data_dir.glob("*.restore_tmp_*"))
    assert leftover_tmp == [], f"temp file(s) left behind: {leftover_tmp}"
