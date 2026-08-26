r"""Runtime guard: the test suite must never MUTATE the real data/ directory.

Why this exists
---------------
paths.py resolves ``data/`` to the MAIN CLONE via safe_io.project_root(),
deliberately, so that a worktree cron run hits real state rather than a
stale local copy. The unavoidable consequence is that **every** pytest run
-- from any worktree -- points at the operator's live production state
unless the specific path constant a test touches happens to be redirected.

conftest.py has been closing those holes one constant at a time since
2026-04, and the same bug class keeps coming back, because a redirect list
can only ever describe leaks somebody already found:

  * data/cron.log            -- 467 fabricated signal lines (2026-08-07)
  * data/paper_trades.json   -- tests read/wrote the real ledger (batch-62)
  * data/metar_lockout_calibration.json -- synthetic coefficients written
                                to production (commit 5d9b6c56)
  * data/nearby_station_shadow.json -- 110 phantom cycles, corrupting the
                                denominator of the module's own deliverable
  * data/signals_cache.json, data/.cron_last_run, data/cron_heartbeat.json,
    data/last_heartbeat.txt   -- overwritten by a fixture ticker
  * data/miami_index_state.json -- a MagicMock repr persisted, firing a
                                red-severity false-positive alert per run
  * data/.halt_transitions.json -- the false->true edge tracker that makes
                                a risk halt alert exactly once

Every one of those was found by accident, after the fact. This module
inverts that: rather than enumerating the paths a test must not write, it
makes any mutation under the real data/ directory impossible and fails the
test that attempted one. New state files added to paths.py are covered the
day they are added, with no conftest change.

Scope
-----
MUTATIONS are blocked (the operation raises before touching the filesystem)
and fail the owning test phase. READS are deliberately left alone -- some
are legitimate, e.g. the five git-tracked data/*.json calibration files --
but every one is counted and reported in the run summary, so that
tightening the guard later can be a data-driven decision rather than a
guess.

There is no opt-out marker, by design. A test that genuinely needs a real
data file must copy it into tmp_path first; nothing may quietly re-open the
hole this module exists to close.

Interaction with tests/test_paths_bypass_guard.py
-------------------------------------------------
_under_real_data() classifies a path with pure string operations (no
resolve(), no stat) because it runs on every open() in the suite. That
means it does not follow symlinks/junctions. It is sound here anyway,
because the only supported way to reach data/ is through paths.py's
absolute constants: test_paths_bypass_guard.py already fails the build for
any module that hand-builds a cwd-relative or __file__-relative path to the
data directory instead of importing the constant. (That guard's own
docstring spells out the two literal spellings; they are deliberately not
repeated here, because its scan reads this file too and would flag the
quotation as an offence.) Relative paths are still normalised via abspath()
for safety; they are simply not the expected case.

Directory creation is deliberately NOT guarded
----------------------------------------------
mkdir/makedirs are left alone entirely. An empty directory holds no
production data, and every write INTO one is blocked on its own merits by
the open/Path.open/sqlite/copy guards -- so guarding mkdir buys nothing.

It also actively broke a fresh clone. An earlier version blocked only a
mkdir that would CREATE a directory (allowing an idempotent
``exist_ok=True`` re-assertion of one already present). That passed on a
developer machine, where data/archive_cache already existed, and failed
every test in CI, where a fresh checkout has a gitignored, empty data/:
backtest.py and ab_test.py both mkdir their cache subdirectory at MODULE
IMPORT, so the block fired during collection and took out ~90 tests at
setup. The "already exists" carve-out looked like precision and was really
a dependency on the developer's own filesystem state -- exactly the class
of environment-coupling this module exists to remove.

Known limitations, disclosed in the same spirit as
test_paths_bypass_guard.py's own:

  * The low-level ``os.open``/``os.write`` fd API is not intercepted, and
    neither is ``tempfile`` with an explicit ``dir=`` inside data/ (which
    reaches os.open). No module in this repo uses either (verified by
    grep), and paper.py's ``mkstemp`` + ``os.fdopen`` atomic write stages
    its temp file in the system temp dir and is caught at its
    ``os.replace`` step regardless.
  * A path reached through a symlink or NTFS junction pointing into data/
    is not recognised, per the string-comparison tradeoff above.
  * The guard covers only THIS process. A subprocess (web_app spawns cron
    with subprocess.Popen) inherits none of these patches.

What it does NOT protect, and why that matters
----------------------------------------------
Everything here is process-local monkeypatching, so anything that runs
after ``uninstall()`` is unguarded. That is not theoretical: the whole
reason conftest no longer calls uninstall() at pytest_unconfigure is that
weather_markets registers atexit flushers which fire at true interpreter
shutdown -- after unconfigure, and after monkeypatch has reverted every
isolate_* redirect. One of those (flush_member_values) was writing
fabricated rows into the real data/predictions.db on every single run. See
conftest.pytest_sessionfinish, which now asserts that every atexit-
registered flush buffer has been drained, and the backlog entry "TEST RUNS
WRITE FABRICATED ROWS INTO THE REAL data/predictions.db".
"""

