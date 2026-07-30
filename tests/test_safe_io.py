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


def test_save_writes_checksum_field(tmp_path, monkeypatch):
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    paper._save({"balance": 1000.0, "trades": []})
    stored = json.loads((tmp_path / "paper_trades.json").read_bytes())
    assert "_checksum" in stored
    # P1-5: new writes must use full 64-char SHA-256 hex
    assert len(stored["_checksum"]) == 64


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
        "crc32" in r.message.lower()
        or "sha-256" in r.message.lower()
        or checksum in r.message
        for r in caplog.records
    )


# ── P1-5: _validate_checksum constant-time comparison ─────────────────────────


def test_validate_checksum_passes_on_valid_64char(tmp_path, monkeypatch):
    """P1-5: valid 64-char checksum must pass validation."""
    import paper

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    paper._save({"balance": 500.0, "trades": []})
    data = json.loads((tmp_path / "paper_trades.json").read_bytes())
    paper._validate_checksum(data)  # must not raise


def test_validate_checksum_rejects_empty_string(tmp_path):
    """P1-5: empty checksum string must raise CorruptionError (was silently passing)."""
    from paper import CorruptionError, _validate_checksum

    data = {"balance": 500.0, "trades": [], "_checksum": ""}
    with pytest.raises(CorruptionError, match="length"):
        _validate_checksum(data)


def test_validate_checksum_rejects_one_char(tmp_path):
    """P1-5: 1-char checksum must raise CorruptionError (was passing 1/16 of corruptions)."""
    from paper import CorruptionError, _validate_checksum

    data = {"balance": 500.0, "trades": [], "_checksum": "a"}
    with pytest.raises(CorruptionError, match="length"):
        _validate_checksum(data)


def test_validate_checksum_rejects_mismatch(tmp_path):
    """P1-5: tampered data must raise CorruptionError."""
    from paper import CorruptionError, _validate_checksum

    data = {"balance": 500.0, "trades": [], "_checksum": "a" * 64}
    with pytest.raises(CorruptionError, match="mismatch"):
        _validate_checksum(data)


def test_validate_checksum_accepts_legacy_16char(tmp_path, monkeypatch):
    """P1-5: 16-char checksums (prior format) must still pass validation."""
    import hashlib

    from paper import _validate_checksum

    payload = {"balance": 500.0, "trades": []}
    body = json.dumps(payload, indent=2, sort_keys=True, default=str).encode()
    checksum_16 = hashlib.sha256(body).hexdigest()[:16]
    data = {**payload, "_checksum": checksum_16}
    _validate_checksum(data)  # must not raise


def test_validate_checksum_skips_when_absent():
    """P1-5: no _checksum field means no validation (legacy files without checksum)."""
    from paper import _validate_checksum

    _validate_checksum({"balance": 500.0, "trades": []})  # must not raise


# ── P1-6: atomic_write_json raises on %TEMP% fallback ─────────────────────────


def test_atomic_write_raises_when_all_retries_fail(tmp_path, monkeypatch):
    """P1-6: AtomicWriteError must be raised when the primary path is unwritable."""
    import os

    import safe_io

    # Isolate the default emergency-copy candidate (project_root()/"data"/
    # ".emergency") to tmp_path -- without this, since no fallback_dir is
    # passed here, the real fallback code path writes into THIS repo's own
    # data/.emergency/ directory rather than a throwaway test path.
    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)

    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()

    def fail_replace(src, dst):
        raise OSError("simulated disk full")

    monkeypatch.setattr(os, "replace", fail_replace)

    target = readonly_dir / "data.json"
    from safe_io import AtomicWriteError

    with pytest.raises(AtomicWriteError):
        safe_io.atomic_write_json({"key": "value"}, target, retries=1)


