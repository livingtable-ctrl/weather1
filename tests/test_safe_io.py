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


def test_save_uses_raised_retry_budget_for_the_ledger_write(tmp_path, monkeypatch):
    """AUD (batch-30 item 4b): paper_trades.json is the entire paper-ledger
    source of truth and is written alongside ~55-57 other data/ files during
    cloud_backup's own end-of-cycle sync pass, exactly when Defender/OneDrive
    scan pressure peaks -- the default retries=3/deadline_secs=0.5 (~3.5s
    worst case) budget can be exhausted by that contention. _save() must
    pass a raised retries/replace_deadline_secs to atomic_write_json rather
    than relying on the library default. Mutation-tested: reverting _save's
    call back to plain `retries=3` (no replace_deadline_secs) makes this
    fail."""
    import paper

    captured = {}
    real_atomic_write_json = paper.atomic_write_json

    def _spy(*args, **kwargs):
        captured.update(kwargs)
        return real_atomic_write_json(*args, **kwargs)

    monkeypatch.setattr(paper, "DATA_PATH", tmp_path / "paper_trades.json")
    monkeypatch.setattr(paper, "atomic_write_json", _spy)

    paper._save({"balance": 1000.0, "trades": []})

    assert captured.get("retries", 3) > 3, (
        f"expected a raised retry count for the ledger write, got {captured}"
    )
    assert captured.get("replace_deadline_secs", 0.5) > 0.5, (
        f"expected a raised per-attempt deadline for the ledger write, got {captured}"
    )


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


# ── _replace_with_retry (opus-review-caught, 2026-08-08, 2nd round: the
# WinError-5-on-Windows fix this helper exists for had zero platform-
# independent test coverage -- every mocked os.replace elsewhere in this
# file raises plain OSError, never PermissionError, and CI runs on
# ubuntu-latest where POSIX rename() never raises PermissionError for an
# open destination regardless of whether this function's retry logic
# exists at all. These 3 tests exercise the function directly with a
# mocked os.replace so the retry/re-raise/no-retry behavior is verified on
# every platform, not just incidentally on a Windows dev machine) ─────────────


def test_replace_with_retry_succeeds_after_transient_permission_errors(tmp_path):
    """Retries through N PermissionErrors, then returns normally once
    os.replace finally succeeds -- the expected shape of a real reader
    briefly holding the destination open."""
    import os
    from unittest.mock import patch

    import safe_io

    src = tmp_path / "src.tmp"
    dst = tmp_path / "dst.txt"
    src.write_text("content")

    calls = {"n": 0}
    _real_replace = os.replace

    def flaky_replace(s, d):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("simulated transient WinError 5")
        _real_replace(s, d)

    with patch.object(os, "replace", flaky_replace):
        safe_io._replace_with_retry(str(src), dst)

    assert calls["n"] == 3
    assert dst.read_text(encoding="utf-8") == "content"


def test_replace_with_retry_reraises_after_deadline(tmp_path, monkeypatch):
    """A PermissionError that never clears must eventually re-raise (not
    hang forever or silently succeed) -- this is what lets the caller's
    OWN outer retry/emergency-copy logic still fire for a genuinely stuck
    lock, not just a transient one."""
    import os
    from unittest.mock import patch

    import safe_io

    src = tmp_path / "src.tmp"
    dst = tmp_path / "dst.txt"
    src.write_text("content")

    # Avoid a real 0.5s sleep-loop in the test suite -- collapse both the
    # deadline and the per-attempt sleep so this still exercises the real
    # retry-then-give-up control flow, just fast.
    monkeypatch.setattr(safe_io.time, "sleep", lambda _secs: None)

    def always_fails(s, d):
        raise PermissionError("simulated permanently stuck lock")

    with patch.object(os, "replace", always_fails):
        with pytest.raises(PermissionError):
            safe_io._replace_with_retry(str(src), dst, deadline_secs=0.05)

    # The destination must never have been created -- a re-raise after
    # exhausting retries means the write genuinely never landed.
    assert not dst.exists()