from __future__ import annotations

import atexit
import builtins
import os
import pathlib
import shutil
import sqlite3
import threading
import urllib.parse

__all__ = [
    "ProdDataWriteError",
    "install",
    "uninstall",
    "set_current_test",
    "assert_clean",
    "read_summary_lines",
    "orphaned_violations",
]


class ProdDataWriteError(RuntimeError):
    """Raised at the call site that tried to mutate the real data/ dir."""


# (nodeid, operation, path, thread) for mutations attempted since the last
# assert_clean(). Reads accumulate for the whole session instead.
_violations: list[tuple[str, str, str, str]] = []
# Violations that no test phase ever claimed -- recorded during collection,
# during a phase that raised for an unrelated reason, or from a thread that
# outlived its test. Dropping these silently is the failure mode this list
# exists to prevent; conftest reports them at session end.
_orphaned: list[tuple[str, str, str, str]] = []
_reads: dict[str, set[str]] = {}  # path -> nodeids that read it
_READ_NODEIDS_PER_PATH = 5  # bounds the summary's memory, not its accuracy
_current_nodeid = "<collection/import>"

# Guards _violations/_orphaned/_current_nodeid. list.append is GIL-atomic so
# nothing corrupts without it, but the SEMANTICS race: this repo spawns
# daemon threads that outlive their test (cron's watchdog, kalshi_ws's depth
# writer, nws's ThreadPoolExecutor), and without a lock such a thread's
# violation can be cleared mid-read or attributed to an innocent test. The
# thread name is recorded in every violation so a cross-thread attribution
# is visible rather than merely confusing.
_lock = threading.RLock()

# Every spelling of the real data dir the string comparison must recognise:
# the literal one, the fully-resolved one (a junction or 8.3 short name in
# the project path would otherwise be a false negative), and the Windows
# extended-length \\?\ form. Captured at install() time, before any fixture
# can monkeypatch paths.DATA_DIR out from under us.
_data_prefixes: tuple[str, ...] = ()

_WRITE_MODES = ("w", "a", "x", "+")
_EXTENDED_PREFIX = "\\\\?\\"
_installed = False
_atexit_registered = False


def _strip_extended(p: str) -> str:
    """Drop a Windows extended-length prefix so \\\\?\\C:\\x == C:\\x."""
    if p.startswith(_EXTENDED_PREFIX):
        rest = p[len(_EXTENDED_PREFIX) :]
        if rest.startswith("UNC\\"):
            return "\\\\" + rest[4:]
        return rest
    return p


def _norm(p: str) -> str:
    p = _strip_extended(p)
    if not os.path.isabs(p):
        p = os.path.abspath(p)
    return os.path.normcase(os.path.normpath(p))


