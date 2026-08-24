r"""Automated guard against the bare-os.replace() anti-pattern reappearing
outside safe_io.py.

backlog.txt "OTHER bare os.replace() CALL SITES OUTSIDE safe_io.py ALSO
EXPOSED TO THE SAME WINDOWS SHARING-VIOLATION FAILURE MODE" (resolved
2026-08-08, following on from the 2nd opus review round of the
hurricane_climatology.py HURDAT2 cache-write-isn't-atomic entry): a bare
`os.replace(src, dst)` call, unlike `safe_io.atomic_write_json`/
`atomic_write_text` (which retry via `safe_io._replace_with_retry`), can
raise a transient `PermissionError`/WinError 5 on Windows whenever another
thread/process has the destination file open for reading at the exact
wrong instant -- a real, 100%-reproducible failure mode this project's own
concurrent-writers test proved for the sibling HURDAT2 fix (POSIX
`rename()` has no such restriction). The 4 call sites this entry fixed
(tracker.py's `_save_strategy_pins`/`_save_retired_strategies`,
weather_markets.py's `save_learned_weights`, alerts.py's `_save`) were only
found via an ad-hoc repo-wide grep during that review -- this guard exists
so a 5th hand-rolled `mkstemp`/`NamedTemporaryFile` + `json.dump` +
`os.replace()` helper can't reappear silently.

This scan is deliberately simple (regex over source text), matching
test_paths_bypass_guard.py's / test_config_divergence_guard.py's own
approach -- including that approach's own disclosed limitation: this is a
source-text regex, not a static call graph, so a comment or docstring that
merely *mentions* `os.replace(` (there are several, describing this exact
failure mode) matches the pattern too, same as any real call would. Rather
than trying to distinguish code from prose (which a regex can't reliably
do), those known mentions are allowlisted below by exact match count, same
mechanism test_paths_bypass_guard.py uses -- a new, unallowlisted
occurrence anywhere (real call OR new comment) still fails loudly, and an
allowlisted file's count changing (up OR down) also fails loudly.

safe_io.py itself is excluded from the scan entirely (like paths.py is
excluded from its own bypass guard) -- it's the single legitimate call site
(`_replace_with_retry`, safe_io.py:60) other code should route through
instead of calling `os.replace()` directly.

AUD batch-25 item 4: this guard originally only matched the `os.replace(`/
`_os.replace(` function-call form, not the equivalent `some_path.replace(
dest)` METHOD form on a `pathlib.Path` object -- which is exactly what
web_app.py's `api_halt`/`api_override_set` used (`_tmp.replace(_KS_PATH)`),
so both slipped past this guard entirely despite being the identical
Windows sharing-violation failure mode.

First attempt (opus-review-caught) scoped the method-form scan to a regex
matching identifiers containing "tmp" (`\b\w*tmp\w*\.replace\(`), reasoned
as "every real atomic-rename call site in this codebase names its temp
variable with 'tmp' in it". That claim was false: `cron.py`'s log-rotation
call `log_path.replace(log_path.with_suffix(".log.1"))` is a real
Path.replace() rename on a file with guaranteed concurrent readers (a log
file) -- the exact shape this guard exists to catch -- and it slipped past
the tmp-name heuristic entirely, since neither operand is named with
"tmp". `cron.py` belonged to a different batch's file ownership at the
time (this batch owned cloud_backup.py/main.py/web_app.py/safe_io.py
only), so it was allowlisted below as a known, pre-existing gap rather
than fixed here -- but the guard itself needed to actually detect it, not
stay blind to it. Fixed by batch-33 (which does own cron.py): the call now
routes through `safe_io._replace_with_retry`, and the allowlist entry
below was removed since the guard no longer finds anything to allow.

The scan is now an AST check instead of a naming-convention regex:
`str.replace(old, new[, count])` always takes >= 2 positional arguments,
so ANY `<expr>.replace(<exactly one positional arg, no keywords>)` call is
unambiguously the `pathlib.Path.replace(target)` rename form, regardless
of what the receiver is named -- no false negatives from naming
convention, and (as a side effect of parsing real syntax instead of
scanning raw text) no false positives from a docstring merely mentioning
`foo.replace(bar)` in prose either, since that text never becomes an
`ast.Call` node. The original `_BARE_REPLACE_PATTERN` function-form scan
below is unchanged -- it's still a text regex (matching
test_paths_bypass_guard.py's established approach) and still needs the
text-mention allowlist entries for it specifically.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_SELF = Path(__file__)
_SAFE_IO = _REPO_ROOT / "safe_io.py"

# Matches os.replace( / _os.replace( as either a real call or a text
# mention in a comment/docstring -- see module docstring for why this
# doesn't try to distinguish the two.
_BARE_REPLACE_PATTERN = re.compile(r"\b_?os\.replace\(")


def _find_single_arg_replace_calls(source: str) -> list[str]:
    """AST-based scan for `<expr>.replace(<one positional arg>)` calls --
    the pathlib.Path.replace(target) rename form. See module docstring for
    why this replaced an earlier naming-convention regex. Returns one
    string per match (its line number) so callers can treat it the same
    way as a regex findall() result -- a count via len(), and something
    printable in a failure message.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return [
        f"line {node.lineno}: <expr>.replace(<1 arg>)"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "replace"
        and len(node.args) == 1
        and not node.keywords
    ]


