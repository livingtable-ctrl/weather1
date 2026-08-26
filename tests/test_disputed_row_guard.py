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
import functools
import os
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
    # Environment/dependency dirs, not production code. joblib ships a
    # deliberately non-UTF8 test .py that crashes the scan's read_text.
    ".venv",
    "venv",
    "node_modules",
}


def _production_py_files() -> list[Path]:
    """Every .py file in the repo outside the excluded directories above.

    Uses ``os.walk`` with IN-PLACE ``dirnames[:]`` pruning rather than
    ``Path.rglob("*.py")``. rglob walks the entire tree and only then
    filters, so from the MAIN CLONE -- whose ``.claude/worktrees/`` holds
    every checked-out worktree, each with its own ``.venv`` and ``.git`` --
    it traversed 13,979 paths to keep 80. Measured on the same tree the
    pruned walk is 4.3s -> 0.05s (~86x). Batch-62 recorded ~8 minutes for
    the rglob form; that did not reproduce here and is best read as a
    COLD-cache number (a `du` over the same directory timed out at 2
    minutes cold, while a warm rglob repeat took 4.3s). The absolute cost
    swings hugely with cache state; the structural win -- never traversing
    .venv/.claude/.git -- is what holds regardless.

    ``_EXCLUDED_DIR_NAMES`` already lists ``.claude``,
    ``.venv``, ``.git`` and ``node_modules``, so pruning on that same set
    skips those subtrees entirely instead of walking and discarding them.

    The selection is unchanged: the old code tested ``rel_parts[:-1]``,
    i.e. DIRECTORY components only, never the filename -- and pruning on
    directory names reproduces exactly that. Result is now sorted, which
    the old form did not guarantee; every consumer builds a set or dict so
    ordering was never load-bearing, but a stable order makes the guard's
    failure messages reproducible.

    Same shape as ``test_bare_write_bytes_guard._production_source_files``
    (batch-62).
    """
    files = []
    for dirpath, dirnames, filenames in os.walk(_REPO_ROOT):
        # Prune BEFORE descending -- this is the whole optimisation.
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIR_NAMES]
        for name in filenames:
            if name.endswith(".py"):
                files.append(Path(dirpath) / name)
    return sorted(files)


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
    ("tracker.py", "backfill_price_history"): (
        "Finds settled tickers missing OHLC candlestick history -- matches "
        "sync_outcomes' own candlestick block, which has no disputed check "
        "either. A disputed label means the SETTLEMENT is contested, not "
        "that the raw market price series is untrustworthy; price_history "
        "is never joined into any Brier/calibration query, so there's no "
        "scoring-pollution risk the disputed-row guard exists to prevent."
    ),
    ("tracker.py", "count_scored_attempt_signal_rows"): (
        "batch-81 item 2. The INVERSE of every other entry here: this query "
        "references raw `outcomes` precisely IN ORDER TO exclude disputed "
        "rows, via NOT EXISTS (... o.disputed IS NOT NULL AND o.disputed != "
        "0) -- which is the exact negation of outcomes_valid's own predicate "
        "(WHERE disputed IS NULL OR disputed = 0). "
        "It cannot be written against the view instead, for two reasons. "
        "(1) The row source is analysis_attempts, and settled-ness is "
        "analysis_attempts.outcome -- outcomes_valid is not on the FROM list "
        "at all, so there is no join through it to filter. "
        "(2) No construct over outcomes_valid can answer 'is this ticker "
        "disputed'. An INNER join drops any attempt row lacking an outcomes "
        "row; an ANTI-join returns disputed-OR-absent, which is the inverse "
        "of what is wanted; and a NOT EXISTS against the VIEW testing "
        "disputed != 0 can never match, so it silently no-ops. Only the raw "
        "table distinguishes 'disputed' from 'absent'. "
        "NOT EXISTS (not an inner join) is used so the query does not depend "
        "on an invariant it cannot enforce: measured 2026-08-26 every one of "
        "the 584 scored attempt rows did have an outcomes row, but nothing "
        "guarantees that, and the population this count exists to measure is "
        "defined by having no PREDICTIONS row (494 of 584), not by having an "
        "outcomes row. "
        "Before this batch the query referenced no outcomes table at all, so "
        "this guard's regex could not see it -- the divergence it now "
        "documents was invisible for exactly as long as it existed."
    ),
    ("tracker.py", "get_pending_attempt_tickers"): (
        "LEFT JOIN ... WHERE o.ticker IS NULL -- an anti-join asking only "
        "'does a settlement record exist for this ticker at all', the same "
        "existence-check shape as sync_outcomes above, and dispute status is "
        "orthogonal to it. Joining outcomes_valid would actively break the "
        "query: a disputed ticker would read as having no outcome, be "
        "re-selected as pending on every cycle, and burn a Kalshi API call "
        "each time without ever leaving the queue, since settling it writes "
        "an outcomes row that stays disputed."
    ),
    ("tracker.py", "settle_orphaned_attempt_outcomes"): (
        "Heals analysis_attempts rows left unscored when "
        "settle_pending_attempt_tickers died between writing the outcomes "
        "row and updating the attempt. It must see exactly the rows that "
        "write path produces, and that path applies no disputed filter -- "
        "nor does sync_outcomes' own attempt-settle block, which this "
        "mirrors. Joining outcomes_valid would leave every disputed "
        "ticker's attempt permanently orphaned, i.e. recreate the exact trap "
        "the function exists to close. The value it copies is Kalshi's own "
        "recorded settled_yes, identical to what the primary path writes."
    ),
    ("tracker.py", "backfill_daily_temp_settlement"): (
        "Data-repair utility that corrects settled_temp_f from Kalshi's own "
        "expiration_value -- like backfill_emos_data, correcting a column's "
        "source data doesn't decide whether the row is later used for "
        "calibration/training; that decision belongs to the consumer (e.g. "
        "get_emos_training_data, which does join outcomes_valid). A "
        "disputed row's settled_temp_f is just as wrong-from-a-proxy as a "
        "non-disputed one's and deserves the same correction."
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


@functools.cache
def _iter_outcomes_join_sites() -> tuple[tuple[str, int, str | None], ...]:
    """Return (relative_file, line_number, enclosing_qualified_function_name)
    for every raw `outcomes` (not `outcomes_valid`) join/from anywhere in a
    production .py file, scanning full file text so a JOIN/table-name split
    across lines is still found.

    ``@functools.cache``d because two tests in this module call it, and
    without the cache each one re-walks the tree and re-parses every
    production file -- i.e. the scan cost was being paid twice per run.
    Returns a tuple rather than a list so the cached value cannot be
    mutated by a caller. Mirrors the identical decorator already on
    ``test_isoformat_cutoff_guard._iter_isoformat_cutoff_sites``, whose
    two-caller shape this module otherwise matched but never cached."""
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
    return tuple(sites)


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