def _under_real_data(p) -> bool:
    """True if `p` names the real data/ dir or anything inside it."""
    try:
        s = os.fspath(p)
    except TypeError:
        return False  # an int fd, a socket, sqlite3's ":memory:" sentinel...
    if isinstance(s, bytes):
        s = os.fsdecode(s)
    if not s:
        return False
    s = _norm(s)
    for prefix in _data_prefixes:
        if s == prefix or s.startswith(prefix + os.sep):
            return True
    return False


def _sqlite_target(database) -> tuple[object, str]:
    """Split a sqlite3 `database` argument into (filesystem path, query).

    sqlite3 accepts both a plain path and a ``file:`` URI (with uri=True).
    Passing the raw URI to _under_real_data() classifies it as a RELATIVE
    path -- it does not start with a drive letter -- so abspath() prepends
    the cwd and the comparison silently fails. That made every URI form a
    bypass, and simultaneously made the "mode=ro is allowed" clause dead
    code: migrate_backup.py's four read-only URI callers were passing by
    accident rather than by design.
    """
    try:
        raw = os.fspath(database)
    except TypeError:
        return database, ""
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    if not isinstance(raw, str) or not raw.startswith("file:"):
        return database, ""
    parsed = urllib.parse.urlsplit(raw)
    target = urllib.parse.unquote(parsed.path)
    # "file:C:/x.db" puts everything in .path; "file:///C:/x.db" leaves a
    # leading slash that must come off before the drive letter.
    if len(target) > 2 and target[0] == "/" and target[2] == ":":
        target = target[1:]
    return target, parsed.query


def _block(operation: str, path) -> None:
    thread = threading.current_thread().name
    with _lock:
        _violations.append((_current_nodeid, operation, str(path), thread))
        nodeid = _current_nodeid
    root = _data_prefixes[0] if _data_prefixes else "data/"
    on_thread = "" if thread == "MainThread" else f" (on thread {thread!r})"
    raise ProdDataWriteError(
        f"{operation} on the REAL production data directory: {path}\n"
        f"  attempted by: {nodeid}{on_thread}\n"
        f"  Tests must never write, delete or rename anything under {root}\n"
        f"  Redirect the path constant this code binds -- and remember that\n"
        f"  it is the CONSUMING module's attribute that must be patched,\n"
        f"  not just paths.<CONST>, when that module did\n"
        f"  `from paths import <CONST>` at import time.\n"
        f"  See tests/conftest.py's isolate_* fixtures for the pattern."
    )


def _note_read(path) -> None:
    with _lock:
        seen = _reads.setdefault(str(path), set())
        if len(seen) < _READ_NODEIDS_PER_PATH:
            seen.add(_current_nodeid)


# --- originals, captured once at import --------------------------------
_o_open = builtins.open
_o_path_open = pathlib.Path.open
_o_connect = sqlite3.connect
_o_replace = os.replace
_o_rename = os.rename
_o_remove = os.remove
_o_unlink = os.unlink
_o_rmdir = os.rmdir
_o_mkdir = os.mkdir
_o_makedirs = os.makedirs
_o_truncate = os.truncate
_o_utime = os.utime
_o_path_unlink = pathlib.Path.unlink
_o_path_rmdir = pathlib.Path.rmdir
_o_path_touch = pathlib.Path.touch
_o_path_mkdir = pathlib.Path.mkdir
_o_rmtree = shutil.rmtree
_o_copyfile = shutil.copyfile
_o_copy = shutil.copy
_o_copy2 = shutil.copy2
_o_copytree = shutil.copytree
_o_move = shutil.move
# pathlib grew copy/copy_into/move in 3.14. On Windows Path.copy uses
# _winapi.CopyFile2, which bypasses open() entirely -- exactly the "a new
# stdlib API silently reopens the hole" shape this module exists to stop.
_o_path_copy = getattr(pathlib.Path, "copy", None)
_o_path_copy_into = getattr(pathlib.Path, "copy_into", None)
_o_path_move = getattr(pathlib.Path, "move", None)