# Value is (expected bare-function-form count, expected AST single-arg-
# method-form count, reason) -- keying on the exact count per DETECTOR
# (not just a combined total) means a new, unallowlisted occurrence in an
# already-allowlisted file still fails loudly even if it happens to net
# out to the same combined total another allowlisted change removed
# elsewhere in the same file (opus-review-round-2 L4: a single merged
# count could let "delete one docstring mention, add one real
# `x.replace(y)` call" pass silently since both detectors' counts would
# otherwise be summed into one number).
_ALLOWLIST: dict[str, tuple[int, int, str]] = {
    "circuit_breaker.py": (
        1,
        0,
        "_load_state()'s own comment documents the READER-side precedent "
        "for this exact Windows behavior -- text mention, not a call.",
    ),
    "tests/test_p1_remaining.py": (
        1,
        0,
        "Docstring mentions os.replace() while describing "
        "circuit_breaker.py's reader-side PermissionError precedent -- "
        "text mention, not a call.",
    ),
    "tests/test_safe_io.py": (
        2,
        0,
        "Docstrings describing safe_io._replace_with_retry's own "
        "Windows PermissionError behavior -- text mentions, not calls "
        "(the actual mocked/real os.replace calls in this file target "
        "safe_io's own _replace_with_retry, not a bare call).",
    ),
    "tests/test_alerts.py": (
        2,
        0,
        "TestSaveRoutesThroughSafeIO's docstring/comment describe this "
        "guard's own backlog entry by name -- text mentions, not calls.",
    ),
    "tests/test_p9_p10.py": (
        2,
        0,
        "TestPersistenceRoutesThroughSafeIO's docstring/comment describe "
        "this guard's own backlog entry by name -- text mentions, not "
        "calls.",
    ),
    "tests/test_weather_markets.py": (
        2,
        0,
        "test_save_fails_open_when_atomic_write_raises' docstring/comment "
        "describe this guard's own backlog entry by name -- text "
        "mentions, not calls.",
    ),
    "tests/test_cron_integration.py": (
        2,
        0,
        "TestKillSwitchOverrideRenameRace's docstring/comment describe the "
        "AUD-0039 fix (which routes through safe_io._replace_with_retry, "
        "not a bare call) by naming the old Path.rename()/os.replace() "
        "semantics gap it closed -- text mentions, not calls.",
    ),
}


def _all_source_files() -> list[Path]:
    result = []
    for p in _REPO_ROOT.rglob("*.py"):
        if not p.is_file() or p in (_SAFE_IO, _SELF):
            continue
        rel_parts = p.relative_to(_REPO_ROOT).parts
        if any(part.startswith(".") or part == "__pycache__" for part in rel_parts):
            continue
        result.append(p)
    return sorted(result)


def test_no_new_bare_os_replace_sites():
    """No *.py file outside safe_io.py should call os.replace()/_os.replace()
    (function form) or ANY single-argument `<expr>.replace(...)` (the
    pathlib.Path.replace(target) rename method form) directly -- route
    through safe_io.atomic_write_json/atomic_write_text (or, for a payload
    shape those don't fit, safe_io._replace_with_retry) instead, so a
    Windows transient-PermissionError gets retried.

    Mutation check: reverting any one of this entry's 4 function-form fixes
    (e.g. restoring tracker.py's old `_os.replace(tmp_name, _PINS_PATH)` in
    `_save_strategy_pins`) makes this test fail, since the regex matches
    the exact call each of those reverts would reintroduce. Same for the
    method-form fix (AUD batch-25 item 4): reverting web_app.py's
    `api_halt`/`api_override_set` to their old `_tmp.replace(_KS_PATH)` /
    `_tmp.replace(_ov_path)` calls makes this test fail via
    `_find_single_arg_replace_calls`'s AST scan.
    """
    offenders: dict[str, list[str]] = {}
    for path in _all_source_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        src = path.read_text(encoding="utf-8")
        bare_matches = _BARE_REPLACE_PATTERN.findall(src)
        ast_matches = _find_single_arg_replace_calls(src)
        expected_bare, expected_ast, _reason = _ALLOWLIST.get(rel, (0, 0, ""))
        if len(bare_matches) != expected_bare or len(ast_matches) != expected_ast:
            offenders[rel] = bare_matches + ast_matches

    assert not offenders, (
        "Found a bare os.replace()/_os.replace() call, a single-argument "
        "<expr>.replace(...) rename call, or an unallowlisted mention of "
        "the former, outside safe_io.py, or an allowlisted file's match "
        "count changed -- route the write through "
        "safe_io.atomic_write_json/atomic_write_text instead, or "
        "document/update a real exception in _ALLOWLIST above:\n"
        + "\n".join(f"  {name}: {ms}" for name, ms in offenders.items())
    )


def test_allowlist_entries_still_exist_and_are_justified():
    """Every _ALLOWLIST entry must name a real file, at least one positive
    expected count (bare-form or AST-form), and a non-empty reason --
    prevents a stale entry from silently masking a real regression."""
    for rel_path, (expected_bare, expected_ast, reason) in _ALLOWLIST.items():
        assert (_REPO_ROOT / rel_path).is_file(), (
            f"_ALLOWLIST references {rel_path!r}, which doesn't exist"
        )
        assert expected_bare > 0 or expected_ast > 0, (
            f"_ALLOWLIST entry for {rel_path!r} has no positive expected "
            "count in either detector -- remove the entry entirely instead "
            "of allowlisting zero occurrences"
        )
        assert reason.strip(), f"_ALLOWLIST entry for {rel_path!r} has no reason"
