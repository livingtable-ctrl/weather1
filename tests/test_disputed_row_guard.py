r"""Automated guard against a new query anywhere in the repo joining the raw
outcomes table instead of the outcomes_valid view (backlog.txt "DISPUTED-ROW
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
joins the RAW outcomes table without a documented reason. It is a text/AST
scan, not a full SQL parser -- a comment or docstring that happens to
contain the literal text "JOIN outcomes" would still be flagged. That's a
deliberate over-catch: false positives cost a one-line allowlist comment,
false negatives cost a silently unprotected live query.

Widened 2026-07-23 (backlog.txt "DISPUTED-ROW GUARD (test_disputed_row_guard.py)
IS SCOPED TO tracker.py ONLY") from a single hardcoded tracker.py path to
every production .py file in the repo: the original tracker.py-only guard
gave false confidence that the disputed-row problem was solved when 9 real
scoring/calibration consumers in backtest.py, calibration.py, ml_bias.py,
main.py, and web_app.py were independently joining the raw table with zero
protection, found only via a manual repo-wide grep. That grep is now this
guard's actual scan -- a future new raw-outcomes query in ANY production
file is caught automatically instead of requiring another manual sweep.
tests/ is excluded (fixtures legitimately touch raw tables to set up
scenarios), along with .git/, __pycache__/, and other non-code directories.

Hardened same day per an opus review of the widening above, which found two
real (if latent) gaps in the first version of this scan:
  1. Function attribution used a `^def ` line-column-0 regex, so it only
     saw module-level functions -- a raw join inside a nested function or a
     class method silently inherited the *enclosing* module-level
     function's attribution (or None), meaning a second, unsafe query added
     inside an already-allowlisted function's body (nested func, method, or
     just further down the same function) would pass the guard silently --
     the exact "one caller gets missed" failure mode this guard exists to
     prevent, just relocated to sub-function granularity. Fixed by walking
     the real ast.FunctionDef/AsyncFunctionDef tree and picking the
     innermost (smallest-span) enclosing node -- true qualified name,
     methods and nested functions included.
  2. The scan matched line-by-line (`pattern.search(line)` per split line),
     so `JOIN\n    outcomes` (JOIN and the table name on separate lines)
     could never match even though the pattern itself is whitespace/newline
     -tolerant (`\s` matches `\n`) -- splitting into lines broke cross-line
     matches structurally, independent of the pattern. Fixed by scanning
     each file's full text in one pass (`re.finditer` over the whole
     string) and computing the line number from the match offset, instead
     of scanning line-by-line.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent

# Directories that never contain production code reaching predictions.db --
# excluded from the scan. Not just "tests": build/cache dirs and static
# frontend assets would otherwise be walked too since rglob is recursive
# (deliberately, so a future new production subdirectory is covered without
# editing this list -- unlike the file-level allowlist below, this is a
# directory-name blocklist, not a path allowlist).
_EXCLUDED_DIR_NAMES = {
    "tests",
    ".git",
    ".github",
    ".claude",
    ".hypothesis",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".superpowers",
    "__pycache__",
    "data",
    "docs",
    "graphify-out",
    "static",
    "templates",
    "frontend",
    "updated frontend",
    "weather app site V_3 (3)",
}


def _production_py_files() -> list[Path]:
    """Every .py file in the repo outside the excluded directories above."""
    files = []
    for path in _REPO_ROOT.rglob("*.py"):
        rel_parts = path.relative_to(_REPO_ROOT).parts
        if any(part in _EXCLUDED_DIR_NAMES for part in rel_parts[:-1]):
            continue
        files.append(path)
    return files


# (relative_file_path, qualified_function_name) -> reason. Every function
# anywhere in the repo that joins the raw `outcomes` table (not
# `outcomes_valid`) must be listed here, or the guard test below fails. A
# new entry landing here without a real reason is a signal worth a second
# look, not something to silently allowlist. Keyed by (file, qualname)
# rather than bare function name since two files (or two nested scopes)
# could plausibly reuse the same function name; qualname uses dotted
# ClassName.method_name / outer_func.inner_func for nested scopes.
_RAW_OUTCOMES_ALLOWLIST: dict[tuple[str, str], str] = {
    ("tracker.py", "init_db"): (
        "The outcomes_valid view's own definition (CREATE VIEW ... AS "
        "SELECT * FROM outcomes WHERE ...) necessarily references the raw "
        "table -- a view can't be defined in terms of itself."
    ),
    ("tracker.py", "purge_old_predictions"): (
        "Deletion by retention age -- disputed rows still need purging like "
        "any other old row; dispute status is irrelevant to a delete-by-age "
        "sweep."
    ),
    ("tracker.py", "get_disputed_count"): (
        "Definitionally counts the disputed rows themselves (WHERE "
        "disputed = 1) -- the opposite of outcomes_valid's filter, can "
        "never join the view."
    ),
    ("tracker.py", "get_history"): (
        "Raw audit/display listing (CLI/dashboard history) -- a LEFT JOIN "
        "showing all predictions including disputed ones is the intended "
        "behavior for a human reviewing history, not a calibration input."
    ),
    ("tracker.py", "backfill_emos_data"): (
        "Data-repair utility that fills missing ens_mean/settled_temp_f "
        "columns from external APIs -- backfilling a column doesn't decide "
        "whether the row is later used for calibration/training; that "
        "decision belongs to the consumer (e.g. get_emos_training_data, "
        "which does join outcomes_valid)."
    ),
    ("tracker.py", "sync_outcomes"): (
        "NOT EXISTS existence check for predictions with no outcome row "
        "yet -- a row can't be disputed before it has a settlement at all."
    ),
    ("tracker.py", "get_outcome_for_ticker"): (
        "Real position-resolution lookup (paper.py closes trades against "
        "this) -- needs the actual current Kalshi settlement regardless of "
        "dispute status; a position resolves on the recorded outcome, not "
        "on whether it's later contested."
    ),
}


def _function_spans(tree: ast.Module) -> list[tuple[int, int, str]]:
    """Return (start_line, end_line, qualified_name) for every
    FunctionDef/AsyncFunctionDef in the module, at any nesting depth
    (including methods and nested functions), with a dotted qualname built
    from its enclosing Class/FunctionDef chain."""
    spans: list[tuple[int, int, str]] = []

    def _visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                qualname = f"{prefix}{child.name}"
                end = child.end_lineno or child.lineno
                spans.append((child.lineno, end, qualname))
                _visit(child, f"{qualname}.")
            elif isinstance(child, ast.ClassDef):
                _visit(child, f"{prefix}{child.name}.")
            else:
                _visit(child, prefix)

    _visit(tree, "")
    return spans


def _func_for_line(spans: list[tuple[int, int, str]], lineno: int) -> str | None:
    """Innermost (smallest-span) function containing lineno, or None if the
    line isn't inside any function (module level)."""
    containing = [
        (end - start, name) for start, end, name in spans if start <= lineno <= end
    ]
    if not containing:
        return None
    return min(containing, key=lambda t: t[0])[1]


