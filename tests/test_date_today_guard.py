r"""Automated guard against new date.today() usage in production code
(backlog.txt "utils.utc_today() SAYS 'USE EVERYWHERE INSTEAD OF
date.today()' -- 17 SITES STILL DON'T").

utils.utc_today() exists specifically because date.today() reads the
server's local calendar, not UTC -- and every UTC-anchored quantity in this
codebase (target_date, market_date, days_out) is computed against
datetime.now(UTC). This project has been bitten by the mismatch more than
once: web_app.py's WA-timezone scar, a 2026-07-13 test failure from mixed
local/UTC fixtures, and (found during the 2026-07-18 audit that populated
this guard's allowlist) tracker.py's _fetch_previous_run_daily silently
using the wrong lead-time archive query on a server running ahead of UTC.

This scan is deliberately simple (regex over source text, matching
test_dead_code_scan.py's / test_disputed_row_guard.py's approach), and
scans every top-level production .py file rather than a fixed list --
the 2026-07-18 audit found real sites in 6 different files (tracker.py,
main.py, backtest.py, climate_indices.py, climatology.py, web_app.py), so
hardcoding a file list would just reproduce the "one gets missed" shape
this guard exists to prevent.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent

# function_name -> reason. Every function that calls date.today() (not
# utc_today()) must be listed here, or the guard test below fails. A new
# function landing here without a real reason is a signal worth a second
# look, not something to silently allowlist.
_DATE_TODAY_ALLOWLIST: dict[str, str] = {
    "backup_data": (
        "cloud_backup.py -- prunes local backup directories older than 30 "
        "days by parsing their date-named folder name; a local-vs-UTC "
        "off-by-one-day skew is immaterial against a 30-day retention "
        "window."
    ),
    "_check_prod_reminder": (
        "cron.py -- once-per-day informational log/alert reminder gated by "
        "a fixed threshold date, with its own idempotency check (compares "
        "against a persisted 'last checked' date string) that "
        "self-corrects if it fires more than once near a day boundary. A "
        "few hours of local-vs-UTC drift around midnight has no real "
        "consequence for a human-facing reminder."
    ),
}


_MASKED_TOKEN_TYPES = {tokenize.STRING, tokenize.COMMENT}
# Python 3.12+ tokenizes f-strings as FSTRING_START/MIDDLE/END instead of one
# STRING token -- FSTRING_MIDDLE (the literal text portions) is NOT
# tokenize.STRING, so it wouldn't be masked without this. Confirmed live:
# without these, a prose mention of "date.today()" inside an f-string's text
# (e.g. an f-string log message discussing the convention) is a false
# positive; getattr guards keep this working on older tokenize modules too.
for _fstring_tok_name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
    _tok_type = getattr(tokenize, _fstring_tok_name, None)
    if _tok_type is not None:
        _MASKED_TOKEN_TYPES.add(_tok_type)


def _code_only_lines(source: str) -> list[str]:
    """Return source lines with every STRING/COMMENT/f-string-text token
    blanked out (replaced with spaces, preserving column positions and line
    count), so a plain regex search never matches text inside a docstring,
    comment, or f-string -- including multi-line docstrings, where a naive
    "does this line start with # or \"\"\"" check misses interior lines
    entirely (found live: this guard's own first version flagged
    main.py:_feature_importance_days_out's explanatory docstring, which
    mentions "date.today()" as prose on an interior line that starts with
    neither marker)."""
    lines = source.splitlines(keepends=True)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenizeError, SyntaxError, IndentationError):
        # Fall back to unmasked lines rather than silently skipping the
        # whole file -- a tokenize failure on a real source file would be
        # surprising enough to want the guard to still try.
        return [line.rstrip("\n") for line in lines]

    for tok in tokens:
        if tok.type not in _MASKED_TOKEN_TYPES:
            continue
        (start_row, start_col), (end_row, end_col) = tok.start, tok.end
        if start_row == end_row:
            line = lines[start_row - 1]
            lines[start_row - 1] = (
                line[:start_col] + " " * (end_col - start_col) + line[end_col:]
            )
        else:
            for row in range(start_row, end_row + 1):
                line = lines[row - 1]
                col_start = start_col if row == start_row else 0
                col_end = end_col if row == end_row else len(line.rstrip("\n"))
                lines[row - 1] = (
                    line[:col_start] + " " * (col_end - col_start) + line[col_end:]
                )
    return [line.rstrip("\n") for line in lines]


def _iter_date_today_sites() -> list[tuple[Path, int, str]]:
    """Return (file, line_number, enclosing_function_name) for every
    date.today() call in top-level production .py files."""
    pattern = re.compile(r"(?<!\w)date\.today\(\)")
    sites = []
    for f in sorted(_REPO_ROOT.glob("*.py")):
        source = f.read_text(encoding="utf-8")
        raw_lines = source.splitlines()
        code_lines = _code_only_lines(source)
        func_starts: list[tuple[int, str]] = []
        for i, line in enumerate(raw_lines):
            m = re.match(r"^def (\w+)", line)
            if m:
                func_starts.append((i + 1, m.group(1)))

        def _func_for_line(lineno: int, _starts=func_starts) -> str | None:
            name = None
            for start, fname in _starts:
                if start <= lineno:
                    name = fname
                else:
                    break
            return name

        for i, line in enumerate(code_lines):
            lineno = i + 1
            if pattern.search(line):
                sites.append((f, lineno, _func_for_line(lineno)))
    return sites


def test_no_new_date_today_outside_allowlist():
    """Fails if a function calls date.today() without a documented reason
    in _DATE_TODAY_ALLOWLIST."""
    sites = _iter_date_today_sites()
    unexplained = [
        (f, lineno, fname)
        for f, lineno, fname in sites
        if fname is None or fname not in _DATE_TODAY_ALLOWLIST
    ]
    assert not unexplained, (
        "date.today() call(s) found with no entry in _DATE_TODAY_ALLOWLIST "
        "-- use utils.utc_today() instead (UTC-anchored, matches "
        "target_date/market_date/days_out everywhere else in this "
        "codebase), or add a documented reason if this one deliberately "
        "wants the local calendar:\n"
        + "\n".join(
            f"  - {f.name}:{lineno} ({fname})" for f, lineno, fname in unexplained
        )
    )


def test_date_today_allowlist_has_no_stale_entries():
    """Inverse check: every allowlisted function must still actually call
    date.today() (catches a rename, or a function later migrated to
    utc_today() without removing its now-stale allowlist entry)."""
    current_funcs = {fname for _, _, fname in _iter_date_today_sites() if fname}
    stale = [name for name in _DATE_TODAY_ALLOWLIST if name not in current_funcs]
    assert not stale, (
        f"Stale _DATE_TODAY_ALLOWLIST entries, function no longer calls "
        f"date.today(): {stale}"
    )


def test_docstring_mention_of_date_today_is_not_a_false_positive():
    """Regression: this guard's own first version flagged a false positive
    on main.py's _feature_importance_days_out, whose multi-line docstring
    explains the fix by name-dropping "date.today()" as prose on an
    interior line -- one that starts with neither "#" nor '\"\"\"', so a
    naive per-line prefix check missed it. Uses a synthetic in-memory
    source string (not a real repo file) so this test stays meaningful
    even if the real docstring's wording ever changes."""
    source = (
        "def _foo():\n"
        '    """Explains something.\n'
        "\n"
        "    Uses utc_today(), not date.today(): see backlog.txt.\n"
        '    """\n'
        "    # was date.today() before the fix\n"
        "    return 1\n"
    )
    code_lines = _code_only_lines(source)
    pattern = re.compile(r"(?<!\w)date\.today\(\)")
    matches = [i + 1 for i, line in enumerate(code_lines) if pattern.search(line)]
    assert matches == [], (
        f"docstring/comment text was not masked, found matches at lines {matches}"
    )