def test_replace_with_retry_does_not_retry_other_exceptions(tmp_path):
    """A non-PermissionError failure (e.g. a genuine disk-full OSError)
    must propagate immediately on the FIRST call -- this function only
    targets the specific Windows sharing-violation shape, not every
    possible os.replace failure, so it must not silently mask or delay a
    real error by retrying something retrying can't fix."""
    import os
    from unittest.mock import patch

    import safe_io

    src = tmp_path / "src.tmp"
    dst = tmp_path / "dst.txt"
    src.write_text("content")

    calls = {"n": 0}

    def fail_once(s, d):
        calls["n"] += 1
        raise OSError("simulated disk full")

    with patch.object(os, "replace", fail_once):
        with pytest.raises(OSError, match="simulated disk full"):
            safe_io._replace_with_retry(str(src), dst)

    assert calls["n"] == 1


def test_atomic_write_json_threads_replace_deadline_secs_to_retry(tmp_path):
    """AUD (batch-30 item 4b): atomic_write_json's replace_deadline_secs
    kwarg must actually reach _replace_with_retry's own deadline_secs, not
    just be accepted and silently dropped -- callers writing an
    irreplaceable file (paper.py's ledger save) rely on this to raise the
    real PermissionError retry window under Defender/OneDrive contention.
    Mutation-tested: hard-coding the call inside _atomic_write_payload back
    to `_replace_with_retry(tmp_path_str, path)` (dropping the
    deadline_secs kwarg) makes this fail."""
    from unittest.mock import patch

    import safe_io

    captured = {}
    _real_replace_with_retry = safe_io._replace_with_retry

    def _spy(src, dst, deadline_secs=0.5):
        captured["deadline_secs"] = deadline_secs
        return _real_replace_with_retry(src, dst, deadline_secs=deadline_secs)

    with patch.object(safe_io, "_replace_with_retry", _spy):
        safe_io.atomic_write_json(
            {"x": 1}, tmp_path / "data.json", replace_deadline_secs=2.5
        )

    assert captured["deadline_secs"] == 2.5


# ── atomic_write_text (backlog.txt "hurricane_climatology.fetch_hurdat2_raw's
# CACHE WRITE ISN'T ATOMIC") ───────────────────────────────────────────────────


def test_atomic_write_text_round_trip(tmp_path):
    """Basic correctness: the exact text passed in is what's on disk after."""
    import safe_io

    target = tmp_path / "cache.txt"
    safe_io.atomic_write_text("some raw HURDAT2-shaped text\nline two\n", target)
    assert (
        target.read_text(encoding="utf-8") == "some raw HURDAT2-shaped text\nline two\n"
    )


def test_atomic_write_text_creates_parent_dirs(tmp_path):
    """Matches atomic_write_json's own path.parent.mkdir(parents=True,
    exist_ok=True) behavior -- callers shouldn't need to pre-create the
    cache directory themselves."""
    import safe_io

    target = tmp_path / "nested" / "dir" / "cache.txt"
    safe_io.atomic_write_text("content", target)
    assert target.read_text(encoding="utf-8") == "content"


def test_atomic_write_text_shares_retry_and_raise_behavior_with_json(
    tmp_path, monkeypatch
):
    """atomic_write_text must go through the same _atomic_write_payload
    core as atomic_write_json (not a parallel, independently-maintained
    implementation) -- proven here by reproducing the identical
    total-failure scenario test_atomic_write_raises_when_all_retries_fail
    above exercises for atomic_write_json, and asserting the same
    AtomicWriteError."""
    import os

    import safe_io

    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)

    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()

    def fail_replace(src, dst):
        raise OSError("simulated disk full")

    monkeypatch.setattr(os, "replace", fail_replace)

    target = readonly_dir / "cache.txt"
    from safe_io import AtomicWriteError

    with pytest.raises(AtomicWriteError):
        safe_io.atomic_write_text("some text", target, retries=1)


