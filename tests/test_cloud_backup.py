import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


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

    batch-86: the fixture now also carries a real, populated predictions.db
    alongside the vestigial file, mirroring the real data/ (4 zero-table
    files next to 2 live ones). Without it this test's data_dir had no
    backable database at all, which is the shape batch-86's snapshot check
    now reports as a failed backup -- so the added DB keeps this test
    pinned on its own claim (a vestigial source is skipped quietly and
    does not drag the run's result down) rather than on the unrelated
    empty-snapshot alarm, which has its own tests below.
    """
    import logging
    import sqlite3

    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    (tmp_path / "sync").mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # Zero bytes: SQLite treats it as a valid zero-table database, the
    # same property the real vestigial files have (they are 4096-byte
    # header-only files, also with zero tables).
    (data_dir / "kalshi.db").write_bytes(b"")
    (data_dir / "paper_trades.json").write_text('{"balance": 1000.0}')
    real_db = data_dir / "predictions.db"
    con = sqlite3.connect(str(real_db))
    con.execute("CREATE TABLE predictions (id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()

    import cloud_backup

    with caplog.at_level(logging.WARNING):
        result = cloud_backup.backup_data(data_dir=data_dir)

    assert result is True
    assert not any("kalshi.db" in r.message for r in caplog.records)

    backup_root = tmp_path / "sync" / "KalshiBot" / "data"
    subdirs = list(backup_root.iterdir())
    assert not (subdirs[0] / "kalshi.db").exists()
    assert (subdirs[0] / "paper_trades.json").exists()
    # Positive control for the absence-assertion above: the vestigial skip
    # must not have taken the live database with it, or "no kalshi.db
    # warning" would pass on a run that backed up no database at all.
    assert (subdirs[0] / "predictions.db").exists()


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


# ── batch-86 item 1: a snapshot with no database is not a restore point ────


def _zero_table_db(path):
    """A vestigial .db behaviourally identical to the 4 real ones in data/
    -- a valid, openable SQLite file with ZERO TABLES, which
    _sqlite_source_is_empty() skips at DEBUG.

    Zero bytes here; the real files are 4096 bytes (header-only), because
    _sqlite_source_is_empty opens sources read-write and SQLite grew them
    a page on first contact. Byte count is not the property under test --
    table count is, and it is 0 for both.
    """
    path.write_bytes(b"")


def _populated_db(path, table="predictions"):
    import sqlite3

    con = sqlite3.connect(str(path))
    con.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")  # noqa: S608
    con.execute(f"INSERT INTO {table} DEFAULT VALUES")  # noqa: S608
    con.commit()
    con.close()


def test_backup_data_reports_failure_when_snapshot_has_no_database(
    tmp_path, monkeypatch, caplog
):
    """The 2026-08-25 hole, reproduced.

    Measured live: <sync>/KalshiBot/data/2026-08-25 holds 100 .json files
    and zero .db, so a restore to that day is impossible -- and every run
    that produced it logged `synced 99 file(s)` at INFO and returned True.
    Of backup_data's three copy-loop paths that produce this shape, the two
    loud ones both log WARNING and neither appears anywhere in bot.log for
    that date; the third logs at DEBUG, which main.py's
    `root.setLevel(logging.INFO)` discards before any handler sees it. So
    the omission has to be reported from the OUTCOME, not from the branch.

    Mutation check: deleting the `if db_sources and not snapshot_dbs`
    block makes this test fail on both counts -- the result goes back to
    True and no WARNING is logged.
    """
    import logging

    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    (tmp_path / "sync").mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # The real data/ shape minus its two live databases.
    for name in ("kalshi.db", "paper_trades.db", "tracker.db", "trades.db"):
        _zero_table_db(data_dir / name)
    (data_dir / "paper_trades.json").write_text('{"balance": 1000.0}')

    import cloud_backup

    with caplog.at_level(logging.WARNING):
        result = cloud_backup.backup_data(data_dir=data_dir)

    assert result is False
    assert any("contains NO database" in r.message for r in caplog.records), [
        r.message for r in caplog.records
    ]

    backup_root = tmp_path / "sync" / "KalshiBot" / "data"
    dest = next(iter(backup_root.iterdir()))
    assert list(dest.glob("*.db")) == []
    # Positive control: the run did NOT abort early -- the non-database
    # files were copied normally. Without this, the assertions above would
    # also pass on a run that raised out of the loop on its first file,
    # which is a different failure with a different fix.
    assert (dest / "paper_trades.json").exists()


def test_backup_data_is_quiet_when_an_earlier_cycle_already_copied_the_database(
    tmp_path, monkeypatch, caplog
):
    """Snapshot dirs are date-named, so every cron cycle in a day writes
    into the SAME directory. A cycle that copies no database into a
    snapshot which already has one from an earlier cycle has not broken
    that snapshot, and must not raise the alarm.

    Mutation check: narrowing `snapshot_dbs` from what `dest` holds to
    what this run alone copied (verified by forcing it empty) makes this
    test fail -- every zero-table-only cycle after the first would report
    a failed backup and fire cron's operator alert, which is the batch-25
    noise regression in new clothes.
    """
    import logging
    from datetime import UTC, datetime

    # Frozen rather than read from the real clock: this test has to
    # pre-create the dated dir that backup_data will then write into, and
    # computing that name twice from datetime.now() is a real (if rare)
    # flake across UTC midnight (opus-review L6).
    frozen = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    _freeze_cloud_backup_clock(monkeypatch, frozen)
    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    (tmp_path / "sync").mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _zero_table_db(data_dir / "kalshi.db")
    (data_dir / "paper_trades.json").write_text('{"balance": 1000.0}')

    # An earlier cycle today already put a database in the snapshot.
    dest = tmp_path / "sync" / "KalshiBot" / "data" / frozen.strftime("%Y-%m-%d")
    dest.mkdir(parents=True)
    _populated_db(dest / "predictions.db")

    import cloud_backup

    with caplog.at_level(logging.WARNING):
        result = cloud_backup.backup_data(data_dir=data_dir)

    assert result is True
    assert not any("contains NO database" in r.message for r in caplog.records)
    # Positive controls: this cycle really did run into that same snapshot
    # dir (so the absence-assertion is not passing on a run that wrote
    # somewhere else), and the earlier cycle's database is still there.
    assert (dest / "paper_trades.json").exists()
    assert (dest / "predictions.db").exists()


def test_backup_data_does_not_alarm_when_the_source_has_no_database_at_all(
    tmp_path, monkeypatch, caplog
):
    """The gate is `db_sources and not snapshot_dbs`. A data_dir with no
    .db files anywhere is not a broken backup -- there was never anything
    to omit -- and several existing tests use exactly that fixture.

    Mutation check: dropping the `db_sources and` half makes this test
    fail (result flips to False, alarm fires) while every other test in
    this section still passes.
    """
    import logging

    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    (tmp_path / "sync").mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "paper_trades.json").write_text('{"balance": 1000.0}')

    import cloud_backup

    with caplog.at_level(logging.WARNING):
        result = cloud_backup.backup_data(data_dir=data_dir)

    assert result is True
    assert not any("contains NO database" in r.message for r in caplog.records)
    backup_root = tmp_path / "sync" / "KalshiBot" / "data"
    dest = next(iter(backup_root.iterdir()))
    # Positive control: the run happened at all.
    assert (dest / "paper_trades.json").exists()


def test_backup_data_info_line_names_the_databases_that_landed(
    tmp_path, monkeypatch, caplog
):
    """`synced N file(s)` on its own is what let the 2026-08-25 hole read
    as a success in the log for a full day. The INFO line names the
    databases the snapshot ends up holding so the omission is legible
    without reproducing it.

    Mutation check: reverting the INFO line to the bare
    `synced %d file(s) to %s` makes this test fail.
    """
    import logging

    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    (tmp_path / "sync").mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _populated_db(data_dir / "predictions.db")
    _populated_db(data_dir / "execution_log.db", table="orders")
    _zero_table_db(data_dir / "kalshi.db")

    import cloud_backup

    with caplog.at_level(logging.INFO):
        result = cloud_backup.backup_data(data_dir=data_dir)

    assert result is True
    synced = [r.getMessage() for r in caplog.records if "synced" in r.getMessage()]
    assert len(synced) == 1, synced
    assert "2 database(s): execution_log.db, predictions.db" in synced[0]
    # The zero-table sources are named too, in their own clause. Without
    # this a primary database that had quietly become zero-table -- a
    # truncated execution_log.db, say -- would leave no trace anywhere,
    # since the per-file skip logs at DEBUG and DEBUG is discarded in
    # production (opus-review L1).
    assert "1 source(s) skipped as empty: kalshi.db" in synced[0]
    # ...but it is NOT counted among the databases the snapshot holds.
    assert "2 database(s): execution_log.db, predictions.db;" in synced[0]


def test_backup_data_reports_a_single_non_empty_database_that_did_not_land(
    tmp_path, monkeypatch, caplog
):
    """opus-review L1: "the snapshot has at least one .db" is weaker than
    "every database that should have landed did".

    The total-absence check alone stays quiet when predictions.db copies
    fine and execution_log.db -- the live-order ledger -- does not. Both
    loud copy-failure paths do warn per file, so this catches the
    remainder: a copy that reported success and left nothing behind, or a
    destination file removed underneath the run.

    Mutation check: deleting the `if snapshot_known and missing:` block
    makes this test fail while every other test in this section stays
    green (the total-absence check cannot see this case -- the snapshot
    does hold a database).
    """
    import logging

    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    (tmp_path / "sync").mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _populated_db(data_dir / "predictions.db")
    _populated_db(data_dir / "execution_log.db", table="orders")

    import cloud_backup
    import safe_io

    real_backup = safe_io.backup_sqlite_db

    def _lose_the_ledger(src, dst):
        """Copies, then loses the file -- a success report with nothing
        behind it, which is precisely the shape neither WARNING path
        covers."""
        ok = real_backup(src, dst)
        if src.name == "execution_log.db":
            dst.unlink(missing_ok=True)
        return ok

    with (
        patch.object(safe_io, "backup_sqlite_db", _lose_the_ledger),
        caplog.at_level(logging.WARNING),
    ):
        result = cloud_backup.backup_data(data_dir=data_dir)

    assert result is False
    assert any(
        "missing database(s)" in r.message and "execution_log.db" in r.message
        for r in caplog.records
    ), [r.message for r in caplog.records]
    # Positive control: the OTHER database did land, so this is a
    # per-database complaint and not the total-absence alarm firing.
    backup_root = tmp_path / "sync" / "KalshiBot" / "data"
    dest = next(iter(backup_root.iterdir()))
    assert (dest / "predictions.db").exists()
    assert not any("contains NO database" in r.message for r in caplog.records)


def test_backup_data_does_not_alarm_when_the_destination_cannot_be_enumerated(
    tmp_path, monkeypatch, caplog
):
    """opus-review L7: `dest.glob` can raise OSError on a cloud-sync
    folder that is offline or locked. Unguarded, that escaped to the
    function-level handler -- returning False for a run whose copies all
    succeeded AND skipping the prune loop entirely, the same shape
    batch-33 M-21 LOW(a) fixed for rmtree.

    An unreadable destination is "unknown", not "empty".

    Mutation check: removing the try/except around the glob makes this
    test fail on both the return value and the surviving old directory.
    """
    import logging
    from datetime import UTC, datetime

    _freeze_cloud_backup_clock(monkeypatch, datetime(2026, 8, 26, 12, 0, tzinfo=UTC))
    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    (tmp_path / "sync").mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _populated_db(data_dir / "predictions.db")

    backup_root = tmp_path / "sync" / "KalshiBot" / "data"
    backup_root.mkdir(parents=True)
    doomed = backup_root / "2026-08-05"  # 21 days old, a Wednesday
    doomed.mkdir()

    import cloud_backup

    real_glob = Path.glob

    def _glob(self, pattern, *a, **kw):
        if pattern == "*.db":
            raise OSError("the cloud file provider is not running")
        return real_glob(self, pattern, *a, **kw)

    with patch.object(Path, "glob", _glob), caplog.at_level(logging.WARNING):
        result = cloud_backup.backup_data(data_dir=data_dir)

    # No missing-database claim either way, and the copies succeeded.
    assert result is True
    assert not any("contains NO database" in r.message for r in caplog.records)
    assert not any("missing database(s)" in r.message for r in caplog.records)
    assert any("could not enumerate" in r.message for r in caplog.records), [
        r.message for r in caplog.records
    ]
    # Positive control, and the point of the guard: retention still ran.
    assert not doomed.exists(), "an unreadable destination must not stop pruning"


# ── batch-86 item 1: tiered snapshot retention ─────────────────────────────


def _freeze_cloud_backup_clock(monkeypatch, when):
    """Pin cloud_backup's `datetime` to `when` (an aware UTC datetime).

    A real datetime subclass rather than a Mock because the code calls
    `.astimezone()`, `.date()` and `.strftime()` on the result and a Mock
    would both break those and silently ignore the tz argument. It does
    NOT pin the UTC-vs-local property of the prune comparison (batch-33
    M-21 LOW(a)): the pruner's `date` comes from a function-local
    `from datetime import date`, which resolves through sys.modules and is
    untouched by patching this module attribute. That property is pinned
    instead by tests/test_date_today_guard.py, whose allowlist is empty
    and which fails on any date.today() in production code.
    """
    from datetime import datetime as _real_datetime

    import cloud_backup

    class _Frozen(_real_datetime):
        @classmethod
        def now(cls, tz=None):
            return when.astimezone(tz) if tz is not None else when.replace(tzinfo=None)

    monkeypatch.setattr(cloud_backup, "datetime", _Frozen)


def test_snapshot_retention_is_tiered_daily_then_weekly(tmp_path, monkeypatch):
    """batch-86 item 1: the retention SHAPE is the decision this item made.

    Previously a flat 30 days of daily full uncompressed copies -- 31
    snapshots, ~2.0 GB at the measured 65.3 MB/day. Now every day for a
    week, then one per week (SUNDAY -- the last snapshot before cron's
    Monday sweep deletes rows) out to 90 days: 19-20 snapshots, and a 3x
    longer horizon.

    Every boundary is pinned in one place because they are only
    meaningfully testable against each other -- a policy that keeps the
    Sunday at day 10 but also keeps its Monday neighbour is not a weekly
    tier at all. The 90-day horizon boundary itself needs a different
    "today" to land a keeper on exactly 90/91 and has its own test below.

    Mutation checks, each individually verified:
      - `_KEEP_DAILY_DAYS = 7` -> `< 7` (or `= 6`/`= 8`): the day-7
        boundary dir flips.
      - dropping the weekly-tier `continue`: 2026-08-16 and 2026-05-31 are
        pruned (i.e. it degrades to a flat 7-day window).
      - dropping `dir_date.weekday() == _WEEKLY_KEEP_WEEKDAY`: the Monday
        and Tuesday neighbours survive, so the weekly tier is really a
        flat 90 days.
      - `_WEEKLY_KEEP_WEEKDAY = 6` -> any other weekday: two failures.
      - `_KEEP_WEEKLY_DAYS = 90` -> `= 85`: the day-87 Sunday is pruned.
        (`= 365` is NOT a sufficient mutation here -- see the horizon test
        below for why, and for the 87..92 band this table cannot see.)
    """
    from datetime import UTC, datetime

    import cloud_backup

    # A Wednesday, so "today" is itself outside the weekly-keeper weekday.
    _freeze_cloud_backup_clock(monkeypatch, datetime(2026, 8, 26, 12, 0, tzinfo=UTC))
    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    (tmp_path / "sync").mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "x.json").write_text("{}")

    backup_root = tmp_path / "sync" / "KalshiBot" / "data"
    backup_root.mkdir(parents=True)

    # name -> (age in days, weekday, expected to survive)
    cases = {
        "2026-08-19": (7, "Wed", True),  # daily-tier boundary
        "2026-08-18": (8, "Tue", False),  # first day past it, not a Sunday
        "2026-08-17": (9, "Mon", False),  # post-sweep day is NOT the keeper
        "2026-08-16": (10, "Sun", True),  # weekly tier
        "2026-06-02": (85, "Tue", False),  # inside 90d but not a Sunday
        "2026-06-01": (86, "Mon", False),  # ditto, and the sweep day
        "2026-05-31": (87, "Sun", True),  # weekly tier, near the horizon
        "2026-05-24": (94, "Sun", False),  # past the horizon
        "not-a-date": (0, "n/a", True),  # unparseable -> never touched
    }
    for name in cases:
        (backup_root / name).mkdir()
        (backup_root / name / "marker.json").write_text("{}")

    cloud_backup.backup_data(data_dir=data_dir)

    survived = {d.name for d in backup_root.iterdir() if d.is_dir()}
    expected = {name for name, (_a, _w, keep) in cases.items() if keep}
    # Today's own snapshot is created by the run itself.
    expected.add("2026-08-26")
    assert survived == expected, (
        f"unexpectedly pruned: {sorted(expected - survived)}; "
        f"unexpectedly kept: {sorted(survived - expected)}"
    )


def test_snapshot_retention_horizon_boundary_is_exactly_90_days(tmp_path, monkeypatch):
    """The `<= _KEEP_WEEKLY_DAYS` comparison itself.

    opus-review M1: weekly keepers are 7 days apart, so the table above --
    frozen on a Wednesday -- has its oldest survivor at age 87 and its
    oldest casualty at 94, leaving the whole 88..93 band untested.
    Empirically demonstrated in review: with that table as the only
    coverage, _KEEP_WEEKLY_DAYS could be retyped as anything from 87 to 93
    (including `<=` mutated to `<`) and the suite stayed green.

    Landing a keeper on exactly 90 needs a different "today": a Sunday
    is 90 days before a Saturday and 91 days before the next Sunday, so
    freezing on each in turn pins both sides of the boundary.

    Mutation checks: `<= _KEEP_WEEKLY_DAYS` -> `<` fails the first case;
    `_KEEP_WEEKLY_DAYS = 91` fails the second. Both verified.
    """
    from datetime import UTC, datetime

    import cloud_backup

    # (frozen today, weekday of it, age of 2026-05-31, must survive)
    for today, _weekday, _age, must_survive in (
        (datetime(2026, 8, 29, 12, 0, tzinfo=UTC), "Sat", 90, True),
        (datetime(2026, 8, 30, 12, 0, tzinfo=UTC), "Sun", 91, False),
    ):
        _freeze_cloud_backup_clock(monkeypatch, today)
        sync = tmp_path / f"sync{_age}"
        sync.mkdir()
        monkeypatch.setenv("CLOUD_BACKUP_PATH", str(sync))

        data_dir = tmp_path / f"data{_age}"
        data_dir.mkdir()
        (data_dir / "x.json").write_text("{}")

        backup_root = sync / "KalshiBot" / "data"
        backup_root.mkdir(parents=True)
        keeper = backup_root / "2026-05-31"  # a Sunday
        keeper.mkdir()

        cloud_backup.backup_data(data_dir=data_dir)

        assert keeper.exists() is must_survive, (
            f"a Sunday snapshot {_age} days old on a {_weekday}: "
            f"expected survive={must_survive}"
        )
        # Positive control: the run reached snapshot creation, so the
        # assertion above is about the prune decision and not about
        # backup_data having quietly done nothing.
        assert (backup_root / today.strftime("%Y-%m-%d")).exists()


def test_snapshot_retention_horizon_is_longer_than_the_flat_window_it_replaced(
    tmp_path, monkeypatch
):
    """The tier trades density for reach: a snapshot 59 days old survives
    now and did not under the flat 30-day window. Pinned separately so a
    future "simplify" back to a single cutoff cannot pass by satisfying
    only the pruning half of the table above.
    """
    from datetime import UTC, datetime

    import cloud_backup

    _freeze_cloud_backup_clock(monkeypatch, datetime(2026, 8, 26, 12, 0, tzinfo=UTC))
    monkeypatch.setenv("CLOUD_BACKUP_PATH", str(tmp_path / "sync"))
    (tmp_path / "sync").mkdir()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "x.json").write_text("{}")

    backup_root = tmp_path / "sync" / "KalshiBot" / "data"
    backup_root.mkdir(parents=True)
    old_sunday = backup_root / "2026-06-28"  # 59 days old, a Sunday
    old_sunday.mkdir()
    # opus-review M2: without these two controls this test passed even
    # when backup_data was forced into a total no-op (_find_sync_folder
    # returning None) -- it was the ONLY new test that did. An
    # "it still exists" assertion proves nothing unless the pruner
    # demonstrably ran and demonstrably still prunes something.
    doomed = backup_root / "2026-08-05"  # 21 days old, a Wednesday
    doomed.mkdir()

    cloud_backup.backup_data(data_dir=data_dir)

    assert old_sunday.exists(), "a 59-day-old Sunday must outlive the old 30d window"
    assert (backup_root / "2026-08-26").exists(), "the run never created a snapshot"
    assert not doomed.exists(), "the prune loop never ran"


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