def test_fstring_prose_mention_is_not_a_false_positive():
    """Regression for an opus-review finding on this guard: Python 3.12+
    tokenizes f-strings as FSTRING_START/MIDDLE/END rather than one STRING
    token, and FSTRING_MIDDLE (the literal text portions) is NOT
    tokenize.STRING -- without explicitly masking it too, a log/error
    f-string that mentions "date.today()" as prose (plausible in this
    codebase given how often it discusses the convention) would false-
    positive, while a real f-string *call* (f"{date.today()}") must still
    be caught."""
    source = (
        'def _foo():\n    msg = f"see date.today() docs for {name}"\n    return msg\n'
    )
    code_lines = _code_only_lines(source)
    pattern = re.compile(r"(?<!\w)date\.today\(\)")
    matches = [i + 1 for i, line in enumerate(code_lines) if pattern.search(line)]
    assert matches == [], (
        f"f-string prose was not masked, found matches at lines {matches}"
    )


def test_fstring_real_call_is_still_caught():
    """The positive-case sibling to the above: a real date.today() call
    interpolated INTO an f-string must still be flagged."""
    source = 'def _foo():\n    msg = f"today is {date.today()}"\n    return msg\n'
    code_lines = _code_only_lines(source)
    pattern = re.compile(r"(?<!\w)date\.today\(\)")
    matches = [i + 1 for i, line in enumerate(code_lines) if pattern.search(line)]
    assert matches == [2], f"expected the real call on line 2, got {matches}"