def test_atomic_write_text_emergency_copy_written_on_failure(tmp_path, monkeypatch):
    """Mirrors test_atomic_write_emergency_copy_written_on_failure below for
    atomic_write_json -- the emergency-copy fallback is part of the shared
    _atomic_write_payload core, so atomic_write_text gets it for free, but
    this proves that wiring rather than assuming it."""
    import os

    import safe_io

    # Belt-and-suspenders (opus-review-caught, 2nd review round, 2026-08-08):
    # fallback_dir is passed explicitly below and should always succeed as
    # the first emergency candidate, so this should never matter in
    # practice -- but isolating the default candidate to tmp_path anyway
    # means an unexpected fallback_dir failure falls through to a throwaway
    # path, not this repo's real data/.emergency/ (this session's own
    # test-pollution incident, caught and cleaned up, is exactly the
    # failure mode this guards against).
    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)

    emergency_dir = tmp_path / "emergency"
    emergency_dir.mkdir()

    target = tmp_path / "data" / "hurdat2_ATL.txt"
    _real_replace = os.replace

    def fail_replace(src, dst):
        if Path(dst) == target:
            raise OSError("simulated disk full")
        _real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_replace)

    from safe_io import AtomicWriteError

    with pytest.raises(AtomicWriteError):
        safe_io.atomic_write_text(
            "hurdat2 text", target, retries=1, fallback_dir=emergency_dir
        )

    emergency_copy = emergency_dir / "hurdat2_ATL.txt"
    assert emergency_copy.exists()
    assert emergency_copy.read_text(encoding="utf-8") == "hurdat2 text"


def test_atomic_write_text_emergency_copy_opt_out_skips_recovery_copy(
    tmp_path, monkeypatch
):
    """backlog.txt "climate_indices.py's PDO/PNA CACHE AND backtest.py's OWN
    CACHE ALSO SKIP safe_io" 2nd opus review round: emergency_copy=False was
    exercised end-to-end only via a mocked safe_io.atomic_write_json in
    tests/test_backtest.py -- the real, non-mocked opt-out behavior (added
    for hurricane_climatology.fetch_hurdat2_raw, commit 94d3640) had zero
    direct test coverage. A mutation deleting the emergency_copy plumbing in
    _atomic_write_payload would have shipped invisibly."""
    import os

    import safe_io

    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)

    emergency_dir = tmp_path / "emergency"
    emergency_dir.mkdir()

    target = tmp_path / "data" / "hurdat2_ATL.txt"
    _real_replace = os.replace

    def fail_replace(src, dst):
        if Path(dst) == target:
            raise OSError("simulated disk full")
        _real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_replace)

    from safe_io import AtomicWriteError

    with pytest.raises(AtomicWriteError):
        safe_io.atomic_write_text(
            "hurdat2 text",
            target,
            retries=1,
            fallback_dir=emergency_dir,
            emergency_copy=False,
        )

    assert list(emergency_dir.iterdir()) == []