def test_atomic_write_emergency_copy_written_on_failure(tmp_path, monkeypatch):
    """P1-6: emergency copy is written to fallback_dir before raising."""
    import os

    import safe_io

    emergency_dir = tmp_path / "emergency"
    emergency_dir.mkdir()

    target = tmp_path / "data" / "paper_trades.json"
    _real_replace = os.replace

    def fail_replace(src, dst):
        # Only the primary target's replace fails -- the emergency copy
        # (also os.replace-based now, temp+fsync+replace) must go through
        # for real so this test can assert its content, same as before
        # atomic_write_json's own emergency copy became atomic.
        if Path(dst) == target:
            raise OSError("simulated disk full")
        _real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_replace)

    from safe_io import AtomicWriteError

    with pytest.raises(AtomicWriteError):
        safe_io.atomic_write_json(
            {"key": "value"}, target, retries=1, fallback_dir=emergency_dir
        )

    # Emergency copy must exist for manual recovery
    assert (emergency_dir / "paper_trades.json").exists()


def test_atomic_write_default_fallback_does_not_clobber_original(tmp_path, monkeypatch):
    """Regression test for the 2026-07-27 live bug: every real caller omits
    fallback_dir, so the default emergency candidate used to be
    project_root()/"data" -- identical to where every real target file
    already lives (DATA_DIR). That silently turned the "emergency copy for
    manual recovery" into a non-atomic same-path overwrite, defeating
    atomic_write_json's entire crash-safety guarantee. Reproduces the exact
    real-world shape (target lives directly in <project_root>/data/) with no
    fallback_dir passed, and asserts the original file is left untouched
    while a real, non-colliding recovery copy lands in data/.emergency/."""
    import os

    import safe_io

    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    target = data_dir / "forecast_sigma.json"
    target.write_text('{"stale": "old data — must survive a failed write"}')

    _real_replace = os.replace

    def fail_replace(src, dst):
        # Only the primary target's replace fails -- the emergency copy's
        # own os.replace (temp+fsync+replace, since the M2 fix) must go
        # through for real so this test can assert its content.
        if Path(dst) == target:
            raise OSError("simulated disk full")
        _real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_replace)

    from safe_io import AtomicWriteError

    with pytest.raises(AtomicWriteError):
        safe_io.atomic_write_json({"fresh": "new data"}, target, retries=1)

    # The original file must be untouched -- this is the actual crash-safety
    # guarantee atomic_write_json exists to provide, and is exactly what the
    # old default silently broke by overwriting it non-atomically instead.
    assert json.loads(target.read_text()) == {
        "stale": "old data — must survive a failed write"
    }

    # The real fix: a genuine, non-colliding recovery copy exists instead.
    emergency_copy = data_dir / ".emergency" / "forecast_sigma.json"
    assert emergency_copy.exists()
    assert json.loads(emergency_copy.read_text()) == {"fresh": "new data"}


def test_atomic_write_skips_fallback_dir_that_collides_with_original(
    tmp_path, monkeypatch
):
    """Belt-and-suspenders guard: even an explicit fallback_dir that happens
    to resolve to the original file's own directory must not be used as the
    emergency-copy location -- it must be skipped, falling through to the
    next candidate (the default data/.emergency/ subdir here), never
    silently overwrite the original."""
    import os

    import safe_io

    # Isolate the default emergency-copy candidate to tmp_path -- see the
    # identical comment on test_atomic_write_raises_when_all_retries_fail.
    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    target = data_dir / "paper_trades.json"
    target.write_text('{"stale": "must survive"}')

    _real_replace = os.replace

    def fail_replace(src, dst):
        # Only the primary target's replace fails -- the eventual emergency
        # copy's own os.replace (temp+fsync+replace, since the M2 fix) must
        # go through for real so this test can assert its content.
        if Path(dst) == target:
            raise OSError("simulated disk full")
        _real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_replace)

    from safe_io import AtomicWriteError

    with pytest.raises(AtomicWriteError):
        safe_io.atomic_write_json(
            {"fresh": "new"}, target, retries=1, fallback_dir=data_dir
        )

    # Original untouched -- proves the colliding candidate was never written to.
    assert json.loads(target.read_text()) == {"stale": "must survive"}

    # Positive half: the write didn't just silently vanish -- it fell
    # through to the next non-colliding candidate (default .emergency subdir).
    fallen_through_copy = data_dir / ".emergency" / "paper_trades.json"
    assert fallen_through_copy.exists()
    assert json.loads(fallen_through_copy.read_text()) == {"fresh": "new"}


