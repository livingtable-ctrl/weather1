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
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_SELF = Path(__file__)
_SAFE_IO = _REPO_ROOT / "safe_io.py"

# Matches os.replace( / _os.replace( as either a real call or a text
# mention in a comment/docstring -- see module docstring for why this
# doesn't try to distinguish the two.
_BARE_REPLACE_PATTERN = re.compile(r"\b_?os\.replace\(")

# Value is (expected match count, reason) -- keying on the exact count
# (not just "skip this file") means a new, unallowlisted occurrence in an
# already-allowlisted file still fails loudly, matching
# test_paths_bypass_guard.py's own _ALLOWLIST discipline.
_ALLOWLIST: dict[str, tuple[int, str]] = {
    "circuit_breaker.py": (
        1,
        "_load_state()'s own comment documents the READER-side precedent "
        "for this exact Windows behavior -- text mention, not a call.",
    ),
    "tests/test_p1_remaining.py": (
        1,
        "Docstring mentions os.replace() while describing "
        "circuit_breaker.py's reader-side PermissionError precedent -- "
        "text mention, not a call.",
    ),
    "tests/test_safe_io.py": (
        2,
        "Docstrings describing safe_io._replace_with_retry's own "
        "Windows PermissionError behavior -- text mentions, not calls "
        "(the actual mocked/real os.replace calls in this file target "
        "safe_io's own _replace_with_retry, not a bare call).",
    ),
    "tests/test_alerts.py": (
        2,
        "TestSaveRoutesThroughSafeIO's docstring/comment describe this "
        "guard's own backlog entry by name -- text mentions, not calls.",
    ),
    "tests/test_p9_p10.py": (
        2,
        "TestPersistenceRoutesThroughSafeIO's docstring/comment describe "
        "this guard's own backlog entry by name -- text mentions, not "
        "calls.",
    ),
    "tests/test_weather_markets.py": (
        2,
        "test_save_fails_open_when_atomic_write_raises' docstring/comment "
        "describe this guard's own backlog entry by name -- text "
        "mentions, not calls.",
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
    directly -- route through safe_io.atomic_write_json/atomic_write_text
    (or, for a payload shape those don't fit, safe_io._replace_with_retry)
    instead, so a Windows transient-PermissionError gets retried.

    Mutation check: reverting any one of this entry's 4 fixes (e.g.
    restoring tracker.py's old
    `_os.replace(tmp_name, _PINS_PATH)` in `_save_strategy_pins`) makes
    this test fail, since the regex matches the exact call each of those
    reverts would reintroduce.
    """
    offenders: dict[str, list[str]] = {}
    for path in _all_source_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        src = path.read_text(encoding="utf-8")
        matches = _BARE_REPLACE_PATTERN.findall(src)
        expected_count, _reason = _ALLOWLIST.get(rel, (0, ""))
        if len(matches) != expected_count:
            offenders[rel] = matches

    assert not offenders, (
        "Found a bare os.replace()/_os.replace() call (or an unallowlisted "
        "mention) outside safe_io.py, or an allowlisted file's match count "
        "changed -- route the write through safe_io.atomic_write_json/"
        "atomic_write_text instead, or document/update a real exception in "
        "_ALLOWLIST above:\n"
        + "\n".join(f"  {name}: {ms}" for name, ms in offenders.items())
    )


def test_allowlist_entries_still_exist_and_are_justified():
    """Every _ALLOWLIST entry must name a real file, a positive expected
    count, and a non-empty reason -- prevents a stale entry from silently
    masking a real regression."""
    for rel_path, (expected_count, reason) in _ALLOWLIST.items():
        assert (_REPO_ROOT / rel_path).is_file(), (
            f"_ALLOWLIST references {rel_path!r}, which doesn't exist"
        )
        assert expected_count > 0, (
            f"_ALLOWLIST entry for {rel_path!r} has a non-positive expected "
            "count -- remove the entry entirely instead of allowlisting "
            "zero occurrences"
        )
        assert reason.strip(), f"_ALLOWLIST entry for {rel_path!r} has no reason"