def test_atomic_write_text_concurrent_writers_never_expose_torn_file(
    tmp_path, monkeypatch
):
    """The actual bug class backlog.txt "hurricane_climatology.
    fetch_hurdat2_raw's CACHE WRITE ISN'T ATOMIC" was about: two racing
    writers to the SAME path must never let a concurrent reader observe a
    partially-written/interleaved file.

    Opus-review-caught (2026-08-08), round 1: an earlier version of this
    test used 5000-char payloads and only checked the file's content AFTER
    both writer threads had already joined -- both flaws made it
    structurally unable to fail even against a genuinely non-atomic write.
    5000 chars fits inside a single buffered write() syscall (default
    buffer ~8KB), so each writer's content lands in one atomic-from-the-
    OS's-perspective call regardless of whether os.replace() is used at
    all; and checking only after both threads finish never samples the
    file DURING the race window where a torn read would actually be
    visible. Verified live: a tight-loop reader (no sleep) against a
    deliberately non-atomic stand-in only caught the regression in 1 of 3
    local runs -- too unreliable to trust.

    Round 2 (self-caught while re-verifying round 1's fix, before
    reporting it "done"): a stronger tight-loop-reader version (multi-
    megabyte payloads, 8 reader threads, no sleep) reliably caught the
    non-atomic regression (10/10 runs) -- but ALSO surfaced a real,
    separate, 100%-reproducible bug against the genuine (correct)
    implementation: on Windows, os.replace() can fail with PermissionError
    (WinError 5 "Access is denied") whenever a reader thread has the file
    open, even briefly, for reading. Zero torn reads were ever observed
    (the atomicity guarantee itself held), but the WRITE could outright
    fail under heavy concurrent-read pressure. Fixed at the source
    (safe_io._replace_with_retry, see its own docstring) rather than
    weakening this test to avoid triggering it. The reader here uses a
    small sleep (not a tight loop) between reads -- closer to this
    codebase's real access pattern (a cache read opens, reads, and closes
    in one call, not a continuous poll) while still sampling frequently
    enough to reliably catch a torn read if the underlying write were
    non-atomic (verified: 5/5 local runs, 0 torn reads, 0 write errors
    against the fixed implementation; 5/5 runs with dozens of torn reads
    each against a deliberately non-atomic stand-in).

    project_root is monkeypatched so a write-failure's emergency-copy
    fallback (if it ever fires) lands in tmp_path, never this repo's real
    data/.emergency/ -- self-caught during round 2's investigation: an
    earlier, unpatched version of this same harness (run as a standalone
    script, not through pytest) left a real 5MB test-payload file in this
    repo's actual data/.emergency/ directory, cleaned up manually before
    this test was written."""
    import threading
    import time

    import safe_io

    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)

    target = tmp_path / "cache.txt"
    text_a = "A" * (5 * 1024 * 1024)
    text_b = "B" * (5 * 1024 * 1024)

    stop = threading.Event()
    torn_reads: list[str] = []
    write_errors: list[str] = []

    def _reader():
        while not stop.is_set():
            try:
                content = target.read_text(encoding="utf-8")
            except (FileNotFoundError, OSError):
                pass
            else:
                if content and content not in (text_a, text_b):
                    torn_reads.append(f"len={len(content)}")
            time.sleep(0.001)

    def _writer(text):
        for _ in range(5):
            try:
                safe_io.atomic_write_text(text, target)
            except Exception as exc:
                # Catch ANY exception, not just the expected AtomicWriteError
                # (opus-review-caught, 2nd review round, 2026-08-08) -- an
                # unexpected exception type silently ending this thread
                # would let the test pass with one writer having done
                # nothing, masking a real regression instead of exposing it.
                write_errors.append(f"{type(exc).__name__}: {exc}")

    readers = [threading.Thread(target=_reader) for _ in range(4)]
    for r in readers:
        r.start()
    writer_threads = [
        threading.Thread(target=_writer, args=(text_a,)),
        threading.Thread(target=_writer, args=(text_b,)),
    ]
    for t in writer_threads:
        t.start()
    for t in writer_threads:
        t.join()
    stop.set()
    for r in readers:
        r.join()

    assert write_errors == [], f"write(s) failed under read contention: {write_errors}"
    assert torn_reads == [], f"observed torn/interleaved read(s): {torn_reads}"
    assert target.read_text(encoding="utf-8") in (text_a, text_b)


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

    # Belt-and-suspenders -- see the identical comment on
    # test_atomic_write_text_emergency_copy_written_on_failure above.
    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)

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