def _g_open(file, mode="r", *args, **kwargs):
    # Mode is tested first, deliberately: it is a pure string check, so a
    # read -- overwhelmingly the common case over a full suite run -- costs
    # one `in` scan and never reaches the path-normalising code.
    if any(m in mode for m in _WRITE_MODES):
        if _under_real_data(file):
            _block(f"open(mode={mode!r})", file)
    elif _under_real_data(file):
        _note_read(file)
    return _o_open(file, mode, *args, **kwargs)


def _g_path_open(self, mode="r", *args, **kwargs):
    # Path.write_text/write_bytes/read_text/read_bytes all route through
    # Path.open(), so patching this one method covers them. Verified
    # against the running CPython by tests/test_prod_data_guard.py rather
    # than assumed from the stdlib source.
    if any(m in mode for m in _WRITE_MODES):
        if _under_real_data(self):
            _block(f"Path.open(mode={mode!r})", self)
    elif _under_real_data(self):
        _note_read(self)
    return _o_path_open(self, mode, *args, **kwargs)


def _g_connect(database, *args, **kwargs):
    # A connection handle is a write capability and sqlite3 gives no way to
    # tell in advance, so anything but the explicit read-only URI form
    # counts. cloud_backup._sqlite_source_is_empty() opens all six
    # production DBs this way while scanning DATA_DIR.
    target, query = _sqlite_target(database)
    if _under_real_data(target) and "mode=ro" not in query:
        _block("sqlite3.connect", database)
    return _o_connect(database, *args, **kwargs)


def _dst_guard(original, operation):
    """Guard a copy: only the destination is mutated, the source is read."""

    def guarded(src, dst, *args, **kwargs):
        if _under_real_data(dst):
            _block(operation, dst)
        return original(src, dst, *args, **kwargs)

    return guarded


def _move_guard(original, operation):
    """Guard a move/rename: BOTH ends mutate the filesystem.

    A move out of data/ is a delete of the source, which is precisely the
    shape the guard blocks Path.unlink/os.remove for ("a delete leaves
    nothing behind to notice afterwards"). Checking only `dst` -- as a copy
    correctly does -- left renaming a production file away as the one
    uncovered delete.
    """

    def guarded(src, dst, *args, **kwargs):
        if _under_real_data(dst):
            _block(operation, dst)
        if _under_real_data(src):
            _block(f"{operation} (moved OUT of data/)", src)
        return original(src, dst, *args, **kwargs)

    return guarded


def _target_guard(original, operation):
    def guarded(path, *args, **kwargs):
        if _under_real_data(path):
            _block(operation, path)
        return original(path, *args, **kwargs)

    return guarded


def _g_path_unlink(self, *args, **kwargs):
    # web_app's /api/resume does exactly this to the production kill
    # switch. It is a DELETE, so it leaves nothing behind to notice
    # afterwards -- a halt the operator set deliberately is simply gone.
    if _under_real_data(self):
        _block("Path.unlink", self)
    return _o_path_unlink(self, *args, **kwargs)


def _g_path_rmdir(self, *args, **kwargs):
    if _under_real_data(self):
        _block("Path.rmdir", self)
    return _o_path_rmdir(self, *args, **kwargs)


def _g_path_touch(self, *args, **kwargs):
    if _under_real_data(self):
        _block("Path.touch", self)
    return _o_path_touch(self, *args, **kwargs)


def _bound_dst_guard(original, operation, *, also_check_src=False):
    """Guard a bound Path method whose first argument is the destination."""

    def guarded(self, target, *args, **kwargs):
        if _under_real_data(target):
            _block(operation, target)
        if also_check_src and _under_real_data(self):
            _block(f"{operation} (moved OUT of data/)", self)
        return original(self, target, *args, **kwargs)

    return guarded


