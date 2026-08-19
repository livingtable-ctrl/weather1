"""
Reproduction for Pass 12 (Concurrency) finding: cron._acquire_cron_lock()
uses a check-then-act (TOCTOU) pattern -- `if lp.exists(): ...` followed
several lines later by `lp.write_text(...)` -- with NO cross-process
locking primitive (unlike paper.py's _CrossProcessDataLock, which uses
msvcrt.locking on Windows). Two threads/processes racing to acquire the
lock when it does not yet exist can BOTH observe lp.exists() == False and
BOTH proceed to write the lock file and return True.

This script proves the race deterministically by monkeypatching
pathlib.Path.exists to force two threads to rendezvous at a barrier while
both are inside the "check" phase of _acquire_cron_lock, before either
reaches the "write" phase. Does not touch any real repo data -- LOCK_PATH
is redirected to a temp directory.

Read-only wrt the rest of the repo. Safe to run standalone.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import threading

REPO_ROOT = r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f"
sys.path.insert(0, REPO_ROOT)

import cron  # noqa: E402

tmpdir = tempfile.mkdtemp()
lock_path = pathlib.Path(tmpdir) / ".cron_lock"
cron.LOCK_PATH = lock_path  # redirect, like tests/test_cron_lock.py does

barrier = threading.Barrier(2, timeout=5)
_orig_exists = pathlib.Path.exists


def _patched_exists(self):
    result = _orig_exists(self)
    if self == lock_path:
        # Rendezvous: force both threads to have completed their
        # exists() check before either is allowed to continue toward
        # the write_text() call further down in _acquire_cron_lock.
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
    return result


pathlib.Path.exists = _patched_exists

results: list[bool] = []
results_lock = threading.Lock()


def _worker():
    r = cron._acquire_cron_lock()
    with results_lock:
        results.append(r)


t1 = threading.Thread(target=_worker)
t2 = threading.Thread(target=_worker)
t1.start()
t2.start()
t1.join(timeout=10)
t2.join(timeout=10)

pathlib.Path.exists = _orig_exists

print("results:", results)
print("lock file final contents:", lock_path.read_text() if lock_path.exists() else "<missing>")

if results.count(True) > 1:
    print("RACE CONFIRMED: both threads acquired the lock (both returned True).")
    sys.exit(0)
else:
    print("Race not reproduced this run (results:", results, ")")
    sys.exit(1)