def test_atomic_write_json_emergency_copy_opt_out_skips_recovery_copy(
    tmp_path, monkeypatch
):
    """backlog.txt "climate_indices.py's PDO/PNA CACHE AND backtest.py's OWN
    CACHE ALSO SKIP safe_io" 2nd opus review round: atomic_write_json's own
    emergency_copy=False opt-out (added this same session, mirroring
    atomic_write_text's) had zero direct test coverage -- backtest.py's
    fetch_archive_temps passes it, but only through a mocked
    safe_io.atomic_write_json in tests/test_backtest.py, never against the
    real function."""
    import os

    import safe_io

    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)

    emergency_dir = tmp_path / "emergency"
    emergency_dir.mkdir()

    target = tmp_path / "data" / "archive_cache" / "cache_key.json"
    _real_replace = os.replace

    def fail_replace(src, dst):
        if Path(dst) == target:
            raise OSError("simulated disk full")
        _real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_replace)

    from safe_io import AtomicWriteError

    with pytest.raises(AtomicWriteError):
        safe_io.atomic_write_json(
            {"values": [1.0, 2.0]},
            target,
            retries=1,
            fallback_dir=emergency_dir,
            emergency_copy=False,
        )

    assert list(emergency_dir.iterdir()) == []


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


def test_check_emergency_copies_empty_when_dir_missing(tmp_path):
    """backlog.txt "SAFE_IO -- NOTHING MONITORS data/.emergency/ FOR REAL
    RECOVERY COPIES": the normal, healthy case (no emergency copy has ever
    fired) must return an empty list, not raise, when the directory doesn't
    exist at all."""
    import safe_io

    missing = tmp_path / "does_not_exist"
    assert safe_io.check_emergency_copies(base_dir=missing) == []


def test_check_emergency_copies_empty_when_dir_empty(tmp_path):
    import safe_io

    empty_dir = tmp_path / "emergency"
    empty_dir.mkdir()
    assert safe_io.check_emergency_copies(base_dir=empty_dir) == []


def test_check_emergency_copies_reports_real_files(tmp_path):
    """A real emergency copy must be reported with its filename, full path,
    and an mtime -- these are exactly what an operator needs to find and
    recover the file manually."""
    import safe_io

    emergency_dir = tmp_path / "emergency"
    emergency_dir.mkdir()
    f = emergency_dir / "forecast_sigma.json"
    f.write_text('{"recovered": true}', encoding="utf-8")

    results = safe_io.check_emergency_copies(base_dir=emergency_dir)

    assert len(results) == 1
    assert results[0]["filename"] == "forecast_sigma.json"
    assert results[0]["path"] == str(f)
    assert results[0]["size_bytes"] == len('{"recovered": true}')
    # mtime must be a real, parseable ISO 8601 timestamp, not a placeholder.
    from datetime import datetime

    datetime.fromisoformat(results[0]["mtime"])


def test_check_emergency_copies_multiple_files_sorted_oldest_first(tmp_path):
    import os
    import time

    import safe_io

    emergency_dir = tmp_path / "emergency"
    emergency_dir.mkdir()
    older = emergency_dir / "older.json"
    newer = emergency_dir / "newer.json"
    older.write_text("{}", encoding="utf-8")
    # Force a real mtime gap -- same-second writes on some filesystems would
    # otherwise make the ordering assertion flaky rather than meaningful.
    older_time = time.time() - 3600
    os.utime(older, (older_time, older_time))
    newer.write_text("{}", encoding="utf-8")

    results = safe_io.check_emergency_copies(base_dir=emergency_dir)

    assert [r["filename"] for r in results] == ["older.json", "newer.json"]


def test_check_emergency_copies_ignores_subdirectories(tmp_path):
    """Only files matter for operator recovery -- a stray subdirectory
    (e.g. from a manual `mkdir` mistake) must not be reported as a file
    needing recovery."""
    import safe_io

    emergency_dir = tmp_path / "emergency"
    emergency_dir.mkdir()
    (emergency_dir / "subdir").mkdir()
    (emergency_dir / "real.json").write_text("{}", encoding="utf-8")

    results = safe_io.check_emergency_copies(base_dir=emergency_dir)

    assert [r["filename"] for r in results] == ["real.json"]


def test_check_emergency_copies_default_base_dir_uses_project_root(
    tmp_path, monkeypatch
):
    """Without an explicit base_dir, the function must look under this
    repo's OWN project_root()/data/.emergency -- not some other location --
    matching atomic_write_json()'s own default emergency-copy destination."""
    import safe_io

    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)
    default_dir = tmp_path / "data" / ".emergency"
    default_dir.mkdir(parents=True)
    (default_dir / "real.json").write_text("{}", encoding="utf-8")

    results = safe_io.check_emergency_copies()

    assert [r["filename"] for r in results] == ["real.json"]