def install(data_dir) -> None:
    """Patch every filesystem mutation entry point. Idempotent."""
    global _installed, _data_prefixes, _atexit_registered
    if _installed:
        return
    literal = _norm(str(data_dir))
    try:
        resolved = _norm(str(pathlib.Path(data_dir).resolve()))
    except OSError:
        resolved = literal
    _data_prefixes = tuple(dict.fromkeys((literal, resolved)))

    builtins.open = _g_open
    pathlib.Path.open = _g_path_open
    sqlite3.connect = _g_connect
    os.replace = _move_guard(_o_replace, "os.replace -> ")
    os.rename = _move_guard(_o_rename, "os.rename -> ")
    os.remove = _target_guard(_o_remove, "os.remove")
    os.unlink = _target_guard(_o_unlink, "os.unlink")
    os.rmdir = _target_guard(_o_rmdir, "os.rmdir")
    os.truncate = _target_guard(_o_truncate, "os.truncate")
    os.utime = _target_guard(_o_utime, "os.utime")
    shutil.rmtree = _target_guard(_o_rmtree, "shutil.rmtree")
    shutil.copyfile = _dst_guard(_o_copyfile, "shutil.copyfile -> ")
    shutil.copy = _dst_guard(_o_copy, "shutil.copy -> ")
    shutil.copy2 = _dst_guard(_o_copy2, "shutil.copy2 -> ")
    # copytree needs its OWN patch: its signature binds copy_function=copy2
    # at def time, so the patched shutil.copy2 above never reaches it, and
    # with dirs_exist_ok=True the first file lands on disk before the guard
    # would otherwise trip at copystat -> os.utime. cloud_backup.py's
    # snapshot call is the live call site.
    shutil.copytree = _dst_guard(_o_copytree, "shutil.copytree -> ")
    shutil.move = _move_guard(_o_move, "shutil.move -> ")
    pathlib.Path.unlink = _g_path_unlink
    pathlib.Path.rmdir = _g_path_rmdir
    pathlib.Path.touch = _g_path_touch
    if _o_path_copy is not None:
        pathlib.Path.copy = _bound_dst_guard(_o_path_copy, "Path.copy -> ")
    if _o_path_copy_into is not None:
        pathlib.Path.copy_into = _bound_dst_guard(
            _o_path_copy_into, "Path.copy_into -> "
        )
    if _o_path_move is not None:
        pathlib.Path.move = _bound_dst_guard(
            _o_path_move, "Path.move -> ", also_check_src=True
        )

    if not _atexit_registered:
        # Last line of defence. conftest deliberately no longer uninstalls
        # at pytest_unconfigure, so the guard is still armed when atexit
        # flushers run -- but by then no test can be failed, and several
        # flushers swallow Exception. Printing is all that is left, and it
        # is far better than the silence that let flush_member_values write
        # production rows unnoticed for months.
        atexit.register(_report_at_exit)
        _atexit_registered = True

    _installed = True


def _report_at_exit() -> None:  # pragma: no cover -- runs at interpreter exit
    with _lock:
        leftovers = list(_violations) + list(_orphaned)
    if not leftovers:
        return
    print(
        "\n[prod-data-guard] *** "
        f"{len(leftovers)} production mutation(s) were attempted but never "
        "reported by a test phase ***"
    )
    for nodeid, operation, path, thread in leftovers:
        print(f"    {operation}  {path}\n        by {nodeid} on {thread}")
    print(
        "    These happened during collection, after the session ended (an "
        "atexit\n    flusher), or on a thread that outlived its test. See "
        "tests/prod_data_guard.py."
    )


