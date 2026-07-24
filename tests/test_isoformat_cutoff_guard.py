r"""Automated guard against a new hand-rolled `.isoformat()` SQL cutoff
appearing anywhere in the repo (backlog.txt "MIXED-TIMESTAMP-FORMAT BUG
CLASS -- RECURRING, NO ROOT-CAUSE FIX").

A 2026-07-10 Fable adversarial review found the *identical* bug three times
in tracker.py: a Python-side "N days ago" cutoff built via
`(datetime.now(UTC) - timedelta(days=...)).isoformat()` ('...T...+00:00')
compared lexicographically in a SQL WHERE clause against a column written by
SQLite's `datetime('now')` ('YYYY-MM-DD HH:MM:SS') -- silently dropping the
entire boundary day, since ' ' (0x20) < 'T' (0x54) in a TEXT comparison. The
2026-07-12 fix pass added `utils.sql_normalize_iso_column()` as the shared
helper for this exact situation and confirmed no unfixed instances remained
at the time -- but nothing structurally stopped a fifth instance from being
hand-rolled the same way later.

This guard is deliberately narrow: it does NOT flag every `.isoformat()`
call (there are 30+ legitimate ones in tracker.py alone -- writing a full
timestamp for an INSERT, building an external API param, etc.). It flags
only the specific *shape* of the bug: a relative-time value computed via
`<...>.now(...) - timedelta(...)).isoformat()` or `<...>.utc_today() -
timedelta(...)).isoformat()` (a Python-side cutoff, optionally with a
trailing `.date()` before `.isoformat()`), which is the pattern that's
dangerous when compared against a `datetime('now')`-written column. Every
site this guard currently finds was individually re-verified against every
INSERT/UPDATE touching its respective column and confirmed safe -- each
column is written ONLY via a matching format throughout the codebase, so
the comparison is internally consistent, not mixed-format. A new site
landing here without that same verification is a signal worth a second
look, not something to silently allowlist.

Modeled directly on tests/test_disputed_row_guard.py's hardened shape: a
full-file-text regex scan (not line-by-line, so a match split across lines
is still found) plus a real ast.FunctionDef/AsyncFunctionDef walk for
qualname attribution (methods and nested functions included, not just
module-level `^def `), scanning every production .py file in the repo minus
non-code directories.

Known blind spots (an opus review of this guard's first version found
these; documented rather than chased, since closing them fully would need
real dataflow analysis, not a text/regex scan -- same "false positives cost
a line, false negatives cost a bug" tradeoff test_disputed_row_guard.py
documents for itself):
  - The two-statement form (`c = datetime.now(UTC) - timedelta(days=30)` on
    one line, `c.isoformat()` on another) is invisible -- the regex only
    matches a single expression, not a value threaded through a variable.
  - Argument nesting beyond 2 parenthesis levels inside `.now(...)` or
    `timedelta(...)` (e.g. a 3-deep `f(g(h(x)))`) is invisible; 2 levels
    (e.g. `timedelta(days=int(cfg("N")))`) IS covered.
  - `+ timedelta(...)` (rather than `-`), `.strftime()` with a wrong format
    string, and other `datetime`/`date` aliasing beyond `_td`/`_utc_today`
    are not covered -- this scan targets the one bug shape actually found
    in this codebase, not every conceivable mixed-format construction.
"""

from __future__ import annotations

import ast
import functools
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent

# Same directory blocklist as test_disputed_row_guard.py / test_dead_code_scan.py
# -- rglob is recursive so a future new production subdirectory is covered
# without editing this list.
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
# anywhere in the repo that builds a `.now(...) - timedelta(...)).isoformat()`
# cutoff must be listed here, or the guard test below fails. A new entry
# landing here without a real reason is a signal worth a second look --
# specifically, whether the column it's compared against is EVER written via
# `datetime('now')` anywhere in the codebase (mixed format = the actual bug).
_ISOFORMAT_CUTOFF_ALLOWLIST: dict[tuple[str, str], str] = {
    ("tracker.py", "get_mean_slippage"): (
        "Cutoff compared against live_fills.logged_at, which is written "
        "ONLY via datetime.now(UTC).isoformat() (log_live_fill) -- no "
        "datetime('now') writer touches this column anywhere in the repo, "
        "so the isoformat-vs-isoformat comparison is internally consistent. "
        "Re-verify if a future write path to live_fills.logged_at ever uses "
        "datetime('now') instead."
    ),
    ("tracker.py", "prune_api_requests"): (
        "Cutoff compared against api_requests.logged_at, which is written "
        "ONLY via datetime.now(UTC).isoformat() (log_api_request) -- no "
        "datetime('now') writer touches this column. Re-verify if a future "
        "write path to api_requests.logged_at ever uses datetime('now') "
        "instead."
    ),
    ("tracker.py", "prune_old_analysis_attempts"): (
        "Cutoff compared against analysis_attempts.analyzed_at, which is "
        "written ONLY via datetime.now(UTC).isoformat() (log_analysis_attempt, "
        "batch_log_analysis_attempts) -- no datetime('now') writer touches "
        "this column. Re-verify if a future write path to "
        "analysis_attempts.analyzed_at ever uses datetime('now') instead."
    ),
    ("tracker.py", "get_recent_city_correlations"): (
        "Cutoff uses .date().isoformat() deliberately (see the function's "
        "own comment two lines above) to match predictions.market_date, "
        "which is written ONLY as market_date.isoformat() on a date object "
        "('YYYY-MM-DD', no 'T') -- date-vs-date comparison, not the mixed "
        "datetime('now')-vs-isoformat() bug shape. Found by this guard's "
        "own first opus review pass (not the original 3-site scope)."
    ),
    ("backtest.py", "run_walk_forward"): (
        "Cutoff (`_utc_today() - timedelta(...)).isoformat()`) is compared "
        "against multiday_predictions.market_date, written as "
        "market_date.isoformat() on a date object ('YYYY-MM-DD', no 'T') -- "
        "same date-vs-date reasoning as run_backtest's own cutoff in this "
        "file (see this function's inline comment). Found by this guard's "
        "own first opus review pass (not the original 3-site scope)."
    ),
}