def test_check_emergency_copies_also_checks_system_temp_fallback(tmp_path, monkeypatch):
    """Opus-review-caught: atomic_write_json()'s own candidate order falls
    through to system temp when data/.emergency/ itself can't be written to
    (e.g. the volume backing data/ is full) -- exactly the scenario this
    monitor exists to catch, so a copy that landed in temp (not
    data/.emergency/) must still be reported, not silently missed."""
    import safe_io

    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)
    fake_temp = tmp_path / "faketemp"
    fake_temp.mkdir()
    monkeypatch.setattr(safe_io.tempfile, "gettempdir", lambda: str(fake_temp))

    # A real target basename must already exist in data/ for the temp check
    # to look for it there (bounded scan -- see the function's docstring).
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "forecast_sigma.json").write_text("{}", encoding="utf-8")

    # The actual emergency copy landed in temp, not data/.emergency/.
    (fake_temp / "forecast_sigma.json").write_text(
        '{"recovered": true}', encoding="utf-8"
    )

    results = safe_io.check_emergency_copies()

    assert [r["filename"] for r in results] == ["forecast_sigma.json"]
    assert str(fake_temp) in results[0]["path"]


def test_check_emergency_copies_temp_scan_ignores_unrelated_files(
    tmp_path, monkeypatch
):
    """The temp scan is bounded to known data/ basenames specifically so it
    doesn't report unrelated files from completely different processes that
    happen to share the same system temp directory."""
    import safe_io

    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)
    fake_temp = tmp_path / "faketemp"
    fake_temp.mkdir()
    monkeypatch.setattr(safe_io.tempfile, "gettempdir", lambda: str(fake_temp))

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "forecast_sigma.json").write_text("{}", encoding="utf-8")

    # Some unrelated process's file living in the same system temp dir.
    (fake_temp / "totally_unrelated_app_cache.json").write_text("{}", encoding="utf-8")

    results = safe_io.check_emergency_copies()

    assert results == []


def test_check_emergency_copies_explicit_base_dir_skips_temp_scan(
    tmp_path, monkeypatch
):
    """Passing an explicit base_dir (as most tests in this file do, for
    isolation) must skip the temp-directory fallback scan entirely --
    otherwise every test using base_dir would depend on this machine's real
    system temp contents, which is what makes those tests deterministic."""
    import safe_io

    # project_root is intentionally left un-mocked and pointed at a dir with
    # no data/ subdir, so if the temp scan ran anyway it would either crash
    # or, worse, silently scan the REAL system temp directory.
    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path / "unused_root")

    explicit_dir = tmp_path / "explicit"
    explicit_dir.mkdir()
    (explicit_dir / "real.json").write_text("{}", encoding="utf-8")

    results = safe_io.check_emergency_copies(base_dir=explicit_dir)

    assert [r["filename"] for r in results] == ["real.json"]


