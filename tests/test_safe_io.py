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
    scan pressure peaks -- even the general default (raised to retries=3/
    deadline_secs=1.0, ~5.0s worst case, by batch-38 item M-23d) isn't
    enough headroom for this specific caller, which holds a 30s cross-
    process lock across the write and can afford a much larger budget.
    _save() must pass a raised retries/replace_deadline_secs to
    atomic_write_json rather than relying on the library default (even the
    current, already-raised one). Mutation-tested: reverting _save's call
    back to plain `retries=3` (no replace_deadline_secs) makes this fail."""
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


def test_replace_with_retry_default_deadline_survives_sub_second_contention(
    tmp_path,
):
    """Batch-38 item M-23d: the DEFAULT replace_deadline_secs (raised from
    0.5 to 1.0) must be long enough to retry through a sustained ~0.7s
    stretch of PermissionErrors -- the shape test_safe_io.py's own
    concurrent-writers test observed failing under real Defender/OneDrive-
    style read contention when the default was still 0.5.

    Mutation check: reverting safe_io._replace_with_retry's own default
    parameter back to 0.5 makes this fail (0.5s deadline can't outlast a
    0.7s stretch of failures), proving this test actually exercises the
    DEFAULT rather than an explicitly-passed deadline_secs."""
    import inspect
    import os
    import time
    from unittest.mock import patch

    import safe_io

    default_deadline = (
        inspect.signature(safe_io._replace_with_retry)
        .parameters["deadline_secs"]
        .default
    )
    assert default_deadline == 1.0, (
        "test assumes the current default -- update the 0.7s contention "
        "window below if the default legitimately changes again"
    )

    src = tmp_path / "src.tmp"
    dst = tmp_path / "dst.txt"
    src.write_text("content")

    start = time.monotonic()
    _real_replace = os.replace

    def flaky_replace(s, d):
        if time.monotonic() - start < 0.7:
            raise PermissionError("simulated sustained WinError 5")
        _real_replace(s, d)

    with patch.object(os, "replace", flaky_replace):
        safe_io._replace_with_retry(str(src), dst)  # must not raise

    assert dst.read_text(encoding="utf-8") == "content"


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


# ── backup_sqlite_db (AUD batch-25 item 1/3) ───────────────────────────────


def _make_wal_db_with_uncheckpointed_row(db_path: Path):
    """Create a WAL-mode DB with a table + committed row that has NOT been
    checkpointed out of the .db-wal sidecar -- reproduces the exact live
    state the audit found (data/predictions.db-wal held 2.2MB of committed-
    but-uncheckpointed data). A plain file copy of `db_path` alone (ignoring
    the -wal sidecar) would come back missing this row entirely.

    Returns the OPEN connection -- SQLite auto-checkpoints (folds the WAL
    back into the main .db file) when the last connection to a WAL-mode DB
    closes, which would silently defeat this fixture's whole purpose if
    closed before the caller performs its backup. The caller must close it
    (after the backup happens) to release the file handle."""
    import sqlite3

    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, note TEXT)")
    con.commit()
    con.execute("INSERT INTO orders (note) VALUES ('committed row')")
    con.commit()
    wal_path = db_path.with_name(db_path.name + "-wal")
    assert wal_path.exists() and wal_path.stat().st_size > 0, (
        "test setup didn't actually produce uncheckpointed WAL data -- "
        "this test wouldn't be exercising the bug"
    )
    return con


def test_backup_sqlite_db_includes_uncheckpointed_wal_data(tmp_path):
    """The real regression guard for the WAL bug: write a row, do NOT
    checkpoint, back up, and assert the backup copy actually contains the
    row.

    Mutation check: reverting safe_io.backup_sqlite_db to
    `shutil.copy2(src, dst)` makes this test fail -- the backup copy would
    either be missing the table entirely (same "no such table" error this
    project reproduced live) or missing the row, depending on OS-level
    write-buffering timing.
    """
    from safe_io import backup_sqlite_db

    src = tmp_path / "execution_log.db"
    setup_con = _make_wal_db_with_uncheckpointed_row(src)
    try:
        dst = tmp_path / "backup" / "execution_log.db"
        result = backup_sqlite_db(src, dst)
    finally:
        setup_con.close()

    assert result is True
    import sqlite3

    con = sqlite3.connect(str(dst))
    rows = con.execute("SELECT note FROM orders").fetchall()
    con.close()
    assert rows == [("committed row",)]


def test_backup_sqlite_db_creates_parent_dir(tmp_path):
    """backup_sqlite_db creates dst's parent directory if missing, matching
    every other write helper in this module."""
    from safe_io import backup_sqlite_db

    src = tmp_path / "predictions.db"
    _make_wal_db_with_uncheckpointed_row(src).close()

    dst = tmp_path / "nested" / "does" / "not" / "exist" / "predictions.db"
    assert backup_sqlite_db(src, dst) is True
    assert dst.exists()


def test_backup_sqlite_db_returns_false_and_removes_corrupt_copy(tmp_path, monkeypatch):
    """If the post-copy readability check fails, backup_sqlite_db returns
    False and removes the bad (temp) copy rather than leaving a corrupt
    file that a caller might mistake for a good backup. `dst` itself is
    never created at all in this path (opus-review-caught -- see the
    dedicated H2 regression test below for why writing straight to `dst`
    was the actual bug).

    Simulated via a sqlite3.Connection subclass (sqlite3.Connection itself
    is a C-level immutable type -- can't monkeypatch its `backup` method
    directly) that writes garbage bytes over whatever path `target` (the
    destination connection backup_sqlite_db actually opened -- introspected
    via PRAGMA database_list rather than assumed, since the temp-path
    redesign means that's no longer literally `dst`) is connected to,
    instead of actually copying -- the fake backup() call itself doesn't
    raise, so this exercises the readability CHECK specifically, not a
    copy-step failure.
    """
    import sqlite3

    from safe_io import backup_sqlite_db

    src = tmp_path / "predictions.db"
    _make_wal_db_with_uncheckpointed_row(src).close()
    dst = tmp_path / "predictions_backup.db"

    class _CorruptingConnection(sqlite3.Connection):
        def backup(self, target, *a, **k):
            target_path = Path(target.execute("PRAGMA database_list").fetchone()[2])
            target.close()
            target_path.write_bytes(b"not a real sqlite database")

    real_connect = sqlite3.connect

    def _fake_connect(path, *a, **k):
        return real_connect(path, factory=_CorruptingConnection)

    monkeypatch.setattr(sqlite3, "connect", _fake_connect)

    result = backup_sqlite_db(src, dst)

    assert result is False
    assert not dst.exists(), "corrupt backup copy should have been removed"
    leftover = list(tmp_path.glob(".*backup_tmp*"))
    assert leftover == [], f"temp file(s) left behind: {leftover}"


def test_backup_sqlite_db_returns_false_for_empty_source(tmp_path):
    """A source DB with zero tables (e.g. a freshly-created but never-
    initialized file) is copied byte-for-byte fine but has no tables --
    the readability check should treat that as unreadable/unusable, not a
    false-positive success."""
    import sqlite3

    from safe_io import backup_sqlite_db

    src = tmp_path / "empty.db"
    con = sqlite3.connect(str(src))
    con.close()  # creates a valid-but-empty SQLite file, zero tables

    dst = tmp_path / "empty_backup.db"
    result = backup_sqlite_db(src, dst)

    assert result is False
    assert not dst.exists()


def _corrupt_index_leaving_table_data_intact(db_path: Path, index_name: str) -> None:
    """Byte-flip an index's own b-tree page so PRAGMA integrity_check
    fails on it, while leaving the underlying TABLE data fully intact and
    queryable -- reproduces the exact real-world shape found live in this
    project's own data/execution_log.db (`wrong # of entries in index
    idx_orders_ticker`, orders table itself fully readable)."""
    import sqlite3

    con = sqlite3.connect(str(db_path))
    rootpage = con.execute(
        "SELECT rootpage FROM sqlite_master WHERE name=?", (index_name,)
    ).fetchone()[0]
    page_size = con.execute("PRAGMA page_size").fetchone()[0]
    baseline = con.execute("PRAGMA integrity_check").fetchone()
    assert baseline == ("ok",), (
        f"test setup itself already has integrity issues: {baseline}"
    )
    con.close()

    with open(db_path, "r+b") as f:
        f.seek((rootpage - 1) * page_size + 100)
        chunk = f.read(50)
        f.seek((rootpage - 1) * page_size + 100)
        f.write(bytes(b ^ 0xFF for b in chunk))


def test_backup_sqlite_db_accepts_db_with_unrelated_index_corruption(tmp_path):
    """AUD batch-25 opus-review H1 regression guard: backup_sqlite_db must
    NOT reject (and must NOT discard the only copy of) a database whose
    PRAGMA integrity_check fails for a reason UNRELATED to the WAL bug
    this function exists to fix -- e.g. a corrupt index -- as long as the
    actual table data is intact and queryable.

    An earlier version of this function additionally required
    `PRAGMA integrity_check` to return "ok". Verified live against this
    project's own data/execution_log.db (a real corrupt index,
    `orders` table fully readable): that version returned False and
    discarded the copy, making item 2 of this batch a no-op in production
    -- the live-order ledger it exists to protect. PRAGMA quick_check has
    the identical false positive (confirmed against the same real file),
    so the fix drops the integrity_check requirement entirely in favor of
    a table-existence check, which still catches the actual originally
    reported bug ("no such table").

    Mutation check: reverting backup_sqlite_db's readability check back to
    requiring `PRAGMA integrity_check == "ok"` makes this test fail --
    confirmed by temporarily restoring that requirement and re-running.
    """
    import sqlite3

    from safe_io import backup_sqlite_db

    src = tmp_path / "execution_log.db"
    con = sqlite3.connect(str(src))
    con.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, ticker TEXT)")
    con.execute("CREATE INDEX idx_orders_ticker ON orders(ticker)")
    for i in range(200):
        con.execute("INSERT INTO orders (ticker) VALUES (?)", (f"T{i}",))
    con.commit()
    con.close()

    _corrupt_index_leaving_table_data_intact(src, "idx_orders_ticker")

    # Confirm the corruption actually reproduces the real-world shape
    # before trusting the rest of this test.
    verify_con = sqlite3.connect(str(src))
    integrity = verify_con.execute("PRAGMA integrity_check").fetchall()
    row_count = verify_con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    verify_con.close()
    assert integrity != [("ok",)], "test setup didn't reproduce an integrity failure"
    assert row_count == 200, "table data should still be fully readable pre-backup"

    dst = tmp_path / "backup" / "execution_log.db"
    result = backup_sqlite_db(src, dst)

    assert result is True, (
        "an unrelated index corruption must not make backup_sqlite_db "
        "discard the only copy of an otherwise-readable database"
    )
    con2 = sqlite3.connect(str(dst))
    assert con2.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 200
    con2.close()


def test_backup_sqlite_db_rejects_db_with_corrupted_table_data(tmp_path):
    """AUD batch-25 opus-review-round-2 M2: table-existence alone (just
    counting sqlite_master rows, the fix for H1 above) accepts a copy
    whose sqlite_master page is intact but a TABLE's own root page is
    corrupted -- `SELECT name FROM sqlite_master` succeeds while `SELECT
    * FROM that_table` raises "database disk image is malformed".
    backup_sqlite_db must reject this (unlike the unrelated-index case
    above, which it must accept) since the actual data is NOT readable
    here, not just some orthogonal metadata.

    Reproduced by zeroing out a table's own root b-tree page directly (not
    an index's, and not corrupting page 1 / sqlite_master itself) -- the
    same shape opus review round 2 demonstrated live.

    Mutation check: reverting the per-table `LIMIT 1` probe back to a
    bare `SELECT COUNT(*) FROM sqlite_master WHERE type='table'` count
    makes this test fail -- the corrupted copy would be accepted.
    """
    import sqlite3

    from safe_io import backup_sqlite_db

    src = tmp_path / "predictions.db"
    con = sqlite3.connect(str(src))
    con.execute("CREATE TABLE predictions (id INTEGER PRIMARY KEY, note TEXT)")
    for i in range(200):
        con.execute("INSERT INTO predictions (note) VALUES (?)", (f"note{i}",))
    con.commit()
    rootpage = con.execute(
        "SELECT rootpage FROM sqlite_master WHERE name='predictions'"
    ).fetchone()[0]
    page_size = con.execute("PRAGMA page_size").fetchone()[0]
    con.close()

    with open(src, "r+b") as f:
        f.seek((rootpage - 1) * page_size)
        f.write(b"\x00" * page_size)

    # Confirm the corruption actually reproduces the claimed shape before
    # trusting the rest of this test: sqlite_master still readable, table
    # data is not.
    verify_con = sqlite3.connect(str(src))
    tables = verify_con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    assert tables == [("predictions",)], "sqlite_master should still be intact"
    try:
        verify_con.execute("SELECT * FROM predictions LIMIT 1").fetchall()
        raise AssertionError("test setup didn't reproduce table-data corruption")
    except sqlite3.DatabaseError:
        pass
    verify_con.close()

    dst = tmp_path / "backup" / "predictions.db"
    result = backup_sqlite_db(src, dst)

    assert result is False, (
        "a copy whose table DATA is corrupted (not just an unrelated "
        "index) must be rejected"
    )
    assert not dst.exists()


def test_backup_sqlite_db_probes_table_names_needing_identifier_escaping(tmp_path):
    """AUD batch-25 opus-review-round-3 L1: the M2 per-table readability
    probe interpolates each table name into `SELECT * FROM "{name}"
    LIMIT 1` with `"` doubled for escaping (sqlite3 has no
    parameter-binding for identifiers). A table literally named with an
    embedded double-quote must still probe correctly -- round 3 found
    this had zero test coverage (a mutant removing the escaping entirely
    passed every existing test).

    Mutation check: reverting the escaping (`table_name.replace('"',
    '""')` -> `table_name` unescaped) makes this test fail -- the probe
    query becomes syntactically invalid for this table name and the
    whole backup is wrongly rejected.
    """
    import sqlite3

    from safe_io import backup_sqlite_db

    src = tmp_path / "predictions.db"
    con = sqlite3.connect(str(src))
    # A table name containing a literal double-quote -- valid SQLite,
    # requires proper "" escaping when re-quoted.
    con.execute('CREATE TABLE "has""quote" (id INTEGER PRIMARY KEY, v TEXT)')
    con.execute('INSERT INTO "has""quote" (v) VALUES (\'data\')')
    con.commit()
    con.close()

    dst = tmp_path / "backup" / "predictions.db"
    result = backup_sqlite_db(src, dst)

    assert result is True, (
        "a table name containing a double-quote must not make an "
        "otherwise-healthy backup get rejected by the readability probe"
    )
    con2 = sqlite3.connect(str(dst))
    assert con2.execute('SELECT v FROM "has""quote"').fetchall() == [("data",)]
    con2.close()


def test_backup_sqlite_db_does_not_delete_preexisting_good_backup_on_failure(
    tmp_path,
):
    """AUD batch-25 opus-review H2 regression guard: if a backup attempt
    into a `dst` that already holds a GOOD earlier backup fails (either
    the copy step or the readability check), that pre-existing good file
    must be left untouched -- not overwritten-then-deleted.

    Real scenario: cloud_backup.backup_data() calls this on the SAME
    per-day destination path after every cron cycle. An earlier version
    wrote directly to `dst` and unconditionally removed it on any
    failure, so a later same-day run that failed (transient error, or a
    DB that developed the exact index corruption covered by the test
    above) destroyed the morning's already-good backup.

    Mutation check: reverting backup_sqlite_db to copy straight into
    `dst` (instead of a sibling temp path, replaced only on success)
    makes this test fail -- the good backup gets deleted when the second
    call's source is unreadable.
    """
    import sqlite3

    from safe_io import backup_sqlite_db

    good_src = tmp_path / "predictions.db"
    con = sqlite3.connect(str(good_src))
    con.execute("CREATE TABLE predictions (id INTEGER PRIMARY KEY)")
    con.execute("INSERT INTO predictions DEFAULT VALUES")
    con.commit()
    con.close()

    dst = tmp_path / "backup" / "predictions.db"
    assert backup_sqlite_db(good_src, dst) is True
    good_backup_bytes = dst.read_bytes()

    # A later same-day run: source now has zero tables (simulates a
    # source that fails the readability check cleanly -- returns False,
    # doesn't raise).
    empty_src = tmp_path / "predictions_now_empty.db"
    sqlite3.connect(str(empty_src)).close()

    result = backup_sqlite_db(empty_src, dst)

    assert result is False
    assert dst.exists(), "the pre-existing good backup must not be deleted"
    assert dst.read_bytes() == good_backup_bytes, (
        "the pre-existing good backup's content must be untouched"
    )


def test_backup_sqlite_db_does_not_delete_preexisting_good_backup_when_copy_raises(
    tmp_path,
):
    """Same H2 guard as above, for the OTHER failure shape: the backup()
    call itself raising (source isn't a valid SQLite file at all) rather
    than a clean readability-check False. Both must leave a pre-existing
    good `dst` untouched.

    Mutation check: reverting backup_sqlite_db to copy straight into
    `dst` makes this test fail -- the good backup gets deleted (and the
    exception still propagates) when the second call's source raises.
    """
    import sqlite3

    from safe_io import backup_sqlite_db

    good_src = tmp_path / "predictions.db"
    con = sqlite3.connect(str(good_src))
    con.execute("CREATE TABLE predictions (id INTEGER PRIMARY KEY)")
    con.execute("INSERT INTO predictions DEFAULT VALUES")
    con.commit()
    con.close()

    dst = tmp_path / "backup" / "predictions.db"
    assert backup_sqlite_db(good_src, dst) is True
    good_backup_bytes = dst.read_bytes()

    bad_src = tmp_path / "predictions_now_broken.db"
    bad_src.write_bytes(b"not a real sqlite database")

    with pytest.raises(sqlite3.DatabaseError):
        backup_sqlite_db(bad_src, dst)

    assert dst.exists(), "the pre-existing good backup must not be deleted"
    assert dst.read_bytes() == good_backup_bytes, (
        "the pre-existing good backup's content must be untouched"
    )


# ── atomic_write_bytes (backlog L24249 -- ml_bias.py's bias-model .pkl write
#    was a bare Path.write_bytes()) ─────────────────────────────────────────


def test_atomic_write_bytes_round_trip_preserves_non_utf8_payload(
    tmp_path, monkeypatch
):
    """The whole point of the binary primitive: a payload that is NOT valid
    UTF-8 must survive byte-for-byte.

    Mutation check: dropping the ``_binary``/``_open_mode`` branch in
    ``_atomic_write_payload`` (i.e. reverting it to the text-only
    ``open(..., "w", encoding="utf-8")``) makes this fail. The underlying
    error is a ``TypeError`` ("write() argument must be str, not bytes"), but
    it surfaces as ``AtomicWriteError`` after ~3s -- the retry loop swallows it
    on every attempt and both emergency-copy candidates fail the same way.
    (Opus-review-caught, batch-62: an earlier draft claimed the TypeError
    propagated directly.)
    """
    import pickle

    import safe_io

    # Isolate the default emergency-copy candidate. This test is expected to
    # succeed, but a regression that made the primary write fail would
    # otherwise drop a recovery copy into the REAL data/.emergency/ -- which
    # cron.py's check_emergency_copies() monitor re-alerts on every cycle
    # until an operator deletes it. (Observed for real while mutation-testing
    # this very test, 2026-08-24.)
    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)

    payload = pickle.dumps({"NYC": [0.1, -0.2, 3.5], "CHI": [1.0]})
    assert b"\x80" in payload, "sanity: a pickle is not valid UTF-8 text"

    target = tmp_path / "models" / "bias_models.pkl"
    safe_io.atomic_write_bytes(payload, target)

    assert target.read_bytes() == payload
    assert pickle.loads(target.read_bytes())["NYC"] == [0.1, -0.2, 3.5]
    # No temp file left behind.
    assert [p.name for p in target.parent.iterdir()] == ["bias_models.pkl"]


def test_atomic_write_bytes_overwrites_existing_file_completely(tmp_path, monkeypatch):
    """A shorter payload must fully replace a longer one (rename semantics),
    not leave the previous file's tail behind."""
    import safe_io

    # See the round-trip test above for why project_root is isolated here.
    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)

    target = tmp_path / "m.pkl"
    safe_io.atomic_write_bytes(b"\x00" * 4096, target)
    safe_io.atomic_write_bytes(b"\xff\xfe", target)

    assert target.read_bytes() == b"\xff\xfe"