def uninstall() -> None:
    """Restore every patched primitive.

    NOT called from pytest_unconfigure: atexit flushers run after that, and
    weather_markets registers three of them. Provided for tests that need
    to exercise the un-guarded behaviour explicitly.
    """
    global _installed
    if not _installed:
        return
    builtins.open = _o_open
    pathlib.Path.open = _o_path_open
    sqlite3.connect = _o_connect
    os.replace = _o_replace
    os.rename = _o_rename
    os.remove = _o_remove
    os.unlink = _o_unlink
    os.rmdir = _o_rmdir
    os.truncate = _o_truncate
    os.utime = _o_utime
    shutil.rmtree = _o_rmtree
    shutil.copyfile = _o_copyfile
    shutil.copy = _o_copy
    shutil.copy2 = _o_copy2
    shutil.copytree = _o_copytree
    shutil.move = _o_move
    pathlib.Path.unlink = _o_path_unlink
    pathlib.Path.rmdir = _o_path_rmdir
    pathlib.Path.touch = _o_path_touch
    if _o_path_copy is not None:
        pathlib.Path.copy = _o_path_copy
    if _o_path_copy_into is not None:
        pathlib.Path.copy_into = _o_path_copy_into
    if _o_path_move is not None:
        pathlib.Path.move = _o_path_move
    _installed = False


def set_current_test(nodeid: str) -> None:
    """Attribute subsequent violations to `nodeid`.

    Anything still pending was never claimed by a phase -- recorded during
    collection, or during a phase that raised for an unrelated reason so
    its assert_clean() was skipped. Moving it to _orphaned rather than
    discarding it is the point: an earlier draft cleared the list here, and
    a production DELETE performed by a fixture finalizer that then raised
    would vanish without a trace.
    """
    global _current_nodeid
    with _lock:
        if _violations:
            _orphaned.extend(_violations)
            _violations.clear()
        _current_nodeid = nodeid


def assert_clean(phase: str) -> None:
    """Fail the current phase if it attempted any production mutation.

    _block() already raised at the call site, but this second check is not
    redundant: this codebase wraps most persistence in ``try: ... except
    Exception: log``, so the call-site raise is routinely swallowed, and
    without this the test would go green having attempted a production
    write.
    """
    with _lock:
        if not _violations:
            return
        attempts = list(_violations)
        _violations.clear()
    lines = "\n".join(
        f"    {op}  {path}"
        + ("" if thread == "MainThread" else f"   [thread {thread}]")
        for _, op, path, thread in attempts
    )
    raise AssertionError(
        f"tests must not mutate the real production data/ directory "
        f"({len(attempts)} attempt(s) blocked during {phase}):\n{lines}\n"
        f"  Redirect the offending path constant on the CONSUMING module "
        f"(see tests/conftest.py's isolate_* fixtures)."
    )


def orphaned_violations() -> list[tuple[str, str, str, str]]:
    """Violations no test phase ever claimed. Reported at session end."""
    with _lock:
        return list(_orphaned)


def _display_path(path: str) -> str:
    """Path relative to the real data dir, so two same-named files in
    different subdirectories do not collapse to one summary line."""
    if not _data_prefixes:
        return path
    normalised = _norm(path)
    prefix = _data_prefixes[0]
    if normalised.startswith(prefix + os.sep):
        return normalised[len(prefix) + 1 :]
    return path


def read_summary_lines(limit: int = 40) -> list[str]:
    """Human-readable summary of production-data READS seen this session."""
    with _lock:
        snapshot = {path: set(ids) for path, ids in _reads.items()}
    if not snapshot:
        return []
    out = [
        f"[prod-data-guard] {len(snapshot)} real data/ file(s) were READ via "
        f"open()/Path.open() during this run (allowed, but each is a "
        f"potential isolation gap).",
        "    Not counted: os.scandir/listdir/stat and Path.exists(), so the "
        "true read surface is wider than this list.",
    ]
    for path in sorted(snapshot)[:limit]:
        nodeids = sorted(snapshot[path])
        shown = ", ".join(nodeids[:2])
        more = f" (+{len(nodeids) - 2} more)" if len(nodeids) > 2 else ""
        out.append(f"    {_display_path(path)}  <- {shown}{more}")
    if len(snapshot) > limit:
        out.append(f"    ... and {len(snapshot) - limit} more")
    return out