def test_check_emergency_copies_skips_file_with_unparseable_mtime(
    tmp_path, monkeypatch
):
    """Opus-review-caught: datetime.fromtimestamp() can raise on a corrupt or
    out-of-range mtime. That must not crash the whole scan or silently
    propagate out of the function -- a corrupt entry is skipped, but every
    OTHER real file must still be reported, not lost alongside it.

    2026-08-01 CI fix (2 rounds): this used to reproduce the failure via a
    real out-of-range mtime set with os.utime() -- reliable on Windows
    (-34560000 raises there, since the CRT rejects any negative
    timestamp), but not on Linux (glibc tolerates that value fine), so
    Linux CI saw "bad.json" parse successfully and fail this assertion. No
    single real mtime value was found that's both settable via os.utime()
    AND unparseable via datetime.fromtimestamp() on every platform: a
    pre-year-1-CE value (which WOULD fail everywhere, via datetime's own
    MINYEAR=1 bound rather than an OS-specific negative-timestamp quirk)
    can't even be SET on Windows (`OSError: [WinError 87]` -- Windows'
    FILETIME epoch floor of 1601-01-01 sits after year 1 CE), and no Linux
    environment was available here to verify a far-future alternative for
    real rather than by inference.

    Round 1 mocked Path.stat() to raise OSError directly for "bad.json" --
    deterministic, but an opus review caught (mutation-proven: moving
    fromtimestamp() outside the try block, the actual historical
    regression this test exists to catch, still passed) that this no
    longer exercised datetime.fromtimestamp() at all, the real failure
    point named in this docstring. Fixed by having Path.stat() return a
    real stat_result-shaped object with a poisoned st_mtime (NaN) instead
    of raising -- entry.stat() now succeeds normally, and the REAL
    datetime.fromtimestamp(nan, tz=UTC) call inside check_emergency_copies
    is what raises (ValueError: "Invalid value NaN (not a number)"),
    proven platform-independent since it's CPython's own datetime
    conversion rejecting NaN before any libc call, not an OS-specific
    timestamp-range quirk.

    Path.is_file() is separately forced to always return True. The same
    review also caught that this docstring originally justified that
    patch as merely precautionary ("verified live that it does NOT route
    through Path.stat()") based on the local dev interpreter (Python
    3.14) -- but CI runs Python 3.12 (.github/workflows/ci.yml), where
    pathlib's is_file() DOES call self.stat() internally and treats a
    bare OSError (errno=None) as un-ignorable, i.e. it would RE-RAISE
    out of is_file() itself on 3.12 without this patch, error rather than
    fail the assertion, for the exact same reason this whole fix exists:
    a "verified live" claim scoped to one interpreter/platform doesn't
    hold on the one CI actually runs. So this patch is load-bearing on
    CI, not belt-and-braces -- keep it."""
    from types import SimpleNamespace

    import safe_io

    emergency_dir = tmp_path / "emergency"
    emergency_dir.mkdir()
    good = emergency_dir / "good.json"
    good.write_text("{}", encoding="utf-8")
    bad = emergency_dir / "bad.json"
    bad.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(Path, "is_file", lambda self, *a, **kw: True)
    original_stat = Path.stat

    def fake_stat_for_bad_file(self, *args, **kwargs):
        if self.name == "bad.json":
            # _dicts_for only ever reads .st_mtime and .st_size off the
            # returned object -- a real os.stat_result isn't needed, just
            # something duck-typed the same way, with a poisoned mtime.
            return SimpleNamespace(st_mtime=float("nan"), st_size=2)
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat_for_bad_file)

    results = safe_io.check_emergency_copies(base_dir=emergency_dir)

    assert [r["filename"] for r in results] == ["good.json"]