# Up to 2 levels of parenthesis nesting tolerated inside a call's argument
# list (e.g. `timedelta(days=int(cfg("N")))`) -- deeper nesting is a
# documented blind spot (see module docstring), not silently wrong.
_ARG = r"(?:[^()]|\((?:[^()]|\([^()]*\))*\))*"

_CUTOFF_PATTERN = re.compile(
    r"(?:\w+\.)?(?:datetime\.now|_?utc_today)\(" + _ARG + r"\)"
    r"\s*-\s*"
    r"(?:\w+\.)?(?:timedelta|_td)\(" + _ARG + r"\)"
    r"\s*\)\s*"  # outer closing paren -- whitespace/newline-tolerant (black-wrap safe)
    r"(?:\.\s*date\(\)\s*)?"
    r"\.\s*isoformat\(\)"
)


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
def _iter_isoformat_cutoff_sites() -> tuple[tuple[str, int, str | None], ...]:
    """Return (relative_file, line_number, enclosing_qualified_function_name)
    for every `.now(...) - timedelta(...)).isoformat()` cutoff anywhere in a
    production .py file, scanning full file text so a match split across
    lines is still found. Cached -- three tests in this module each call
    this, and repo files don't change mid-run."""
    sites: list[tuple[str, int, str | None]] = []
    for path in _production_py_files():
        rel = str(path.relative_to(_REPO_ROOT)).replace("\\", "/")
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=rel)
            spans = _function_spans(tree)
        except SyntaxError:
            spans = []
        for m in _CUTOFF_PATTERN.finditer(text):
            lineno = text.count("\n", 0, m.start()) + 1
            sites.append((rel, lineno, _func_for_line(spans, lineno)))
    return tuple(sites)


def test_no_new_isoformat_cutoff_outside_allowlist():
    """Fails if a function builds a `.now(...) - timedelta(...)).isoformat()`
    cutoff without a documented reason in _ISOFORMAT_CUTOFF_ALLOWLIST."""
    sites = _iter_isoformat_cutoff_sites()
    unexplained = [
        (rel, lineno, fname)
        for rel, lineno, fname in sites
        if fname is None or (rel, fname) not in _ISOFORMAT_CUTOFF_ALLOWLIST
    ]
    assert not unexplained, (
        "New .isoformat() SQL cutoff(s) found with no entry in "
        "_ISOFORMAT_CUTOFF_ALLOWLIST -- use utils.sql_normalize_iso_column() "
        "or push the cutoff into SQL via datetime('now', ? || ' days') "
        "instead, or add a documented reason (after verifying the compared "
        "column is never written via datetime('now') anywhere in the repo) "
        "if this one is genuinely safe. A site with fname=None is at module "
        "level -- it can't be allowlisted by function name at all and must "
        "be refactored into a function first:\n"
        + "\n".join(
            f"  - {rel}:{lineno} ({fname})" for rel, lineno, fname in unexplained
        )
    )


def test_isoformat_cutoff_allowlist_has_no_stale_entries():
    """Inverse check: every allowlisted (file, qualname) must still actually
    build this cutoff shape (catches a rename, or a function later migrated
    to the shared helper without removing its now-stale allowlist entry)."""
    current_sites = {
        (rel, fname) for rel, _, fname in _iter_isoformat_cutoff_sites() if fname
    }
    stale = [key for key in _ISOFORMAT_CUTOFF_ALLOWLIST if key not in current_sites]
    assert not stale, (
        f"Stale _ISOFORMAT_CUTOFF_ALLOWLIST entries, function no longer "
        f"builds this cutoff shape: {stale}"
    )


