"""paper._DATA_LOCK must serialise the ledger read-modify-write cycle across
SEPARATE OS PROCESSES, not just threads within one process.

Regression for the cross-process lost-update race: cron and the web dashboard
are independent long-lived processes with no shared threading.Lock — before
this fix, a load in one could straddle a save in the other and silently
revert a settlement. Windows-only (msvcrt); skipped elsewhere.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="cross-process lock uses msvcrt (Windows-only)"
)

_HOLD_SECONDS = 1.5

# Run in a real subprocess (not multiprocessing.Process) so it goes through a
# fresh Python interpreter and genuinely exercises the msvcrt OS-level lock —
# not just Python-level state that could accidentally be shared in-process.
_SUBPROCESS_SCRIPT = """
import sys, time
sys.path.insert(0, {repo_dir!r})
import paper
from pathlib import Path
paper.DATA_PATH = Path({data_path!r})
paper._DATA_LOCK.acquire()
Path({signal_path!r}).write_text("locked")
time.sleep({hold_seconds})
paper._DATA_LOCK.release()
"""


def test_second_process_blocks_until_first_releases(tmp_path):
    repo_dir = str(__import__("pathlib").Path(__file__).parent.parent)
    data_path = str(tmp_path / "paper_trades.json")
    signal_path = tmp_path / "locked.signal"

    script = _SUBPROCESS_SCRIPT.format(
        repo_dir=repo_dir,
        data_path=data_path,
        signal_path=str(signal_path),
        hold_seconds=_HOLD_SECONDS,
    )
    proc = subprocess.Popen([sys.executable, "-c", script])
    try:
        # Wait for the subprocess to confirm it's holding the lock.
        deadline = time.monotonic() + 5.0
        while not signal_path.exists():
            if time.monotonic() > deadline:
                pytest.fail("subprocess never signaled it acquired the lock")
            time.sleep(0.02)

        import paper

        paper.DATA_PATH = tmp_path / "paper_trades.json"

        start = time.monotonic()
        paper._DATA_LOCK.acquire()
        elapsed = time.monotonic() - start
        paper._DATA_LOCK.release()

        assert elapsed > _HOLD_SECONDS * 0.5, (
            f"acquire() returned after {elapsed:.2f}s — the lock file held by the "
            f"other process (held for {_HOLD_SECONDS}s) should have blocked this "
            "acquisition, not let it through immediately"
        )
    finally:
        proc.wait(timeout=10)