class TestCrossProcessLock:
    """AUD-0006/AUD-0051: shared OS-mutex primitive used to guard critical
    sections that must not run concurrently across separate processes
    (cron's lock-file check-then-write, settlement_monitor's whole run)."""

    def test_acquire_release_round_trip(self, tmp_path):
        import sys

        import safe_io

        lock = safe_io.CrossProcessLock(tmp_path / ".test.lock", timeout=2.0)
        assert lock.acquire() is True
        lock.release()
        # Must be re-acquirable after release, not left permanently held.
        assert lock.acquire() is True
        lock.release()
        if sys.platform == "win32":
            assert (tmp_path / ".test.lock").exists()

    @pytest.mark.skipif(
        __import__("sys").platform != "win32",
        reason="cross-process mutual exclusion uses msvcrt (Windows-only)",
    )
    def test_acquire_closes_handle_on_unexpected_exception_during_contention(
        self, tmp_path, monkeypatch
    ):
        """Opus review: a BaseException (e.g. KeyboardInterrupt) landing
        inside the retry sleep -- a real window on every call, up to
        `timeout` seconds -- used to propagate with the file handle left
        open (only closed later, if/when CPython's refcounting GC finalizes
        it -- not guaranteed to be immediate, and not something to rely on
        for an OS-level resource). Directly checks `fh.closed` on the exact
        handle `open()` returned, rather than inferring closure indirectly
        (e.g. via whether a second lock can acquire afterward -- CPython's
        prompt refcounting can incidentally finalize/close an unreferenced
        file object even without an explicit .close(), which would make an
        indirect check pass for the wrong reason and not actually verify
        the explicit-close code path this fix adds)."""
        import safe_io

        lock_path = tmp_path / ".test.lock"
        lock = safe_io.CrossProcessLock(lock_path, timeout=5.0)

        import msvcrt as _real_msvcrt

        def _always_locked(*_a, **_kw):
            raise OSError("simulated contention")

        monkeypatch.setattr(_real_msvcrt, "locking", _always_locked)

        class _Boom(Exception):
            pass

        def _boom_sleep(*_a, **_kw):
            raise _Boom("simulated interrupt during contention wait")

        monkeypatch.setattr(safe_io.time, "sleep", _boom_sleep)

        import builtins

        opened: list = []
        _orig_open = builtins.open

        def _tracking_open(*a, **kw):
            fh = _orig_open(*a, **kw)
            opened.append(fh)
            return fh

        monkeypatch.setattr(builtins, "open", _tracking_open)

        with pytest.raises(_Boom):
            lock.acquire()

        assert len(opened) == 1, f"expected exactly one open() call, got {opened}"
        assert opened[0].closed, (
            "file handle must be explicitly closed before the exception "
            "propagates, not left open for GC to eventually finalize"
        )

    @pytest.mark.skipif(
        __import__("sys").platform != "win32",
        reason="cross-process mutual exclusion uses msvcrt (Windows-only)",
    )
    def test_second_holder_blocked_while_first_holds_it(self, tmp_path):
        import safe_io

        path = tmp_path / ".test.lock"
        holder = safe_io.CrossProcessLock(path, timeout=5.0)
        assert holder.acquire() is True

        contender = safe_io.CrossProcessLock(path, timeout=0.3)
        try:
            # Short timeout so this returns promptly instead of really
            # waiting -- proves mutual exclusion, not just that it can lock.
            result = contender.acquire()
            assert result is False, (
                "a second CrossProcessLock on the SAME path must not "
                "acquire while the first is still held"
            )
        finally:
            holder.release()

        # Once released, a fresh attempt must succeed.
        contender2 = safe_io.CrossProcessLock(path, timeout=2.0)
        assert contender2.acquire() is True
        contender2.release()

    @pytest.mark.skipif(
        __import__("sys").platform != "win32",
        reason="cross-process mutual exclusion uses msvcrt (Windows-only)",
    )
    def test_two_threads_racing_both_eventually_acquire_but_never_overlap(
        self, tmp_path
    ):
        """Opus review: the original version of this test only asserted
        results.count(True) == 2, which passes even if acquire() were
        gutted to `return True` unconditionally with no locking at all --
        it proved both threads finished, not that they were ever mutually
        exclusive. Recording each hold's [enter, exit) interval and
        asserting they never overlap actually discriminates a broken lock."""
        import threading
        import time as _t

        import safe_io

        path = tmp_path / ".test.lock"
        intervals = []
        intervals_lock = threading.Lock()

        def _worker():
            lock = safe_io.CrossProcessLock(path, timeout=3.0)
            got = lock.acquire()
            if got:
                enter = _t.monotonic()
                _t.sleep(0.2)  # hold briefly so the other thread must wait
                exit_ = _t.monotonic()
                lock.release()
                with intervals_lock:
                    intervals.append((enter, exit_))

        t1 = threading.Thread(target=_worker)
        t2 = threading.Thread(target=_worker)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert len(intervals) == 2, (
            f"both threads should eventually acquire it (one after the "
            f"other releases), got {intervals}"
        )
        (e1, x1), (e2, x2) = intervals
        assert x1 <= e2 or x2 <= e1, (
            f"holds overlapped ({intervals}) -- the lock did not actually "
            f"provide mutual exclusion"
        )
