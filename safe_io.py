"""
Atomic JSON write with retry and fallback location.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

_log = logging.getLogger(__name__)


class AtomicWriteError(Exception):
    pass


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
    data: dict, path: Path, retries: int = 3, fallback_dir: Path | None = None
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
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, default=str)
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
            os.replace(tmp_path_str, path)
            return
        except Exception as exc:
            if tmp_path_str:
                try:
                    os.unlink(tmp_path_str)
                except OSError:
                    pass
            last_exc = exc
            _log.warning(
                "atomic_write_json attempt %d/%d failed for %s: %s",
                attempt + 1,
                retries,
                path,
                exc,
            )
            if attempt < retries - 1:
                time.sleep(1.0)

    # All retries exhausted — write emergency copy for manual operator recovery only.
    # This is NOT a transparent fallback; the caller will still get an error.
    emergency_path: Path | None = None
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
    # call site 2026-07-27), and the emergency copy is a best-effort recovery
    # aid, not the source of truth, so this is deliberately left as-is rather
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
            os.replace(candidate_tmp, candidate_path)
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
            _log.error("Emergency copy also failed for %s: %s", candidate_path, fb_exc)

    if emergency_path is not None:
        emergency_note = (
            f"Emergency copy written to {emergency_path} for manual recovery."
        )
    else:
        emergency_note = (
            "NO emergency copy could be written anywhere -- this write's data is lost."
        )
        _log.error(
            "atomic_write_json: %s could not be written and no emergency copy "
            "could be written to any candidate location either: %s",
            path,
            [str(c) for c in emergency_candidates],
        )

    raise AtomicWriteError(
        f"Failed to write {path} after {retries} attempts. "
        f"Disk full, permissions error, or path unavailable. "
        f"{emergency_note} "
        f"Original error: {last_exc}"
    )


def atomic_write_json_with_history(
    data: dict,
    path: Path,
    max_history: int = 10,
) -> None:
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
