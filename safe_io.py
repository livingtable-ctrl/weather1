"""
Atomic JSON write with retry and fallback location.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import threading
import time
import typing
from pathlib import Path

_log = logging.getLogger(__name__)


class AtomicWriteError(Exception):
    pass


class CrossProcessLock:
    """OS-level mutual exclusion across separate processes, guarding a
    critical section keyed by a lock file path.

    Windows-only (msvcrt.locking) -- a no-op that always succeeds on other
    platforms, same convention as paper.py's _CrossProcessDataLock (this
    project only runs on Windows; non-Windows callers fall back to whatever
    in-process protection they already have, not a new gap).

    Not reentrant -- a caller that needs recursive acquisition from the same
    thread (paper.py's get_open_trades/get_balance calling back into an
    already-locked section) should keep using its own RLock-wrapped
    implementation rather than this class.
    """

    def __init__(self, lock_path: Path, timeout: float = 10.0):
        self._lock_path = lock_path
        self._timeout = timeout
        self._fh: typing.BinaryIO | None = None

    def __enter__(self) -> CrossProcessLock:
        self.acquire()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()

    def acquire(self) -> bool:
        """Block (up to `timeout` seconds) until the OS mutex is held.

        Returns True once acquired (or immediately on non-Windows, where
        this is a no-op). On sustained contention past the deadline, logs at
        ERROR -- silently proceeding unlocked is a real safety gap, not just
        a warning -- and returns False without holding anything. Never
        raises; callers decide whether False means fail-closed (abort) or
        fail-open (proceed unlocked), matching what they need.
        """
        if sys.platform != "win32":
            return True
        try:
            self._lock_path.parent.mkdir(exist_ok=True)
            fh = open(self._lock_path, "a+b")
        except Exception as exc:
            _log.warning(
                "CrossProcessLock: could not open lock file %s: %s",
                self._lock_path,
                exc,
            )
            return False

        import msvcrt

        deadline = time.monotonic() + self._timeout
        try:
            while True:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        _log.error(
                            "CrossProcessLock: lock %s contended >%.0fs -- "
                            "giving up without acquiring it",
                            self._lock_path,
                            self._timeout,
                        )
                        fh.close()
                        return False
                    time.sleep(0.05)
        except BaseException:
            # Opus review: a KeyboardInterrupt landing inside the retry
            # sleep (a real window on every call -- up to `timeout` seconds)
            # used to propagate with `fh` still open and, worse, still
            # holding the OS byte-range lock until GC. Close it before
            # re-raising rather than silently leaking the handle/lock.
            fh.close()
            raise
        self._fh = fh
        return True

    def release(self) -> None:
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            if sys.platform == "win32":
                fh.seek(0)
                import msvcrt

                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:
            pass
        finally:
            fh.close()


def _replace_with_retry(src: str, dst: Path, deadline_secs: float = 0.5) -> None:
    """os.replace(src, dst), retrying briefly on PermissionError.

    Self-caught (2026-08-08) while mutation-testing an unrelated regression
    test's own discriminating power -- confirmed live and 100% reproducible
    under concurrent read pressure: on Windows, os.replace() (MoveFileEx)
    can fail with PermissionError/WinError 5 "Access is denied" whenever
    ANY other thread/process has `dst` open, even just for reading -- a
    transient condition unrelated to a real disk-full/permissions problem
    (POSIX rename() has no such restriction; a reader there never blocks a
    concurrent rename). Real reader handles in this codebase are held only
    briefly (cache.read_text() opens, reads, and closes in one call), so a
    short bounded retry here resolves the vast majority of these before
    ever reaching the caller's own slower (1s-backoff, 3-attempt) outer
    retry loop -- same "retry briefly, don't treat transient contention as
    a hard failure" approach paper.py's own msvcrt.locking retry loop
    already uses for the identical class of Windows file-sharing
    contention. Any exception OTHER than PermissionError propagates
    immediately, unretried -- this function only targets the specific
    Windows sharing-violation shape, not genuine failures.

    Worst-case latency (opus-review-caught, 2nd review round, 2026-08-08):
    this adds up to `deadline_secs` per outer attempt on top of the
    existing 1s inter-attempt backoff -- at the default retries=3 and
    deadline_secs=0.5, worst case is 3*0.5 + 2*1.0 = 3.5s for the primary
    write (was 2.0s before this function existed), plus up to 0.1s per
    emergency-copy candidate (that call site deliberately passes a shorter
    deadline_secs=0.1 -- read contention on a data/.emergency/ or system-
    temp destination isn't the expected failure mode there) if the primary
    write exhausts all retries. paper.py's own cross-process lock
    (_acquire_file_lock) gives up after a fixed 30s budget (AUD-0030,
    extended from 10s) -- callers that
    hold that lock across an atomic_write_json/atomic_write_text call
    should account for this function's contribution to worst-case latency,
    not just the write itself. paper.py's _save() (the paper-trades ledger,
    held across that same 30s-budget lock on every call) is exactly such a
    caller -- it raises both retries (6) and deadline_secs (1.0, via
    atomic_write_json's replace_deadline_secs) to 6*1.0 + 5*1.0 = 11s worst
    case (AUD batch-30 item 4b), specifically bounded well under 30s rather
    than raised further, so a slow write can't itself exhaust the lock
    budget it's running inside of.
    """
    start = time.monotonic()
    while True:
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if time.monotonic() - start >= deadline_secs:
                raise
            time.sleep(0.01)


def project_root() -> Path:
    """
    Return the main project root directory, resolving git worktrees correctly.

    When running from a git worktree, Path(__file__).parent gives the worktree
    directory — which has no data/ files (they're gitignored). This function
    detects the worktree case and returns the main project root instead.
    """
    here = Path(__file__).resolve().parent
    git_marker = here / ".git"
    if git_marker.is_file():
        # We're in a git worktree — .git is a file like:
        # "gitdir: ../../.git/worktrees/phase-f-websocket"
        try:
            content = git_marker.read_text(encoding="utf-8").strip()
            if content.startswith("gitdir:"):
                git_dir = Path(content.split(":", 1)[1].strip())
                if not git_dir.is_absolute():
                    git_dir = (here / git_dir).resolve()
                # git_dir is .git/worktrees/<name> → go up 3 levels to main project
                return git_dir.parent.parent.parent
        except Exception as _e:
            _log.warning(
                "project_root: failed to parse .git worktree pointer: %s; "
                "falling back to %s",
                _e,
                here,
            )
    return here


def atomic_write_json(
    data: dict,
    path: Path,
    retries: int = 3,
    fallback_dir: Path | None = None,
    *,
    emergency_copy: bool = True,
    replace_deadline_secs: float = 0.5,
) -> None:
    """
    Write data to path atomically (write temp → fsync → rename).
    Retries up to `retries` times with 1s backoff on failure.

    On total failure (all `retries` attempts fail), also attempts a best-
    effort emergency copy for manual operator recovery before raising
    AtomicWriteError -- NOT a transparent fallback, the caller still gets
    an error. `fallback_dir`, if given, is tried first; otherwise (the
    common case -- no real caller in this codebase passes it) the default
    is a dedicated `<project_root>/data/.emergency/` subdirectory, then
    system temp as a last resort. The emergency copy is itself written
    atomically (temp + fsync + rename), same as the primary write.

    Set emergency_copy=False for disposable/re-fetchable JSON data -- same
    opt-out atomic_write_text already exposes (see its own docstring for
    why: cron.py's check_emergency_copies() monitor re-alerts an operator
    every cycle until a landed emergency copy is manually deleted, which a
    trivially-refetchable cache shouldn't trigger).

    `replace_deadline_secs` is the per-attempt PermissionError retry window
    passed to _replace_with_retry -- raise it (e.g. paper.py's ledger save)
    when the destination is an irreplaceable file that real-world Defender/
    OneDrive scan pressure has been observed contending for; see
    _replace_with_retry's own docstring for the worst-case latency formula.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, default=str)
    _atomic_write_payload(
        payload,
        path,
        retries,
        fallback_dir,
        emergency_copy,
        caller_name="atomic_write_json",
        replace_deadline_secs=replace_deadline_secs,
    )


def atomic_write_text(
    text: str,
    path: Path,
    retries: int = 3,
    fallback_dir: Path | None = None,
    *,
    emergency_copy: bool = True,
    replace_deadline_secs: float = 0.5,
) -> None:
    """
    Write raw text to path atomically -- same write-temp/fsync/rename,
    retry, and (by default) emergency-copy-on-total-failure behavior as
    atomic_write_json above, for callers whose payload isn't JSON (e.g.
    hurricane_climatology.py's raw HURDAT2 text cache). Shares the same
    internal _atomic_write_payload helper rather than duplicating the
    retry/fsync/emergency-copy logic -- see atomic_write_json_with_history
    below for the existing precedent of composing on top of that shared
    core instead of reimplementing it.

    Set emergency_copy=False for disposable/re-fetchable data (e.g. a
    30-day HTTP cache that will simply be re-downloaded next call) --
    opus-review-caught (2026-08-08): the emergency-copy machinery exists
    for irreplaceable trading state, but cron.py's check_emergency_copies()
    monitor treats ANY file landing in data/.emergency/ as needing manual
    operator attention, re-alerting every cycle until someone deletes it --
    a multi-megabyte, trivially-refetchable text cache tripping all 3
    retries would page an operator for data that isn't actually at risk of
    loss. AtomicWriteError is still raised on total failure either way
    (the caller's own fail-open handling is unaffected) -- this flag only
    controls whether a best-effort recovery copy is ALSO attempted.

    See atomic_write_json's docstring for `replace_deadline_secs`.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_payload(
        text,
        path,
        retries,
        fallback_dir,
        emergency_copy,
        caller_name="atomic_write_text",
        replace_deadline_secs=replace_deadline_secs,
    )


def _atomic_write_payload(
    payload: str,
    path: Path,
    retries: int = 3,
    fallback_dir: Path | None = None,
    emergency_copy: bool = True,
    *,
    caller_name: str,
    replace_deadline_secs: float = 0.5,
) -> None:
    """Shared write-temp/fsync/rename/retry/emergency-copy core for
    atomic_write_json and atomic_write_text -- both public functions only
    differ in how `payload` is produced (json.dumps vs. raw text), not in
    how it's durably written. `path` is already coerced to a Path with its
    parent directory created by the caller; it does not need to (and
    normally does not) already exist -- it's the write target.

    caller_name identifies the public function in this module's own log
    messages (opus-review-caught 2026-08-08: the messages used to hard-code
    "atomic_write_json" even for a failed atomic_write_text call, AND
    backlog.txt documents an operator grep pattern -- `atomic_write_json
    attempt.*failed` -- against the exact original wording; threading the
    real caller through keeps that pattern matching for JSON callers while
    giving text callers an accurate name instead of a private helper's)."""
    last_exc: Exception | None = None

    for attempt in range(retries):
        try:
            # pid+thread-id included so two processes OR two threads within
            # the same process racing to write the same path (both are real,
            # observed scenarios -- see backlog.txt "FORECAST_SIGMA.JSON
            # ATOMIC WRITE CONTENTION": a cron.py ThreadPoolExecutor worker
            # pool hit this exact collision on a PID-only temp name, since
            # two threads share one PID and therefore raced on the SAME temp
            # file, which is not the "only os.replace can race, which is
            # safe" case this comment used to describe -- that safety
            # argument only holds when each racer has its own temp file)
            # never share one temp file -- each gets its own, and only the
            # eventual os.replace can race, which is safe (whole-file atomic
            # rename, last writer wins cleanly).
            tmp_path_str = str(
                path.parent
                / f".{path.name}_{os.getpid()}_{threading.get_ident()}_{attempt}.tmp"
            )
            with open(tmp_path_str, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError as _fsync_err:
                    _log.warning(
                        "fsync failed for %s — data may not be durable on crash: %s",
                        tmp_path_str,
                        _fsync_err,
                    )
            _replace_with_retry(tmp_path_str, path, deadline_secs=replace_deadline_secs)
            return
        except Exception as exc:
            if tmp_path_str:
                try:
                    os.unlink(tmp_path_str)
                except OSError:
                    pass
            last_exc = exc
            _log.warning(
                "%s attempt %d/%d failed for %s: %s",
                caller_name,
                attempt + 1,
                retries,
                path,
                exc,
            )
            if attempt < retries - 1:
                time.sleep(1.0)

    # All retries exhausted — write emergency copy for manual operator recovery only
    # (unless the caller opted out via emergency_copy=False -- see atomic_write_text's
    # own docstring for why a disposable/re-fetchable payload should skip this).
    # This is NOT a transparent fallback; the caller will still get an error either way.
    emergency_path: Path | None = None
    if not emergency_copy:
        emergency_note = (
            "Emergency copy was skipped (caller passed emergency_copy=False -- "
            "this data is considered disposable/re-fetchable, not irreplaceable)."
        )
    else:
        emergency_candidates = []
        if fallback_dir:
            emergency_candidates.append(Path(fallback_dir))
        # P2-H: prefer a project data subdir so the emergency copy is in a monitored,
        # operator-visible location. Deliberately a dedicated ".emergency" subdir, NOT
        # project_root()/"data" itself -- every real caller's own `path` already lives
        # in data/ (DATA_DIR), so that candidate used to resolve to the exact same file
        # that just failed 3 atomic-write attempts, silently degrading to a non-atomic
        # same-path overwrite for every one of this function's 20+ callers (none pass
        # fallback_dir). System temp is kept as a last-resort fallback.
        # NOTE (accepted limitation): candidates are keyed by path.name (basename)
        # only, not the full relative path -- data/foo.json and data/ab_tests/
        # foo.json would share one emergency slot. No real caller today has an
        # actual basename collision (verified live against every atomic_write_json
        # call site 2026-07-27; re-verified 2026-07-31 after notify.py's new
        # .notify_cooldowns.json call site; re-verified again 2026-08-08 after
        # tracker.py's strategy_pins.json/retired_strategies.json and
        # weather_markets.py's learned_weights.json were migrated to
        # atomic_write_json -- still unique; alerts.py's own migration added no
        # new basename, since alerts.json was already a call site via
        # save_alerts()), and the emergency copy is a best-effort recovery aid,
        # not the source of truth, so this is deliberately left as-is rather
        # than adding relative-path encoding complexity for a theoretical case.
        emergency_candidates.append(project_root() / "data" / ".emergency")
        emergency_candidates.append(Path(tempfile.gettempdir()))
        resolved_target = path.resolve()

        for fb_dir in emergency_candidates:
            candidate_path = fb_dir / path.name
            candidate_tmp: str | None = None
            try:
                if candidate_path.resolve() == resolved_target:
                    # Belt-and-suspenders: never overwrite the exact file that
                    # just failed to write, even if an explicit fallback_dir
                    # collides with it -- that would silently defeat this
                    # function's entire crash-safety guarantee instead of
                    # surfacing the failure.
                    _log.warning(
                        "Skipping emergency-copy candidate %s — resolves to the "
                        "same path as the original write target",
                        candidate_path,
                    )
                    continue
                candidate_path.parent.mkdir(parents=True, exist_ok=True)
                # Same temp+fsync+replace discipline as the primary write above --
                # the emergency copy exists specifically to survive the failure
                # that just occurred, so it needs the same durability, not weaker.
                candidate_tmp = str(
                    candidate_path.parent
                    / f".{candidate_path.name}_{os.getpid()}_{threading.get_ident()}.emergency.tmp"
                )
                with open(candidate_tmp, "w", encoding="utf-8") as f:
                    f.write(payload)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError as _fsync_err:
                        _log.warning(
                            "fsync failed for emergency copy %s: %s",
                            candidate_tmp,
                            _fsync_err,
                        )
                # Shorter deadline than the primary write's default (0.1s
                # vs. 0.5s) -- emergency-copy destinations (data/.emergency/,
                # system temp) aren't read by anything else in this codebase,
                # so sustained reader contention isn't the expected failure
                # mode here; keeping this bounded caps the worst-case total
                # latency this whole function can add on top of the primary
                # write's own already-exhausted retries (opus-review-caught,
                # 2nd review round, 2026-08-08).
                _replace_with_retry(candidate_tmp, candidate_path, deadline_secs=0.1)
                emergency_path = candidate_path
                _log.error(
                    "Emergency copy written to %s for manual recovery (original write failed)",
                    emergency_path,
                )
                break
            except Exception as fb_exc:
                if candidate_tmp:
                    try:
                        os.unlink(candidate_tmp)
                    except OSError:
                        pass
                _log.error(
                    "Emergency copy also failed for %s: %s", candidate_path, fb_exc
                )

        if emergency_path is not None:
            emergency_note = (
                f"Emergency copy written to {emergency_path} for manual recovery."
            )
        else:
            emergency_note = (
                "NO emergency copy could be written anywhere -- this write's "
                "data is lost."
            )
            _log.error(
                "%s: %s could not be written and no emergency copy could be "
                "written to any candidate location either: %s",
                caller_name,
                path,
                [str(c) for c in emergency_candidates],
            )

    raise AtomicWriteError(
        f"Failed to write {path} after {retries} attempts. "
        f"Disk full, permissions error, or path unavailable. "
        f"{emergency_note} "
        f"Original error: {last_exc}"
    )


def check_emergency_copies(base_dir: Path | None = None) -> list[dict]:
    """Return info about any real recovery copies sitting in the emergency-
    copy fallback location(s) (backlog.txt "SAFE_IO -- NOTHING MONITORS
    data/.emergency/ FOR REAL RECOVERY COPIES"). A file existing here means
    some real caller's atomic_write_json() or atomic_write_text() (both now
    expose a per-call emergency_copy opt-out for disposable payloads --
    atomic_write_text got it first, 2026-08-08; atomic_write_json followed
    the same day once a second disposable-cache caller needed it -- so not
    every failure lands here, only callers that left it at the True
    default) exhausted all `retries` attempts and fell back here -- the
    caller still raised AtomicWriteError, so nothing else ever reads this
    copy; only a human
    manually recovering it closes the loop. Previously the only signal was
    one buried ERROR log line at write time.

    Returns one dict per file, oldest first:
    {"filename": str, "path": str, "mtime": ISO 8601 UTC string, "size_bytes": int}.
    Returns an empty list (not an exception) when nothing is found -- the
    normal, healthy case; a caller should treat a non-empty result as
    something to surface loudly, not as an error condition itself.

    When `base_dir` is omitted (the real/default call shape), also checks
    system temp (`tempfile.gettempdir()`) for the same basenames already
    present in `project_root()/"data"` -- atomic_write_json()'s own
    candidate order falls through to system temp when `data/.emergency/`
    itself can't be written to (e.g. the volume backing `data/` is full),
    which is exactly the scenario this monitor exists to catch, so checking
    only `.emergency/` would miss it. Bounded to known basenames rather
    than scanning all of system temp, which would report unrelated files
    from completely different processes as false positives. Passing an
    explicit `base_dir` (as tests do, for isolation) skips the temp check
    entirely and only inspects `base_dir` itself.

    A file can transiently appear here mid-write (the emergency copy is
    itself written via temp-file + os.replace) or, in the rare case of a
    crash between those two steps, a stray `*.emergency.tmp` file can be
    left permanently -- both are surfaced rather than filtered out, since
    partial recovery data still needs an operator's attention, not silence.
    """
    from datetime import UTC, datetime

    def _dicts_for(paths: list[Path]) -> list[dict]:
        found: list[dict] = []
        for entry in paths:
            if not entry.is_file():
                continue
            try:
                stat = entry.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
            except (OSError, ValueError, OverflowError):
                continue
            found.append(
                {
                    "filename": entry.name,
                    "path": str(entry),
                    "mtime": mtime,
                    "size_bytes": stat.st_size,
                }
            )
        return found

    if base_dir is not None:
        target_dir = Path(base_dir)
        results = _dicts_for(list(target_dir.iterdir())) if target_dir.is_dir() else []
    else:
        primary_dir = project_root() / "data" / ".emergency"
        results = (
            _dicts_for(list(primary_dir.iterdir())) if primary_dir.is_dir() else []
        )

        data_dir = project_root() / "data"
        try:
            known_names = (
                {p.name for p in data_dir.glob("*.json")}
                if data_dir.is_dir()
                else set()
            )
        except OSError:
            known_names = set()
        if known_names:
            temp_dir = Path(tempfile.gettempdir())
            results.extend(_dicts_for([temp_dir / n for n in known_names]))

    results.sort(key=lambda r: str(r["mtime"]))
    return results


def atomic_write_json_with_history(
    data: dict,
    path: Path,
    max_history: int = 10,
) -> None:
    """Does not expose emergency_copy -- this function exists specifically
    to preserve a recoverable history of state worth backing up, so keeping
    atomic_write_json's own emergency_copy=True default (not forwarding a
    caller override) matches its own purpose; no real caller needs the
    opt-out today."""
    import time as _time
    from datetime import UTC, datetime
    from pathlib import Path

    path = Path(path)
    history_dir = path.parent / ".history"

    try:
        if path.exists():
            history_dir.mkdir(exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            history_file = history_dir / f"{path.stem}_{stamp}.json"
            # Avoid collision if two writes happen within the same second
            if history_file.exists():
                history_file = (
                    history_dir
                    / f"{path.stem}_{stamp}_{int(_time.monotonic() * 1000) % 1000}.json"
                )
            history_file.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

            # Prune oldest history files if over limit
            existing = sorted(history_dir.glob(f"{path.stem}_*.json"))
            while len(existing) > max_history:
                existing[0].unlink(missing_ok=True)
                existing = existing[1:]
    except Exception as _hist_exc:
        _log.warning(
            "atomic_write_json_with_history: history backup failed for %s: %s",
            path,
            _hist_exc,
        )

    # Write the new version atomically (call existing atomic_write_json, do NOT use json.dump)
    atomic_write_json(data, path)