def test_atomic_write_bytes_shares_retry_and_raise_behavior(
    tmp_path, monkeypatch, caplog
):
    """atomic_write_bytes must go through the same _atomic_write_payload core
    as atomic_write_json/atomic_write_text -- proven by reproducing the same
    total-failure scenario, asserting the same AtomicWriteError, and asserting
    the failure log names *this* caller (the caller_name wiring)."""
    import logging
    import os

    import safe_io
    from safe_io import AtomicWriteError

    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)

    attempted: list[str] = []

    def fail_replace(src, dst):
        # Positive control, recorded rather than inferred: a temp file really
        # was written, with the right bytes, before the rename was attempted.
        # The previous version asserted only that the target dir was empty
        # afterwards -- two absence assertions an implementation that did
        # nothing at all would also satisfy. Opus-review-caught, batch-62.
        attempted.append(src)
        assert Path(src).exists(), "no temp file was written before os.replace"
        assert Path(src).read_bytes() == b"\x80\x81"
        raise OSError("simulated disk full")

    monkeypatch.setattr(os, "replace", fail_replace)

    target = tmp_path / "out" / "m.pkl"
    with caplog.at_level(logging.WARNING, logger="safe_io"):
        with pytest.raises(AtomicWriteError):
            safe_io.atomic_write_bytes(b"\x80\x81", target, retries=1)

    assert attempted, "os.replace was never reached -- nothing was written"
    # caller_name wiring: the log must name atomic_write_bytes, not the
    # private helper and not the JSON caller whose exact wording backlog.txt
    # records an operator grep pattern against.
    assert "atomic_write_bytes attempt 1/1 failed" in caplog.text
    # And the temp file is cleaned up.
    assert list(target.parent.iterdir()) == []


