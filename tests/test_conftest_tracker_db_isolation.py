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