def test_comment_mention_is_a_known_accepted_false_positive():
    """Regression: a comment/docstring merely discussing this cutoff shape
    (e.g. this file's own module docstring, or tracker.py's H-20/H-21/H-22
    writeup) IS matched by this guard -- documenting the accepted tradeoff
    below, not asserting a masking behavior this guard deliberately doesn't
    implement. Uses a synthetic in-memory source string parsed the same way
    the real scan does."""
    source = (
        "def _foo():\n"
        "    # was (datetime.now(UTC) - timedelta(days=1)).isoformat() before the fix\n"
        "    return 1\n"
    )
    matches = list(_CUTOFF_PATTERN.finditer(source))
    # The regex itself has no comment-awareness (matching test_disputed_row_
    # guard.py's own documented tradeoff: false positives here cost a
    # one-line allowlist entry, false negatives cost a silently unprotected
    # live cutoff) -- so a literal mention in a comment IS expected to match
    # the pattern. This test documents that tradeoff rather than asserting a
    # masking behavior this guard deliberately doesn't implement.
    assert len(matches) == 1


def test_real_cutoff_expression_is_caught():
    """Positive-case regression: the exact bug shape must still be caught,
    including with a module-alias prefix (tracker.py's `_dt.datetime.now(...)
    - _dt.timedelta(...)` form)."""
    source = (
        "def _foo(days):\n"
        "    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()\n"
        "    return cutoff\n"
    )
    matches = [m for m in _CUTOFF_PATTERN.finditer(source)]
    assert len(matches) == 1

    aliased_source = (
        "def _bar(days):\n"
        "    cutoff = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(days=days)).isoformat()\n"
        "    return cutoff\n"
    )
    aliased_matches = [m for m in _CUTOFF_PATTERN.finditer(aliased_source)]
    assert len(aliased_matches) == 1


def test_black_wrapped_multiline_cutoff_is_caught():
    """Regression for an opus-review finding on this guard's first version:
    black wraps a long cutoff expression across 3 lines (outer parens on
    their own lines), which the original `\\)\\)` (no whitespace tolerance)
    missed entirely -- a long retention-days constant name was all it took.
    Fixed via `\\)\\s*\\)`."""
    source = (
        "def _f():\n"
        "    cutoff = (\n"
        "        datetime.now(UTC) - timedelta(days=RETENTION_DAYS_FOR_THIS_TABLE)\n"
        "    ).isoformat()\n"
    )
    matches = list(_CUTOFF_PATTERN.finditer(source))
    assert len(matches) == 1


def test_date_suffix_variant_is_caught():
    """Regression: tracker.py's get_recent_city_correlations uses
    `.date().isoformat()` (deliberately, to match a date-only column) --
    the original pattern only matched a bare trailing `.isoformat()`."""
    source = (
        "def _f(days):\n"
        "    cutoff = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()\n"
    )
    matches = list(_CUTOFF_PATTERN.finditer(source))
    assert len(matches) == 1


def test_utc_today_base_variant_is_caught():
    """Regression: backtest.py's real cutoff uses `_utc_today()` (a local
    `from utils import utc_today as _utc_today` alias) instead of
    `datetime.now(...)` as the base -- both the bare-underscore-alias and
    dotted-module forms must be caught."""
    bare = "def _f(n):\n    cutoff = (_utc_today() - timedelta(days=n)).isoformat()\n"
    assert len(list(_CUTOFF_PATTERN.finditer(bare))) == 1

    dotted = (
        "def _f(n):\n    cutoff = (utils.utc_today() - timedelta(days=n)).isoformat()\n"
    )
    assert len(list(_CUTOFF_PATTERN.finditer(dotted))) == 1


def test_two_level_nested_call_args_are_caught():
    """Regression for an opus-review finding: a call argument with nested
    calls (e.g. `int(cfg("N"))`, `ZoneInfo("UTC")`) previously defeated the
    `[^()]*` argument match entirely. 2 levels of nesting are now tolerated
    (see _ARG and the module docstring's documented limit beyond that)."""
    source = (
        "def _f():\n"
        '    cutoff = (datetime.now(tz=ZoneInfo("UTC")) - '
        'timedelta(days=int(cfg("N")))).isoformat()\n'
    )
    matches = list(_CUTOFF_PATTERN.finditer(source))
    assert len(matches) == 1


def test_current_repo_matches_exactly_the_known_allowlisted_sites():
    """End-to-end sanity check: as of this guard's introduction, the repo
    has exactly the 5 known-safe sites and nothing else. Not a substitute
    for the two guard tests above (which are what actually protects against
    regressions) -- just documents the known-good baseline directly."""
    sites = {(rel, fname) for rel, _, fname in _iter_isoformat_cutoff_sites()}
    assert sites == set(_ISOFORMAT_CUTOFF_ALLOWLIST.keys())
