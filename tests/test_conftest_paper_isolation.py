"""Regression tests for tests/conftest.py's ``mock_balance_1000`` fixture.

backlog L24334: the fixture used to ``monkeypatch.setattr("paper.DATA_PATH", ...)``
and then ``importlib.reload(paper)`` -- the reload re-executes paper.py's module
body, which recomputes ``DATA_PATH`` from ``safe_io.project_root()``, silently
discarding the patch (and the autouse ``isolate_paper_data`` fixture's patch with
it). Every test taking the fixture therefore read, and would have written, the
REAL data/paper_trades.json production ledger.

These tests guard the fixture itself, not any production code path.
"""

from __future__ import annotations

import json

import paper
from safe_io import project_root

_PRODUCTION_LEDGER = project_root() / "data" / "paper_trades.json"


def _production_ledger_snapshot() -> str | None:
    """Raw text of the REAL ledger, or None if it does not exist.

    Read-only, always -- nothing in this file may write to it.
    """
    if not _PRODUCTION_LEDGER.exists():
        return None
    try:
        return _PRODUCTION_LEDGER.read_text(encoding="utf-8")
    except OSError:
        return None


def test_mock_balance_1000_isolates_data_path(mock_balance_1000, tmp_path):
    """The fixture's paper.DATA_PATH must live under the test's tmp_path.

    Mutation check: restoring the ``importlib.reload(paper)`` line in the
    fixture makes this fail with the real data/paper_trades.json path.
    """
    assert mock_balance_1000 is paper
    assert paper.DATA_PATH.parent == tmp_path
    assert paper.DATA_PATH != _PRODUCTION_LEDGER

    # The derived module constants must follow DATA_PATH, not lag behind it --
    # they are computed once at import time from DATA_PATH, so a reload (or a
    # partial patch) leaves them pointing at data/*.json.
    assert paper._LOSS_OVERRIDE_PATH.parent == tmp_path
    assert paper._ACCURACY_HALT_OVERRIDE_PATH.parent == tmp_path


def test_mock_balance_1000_write_does_not_touch_production_ledger(
    mock_balance_1000, tmp_path
):
    """Positive control for the isolation above.

    Asserting only "DATA_PATH is not the production path" is an absence
    assertion: a future refactor that stopped writing at all would keep it
    green while proving nothing. So this test actually places a trade through
    the fixture and asserts (a) the temp ledger really was written -- the
    positive control -- and (b) the production ledger's bytes and mtime are
    byte-for-byte unchanged.
    """
    # Fail closed BEFORE writing anything: if isolation is broken, this test
    # must not be the thing that corrupts the real ledger. An explicit raise,
    # not an `assert` -- matching conftest's own guard, which was changed for
    # the same reason (an assert is compiled away under `python -O`).
    if paper.DATA_PATH.parent != tmp_path:
        raise RuntimeError(
            f"refusing to place a trade -- paper.DATA_PATH is {paper.DATA_PATH}, "
            "not isolated"
        )

    ticker = "KXHIGHNY-26JUN15-T75"
    before = _production_ledger_snapshot()

    trade = paper.place_paper_order(ticker, "yes", 3, 0.40)

    # Positive control: the write really happened, into the TEMP ledger, and
    # it contains this trade. `DATA_PATH.exists()` is deliberately NOT the
    # control -- the fixture itself seeds a ledger there, so that assertion
    # could never fail and proved nothing (opus-review-caught, batch-62).
    assert trade is not None
    written = json.loads(paper.DATA_PATH.read_text(encoding="utf-8"))
    assert [t["ticker"] for t in written["trades"]] == [ticker]

    # And the production ledger never saw it.
    after = _production_ledger_snapshot()
    # Compare on CONTENT, not raw bytes+mtime: the live bot writes this file
    # on its own schedule, and a cron cycle landing mid-test would otherwise
    # report a fake isolation breach (opus-review-caught -- an external writer
    # was observed touching data/ during this batch's own review). The precise
    # claim is "this test's ticker is absent from the real ledger", which no
    # concurrent legitimate write can make false.
    assert after is None or ticker not in after
    assert before is None or ticker not in before
