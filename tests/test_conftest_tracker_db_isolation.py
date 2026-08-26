"""Guards for conftest.py's ``isolate_tracker_db`` fixture.

That fixture used to call ``tracker.init_db()`` for every test, which was
measured at 63-207 ms/test (the figure moves with machine load) and was the
second-largest fixture cost in the suite. It now copies a session-scoped
template file instead -- 0.5 ms/test.

The optimisation is only safe because init_db() is pure schema: one
executescript of CREATE TABLE/INDEX statements plus a loop of idempotent
ALTERs, with no inserts and no environment dependency. These tests pin the two
properties a per-test init_db() was providing, so a regression in the copy
approach fails here rather than as a confusing "no such table" somewhere else.

Deliberately ordered: the second test depends on the first having written a
row, so it proves freshness rather than merely observing an empty table.
"""

from __future__ import annotations

import sqlite3

import pytest

import tracker

_MARKER_TICKER = "KXHIGHNY-26JUN15-T75"


def _tables() -> set[str]:
    with sqlite3.connect(tracker.DB_PATH) as con:
        return {
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


def test_tracker_db_arrives_schema_complete_and_empty():
    """Step 1: the copied template has the schema and no rows, and a write
    lands. The write is the positive control for the freshness test below --
    without it, that test would pass vacuously against a table that was never
    written to in the first place."""
    tables = _tables()
    # A representative spread across the schema, not just one table.
    for expected in ("predictions", "outcomes", "price_improvement"):
        assert expected in tables, f"{expected} missing -- template is incomplete"
    assert len(tables) > 5, f"only {len(tables)} tables -- template looks truncated"

    with sqlite3.connect(tracker.DB_PATH) as con:
        assert con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0
        # predicted_at is NOT NULL alongside ticker; supply both.
        con.execute(
            "INSERT INTO predictions (ticker, city, predicted_at) VALUES (?, ?, ?)",
            (_MARKER_TICKER, "NYC", "2026-08-25T00:00:00+00:00"),
        )
        assert con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 1


def test_tracker_db_is_fresh_for_every_test():
    """Step 2: the row written by the test above must not be visible here.

    This is the property the per-test init_db() call used to provide and the
    one a shared template could plausibly break -- if the fixture ever handed
    out the template itself rather than a copy, this fails.
    """
    with sqlite3.connect(tracker.DB_PATH) as con:
        leaked = con.execute(
            "SELECT COUNT(*) FROM predictions WHERE ticker = ?", (_MARKER_TICKER,)
        ).fetchone()[0]
    assert leaked == 0, (
        "a row written by a previous test is visible -- isolate_tracker_db is "
        "handing out shared state, not a per-test copy"
    )


def test_tracker_db_path_is_isolated_from_production():
    """The copy must live under the test's tmp dir, never the real data/."""
    from safe_io import project_root

    assert tracker.DB_PATH != project_root() / "data" / "predictions.db"
    assert "pytest" in str(tracker.DB_PATH).lower(), tracker.DB_PATH


def test_prod_data_guard_is_armed_while_this_fixture_runs():
    """The two protections must not be able to silently disarm each other.

    ``isolate_tracker_db`` keeps the tracker DB out of the real ``data/`` by
    REDIRECTING a path; ``prod_data_guard`` keeps everything out of it by
    BLOCKING the primitives. They cover the same directory from opposite
    directions, and the test above (``..._path_is_isolated_from_production``)
    asserts an absence -- it passes just as happily against a disarmed guard
    as against a working one.

    So assert the guard is actually live at the moment this fixture has run,
    and specifically that ``shutil.copyfile`` -- the one primitive the fixture
    itself now depends on, since it copies the template -- is the guarded
    wrapper rather than the stdlib original. A future rewrite of the fixture
    that reached for an unguarded primitive would still pass every other test
    in this file.
    """
    import shutil

    from tests import prod_data_guard

    assert prod_data_guard._installed, (
        "the production-data guard is not armed during this test -- "
        "isolate_tracker_db's redirect is now the ONLY thing standing between "
        "the suite and the real data/predictions.db"
    )
    assert prod_data_guard._mode == prod_data_guard._MODE_BLOCK, (
        f"guard armed in {prod_data_guard._mode!r} mode, not BLOCK -- a real "
        "data/ write would be recorded and then allowed through"
    )
    assert shutil.copyfile is not prod_data_guard._o_copyfile, (
        "shutil.copyfile is the unpatched stdlib original -- the primitive "
        "isolate_tracker_db uses to place the tracker DB is unguarded"
    )


def test_a_copy_into_the_real_data_dir_is_still_blocked(tmp_path):
    """Behavioural counterpart to the test above.

    Asserting `_installed is True` proves a flag, not a behaviour. This drives
    the actual primitive at the actual production directory and requires it to
    raise -- so "the guard is armed" is a claim about what happens, not about
    what a global says.

    Deliberately a WEAKER claim than the identity assertion above, and the
    difference is load-bearing. Mutation-tested by replacing install()'s
    ``shutil.copyfile = _dst_guard(...)`` with the bare stdlib original: this
    test still passed, because shutil.copyfile opens its destination through
    ``open()``, which stays patched. The block is real and the file still does
    not land -- genuine defence in depth -- but it arrives from a different
    patch than the one being removed. That is exactly why the test above
    asserts the copyfile identity separately; it is the one that failed under
    that mutation, and without it the fixture's own primitive could be
    unguarded with every test in this file green.
    """
    import shutil

    from safe_io import project_root
    from tests import prod_data_guard

    src = tmp_path / "payload.db"
    src.write_text("not a real db", encoding="utf-8")
    target = project_root() / "data" / "__isolate_interaction_probe.db"

    with pytest.raises(prod_data_guard.ProdDataWriteError):
        shutil.copyfile(src, target)

    assert not target.exists(), (
        "the guard raised but the copy still landed in the real data/ dir"
    )
    # This block was deliberate; drop it so the phase-end assert_clean() hook
    # does not report it as an unintended production mutation.
    prod_data_guard._violations.clear()