def test_atomic_write_concurrent_threads_same_target_no_collision(
    tmp_path, monkeypatch
):
    """backlog.txt "FORECAST_SIGMA.JSON ATOMIC WRITE CONTENTION": multiple
    threads within the SAME process (same PID) racing to atomic_write_json()
    the same path used to share one PID-only temp filename (f".{name}_
    {pid}_{attempt}.tmp") -- two threads at the same attempt number opened/
    wrote/renamed the identical temp file, observed live as WinError 32/5/2
    on the os.replace rename step (bot.log, 2026-07-19/25/27/30, same PID,
    same tmp path each time). Widens the race window by delaying os.fsync
    so N threads' open->write->fsync windows overlap, then asserts every
    thread's atomic_write_json call succeeds with no exception and the
    final file is valid, uncorrupted JSON from exactly one whole writer --
    proving concurrent threads no longer share a temp file now that
    threading.get_ident() is part of the name."""
    import os
    import threading
    import time as _time

    import safe_io

    target = tmp_path / "shared.json"
    n_threads = 8
    barrier = threading.Barrier(n_threads)
    real_fsync = os.fsync

    def slow_fsync(fd):
        real_fsync(fd)
        _time.sleep(0.02)

    monkeypatch.setattr(os, "fsync", slow_fsync)

    errors = []

    def worker(i):
        try:
            barrier.wait(timeout=5)
            # Default retries (3) matches real call sites -- the retry+1s
            # backoff is the existing mechanism that absorbs a same-
            # destination os.replace collision (a residual, harder-to-hit
            # race distinct from the shared-temp-file bug this test targets;
            # Windows os.replace isn't safe against two concurrent replaces
            # of the same destination with zero retries).
            safe_io.atomic_write_json({"writer": i}, target)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"concurrent atomic_write_json calls raised: {errors}"
    final = json.loads(target.read_text())
    assert final.get("writer") in range(n_threads), (
        f"final file must be one whole writer's payload, got: {final}"
    )
    # No leftover temp files from any racer -- every thread's tmp path was
    # unique and successfully renamed away (or cleaned up on its own path).
    leftover = list(tmp_path.glob(".shared.json_*"))
    assert not leftover, f"leftover temp files from a collision: {leftover}"


def test_atomic_write_error_message_accurate_when_no_emergency_copy_possible(
    tmp_path, monkeypatch
):
    """When every candidate (primary write AND every emergency candidate)
    fails, the raised message must say so plainly, not claim 'Emergency
    copy written to None for manual recovery' -- a lie that would mislead
    an operator into thinking recovery data exists when it doesn't. Since
    the emergency copy is now itself atomic (temp + fsync + os.replace,
    same as the primary write), patching os.replace to always fail forces
    every single candidate -- primary and all emergency ones -- to fail
    the same way, deterministically reproducing total failure."""
    import os
    import tempfile

    import safe_io

    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)

    target = tmp_path / "data" / "paper_trades.json"

    def fail_replace(src, dst):
        raise OSError("simulated total disk failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    from safe_io import AtomicWriteError

    with pytest.raises(AtomicWriteError) as exc_info:
        safe_io.atomic_write_json({"key": "value"}, target, retries=1)

    message = str(exc_info.value)
    assert "NO emergency copy could be written" in message
    assert "written to None" not in message

    # No emergency copy actually landed anywhere -- confirms the message
    # is telling the truth, not just phrased differently.
    assert not (tmp_path / "data" / ".emergency" / "paper_trades.json").exists()

    # Regression: every emergency candidate's temp file (written
    # successfully by plain `open`, then failing at os.replace) must be
    # cleaned up on failure, same as the primary write's own tmp cleanup --
    # not left behind to accumulate on disk across repeated failures (ironic
    # given the failure mode under test is itself disk-space-shaped). Caught
    # live while writing this test: an early version of the emergency-copy
    # fix left exactly this kind of stray .emergency.tmp file in this
    # repo's own data/.emergency/ after a single failed test run.
    leftover_tmps = list((tmp_path / "data").rglob("*.tmp")) + list(
        Path(tempfile.gettempdir()).glob(f".paper_trades.json_{os.getpid()}*.tmp")
    )
    assert leftover_tmps == [], f"stray temp file(s) left behind: {leftover_tmps}"