def _iter_outcomes_join_sites() -> list[tuple[str, int, str | None]]:
    """Return (relative_file, line_number, enclosing_qualified_function_name)
    for every raw `outcomes` (not `outcomes_valid`) join/from anywhere in a
    production .py file, scanning full file text so a JOIN/table-name split
    across lines is still found."""
    pattern = re.compile(r"\bJOIN\s+outcomes\b(?!_valid)|\bFROM\s+outcomes\b(?!_valid)")
    sites: list[tuple[str, int, str | None]] = []
    for path in _production_py_files():
        rel = str(path.relative_to(_REPO_ROOT)).replace("\\", "/")
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=rel)
            spans = _function_spans(tree)
        except SyntaxError:
            spans = []
        for m in pattern.finditer(text):
            lineno = text.count("\n", 0, m.start()) + 1
            sites.append((rel, lineno, _func_for_line(spans, lineno)))
    return sites


def test_no_new_raw_outcomes_join_outside_allowlist():
    """Fails if a function joins the raw outcomes table without a
    documented reason in _RAW_OUTCOMES_ALLOWLIST."""
    sites = _iter_outcomes_join_sites()
    unexplained = [
        (rel, lineno, fname)
        for rel, lineno, fname in sites
        if fname is None or (rel, fname) not in _RAW_OUTCOMES_ALLOWLIST
    ]
    assert not unexplained, (
        "File(s) join the raw `outcomes` table instead of the outcomes_valid "
        "view, with no entry in _RAW_OUTCOMES_ALLOWLIST -- join "
        "outcomes_valid instead, or add a documented reason if this one "
        "deliberately needs disputed rows included:\n"
        + "\n".join(
            f"  - {rel}:{lineno} ({fname})" for rel, lineno, fname in unexplained
        )
    )


def test_raw_outcomes_allowlist_has_no_stale_entries():
    """Inverse check: every allowlisted (file, qualname) must still actually
    join the raw outcomes table (catches a rename, or a function later
    migrated to outcomes_valid without removing its now-stale allowlist
    entry)."""
    current_raw_sites = {
        (rel, fname) for rel, _, fname in _iter_outcomes_join_sites() if fname
    }
    stale = [key for key in _RAW_OUTCOMES_ALLOWLIST if key not in current_raw_sites]
    assert not stale, (
        f"Stale _RAW_OUTCOMES_ALLOWLIST entries, (file, function) no longer "
        f"joins raw outcomes: {stale}"
    )


def test_outcomes_valid_view_exists_in_schema():
    """Sanity check the view definition itself hasn't been renamed/removed
    out from under every migrated query."""
    src = (_REPO_ROOT / "tracker.py").read_text(encoding="utf-8")
    assert "CREATE VIEW IF NOT EXISTS outcomes_valid" in src
    assert "WHERE disputed IS NULL OR disputed = 0" in src
