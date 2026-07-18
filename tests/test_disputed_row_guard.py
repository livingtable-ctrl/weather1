r"""Automated guard against a new tracker.py query joining the raw outcomes
table instead of the outcomes_valid view (backlog.txt "DISPUTED-ROW
EXCLUSION PREDICATE HAND-COPIED ~40 TIMES IN tracker.py").

Before this guard, "exclude disputed rows" was a hand-copied SQL predicate
pasted into ~31 queries independently, with no mechanism forcing a new
query joining outcomes to know the rule exists -- exactly how the original
3-function scope grew to 31 in the first place. It's now enforced by a
single CREATE VIEW IF NOT EXISTS outcomes_valid (tracker.py, init_db) that
every calibration/accuracy/training consumer joins instead of the raw
table -- so the fix is structural (join the right table), not something
this guard has to re-verify per query.

This guard's job is narrower and purely mechanical: catch any query that
joins the RAW outcomes table without a documented reason. A regex scan
(matching test_dead_code_scan.py's approach, not a full SQL parser) has one
real wrinkle found while building this file: tracker.py's queries are
inconsistently whitespace-formatted (`JOIN outcomes` vs `JOIN   outcomes`,
multiple spaces for alignment) -- a naive single-space regex missed 4 real
sites during the 2026-07-18 consolidation. The pattern below is
whitespace-tolerant for exactly that reason.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_TRACKER_PY = _REPO_ROOT / "tracker.py"

# function_name -> reason. Every function that joins the raw `outcomes`
# table (not `outcomes_valid`) must be listed here, or the guard test below
# fails. A new function landing here without a real reason is a signal
# worth a second look, not something to silently allowlist.
_RAW_OUTCOMES_ALLOWLIST: dict[str, str] = {
    "init_db": (
        "The outcomes_valid view's own definition (CREATE VIEW ... AS "
        "SELECT * FROM outcomes WHERE ...) necessarily references the raw "
        "table -- a view can't be defined in terms of itself."
    ),
    "purge_old_predictions": (
        "Deletion by retention age -- disputed rows still need purging like "
        "any other old row; dispute status is irrelevant to a delete-by-age "
        "sweep."
    ),
    "get_disputed_count": (
        "Definitionally counts the disputed rows themselves (WHERE "
        "disputed = 1) -- the opposite of outcomes_valid's filter, can "
        "never join the view."
    ),
    "get_history": (
        "Raw audit/display listing (CLI/dashboard history) -- a LEFT JOIN "
        "showing all predictions including disputed ones is the intended "
        "behavior for a human reviewing history, not a calibration input."
    ),
    "backfill_emos_data": (
        "Data-repair utility that fills missing ens_mean/settled_temp_f "
        "columns from external APIs -- backfilling a column doesn't decide "
        "whether the row is later used for calibration/training; that "
        "decision belongs to the consumer (e.g. get_emos_training_data, "
        "which does join outcomes_valid)."
    ),
    "sync_outcomes": (
        "NOT EXISTS existence check for predictions with no outcome row "
        "yet -- a row can't be disputed before it has a settlement at all."
    ),
    "get_outcome_for_ticker": (
        "Real position-resolution lookup (paper.py closes trades against "
        "this) -- needs the actual current Kalshi settlement regardless of "
        "dispute status; a position resolves on the recorded outcome, not "
        "on whether it's later contested."
    ),
}


def _iter_outcomes_join_sites() -> list[tuple[int, str]]:
    """Return (line_number, enclosing_function_name) for every line in
    tracker.py that joins the raw `outcomes` table (not `outcomes_valid`)."""
    lines = _TRACKER_PY.read_text(encoding="utf-8").splitlines()
    func_starts: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = re.match(r"^def (\w+)", line)
        if m:
            func_starts.append((i + 1, m.group(1)))

    def _func_for_line(lineno: int) -> str | None:
        name = None
        for start, fname in func_starts:
            if start <= lineno:
                name = fname
            else:
                break
        return name

    sites = []
    pattern = re.compile(r"\bJOIN\s+outcomes\b(?!_valid)|\bFROM\s+outcomes\b(?!_valid)")
    for i, line in enumerate(lines):
        lineno = i + 1
        if pattern.search(line):
            sites.append((lineno, _func_for_line(lineno)))
    return sites


def test_no_new_raw_outcomes_join_outside_allowlist():
    """Fails if a function joins the raw outcomes table without a
    documented reason in _RAW_OUTCOMES_ALLOWLIST."""
    sites = _iter_outcomes_join_sites()
    unexplained = [
        (lineno, fname)
        for lineno, fname in sites
        if fname is None or fname not in _RAW_OUTCOMES_ALLOWLIST
    ]
    assert not unexplained, (
        "tracker.py line(s) join the raw `outcomes` table instead of the "
        "outcomes_valid view, with no entry in _RAW_OUTCOMES_ALLOWLIST -- "
        "join outcomes_valid instead, or add a documented reason if this "
        "one deliberately needs disputed rows included:\n"
        + "\n".join(
            f"  - tracker.py:{lineno} ({fname})" for lineno, fname in unexplained
        )
    )


def test_raw_outcomes_allowlist_has_no_stale_entries():
    """Inverse check: every allowlisted function must still actually join
    the raw outcomes table (catches a rename, or a function later migrated
    to outcomes_valid without removing its now-stale allowlist entry)."""
    current_raw_funcs = {fname for _, fname in _iter_outcomes_join_sites() if fname}
    stale = [name for name in _RAW_OUTCOMES_ALLOWLIST if name not in current_raw_funcs]
    assert not stale, (
        f"Stale _RAW_OUTCOMES_ALLOWLIST entries, function no longer joins "
        f"raw outcomes: {stale}"
    )


def test_outcomes_valid_view_exists_in_schema():
    """Sanity check the view definition itself hasn't been renamed/removed
    out from under every migrated query."""
    src = _TRACKER_PY.read_text(encoding="utf-8")
    assert "CREATE VIEW IF NOT EXISTS outcomes_valid" in src
    assert "WHERE disputed IS NULL OR disputed = 0" in src