def test_atomic_write_bytes_emergency_copy_is_binary_identical(tmp_path, monkeypatch):
    """The emergency-copy path lives in the same shared core and must also
    switch to binary mode -- a utf-8 text handle there would either raise or
    silently mangle the recovery copy of an irreplaceable model file."""
    import os

    import safe_io
    from safe_io import AtomicWriteError

    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)

    emergency_dir = tmp_path / "emergency"
    emergency_dir.mkdir()
    target = tmp_path / "data" / "bias_models.pkl"
    payload = bytes(range(256))

    _real_replace = os.replace

    def fail_replace(src, dst):
        if Path(dst) == target:
            raise OSError("simulated disk full")
        _real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(AtomicWriteError):
        safe_io.atomic_write_bytes(
            payload, target, retries=1, fallback_dir=emergency_dir
        )

    emergency_copy = emergency_dir / "bias_models.pkl"
    assert emergency_copy.exists(), "no emergency copy written"
    assert emergency_copy.read_bytes() == payload


def test_atomic_write_bytes_failure_leaves_the_previous_file_intact(
    tmp_path, monkeypatch
):
    """The property backlog L24249 actually wanted: a failed write must leave
    the PREVIOUS bytes on disk, not a truncated file.

    Scoped to safe_io deliberately. An earlier version of this was named
    test_ml_bias_model_write_is_atomic and claimed "restoring
    _MODEL_PATH.write_bytes(pkl_bytes) makes this fail" -- it did not, because
    the body never invoked any ml_bias code (coverage showed the whole
    ``if models:`` save block unexecuted). Opus-review-caught, batch-62. The
    ml_bias call site is now pinned properly by
    tests/test_ml_bias.py::TestModelWriteRoutesThroughAtomicWriteBytes.
    """
    import os
    import pickle

    import safe_io

    monkeypatch.setattr(safe_io, "project_root", lambda: tmp_path)
    model_path = tmp_path / "data" / "bias_models.pkl"
    model_path.parent.mkdir(parents=True, exist_ok=True)

    previous = pickle.dumps({"NYC": "previous-model"})
    model_path.write_bytes(previous)

    _real_replace = os.replace

    def fail_replace(src, dst):
        if Path(dst) == model_path:
            raise OSError("simulated disk full")
        _real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_replace)

    new_payload = pickle.dumps({"NYC": "new-model", "pad": "x" * 10_000})
    with pytest.raises(safe_io.AtomicWriteError):
        safe_io.atomic_write_bytes(new_payload, model_path, retries=1)

    # The previous model is byte-for-byte intact and still unpickles.
    assert model_path.read_bytes() == previous
    assert pickle.loads(model_path.read_bytes()) == {"NYC": "previous-model"}
